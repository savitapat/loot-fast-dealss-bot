# Loot Fast Dealss bot main script
# app.py
# Loot Fast Dealss — 24/7 Telegram bot (Amazon + Flipkart) without affiliate APIs
# Educational use. Scraping may break or be rate-limited; tune selectors/intervals as needed.

import os, re, time, math, random, sqlite3
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from apscheduler.schedulers.blocking import BlockingScheduler
from telegram import Bot
from dotenv import load_dotenv

# ---------- config ----------
load_dotenv(override=True)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID     = os.getenv("CHANNEL_ID", "@loot_fast_dealss")

assert TELEGRAM_TOKEN, "Set TELEGRAM_TOKEN in environment"

bot = Bot(token=TELEGRAM_TOKEN)

DB = "prices.db"

# thresholds (tune for your channel)
BIG_DISCOUNT_PCT   = 55    # post if >= 55% off vs MRP found on page
SUDDEN_DROP_PCT    = 50    # post if price dropped >= 50% vs last seen price
COOLDOWN_HOURS     = 12    # don’t repost same price within 12h
AMZ_INTERVAL_MIN   = 5     # scan every 5 min
FK_INTERVAL_MIN    = 3     # scan every 3 min

HEADERS_POOL = [
    # a few modern desktop UA strings
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
]

AMZ_DEALS_URLS = [
    "https://www.amazon.in/gp/goldbox",           # Today's Deals hub
    "https://www.amazon.in/deals"                 # Deals landing
]

FK_DEALS_URLS = [
    "https://www.flipkart.com/offers",           # Offers hub
    "https://www.flipkart.com/deals-of-the-day"  # DoD
]

# ---------- SQLite ----------
SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
  product_id TEXT PRIMARY KEY,
  source     TEXT NOT NULL,
  title      TEXT,
  link       TEXT,
  mrp        INTEGER,
  last_seen  INTEGER
);
CREATE TABLE IF NOT EXISTS prices (
  product_id TEXT,
  ts         INTEGER,
  price      INTEGER,
  PRIMARY KEY(product_id, ts)
);
CREATE TABLE IF NOT EXISTS posts (
  product_id TEXT,
  ts         INTEGER,
  price      INTEGER,
  message_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_prices_product ON prices(product_id);
"""

def db():
    return sqlite3.connect(DB)

def init_db():
    with db() as c:
        c.executescript(SCHEMA)

# ---------- helpers ----------

def now_s():
    return int(time.time())

price_re = re.compile(r"₹\s*([\d,]+)")
percent_re = re.compile(r"(\d{1,3})%\s*off", re.I)


def clean_price(text):
    if not text: return None
    m = price_re.search(text.replace("\u20b9", "₹"))
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def pct(off, base):
    try:
        return round(100.0 * (1.0 - (off / max(1, base))), 1)
    except Exception:
        return 0.0


def upsert_product(pid, source, title, link, mrp):
    with db() as c:
        c.execute(
            """
            INSERT INTO products(product_id, source, title, link, mrp, last_seen)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(product_id) DO UPDATE SET
              title=excluded.title,
              link=excluded.link,
              mrp=excluded.mrp,
              last_seen=excluded.last_seen
            """,
            (pid, source, title, link, int(now_s()))
        )

def insert_price(pid, price):
    with db() as c:
        c.execute("INSERT OR REPLACE INTO prices(product_id, ts, price) VALUES(?,?,?)",
                  (pid, now_s(), int(price)))

def last_price_before_now(pid):
    with db() as c:
        row = c.execute("SELECT price FROM prices WHERE product_id=? ORDER BY ts DESC LIMIT 1",
                        (pid,)).fetchone()
    return row[0] if row else None

def min_price_30d(pid):
    since = now_s() - 30*24*3600
    with db() as c:
        row = c.execute("SELECT MIN(price) FROM prices WHERE product_id=? AND ts>=?",
                        (pid, since)).fetchone()
    return row[0] if (row and row[0] is not None) else None

def posted_recently(pid, price, cooldown_hours=COOLDOWN_HOURS):
    cutoff = now_s() - cooldown_hours*3600
    with db() as c:
        row = c.execute("SELECT 1 FROM posts WHERE product_id=? AND price=? AND ts>=? LIMIT 1",
                        (pid, int(price), cutoff)).fetchone()
    return bool(row)

def mark_posted(pid, price, mid):
    with db() as c:
        c.execute("INSERT INTO posts(product_id, ts, price, message_id) VALUES(?,?,?,?)",
                  (pid, now_s(), int(price), str(mid)))

# ---------- HTTP ----------

def fetch(url, tries=3):
    for i in range(tries):
        try:
            headers = {"User-Agent": random.choice(HEADERS_POOL), "Accept-Language": "en-IN,en;q=0.9"}
            r = requests.get(url, headers=headers, timeout=20)
            if r.status_code in (200, 203):
                return r.text
            time.sleep(1.5 + i)
        except Exception:
            time.sleep(1 + i)
    return ""

# ---------- Scrapers (best-effort; selectors may need periodic tweaks) ----------

def parse_amazon_list(html, base_url):
    soup = BeautifulSoup(html, "lxml")
    items = []

    # Try structured deal cards first
    cards = soup.select('div[data-component-type="s-deal-card"], div[data-component-type="s-search-result"]')
    for c in cards:
        a = c.select_one('a.a-link-normal[href*="/dp/"]') or c.select_one('a[href*="/dp/"]')
        if not a: continue
        link = urljoin(base_url, a.get('href').split('?')[0])
        title = (c.select_one('span.a-text-normal') or c.select_one('span[dir="auto"]') or a).get_text(strip=True)
        price = None
        mrp = None
        # price blocks
        p_whole = c.select_one('span.a-price-whole')
        p_sym   = c.select_one('span.a-price-symbol')
        if p_whole:
            price = clean_price((p_sym.get_text(strip=True) if p_sym else "₹") + p_whole.get_text(strip=True))
        if not price:
            price = clean_price(c.get_text(" ", strip=True))
        # mrp/strike
        mrp_el = c.select_one('span.a-text-strike')
        if mrp_el:
            mrp = clean_price(mrp_el.get_text())
        if not mrp:
            # infer from "% off"
            pct_m = percent_re.search(c.get_text(" ", strip=True))
            if pct_m and price:
                perc = int(pct_m.group(1))
                mrp = math.floor(price / (1 - perc/100.0))
        if not price:
            continue
        pid = f"amz_{hash(link)}"
        items.append({"pid": pid, "source": "Amazon", "title": title, "link": link, "price": price, "mrp": mrp or price})

    # Fallback: any anchor to /dp/
    if not items:
        for a in soup.select('a[href*="/dp/"]'):
            link = urljoin(base_url, a.get('href').split('?')[0])
            title = a.get_text(strip=True)[:120] or "Amazon Deal"
            txt = a.find_parent().get_text(" ", strip=True) if a.find_parent() else ""
            price = clean_price(txt)
            if not price: continue
            mrp = clean_price(txt) or price
            pid = f"amz_{hash(link)}"
            items.append({"pid": pid, "source": "Amazon", "title": title, "link": link, "price": price, "mrp": mrp})

    return items


def scrape_amazon():
    collected = []
    for url in AMZ_DEALS_URLS:
        html = fetch(url)
        if not html: continue
        collected.extend(parse_amazon_list(html, url))
        time.sleep(1)
    return collected


def parse_flipkart_list(html, base_url):
    soup = BeautifulSoup(html, "lxml")
    items = []

    # Common product card patterns on Flipkart search/listing/DoD
    cards = soup.select('a._1fQZEK, a.s1Q9rs, a._2UzuFa, a._2rpwqI, a[href^="/item/"], a[href^="/p/"]')
    for a in cards:
        href = a.get('href')
        if not href: continue
        link = urljoin("https://www.flipkart.com", href.split('?')[0])
        card = a.find_parent()
        title = a.get('title') or a.get_text(strip=True) or "Flipkart Deal"
        block_text = card.get_text(" ", strip=True) if card else title
        price = None
        mrp = None
        # Flipkart often shows price in classes _30jeq3 or via ₹ sign
        price_el = (card.select_one('div._30jeq3') if card and hasattr(card, 'select_one') else None)
        if price_el:
            price = clean_price(price_el.get_text())
        if not price:
            price = clean_price(block_text)
        # MRP is often in class _3I9_wc (strike)
        mrp_el = (card.select_one('div._3I9_wc') if card and hasattr(card, 'select_one') else None)
        if mrp_el:
            mrp = clean_price(mrp_el.get_text())
        # else try % off
        pct_m = percent_re.search(block_text)
        if pct_m and price and not mrp:
            perc = int(pct_m.group(1))
            mrp = math.floor(price / (1 - perc/100.0))
        if not price:
            continue
        pid = f"fk_{hash(link)}"
        items.append({"pid": pid, "source": "Flipkart", "title": title, "link": link, "price": price, "mrp": mrp or price})

    return items


def scrape_flipkart():
    collected = []
    for url in FK_DEALS_URLS:
        html = fetch(url)
        if not html: continue
        collected.extend(parse_flipkart_list(html, url))
        time.sleep(1)
    return collected

# ---------- posting ----------

def compose_message(item, flags):
    badges = []
    if flags.get("price_error"): badges.append("🚨 PRICE ERROR")
    if flags.get("month_low"):   badges.append("📉 30‑DAY LOW")
    if flags.get("big_discount"):badges.append("🔥 BIG DEAL")
    badge_line = " | ".join(badges) if badges else "🤖 Loot Fast Dealss"
    disc = pct(item['price'], item.get('mrp', item['price']))
    return (
        f"{badge_line}\n"
        f"{item['source']} · {item['title']}\n"
        f"MRP: ₹{item.get('mrp', item['price'])}  |  Deal: ₹{item['price']}  (↓{disc}%)\n\n"
        f"👉 {item['link']}"
    )


def process_and_post(items):
    for it in items:
        pid   = it['pid']
        price = int(it['price'])
        mrp   = int(it.get('mrp', price))

        upsert_product(pid, it['source'], it['title'], it['link'], mrp)
        prev = last_price_before_now(pid)
        insert_price(pid, price)

        price_error = False
        if prev is not None and prev > 0:
            drop = pct(price, prev)
            price_error = drop >= SUDDEN_DROP_PCT

        low30 = min_price_30d(pid)
        month_low = low30 is None or price <= low30

        big_discount = pct(price, mrp) >= BIG_DISCOUNT_PCT

        flags = {"price_error": price_error, "month_low": month_low, "big_discount": big_discount}

        if not (price_error or month_low or big_discount):
            continue
        if posted_recently(pid, price):
            continue

        msg = compose_message(it, flags)
        try:
            m = bot.send_message(chat_id=CHANNEL_ID, text=msg, disable_web_page_preview=False)
            mark_posted(pid, price, m.message_id)
            time.sleep(1.2)
        except Exception as e:
            print("[Telegram post error]", e)
            time.sleep(2)

# ---------- jobs ----------

def job_amazon():
    items = scrape_amazon()
    process_and_post(items)


def job_flipkart():
    items = scrape_flipkart()
    process_and_post(items)

# ---------- main ----------

def main():
    init_db()
    print("Loot Fast Dealss bot started ✨")
    sched = BlockingScheduler()
    sched.add_job(job_flipkart, 'interval', minutes=FK_INTERVAL_MIN, id='flipkart')
    sched.add_job(job_amazon,  'interval', minutes=AMZ_INTERVAL_MIN, id='amazon')
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        pass

if __name__ == '__main__':
    main()