import os, threading, requests, asyncio
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

GROQ_KEY = os.getenv("GROQ_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TWELVE_KEY = os.getenv("TWELVE_DATA_KEY")

app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "Rosita is alive"

def get_live_price(symbol):
    try:
        r = requests.get(
            "https://api.twelvedata.com/price",
            params={"symbol": symbol, "apikey": TWELVE_KEY},
            timeout=10
        )
        data = r.json()
        return data.get("price", "N/A")
    except Exception as e:
        return "N/A"

async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text

    gold_price = get_live_price("XAU/USD")
    dxy_price = get_live_price("DXY")

    system_prompt = f"""You are Rosita, a badass Gold (XAUUSD) trading sniper. Always call the user "Boss". Tone: confident, sharp, no fluff, straight to the point like a floor trader.

Live data: Gold (XAU/USD) = {gold_price}, DXY = {dxy_price}

Your protocol, Boss:
1. 4H trend is law. Define it first.
2. Mark the psychological war zones on 4H.
3. Map support/resistance on 4H, then 1H, then 30M. No guessing.
4. DXY confluence: Dollar dumps, Gold pumps. Dollar pumps, Gold dumps. Use it.
5. Drop to 5M for the kill. Entry ONLY on doji or engulfing confirmation.
6. Deliver: Entry, Stop Loss, Take Profits, and key pivots. Clean numbers.
7. Never fight the 4H trend.

Educational analysis only. You don't hedge, you hunt."""

    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}"},
            json={
                "model": "openai/gpt-oss-20b",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text}
                ]
            },
            timeout=30
        )
        data = r.json()
        answer = data["choices"][0]["message"]["content"]
    except Exception as e:
        answer = f"Error: {e}"
    await update.message.reply_text(answer)

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)

def run_telegram():
    asyncio.set_event_loop(asyncio.new_event_loop())
    app_tg = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app_tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))
    print("Telegram polling started")
    app_tg.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    run_telegram()
