# app.py – Loot Fast Dealss Bot
import os, re, time, random, sqlite3
from datetime import datetime
from urllib.parse import urljoin

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
TEST_MODE = os.getenv("TEST_MODE", "true").lower() == "true"

if not BOT_TOKEN or not CHANNEL_ID:
    raise ValueError("❌ TELEGRAM_TOKEN or CHANNEL_ID not set in environment!")

bot = Bot(BOT_TOKEN)
app = Flask(__name__)

DB = "deals.db"
HEADERS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36"
]

AMAZON_URLS = [
    "https://www.amazon.in/gp/goldbox",
    "https://www.amazon.in/deals",
    "https://www.amazon.in/offers",
]
FLIPKART_URLS = [
    "https://www.flipkart.com/offers",
    "https://www.flipkart.com/deals-of-the-day",
    "https://www.flipkart.com/electronics/pr?sid=tyy,4io&filter=discount%3A30.",
]

# ---------------- DB INIT ----------------
def init_db():
    with sqlite3.connect(DB) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS posts (
            pid TEXT PRIMARY KEY,
            ts INTEGER,
            price INTEGER
        )""")

def posted_recently(pid, price, hours=12):
    cutoff = int(time.time()) - hours * 3600
    with sqlite3.connect(DB) as c:
        row = c.execute("SELECT 1 FROM posts WHERE pid=? AND price=? AND ts>=?",
                        (pid, price, cutoff)).fetchone()
    return bool(row)

def mark_posted(pid, price):
    with sqlite3.connect(DB) as c:
        c.execute("INSERT OR REPLACE INTO posts VALUES (?,?,?)",
                  (pid, int(time.time()), price))

# ---------------- HELPERS ----------------
def fetch(url):
    try:
        r = requests.get(url, headers={"User-Agent": random.choice(HEADERS)}, timeout=25)
        if r.status_code == 200:
            return r.text
    except Exception as e:
        print(f"❌ Fetch failed {url}: {e}")
    return ""

def parse_price(text):
    if not text:
        return None
    text = re.sub(r"[^\d]", "", text)
    return int(text) if text.isdigit() else None

# ---------------- SCRAPERS ----------------
def scrape_amazon():
    items = []
    for url in AMAZON_URLS:
        html = fetch(url)
        if not html: continue
        soup = BeautifulSoup(html, "lxml")
        
        # Multiple selectors for Amazon deal cards
        cards = soup.select('[data-component-type="s-deal-card"], .deal-tile, .gb-grid-column, .a-carousel-card')
        
        for c in cards:
            try:
                # Find link
                a = c.select_one('a[href*="/dp/"], a[href*="/gp/"]')
                if not a: continue
                
                link = urljoin(url, a["href"].split("?")[0])
                
                # Find title
                title_elem = c.select_one("h2, .a-text-normal, .deal-title, .a-size-base-plus")
                title = title_elem.get_text(strip=True) if title_elem else "No title"
                
                # Find price - try multiple selectors
                price_selectors = [
                    ".a-price-whole",
                    ".a-price .a-offscreen",
                    ".deal-price",
                    ".price-block",
                    ".a-price-symbol"
                ]
                
                price = None
                for selector in price_selectors:
                    price_elems = c.select(selector)
                    for price_elem in price_elems:
                        price = parse_price(price_elem.get_text())
                        if price: break
                    if price: break
                
                if not price: continue
                
                pid = f"amz_{hash(link)}"
                items.append((pid, "Amazon", title, link, price))
                
            except Exception as e:
                print(f"❌ Error parsing Amazon card: {e}")
                continue
    
    print(f"✅ Scraped {len(items)} Amazon items")
    return items

def scrape_flipkart():
    items = []
    for url in FLIPKART_URLS:
        html = fetch(url)
        if not html: continue
        soup = BeautifulSoup(html, "lxml")
        
        # Multiple selectors for Flipkart deal items
        cards = soup.select("a._1fQZEK, a.s1Q9rs, a._2UzuFa, a._2rpwqI, a.CGtCQZ, a._2mylT6, a._8VNy32")
        
        for a in cards:
            try:
                href = a.get("href")
                if not href: continue
                
                link = urljoin("https://www.flipkart.com", href.split("?")[0])
                
                # Get title
                title_elem = a.select_one("img")  # Often title is in alt of image
                if title_elem and title_elem.get("alt"):
                    title = title_elem.get("alt")
                else:
                    title_elem = a.select_one("._4rR01T, .s1Q9rs, ._2mylT6, ._2WkVRV")
                    title = title_elem.get_text(strip=True) if title_elem else a.get_text(strip=True) or "No title"
                
                # Find price in parent or nearby elements
                price = None
                parent = a.find_parent("div")
                if parent:
                    price_elems = parent.select("._30jeq3, ._1_WHN1, ._2WkVRV, ._3I9_wc, ._25b18c")
                    for price_elem in price_elems:
                        price = parse_price(price_elem.get_text())
                        if price: break
                
                # If price not found in parent, try siblings
                if not price:
                    price_elems = a.find_next_siblings("div")
                    for elem in price_elems:
                        price = parse_price(elem.get_text())
                        if price: break
                
                if not price: continue
                
                pid = f"fk_{hash(link)}"
                items.append((pid, "Flipkart", title, link, price))
                
            except Exception as e:
                print(f"❌ Error parsing Flipkart card: {e}")
                continue
    
    print(f"✅ Scraped {len(items)} Flipkart items")
    return items

# ---------------- POSTING ----------------
def compose(item):
    pid, src, title, link, price = item
    emoji = "🔥" if price < 1000 else "💥" if price < 5000 else "⚡"
    return f"{emoji} {src} Deal\n{title}\n💰 Price: ₹{price:,}\n👉 {link}"

def process_and_post(items):
    posted_count = 0
    for pid, src, title, link, price in items:
        if posted_recently(pid, price): 
            continue
            
        msg = compose((pid, src, title, link, price))
        try:
            bot.send_message(chat_id=CHANNEL_ID, text=msg, disable_web_page_preview=False)
            mark_posted(pid, price)
            print(f"📢 Posted: {title[:50]}...")
            posted_count += 1
            time.sleep(2)  # Avoid rate limiting
        except Exception as e:
            print(f"❌ Telegram post error: {e}")
    
    return posted_count

# ---------------- DEBUG ----------------
def debug_scraping():
    """Debug function to see what's being scraped"""
    print("=== DEBUG MODE ===")
    
    # Test Amazon
    print("Testing Amazon...")
    amazon_items = scrape_amazon()
    for i, item in enumerate(amazon_items[:5], 1):
        print(f"{i}. Amazon: {item[2][:60]}... - ₹{item[4]:,}")
    
    # Test Flipkart
    print("\nTesting Flipkart...")
    flipkart_items = scrape_flipkart()
    for i, item in enumerate(flipkart_items[:5], 1):
        print(f"{i}. Flipkart: {item[2][:60]}... - ₹{item[4]:,}")
    
    print(f"\nTotal Amazon: {len(amazon_items)}")
    print(f"Total Flipkart: {len(flipkart_items)}")
    print("=== DEBUG END ===")
    
    return len(amazon_items) + len(flipkart_items)

# ---------------- LOOP ----------------
last_post = {"text": None, "time": None, "count": 0}

def deal_loop():
    global last_post
    while True:
        try:
            if TEST_MODE:
                # Debug mode - test scraping without posting
                total_items = debug_scraping()
                
                samples = [
                    "🔥 Sample Deal – iPhone 15 Pro only ₹9,999 (Testing)",
                    "💥 Flash Sale – 80% OFF on Headphones (Testing)",
                    "⚡ Price Drop – Gaming Laptop ₹15,000 (Testing)",
                    "🎉 Loot Offer – Smartwatch ₹499 (Testing)",
                    f"🔍 Debug Mode – Found {total_items} potential deals (Not posting)"
                ]
                msg = random.choice(samples)
                try:
                    bot.send_message(chat_id=CHANNEL_ID, text=msg)
                    last_post = {
                        "text": msg, 
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "count": total_items
                    }
                    print("📢 Posted DEBUG message")
                except Exception as e:
                    print(f"❌ Debug message failed: {e}")
                
            else:
                # REAL MODE - actual scraping and posting
                print("🔄 Starting real scraping...")
                amz = scrape_amazon()
                fk = scrape_flipkart()
                all_items = amz + fk
                
                if all_items:
                    posted_count = process_and_post(all_items)
                    last_item = all_items[0]
                    last_post = {
                        "text": f"Posted {posted_count} deals. Latest: {last_item[2][:30]}...", 
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "count": posted_count
                    }
                    print(f"✅ Posted {posted_count} new deals")
                else:
                    print("⚠️  No deals found this cycle")
                    last_post = {
                        "text": "No new deals found", 
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "count": 0
                    }
            
            # Wait time based on mode
            wait_time = 300 if TEST_MODE else 1800  # 5 min test, 30 min real
            print(f"⏰ Next check in {wait_time//60} minutes...")
            time.sleep(wait_time)
            
        except Exception as e:
            print(f"❌ Loop error: {e}")
            time.sleep(60)

# ---------------- FLASK ----------------
@app.route("/")
def home():
    return "Loot Fast Dealss Bot ✅ Running"

@app.route("/status")
def status():
    return jsonify(last_post)

@app.route("/debug")
def debug():
    total = debug_scraping()
    return jsonify({"status": "debug_complete", "items_found": total})

# ---------------- MAIN ----------------
def main():
    print(f"BOT_TOKEN from env = {BOT_TOKEN[:10]}...")
    print(f"CHANNEL_ID from env = {CHANNEL_ID}")
    print(f"TEST_MODE = {TEST_MODE}")
    
    if TEST_MODE:
        print("⚡ Bot starting in DEBUG MODE (Testing scraping, no real posts)")
    else:
        print("⚡ Bot starting in REAL MODE (Actual scraping and posting)")

    init_db()
    
    try:
        startup_msg = "✅ Bot deployed in DEBUG mode!" if TEST_MODE else "✅ Bot deployed with REAL scraping!"
        bot.send_message(chat_id=CHANNEL_ID, text=startup_msg)
        print("✅ Startup message sent")
    except Exception as e:
        print(f"❌ Failed to send startup message: {e}")

    # Start background thread
    t = Thread(target=deal_loop, daemon=True)
    t.start()
    print("✅ Background deal loop started")

    # Start Flask app
    port = int(os.environ.get("PORT", 10000))
    print(f"🌐 Flask server starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)

if __name__ == "__main__":
    main()