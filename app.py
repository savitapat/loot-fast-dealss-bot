import os, re, time, sqlite3, requests, asyncio
from datetime import datetime
from flask import Flask, jsonify
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from bs4 import BeautifulSoup
from telegram import Bot

load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
AFFILIATE_TAG = os.getenv("AFFILIATE_TAG", "lootfastdeals-21")
DB = "deal_history.db"
app = Flask(__name__)
bot = Bot(BOT_TOKEN)

def init_db():
    with sqlite3.connect(DB) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS deals (
            pid TEXT PRIMARY KEY,
            title TEXT,
            last_price INTEGER,
            best_price INTEGER,
            platform TEXT,
            link TEXT,
            last_post INTEGER
        )""")

def get_price_history(pid):
    with sqlite3.connect(DB) as c:
        row = c.execute("SELECT last_price, best_price FROM deals WHERE pid=?", (pid,)).fetchone()
    return row if row else (None, None)

def update_price_history(pid, title, price, platform, link):
    with sqlite3.connect(DB) as c:
        last_price, best_price = get_price_history(pid)
        best_price = min(price, best_price) if best_price else price
        c.execute("""INSERT OR REPLACE INTO deals VALUES (?,?,?,?,?,?,?)""",
                  (pid, title, price, best_price, platform, link, int(time.time())))

def was_posted_recently(pid, min_interval=1800):
    with sqlite3.connect(DB) as c:
        row = c.execute("SELECT last_post FROM deals WHERE pid=?", (pid,)).fetchone()
    return row and row and (int(time.time()) - row < min_interval)

async def send_telegram_async(msg):
    await bot.send_message(chat_id=CHANNEL_ID, text=msg, disable_web_page_preview=False)

def send_telegram(msg):
    asyncio.run(send_telegram_async(msg))

def is_hot_deal(price, best_price, discount_thresh=40, drop_thresh=0.6):
    if not best_price: return False
    discount = int((best_price - price) * 100 / best_price) if best_price > 0 else 0
    return price < best_price * drop_thresh or discount >= discount_thresh

def scrape_amazon():
    url = "https://www.amazon.in/gp/goldbox"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    results = []
    try:
        r = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(r.text, "lxml")
        for card in soup.select('div[data-asin]'):
            try:
                title_elem = card.select_one('span.a-text-normal')
                price_elem = card.select_one('span.a-price-whole')
                link_elem = card.select_one('a.a-link-normal[href*="/dp/"]')
                if not title_elem or not price_elem or not link_elem: continue
                title = title_elem.text[:60]
                price = int(re.sub(r'\D', '', price_elem.text))
                link = "https://www.amazon.in" + link_elem.get('href').split('?')
                if AFFILIATE_TAG and 'amazon.in' in link and 'tag=' not in link:
                    link += ('&' if '?' in link else '?') + 'tag=%s' % AFFILIATE_TAG
                pid = 'amz_' + re.sub(r'\W+', '', link)[-16:]
                results.append({
                    'pid': pid, 'title': title, 'price': price, 'platform': 'AMAZON', 'link': link
                })
            except Exception:
                continue
    except Exception as e:
        print("Amazon scrape error:", e)
    return results

def scrape_flipkart():
    url = "https://www.flipkart.com/offers-store"
    headers = {'User-Agent': 'Mozilla/5.0'}
    results = []
    try:
        r = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.select('a.s1Q9rs, a._1fQZEK'):
            try:
                title = a.text[:80]
                link = "https://www.flipkart.com" + a.get('href').split('?')
                parent = a.find_parent()
                price_elem = parent.select_one('div._30jeq3')
                price = int(re.sub(r'\D', '', price_elem.text)) if price_elem else None
                if not price: continue
                pid = 'fk_' + re.sub(r'\W+', '', link)[-16:]
                results.append({
                    'pid': pid, 'title': title, 'price': price, 'platform': 'FLIPKART', 'link': link
                })
            except Exception:
                continue
    except Exception as e:
        print("Flipkart scrape error:", e)
    return results

def find_and_post_deals():
    for deal in scrape_amazon() + scrape_flipkart():
        pid, title, price, platform, link = deal['pid'], deal['title'], deal['price'], deal['platform'], deal['link']
        best_price = get_price_history(pid)[1]
        hot = is_hot_deal(price, best_price)
        not_recent = not was_posted_recently(pid)
        if (hot or not best_price) and not_recent:
            msg = f"🔥 {platform} DEAL\n\n🏷️ {title}\n\n💰 Price: ₹{price}\n👉 {link}\n⚡ GRAB NOW! LIMITED STOCK!"
            send_telegram(msg)
            update_price_history(pid, title, price, platform, link)

@app.route('/status')
def status():
    with sqlite3.connect(DB) as c:
        deals = list(c.execute("SELECT * FROM deals ORDER BY last_post DESC LIMIT 10"))
        return jsonify({'recent': [dict(zip(
            ['pid','title','last_price','best_price','platform','link','last_post'], d)) for d in deals]})

@app.route('/debug')
def debug():
    return jsonify({'amazon': scrape_amazon(), 'flipkart': scrape_flipkart()})

if __name__ == "__main__":
    init_db()
    scheduler = BackgroundScheduler()
    scheduler.add_job(find_and_post_deals, 'interval', seconds=60)
    scheduler.start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)), debug=False)
