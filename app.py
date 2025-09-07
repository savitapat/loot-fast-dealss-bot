# app.py – Loot Fast Dealss Bot (No API Needed)
import os, re, time, random, sqlite3
from datetime import datetime
from urllib.parse import urljoin, quote_plus
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
    'Accept-Encoding': 'gzip, deflate',
}

# PREMIUM DEAL SOURCES
PREMIUM_DEAL_URLS = [
    # Amazon Deal Pages
    "https://www.amazon.in/deals",
    "https://www.amazon.in/gp/goldbox",
    "https://www.amazon.in/b/?node=1389401031",  # Electronics
    "https://www.amazon.in/b/?node=1389402031",  # Fashion
    
    # Flipkart Deal Pages
    "https://www.flipkart.com/offers/deals-of-the-day",
    "https://www.flipkart.com/offers/supercoin-zone",
    "https://www.flipkart.com/electronics/electronics-sale-store",
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
        r = requests.get(url, headers=HEADERS, timeout=25)
        return r.text if r.status_code == 200 else ""
    except Exception as e:
        print(f"❌ Fetch failed: {e}")
        return ""

def parse_price(text):
    if not text: return None
    text = re.sub(r"[^\d]", "", text)
    return int(text) if text.isdigit() and len(text) > 2 else None

def add_affiliate_tag(url):
    """Add your affiliate tag to Amazon URLs"""
    if AFFILIATE_TAG and "amazon.in" in url and "tag=" not in url:
        return f"{url}{'&' if '?' in url else '?'}tag={AFFILIATE_TAG}"
    return url

# ---------------- SCRAPERS ----------------
def scrape_amazon_deals():
    items = []
    for url in [u for u in PREMIUM_DEAL_URLS if "amazon" in u]:
        html = fetch(url)
        if not html: continue
        
        soup = BeautifulSoup(html, "lxml")
        
        # Multiple selectors for deal cards
        deal_selectors = [
            '[data-testid="deal-card"]',
            '.deal-tile',
            '.a-carousel-card',
            '.a-section.a-spacing-none'
        ]
        
        for selector in deal_selectors:
            for card in soup.select(selector):
                try:
                    # Find link
                    link_elem = card.select_one('a[href*="/deal/"], a[href*="/dp/"], a[href*="/gp/"]')
                    if not link_elem: continue
                    
                    link = urljoin("https://www.amazon.in", link_elem["href"])
                    link = add_affiliate_tag(link.split('?')[0])
                    
                    # Find title
                    title_elem = card.select_one('h2, .a-text-normal, [data-testid="deal-title"]')
                    title = title_elem.get_text(strip=True)[:100] if title_elem else "Amazon Deal"
                    
                    # Find prices
                    price_elems = card.select('.a-price-whole, .a-price .a-offscreen, [data-testid="deal-price"]')
                    current_price = None
                    for elem in price_elems:
                        current_price = parse_price(elem.get_text())
                        if current_price: break
                    
                    if not current_price: continue
                    
                    # Find original price for discount calculation
                    original_price_elems = card.select('.a-text-strike, .a-text-price, [data-testid="strikethrough-price"]')
                    original_price = None
                    for elem in original_price_elems:
                        original_price = parse_price(elem.get_text())
                        if original_price: break
                    
                    # Calculate discount
                    discount = 0
                    if original_price and original_price > current_price:
                        discount = int(((original_price - current_price) / original_price) * 100)
                    
                    # Only take good deals
                    if discount >= 40 or current_price <= 500:
                        pid = f"amz_{hash(link)}"
                        items.append((pid, "Amazon", title, link, current_price, discount))
                        
                except Exception as e:
                    continue
    
    return items

def scrape_flipkart_deals():
    items = []
    for url in [u for u in PREMIUM_DEAL_URLS if "flipkart" in u]:
        html = fetch(url)
        if not html: continue
        
        soup = BeautifulSoup(html, "lxml")
        
        # Flipkart deal selectors
        deal_selectors = [
            'a._1fQZEK',
            'a._2UzuFa',
            'a.CGtCQZ',
            'a._2rpwqI'
        ]
        
        for selector in deal_selectors:
            for card in soup.select(selector):
                try:
                    href = card.get("href")
                    if not href: continue
                    
                    link = urljoin("https://www.flipkart.com", href.split('?')[0])
                    
                    # Title
                    title_elem = card.select_one('._4rR01T, .s1Q9rs, ._2mylT6')
                    title = title_elem.get_text(strip=True)[:100] if title_elem else "Flipkart Deal"
                    
                    # Current price
                    price_elem = card.select_one('._30jeq3, ._1_WHN1')
                    current_price = parse_price(price_elem.get_text()) if price_elem else None
                    if not current_price: continue
                    
                    # Original price
                    original_elem = card.select_one('._3I9_wc, ._2p6lqe')
                    original_price = parse_price(original_elem.get_text()) if original_elem else None
                    
                    # Discount
                    discount = 0
                    if original_price and original_price > current_price:
                        discount = int(((original_price - current_price) / original_price) * 100)
                    
                    # Discount badge
                    discount_elem = card.select_one('._3Ay6Sb, ._2ZdXDS')
                    if discount_elem and not discount:
                        discount_text = discount_elem.get_text()
                        discount_match = re.search(r'(\d+)%', discount_text)
                        if discount_match:
                            discount = int(discount_match.group(1))
                    
                    if discount >= 50 or current_price <= 300:
                        pid = f"fk_{hash(link)}"
                        items.append((pid, "Flipkart", title, link, current_price, discount))
                        
                except Exception as e:
                    continue
    
    return items

# ---------------- POSTING ----------------
def compose_message(item):
    pid, platform, title, link, price, discount = item
    
    # Emoji based on discount
    if discount >= 70:
        emoji = "🚀🔥"
    elif discount >= 50:
        emoji = "⚡💥"
    else:
        emoji = "🔥"
    
    message = f"{emoji} {platform} DEAL\n\n"
    message += f"🏷️ {title}\n\n"
    message += f"💰 Price: ₹{price:,}\n"
    
    if discount > 0:
        message += f"🎯 {discount}% OFF\n"
    
    message += f"\n👉 {link}"
    
    if discount >= 60:
        message += "\n\n⚡ GRAB FAST! LIMITED TIME! ⚡"
    
    return message

def post_deals():
    print("🔄 Scanning for deals...")
    amazon_deals = scrape_amazon_deals()
    flipkart_deals = scrape_flipkart_deals()
    all_deals = amazon_deals + flipkart_deals
    
    posted_count = 0
    for deal in all_deals:
        pid, platform, title, link, price, discount = deal
        
        if posted_recently(pid):
            continue
            
        try:
            message = compose_message(deal)
            bot.send_message(
                chat_id=CHANNEL_ID,
                text=message,
                disable_web_page_preview=False
            )
            mark_posted(pid, price, discount, title)
            print(f"📢 Posted: {title[:50]}... ({discount}% OFF)")
            posted_count += 1
            time.sleep(2)
        except Exception as e:
            print(f"❌ Post failed: {e}")
    
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
                
                bot.send_message(chat_id=CHANNEL_ID, text=msg)
                last_post = {"text": msg, "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "count": posted_count}
                
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
            
            # Wait time
            wait_time = 600 if TEST_MODE else 1800  # 10 min test, 30 min real
            time.sleep(wait_time)
            
        except Exception as e:
            print(f"❌ Loop error: {e}")
            time.sleep(300)

# ---------------- FLASK ROUTES ----------------
@app.route("/")
def home():
    return "Loot Fast Dealss Bot ✅ Running (No API Needed)"

@app.route("/status")
def status():
    return jsonify(last_post)

@app.route("/scan-now")
def scan_now():
    posted_count, all_deals = post_deals()
    return jsonify({
        "posted": posted_count,
        "found": len(all_deals),
        "status": "success"
    })

# ---------------- MAIN ----------------
def main():
    print("🤖 Starting Deal Bot (No API Version)")
    print(f"Channel: {CHANNEL_ID}")
    print(f"Test Mode: {TEST_MODE}")
    print(f"Affiliate Tag: {AFFILIATE_TAG}")
    
    init_db()
    
    try:
        bot.send_message(chat_id=CHANNEL_ID, text="✅ Deal Bot Started! Scanning for premium deals...")
    except Exception as e:
        print(f"❌ Startup message failed: {e}")
    
    t = Thread(target=deal_loop, daemon=True)
    t.start()
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)

if __name__ == "__main__":
    main()