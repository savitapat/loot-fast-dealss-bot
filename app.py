# app.py – Loot Fast Dealss Bot
import os, re, time, random, sqlite3
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify
from threading import Thread
from dotenv import load_dotenv
from telegram import Bot

# ---------------- CONFIG ----------------
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
TEST_MODE = os.getenv("TEST_MODE", "true").lower() == "true"

if not BOT_TOKEN or not CHANNEL_ID:
    raise ValueError("❌ TELEGRAM_TOKEN or CHANNEL_ID not set in environment!")

bot = Bot(BOT_TOKEN)
app = Flask(__name__)

DB = "deals.db"
HEADERS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

AMAZON_URLS = [
    "https://www.amazon.in/gp/goldbox",
    "https://www.amazon.in/deals",
]
FLIPKART_URLS = [
    "https://www.flipkart.com/offers",
    "https://www.flipkart.com/deals-of-the-day",
]

# ---------------- DB INIT ----------------
def init_db():
    with sqlite3.connect(DB) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS posts (
            pid TEXT PRIMARY KEY,
            ts INTEGER,
            price INTEGER
        )""")

def posted_recently(pid, price, hours=12):
    cutoff = int(time.time()) - hours * 3600
    with sqlite3.connect(DB) as c:
        row = c.execute("SELECT 1 FROM posts WHERE pid=? AND price=? AND ts>=?",
                        (pid, price, cutoff)).fetchone()
    return bool(row)

def mark_posted(pid, price):
    with sqlite3.connect(DB) as c:
        c.execute("INSERT OR REPLACE INTO posts VALUES (?,?,?)",
                  (pid, int(time.time()), price))

# ---------------- HELPERS ----------------
def fetch(url):
    try:
        r = requests.get(url, headers={"User-Agent": random.choice(HEADERS)}, timeout=20)
        if r.status_code == 200:
            return r.text
    except Exception as e:
        print(f"❌ Fetch failed {url}: {e}")
    return ""

def parse_price(text):
    if not text:
        return None
    text = re.sub(r"[^\d]", "", text)
    return int(text) if text.isdigit() else None

# ---------------- SCRAPERS ----------------
def scrape_amazon():
    items = []
    for url in AMAZON_URLS:
        html = fetch(url)
        if not html: continue
        soup = BeautifulSoup(html, "lxml")
        cards = soup.select('div[data-component-type="s-deal-card"], div[data-component-type="s-search-result"]')
        for c in cards:
            a = c.select_one('a[href*="/dp/"]')
            if not a: continue
            link = urljoin(url, a["href"].split("?")[0])
            title = (c.select_one("span.a-text-normal") or a).get_text(strip=True)
            price = parse_price("".join(x.get_text() for x in c.select("span.a-price-whole")))
            if not price: continue
            pid = f"amz_{hash(link)}"
            items.append((pid, "Amazon", title, link, price))
    print(f"✅ Scraped {len(items)} Amazon items")
    return items

def scrape_flipkart():
    items = []
    for url in FLIPKART_URLS:
        html = fetch(url)
        if not html: continue
        soup = BeautifulSoup(html, "lxml")
        cards = soup.select("a._1fQZEK, a.s1Q9rs, a._2UzuFa, a._2rpwqI")
        for a in cards:
            href = a.get("href")
            if not href: continue
            link = urljoin("https://www.flipkart.com", href.split("?")[0])
            title = a.get("title") or a.get_text(strip=True)
            parent = a.find_parent()
            price = None
            if parent:
                price = parse_price(parent.get_text(" ", strip=True))
            if not price: continue
            pid = f"fk_{hash(link)}"
            items.append((pid, "Flipkart", title, link, price))
    print(f"✅ Scraped {len(items)} Flipkart items")
    return items

# ---------------- POSTING ----------------
def compose(item):
    pid, src, title, link, price = item
    return f"🔥 {src} Deal\n{title}\n💰 Price: ₹{price}\n👉 {link}"

def process_and_post(items):
    for pid, src, title, link, price in items:
        if posted_recently(pid, price): continue
        msg = compose((pid, src, title, link, price))
        try:
            bot.send_message(chat_id=CHANNEL_ID, text=msg, disable_web_page_preview=False)
            mark_posted(pid, price)
            print(f"📢 Posted: {title[:50]}")
            time.sleep(1.5)
        except Exception as e:
            print(f"❌ Telegram post error: {e}")

# ---------------- LOOP ----------------
last_post = {"text": None, "time": None}

def deal_loop():
    global last_post
    while True:
        try:
            if TEST_MODE:
                samples = [
                    "🔥 Sample Deal – iPhone 15 Pro only ₹9999 (Testing)",
                    "💥 Flash Sale – 80% OFF on Headphones (Testing)",
                    "⚡ Price Drop – Laptop ₹15,000 (Testing)",
                    "🎉 Loot Offer – Smartwatch ₹499 (Testing)"
                ]
                msg = random.choice(samples)
                bot.send_message(chat_id=CHANNEL_ID, text=msg)
                last_post = {"text": msg, "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                print("📢 Posted FAKE deal")
            else:
                amz = scrape_amazon()
                fk = scrape_flipkart()
                all_items = amz + fk
                process_and_post(all_items)
                if all_items:
                    last_post = {"text": all_items[0][2], "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            time.sleep(60)  # every 1 min for testing
        except Exception as e:
            print(f"❌ Loop error: {e}")
            time.sleep(10)

# ---------------- FLASK ----------------
@app.route("/")
def home():
    return "Loot Fast Dealss Bot ✅ Running"

@app.route("/status")
def status():
    return jsonify(last_post)

# ---------------- MAIN ----------------
def main():
    print(f"BOT_TOKEN from env = {BOT_TOKEN}")
    print(f"CHANNEL_ID from env = {CHANNEL_ID}")
    print("⚡ Bot starting in THREAD MODE (Fake Deals)" if TEST_MODE else "⚡ Bot starting in THREAD MODE (REAL Scraping)")

    init_db()
    try:
        bot.send_message(chat_id=CHANNEL_ID, text="✅ Bot deployed and running!")
        print("✅ Startup message sent")
    except Exception as e:
        print(f"❌ Failed to send startup message: {e}")

    t = Thread(target=deal_loop, daemon=True)
    t.start()
    print("✅ Background deal loop started")

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)), debug=False)

if __name__ == "__main__":
    main()
