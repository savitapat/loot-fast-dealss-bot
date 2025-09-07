import os
import time
import threading
import asyncio
from flask import Flask
from telegram import Bot

# ---------------- Config ----------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

if not BOT_TOKEN or not CHANNEL_ID:
    raise ValueError("❌ BOT_TOKEN or CHANNEL_ID not set in environment!")

bot = Bot(token=BOT_TOKEN)
app = Flask(__name__)

# ---------------- Flask routes ----------------
@app.route("/")
def home():
    return "✅ Loot Fast Deals Bot is running (Thread Mode)"

@app.route("/health")
def health():
    return {"status": "ok"}

# ---------------- Deal Loop ----------------
def deal_loop():
    print("✅ Background deal loop started")
    while True:
        try:
            print("🔄 Loop tick - checking deals...")
            asyncio.run(
                bot.send_message(
                    chat_id=CHANNEL_ID,
                    text="🕒 Test tick from loop"
                )
            )
        except Exception as e:
            print("❌ Loop error:", e)
        time.sleep(60)  # 1 min interval

# ---------------- Main ----------------
def main():
    print("⚡ Bot starting in THREAD MODE")
    try:
        asyncio.run(
            bot.send_message(
                chat_id=CHANNEL_ID,
                text="✅ Bot running in THREAD MODE - deals every 1 min"
            )
        )
        print("✅ Startup message sent")
    except Exception as e:
        print("❌ Startup send failed:", e)

    # Start loop in background thread
    t = threading.Thread(target=deal_loop, daemon=True)
    t.start()

    # Run Flask server
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000)),
        debug=False,
        use_reloader=False
    )

if __name__ == "__main__":
    main()
