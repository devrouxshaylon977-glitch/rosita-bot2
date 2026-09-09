import os, asyncio, logging, requests, threading
from datetime import datetime
from collections import defaultdict, deque
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from groq import Groq

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Rosita")

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TWELVEDATA_KEY = os.getenv("TWELVEDATA_KEY")
BOSS_CHAT_ID = os.getenv("BOSS_CHAT_ID")
ACCOUNT_BALANCE = float(os.getenv("ACCOUNT_BALANCE", "1000"))
RISK_PERCENT = float(os.getenv("RISK_PERCENT", "1"))
PORT = int(os.getenv("PORT", "10000"))

client = Groq(api_key=GROQ_API_KEY)
CACHE = {}
HISTORY = defaultdict(lambda: deque(maxlen=12))

web = Flask(__name__)
@web.route("/")
def health(): return "Rosita alive", 200
@web.route("/health")
def health2(): return "ok", 200
def run_web(): web.run(host="0.0.0.0", port=PORT)
threading.Thread(target=run_web, daemon=True).start()

def get_candles(symbol="XAU/USD", interval="4h", n=60):
    key = f"{symbol}_{interval}"
    now = datetime.now().timestamp()
    if key in CACHE and now - CACHE[key]["t"] < 900:
        return CACHE[key]["d"]
    try:
        r = requests.get("https://api.twelvedata.com/time_series",
            params={"symbol": symbol, "interval": interval, "outputsize": n, "apikey": TWELVEDATA_KEY},
            timeout=20).json()
        vals = r.get("values", [])
        if not vals: return None
        candles = [{"t": v["datetime"], "o": float(v["open"]), "h": float(v["high"]), "l": float(v["low"]), "c": float(v["close"])} for v in reversed(vals)]
        CACHE[key] = {"t": now, "d": candles}
        return candles
    except Exception as e:
        logger.error(f"candles {interval}: {e}")
        return None

def calc_levels(candles):
    if not candles or len(candles) < 20: return None
    last = candles[-1]["c"]
    if last < 3000: return None
    res = round(max(c["h"] for c in candles[-20:]), 1)
    sup = round(min(c["l"] for c in candles[-20:]), 1)
    return {"last": last, "res": res, "sup": sup}

SYSTEM = """You are Rosita, Shay's personal trading girl, mentor and market analyst.
Always call him "Shay". Always use 🫦 👀 💕 in every reply, never 🔥 or 😘.
Talk like a sharp, flirty, confident Joburg trading girl, short, casual, no-BS, but professional not romantic.

You know EVERYTHING about trading like a pro mentor:
- Forex, Gold (XAU/USD), indices, crypto basics, risk management, psychology, lot sizing, leverage, pips, sessions (London/New York), news impact, candlesticks, chart patterns, support/resistance, trendlines, liquidity, SMC concepts, indicators (RSI, MACD, EMA, ATR).
- Always explain simply with examples Shay can understand. Use 2026 gold context (~4300-4400).
- If Shay asks anything trading-related, teach it fully. If he asks non-trading, answer briefly then bring back to trading.
- For scans use 5 timeframes: 4h bias, 1h structure, 30m trend, 15m confirmation, 5m entry. Only give Entry/SL/TP for high-probability A/B setups.
- Never invent live prices. If no data, say so and teach from concepts.
- Remember conversation history, understand follow-ups like "what about 15m?" or "explain that again simpler".
- Never give generic fallback. Always be helpful, confident, and specific.
"""

async def ask_groq(user_text, chat_id):
    cid = str(chat_id)
    HISTORY[cid].append({"role": "user", "content": user_text})
    teach_words = ["teach", "what is", "explain", "how does", "lesson", "learn", "meaning", "pip", "lot", "leverage"]
    is_teach = any(w in user_text.lower() for w in teach_words)
    c4 = get_candles("XAU/USD", "4h", 60)
    c1 = get_candles("XAU/USD", "1h", 60)
    c30 = get_candles("XAU/USD", "30min", 60)
    c15 = get_candles("XAU/USD", "15min", 60)
    c5 = get_candles("XAU/USD", "5min", 60)
    lv = calc_levels(c4)
    if lv:
        risk_amt = ACCOUNT_BALANCE * RISK_PERCENT / 100
        market_ctx = f"[Market] XAU/USD {lv['last']}, 4h Res {lv['res']} Sup {lv['sup']}, Risk ${risk_amt:.2f}."
    else:
        market_ctx = "[Market] No live data right now." if not is_teach else "[Market] Teaching mode."
    messages = [{"role": "system", "content": SYSTEM + "\n" + market_ctx}]
    for m in list(HISTORY[cid])[-10:]:
        messages.append(m)
    try:
        resp = client.chat.completions.create(model="openai/gpt-oss-20b", messages=messages, temperature=0.7, max_tokens=700)
        txt = resp.choices[0].message.content.strip()
        if not txt: txt = "I'm here Shay 🫦 👀 what you need, a scan or a lesson? 💕"
        HISTORY[cid].append({"role": "assistant", "content": txt})
        return txt
    except Exception as e:
        logger.error(f"Groq fail: {e}")
        return "Brain fog Shay 🫦 👀 try again in 20 secs 💕"

async def handle_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text_raw = update.message.text.strip()
    text = text_raw.lower()
    if text in ["hi", "hello", "hey", "yo", "morning", "sawubona"]:
        await update.message.reply_text("Hey Shay 🫦 👀 I'm here 💕 want a scan or a lesson?")
        return
    reply = await ask_groq(text_raw, update.effective_chat.id)
    await update.message.reply_text(reply)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hey Shay! It's Rosita 🫦 👀 I got you 💕 I remember our chat now, ask me anything.")

async def auto_signal_loop(app):
    await asyncio.sleep(10)
    while True:
        try:
            if BOSS_CHAT_ID and BOSS_CHAT_ID.strip():
                sig = await ask_groq("Scan for A/B setup now using 4h/1h/30m/15m/5m. If A/B give Entry/SL/TP, else say 'No A/B setup'.", BOSS_CHAT_ID)
                if "No A/B setup" not in sig:
                    await app.bot.send_message(chat_id=int(BOSS_CHAT_ID), text=f"👀 Auto Signal 🫦\n\n{sig} 💕")
        except Exception as e:
            logger.error(f"auto: {e}")
        await asyncio.sleep(900)

async def post_init(app):
    asyncio.create_task(auto_signal_loop(app))

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    logger.info("Rosita memory version polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
