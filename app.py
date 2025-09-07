# app.py – ULTRA FAST LOOT DEALS BOT (Midnight Edition)
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

bot = Bot(BOT_TOKEN)
app = Flask(__name__)

DB = "deals.db"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

# ULTRA AGGRESSIVE DEAL SOURCES (Like big channels)
ULTRA_DEAL_SOURCES = [
    # FLASH SALE PAGES (Midnight deals)
    "https://www.amazon.in/deals?dealType=LIGHTNING_DEAL",
    "https://www.amazon.in/gp/goldbox?dealType=lightning",
    "https://www.flipkart.com/offers/flash-sales",
    "https://www.flipkart.com/plus/member-only-deals",
    
    # CLEARANCE & LIQUIDATION (Where loot deals are)
    "https://www.amazon.in/b/?node=3404659031",  # Clearance Store
    "https://www.amazon.in/b/?node=3404670031",  # Overstock Deals
    "https://www.flipkart.com/offers/clearance-store",
    
    # PRICE DROP PAGES
    "https://www.amazon.deals/price-drops",
    "https://www.flipkart.com/offers/price-drop",
    
    # CATEGORY-SPECIFIC LOOT DEALS
    "https://www.amazon.in/b/?node=1389401031&filter=discount%3A70-",  # Electronics 70%+
    "https://www.amazon.in/b/?node=1389402031&filter=discount%3A80-",  # Fashion 80%+
    "https://www.flipkart.com/electronics/pr?sid=tyy%2C4io&filter=discount%3A60.",  # Electronics 60%+
    "https://www.flipkart.com/clothing-and-accessories/pr?sid=clo&filter=discount%3A70.",  # Fashion 70%+
    
    # DAILY SUPER DEALS
    "https://www.amazon.in/b/?node=26841786031",  # Today's Deals
    "https://www.flipkart.com/offers-list/todays-special-deals",
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
            source TEXT
        )""")

def posted_recently(pid, hours=3):  # Only 3 hours cooldown for flash deals
    cutoff = int(time.time()) - hours * 3600
    with sqlite3.connect(DB) as c:
        row = c.execute("SELECT 1 FROM posts WHERE pid=? AND ts>=?", (pid, cutoff)).fetchone()
    return bool(row)

def mark_posted(pid, price, discount, title, source):
    with sqlite3.connect(DB) as c:
        c.execute("INSERT OR REPLACE INTO posts VALUES (?,?,?,?,?,?)",
                  (pid, int(time.time()), price, discount, title, source))

# ---------------- HELPERS ----------------
def fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)  # Faster timeout
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

# ---------------- ULTRA AGGRESSIVE SCRAPERS ----------------
def scrape_flash_deals():
    items = []
    print("⚡ Scanning FLASH deals...")
    
    for url in ULTRA_DEAL_SOURCES:
        html = fetch(url)
        if not html: continue
        
        soup = BeautifulSoup(html, "lxml")
        
        # AGGRESSIVE SELECTORS (like big channels use)
        aggressive_selectors = [
            # Amazon flash deals
            '[data-testid="deal-card"]',
            '.lightningDeal',
            '.a-box-group',
            '.s-result-item',
            '.deal-container',
            
            # Flipkart flash deals  
            'a._1fQZEK',
            'a._2UzuFa',
            'a.CGtCQZ',
            '.IIdQZO',
            '._4ddWXP'
        ]
        
        for selector in aggressive_selectors:
            for card in soup.select(selector)[:20]:  # Check more items
                try:
                    # AMAZON
                    if "amazon" in url:
                        link_elem = card.select_one('a[href*="/deal/"], a[href*="/dp/"], a[href*="/gp/"]')
                        if not link_elem: continue
                        
                        link = urljoin("https://www.amazon.in", link_elem["href"])
                        link = add_affiliate_tag(link.split('?')[0])
                        
                        title_elem = card.select_one('h2, .a-text-normal, [data-testid="deal-title"]')
                        title = title_elem.get_text(strip=True)[:80] if title_elem else "Flash Deal"
                        
                        # PRICE - ULTRA AGGRESSIVE
                        price = None
                        price_selectors = ['.a-price-whole', '.a-price .a-offscreen', '.dealPrice', '.price']
                        for ps in price_selectors:
                            price_elem = card.select_one(ps)
                            if price_elem:
                                price = parse_price(price_elem.get_text())
                                if price and price < 500: break  # ONLY CHEAP ITEMS
                        
                        if not price or price > 1000: continue  # MAX ₹1000 for loot deals
                        
                        # DISCOUNT - MUST BE HIGH
                        discount = 0
                        discount_selectors = ['.a-text-strike', '.a-text-price', '.savingsPercentage', '.discount']
                        for ds in discount_selectors:
                            discount_elem = card.select_one(ds)
                            if discount_elem:
                                discount_text = discount_elem.get_text()
                                discount_match = re.search(r'(\d+)%', discount_text)
                                if discount_match:
                                    discount = int(discount_match.group(1))
                                    if discount >= 60: break  # Only high discounts
                        
                        if discount < 60: continue  # MINIMUM 60% OFF
                        
                        pid = f"flash_amz_{hash(link)}"
                        items.append((pid, "AMAZON FLASH", title, link, price, discount))
                    
                    # FLIPKART
                    elif "flipkart" in url:
                        href = card.get("href")
                        if not href: continue
                        
                        link = urljoin("https://www.flipkart.com", href.split('?')[0])
                        
                        title_elem = card.select_one('._4rR01T', '.s1Q9rs', '._2mylT6')
                        title = title_elem.get_text(strip=True)[:80] if title_elem else "Flash Deal"
                        
                        # PRICE
                        price_elem = card.select_one('._30jeq3', '._1_WHN1')
                        price = parse_price(price_elem.get_text()) if price_elem else None
                        if not price or price > 1000: continue
                        
                        # DISCOUNT
                        discount = 0
                        discount_elem = card.select_one('._3Ay6Sb', '._2ZdXDS', '.ICdJdP')
                        if discount_elem:
                            discount_text = discount_elem.get_text()
                            discount_match = re.search(r'(\d+)%', discount_text)
                            if discount_match:
                                discount = int(discount_match.group(1))
                        
                        if discount < 60: continue
                        
                        pid = f"flash_fk_{hash(link)}"
                        items.append((pid, "FLIPKART FLASH", title, link, price, discount))
                        
                except Exception:
                    continue
    
    print(f"✅ Found {len(items)} FLASH deals")
    return items

def scrape_clearance_deals():
    """Find clearance and liquidation deals (real loot deals)"""
    items = []
    print("🛒 Scanning CLEARANCE deals...")
    
    clearance_urls = [
        "https://www.amazon.in/b/?node=3404659031",  # Clearance
        "https://www.amazon.in/b/?node=3404670031",  # Overstock
        "https://www.flipkart.com/offers/clearance-store"
    ]
    
    for url in clearance_urls:
        html = fetch(url)
        if not html: continue
        
        soup = BeautifulSoup(html, "lxml")
        
        products = soup.select('.s-result-item, ._1fQZEK, ._2UzuFa')[:25]
        for product in products:
            try:
                if "amazon" in url:
                    link_elem = product.select_one('a[href*="/dp/"]')
                    if not link_elem: continue
                    
                    link = urljoin("https://www.amazon.in", link_elem["href"])
                    link = add_affiliate_tag(link.split('?')[0])
                    
                    title_elem = product.select_one('.a-text-normal')
                    title = title_elem.get_text(strip=True)[:70] if title_elem else "Clearance Deal"
                    
                    price_elem = product.select_one('.a-price-whole')
                    price = parse_price(price_elem.get_text()) if price_elem else None
                    if not price or price > 500: continue  # MAX ₹500 for clearance
                    
                    pid = f"clearance_{hash(link)}"
                    items.append((pid, "CLEARANCE", title, link, price, 70))  # Assume 70% off
                
                elif "flipkart" in url:
                    href = product.get("href")
                    if not href: continue
                    
                    link = urljoin("https://www.flipkart.com", href.split('?')[0])
                    
                    title_elem = product.select_one('._4rR01T', '.s1Q9rs')
                    title = title_elem.get_text(strip=True)[:70] if title_elem else "Clearance Deal"
                    
                    price_elem = product.select_one('._30jeq3')
                    price = parse_price(price_elem.get_text()) if price_elem else None
                    if not price or price > 500: continue
                    
                    pid = f"clearance_{hash(link)}"
                    items.append((pid, "CLEARANCE", title, link, price, 70))
                    
            except Exception:
                continue
    
    print(f"✅ Found {len(items)} CLEARANCE deals")
    return items

# ---------------- POSTING ----------------
def compose_ultra_message(item):
    pid, platform, title, link, price, discount = item
    
    # URGENT MESSAGES LIKE BIG CHANNELS
    if discount >= 80:
        emoji = "🚀💥"
        urgency = "SUPER LOOT"
    elif discount >= 70:
        emoji = "⚡🔥" 
        urgency = "HOT DEAL"
    else:
        emoji = "🔥"
        urgency = "FLASH SALE"
    
    message = f"{emoji} <b>{urgency} - {platform}</b>\n\n"
    message += f"🏷️ {title}\n\n"
    message += f"💰 Price: <b>₹{price}</b>\n"
    message += f"🎯 Discount: <b>{discount}% OFF</b>\n\n"
    message += f"🔗 {link}\n\n"
    message += f"⏰ <b>GRAB BEFORE STOCK ENDS!</b>\n"
    message += f"📦 <b>Cash on Delivery Available</b>"
    
    return message

def post_ultra_deals():
    print("🚀 Scanning for ULTRA deals...")
    
    flash_deals = scrape_flash_deals()
    clearance_deals = scrape_clearance_deals()
    
    all_deals = flash_deals + clearance_deals
    
    # Sort by price (lowest first) for real loot deals
    all_deals.sort(key=lambda x: x[4])
    
    posted_count = 0
    for deal in all_deals:
        pid, platform, title, link, price, discount = deal
        
        if posted_recently(pid):
            continue
            
        message = compose_ultra_message(deal)
        if sync_send_message(message):
            mark_posted(pid, price, discount, title, platform)
            print(f"📢 Posted ULTRA: ₹{price} - {title[:40]}...")
            posted_count += 1
            time.sleep(1)  # VERY FAST POSTING
    
    return posted_count, all_deals

# ---------------- MAIN LOOP ----------------
last_post = {"text": None, "time": None, "count": 0}

def ultra_deal_loop():
    global last_post
    while True:
        try:
            current_hour = datetime.now().hour
            current_minute = datetime.now().minute
            
            # ULTRA AGGRESSIVE during peak hours (10PM - 2AM)
            if 22 <= current_hour <= 23 or 0 <= current_hour <= 2:
                print("🌙 NIGHT MODE: Ultra aggressive scanning...")
                posted_count, all_deals = post_ultra_deals()
                
                if posted_count > 0:
                    last_post = {
                        "text": f"🌙 Posted {posted_count} NIGHT deals",
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "count": posted_count
                    }
                    print(f"✅ Posted {posted_count} night deals")
                else:
                    last_post = {
                        "text": "No night deals found",
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "count": 0
                    }
                    
                wait_time = 180  # 3 minutes during night
                
            else:
                # Normal mode during day
                print("☀️ DAY MODE: Normal scanning...")
                posted_count, all_deals = post_ultra_deals()
                
                if posted_count > 0:
                    last_post = {
                        "text": f"Posted {posted_count} deals",
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "count": posted_count
                    }
                else:
                    last_post = {
                        "text": "No deals found",
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "count": 0
                    }
                    
                wait_time = 300  # 5 minutes during day
            
            print(f"⏰ Next scan in {wait_time} seconds...")
            time.sleep(wait_time)
            
        except Exception as e:
            print(f"❌ Loop error: {e}")
            time.sleep(60)

# ---------------- FLASK ROUTES ----------------
@app.route("/")
def home():
    return "ULTRA LOOT DEALS BOT ✅ Running (Night Mode Active)"

@app.route("/status")
def status():
    return jsonify(last_post)

@app.route("/ultra-scan")
def ultra_scan():
    posted_count, all_deals = post_ultra_deals()
    return jsonify({
        "posted": posted_count,
        "found": len(all_deals),
        "deals": [{"platform": d[1], "price": d[4], "discount": d[5]} for d in all_deals[:10]]
    })

# ---------------- MAIN ----------------
def main():
    print("🤖 Starting ULTRA LOOT DEALS BOT")
    print(f"Channel: {CHANNEL_ID}")
    print("🌙 Night Mode: 10PM - 2AM (3-minute scans)")
    print("☀️ Day Mode: 5-minute scans")
    
    init_db()
    
    # Aggressive startup message
    startup_msg = "🚀 <b>ULTRA LOOT DEALS BOT ACTIVATED!</b>\n\n"
    startup_msg += "⚡ Scanning for 60-80% OFF deals\n"
    startup_msg += "🌙 Night Mode: 10PM-2AM (3-minute scans)\n"
    startup_msg += "☀️ Day Mode: 5-minute scans\n\n"
    startup_msg += "Get ready for AMAZING LOOTS! 🔥"
    
    if sync_send_message(startup_msg):
        print("✅ Startup message sent")
    
    # Start ULTRA aggressive thread
    t = Thread(target=ultra_deal_loop, daemon=True)
    t.start()
    print("✅ Ultra aggressive scanner started")
    
    # Start Flask
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)

if __name__ == "__main__":
    main()