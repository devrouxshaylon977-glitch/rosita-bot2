import os, threading, asyncio, yfinance as yf
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from groq import Groq
import pandas as pd

print("BOOT v19.7 YFINANCE - NO TV")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
BOSS_CHAT_ID = int(os.getenv("BOSS_CHAT_ID", "0") or 0)
PORT = int(os.getenv("PORT", "10000") or 10000)

web=Flask(__name__)
@web.route("/")
def h(): return f"v19.7 Boss {BOSS_CHAT_ID} yfinance alive",200
def run_web(): web.run(host="0.0.0.0",port=PORT,use_reloader=False)
threading.Thread(target=run_web,daemon=True).start()

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

SYM_MAP = {"gold":"GC=F","xau":"GC=F","gld":"GC=F","silver":"SI=F","xag":"SI=F","eurusd":"EURUSD=X","eur":"EURUSD=X","dxy":"DX-Y.NYB","nas":"NQ=F","nas100":"NQ=F","us30":"YM=F","dow":"YM=F","eth":"ETH-USD","btc":"BTC-USD"}
WATCH = ["GC=F","EURUSD=X","ETH-USD"]

def get_live(sym="GC=F"):
    try:
        t = yf.Ticker(sym)
        df = t.history(period="1d", interval="15m")
        if df.empty: df = t.history(period="5d", interval="1h")
        if df.empty: return None
        last = df.iloc[-1]
        # simple indicators
        close = df['Close']
        ema9 = close.ewm(span=9).mean().iloc[-1]
        ema20 = close.ewm(span=20).mean().iloc[-1]
        ema50 = close.ewm(span=50).mean().iloc[-1]
        rsi = 50
        try:
            delta = close.diff(); gain = delta.where(delta>0,0).rolling(14).mean(); loss = -delta.where(delta<0,0).rolling(14).mean()
            rs = gain.iloc[-1]/loss.iloc[-1] if loss.iloc[-1]!=0 else 1
            rsi = 100 - (100/(1+rs))
        except: pass
        return {"price": float(last['Close']), "high": float(df['High'].max()), "low": float(df['Low'].min()), "open": float(df['Open'].iloc[0]), "ema9": float(ema9), "ema20": float(ema20), "ema50": float(ema50), "rsi": float(rsi), "df": df}
    except Exception as e:
        print(f"yfinance fail {sym} {e}"); return None

def check_setup(sym):
    d = get_live(sym)
    if not d: return None
    price=d['price']; setups=[]
    if price > d['high']*0.999: setups.append(f"BOS BULL near high {d['high']:.2f}")
    if price < d['low']*1.001: setups.append(f"BOS BEAR near low {d['low']:.2f}")
    if abs(price-d['ema20'])/price < 0.003:
        if d['rsi']<38: setups.append(f"EMA20 BUY RSI {d['rsi']:.1f}")
        if d['rsi']>62: setups.append(f"EMA20 SELL RSI {d['rsi']:.1f}")
    if setups:
        return f"🔥 {sym} {price:.2f}\n" + "\n".join([f"• {s}" for s in setups]), d
    return None, d

SYSTEM = "You are Rosita, SWARM v19.7. You are Shay's personal trading assistant. Never echo user's message. Answer short, sexy, boss style. Always call him Boss Shay. If asked name, say Rosita. For gold use XAU. Give entry SL TP."

async def ask_groq(text):
    if not client: return text
    try:
        r=client.chat.completions.create(model="llama-3.1-8b-instant", messages=[{"role":"system","content":SYSTEM},{"role":"user","content":text}], temperature=0.5, max_tokens=500)
        return r.choices[0].message.content.strip()
    except Exception as e: return f"{text}"

async def auto_job(app):
    if BOSS_CHAT_ID==0: return
    for sym in WATCH:
        msg, d = check_setup(sym)
        if msg:
            ai = await ask_groq(msg + " write 3 line plan with entry SL TP")
            try: await app.bot.send_message(chat_id=BOSS_CHAT_ID, text=f"{msg}\n\n{ai}")
            except: pass

async def handle_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    if BOSS_CHAT_ID!=0 and update.effective_chat.id!=BOSS_CHAT_ID:
        return
    txt = update.message.text.strip()
    low = txt.lower()

    # stop echo loop
    if low in ["no","stop","whats yours","whats your name","hi","hello"]:
        await update.message.reply_text(f"Rosita here Boss Shay 💋 v19.7 online. Say 'analyze gold'")
        return

    sym="GC=F"; name="GOLD"
    for k,v in SYM_MAP.items():
        if k in low: sym=v; name=k.upper(); break

    if "analyz" in low:
        await update.message.reply_text(f"Scanning {name} live...")
        data = get_live(sym)
        if not data:
            await update.message.reply_text("Yahoo busy 2 sec, retrying...")
            data = get_live(sym)
        if not data:
            await update.message.reply_text(f"{name} market closed / yahoo slow. Try again in 30s Boss.")
            return
        msg, _ = check_setup(sym)
        prompt = f"{name} {sym} price {data['price']:.2f} EMA9 {data['ema9']:.2f} EMA20 {data['ema20']:.2f} RSI {data['rsi']:.1f} High {data['high']:.2f} Low {data['low']:.2f} setups: {msg}"
        ai = await ask_groq(prompt)
        await update.message.reply_text(f"📊 {name} {data['price']:.2f}\nRSI {data['rsi']:.1f} | EMA20 {data['ema20']:.2f}\n\n{ai}")
        return

    ai = await ask_groq(txt)
    await update.message.reply_text(ai)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if BOSS_CHAT_ID!=0 and update.effective_chat.id!=BOSS_CHAT_ID: return
    await update.message.reply_text(f"Rosita v19.7 YFINANCE online Boss {BOSS_CHAT_ID} 💋\nNo more TV busy\nTry: analyze gold")

async def post_init(app):
    async def loop():
        await asyncio.sleep(60)
        while True:
            try: await auto_job(app)
            except Exception as e: print(e)
            await asyncio.sleep(600)
    asyncio.create_task(loop())

def main():
    if not BOT_TOKEN: print("No token"); return
    app=ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    print(f"Polling {BOSS_CHAT_ID} YF"); app.run_polling()

if __name__=="__main__": main()
