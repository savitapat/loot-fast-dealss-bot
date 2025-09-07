# app.py
import os, re, time, random, threading
from urllib.parse import urljoin
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from telegram.ext import Application
from flask import Flask

# ---------- config ----------
load_dotenv(override=True)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

application = Application.builder().token(TELEGRAM_TOKEN).build()
bot = application.bot

# run every N seconds (for testing)
AMZ_INTERVAL = 120   # 2 min
FK_INTERVAL = 60     # 1 min
LAST_AMZ, LAST_FK = 0, 0

HEADERS_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15"
]

# ---------- helpers ----------
def fetch_url(url):
    try:
        r = requests.get(url, headers={"User-Agent": random.choice(HEADERS_POOL)}, timeout=15)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print("[fetch error]", url, e)
        return None

def parse_price(txt):
    clean = re.sub(r"[^\d]", "", txt or "")
    return int(clean) if clean else 0

# ---------- scrapers ----------
def scrape_amazon():
    url = "https://www.amazon.in/gp/goldbox"
    html = fetch_url(url)
    if not html: return []
    soup = BeautifulSoup(html, "lxml")
    items = []
    for a in soup.select("a[href*='/dp/']"):
        link = urljoin(url, a["href"].split("?")[0])
        title = a.get_text(strip=True)[:120]
        block = a.find_parent().get_text(" ", strip=True) if a.find_parent() else ""
        price = parse_price(block)
        if title and price:
            items.append({"title": title, "link": link, "price": price, "source": "Amazon"})
    print(f"[Amazon] scraped {len(items)} items")
    return items

def scrape_flipkart():
    url = "https://www.flipkart.com/offers"
    html = fetch_url(url)
    if not html: return []
    soup = BeautifulSoup(html, "lxml")
    items = []
    for a in soup.select("a[href*='/p/']"):
        link = urljoin(url, a["href"].split("?")[0])
        title = a.get_text(strip=True)[:120]
        block = a.find_parent().get_text(" ", strip=True) if a.find_parent() else ""
        price = parse_price(block)
        if title and price:
            items.append({"title": title, "link": link, "price": price, "source": "Flipkart"})
    print(f"[Flipkart] scraped {len(items)} items")
    return items

# ---------- posting ----------
def post_deals(items, src):
    if not items:
        print(f"[{src}] no deals found")
        return
    for it in items[:2]:  # only 2 per cycle
        try:
            msg = (
                f"🧪 TEST DEAL\n\n"
                f"{it['source']} · {it['title']}\n"
                f"💰 Price: ₹{it['price']}\n\n"
                f"🔗 {it['link']}"
            )
            # synchronous send via asyncio runner
            import asyncio
            asyncio.run(bot.send_message(chat_id=CHANNEL_ID, text=msg, disable_web_page_preview=False))
            print(f"[{src}] posted: {it['title'][:40]}")
            time.sleep(2)
        except Exception as e:
            print(f"[{src}] post error", e)

# ---------- background loop ----------
def deal_loop():
    global LAST_AMZ, LAST_FK
    print("✅ Background deal loop started")
    while True:
        now = time.time()
        if now - LAST_FK >= FK_INTERVAL:
            print(">> Flipkart job fired")
            post_deals(scrape_flipkart(), "Flipkart")
            LAST_FK = now
        if now - LAST_AMZ >= AMZ_INTERVAL:
            print(">> Amazon job fired")
            post_deals(scrape_amazon(), "Amazon")
            LAST_AMZ = now
        time.sleep(10)  # heartbeat every 10s

# ---------- Flask ----------
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot running ✅"

@app.route("/status")
def status():
    return {
        "last_amazon": datetime.fromtimestamp(LAST_AMZ).strftime("%H:%M:%S") if LAST_AMZ else "never",
        "last_flipkart": datetime.fromtimestamp(LAST_FK).strftime("%H:%M:%S") if LAST_FK else "never",
        "now": datetime.now().strftime("%H:%M:%S")
    }

# ---------- main ----------
def main():
    print("⚡ Bot starting in THREAD MODE")
    try:
        import asyncio
        asyncio.run(bot.send_message(chat_id=CHANNEL_ID, text="✅ Bot running in THREAD MODE - deals every 1 min"))
    except Exception as e:
        print("Startup send failed:", e)

    # start background thread
    t = threading.Thread(target=deal_loop, daemon=True)
    t.start()

    # run Flask server (foreground)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)), debug=False, use_reloader=False)

if __name__ == "__main__":
    main()
