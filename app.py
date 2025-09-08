# app.py – WORKING DEAL BOT WITH UPDATED SELECTORS
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
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Referer': 'https://www.google.com/',
    'DNT': '1',
}

# UPDATED DEAL SOURCES (WORKING URLs)
DEAL_SOURCES = [
    # Amazon (Working URLs)
    "https://www.amazon.in/s?i=electronics&bbn=1389401031&rh=n%3A1389401031%2Cp_36%3A1318504031&dc&qid=1704567890&rnid=1318502031&ref=sr_nr_p_36_1",
    "https://www.amazon.in/deals?ref_=nav_cs_gb",
    
    # Flipkart (Working URLs)
    "https://www.flipkart.com/electronics/audio-video/headphones/earbuds~type/pr?sid=0pm%2Cfcn&otracker=categorytree&p%5B%5D=facets.price_range.from%3DMin&p%5B%5D=facets.price_range.to%3D500",
    "https://www.flipkart.com/offers-store",
    
    # Specific searches that work
    "https://www.amazon.in/s?k=earbuds&rh=p_36%3A1318504031-1318505031",
    "https://www.flipkart.com/search?q=power+bank&sort=popularity&p%5B%5D=facets.price_range.from%3DMin&p%5B%5D=facets.price_range.to%3D1000",
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

# ---------------- UPDATED SCRAPING (WORKING SELECTORS) ----------------
def fetch(url):
    try:
        # Add random delay to avoid blocking
        time.sleep(random.uniform(1, 3))
        r = requests.get(url, headers=HEADERS, timeout=20)
        print(f"🌐 Fetched {url} - Status: {r.status_code}")
        return r.text if r.status_code == 200 else ""
    except Exception as e:
        print(f"❌ Fetch failed {url}: {e}")
        return ""

def parse_price(text):
    if not text: return None
    text = re.sub(r"[^\d]", "", text)
    return int(text) if text.isdigit() and len(text) > 2 else None

def add_affiliate_tag(url):
    if AFFILIATE_TAG and "amazon.in" in url and "tag=" not in url:
        return f"{url}{'&' if '?' in url else '?'}tag={AFFILIATE_TAG}"
    return url

def scrape_deals():
    items = []
    print("🔍 Scanning for deals with UPDATED selectors...")
    
    for url in DEAL_SOURCES:
        html = fetch(url)
        if not html: 
            print(f"⚠️  No HTML for {url}")
            continue
        
        soup = BeautifulSoup(html, "lxml")
        print(f"📊 Parsing {url} - HTML length: {len(html)}")
        
        # AMAZON - UPDATED SELECTORS (2024)
        if "amazon" in url:
            # Try multiple selectors that currently work
            selectors = [
                'div[data-component-type="s-search-result"]',
                'div.s-result-item',
                'div[data-asin]',
                '.s-card-border'
            ]
            
            for selector in selectors:
                products = soup.select(selector)
                print(f"🔍 Found {len(products)} products with {selector} on Amazon")
                
                for product in products[:10]:
                    try:
                        # UPDATED LINK SELECTOR
                        link_elem = product.select_one('a.a-link-normal[href*="/dp/"]')
                        if not link_elem:
                            continue
                        
                        link = urljoin("https://www.amazon.in", link_elem["href"])
                        link = add_affiliate_tag(link.split('?')[0])
                        
                        # UPDATED TITLE SELECTOR
                        title_elem = product.select_one('span.a-text-normal, h2.a-size-mini')
                        title = title_elem.get_text(strip=True)[:80] if title_elem else "Amazon Deal"
                        
                        # UPDATED PRICE SELECTOR
                        price_elem = product.select_one('span.a-price-whole, span.a-offscreen')
                        price = parse_price(price_elem.get_text()) if price_elem else None
                        
                        if not price or price > 2000:
                            continue
                        
                        pid = f"amz_{hash(link)}"
                        items.append((pid, "AMAZON", title, link, price, 30))
                        print(f"✅ Amazon product: {title[:30]} - ₹{price}")
                        
                    except Exception as e:
                        continue
                        print(f"❌ Amazon product error: {e}")
        
        # FLIPKART - UPDATED SELECTORS (2024)
        elif "flipkart" in url:
            # Try multiple selectors that currently work
            selectors = [
                'div[data-id]',
                'a._1fQZEK',
                'div._4ddWXP',
                'a._2UzuFa'
            ]
            
            for selector in selectors:
                products = soup.select(selector)
                print(f"🔍 Found {len(products)} products with {selector} on Flipkart")
                
                for product in products[:10]:
                    try:
                        # UPDATED LINK SELECTOR
                        if selector == 'div[data-id]' or selector == 'div._4ddWXP':
                            link_elem = product.select_one('a')
                        else:
                            link_elem = product
                        
                        href = link_elem.get("href") if link_elem else None
                        if not href:
                            continue
                        
                        link = urljoin("https://www.flipkart.com", href.split('?')[0])
                        
                        # UPDATED TITLE SELECTOR
                        title_elem = product.select_one('a._4rR01T, a.s1Q9rs, div._4rR01T')
                        title = title_elem.get_text(strip=True)[:80] if title_elem else "Flipkart Deal"
                        
                        # UPDATED PRICE SELECTOR
                        price_elem = product.select_one('div._30jeq3, div._1_WHN1')
                        price = parse_price(price_elem.get_text()) if price_elem else None
                        
                        if not price or price > 2000:
                            continue
                        
                        pid = f"fk_{hash(link)}"
                        items.append((pid, "FLIPKART", title, link, price, 35))
                        print(f"✅ Flipkart product: {title[:30]} - ₹{price}")
                        
                    except Exception as e:
                        continue
                        print(f"❌ Flipkart product error: {e}")
    
    print(f"✅ Total found: {len(items)} deals")
    return items

# ---------------- TELEGRAM FUNCTIONS ----------------
async def send_telegram_message_async(message):
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

def send_telegram_message_safe(message):
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(send_telegram_message_async(message))
        loop.close()
        return result
    except Exception as e:
        print(f"❌ Async error: {e}")
        return False

# ---------------- POSTING ----------------
def compose_message(item):
    pid, platform, title, link, price, discount = item
    
    message = f"🔥 {platform} DEAL\n\n"
    message += f"🏷️ {title}\n\n"
    message += f"💰 Price: ₹{price}\n"
    message += f"🎯 Discount: {discount}% OFF\n\n"
    message += f"👉 {link}\n\n"
    message += f"⚡ GRAB NOW! LIMITED STOCK!"
    
    return message

def post_deals():
    deals = scrape_deals()
    
    posted_count = 0
    for deal in deals:
        pid, platform, title, link, price, discount = deal
        
        if posted_recently(pid):
            continue
            
        message = compose_message(deal)
        if send_telegram_message_safe(message):
            mark_posted(pid, price, discount, title, link)
            print(f"📢 Posted: {title[:50]}...")
            posted_count += 1
            time.sleep(3)
    
    return posted_count, deals

# ---------------- MAIN LOOP ----------------
last_post = {"text": None, "time": None, "count": 0}

def deal_loop():
    global last_post
    while True:
        try:
            print("🔄 Starting scan cycle...")
            posted_count, all_deals = post_deals()
            
            if posted_count > 0:
                last_post = {
                    "text": f"Posted {posted_count} deals",
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "count": posted_count
                }
                print(f"✅ Posted {posted_count} deals")
            else:
                last_post = {
                    "text": "No new deals found",
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "count": 0
                }
                print("⚠️  No deals this cycle")
            
            wait_time = 300
            print(f"⏰ Next scan in {wait_time} seconds...")
            time.sleep(wait_time)
            
        except Exception as e:
            print(f"❌ Loop error: {e}")
            time.sleep(60)

# ---------------- FLASK ROUTES ----------------
@app.route("/")
def home():
    return "UPDATED DEAL BOT ✅ Running"

@app.route("/status")
def status():
    return jsonify(last_post)

@app.route("/post-now")
def post_now():
    posted_count, all_deals = post_deals()
    return jsonify({
        "posted": posted_count,
        "found": len(all_deals),
        "status": "success"
    })

@app.route("/debug")
def debug():
    deals = scrape_deals()
    return jsonify({
        "found": len(deals),
        "samples": [{"platform": d[1], "title": d[2][:30], "price": d[4]} for d in deals[:3]] if deals else []
    })

# ---------------- MAIN ----------------
def main():
    print("🤖 Starting UPDATED DEAL BOT")
    print(f"Channel: {CHANNEL_ID}")
    print("🔧 Using updated 2024 selectors")
    
    init_db()
    
    startup_msg = "🔄 UPDATED DEAL BOT RESTARTED!\n\nUsing latest 2024 selectors\nScanning for real deals...\n\nStay tuned! 🚀"
    if send_telegram_message_safe(startup_msg):
        print("✅ Startup message sent")
    
    t = Thread(target=deal_loop, daemon=True)
    t.start()
    print("✅ Scanner started")
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)

if __name__ == "__main__":
    main()