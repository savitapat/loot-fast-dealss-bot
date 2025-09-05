# Loot Fast Dealss bot main script
# app.py
# Loot Fast Dealss — 24/7 Telegram bot (Amazon + Flipkart) without affiliate APIs
# Educaational use. Scraping may break or be rate-limited; tune selectors/intervals as needed.

import os, re, time, math, random, sqlite3
from urllib.parse import urljoin
from datetime import datetime
from dotenv import load_dotenv

import requests
from bs4 import BeautifulSoup
from apscheduler.schedulers.background import BackgroundScheduler
from telegram.ext import Application
import telegram
from telegram import InputFile

# ---------- config ----------
# Load environment variables from a .env file for local development
load_dotenv(override=True)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

assert TELEGRAM_TOKEN, "Set TELEGRAM_TOKEN in environment"
assert CHANNEL_ID, "Set CHANNEL_ID in environment"

application = Application.builder().token(TELEGRAM_TOKEN).build()
bot = application.bot

# SQLite database for tracking posted deals
DB = "prices.db"

# thresholds (tune for your channel)
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

class Item:
    def __init__(self, product_id, title, url, mrp, price, image_url):
        self.product_id = product_id
        self.title = title
        self.url = url
        self.mrp = mrp
        self.price = price
        self.image_url = image_url
        self.prev_price = None

    def __repr__(self):
        return f"Item(id={self.product_id}, title='{self.title}', price={self.price})"

# ---------- db helpers ----------
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

def get_db_info(product_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT last_price, last_posted_at, last_message_id, prev_price, low_30d FROM prices WHERE product_id=?", (product_id,))
    res = c.fetchone()
    conn.close()
    return res

def mark_posted(product_id, price, message_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO prices (product_id, last_price, last_posted_at, last_message_id) VALUES (?, ?, ?, ?)",
              (product_id, price, int(time.time()), message_id))
    conn.commit()
    conn.close()

def update_prices(product_id, price, prev_price):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    # Update prev_price and low_30d
    c.execute("UPDATE prices SET prev_price=?, low_30d=COALESCE(MIN(low_30d,?),?) WHERE product_id=?",
              (prev_price, price, price, product_id))
    conn.commit()
    conn.close()

def min_price_30d(product_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    # For simplicity, we just fetch the stored low_30d
    c.execute("SELECT low_30d FROM prices WHERE product_id=?", (product_id,))
    res = c.fetchone()
    conn.close()
    return res[0] if res else None

def posted_recently(product_id, price):
    info = get_db_info(product_id)
    if info:
        last_price, last_posted_at, _, _, _ = info
        if abs(last_price - price) / last_price < 0.05: # if price hasn't changed much
            return (time.time() - last_posted_at) < (COOLDOWN_HOURS * 3600)
    return False

# ---------- scraping helpers ----------
def fetch_url(url):
    headers = {'User-Agent': random.choice(HEADERS_POOL)}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return None

def parse_price(text):
    if not text:
        return 0
    clean_text = re.sub(r'[^\d.]', '', text.replace(',', ''))
    try:
        return float(clean_text)
    except (ValueError, TypeError):
        return 0

# ---------- scrapers ----------
def scrape_amazon():
    print("Scraping Amazon...")
    url = "https://www.amazon.in/gp/goldbox/ref=nav_cs_gb_deal_oc?deals-widget=4d7547e1-b4ef-466d-8884-6e06827050a9"
    html_content = fetch_url(url)
    if not html_content:
        return []
    
    soup = BeautifulSoup(html_content, 'lxml')
    items = []
    
    # NOTE: These selectors are examples and might need to be updated.
    deals = soup.select('div.a-section.a-spacing-none.a-inline-block.a-span12.a-text-center')
    for deal in deals:
        try:
            link = deal.select_one('a.a-link-normal.a-text-normal')
            if not link: continue
            
            product_url = urljoin(url, link['href'])
            product_id_match = re.search(r'dp/(B[0-9A-Z]{9})', product_url) or re.search(r'dp/([A-Z0-9]{10})', product_url)
            if not product_id_match: continue
            
            product_id = product_id_match.group(1)
            title = deal.select_one('div.a-section.a-spacing-none.p13n-asin').get_text(strip=True)
            
            price_elem = deal.select_one('span.a-price-whole')
            price = parse_price(price_elem.get_text(strip=True)) if price_elem else 0
            
            mrp_elem = deal.select_one('span.a-price.a-text-price')
            mrp = parse_price(mrp_elem.get_text(strip=True)) if mrp_elem else price
            
            img_elem = deal.select_one('img')
            image_url = img_elem['src'] if img_elem else None
            
            if not price or not title: continue
            
            item = Item(f"amz_{product_id}", title, product_url, mrp, price, image_url)
            items.append(item)
            
        except Exception as e:
            print(f"Error parsing Amazon deal: {e}")
            continue

    print(f"Found {len(items)} Amazon deals.")
    return items

def scrape_flipkart():
    print("Scraping Flipkart...")
    url = "https://www.flipkart.com/tyy/store"
    html_content = fetch_url(url)
    if not html_content:
        return []

    soup = BeautifulSoup(html_content, 'lxml')
    items = []

    # NOTE: These selectors are examples and might need to be updated.
    deals = soup.select('div.WJ3Vvj')
    for deal in deals:
        try:
            link = deal.select_one('a._1LKq3p')
            if not link: continue
            
            product_url = urljoin(url, link['href'])
            product_id_match = re.search(r'pid=(.*?)(?:&|$)', product_url)
            if not product_id_match: continue

            product_id = product_id_match.group(1)
            title = deal.select_one('a._2QKfM8').get_text(strip=True)
            
            price_elem = deal.select_one('div._30jeq3')
            price = parse_price(price_elem.get_text(strip=True)) if price_elem else 0

            mrp_elem = deal.select_one('div._3I9_wc')
            mrp = parse_price(mrp_elem.get_text(strip=True)) if mrp_elem else price

            img_elem = deal.select_one('img._2r_T1I')
            image_url = img_elem['src'] if img_elem else None

            if not price or not title: continue

            item = Item(f"fk_{product_id}", title, product_url, mrp, price, image_url)
            items.append(item)

        except Exception as e:
            print(f"Error parsing Flipkart deal: {e}")
            continue

    print(f"Found {len(items)} Flipkart deals.")
    return items

# ---------- bot logic ----------
def pct(x, y):
    if y == 0:
        return 0
    return round((y - x) / y * 100, 2)

def compose_message(item, flags):
    msg = (
        f"🚨 **LOOT DEALS!** 🚨\n"
        f"**{item.title}**\n\n"
        f"🔥 Deal Price: ₹{item.price:.2f}\n"
    )

    if item.mrp > item.price:
        discount_pct = pct(item.price, item.mrp)
        msg += f"🏷️ MRP: ₹{item.mrp:.2f}\n"
        msg += f"📉 Discount: {discount_pct:.2f}%\n"

    if flags['month_low']:
        msg += f"🌟 All-time low price!\n"
    if flags['price_error']:
        msg += f"🚀 Sudden price drop!\n"

    msg += f"\n🔗 **[Grab the deal now!]({item.url})**\n\n"
    msg += f"#loot #deals #{item.product_id.split('_')[0]}"

    return msg

def process_and_post(items):
    bot.send_message(chat_id=CHANNEL_ID, text=f"Checking {len(items)} deals...", disable_web_page_preview=True)
    
    for it in items:
        pid = it.product_id
        info = get_db_info(pid)
        if info:
            it.prev_price = info[3]
            update_prices(pid, it.price, info[0])
        else:
            update_prices(pid, it.price, it.price)

        prev = it.prev_price
        price = it.price
        mrp = it.mrp

        price_error = False
        if prev and price < prev:
            drop = pct(price, prev)
            price_error = drop >= SUDDEN_DROP_PCT

        low30 = min_price_30d(pid)
        month_low = low30 is None or price <= low30
        big_discount = pct(price, mrp) >= BIG_DISCOUNT_PCT

        flags = {"price_error": price_error, "month_low": month_low, "big_discount": big_discount}

        if not (price_error or month_low or big_discount):
            continue
        if posted_recently(pid, price):
            continue

        msg = compose_message(it, flags)
        try:
            m = bot.send_message(chat_id=CHANNEL_ID, text=msg, disable_web_page_preview=False)
            mark_posted(pid, price, m.message_id)
            time.sleep(1.2)
        except telegram.error.TimedOut:
            print("[Telegram post error] Timed out, retrying...")
            time.sleep(2)
            try:
                m = bot.send_message(chat_id=CHANNEL_ID, text=msg, disable_web_page_preview=False)
                mark_posted(pid, price, m.message_id)
            except Exception as e:
                print(f"[Telegram post error] Failed again: {e}")
        except Exception as e:
            print(f"[Telegram post error] {e}")
            time.sleep(2)

# ---------- jobs ----------
def job_amazon():
    items = scrape_amazon()
    process_and_post(items)

def job_flipkart():
    items = scrape_flipkart()
    process_and_post(items)

# ---------- main ----------
def main():
    init_db()
    print("Loot Fast Dealss bot started ✨")
    sched = BackgroundScheduler()
    sched.add_job(job_flipkart, 'interval', minutes=FK_INTERVAL_MIN, id='flipkart')
    sched.add_job(job_amazon, 'interval', minutes=AMZ_INTERVAL_MIN, id='amazon')
    sched.start()
    
    # Keep the script running
    try:
        while True:
            time.sleep(2)
    except (KeyboardInterrupt, SystemExit):
        sched.shutdown()
        
if __name__ == '__main__':
    main()
