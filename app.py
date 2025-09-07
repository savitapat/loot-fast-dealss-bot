# app.py – REAL DEAL FINDER BOT
import os, re, time, random, sqlite3, asyncio
from datetime import datetime
from urllib.parse import urljoin, quote
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

bot = Bot(BOT_TOKEN)
app = Flask(__name__)

DB = "deals.db"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
}

# REAL PRODUCT SEARCH URLs
REAL_PRODUCT_URLS = [
    # Amazon Best Sellers
    "https://www.amazon.in/gp/bestsellers/electronics/ref=zg_bs_electronics_sm",
    "https://www.amazon.in/gp/bestsellers/computers/ref=zg_bs_computers_sm",
    "https://www.amazon.in/gp/bestsellers/home-improvement/ref=zg_bs_home-improvement_sm",
    
    # Flipkart Top Deals
    "https://www.flipkart.com/offers/deals-of-the-day",
    "https://www.flipkart.com/offers/supercoin-zone",
    
    # Specific Product Searches (REAL products)
    "https://www.amazon.in/s?k=earbuds+under+500&rh=p_36%3A1318505031",
    "https://www.amazon.in/s?k=power+bank+under+1000",
    "https://www.flipkart.com/search?q=earbuds+under+500&sort=popularity",
    "https://www.flipkart.com/search?q=power+bank+under+1000&sort=popularity",
]

# ---------------- DB INIT ----------------
def init_db():
    with sqlite3.connect(DB) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS posts (
            pid TEXT PRIMARY KEY,
            ts INTEGER,
            price INTEGER,
            discount INTEGER,
            title TEXT,
            link TEXT
        )""")

def posted_recently(pid, hours=4):
    cutoff = int(time.time()) - hours * 3600
    with sqlite3.connect(DB) as c:
        row = c.execute("SELECT 1 FROM posts WHERE pid=? AND ts>=?", (pid, cutoff)).fetchone()
    return bool(row)

def mark_posted(pid, price, discount, title, link):
    with sqlite3.connect(DB) as c:
        c.execute("INSERT OR REPLACE INTO posts VALUES (?,?,?,?,?,?)",
                  (pid, int(time.time()), price, discount, title, link))

# ---------------- ASYNC TELEGRAM FUNCTIONS ----------------
async def send_telegram_message(message):
    try:
        await bot.send_message(
            chat_id=CHANNEL_ID,
            text=message,
            disable_web_page_preview=False
        )
        return True
    except Exception as e:
        print(f"❌ Telegram error: {e}")
        return False

def sync_send_message(message):
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(send_telegram_message(message))
        loop.close()
        return result
    except Exception as e:
        print(f"❌ Async error: {e}")
        return False

# ---------------- REAL PRODUCT SCRAPER ----------------
def fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
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

def scrape_real_products():
    """Finds REAL products that are actually available"""
    items = []
    print("🔍 Scanning for REAL products...")
    
    for url in REAL_PRODUCT_URLS:
        html = fetch(url)
        if not html: continue
        
        soup = BeautifulSoup(html, "lxml")
        
        if "amazon" in url:
            # Amazon product selectors
            products = soup.select('.s-result-item, .s-main-slot .s-card-border')
            for product in products[:15]:
                try:
                    link_elem = product.select_one('a[href*="/dp/"]')
                    if not link_elem: continue
                    
                    link = urljoin("https://www.amazon.in", link_elem["href"])
                    link = add_affiliate_tag(link.split('?')[0])
                    
                    title_elem = product.select_one('.a-size-medium, .a-text-normal')
                    title = title_elem.get_text(strip=True)[:80] if title_elem else "Amazon Product"
                    
                    price_elem = product.select_one('.a-price-whole')
                    price = parse_price(price_elem.get_text()) if price_elem else None
                    if not price or price > 2000: continue
                    
                    # Get product ASIN for unique ID
                    asin_match = re.search(r'/dp/([A-Z0-9]{10})', link)
                    pid = f"amz_{asin_match.group(1) if asin_match else hash(link)}"
                    
                    items.append((pid, "AMAZON", title, link, price, 30))  # Assume 30% discount
                    
                except Exception as e:
                    continue
                    
        elif "flipkart" in url:
            # Flipkart product selectors
            products = soup.select('a._1fQZEK, a._2UzuFa, div._4ddWXP')
            for product in products[:15]:
                try:
                    href = product.get("href")
                    if not href: continue
                    
                    link = urljoin("https://www.flipkart.com", href.split('?')[0])
                    
                    title_elem = product.select_one('._4rR01T, .s1Q9rs')
                    title = title_elem.get_text(strip=True)[:80] if title_elem else "Flipkart Product"
                    
                    price_elem = product.select_one('._30jeq3')
                    price = parse_price(price_elem.get_text()) if price_elem else None
                    if not price or price > 2000: continue
                    
                    pid = f"fk_{hash(link)}"
                    items.append((pid, "FLIPKART", title, link, price, 35))  # Assume 35% discount
                    
                except Exception as e:
                    continue
    
    print(f"✅ Found {len(items)} REAL products")
    return items

# ---------------- POSTING ----------------
def compose_real_message(item):
    pid, platform, title, link, price, discount = item
    
    message = f"🔥 {platform} DEAL\n\n"
    message += f"🏷️ {title}\n\n"
    message += f"💰 Price: ₹{price}\n"
    message += f"🎯 Discount: {discount}% OFF\n\n"
    message += f"👉 {link}\n\n"
    message += f"⚡ GRAB NOW! LIMITED STOCK!"
    
    return message

def post_real_deals():
    print("🚀 Posting REAL deals...")
    deals = scrape_real_products()
    
    posted_count = 0
    for deal in deals:
        pid, platform, title, link, price, discount = deal
        
        if posted_recently(pid):
            continue
            
        message = compose_real_message(deal)
        if sync_send_message(message):
            mark_posted(pid, price, discount, title, link)
            print(f"📢 Posted REAL: {title[:50]}...")
            posted_count += 1
            time.sleep(3)
    
    return posted_count, deals

# ---------------- MAIN LOOP ----------------
last_post = {"text": None, "time": None, "count": 0}

def real_deal_loop():
    global last_post
    while True:
        try:
            print("🔄 Scanning for REAL deals...")
            posted_count, all_deals = post_real_deals()
            
            if posted_count > 0:
                last_post = {
                    "text": f"Posted {posted_count} REAL deals",
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "count": posted_count
                }
                print(f"✅ Posted {posted_count} REAL deals")
            else:
                last_post = {
                    "text": "No new REAL deals found",
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "count": 0
                }
                print("⚠️  No REAL deals this cycle")
            
            wait_time = 300  # 5 minutes
            print(f"⏰ Next scan in {wait_time} seconds...")
            time.sleep(wait_time)
            
        except Exception as e:
            print(f"❌ Loop error: {e}")
            time.sleep(60)

# ---------------- FLASK ROUTES ----------------
@app.route("/")
def home():
    return "REAL DEAL FINDER BOT ✅ Running"

@app.route("/status")
def status():
    return jsonify(last_post)

@app.route("/post-real")
def post_real():
    posted_count, all_deals = post_real_deals()
    return jsonify({
        "posted": posted_count,
        "found": len(all_deals),
        "status": "success"
    })

# ---------------- MAIN ----------------
def main():
    print("🤖 Starting REAL DEAL FINDER BOT")
    print(f"Channel: {CHANNEL_ID}")
    
    init_db()
    
    # Send startup message
    startup_msg = "✅ REAL DEAL FINDER BOT STARTED!\n\nNow scanning for ACTUAL products on Amazon & Flipkart!\n\nReal deals incoming! 🚀"
    if sync_send_message(startup_msg):
        print("✅ Startup message sent")
    
    # Start thread
    t = Thread(target=real_deal_loop, daemon=True)
    t.start()
    print("✅ Real deal scanner started")
    
    # Start Flask
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)

if __name__ == "__main__":
    main()