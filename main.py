import os, threading, json, io
from datetime import datetime, timezone
from collections import defaultdict, deque
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from groq import Groq
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from tradingview_ta import TA_Handler, Interval

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
PORT = int(os.getenv("PORT", "10000") or 10000)
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
        a=h.get_analysis()
        ind=a.indicators
        d={
          "price":ind.get("close"), "high":ind.get("high"), "low":ind.get("low"), "open":ind.get("open"),
          "rsi":ind.get("RSI"), "ema9":ind.get("EMA9"), "ema20":ind.get("EMA20"), "ema50":ind.get("EMA50"), "ema200":ind.get("EMA200"),
          "bb_up":ind.get("BB.upper"), "bb_low":ind.get("BB.lower"), "pivot":ind.get("Pivot.M.Classic.Middle"),
          "s1":ind.get("Pivot.M.Classic.S1"), "s2":ind.get("Pivot.M.Classic.S2"), "r1":ind.get("Pivot.M.Classic.R1"), "r2":ind.get("Pivot.M.Classic.R2"),
          "vol":ind.get("volume"), "vol_ma":ind.get("Vol.MA20"), "vwap":ind.get("VWAP"), "mfi":ind.get("MFI"), "cmf":ind.get("ChaikinMoneyFlow"),
          "rec":a.summary.get("RECOMMENDATION"),
        }
        CACHE[key]={'t':now,'d':d}; return d
    except Exception as e:
        # fallback try TVC if broker fails
        try:
            fallback = {"DXY/USD":("TVC","DXY","america"),"SPX/USD":("FOREXCOM","SPX500","america"),"DJI/USD":("FOREXCOM","DJI","america"),"WTI/USD":("NYMEX","CL1!","cfd")}
            if sym in fallback:
                exch,symbol,screener=fallback[sym]
                h=TA_Handler(symbol=symbol,exchange=exch,screener=screener,interval=tf)
                a=h.get_analysis(); ind=a.indicators
                d={"price":ind.get("close"),"high":ind.get("high"),"low":ind.get("low"),"open":ind.get("open"),"rsi":ind.get("RSI"),"ema9":ind.get("EMA9"),"ema20":ind.get("EMA20"),"ema50":ind.get("EMA50"),"ema200":ind.get("EMA200"),"bb_up":ind.get("BB.upper"),"bb_low":ind.get("BB.lower"),"pivot":ind.get("Pivot.M.Classic.Middle"),"s1":ind.get("Pivot.M.Classic.S1"),"s2":ind.get("Pivot.M.Classic.S2"),"r1":ind.get("Pivot.M.Classic.R1"),"r2":ind.get("Pivot.M.Classic.R2"),"vol":ind.get("volume"),"vol_ma":ind.get("Vol.MA20"),"vwap":ind.get("VWAP"),"mfi":ind.get("MFI"),"cmf":ind.get("ChaikinMoneyFlow"),"rec":a.summary.get("RECOMMENDATION")}
                CACHE[key]={'t':now,'d':d}; return d
        except: pass
        return None

def get_session_levels(sym):
    daily = get_tv(sym, Interval.INTERVAL_1_DAY)
    h1 = get_tv(sym, Interval.INTERVAL_1_HOUR)
    if not daily: return "\nSession: no data\n", None
    pdh = daily.get('high'); pdl = daily.get('low')
    sh = h1.get('high') if h1 else pdh; sl = h1.get('low') if h1 else pdl
    price = h1.get('price') if h1 else daily.get('price')
    txt = f"\nSession Liquidity:\n- PDH {pdh:.2f} PDL {pdl:.2f}\n- Sess H {sh:.2f} L {sl:.2f}\n"
    if price:
        if price > pdh: txt+=f"- ABOVE PDH = buy sweep -> short\n"
        elif price < pdl: txt+=f"- BELOW PDL = sell sweep -> long ✅\n"
        else: txt+=f"- Between PDH/PDL\n"
    return txt, {"pdh":pdh,"pdl":pdl,"sh":sh,"sl":sl}

def get_trendline_confluence(sym):
    m15 = get_tv(sym, Interval.INTERVAL_15_MINUTES); h1 = get_tv(sym, Interval.INTERVAL_1_HOUR); h4 = get_tv(sym, Interval.INTERVAL_4_HOURS)
    if not m15 or not h1 or not h4: return "\nTrendline: no data\n", None
    def ema_bias(tf):
        if tf['ema9'] and tf['ema20'] and tf['ema50']:
            if tf['ema9']>tf['ema20']>tf['ema50']: return "UPTREND"
            if tf['ema9']<tf['ema20']<tf['ema50']: return "DOWNTREND"
        return "RANGE"
    b15=ema_bias(m15); b1=ema_bias(h1); b4=ema_bias(h4)
    txt=f"\nTrendline BOS/CHoCH:\n- 15m {b15} | 1h {b1} | 4h {b4}\n"
    if m15['price'] > h1['high']: txt+=f"- BOS BULLISH BREAK {h1['high']:.2f} ✅\n"
    elif m15['price'] < h1['low']: txt+=f"- BOS BEARISH BREAK {h1['low']:.2f} ✅\n"
    if b4=="UPTREND" and b15=="DOWNTREND": txt+=f"- CHoCH pullback long\n"
    if b4=="DOWNTREND" and b15=="UPTREND": txt+=f"- CHoCH pullback short\n"
    if m15['ema20'] and abs(m15['price']-m15['ema20'])/m15['price']<0.002: txt+=f"- Touch EMA20 trendline {m15['ema20']:.2f} ✅\n"
    return txt, {"bias_15":b15,"bias_1h":b1,"bias_4h":b4,"h1_high":h1['high'],"h1_low":h1['low']}

def get_psych_levels(price, sym):
    if "XAU" in sym: step=10
    elif "DJI" in sym or "NDX" in sym: step=100
    elif "XAG" in sym: step=0.5
    else: step=0.002
    base=round(price/step)*step
    return [base-step*2, base-step, base, base+step, base+step*2]

def get_fib_levels(tv1h, tv15):
    base = tv1h if tv1h and tv1h.get('high') else tv15
    if not base or not base.get('high'): return None
    high=base['high']; low=base['low']; rng=high-low
    if rng<=0: return None
    return {"high":high, "low":low, "618":low+rng*0.618, "79":low+rng*0.79, "ote_low":low+rng*0.618, "ote_high":low+rng*0.79}

def get_intermarket(sym):
    dxy=get_tv("DXY/USD", Interval.INTERVAL_1_HOUR); spx=get_tv("SPX/USD", Interval.INTERVAL_1_HOUR); oil=get_tv("WTI/USD", Interval.INTERVAL_1_HOUR)
    txt="\nIntermarket FILTER (Broker Live):\n"
    if dxy and dxy.get('price'): txt+=f"- DXY CAPITALCOM {dxy['price']:.2f} RSI {dxy['rsi']:.1f} {'STRONG bear Gold' if dxy['rsi']>60 else 'WEAK bull Gold' if dxy['rsi']<40 else 'neutral'}\n"
    if spx and spx.get('price'): txt+=f"- SPX FOREXCOM {spx['price']:.2f} RSI {spx['rsi']:.1f}\n"
    if oil and oil.get('price'): txt+=f"- OIL OANDA {oil['price']:.2f} {oil['rec']}\n"
    return txt

def build_confluence(tv15, tv1h, tv4h, price, sym):
    fib=get_fib_levels(tv1h, tv15)
    txt=""
    if fib: txt+=f"Fib OTE {fib['ote_low']:.2f}-{fib['ote_high']:.2f} {'IN OTE ✅' if fib['ote_low']<=price<=fib['ote_high'] else 'outside'}\n"
    if tv1h and tv1h['r1']: txt+=f"S/R R1 {tv1h['r1']:.2f} S1 {tv1h['s1']:.2f}\n"
    psych=get_psych_levels(price, sym); txt+=f"Psych {' / '.join([f'{p:.2f}' for p in psych])}\n"
    if tv15: txt+=f"EMA {tv15['ema9']:.2f}/{tv15['ema20']:.2f}/{tv15['ema50']:.2f} VWAP {tv15.get('vwap',0):.2f}\n"
    if tv15 and tv15.get('mfi'): txt+=f"- MFI {tv15['mfi']:.1f} CMF {tv15.get('cmf',0):.3f}\n"
    sess_txt, sess_lvls = get_session_levels(sym); txt+=sess_txt
    trend_txt, trend_lvls = get_trendline_confluence(sym); txt+=trend_txt
    txt+=get_intermarket(sym)
    return txt, fib, sess_lvls, trend_lvls

def make_chart(name, sym, tv, fib, sess, trend):
    try:
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(7,4), facecolor='#070709')
        ax.set_facecolor('#070709')
        levels=[tv.get('ema200'),tv.get('ema50'),tv.get('ema20'),tv.get('ema9'),tv['price']]
        levels=[x for x in levels if x]
        ax.plot(levels, color='#14d47a', linewidth=2.2, marker='o')
        if fib:
            ax.axhline(fib['618'], color='#ff9500', linestyle='--', linewidth=1.1)
            ax.axhline(fib['79'], color='#ff3b30', linestyle='--', linewidth=1.1)
            ax.axhspan(fib['ote_low'], fib['ote_high'], color='#ff9500', alpha=0.18)
        if sess:
            ax.axhline(sess['pdh'], color='#9d4edd', linestyle=':', linewidth=1.0)
            ax.axhline(sess['pdl'], color='#9d4edd', linestyle=':', linewidth=1.0)
        if tv.get('ema20'): ax.axhline(tv['ema20'], color='#00d4ff', linestyle='-', linewidth=0.9, alpha=0.7)
        if trend and trend.get('h1_high'): ax.axhline(trend['h1_high'], color='white', linestyle='-.', linewidth=0.7, alpha=0.5)
        title=f"{name} {tv['price']:.2f} OTE {fib['ote_low']:.2f}-{fib['ote_high']:.2f} {trend['bias_1h'] if trend else ''}" if fib and trend else f"{name} {tv['price']:.2f}"
        ax.set_title(title, fontsize=7, color='white')
        ax.tick_params(colors='#8a8a90', labelsize=6)
        for s in ax.spines.values(): s.set_color('#222')
        plt.tight_layout()
        buf=io.BytesIO(); plt.savefig(buf, format='png', dpi=180, facecolor='#070709'); plt.close(fig); buf.seek(0); return buf
    except: return None

SYSTEM="""You are SWARM v19.3 NO TVC Broker Live. Call user Shay.
Tradable: XAU XAG EUR ETH NDX DJI. DXY SPX OIL FILTER ONLY but now broker live: CAPITALCOM:DXY, FOREXCOM:SPX500, FOREXCOM:US30, OANDA:WTICOUSD.

12 Confluences: Fib OTE, S/R, Psych, EMA, BB, VWAP, OrderFlow, DXY broker, SPX broker, OIL broker, Session PDH/PDL, Trendline BOS/CHoCH.

Output: Bias, Harleen PASS/VETO, Magna Snipe with trendline + OTE + session sweep + broker intermarket, Entry, SL, TPs, Confluences.
"""

async def ask_groq(text, chat_id):
    cid=str(chat_id); HISTORY[cid].append({"role":"user","content":text}); mem=LONG_MEM.get(cid,"")
    if not client: return "No brain"
    msgs=[{"role":"system","content":SYSTEM+f"\nMemory {mem}"}]
    for m in list(HISTORY[cid])[-8:]: msgs.append(m)
    try:
        r=client.chat.completions.create(model="openai/gpt-oss-20b",messages=msgs,temperature=0.5,max_tokens=1500)
        txt=r.choices[0].message.content.strip(); HISTORY[cid].append({"role":"assistant","content":txt}); return txt
    except: return "Brain fog Shay"

async def handle_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    low=update.message.text.lower().strip()
    sym="XAU/USD"; name="GOLD"
    for k,v in SYM_MAP.items():
        if k in low: sym=v; name=k.upper(); break
    if low in ["hi","hello","hey"]:
        await update.message.reply_text("Hey Shay 💋 v19.3 NO TVC Broker Live\nanalyze gold / trend gold / chart gold"); return
    if "chart" in low:
        tv15=get_tv(sym, Interval.INTERVAL_15_MINUTES); tv1h=get_tv(sym, Interval.INTERVAL_1_HOUR)
        fib=get_fib_levels(tv1h, tv15); sess_txt, sess_lvls=get_session_levels(sym); trend_txt, trend_lvls=get_trendline_confluence(sym)
        buf=make_chart(name,sym,tv15,fib,sess_lvls,trend_lvls)
        cap=f"📈 {name} {tv15['price']:.2f} Broker Live NO TVC\n{fib['ote_low']:.2f}-{fib['ote_high']:.2f} {trend_txt[:400]}" if fib else f"{name}"
        if buf: await update.message.reply_photo(photo=buf, caption=cap[:900])
        else: await update.message.reply_text(cap); return
    if "analyze" in low or any(k in low for k in SYM_MAP.keys()):
        await update.message.reply_text(f"Scanning {name} Broker Live NO TVC + 12 Confluences...")
        tv1=get_tv(sym, Interval.INTERVAL_1_MINUTE); tv15=get_tv(sym, Interval.INTERVAL_15_MINUTES)
        tv1h=get_tv(sym, Interval.INTERVAL_1_HOUR); tv4h=get_tv(sym, Interval.INTERVAL_4_HOURS)
        if not tv15: await update.message.reply_text("TV busy"); return
        price=tv1['price'] if tv1 else tv15['price']
        conf,fib,sess,trend=build_confluence(tv15, tv1h, tv4h, price, sym)
        sig=await ask_groq(f"{name} {sym} {price:.2f} {conf} 4h {tv4h['rec'] if tv4h else ''}", update.effective_chat.id)
        await update.message.reply_text(sig)
        buf=make_chart(name,sym,tv15,fib,sess,trend)
        if buf: await update.message.reply_photo(photo=buf, caption=f"v19.3 {name} {price:.2f} NO TVC")
        return
    if "trend" in low or "session" in low or "pdh" in low:
        tv15=get_tv(sym, Interval.INTERVAL_15_MINUTES); tv1h=get_tv(sym, Interval.INTERVAL_1_HOUR); tv4h=get_tv(sym, Interval.INTERVAL_4_HOURS)
        price=tv15['price'] if tv15 else 0
        conf,fib,sess,trend=build_confluence(tv15, tv1h, tv4h, price, sym)
        await update.message.reply_text(f"📈 {name} {price:.2f}\n{conf}"); return
    reply=await ask_groq(update.message.text, update.effective_chat.id)
    await update.message.reply_text(reply)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("v19.3 NO TVC Broker Live online 💋 analyze gold")
def main():
    app=ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    app.run_polling()
if __name__=="__main__": main()
