💰 Loot Fast Dealss — 24/7 Telegram Bot
This is a simple Telegram bot that automatically scrapes Amazon and Flipkart for new deals and posts them to a Telegram channel. It is designed for educational purposes and is not affiliated with Amazon or Flipkart.

🚀 Features
Automatic Deal Finding: The bot runs on a schedule to find new "loot" deals (items with significant discounts).

Price History: Tracks the price history of items to identify sudden price drops or all-time lows.

No API Needed: Uses web scraping to find deals, so you don't need any official affiliate APIs.

24/7 Operation: Designed to run continuously on a platform like Render.

⚙️ Setup
Prerequisites
Python 3.8 or higher.

A Telegram Bot Token (from @BotFather).

Your Telegram Channel ID (e.g., @your_channel_name). You need to add your bot to the channel and give it admin permissions to post messages.

1. Environment Variables
Create a .env file in your project directory to store your sensitive information. This file is not uploaded to GitHub for security reasons.

TELEGRAM_TOKEN=your_bot_token_here
CHANNEL_ID=@your_channel_id_here

2. Dependencies
Install the required Python packages using pip:

pip install -r requirements.txt

3. Running the Bot
To start the bot, simply run the Python script:

python app.py

4. Deployment on Render
This bot is designed to run 24/7 on a service like Render.

Create a New Web Service: In your Render dashboard, create a new web service.

Connect Your Repository: Connect the GitHub repository where you uploaded these files.

Configure Build & Start Commands:

Build Command: pip install -r requirements.txt

Start Command: python app.py

Add Environment Variables: Go to the "Environment" section of your service and add TELEGRAM_TOKEN and CHANNEL_ID with the correct values.

The bot will automatically build and start. Render will keep the process alive, so it will run continuously.

⚠️ Disclaimer
Scraping: The web scraping logic relies on the HTML structure of Amazon and Flipkart. This structure can change at any time, which may break the bot. You will need to inspect the page and update the CSS selectors in the app.py script if this happens.

Rate Limiting: Repeated scraping may lead to your server's IP address being temporarily blocked by the websites.
