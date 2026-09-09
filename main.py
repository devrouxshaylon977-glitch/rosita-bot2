import os, requests, threading, time, asyncio, re
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes
from groq import Groq
from datetime import datetime, timezone

BOT_TOKEN = os.environ.get("BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
TWELVEDATA_KEY = os.environ.get("TWELVEDATA_KEY")
BOSS_CHAT_ID_RAW = os.environ.get("BOSS_CHAT_ID")
ACCOUNT_BALANCE = float(os.environ.get("ACCOUNT_BALANCE", "1000"))
RISK_PERCENT = float(os.environ.get("RISK_PERCENT", "1"))

def get_boss_id():
    try:
        return int(BOSS_CHAT_ID_RAW) if BOSS_CHAT_ID_RAW else None
    except:
        return None
BOSS_ID = get_boss_id()

app = Flask(__name__)
groq_client = None
def get_groq():
    global groq_client
    if groq_client is None:
        groq_client = Groq(api_key=GROQ_API_KEY)
    return groq_client

@app.route('/')
def home(): return "Rosita v5.1 awake."

cache = {"time":0,"data":"","news_time":0,"news":""}
CACHE_SECONDS=900
NEWS_CACHE_SECONDS=3600
memory={}
tg_app_global=None
user_settings={}

def get_user_risk(chat_id):
    s = user_settings.get(chat_id, {})
    return s.get("balance", ACCOUNT_BALANCE), s.get("risk", RISK_PERCENT)

def calc_lot(balance, risk_pct, entry, sl):
    try:
        risk_money = balance * (risk_pct/100)
        sl_dist = abs(entry - sl)
        if sl_dist == 0: return 0.01
        return max(0.01, round(risk_money / (sl_dist * 100), 2))
    except: return 0.01

def is_good_session():
    h = datetime.now(timezone.utc).hour
    return 7 <= h < 20

def session_name():
    h = datetime.now(timezone.utc).hour
    if 7 <= h < 12: return "London"
    if 12 <= h < 20: return "New York"
    return "Off-hours / Asia"

TRADING_WORDS=["gold","xau","dxy","dollar","analyze","analysis","chart","buy","sell","trade","long","short","support","resistance","trend","entry","bias","fib","news","nfp","fomc","cpi","lot","risk","size","trendline","session"]

def is_trading_question(t):
    t=(t or "").lower()
    return any(w in t for w in TRADING_WORDS)

def get_news():
    if time.time()-cache["news_time"]<NEWS_CACHE_SECONDS and cache["news"]:
        return cache["news"]
    try:
        r=requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json",timeout=15).json()
        today=datetime.now(timezone.utc).date().isoformat()
        high=[]
        for e in r:
            if e.get("country")=="USD" and e.get("impact")=="High" and e.get("date","")[:10]==today:
                high.append(f"{e.get('date')[11:16]} UTC - {e.get('title')}")
        txt="\nNEWS: No high-impact USD today. Safe.\n" if not high else "\nNEWS USD TODAY:\n"+"\n".join("- "+h for h in high)+"\nAvoid 30min before/after.\n"
        cache["news"]=txt; cache["news_time"]=time.time()
        return txt
    except Exception as e: return f"\nNEWS err {e}\n"

def get_candles_raw(s,i,outputsize=50):
    try:
        r=requests.get("https://api.twelvedata.com/time_series",params={"symbol":s,"interval":i,"outputsize":outputsize,"apikey":TWELVEDATA_KEY},timeout=15).json()
        return r.get("values",[])
    except: return []

def calc_fib(h,l):
    d=h-l
    return {"0%":h,"23.6%":h-d*0.236,"38.2%":h-d*0.382,"50%":h-d*0.5,"61.8%":h-d*0.618,"78.6%":h-d*0.786,"100%":l}

def get_fib_levels():
    try:
        vals=get_candles_raw("XAU/USD","4h",20)[:20]
        if not vals: return "\nFIB: no data\n"
        sh=max(float(v["high"]) for v in vals); sl=min(float(v["low"]) for v in vals)
        fibs=calc_fib(sh,sl)
        out=f"\nFIB (4H 20-candle {sl:.2f}-{sh:.2f}):\n"
        for k,v in fibs.items():
            out+=f"{k}: {v:.2f}{' <-- GOLDEN' if k in ['61.8%','50%'] else ''}\n"
        out+=f"Current: {float(vals[0]['close']):.2f}\n"
        return out
    except Exception as e: return f"\nFIB err {e}\n"

def find_swings(vals):
    highs = [float(v["high"]) for v in vals[::-1]]
    lows = [float(v["low"]) for v in vals[::-1]]
    s_highs, s_lows = [], []
    for i in range(2, len(highs)-2):
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            s_highs.append((i, highs[i]))
        if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
            s_lows.append((i, lows[i]))
    return s_highs[-3:], s_lows[-3:], highs[-1]

def get_trendlines():
    try:
        vals = get_candles_raw("XAU/USD", "4h", 50)
        if len(vals) < 20: return "\nTRENDLINES: no data\n"
        sh, sl, curr = find_swings(vals)
        out = "\nTRENDLINES (4H):\n"
        if len(sh) >= 2:
            (i1,p1),(i2,p2) = sh[-2], sh[-1]
            slope = (p2-p1)/(i2-i1) if i2!=i1 else 0
            proj = p2 + slope*2
            trend = "falling resistance" if slope < -0.5 else "rising resistance" if slope > 0.5 else "flat resistance"
            out += f"Resistance: {trend} through {p1:.2f} -> {p2:.2f}, proj ~{proj:.2f}\n"
        else: out += "Resistance: not enough swings\n"
        if len(sl) >= 2:
            (i1,p1),(i2,p2) = sl[-2], sl[-1]
            slope = (p2-p1)/(i2-i1) if i2!=i1 else 0
            proj = p2 + slope*2
            trend = "rising support" if slope > 0.5 else "falling support" if slope < -0.5 else "flat support"
            out += f"Support: {trend} through {p1:.2f} -> {p2:.2f}, proj ~{proj:.2f}\n"
        else: out += "Support: not enough swings\n"
        out += f"Current: {curr:.2f}\n"
        return out
    except Exception as e:
        return f"\nTRENDLINES err {e}\n"

def get_candles(s,i):
    try:
        r=requests.get("https://api.twelvedata.com/time_series",params={"symbol":s,"interval":i,"outputsize":20,"apikey":TWELVEDATA_KEY},timeout=15).json()
        if "values" not in r: return f"\n{s} {i}: {r.get('message','err')}\n"
        out=f"\n{s} {i}:\n"
        for v in r["values"][:10]:
            out+=f"{v.get('datetime')} O:{v.get('open')} H:{v.get('high')} L:{v.get('low')} C:{v.get('close')}\n"
        return out
    except Exception as e: return f"\n{s} {i} err {e}\n"

def get_market_data(force=False):
    if not force and time.time()-cache["time"]<CACHE_SECONDS: return cache["data"]
    data="LIVE MARKET DATA:\n"+get_news()
    data+=f"\nSESSION: {session_name()} ({'TRADEABLE' if is_good_session() else 'AVOID - low volume'})\n"
    time.sleep(1); data+=get_candles("XAU/USD","4h")
    time.sleep(1); data+=get_fib_levels()
    time.sleep(1); data+=get_trendlines()
    time.sleep(1); data+=get_candles("XAU/USD","1h")
    time.sleep(1); data+=get_candles("XAU/USD","30min")
    time.sleep(1); data+=get_candles("XAU/USD","5min")
    time.sleep(1); data+=get_candles("DXY","1h")
    cache["time"]=time.time(); cache["data"]=data
    return data

def extract_entry_sl(text):
    try:
        entry=re.search(r'Entry[:\s]*([0-9]+\.[0-9]+)',text,re.I)
        sl=re.search(r'SL[:\s]*([0-9]+\.[0-9]+)',text,re.I)
        if entry and sl: return float(entry.group(1)), float(sl.group(1))
    except: pass
    return None, None

def check_for_signal():
    if not is_good_session():
        return "NO SIGNAL"
    market=get_market_data(force=True)
    if "FIB: no data" in market or "exceeded" in market.lower() or "error" in market.lower():
        return "NO SIGNAL"
    bal, risk = ACCOUNT_BALANCE, RISK_PERCENT
    if BOSS_ID and BOSS_ID in user_settings:
        bal, risk = get_user_risk(BOSS_ID)
    prompt=(f"You are Rosita signal engine.\nAccount: ${bal} Risk: {risk}%\n"
             "GRADES:\n"
             "A = 4H trend + trendline touch + fib golden/psych + DXY agree + 5m confirm + no news (5/5)\n"
             "B = any 3 of those 5\n"
             "Accept A AND B. Skip C (<3) or high news within 30min.\n\n"
             +market+"\n\nIf A or B, reply: SIGNAL [GRADE A/B]: LONG/SHORT Entry: XXXX.XX SL: XXXX.XX TP1: XXXX.XX TP2: XXXX.XX + 2 line reason. Else: NO SIGNAL")
    try:
        res=get_groq().chat.completions.create(model="openai/gpt-oss-20b",messages=[{"role":"user","content":prompt}],temperature=0.3,max_tokens=300)
        txt=res.choices[0].message.content.strip()
        if txt.startswith("SIGNAL"):
            e, s = extract_entry_sl(txt)
            if e and s:
                lots=calc_lot(bal,risk,e,s)
                is_b = "GRADE B" in txt.upper()
                if is_b:
                    lots = max(0.01, round(lots * 0.5, 2))
                    risk_note = f"Risk ${bal*risk/100*0.5:.2f} (B-grade half size)"
                else:
                    risk_note = f"Risk ${bal*risk/100:.2f}"
                txt+=f"\nLot: {lots} ({risk_note})"
        return txt
    except: return "NO SIGNAL"

async def signal_watcher():
    await asyncio.sleep(30)
    while True:
        try:
            if BOSS_ID and tg_app_global:
                result=await asyncio.to_thread(check_for_signal)
                if result.startswith("SIGNAL"):
                    await tg_app_global.bot.send_message(chat_id=BOSS_ID,text=f"Boss! I found one 😍\n\n{result}\n\nYou taking it?")
            await asyncio.sleep(900)
        except Exception as e:
            print(e); await asyncio.sleep(900)

def reply(chat_id, user_text):
    trading=is_trading_question(user_text)
    market=get_market_data() if trading else "Casual chat."
    bal, risk = get_user_risk(chat_id)
    hist=memory.get(chat_id,[])
    system=(f"You are Rosita, Boss's sexy trading girlfriend. Flirty, call him Boss.\nAccount: ${bal} Risk: {risk}% Lot = Risk$ / (|Entry-SL|*100). B-grade = half size.\n\n"+market+
            "\n\nPLAYBOOK: Accept A and B grades. A=5/5 confluence, B=3/5 confluence. Always state GRADE A/B. 1.4H Trend + trendlines 2.Fib golden + psych + S/R + trendline touch 3.DXY 4.5m confirm 5.News filter 6.Session 07-20 UTC\n"
            "Always include Lot. Output: 4H, Trendlines, Session, News, Fib, Levels, DXY, Bias, GRADE, Entry/SL/TP1/TP2/Lot\nRULES: 2-4 emojis, short.")
    msgs=[{"role":"system","content":system}]; msgs.extend(hist[-10:]); msgs.append({"role":"user","content":user_text})
    try:
        br=get_groq().chat.completions.create(model="openai/gpt-oss-20b",messages=msgs,temperature=0.9,max_tokens=650).choices[0].message.content.strip()
        e,s=extract_entry_sl(br)
        if e and s and "lot" not in br.lower():
            lots = calc_lot(bal,risk,e,s)
            if "GRADE B" in br.upper():
                lots = max(0.01, round(lots * 0.5, 2))
                br+=f"\nLot: {lots} (B-grade half size) 💰"
            else:
                br+=f"\nLot: {lots} 💰"
        hist.extend([{"role":"user","content":user_text},{"role":"assistant","content":br}])
        memory[chat_id]=hist[-20:]
        return br
    except: return "Ugh brain glitch Boss, say again?"

async def setrisk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bal=float(context.args[0]); risk=float(context.args[1])
        user_settings[update.effective_chat.id]={"balance":bal,"risk":risk}
        await update.message.reply_text(f"Got it Boss 😘 Balance ${bal}, Risk {risk}% saved.")
    except:
        await update.message.reply_text("Use: /setrisk 2000 1 (balance risk%)")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(reply(update.effective_chat.id, update.message.text or ""))

async def post_init(app: ApplicationBuilder): asyncio.create_task(signal_watcher())

def run_telegram():
    global tg_app_global
    try: asyncio.get_event_loop()
    except RuntimeError: asyncio.set_event_loop(asyncio.new_event_loop())
    tg_app=ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    tg_app_global=tg_app
    tg_app.add_handler(CommandHandler("setrisk", setrisk))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Rosita v5.1 polling..."); tg_app.run_polling()

def run_flask(): app.run(host="0.0.0.0",port=int(os.environ.get("PORT",10000)))
if __name__=="__main__":
    threading.Thread(target=run_flask,daemon=True).start(); run_telegram()
