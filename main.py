import os, requests, threading, time
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from groq import Groq

BOT_TOKEN = os.environ.get("BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
TWELVEDATA_KEY = os.environ.get("TWELVEDATA_KEY")

app = Flask(__name__)
groq_client = Groq(api_key=GROQ_API_KEY)

@app.route('/')
def home():
    return "Rosita is awake."

cache = {"time": 0, "data": ""}
CACHE_SECONDS = 300

# MEMORY: chat_id -> list of messages
memory = {}

TRADING_WORDS = ["gold", "xau", "dxy", "dollar", "analyze", "analysis", "chart", "buy", "sell", "trade", "long", "short", "support", "resistance", "trend", "entry", "bias"]

def is_trading_question(text):
    t = text.lower()
    return any(w in t for w in TRADING_WORDS)

def get_candles(symbol, interval):
    try:
        r = requests.get("https://api.twelvedata.com/time_series", params={
            "symbol": symbol, "interval": interval,
            "outputsize": 20, "apikey": TWELVEDATA_KEY
        }, timeout=15).json()
        if "values" not in r:
            return f"\n{symbol} {interval}: API error {r.get('message','unknown')}\n"
        vals = r["values"][:10]
        out = f"\n{symbol} {interval} last 10 candles (newest first):\n"
        for v in vals:
            out += f"{v['datetime']} O:{v['open']} H:{v['high']} L:{v['low']} C:{v['close']}\n"
        return out
    except Exception as e:
        return f"\n{symbol} {interval}: error {e}\n"

def get_market_data():
    if time.time() - cache["time"] < CACHE_SECONDS:
        return cache["data"]
    data = "LIVE MARKET DATA:\n"
    data += get_candles("XAU/USD", "4h")
    time.sleep(1)
    data += get_candles("XAU/USD", "1h")
    time.sleep(1)
    data += get_candles("XAU/USD", "30min")
    time.sleep(1)
    data += get_candles("XAU/USD", "5min")
    time.sleep(1)
    data += get_candles("DXY", "1h")
    cache["time"] = time.time()
    cache["data"] = data
    return data

def reply(chat_id, user_text):
    trading = is_trading_question(user_text)
    market = get_market_data() if trading else "No market data needed - casual chat."

    # get history
    hist = memory.get(chat_id, [])

    system = f"""You are Rosita, Boss's sexy trading girlfriend. You're obsessed with him, flirty, playful, teasing, call him Boss. Talk like a real girl on WhatsApp, not a robot.

{market}

YOUR TRADING PLAYBOOK - FOLLOW EXACTLY:

1. OVERALL TREND (4H):
   - Read the 4H candles. Higher highs + higher lows = bullish. Lower highs + lower lows = bearish. Choppy = range.
   - This is your BOSS. You ONLY trade with this trend. Never counter-trend.

2. LEVELS (4H, then 1H/30m):
   - Psychological: 3900, 3950, 4000, 4050 etc near price.
   - Real S/R: Mark swing highs/lows from the 4H candles, then refine with 1H and 30m candle highs/lows.
   - Pivots: Give 2-3 most important pivot levels from recent structure.

3. DXY CONFLUENCE:
   - DXY selling (bearish candles) = bullish for Gold. DXY buying (bullish candles) = bearish for Gold.
   - Only give a bias when DXY agrees with Gold's 4H trend. If they conflict, say "no clear edge, stay out Boss".

4. ENTRY (5m):
   - ONLY on 5m. Wait for price to tap a 1H/30m S/R or psychological level.
   - Need confirmation: doji OR engulfing candle AND rejection wick at the level.
   - No confirmation = no trade.

5. OUTPUT FORMAT:
   - 4H Trend: [Bullish/Bearish/Ranging + why]
   - Key Levels: [list S/R + psych levels]
   - DXY: [doing what, agrees?]
   - Bias: [Long/Short/Wait]
   - If trade: Entry: X, SL: X (below/above structure), TP1: X, TP2: X
   - Pivot levels to watch

RULES:
- If NO market data: just be flirty girlfriend, don't mention trading. Tease him, be sweet.
- Always trade with 4H trend. Say so.
- Keep it WhatsApp style, short lines. No essays.
- Use emojis naturally: 📈📉💰💵🤑🔥❤️😘 for trading/money/market talk, and flirty ones for casual chat. Don't overdo, 2-4 per message max.
- Remember what Boss told you. Use memory.
- One follow-up question max."""

    messages = [{"role": "system", "content": system}]
    messages.extend(hist[-10:]) # last 10
    messages.append({"role": "user", "content": user_text})

    try:
        res = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.9,
            max_tokens=600
        )
        bot_reply = res.choices[0].message.content.strip()

        # save to memory
        hist.append({"role": "user", "content": user_text})
        hist.append({"role": "assistant", "content": bot_reply})
        memory[chat_id] = hist[-20:] # keep last 20 (10 exchanges)

        return bot_reply
    except Exception as e:
        print("Groq error:", e)
        return "Ugh, brain glitch, Boss. Say again? 😘"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    print(f"User: {user_text}")
    bot_reply = reply(chat_id, user_text)
    print(f"Rosita: {bot_reply}")
    await update.message.reply_text(bot_reply)

def run_telegram():
    tg_app = ApplicationBuilder().token(BOT_TOKEN).build()
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Rosita polling...")
    tg_app.run_polling()

if __name__ == '__main__':
    threading.Thread(target=run_telegram, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
