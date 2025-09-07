import os
import time
import threading
import asyncio
import logging
import requests
from bs4 import BeautifulSoup
from flask import Flask
from dotenv import load_dotenv
from telegram import Bot

# -------------------------------------------------
# Setup
# -------------------------------------------------
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

if not TOKEN or not CHANNEL_ID:
    raise ValueError("❌ BOT_TOKEN or CHANNEL_ID not set in environment!")

bot = Bot(token=TOKEN)

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Flask app
app = Flask(__name__)

@app.route("/")
def home():
    return "Loot Fast Deals Bot is running ✅"

@app.route("/health")
def health():
    return {"status": "ok"}

@app.route("/status")
def status():
    return {"last_post": LAST_POST_TIME, "last_source": LAST_SOURCE}


# -------------------------------------------------
# Globals
# -------------------------------------------------
FK_INTERVAL_MIN = 1   # super quick testing
AMZ_INTERVAL_MIN = 1  # super quick testing
TEST_MODE = True      # flip to False for real deals

LAST_POST_TIME = "never"
LAST_SOURCE = "none"


# -------------------------------------------------
# Scrapers
# -------------------------------------------------
def scrape_flipkart():
    url = "https://www.flipkart.com/search?q=deals"
    logging.info("🔎 Scraping Flipkart...")
    try:
        r = requests.get(url, timeout=10)
        soup = BeautifulSoup(r.text, "lxml")
        items = [a.text.strip() for a in soup.select("a.s1Q9rs")]
        return items[:3] if items else []
    except Exception as e:
        logging.error(f"Flipkart scrape error: {e}")
        return []


def scrape_amazon():
    url = "https://www.amazon.in/s?k=deals"
    logging.info("🔎 Scraping Amazon...")
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, "lxml")
        items = [a.text.strip() for a in soup.select("span.a-text-normal")]
        return items[:3] if items else []
    except Exception as e:
        logging.error(f"Amazon scrape error: {e}")
        return []


# -------------------------------------------------
# Deal Loop (Background Thread)
# -------------------------------------------------
def deal_loop():
    global LAST_POST_TIME, LAST_SOURCE
    logging.info("✅ Background deal loop started")

    while True:
        try:
            # Flipkart
            deals = scrape_flipkart()
            if deals:
                msg = "🔥 Flipkart Deals:\n" + "\n".join(deals)
                asyncio.run(bot.send_message(chat_id=CHANNEL_ID, text=msg))
                LAST_POST_TIME = time.strftime("%Y-%m-%d %H:%M:%S")
                LAST_SOURCE = "flipkart"
                logging.info(f"📨 Posted {len(deals)} Flipkart deals")

            # Amazon
            deals = scrape_amazon()
            if deals:
                msg = "🛒 Amazon Deals:\n" + "\n".join(deals)
                asyncio.run(bot.send_message(chat_id=CHANNEL_ID, text=msg))
                LAST_POST_TIME = time.strftime("%Y-%m-%d %H:%M:%S")
                LAST_SOURCE = "amazon"
                logging.info(f"📨 Posted {len(deals)} Amazon deals")

        except Exception as e:
            logging.error(f"❌ Error in deal loop: {e}")

        # Sleep between cycles
        time.sleep(60)  # every 1 min for testing


# -------------------------------------------------
# Main
# -------------------------------------------------
def main():
    logging.info("⚡ Bot starting in THREAD MODE")
    try:
        asyncio.run(bot.send_message(chat_id=CHANNEL_ID,
                                     text="✅ Bot running in THREAD MODE - expect frequent deals"))
    except Exception as e:
        logging.error(f"❌ Startup message failed: {e}")

    # start background thread
    t = threading.Thread(target=deal_loop, daemon=True)
    t.start()

    # run Flask (foreground)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)),
            debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
