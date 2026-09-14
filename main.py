import os, threading, json, io
from datetime import datetime
from collections import defaultdict, deque
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from groq import Groq
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from tradingview_ta import TA_Handler, Interval

print("BOOT v19.5 AUTO ALERTS")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
BOSS_CHAT_ID = int(os.getenv("BOSS_CHAT_ID", "0") or 0)
PORT = int(os.getenv("PORT", "10000") or 10000)

web=Flask(__name__)
@web.route("/")
def h(): return f"v19.5 Boss {BOSS_CHAT_ID} Alive",200
def run_web(): web.run(host="0.0.0.0",port=PORT,use_reloader=False)
threading.Thread(target=run_web,daemon=True).start()

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
CACHE={}

SYM_MAP = {"gold":"XAU/USD","xau":"XAU/USD","silver":"XAG/USD","euru":"EUR/USD","eurusd":"EUR/USD","nas100":"NDX/USD","us30":"DJI/USD","dji":"DJI/USD","eth":"ETH/USD"}
WATCH = ["XAU/USD","XAG/USD","EUR/USD","ETH/USD","NDX/USD","DJI/USD"]
TV_MAP = {"XAU/USD": ("OANDA","XAUUSD","forex"),"XAG/USD": ("OANDA","XAGUSD","forex"),"EUR/USD": ("FX","EURUSD","forex"),"ETH/USD": ("BINANCE","ETHUSD","crypto"),"NDX/USD": ("NASDAQ","NDX","america"),"DJI/USD": ("FOREXCOM","US30","america"),"DXY/USD": ("CAPITALCOM","DXY","cfd"),"SPX/USD": ("FOREXCOM","SPX500","america")}

def get_tv(sym, tf):
    key=f"{sym}_{tf}"; now=datetime.now().timestamp()
    if key in CACHE and now-CACHE[key]['t']<60: return CACHE[key]['d']
    try:
        exch,symbol,screener=TV_MAP.get(sym,("OANDA","XAUUSD","forex"))
        h=TA_Handler(symbol=symbol,exchange=exch,screener=screener,interval=tf)
        a=h.get_analysis(); ind=a.indicators
        d={"price":ind.get("close"),"high":ind.get("high"),"low":ind.get("low"),"rsi":ind.get("RSI"),"ema9":ind.get("EMA9"),"ema20":ind.get("EMA20"),"ema50":ind.get("EMA50"),"ema200":ind.get("EMA200"),"vwap":ind.get("VWAP"),"r1":ind.get("Pivot.M.Classic.R1"),"s1":ind.get("Pivot.M.Classic.S1")}
        CACHE[key]={'t':now,'d':d}; return d
    except: return None

def check_setup(sym):
    m15=get_tv(sym, Interval.INTERVAL_15_MINUTES); h1=get_tv(sym, Interval.INTERVAL_1_HOUR); h4=get_tv(sym, Interval.INTERVAL_4_HOURS)
    if not m15 or not h1: return None
    price=m15['price']
    # OTE
    rng=h1['high']-h1['low'] if h1['high'] and h1['low'] else 0
    ote_low=h1['low']+rng*0.618 if rng else 0
    ote_high=h1['low']+rng*0.79 if rng else 0
    setup=[]
    # BOS
    if price>h1['high']: setup.append(f"BOS BULL BREAK {h1['high']:.2f}")
    if price<h1['low']: setup.append(f"BOS BEAR BREAK {h1['low']:.2f}")
    # EMA20 touch + RSI
    if m15['ema20'] and abs(price-m15['ema20'])/price<0.003:
        if m15['rsi'] and m15['rsi']<35: setup.append(f"EMA20 TOUCH + RSI {m15['rsi']:.1f} LONG")
        if m15['rsi'] and m15['rsi']>65: setup.append(f"EMA20 TOUCH + RSI {m15['rsi']:.1f} SHORT")
    # OTE retest
    if ote_low and ote_low <= price <= ote_high:
        bias="UP" if m15['ema9']>m15['ema20'] else "DOWN"
        setup.append(f"IN OTE {ote_low:.2f}-{ote_high:.2f} {bias}")
    if len(setup)>=2: # only alert if confluence 2+
        return f"🔥 {sym} {price:.2f}\n" + "\n".join([f"• {s}" for s in setup])
    return None

SYSTEM="You are SWARM v19.5 boss alert. Short signal."

async def ask_groq(text):
    if not client: return text
    try:
        r=client.chat.completions.create(model="llama-3.1-8b-instant",messages=[{"role":"system","content":SYSTEM},{"role":"user","content":text}],temperature=0.4,max_tokens=300)
        return r.choices[0].message.content.strip()
    except: return text

# AUTO JOB - runs every 10 min
async def auto_alert_job(context: ContextTypes.DEFAULT_TYPE):
    if BOSS_CHAT_ID==0: return
    for sym in WATCH:
        msg=check_setup(sym)
        if msg:
            ai=await ask_groq(msg + " - write 2 line trade plan with entry SL TP")
            try:
                await context.bot.send_message(chat_id=BOSS_CHAT_ID, text=f"{msg}\n\n{ai}")
            except: pass

async def handle_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    if BOSS_CHAT_ID!=0 and update.effective_chat.id!=BOSS_CHAT_ID: return
    low=update.message.text.lower(); sym="XAU/USD"; name="GOLD"
    for k,v in SYM_MAP.items():
        if k in low: sym=v; name=k.upper(); break
    if "analyze" in low or any(k in low for k in SYM_MAP.keys()):
        await update.message.reply_text(f"Scanning {name}...")
        tv15=get_tv(sym, Interval.INTERVAL_15_MINUTES); tv1h=get_tv(sym, Interval.INTERVAL_1_HOUR); tv4h=get_tv(sym, Interval.INTERVAL_4_HOURS)
        if not tv15: await update.message.reply_text("TV busy"); return
        conf=check_setup(sym) or "No confluence yet"
        ai=await ask_groq(f"{name} {tv15['price']:.2f} {conf}"); await update.message.reply_text(ai); return
    reply=await ask_groq(update.message.text); await update.message.reply_text(reply)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if BOSS_CHAT_ID!=0 and update.effective_chat.id!=BOSS_CHAT_ID: return
    await update.message.reply_text(f"v19.5 AUTO ALERTS ON for {BOSS_CHAT_ID} 💋\nI will DM you when setup hits: BOS + OTE + EMA20")

def main():
    if not BOT_TOKEN: print("No token"); return
    app=ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    # auto alerts every 10 min
    app.job_queue.run_repeating(auto_alert_job, interval=600, first=60)
    print(f"Polling Boss {BOSS_CHAT_ID} auto on"); app.run_polling()

if __name__=="__main__": main()
