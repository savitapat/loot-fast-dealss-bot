import os
import time
import threading
import asyncio
import random
from flask import Flask
from telegram import Bot

# ---------------- Config ----------------
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

print("BOT_TOKEN from env =", BOT_TOKEN)
print("CHANNEL_ID from env =", CHANNEL_ID)

if not BOT_TOKEN or not CHANNEL_ID:
    raise ValueError("❌ TELEGRAM_TOKEN or CHANNEL_ID not set in environment!")

bot = Bot(token=BOT_TOKEN)
app = Flask(__name__)

# Fake deals for testing
FAKE_DEALS = [
    "🔥 Sample Deal – iPhone 15 Pro only ₹9999 (Testing)",
    "💥 Flash Sale – 80% OFF on Headphones (Testing)",
    "⚡ Price Drop – Laptop ₹15,000 (Testing)",
    "🎉 Loot Offer – Smartwatch ₹499 (Testing)",
]

# Track last posted deal for /status
last_deal = {"text": None, "time": None}

# ---------------- Flask routes ----------------
@app.route("/")
def home():
    return "✅ Loot Fast Deals Bot is running (Fake Deals Mode)"

@app.route("/status")
def status():
    return last_deal if last_deal["text"] else {"status": "no deals yet"}

@app.route("/health")
def health():
    return {"status": "ok"}

# ---------------- Deal Loop ----------------
async def send_fake_deal():
    """Async function that posts one fake deal to Telegram."""
    deal = random.choice(FAKE_DEALS)
    print("📢 Posting deal:", deal)
    await bot.send_message(chat_id=CHANNEL_ID, text=deal)

    last_deal["text"] = deal
    last_deal["time"] = time.strftime("%Y-%m-%d %H:%M:%S")

async def deal_loop():
    """Keeps running forever inside asyncio loop."""
    while True:
        try:
            await send_fake_deal()
        except Exception as e:
            print("❌ Loop error:", e)
        await asyncio.sleep(60)  # every 1 min

def start_background_loop():
    """Runs the async loop in a thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(deal_loop())
    loop.run_forever()

# ---------------- Main ----------------
def main():
    print("⚡ Bot starting in THREAD MODE (Fake Deals)")

    try:
        asyncio.run(
            bot.send_message(
                chat_id=CHANNEL_ID,
                text="✅ Bot running in THREAD MODE - Fake Deals every 1 min"
            )
        )
        print("✅ Startup message sent")
    except Exception as e:
        print("❌ Startup send failed:", e)

    # Start async loop in background thread
    t = threading.Thread(target=start_background_loop, daemon=True)
    t.start()

    # Run Flask
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000)),
        debug=False,
        use_reloader=False
    )

if __name__ == "__main__":
    main()
