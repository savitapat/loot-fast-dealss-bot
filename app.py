import os, re, time, random, sqlite3, requests, asyncio
from datetime import datetime
from flask import Flask, jsonify
from dotenv import load_dotenv
from telegram import Bot
from apscheduler.schedulers.background import BackgroundScheduler

# Selenium
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
DB = "deal_history.db"
AFFILIATE_TAG = os.getenv("AFFILIATE_TAG", "lootfastdeals-21")
app = Flask(__name__)
bot = Bot(BOT_TOKEN)

# Chrome headless for Render (no need for GUI)
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--no-sandbox')
    # If running locally, set executable_path; for Render, use default
    return webdriver.Chrome(options=chrome_options)

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
    return row and row[0] and (int(time.time()) - row[0] < min_interval)

async def send_telegram_async(msg):
    await bot.send_message(chat_id=CHANNEL_ID, text=msg, disable_web_page_preview=False)

def send_telegram(msg):
    asyncio.run(send_telegram_async(msg))

def is_hot_deal(price, best_price, discount_thresh=40, drop_thresh=0.6):
    if not best_price: return False
    discount = int((best_price - price) * 100 / best_price) if best_price > 0 else 0
    return price < best_price * drop_thresh or discount >= discount_thresh

def scrape_amazon():
    driver = get_driver()
    driver.get("https://www.amazon.in/deals?ref_=nav_cs_gb")
    time.sleep(3)
    # Example selector for deal cards (update based on live HTML)
    results = []
    for card in driver.find_elements(By.CSS_SELECTOR, 'div[data-asin]'):
        try:
            title_elem = card.find_element(By.CSS_SELECTOR, 'span.a-text-normal')
            price_elem = card.find_element(By.CSS_SELECTOR, 'span.a-price-whole')
            link_elem = card.find_element(By.CSS_SELECTOR, 'a.a-link-normal')
            title = title_elem.text[:60]
            price = int(re.sub(r'\D', '', price_elem.text))
            link = link_elem.get_attribute('href')
            pid = 'amz_' + re.sub(r'\W+', '', link)[-16:]
            results.append({
                'pid': pid, 'title': title, 'price': price, 'platform': 'AMAZON', 'link': link
            })
        except Exception:
            continue
    driver.quit()
    return results

def scrape_flipkart():
    driver = get_driver()
    driver.get("https://www.flipkart.com/offers-store")
    time.sleep(3)
    results = []
    for card in driver.find_elements(By.CSS_SELECTOR, 'a.s1Q9rs, a._1fQZEK'):
        try:
            title = card.text[:60]
            link = card.get_attribute('href')
            parent = card.find_element(By.XPATH, '..')
            price_elem = parent.find_element(By.CSS_SELECTOR, 'div._30jeq3')
            price = int(re.sub(r'\D', '', price_elem.text))
            pid = 'fk_' + re.sub(r'\W+', '', link)[-16:]
            results.append({
                'pid': pid, 'title': title, 'price': price, 'platform': 'FLIPKART', 'link': link
            })
        except Exception:
            continue
    driver.quit()
    return results

def find_and_post_deals():
    for deal in scrape_amazon() + scrape_flipkart():
        pid, title, price, platform, link = deal['pid'], deal['title'], deal['price'], deal['platform'], deal['link']
        best_price = get_price_history(pid)[1]
        # Alert if price error, very low, hot discount, or lowest ever
        hot = is_hot_deal(price, best_price)
        not_recent = not was_posted_recently(pid)
        big_error = price < 499  # Example: Price error on TV, etc.
        if hot or big_error or price < 999:
            msg = f"🔥 {platform} DEAL\n\n🏷️ {title}\n\n💰 Price: ₹{price}\n" \
                f"👉 {link}\n\n⚡ Lowest/Hot Deal!"
            send_telegram(msg)
            update_price_history(pid, title, price, platform, link)

# Flask debug/status endpoints
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
    scheduler.add_job(find_and_post_deals, 'interval', seconds=60) # every minute
    scheduler.start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)), debug=False)
