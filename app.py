# app.py – ULTIMATE 24/7 LOOT DEALS BOT (Advanced Techniques)
import os, re, time, random, sqlite3, asyncio, json, threading
from datetime import datetime, timedelta
from urllib.parse import urljoin, quote, parse_qs
import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify
from threading import Thread, Lock
from dotenv import load_dotenv
from telegram import Bot
from telegram.error import TelegramError
import concurrent.futures

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
HEADERS_LIST = [
    {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'},
    {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15'},
    {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0'},
    {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
]

# ---------------- ADVANCED CONFIG ----------------
PRICE_TRACKING = {}  # Tracks price history for drop detection
deal_lock = Lock()
MAX_WORKERS = 5  # Parallel scraping threads

# MULTIPLE SCRAPING SOURCES (Simultaneous monitoring)
SCRAPING_SOURCES = {
    "amazon_bestsellers": [
        "https://www.amazon.in/gp/bestsellers/electronics",
        "https://www.amazon.in/gp/bestsellers/computers", 
        "https://www.amazon.in/gp/bestsellers/home-improvement"
    ],
    "amazon_deals": [
        "https://www.amazon.in/deals",
        "https://www.amazon.in/gp/goldbox"
    ],
    "flipkart_deals": [
        "https://www.flipkart.com/offers/deals-of-the-day",
        "https://www.flipkart.com/offers/supercoin-zone"
    ],
    "category_specific": [
        "https://www.amazon.in/s?k=earbuds+under+500",
        "https://www.amazon.in/s?k=power+bank+under+1000",
        "https://www.flipkart.com/search?q=earbuds+under+500",
        "https://www.flipkart.com/search?q=power+bank+under+1000"
    ]
}

# ---------------- DB INIT (Advanced) ----------------
def init_db():
    with sqlite3.connect(DB) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS posts (
            pid TEXT PRIMARY KEY,
            ts INTEGER,
            price INTEGER,
            original_price INTEGER,
            discount INTEGER,
            title TEXT,
            link TEXT,
            source TEXT,
            category TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS price_history (
            pid TEXT,
            ts INTEGER,
            price INTEGER,
            PRIMARY KEY (pid, ts)
        )""")

def posted_recently(pid, hours=2):
    cutoff = int(time.time()) - hours * 3600
    with sqlite3.connect(DB) as c:
        row = c.execute("SELECT 1 FROM posts WHERE pid=? AND ts>=?", (pid, cutoff)).fetchone()
    return bool(row)

def mark_posted(pid, price, original_price, discount, title, link, source, category):
    with sqlite3.connect(DB) as c:
        c.execute("INSERT OR REPLACE INTO posts VALUES (?,?,?,?,?,?,?,?,?)",
                  (pid, int(time.time()), price, original_price, discount, title, link, source, category))
        # Track price history for drop detection
        c.execute("INSERT INTO price_history VALUES (?,?,?)", 
                 (pid, int(time.time()), price))

def get_price_history(pid):
    with sqlite3.connect(DB) as c:
        rows = c.execute("SELECT price, ts FROM price_history WHERE pid=? ORDER BY ts DESC LIMIT 10", (pid,)).fetchall()
    return rows

# ---------------- ADVANCED HELPERS ----------------
def get_random_headers():
    return random.choice(HEADERS_LIST)

def fetch_with_retry(url, retries=3):
    for attempt in range(retries):
        try:
            headers = get_random_headers()
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 200:
                return r.text
            time.sleep(2 ** attempt)  # Exponential backoff
        except Exception as e:
            print(f"❌ Fetch attempt {attempt+1} failed: {e}")
            time.sleep(1)
    return ""

def parse_price(text):
    if not text: return None
    text = re.sub(r"[^\d]", "", text)
    return int(text) if text.isdigit() and len(text) > 2 else None

def add_affiliate_tag(url):
    if AFFILIATE_TAG and "amazon.in" in url and "tag=" not in url:
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}tag={AFFILIATE_TAG}"
    return url

# ---------------- MULTI-THREADED SCRAPING ----------------
def scrape_source(source_name, urls):
    """Scrape a single source category in parallel"""
    items = []
    print(f"🔍 Scanning {source_name}...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(urls))) as executor:
        future_to_url = {executor.submit(scrape_single_url, url, source_name): url for url in urls}
        for future in concurrent.futures.as_completed(future_to_url):
            try:
                result = future.result()
                items.extend(result)
            except Exception as e:
                print(f"❌ Error scraping {source_name}: {e}")
    
    print(f"✅ Found {len(items)} items in {source_name}")
    return items

def scrape_single_url(url, source_name):
    """Scrape a single URL with advanced detection"""
    items = []
    html = fetch_with_retry(url)
    if not html: return items
    
    soup = BeautifulSoup(html, "lxml")
    
    # DYNAMIC SELECTOR DETECTION
    selectors = {
        "amazon": [
            '[data-component-type="s-search-result"]',
            '.s-result-item',
            '.deal-tile',
            '[data-testid="deal-card"]'
        ],
        "flipkart": [
            'a._1fQZEK',
            'a._2UzuFa',
            'a.CGtCQZ',
            'div._4ddWXP'
        ]
    }
    
    platform = "amazon" if "amazon" in url else "flipkart" if "flipkart" in url else "unknown"
    
    for selector in selectors.get(platform, []):
        for product in soup.select(selector)[:20]:
            try:
                item = extract_product_info(product, platform, url)
                if item and item["price"] and item["price"] <= 2000:
                    items.append((
                        item["pid"], item["platform"], item["title"], 
                        item["link"], item["price"], item["original_price"],
                        item["discount"], source_name, item["category"]
                    ))
            except Exception as e:
                continue
    
    return items

def extract_product_info(product, platform, source_url):
    """Advanced product information extraction"""
    if platform == "amazon":
        link_elem = product.select_one('a[href*="/dp/"], a[href*="/gp/"], a[href*="/deal/"]')
        if not link_elem: return None
        
        link = urljoin("https://www.amazon.in", link_elem["href"])
        link = add_affiliate_tag(link.split('?')[0])
        
        title_elem = product.select_one('.a-size-medium, .a-text-normal, .a-size-base-plus')
        title = title_elem.get_text(strip=True)[:100] if title_elem else "Amazon Deal"
        
        # Price extraction with multiple fallbacks
        price = None
        for selector in ['.a-price-whole', '.a-price .a-offscreen', '.dealPrice']:
            price_elem = product.select_one(selector)
            if price_elem:
                price = parse_price(price_elem.get_text())
                if price: break
        
        # Original price for discount calculation
        original_price = None
        for selector in ['.a-text-strike', '.a-price.a-text-price']:
            original_elem = product.select_one(selector)
            if original_elem:
                original_price = parse_price(original_elem.get_text())
                if original_price: break
        
        # Discount calculation
        discount = calculate_discount(price, original_price)
        
        # Category detection
        category = detect_category(title, source_url)
        
        # Unique ID with ASIN
        asin_match = re.search(r'/dp/([A-Z0-9]{10})', link)
        pid = f"amz_{asin_match.group(1) if asin_match else hash(link)}"
        
        return {
            "pid": pid, "platform": "AMAZON", "title": title, "link": link,
            "price": price, "original_price": original_price, 
            "discount": discount, "category": category
        }
    
    elif platform == "flipkart":
        href = product.get("href")
        if not href: return None
        
        link = urljoin("https://www.flipkart.com", href.split('?')[0])
        
        title_elem = product.select_one('._4rR01T, .s1Q9rs, ._2mylT6')
        title = title_elem.get_text(strip=True)[:100] if title_elem else "Flipkart Deal"
        
        price_elem = product.select_one('._30jeq3, ._1_WHN1')
        price = parse_price(price_elem.get_text()) if price_elem else None
        
        original_elem = product.select_one('._3I9_wc, ._2p6lqe')
        original_price = parse_price(original_elem.get_text()) if original_elem else None
        
        discount = calculate_discount(price, original_price)
        category = detect_category(title, source_url)
        
        pid = f"fk_{hash(link)}"
        
        return {
            "pid": pid, "platform": "FLIPKART", "title": title, "link": link,
            "price": price, "original_price": original_price,
            "discount": discount, "category": category
        }
    
    return None

def calculate_discount(current_price, original_price):
    if current_price and original_price and original_price > current_price:
        return int(((original_price - current_price) / original_price) * 100)
    return 0

def detect_category(title, url):
    """Advanced category detection"""
    title_lower = title.lower()
    if any(word in title_lower for word in ['earbud', 'headphone', 'earphone']):
        return 'Audio'
    elif any(word in title_lower for word in ['power bank', 'charger']):
        return 'Power Bank'
    elif any(word in title_lower for word in ['smartwatch', 'watch']):
        return 'Smartwatch'
    elif any(word in title_lower for word in ['trimmer', 'shaver']):
        return 'Grooming'
    elif 'amazon' in url and 'electronics' in url:
        return 'Electronics'
    elif 'flipkart' in url and 'electronics' in url:
        return 'Electronics'
    return 'Other'

# ---------------- PRICE TRACKING ALGORITHM ----------------
def detect_price_drops():
    """Advanced price drop detection algorithm"""
    print("📊 Analyzing price drops...")
    price_drops = []
    
    with sqlite3.connect(DB) as c:
        recent_products = c.execute("""
            SELECT pid, price, title, link FROM posts 
            WHERE ts >= ? ORDER BY ts DESC LIMIT 100
        """, (int(time.time()) - 86400,)).fetchall()
    
    for pid, current_price, title, link in recent_products:
        history = get_price_history(pid)
        if len(history) >= 2:
            previous_price = history[1][0]  # Second most recent price
            if current_price < previous_price:
                drop_percent = int(((previous_price - current_price) / previous_price) * 100)
                if drop_percent >= 10:  # Minimum 10% drop
                    price_drops.append((pid, "PRICE_DROP", title, link, current_price, drop_percent))
    
    return price_drops

# ---------------- REAL-TIME MONITORING ----------------
def monitor_deals_continuously():
    """24/7 real-time monitoring with multiple techniques"""
    while True:
        try:
            all_items = []
            
            # MULTI-THREADED SCRAPING (Simultaneous)
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(SCRAPING_SOURCES)) as executor:
                future_to_source = {executor.submit(scrape_source, source, urls): source for source, urls in SCRAPING_SOURCES.items()}
                for future in concurrent.futures.as_completed(future_to_source):
                    try:
                        items = future.result()
                        all_items.extend(items)
                    except Exception as e:
                        print(f"❌ Source monitoring failed: {e}")
            
            # PRICE DROP DETECTION
            price_drops = detect_price_drops()
            for drop in price_drops:
                all_items.append(drop)
            
            # PROCESS AND POST
            process_and_post_deals(all_items)
            
            # ADAPTIVE SLEEP BASED ON TIME
            current_hour = datetime.now().hour
            sleep_time = 180 if 22 <= current_hour <= 23 or 0 <= current_hour <= 2 else 300
            print(f"⏰ Next scan in {sleep_time} seconds...")
            time.sleep(sleep_time)
            
        except Exception as e:
            print(f"❌ Monitoring error: {e}")
            time.sleep(60)

def process_and_post_deals(all_items):
    """Process and post deals with advanced filtering"""
    posted_count = 0
    
    # Sort by price and discount
    all_items.sort(key=lambda x: (x[4] if len(x) > 4 else 0, -x[5] if len(x) > 5 else 0))
    
    for item in all_items:
        try:
            if len(item) == 9:  # Regular product
                pid, platform, title, link, price, original_price, discount, source, category = item
                message_type = "HOT_DEAL"
            else:  # Price drop
                pid, platform, title, link, price, discount = item
                message_type = "PRICE_DROP"
                original_price = price + (price * discount // 100)
            
            if posted_recently(pid):
                continue
            
            message = compose_advanced_message(
                platform, title, link, price, original_price, discount, message_type
            )
            
            if sync_send_message(message):
                mark_posted(pid, price, original_price, discount, title, link, platform, category)
                print(f"📢 Posted {message_type}: ₹{price} - {title[:40]}...")
                posted_count += 1
                time.sleep(2)
                
        except Exception as e:
            print(f"❌ Posting error: {e}")
    
    return posted_count

def compose_advanced_message(platform, title, link, price, original_price, discount, message_type):
    """Advanced message composition like big channels"""
    if message_type == "PRICE_DROP":
        emoji = "📉🔥"
        urgency = "PRICE DROP ALERT"
    elif discount >= 70:
        emoji = "🚀💥"
        urgency = "SUPER LOOT"
    elif discount >= 50:
        emoji = "⚡🔥"
        urgency = "HOT DEAL"
    else:
        emoji = "🎯"
        urgency = "GREAT DEAL"
    
    message = f"{emoji} <b>{urgency} - {platform}</b>\n\n"
    message += f"🏷️ {title}\n\n"
    message += f"💰 Price: <b>₹{price}</b>\n"
    
    if original_price and original_price > price:
        message += f"🎯 Was: <s>₹{original_price}</s> | Save: {discount}%\n\n"
    
    message += f"🔗 {link}\n\n"
    
    if message_type == "PRICE_DROP":
        message += f"📉 <b>JUST DROPPED {discount}%!</b>\n"
    else:
        message += f"⏰ <b>GRAB BEFORE STOCK ENDS!</b>\n"
    
    message += f"📦 <b>Cash on Delivery Available</b>"
    
    return message

# ---------------- ASYNC TELEGRAM FUNCTIONS ----------------
async def send_telegram_message(message):
    try:
        await bot.send_message(
            chat_id=CHANNEL_ID,
            text=message,
            disable_web_page_preview=False,
            parse_mode='HTML'
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

# ---------------- FLASK ROUTES ----------------
@app.route("/")
def home():
    return "ULTIMATE 24/7 LOOT DEALS BOT ✅ Running"

@app.route("/status")
def status():
    return jsonify({"status": "active", "monitoring": "24/7"})

@app.route("/force-scan")
def force_scan():
    all_items = []
    for source, urls in SCRAPING_SOURCES.items():
        all_items.extend(scrape_source(source, urls))
    
    posted = process_and_post_deals(all_items)
    return jsonify({"posted": posted, "found": len(all_items)})

# ---------------- MAIN ----------------
def main():
    print("🤖 Starting ULTIMATE 24/7 LOOT DEALS BOT")
    print(f"Channel: {CHANNEL_ID}")
    print("🌐 Multi-threaded scraping: ACTIVE")
    print("📊 Price tracking: ACTIVE")
    print("🚀 Real-time monitoring: 24/7")
    
    init_db()
    
    startup_msg = "🚀 <b>ULTIMATE 24/7 LOOT DEALS BOT ACTIVATED!</b>\n\n"
    startup_msg += "✅ Multi-threaded scraping\n✅ Real-time price tracking\n✅ 24/7 monitoring\n\n"
    startup_msg += "Get ready for NON-STOP DEALS! 🔥"
    
    if sync_send_message(startup_msg):
        print("✅ Startup message sent")
    
    # Start advanced monitoring
    monitor_thread = Thread(target=monitor_deals_continuously, daemon=True)
    monitor_thread.start()
    print("✅ Advanced monitoring started")
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)

if __name__ == "__main__":
    main()