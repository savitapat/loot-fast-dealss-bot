# app.py
# Loot Fast Dealss bot with Flask + Telegram + Scheduler
# Deployable on Render

import os, re, time, random, sqlite3
from urllib.parse import urljoin
from dotenv import load_dotenv

import requests
from bs4 import BeautifulSoup
from apscheduler.schedulers.background import BackgroundScheduler
from telegram.ext import Application
from flask import Flask

# ---------- config ----------
load_dotenv(override=True)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

assert TELEGRAM_TOKEN, "❌ TELEGRAM_TOKEN missing in environment"
assert CHANNEL_ID, "❌ CHANNEL_ID missing in environment"

application = Application.builder().token(TELEGRAM_TOKEN).build()
bot = application.bot

DB = "prices.db"

BIG_DISCOUNT_PCT = 55
SUDDEN_DROP_PCT = 50
COOLDOWN_HOURS = 12
AMZ_INTERVAL_MIN = 15
FK_INTERVAL_MIN = 10

HEADERS_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15"
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

# ---------- helpers ----------
def fetch_url(url):
    headers = {"User-Agent": random.choice(HEADERS_POOL)}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"[fetch error] {url}: {e}")
        return None

def parse_price(txt):
    if not txt:
        return 0
    clean = re.sub(r"[^\d]", "", txt)
    try:
        return int(clean)
    except:
        return 0

def pct(curr, base):
    if not base:
        return 0
    return round((1 - curr / base) * 100, 1)

# ---------- scrapers ----------
def scrape_amazon():
    print("🔎 Scraping Amazon deals...")
    url = "https://www.amazon.in/gp/goldbox"
    html = fetch_url(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    items = []
    for c in soup.select('div[data-component-type="s-deal-card"]'):
        try:
            a = c.select_one('a[href*="/dp/"]')
            if not a:
                continue
            link = urljoin(url, a["href"].split("?")[0])
            title = a.get_text(strip=True)[:100]
            price_el = c.select_one("span.a-price-whole")
            mrp_el = c.select_one("span.a-text-strike")
            price = parse_price(price_el.get_text()) if price_el else 0
            mrp = parse_price(mrp_el.get_text()) if mrp_el else price
            if not price or not title:
                continue
            items.append({"title": title, "link": link, "price": price, "mrp": mrp, "source": "Amazon"})
        except Exception as e:
            print("Amazon parse error:", e)
            continue
    print(f"✅ Found {len(items)} Amazon items")
    return items

def scrape_flipkart():
    print("🔎 Scraping Flipkart deals...")
    url = "https://www.flipkart.com/offers"
    html = fetch_url(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    items = []
    for c in soup.select("a[href*='/p/']"):
        try:
            link = urljoin(url, c["href"].split("?")[0])
            title = c.get_text(strip=True)[:100]
            parent = c.find_parent()
            block = parent.get_text(" ", strip=True) if parent else ""
            price = parse_price(block)
            if not price or not title:
                continue
            items.append({"title": title, "link": link, "price": price, "mrp": price, "source": "Flipkart"})
        except Exception as e:
            print("Flipkart parse error:", e)
            continue
    print(f"✅ Found {len(items)} Flipkart items")
    return items

# ---------- posting ----------
def post_deals(items):
    for it in items:
        try:
            discount = pct(it["price"], it.get("mrp", it["price"]))
            if discount < BIG_DISCOUNT_PCT:
                continue
            msg = (
                f"🔥 *{it['source']} Deal*\n\n"
                f"{it['title']}\n"
                f"💰 Price: ₹{it['price']} (↓{discount}% off)\n\n"
                f"🔗 {it['link']}"
            )
            bot.send_message(chat_id=CHANNEL_ID, text=msg, parse_mode="Markdown", disable_web_page_preview=False)
            print(f"✅ Posted deal: {it['title']}")
            time.sleep(2)
        except Exception as e:
            print(f"[Telegram post error] {e}")
            time.sleep(2)

# ---------- jobs ----------
def job_amazon():
    items = scrape_amazon()
    post_deals(items)

def job_flipkart():
    items = scrape_flipkart()
    post_deals(items)

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
    print("⚡ Loot Fast Dealss bot starting...")

    # Startup test message
    try:
        print("📨 Trying to send startup message...")
        bot.send_message(chat_id=CHANNEL_ID, text="✅ Bot deployed and running on Render!")
        print("✅ Startup message sent to Telegram channel")
    except Exception as e:
        print(f"❌ Failed to send startup message: {e}")

    # Scheduler
    sched = BackgroundScheduler()
    sched.add_job(job_flipkart, "interval", minutes=FK_INTERVAL_MIN, id="flipkart")
    sched.add_job(job_amazon, "interval", minutes=AMZ_INTERVAL_MIN, id="amazon")
    sched.start()

    print("🌍 Starting Flask server...")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)), debug=False)

if __name__ == "__main__":
    main()
