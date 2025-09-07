# app.py – Loot Fast Dealss Bot (Fixed Async Version)
import os, re, time, random, sqlite3, asyncio
from datetime import datetime
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify
from threading import Thread
from dotenv import load_dotenv
from telegram import Bot
from telegram.error import TelegramError

# ---------------- CONFIG ----------------
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
TEST_MODE = os.getenv("TEST_MODE", "false").lower() == "true"
AFFILIATE_TAG = os.getenv("AFFILIATE_TAG", "lootfastdeals-21")

if not BOT_TOKEN or not CHANNEL_ID:
    raise ValueError("❌ TELEGRAM_TOKEN or CHANNEL_ID not set in environment!")

# Initialize bot with async support
bot = Bot(BOT_TOKEN)
app = Flask(__name__)

DB = "deals.db"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

# PREMIUM DEAL SOURCES
PREMIUM_DEAL_URLS = [
    "https://www.amazon.in/deals",
    "https://www.amazon.in/gp/goldbox",
    "https://www.flipkart.com/offers/deals-of-the-day",
    "https://www.flipkart.com/offers/supercoin-zone",
]

# ---------------- DB INIT ----------------
def init_db():
    with sqlite3.connect(DB) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS posts (
            pid TEXT PRIMARY KEY,
            ts INTEGER,
            price INTEGER,
            discount INTEGER,
            title TEXT
        )""")

def posted_recently(pid, hours=6):
    cutoff = int(time.time()) - hours * 3600
    with sqlite3.connect(DB) as c:
        row = c.execute("SELECT 1 FROM posts WHERE pid=? AND ts>=?", (pid, cutoff)).fetchone()
    return bool(row)

def mark_posted(pid, price, discount, title):
    with sqlite3.connect(DB) as c:
        c.execute("INSERT OR REPLACE INTO posts VALUES (?,?,?,?,?)",
                  (pid, int(time.time()), price, discount, title))

# ---------------- HELPERS ----------------
def fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        return r.text if r.status_code == 200 else ""
    except Exception as e:
        print(f"❌ Fetch failed: {e}")
        return ""

def parse_price(text):
    if not text: return None
    text = re.sub(r"[^\d]", "", text)
    return int(text) if text.isdigit() and len(text) > 2 else None

def add_affiliate_tag(url):
    if AFFILIATE_TAG and "amazon.in" in url and "tag=" not in url:
        return f"{url}{'&' if '?' in url else '?'}tag={AFFILIATE_TAG}"
    return url

# ---------------- ASYNC TELEGRAM FUNCTIONS ----------------
async def send_telegram_message(message):
    """Async function to send Telegram message"""
    try:
        await bot.send_message(
            chat_id=CHANNEL_ID,
            text=message,
            disable_web_page_preview=False
        )
        return True
    except TelegramError as e:
        print(f"❌ Telegram error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

def sync_send_message(message):
    """Synchronous wrapper for async Telegram send"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(send_telegram_message(message))
        loop.close()
        return result
    except Exception as e:
        print(f"❌ Async loop error: {e}")
        return False

# ---------------- SCRAPERS ----------------
def scrape_amazon_deals():
    items = []
    print("🔍 Scanning Amazon deals...")
    
    for url in [u for u in PREMIUM_DEAL_URLS if "amazon" in u]:
        html = fetch(url)
        if not html: continue
        
        soup = BeautifulSoup(html, "lxml")
        
        # Amazon deal selectors
        cards = soup.select('[data-testid="deal-card"], .deal-tile, .a-section')
        for card in cards[:10]:  # Limit to first 10
            try:
                link_elem = card.select_one('a[href*="/deal/"], a[href*="/dp/"]')
                if not link_elem: continue
                
                link = urljoin("https://www.amazon.in", link_elem["href"])
                link = add_affiliate_tag(link.split('?')[0])
                
                title_elem = card.select_one('h2, .a-text-normal')
                title = title_elem.get_text(strip=True)[:80] if title_elem else "Amazon Deal"
                
                # Price
                price_elem = card.select_one('.a-price-whole, .a-price .a-offscreen')
                price = parse_price(price_elem.get_text()) if price_elem else None
                if not price: continue
                
                pid = f"amz_{hash(link)}"
                items.append((pid, "Amazon", title, link, price, 0))
                
            except Exception as e:
                continue
    
    print(f"✅ Found {len(items)} Amazon deals")
    return items

def scrape_flipkart_deals():
    items = []
    print("🔍 Scanning Flipkart deals...")
    
    for url in [u for u in PREMIUM_DEAL_URLS if "flipkart" in u]:
        html = fetch(url)
        if not html: continue
        
        soup = BeautifulSoup(html, "lxml")
        
        # Flipkart deal selectors
        cards = soup.select('a._1fQZEK, a._2UzuFa, a.CGtCQZ')
        for card in cards[:10]:  # Limit to first 10
            try:
                href = card.get("href")
                if not href: continue
                
                link = urljoin("https://www.flipkart.com", href.split('?')[0])
                
                title_elem = card.select_one('._4rR01T, .s1Q9rs')
                title = title_elem.get_text(strip=True)[:80] if title_elem else "Flipkart Deal"
                
                price_elem = card.select_one('._30jeq3, ._1_WHN1')
                price = parse_price(price_elem.get_text()) if price_elem else None
                if not price: continue
                
                pid = f"fk_{hash(link)}"
                items.append((pid, "Flipkart", title, link, price, 0))
                
            except Exception as e:
                continue
    
    print(f"✅ Found {len(items)} Flipkart deals")
    return items

# ---------------- POSTING ----------------
def compose_message(item):
    pid, platform, title, link, price, discount = item
    return f"🔥 {platform} DEAL\n\n{title}\n\n💰 Price: ₹{price:,}\n\n👉 {link}"

def post_deals():
    print("🔄 Starting deal scan...")
    amazon_deals = scrape_amazon_deals()
    flipkart_deals = scrape_flipkart_deals()
    all_deals = amazon_deals + flipkart_deals
    
    posted_count = 0
    for deal in all_deals:
        pid, platform, title, link, price, discount = deal
        
        if posted_recently(pid):
            continue
            
        message = compose_message(deal)
        if sync_send_message(message):
            mark_posted(pid, price, discount, title)
            print(f"📢 Posted: {title[:50]}...")
            posted_count += 1
            time.sleep(2)
    
    return posted_count, all_deals

# ---------------- MAIN LOOP ----------------
last_post = {"text": None, "time": None, "count": 0}

def deal_loop():
    global last_post
    while True:
        try:
            if TEST_MODE:
                print("🧪 TEST MODE: Scanning...")
                posted_count, all_deals = post_deals()
                msg = f"🧪 TEST: Found {len(all_deals)} deals, posted {posted_count}"
                
                if sync_send_message(msg):
                    last_post = {"text": msg, "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "count": posted_count}
                    print("📢 Posted TEST message")
                
            else:
                posted_count, all_deals = post_deals()
                if posted_count > 0:
                    last_post = {
                        "text": f"Posted {posted_count} new deals",
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "count": posted_count
                    }
                else:
                    last_post = {
                        "text": "No new deals found",
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "count": 0
                    }
            
            wait_time = 300 if TEST_MODE else 1800
            print(f"⏰ Next scan in {wait_time//60} minutes...")
            time.sleep(wait_time)
            
        except Exception as e:
            print(f"❌ Loop error: {e}")
            time.sleep(300)

# ---------------- FLASK ROUTES ----------------
@app.route("/")
def home():
    return "Loot Fast Dealss Bot ✅ Running"

@app.route("/status")
def status():
    return jsonify(last_post)

@app.route("/scan")
def scan():
    posted_count, all_deals = post_deals()
    return jsonify({
        "posted": posted_count,
        "found": len(all_deals),
        "status": "success"
    })

# ---------------- MAIN ----------------
def main():
    print("🤖 Starting Deal Bot")
    print(f"Channel: {CHANNEL_ID}")
    print(f"Mode: {'TEST' if TEST_MODE else 'LIVE'}")
    
    init_db()
    
    # Send startup message
    startup_msg = "✅ Deal Bot Started! Ready to find deals..."
    if sync_send_message(startup_msg):
        print("✅ Startup message sent")
    else:
        print("❌ Startup message failed")
    
    # Start background thread
    t = Thread(target=deal_loop, daemon=True)
    t.start()
    print("✅ Background scanner started")
    
    # Start Flask
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)

if __name__ == "__main__":
    main()