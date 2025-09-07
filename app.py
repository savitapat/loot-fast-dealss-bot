# app.py
# Fixed so APScheduler + Flask both run

import os, re, time, random, asyncio, threading
from urllib.parse import urljoin
from dotenv import load_dotenv
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from apscheduler.schedulers.background import BackgroundScheduler
from telegram.ext import Application
from flask import Flask

# ---------- config ----------
load_dotenv(override=True)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

application = Application.builder().token(TELEGRAM_TOKEN).build()
bot = application.bot

AMZ_INTERVAL_MIN = 2   # low for testing
FK_INTERVAL_MIN = 3

HEADERS_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) Gecko/20100101 Firefox/125.0",
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
    print(f"Amazon scraped {len(items)} items")
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
    print(f"Flipkart scraped {len(items)} items")
    return items

# ---------- posting ----------
def post_deals(items):
    if not items:
        print("No deals found")
        return
    for it in items[:3]:  # limit to 3 for testing
        try:
            msg = (
                f"🧪 TEST DEAL\n\n"
                f"{it['source']} · {it['title']}\n"
                f"💰 Price: ₹{it['price']}\n\n"
                f"🔗 {it['link']}"
            )
            asyncio.run(bot.send_message(chat_id=CHANNEL_ID, text=msg, disable_web_page_preview=False))
            print("Posted:", it["title"])
            time.sleep(2)
        except Exception as e:
            print("[post error]", e)

# ---------- jobs ----------
def job_amazon():
    post_deals(scrape_amazon())

def job_flipkart():
    post_deals(scrape_flipkart())

# ---------- Flask ----------
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot running in TEST MODE ✅"

@app.route("/status")
def status():
    return {"mode": "test", "amazon_interval": AMZ_INTERVAL_MIN, "flipkart_interval": FK_INTERVAL_MIN}

# ---------- main ----------
def main():
    print("⚡ Bot starting in TEST MODE")
    asyncio.run(bot.send_message(chat_id=CHANNEL_ID, text="✅ Bot in TEST MODE - expect spam deals"))

    # Start scheduler
    sched = BackgroundScheduler()
    sched.add_job(job_amazon, "interval", minutes=AMZ_INTERVAL_MIN)
    sched.add_job(job_flipkart, "interval", minutes=FK_INTERVAL_MIN)
    sched.start()

    # Run Flask in separate thread
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)), debug=False, use_reloader=False)).start()

    # Keep alive
    while True:
        time.sleep(60)

if __name__ == "__main__":
    main()
