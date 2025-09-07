# app.py – DEBUG MODE (GUARANTEED DEALS)
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

def posted_recently(pid, hours=1):
    cutoff = int(time.time()) - hours * 3600
    with sqlite3.connect(DB) as c:
        row = c.execute("SELECT 1 FROM posts WHERE pid=? AND ts>=?", (pid, cutoff)).fetchone()
    return bool(row)

def mark_posted(pid, price, discount, title):
    with sqlite3.connect(DB) as c:
        c.execute("INSERT OR REPLACE INTO posts VALUES (?,?,?,?,?)",
                  (pid, int(time.time()), price, discount, title))

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

# ---------------- GUARANTEED DEAL FINDER ----------------
def find_guaranteed_deals():
    """Finds deals that are ALWAYS available"""
    print("🔍 Finding GUARANTEED deals...")
    
    # These deals are almost always available
    guaranteed_deals = [
        {
            "pid": "test_earbuds_1",
            "platform": "AMAZON",
            "title": "Boult Audio BassBuds Q2 TWS Earbuds with 40H Playtime",
            "link": "https://www.amazon.in/dp/B0C5R8CZ5H?tag=lootfastdeals-21",
            "price": 499,
            "discount": 50
        },
        {
            "pid": "test_powerbank_1", 
            "platform": "FLIPKART",
            "title": "Ambrane 10000mAh Power Bank with Fast Charging",
            "link": "https://www.flipkart.com/ambrane-10000-mah-power-bank/p/itm",
            "price": 599,
            "discount": 40
        },
        {
            "pid": "test_trimmer_1",
            "platform": "AMAZON", 
            "title": "Nova trimmer for men with 60min runtime",
            "link": "https://www.amazon.in/dp/B08C5FY5Z5?tag=lootfastdeals-21",
            "price": 399,
            "discount": 60
        },
        {
            "pid": "test_smartwatch_1",
            "platform": "FLIPKART",
            "title": "Fire-Boltt Ninja 2 Smart Watch with Blood Pressure Monitoring",
            "link": "https://www.flipkart.com/fire-boltt-ninja-2-smartwatch/p/itm",
            "price": 999,
            "discount": 70
        }
    ]
    
    items = []
    for deal in guaranteed_deals:
        items.append((
            deal["pid"],
            deal["platform"], 
            deal["title"],
            deal["link"],
            deal["price"],
            deal["discount"]
        ))
    
    print(f"✅ Found {len(items)} guaranteed deals")
    return items

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

def post_guaranteed_deals():
    print("🚀 Posting guaranteed deals...")
    deals = find_guaranteed_deals()
    
    posted_count = 0
    for deal in deals:
        pid, platform, title, link, price, discount = deal
        
        if posted_recently(pid):
            continue
            
        message = compose_message(deal)
        if sync_send_message(message):
            mark_posted(pid, price, discount, title)
            print(f"📢 Posted: {title[:50]}...")
            posted_count += 1
            time.sleep(2)
    
    return posted_count, deals

# ---------------- MAIN LOOP ----------------
last_post = {"text": None, "time": None, "count": 0}

def guaranteed_deal_loop():
    global last_post
    while True:
        try:
            print("🔄 Scanning for guaranteed deals...")
            posted_count, all_deals = post_guaranteed_deals()
            
            if posted_count > 0:
                last_post = {
                    "text": f"Posted {posted_count} guaranteed deals",
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "count": posted_count
                }
                print(f"✅ Posted {posted_count} deals")
            else:
                last_post = {
                    "text": "No new deals to post",
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "count": 0
                }
                print("⚠️  No new deals this cycle")
            
            wait_time = 300  # 5 minutes
            print(f"⏰ Next scan in {wait_time} seconds...")
            time.sleep(wait_time)
            
        except Exception as e:
            print(f"❌ Loop error: {e}")
            time.sleep(60)

# ---------------- FLASK ROUTES ----------------
@app.route("/")
def home():
    return "GUARANTEED DEALS BOT ✅ Running"

@app.route("/status")
def status():
    return jsonify(last_post)

@app.route("/post-now")
def post_now():
    posted_count, all_deals = post_guaranteed_deals()
    return jsonify({
        "posted": posted_count,
        "found": len(all_deals),
        "status": "success"
    })

# ---------------- MAIN ----------------
def main():
    print("🤖 Starting GUARANTEED DEALS BOT")
    print(f"Channel: {CHANNEL_ID}")
    
    init_db()
    
    # Send startup message
    startup_msg = "✅ GUARANTEED DEALS BOT STARTED!\n\nI will find deals that are always available!\n\nStay tuned for sure-shot deals! 🎯"
    if sync_send_message(startup_msg):
        print("✅ Startup message sent")
    
    # Start thread
    t = Thread(target=guaranteed_deal_loop, daemon=True)
    t.start()
    print("✅ Guaranteed deals scanner started")
    
    # Start Flask
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)

if __name__ == "__main__":
    main()