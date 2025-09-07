# app.py – 24/7 ULTIMATE LOOT DEALS BOT
import os, re, time, random, sqlite3, asyncio, json
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
    'Referer': 'https://www.google.com/'
}

# ULTIMATE DEAL SOURCES (24/7 monitoring)
ULTIMATE_DEAL_SOURCES = [
    # REAL-TIME DEAL FEEDS
    "https://www.amazon.in/deals?ref_=nav_cs_gb",
    "https://www.flipkart.com/offers/deals-of-the-day",
    
    # CATEGORY-SPECIFIC LOOT ZONES
    "https://www.amazon.in/gp/bestsellers/electronics/ref=zg_bs_electronics_sm",
    "https://www.flipkart.com/electronics/pr?sid=tyy%2C4io&p%5B%5D=facets.discount_range_v1%5B%5D=50%25+or+more",
    
    # UNDER ₹500 SECTION (Where real loot is)
    "https://www.amazon.in/b/?node=3404659031",  # Clearance
    "https://www.flipkart.com/offers/clearance-store",
    
    # FLASH SALE PAGES
    "https://www.amazon.in/events?ref_=nav_cs_gb",
    "https://www.flipkart.com/plus/member-only-deals",
    
    # TRENDING DEALS (What other channels scrape)
    "https://www.amazon.in/b/?node=1389401031&filter=discount%3A70-",  # Electronics 70%+
    "https://www.flipkart.com/offers-list/trending-deals",
]

# POPULAR PRODUCT CATEGORIES (That other channels target)
POPULAR_CATEGORIES = [
    "https://www.amazon.in/s?k=earbuds+under+500&rh=p_36%3A1318505031",
    "https://www.amazon.in/s?k=power+bank+under+500",
    "https://www.flipkart.com/search?q=earbuds+under+500&sort=popularity",
    "https://www.flipkart.com/search?q=power+bank+under+1000",
    "https://www.amazon.in/s?k=smartwatch+under+1000",
    "https://www.flipkart.com/search?q=smartwatch+under+1500",
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
            source TEXT,
            category TEXT
        )""")

def posted_recently(pid, hours=2):  # Only 2 hours cooldown for frequent posting
    cutoff = int(time.time()) - hours * 3600
    with sqlite3.connect(DB) as c:
        row = c.execute("SELECT 1 FROM posts WHERE pid=? AND ts>=?", (pid, cutoff)).fetchone()
    return bool(row)

def mark_posted(pid, price, discount, title, source, category):
    with sqlite3.connect(DB) as c:
        c.execute("INSERT OR REPLACE INTO posts VALUES (?,?,?,?,?,?,?)",
                  (pid, int(time.time()), price, discount, title, source, category))

# ---------------- HELPERS ----------------
def fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        return r.text if r.status_code == 200 else ""
    except Exception as e:
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
    try:
        await bot.send_message(
            chat_id=CHANNEL_ID,
            text=message,
            disable_web_page_preview=False,
            parse_mode='HTML'
        )
        return True
    except Exception as e:
        return False

def sync_send_message(message):
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(send_telegram_message(message))
        loop.close()
        return result
    except Exception as e:
        return False

# ---------------- ULTIMATE SCRAPING ENGINE ----------------
def scrape_amazon_aggressive():
    items = []
    print("🛒 Scanning Amazon AGGRESSIVELY...")
    
    for url in ULTIMATE_DEAL_SOURCES + POPULAR_CATEGORIES:
        if "amazon" not in url: continue
        
        html = fetch(url)
        if not html: continue
        
        soup = BeautifulSoup(html, "lxml")
        
        # AGGRESSIVE AMAZON SELECTORS
        selectors = [
            '[data-component-type="s-search-result"]',
            '.s-result-item',
            '.a-section',
            '.deal-tile',
            '[data-testid="deal-card"]'
        ]
        
        for selector in selectors:
            for product in soup.select(selector)[:25]:  # Check more products
                try:
                    # Find link
                    link_elem = product.select_one('a[href*="/dp/"], a[href*="/gp/"], a[href*="/deal/"]')
                    if not link_elem: continue
                    
                    link = urljoin("https://www.amazon.in", link_elem["href"])
                    link = add_affiliate_tag(link.split('?')[0])
                    
                    # Find title
                    title_elem = product.select_one('.a-text-normal, h2, .a-size-base-plus')
                    title = title_elem.get_text(strip=True)[:80] if title_elem else "Amazon Deal"
                    
                    # Find price - ULTRA AGGRESSIVE
                    price = None
                    price_selectors = ['.a-price-whole', '.a-price .a-offscreen', '.a-text-price']
                    for ps in price_selectors:
                        price_elems = product.select(ps)
                        for elem in price_elems:
                            price = parse_price(elem.get_text())
                            if price and price <= 1000: break  # Only affordable items
                        if price: break
                    
                    if not price or price > 1500: continue  # Max ₹1500 for loot deals
                    
                    # Find original price for discount
                    original_price = None
                    original_selectors = ['.a-text-strike', '.a-price.a-text-price']
                    for ops in original_selectors:
                        original_elem = product.select_one(ops)
                        if original_elem:
                            original_price = parse_price(original_elem.get_text())
                            if original_price: break
                    
                    # Calculate discount
                    discount = 0
                    if original_price and original_price > price:
                        discount = int(((original_price - price) / original_price) * 100)
                    
                    # Also check discount badges
                    discount_elem = product.select_one('.savingsPercentage, .a-badge-text')
                    if discount_elem and not discount:
                        discount_text = discount_elem.get_text()
                        discount_match = re.search(r'(\d+)%', discount_text)
                        if discount_match:
                            discount = int(discount_match.group(1))
                    
                    # ONLY POST GOOD DEALS
                    if discount >= 50 or price <= 500:
                        pid = f"amz_{hash(link)}"
                        category = "Electronics" if "electronics" in url else "Fashion" if "fashion" in url else "Other"
                        items.append((pid, "AMAZON", title, link, price, discount, category))
                        
                except Exception:
                    continue
    
    print(f"✅ Found {len(items)} Amazon loot deals")
    return items

def scrape_flipkart_aggressive():
    items = []
    print("📦 Scanning Flipkart AGGRESSIVELY...")
    
    for url in ULTIMATE_DEAL_SOURCES + POPULAR_CATEGORIES:
        if "flipkart" not in url: continue
        
        html = fetch(url)
        if not html: continue
        
        soup = BeautifulSoup(html, "lxml")
        
        # AGGRESSIVE FLIPKART SELECTORS
        selectors = [
            'a._1fQZEK',
            'a._2UzuFa',
            'a.CGtCQZ',
            'a._2rpwqI',
            'div._4ddWXP'
        ]
        
        for selector in selectors:
            for product in soup.select(selector)[:25]:
                try:
                    # Find link
                    href = product.get("href")
                    if not href: continue
                    
                    link = urljoin("https://www.flipkart.com", href.split('?')[0])
                    
                    # Find title
                    title_elem = product.select_one('._4rR01T, .s1Q9rs, ._2mylT6')
                    title = title_elem.get_text(strip=True)[:80] if title_elem else "Flipkart Deal"
                    
                    # Find price
                    price_elem = product.select_one('._30jeq3, ._1_WHN1')
                    price = parse_price(price_elem.get_text()) if price_elem else None
                    if not price or price > 1500: continue
                    
                    # Find original price
                    original_elem = product.select_one('._3I9_wc, ._2p6lqe')
                    original_price = parse_price(original_elem.get_text()) if original_elem else None
                    
                    # Calculate discount
                    discount = 0
                    if original_price and original_price > price:
                        discount = int(((original_price - price) / original_price) * 100)
                    
                    # Check discount badge
                    discount_elem = product.select_one('._3Ay6Sb, ._2ZdXDS')
                    if discount_elem and not discount:
                        discount_text = discount_elem.get_text()
                        discount_match = re.search(r'(\d+)%', discount_text)
                        if discount_match:
                            discount = int(discount_match.group(1))
                    
                    # ONLY POST GOOD DEALS
                    if discount >= 50 or price <= 500:
                        pid = f"fk_{hash(link)}"
                        category = "Electronics" if "electronics" in url else "Fashion" if "fashion" in url else "Other"
                        items.append((pid, "FLIPKART", title, link, price, discount, category))
                        
                except Exception:
                    continue
    
    print(f"✅ Found {len(items)} Flipkart loot deals")
    return items

def scrape_popular_products():
    """Scrape specific popular products that other channels target"""
    items = []
    print("🎯 Scanning POPULAR products...")
    
    popular_products = [
        # Power Banks
        ("https://www.amazon.in/s?k=power+bank+under+1000", "Power Bank"),
        ("https://www.flipkart.com/search?q=power+bank+under+1000", "Power Bank"),
        
        # Earbuds
        ("https://www.amazon.in/s?k=earbuds+under+500", "Earbuds"),
        ("https://www.flipkart.com/search?q=earbuds+under+500", "Earbuds"),
        
        # Smartwatches
        ("https://www.amazon.in/s?k=smartwatch+under+1500", "Smartwatch"),
        ("https://www.flipkart.com/search?q=smartwatch+under+1500", "Smartwatch"),
        
        # Trimmers
        ("https://www.amazon.in/s?k=trimmer+under+500", "Trimmer"),
        ("https://www.flipkart.com/search?q=trimmer+under+500", "Trimmer"),
    ]
    
    for url, category in popular_products:
        html = fetch(url)
        if not html: continue
        
        soup = BeautifulSoup(html, "lxml")
        
        products = soup.select('.s-result-item, a._1fQZEK')[:15]
        for product in products:
            try:
                if "amazon" in url:
                    link_elem = product.select_one('a[href*="/dp/"]')
                    if not link_elem: continue
                    
                    link = urljoin("https://www.amazon.in", link_elem["href"])
                    link = add_affiliate_tag(link.split('?')[0])
                    
                    title_elem = product.select_one('.a-text-normal')
                    title = title_elem.get_text(strip=True)[:70] if title_elem else f"{category} Deal"
                    
                    price_elem = product.select_one('.a-price-whole')
                    price = parse_price(price_elem.get_text()) if price_elem else None
                    if not price: continue
                    
                    pid = f"pop_{hash(link)}"
                    items.append((pid, "AMAZON", title, link, price, 0, category))
                
                elif "flipkart" in url:
                    href = product.get("href")
                    if not href: continue
                    
                    link = urljoin("https://www.flipkart.com", href.split('?')[0])
                    
                    title_elem = product.select_one('._4rR01T, .s1Q9rs')
                    title = title_elem.get_text(strip=True)[:70] if title_elem else f"{category} Deal"
                    
                    price_elem = product.select_one('._30jeq3')
                    price = parse_price(price_elem.get_text()) if price_elem else None
                    if not price: continue
                    
                    pid = f"pop_{hash(link)}"
                    items.append((pid, "FLIPKART", title, link, price, 0, category))
                    
            except Exception:
                continue
    
    print(f"✅ Found {len(items)} popular product deals")
    return items

# ---------------- POSTING ----------------
def compose_ultimate_message(item):
    pid, platform, title, link, price, discount, category = item
    
    # URGENT MESSAGES LIKE BIG CHANNELS
    if price <= 300:
        emoji = "🚀💥"
        urgency = "SUPER LOOT"
    elif discount >= 70:
        emoji = "⚡🔥"
        urgency = "MEGA DEAL"
    elif discount >= 50:
        emoji = "🔥"
        urgency = "HOT DEAL"
    else:
        emoji = "🎯"
        urgency = "GREAT DEAL"
    
    message = f"{emoji} <b>{urgency} - {platform}</b>\n\n"
    message += f"🏷️ {title}\n\n"
    message += f"💰 Price: <b>₹{price}</b>\n"
    
    if discount > 0:
        message += f"🎯 Discount: <b>{discount}% OFF</b>\n\n"
    
    message += f"🔗 {link}\n\n"
    message += f"⏰ <b>GRAB BEFORE STOCK ENDS!</b>\n"
    message += f"📦 <b>Cash on Delivery Available</b>"
    
    return message

def post_ultimate_deals():
    print("🚀 Scanning for ULTIMATE deals...")
    
    # SCRAPE ALL SOURCES SIMULTANEOUSLY
    amazon_deals = scrape_amazon_aggressive()
    flipkart_deals = scrape_flipkart_aggressive()
    popular_deals = scrape_popular_products()
    
    all_deals = amazon_deals + flipkart_deals + popular_deals
    
    # Sort by price (lowest first) and discount (highest first)
    all_deals.sort(key=lambda x: (x[4], -x[5]))
    
    posted_count = 0
    for deal in all_deals:
        pid, platform, title, link, price, discount, category = deal
        
        if posted_recently(pid):
            continue
            
        message = compose_ultimate_message(deal)
        if sync_send_message(message):
            mark_posted(pid, price, discount, title, platform, category)
            print(f"📢 Posted: ₹{price} - {title[:40]}...")
            posted_count += 1
            time.sleep(1)  # FAST POSTING
    
    return posted_count, all_deals

# ---------------- MAIN LOOP ----------------
last_post = {"text": None, "time": None, "count": 0}

def ultimate_deal_loop():
    global last_post
    while True:
        try:
            # ALWAYS AGGRESSIVE - 24/7
            print("🌐 24/7 AGGRESSIVE scanning...")
            posted_count, all_deals = post_ultimate_deals()
            
            if posted_count > 0:
                last_post = {
                    "text": f"Posted {posted_count} new loot deals",
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "count": posted_count
                }
                print(f"✅ Posted {posted_count} loot deals")
            else:
                last_post = {
                    "text": "No new loot deals found",
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "count": 0
                }
                print("⚠️  No loot deals this cycle")
            
            # ULTRA FAST: 3 minutes always
            wait_time = 180  # 3 minutes
            print(f"⏰ Next scan in {wait_time} seconds...")
            time.sleep(wait_time)
            
        except Exception as e:
            print(f"❌ Loop error: {e}")
            time.sleep(60)

# ---------------- FLASK ROUTES ----------------
@app.route("/")
def home():
    return "24/7 ULTIMATE LOOT DEALS BOT ✅ Running"

@app.route("/status")
def status():
    return jsonify(last_post)

@app.route("/force-scan")
def force_scan():
    posted_count, all_deals = post_ultimate_deals()
    return jsonify({
        "posted": posted_count,
        "found": len(all_deals),
        "deals": [{"platform": d[1], "price": d[4], "discount": d[5]} for d in all_deals[:10]]
    })

# ---------------- MAIN ----------------
def main():
    print("🤖 Starting 24/7 ULTIMATE LOOT DEALS BOT")
    print(f"Channel: {CHANNEL_ID}")
    print("🌐 24/7 Mode: 3-minute scans ALWAYS")
    print("🎯 Targeting: Power Banks, Earbuds, Smartwatches, Trimmers")
    
    init_db()
    
    # Aggressive startup message
    startup_msg = "🚀 <b>24/7 ULTIMATE LOOT DEALS BOT ACTIVATED!</b>\n\n"
    startup_msg += "⚡ Scanning every 3 minutes 24/7\n"
    startup_msg += "🎯 Targeting: Power Banks, Earbuds, Smartwatches\n"
    startup_msg += "💰 Max price: ₹1500 | Min discount: 50%\n\n"
    startup_msg += "Get ready for NON-STOP LOOTS! 🔥"
    
    if sync_send_message(startup_msg):
        print("✅ Startup message sent")
    
    # Start ULTIMATE aggressive thread
    t = Thread(target=ultimate_deal_loop, daemon=True)
    t.start()
    print("✅ 24/7 aggressive scanner started")
    
    # Start Flask
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)

if __name__ == "__main__":
    main()