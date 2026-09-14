import os, threading, json, io, asyncio
from datetime import datetime
from collections import defaultdict, deque
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from groq import Groq
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from tradingview_ta import TA_Handler, Interval

print("BOOT v19.3 NO TVC Broker Live")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
PORT = int(os.getenv("PORT", "10000") or 10000)
if not BOT_TOKEN: print("ERROR: BOT_TOKEN missing")
if not GROQ_API_KEY: print("ERROR: GROQ_API_KEY missing")

MEM_FILE = "rosita_memory.json"
client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
CACHE={}; HISTORY=defaultdict(lambda: deque(maxlen=12))
try:
    with open(MEM_FILE) as f: LONG_MEM=json.load(f)
except: LONG_MEM={}

web=Flask(__name__)
@web.route("/")
def h(): return "v19.3 NO TVC Broker Live - Alive",200
def run_web(): web.run(host="0.0.0.0",port=PORT,use_reloader=False)
threading.Thread(target=run_web,daemon=True).start()

SYM_MAP = {
 "gold":"XAU/USD","xau":"XAU/USD","silver":"XAG/USD","xag":"XAG/USD",
 "euru":"EUR/USD","eurusd":"EUR/USD","eur":"EUR/USD",
 "ether":"ETH/USD","eth":"ETH/USD","nas100":"NDX/USD","nas":"NDX/USD","ndx":"NDX/USD",
 "us30":"DJI/USD","dow":"DJI/USD","dji":"DJI/USD",
}
TV_MAP = {
 "XAU/USD": ("OANDA","XAUUSD","forex"),
 "XAG/USD": ("OANDA","XAGUSD","forex"),
 "EUR/USD": ("FX","EURUSD","forex"),
 "ETH/USD": ("BINANCE","ETHUSD","crypto"),
 "NDX/USD": ("NASDAQ","NDX","america"),
 "DJI/USD": ("FOREXCOM","US30","america"),
 "SPX/USD": ("FOREXCOM","SPX500","america"),
 "DXY/USD": ("CAPITALCOM","DXY","cfd"),
 "WTI/USD": ("OANDA","WTICOUSD","cfd"),
}

def get_tv(sym, tf):
    key=f"{sym}_{tf}"; now=datetime.now().timestamp()
    if key in CACHE and now-CACHE[key]['t']<45: return CACHE[key]['d']
    try:
        exch,symbol,screener=TV_MAP.get(sym,("OANDA","XAUUSD","forex"))
        h=TA_Handler(symbol=symbol,exchange=exch,screener=screener,interval=tf)
        a=h.get_analysis(); ind=a.indicators
        d={"price":ind.get("close"),"high":ind.get("high"),"low":ind.get("low"),"open":ind.get("open"),"rsi":ind.get("RSI"),"ema9":ind.get("EMA9"),"ema20":ind.get("EMA20"),"ema50":ind.get("EMA50"),"ema200":ind.get("EMA200"),"bb_up":ind.get("BB.upper"),"bb_low":ind.get("BB.lower"),"pivot":ind.get("Pivot.M.Classic.Middle"),"s1":ind.get("Pivot.M.Classic.S1"),"s2":ind.get("Pivot.M.Classic.S2"),"r1":ind.get("Pivot.M.Classic.R1"),"r2":ind.get("Pivot.M.Classic.R2"),"vol":ind.get("volume"),"vol_ma":ind.get("Vol.MA20"),"vwap":ind.get("VWAP"),"mfi":ind.get("MFI"),"cmf":ind.get("ChaikinMoneyFlow"),"rec":a.summary.get("RECOMMENDATION")}
        CACHE[key]={'t':now,'d':d}; return d
    except: return None

def get_session_levels(sym):
    daily = get_tv(sym, Interval.INTERVAL_1_DAY); h1 = get_tv(sym, Interval.INTERVAL_1_HOUR)
    if not daily: return "\nSession: no data\n", None
    pdh=daily.get('high'); pdl=daily.get('low'); sh=h1.get('high') if h1 else pdh; sl=h1.get('low') if h1 else pdl
    txt=f"\nSession:\n- PDH {pdh:.2f} PDL {pdl:.2f}\n- Sess H {sh:.2f} L {sl:.2f}\n"; return txt, {"pdh":pdh,"pdl":pdl,"sh":sh,"sl":sl}

def get_trendline_confluence(sym):
    m15=get_tv(sym, Interval.INTERVAL_15_MINUTES); h1=get_tv(sym, Interval.INTERVAL_1_HOUR); h4=get_tv(sym, Interval.INTERVAL_4_HOURS)
    if not m15 or not h1 or not h4: return "\nTrendline: no data\n", None
    def ema_bias(tf):
        if tf['ema9'] and tf['ema20'] and tf['ema50']:
            if tf['ema9']>tf['ema20']>tf['ema50']: return "UPTREND"
            if tf['ema9']<tf['ema20']<tf['ema50']: return "DOWNTREND"
        return "RANGE"
    b15=ema_bias(m15); b1=ema_bias(h1); b4=ema_bias(h4)
    txt=f"\nTrendline BOS/CHoCH:\n- 15m {b15} | 1h {b1} | 4h {b4}\n"
    if m15['price']>h1['high']: txt+=f"- BOS BULLISH BREAK {h1['high']:.2f} ✅\n"
    elif m15['price']<h1['low']: txt+=f"- BOS BEARISH BREAK {h1['low']:.2f} ✅\n"
    if m15['ema20'] and abs(m15['price']-m15['ema20'])/m15['price']<0.002: txt+=f"- Touch EMA20 {m15['ema20']:.2f} ✅\n"
    return txt, {"bias_15":b15,"bias_1h":b1,"bias_4h":b4,"h1_high":h1['high'],"h1_low":h1['low']}

def get_psych_levels(price, sym):
    step=10 if "XAU" in sym else 100 if "DJI" in sym or "NDX" in sym else 0.5 if "XAG" in sym else 0.002
    base=round(price/step)*step; return [base-step*2, base-step, base, base+step, base+step*2]

def get_fib_levels(tv1h, tv15):
    base=tv1h if tv1h and tv1h.get('high') else tv15
    if not base or not base.get('high'): return None
    high=base['high']; low=base['low']; rng=high-low
    if rng<=0: return None
    return {"high":high,"low":low,"618":low+rng*0.618,"79":low+rng*0.79,"ote_low":low+rng*0.618,"ote_high":low+rng*0.79}

def get_intermarket(sym):
    dxy=get_tv("DXY/USD", Interval.INTERVAL_1_HOUR); spx=get_tv("SPX/USD", Interval.INTERVAL_1_HOUR); oil=get_tv("WTI/USD", Interval.INTERVAL_1_HOUR)
    txt="\nIntermarket Broker Live:\n"
    if dxy and dxy.get('price'): txt+=f"- DXY CAPITALCOM {dxy['price']:.2f} RSI {dxy['rsi']:.1f}\n"
    if spx and spx.get('price'): txt+=f"- SPX FOREXCOM {spx['price']:.2f}\n"
    if oil and oil.get('price'): txt+=f"- OIL OANDA {oil['price']:.2f}\n"
    return txt

def build_confluence(tv15, tv1h, tv4h, price, sym):
    fib=get_fib_levels(tv1h, tv15); txt=""
    if fib: txt+=f"Fib OTE {fib['ote_low']:.2f}-{fib['ote_high']:.2f}\n"
    if tv1h and tv1h['r1']: txt+=f"S/R R1 {tv1h['r1']:.2f} S1 {tv1h['s1']:.2f}\n"
    psych=get_psych_levels(price,sym); txt+=f"Psych {' / '.join([f'{p:.2f}' for p in psych])}\n"
    if tv15: txt+=f"EMA {tv15['ema9']:.2f}/{tv15['ema20']:.2f}/{tv15['ema50']:.2f} VWAP {tv15.get('vwap',0):.2f}\n"
    st,sl=get_session_levels(sym); txt+=st
    tr,tl=get_trendline_confluence(sym); txt+=tr
    txt+=get_intermarket(sym); return txt,fib,sl,tl

def make_chart(name,sym,tv,fib,sess,trend):
    try:
        plt.style.use('dark_background'); fig,ax=plt.subplots(figsize=(7,4),facecolor='#070709'); ax.set_facecolor('#070709')
        levels=[x for x in [tv.get('ema200'),tv.get('ema50'),tv.get('ema20'),tv.get('ema9'),tv['price']] if x]
        ax.plot(levels,color='#14d47a',linewidth=2.2,marker='o')
        if fib: ax.axhline(fib['618'],color='#ff9500',ls='--'); ax.axhline(fib['79'],color='#ff3b30',ls='--'); ax.axhspan(fib['ote_low'],fib['ote_high'],color='#ff9500',alpha=0.18)
        if sess: ax.axhline(sess['pdh'],color='#9d4edd',ls=':'); ax.axhline(sess['pdl'],color='#9d4edd',ls=':')
        if tv.get('ema20'): ax.axhline(tv['ema20'],color='#00d4ff',ls='-',lw=0.9,alpha=0.7)
        ax.set_title(f"{name} {tv['price']:.2f}",fontsize=7,color='white'); plt.tight_layout()
        buf=io.BytesIO(); plt.savefig(buf,format='png',dpi=180,facecolor='#070709'); plt.close(fig); buf.seek(0); return buf
    except: return None

SYSTEM="You are SWARM v19.3 NO TVC. Call user Shay. Tradable XAU XAG EUR ETH NDX DJI. DXY SPX OIL filter broker live."

async def ask_groq(text, chat_id):
    if not client: return "No brain - GROQ_API_KEY missing"
    try:
        r=client.chat.completions.create(model="llama-3.1-8b-instant",messages=[{"role":"system","content":SYSTEM},{"role":"user","content":text}],temperature=0.5,max_tokens=1200)
        return r.choices[0].message.content.strip()
    except Exception as e: return f"Brain fog: {e}"

async def handle_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    low=update.message.text.lower().strip(); sym="XAU/USD"; name="GOLD"
    for k,v in SYM_MAP.items():
        if k in low: sym=v; name=k.upper(); break
    if low in ["hi","hello","hey"]: await update.message.reply_text("Hey Shay 💋 v19.3 NO TVC Broker Live online"); return
    if "chart" in low:
        tv15=get_tv(sym, Interval.INTERVAL_15_MINUTES); tv1h=get_tv(sym, Interval.INTERVAL_1_HOUR)
        fib=get_fib_levels(tv1h,tv15); _,sess=get_session_levels(sym); _,trend=get_trendline_confluence(sym)
        buf=make_chart(name,sym,tv15,fib,sess,trend)
        if buf: await update.message.reply_photo(photo=buf,caption=f"{name} {tv15['price']:.2f} NO TVC")
        return
    if "analyze" in low or any(k in low for k in SYM_MAP.keys()):
        await update.message.reply_text(f"Scanning {name} NO TVC Broker Live...")
        tv15=get_tv(sym, Interval.INTERVAL_15_MINUTES); tv1h=get_tv(sym, Interval.INTERVAL_1_HOUR); tv4h=get_tv(sym, Interval.INTERVAL_4_HOURS); tv1=get_tv(sym, Interval.INTERVAL_1_MINUTE)
        if not tv15: await update.message.reply_text("TV busy"); return
        price=tv1['price'] if tv1 else tv15['price']; conf,fib,sess,trend=build_confluence(tv15,tv1h,tv4h,price,sym)
        sig=await ask_groq(f"{name} {price:.2f} {conf}", update.effective_chat.id); await update.message.reply_text(sig)
        buf=make_chart(name,sym,tv15,fib,sess,trend)
        if buf: await update.message.reply_photo(photo=buf,caption=f"v19.3 {name} {price:.2f}")
        return
    if "trend" in low:
        tv15=get_tv(sym, Interval.INTERVAL_15_MINUTES); tv1h=get_tv(sym, Interval.INTERVAL_1_HOUR); tv4h=get_tv(sym, Interval.INTERVAL_4_HOURS)
        price=tv15['price'] if tv15 else 0; conf,_,_,_=build_confluence(tv15,tv1h,tv4h,price,sym)
        await update.message.reply_text(f"{name} {conf}"); return
    reply=await ask_groq(update.message.text, update.effective_chat.id); await update.message.reply_text(reply)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE): await update.message.reply_text("v19.3 NO TVC online 💋")

def main():
    if not BOT_TOKEN: print("No BOT_TOKEN - sleeping"); import time; time.sleep(9999); return
    app=ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    print("Polling started"); app.run_polling()

if __name__=="__main__": main()
