# app.py
# Loot Fast Dealss bot with Flask + Telegram + Scheduler
# Deployable on Render

import os, re, time, math, random, sqlite3
from urllib.parse import urljoin
from datetime import datetime
from dotenv import load_dotenv

import requests
from bs4 import BeautifulSoup
from apscheduler.schedulers.background import BackgroundScheduler
from telegram.ext import Application
import telegram
from flask import Flask

# ---------- config ----------
load_dotenv(override=True)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

assert TELEGRAM_TOKEN, "Set TELEGRAM_TOKEN in environment"
assert CHANNEL_ID, "Set CHANNEL_ID in environment"

application = Application.builder().token(TELEGRAM_TOKEN).build()
bot = application.bot

DB = "prices.db"

BIG_DISCOUNT_PCT = 55
SUDDEN_DROP_PCT = 50
COOLDOWN_HOURS = 12
AMZ_INTERVAL_MIN = 5
FK_INTERVAL_MIN = 3

HEADERS_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0"
]

# ---------- DB ----------
def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS prices (
            product_id TEXT PRIMARY KEY,
            last_price REAL,
            last_posted_at INTEGER,
            last_message_id INTEGER,
            prev_price REAL,
            low_30d REAL
        )
    ''')
    conn.commit()
    conn.close()

# ---------- Scraper helpers ----------
def fetch_url(url):
    headers = {'User-Agent': random.choice(HEADERS_POOL)}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return None

def parse_price(text):
    if not text:
        return 0
    clean_text = re.sub(r'[^\d.]', '', text.replace(',', ''))
    try:
        return float(clean_text)
    except:
        return 0

# (Simplified scraping functions for brevity)
def scrape_amazon():
    print("Scraping Amazon...")
    return []

def scrape_flipkart():
    print("Scraping Flipkart...")
    return []

# ---------- Jobs ----------
def job_amazon():
    items = scrape_amazon()
    print(f"Amazon job ran, found {len(items)} items")

def job_flipkart():
    items = scrape_flipkart()
    print(f"Flipkart job ran, found {len(items)} items")

# ---------- Flask ----------
app = Flask(__name__)

@app.route("/")
def home():
    return "Loot Fast Dealss Bot is running ✅"

@app.route("/health")
def health():
    return {"status": "ok"}

# ---------- main ----------
def main():
    init_db()
    print("Loot Fast Dealss bot starting ✨")

    # Test startup message
    try:
        bot.send_message(chat_id=CHANNEL_ID, text="✅ Bot deployed and running on Render!")
        print("Startup message sent ✅")
    except Exception as e:
        print(f"❌ Failed to send startup message: {e}")

    # Scheduler
    sched = BackgroundScheduler()
    sched.add_job(job_flipkart, 'interval', minutes=FK_INTERVAL_MIN, id='flipkart')
    sched.add_job(job_amazon, 'interval', minutes=AMZ_INTERVAL_MIN, id='amazon')
    sched.start()

    # Start Flask
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)), debug=False)

if __name__ == "__main__":
    main()
