import os, asyncio, logging, requests, threading, json, re
from datetime import datetime, timezone
from collections import defaultdict, deque
from flask import Flask, request, jsonify, render_template_string
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from groq import Groq

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Swarm18.2")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
TWELVEDATA_KEY = os.getenv("TWELVEDATA_KEY", "")
BOSS_CHAT_ID = os.getenv("BOSS_CHAT_ID", "")
PORT = int(os.getenv("PORT", "10000") or 10000)
MEM_FILE = "rosita_memory.json"

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
CACHE = {}
NEWS_CACHE = {"t": 0, "d": []}
HISTORY = defaultdict(lambda: deque(maxlen=12))

try:
    with open(MEM_FILE, "r") as f: LONG_MEM = json.load(f)
except: LONG_MEM={}
def save_mem():
    try:
        with open(MEM_FILE, "w") as ff: json.dump(LONG_MEM, ff)
    except: pass

web = Flask(__name__)

SYM_MAP = {
 "gold":"XAU/USD","xau":"XAU/USD",
 "silver":"XAG/USD","xag":"XAG/USD",
 "us oil":"WTI/USD","wti":"WTI/USD","oil":"WTI/USD",
 "brent":"BRENT/USD",
 "euru":"EUR/USD","eurusd":"EUR/USD","eur":"EUR/USD",
 "ether":"ETH/USD","eth":"ETH/USD",
 "nas100":"NDX/USD","nas":"NDX/USD","ndx":"NDX/USD",
 "us30":"DJI/USD","dow":"DJI/USD","dji":"DJI/USD","us30cash":"DJI/USD",
 "spx500":"SPX/USD","spx":"SPX/USD",
 "dxy":"DXY/USD","dollar":"DXY/USD"
}
SYM_MAP_DESK = {"GOLD":"XAU/USD","SILVER":"XAG/USD","US OIL":"WTI/USD","BRENT":"BRENT/USD","EURU":"EUR/USD","ETHER":"ETH/USD","NAS100":"NDX/USD","US30":"DJI/USD","SPX500":"SPX/USD","DXY":"DXY/USD"}

def get_td_price(sym):
    try:
        r=requests.get("https://api.twelvedata.com/price",params={"symbol":sym,"apikey":TWELVEDATA_KEY},timeout=10).json()
        return float(r["price"])
    except: return None

def is_weekend_closed():
    now=datetime.now(timezone.utc); wd=now.weekday(); hr=now.hour
    if wd==4 and hr>=22: return True
    if wd==5: return True
    if wd==6 and hr<22: return True
    return False

def get_candles(symbol="XAU/USD", interval="4h", n=200):
    key=f"{symbol}_{interval}"; now_ts=datetime.now().timestamp()
    if key in CACHE and now_ts-CACHE[key]["t"]<300: return CACHE[key]["d"]
    try:
        r=requests.get("https://api.twelvedata.com/time_series",params={"symbol":symbol,"interval":interval,"outputsize":n,"apikey":TWELVEDATA_KEY},timeout=20).json()
        vals=r.get("values",[])
        if not vals: return None
        candles=[]
        for v in reversed(vals): candles.append({"t":v["datetime"],"o":float(v["open"]),"h":float(v["high"]),"l":float(v["low"]),"c":float(v["close"])})
        CACHE[key]={"t":now_ts,"d":candles}; return candles
    except: return None

def get_live_price(sym="XAU/USD"):
    c=get_candles(sym,"5min",5)
    if c: return c[-1]["c"]
    return get_td_price(sym)

def ema(values, period):
    k=2.0/(period+1); e=values[0]; out=[]
    for v in values: e=v*k+e*(1-k); out.append(e)
    return out
def tf_bias(c):
    if not c or len(c)<22: return "unknown"
    closes=[x["c"] for x in c]; e9=ema(closes,9); e21=ema(closes,21)
    return "bullish" if e9[-1]>e21[-1] else "bearish"
def fib_levels(candles, lookback=50):
    if not candles or len(candles)<lookback: return None
    w=candles[-lookback:]; sh=max(x["h"] for x in w); sl=min(x["l"] for x in w); d=sh-sl
    if d<=0: return None
    return {"high":sh,"low":sl,"0.618":sh-d*0.618,"0.65":sh-d*0.65,"0.705":sh-d*0.705,"0.79":sh-d*0.79}
def get_news_warning():
    now_ts=datetime.now(timezone.utc).timestamp()
    if now_ts-NEWS_CACHE["t"]<1800: events=NEWS_CACHE["d"]
    else:
        try: r=requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json",timeout=15).json(); events=r; NEWS_CACHE["t"]=now_ts; NEWS_CACHE["d"]=events
        except: return ""
    warns=[]; now=datetime.now(timezone.utc)
    for ev in events:
        try:
            if ev.get("country")!="USD": continue
            if ev.get("impact")!="High": continue
            dt=datetime.fromisoformat(ev["date"].replace("Z","+00:00")); diff=(dt-now).total_seconds()/60
            if -30<=diff<=60: warns.append(f"{ev['title']} ({int(diff)}m)")
        except: continue
    if warns: return "HIGH IMPACT USD: "+",".join(warns[:3])+" - Harleen says sit out"
    return ""

SYSTEM="""You are SWARM v18.2 - Rosita + Harleen Quinzel + Magna. ALWAYS include emojis.
Rosita Boss top-down 4h->1h->15m->5m.
Harleen Veto news/session/weekend.
Magna Sniper sweep/FVG/OTE 61.8-79%.
You can analyze GOLD SILVER US OIL BRENT EURU ETHER NAS100 US30 SPX500 DXY - use given symbol price.
If valid:
Bias 4h/1h: [Rosita]
Harleen Verdict: [PASS/VETO]
Magna Snipe: [OTE/sweep/FVG]
Direction: Long/Short
Entry: x.xx
SL: x.xx
TP1-TP10 Ladder: [10 TPs compact]
Reason: Setup A/B/C
Confluences: bullets
If no valid: No A/B/C setup - Harleen vetoed / no confluence
Manual only, educational. Call user Shay.
"""

async def ask_groq(text, chat_id):
    cid=str(chat_id); HISTORY[cid].append({"role":"user","content":text}); mem=LONG_MEM.get(cid,"")
    if not client: return "No brain yet Shay add GROQ_API_KEY"
    msgs=[{"role":"system","content":SYSTEM+f"\n[Memory] {mem}"}]
    for m in list(HISTORY[cid])[-10:]: msgs.append(m)
    try:
        r=client.chat.completions.create(model="openai/gpt-oss-20b",messages=msgs,temperature=0.6,max_tokens=900)
        txt=r.choices[0].message.content.strip(); HISTORY[cid].append({"role":"assistant","content":txt}); return txt
    except Exception as e: logger.error(e); return "Brain fog Shay try again"

HTML_DESK="""
<!DOCTYPE html><head><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{background:#070709;color:#e8e8e8;font-family:monospace;margin:0;padding:10px}
.title{font-size:24px;font-weight:900}.tabs{display:flex;gap:6px;overflow-x:auto;padding:8px 0}
.tab{background:#1b1b1f;border-radius:20px;padding:6px 14px;font-size:11px;white-space:nowrap;border:1px solid #2a2a2e;cursor:pointer}
.tab.active{background:#fff;color:#000}.price{font-size:30px;font-weight:800}
.btn{border-radius:14px;padding:14px;margin:6px 0;font-weight:800;font-size:13px;width:100%;text-align:left;border:none;cursor:pointer}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.green{background:#14d47a;color:#000}.red{background:#ff5a5a;color:#000}.yellow{background:#ffcb3f;color:#000}.blue{background:#6dc8ff;color:#000}.white{background:#eee;color:#000}
.card{background:#141418;border-radius:14px;padding:10px;margin:8px 0;border:1px solid #222}.small{font-size:9px;letter-spacing:2px;color:#8a8a90}.yn{font-size:20px;font-weight:900}
</style></head><body>
<div class="small">ACW · CORE V18.2 · OLD SWARM · ALL ASSETS + US30</div>
<div class="title">OBSIDIAN DESK</div>
<div class="tabs" id="tabs"></div>
<div class="small" id="sym">GOLD</div><div class="price" id="price">---</div><div class="small" id="chg">loading</div>
<div class="grid2">
<div class="btn green" onclick="ask('CAN I BUY NOW')">CAN I BUY NOW</div>
<div class="btn red" onclick="ask('CAN I SELL NOW')">CAN I SELL NOW</div>
</div>
<div class="btn yellow" onclick="ask('CAN I ENTER')">CAN I ENTER</div>
<div class="grid2"><div class="btn blue" onclick="ask('WHERE IS SL')">WHERE'S SL</div><div class="btn white" onclick="ask('WHERE IS TP')">WHERE'S TP</div></div>
<div class="card" id="out" style="display:none">
<div class="yn" id="yn">---</div><div style="font-size:11px;color:#aaa" id="desc"></div>
<div class="grid2">
<div class="card"><div class="small">ENTRY</div><div id="ez"></div></div>
<div class="card"><div class="small">EXIT</div><div id="xz"></div></div>
<div class="card"><div class="small">SL</div><div id="sl"></div></div>
<div class="card"><div class="small">TP</div><div id="tp"></div></div>
</div>
<div class="card"><div class="small">ROSITA <span style="float:right" id="r_tag"></span></div><div style="font-size:11px" id="r_txt"></div></div>
<div class="card"><div class="small">MAGNA <span style="float:right" id="m_tag"></span></div><div style="font-size:11px" id="m_txt"></div></div>
<div class="card"><div class="small">HARLEEN <span style="float:right" id="h_tag"></span></div><div style="font-size:11px" id="h_txt"></div></div>
<div class="small" id="det"></div>
</div>
<script>
const assets=["GOLD","SILVER","US OIL","BRENT","EURU","ETHER","NAS100","US30","SPX500","DXY"]; let cur="GOLD";
function renderTabs(){let h=""; assets.forEach(a=>{h+=`<div class='tab ${a==cur?'active':''}' onclick="pick('${a}')">${a}</div>`}); document.getElementById('tabs').innerHTML=h;}
async function pick(a){cur=a; renderTabs(); document.getElementById('sym').innerText=a; document.getElementById('price').innerText='loading...'; let r=await fetch('/api/price?asset='+a); let j=await r.json(); document.getElementById('price').innerText=j.price; document.getElementById('chg').innerText=j.bias+' | '+j.raw;}
async function ask(q){
 document.getElementById('out').style.display='block'; document.getElementById('yn').innerText='SCANNING '+cur+'...';
 let r=await fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({asset:cur,question:q})}); let j=await r.json();
 document.getElementById('yn').innerText=j.yn; document.getElementById('yn').style.color=j.yn.includes('BUY')?'#14d47a':j.yn.includes('SELL')?'#ff5a5a':'#ffcb3f';
 document.getElementById('desc').innerText=j.desc; document.getElementById('ez').innerText=j.entry; document.getElementById('xz').innerText=j.exit; document.getElementById('sl').innerText=j.sl; document.getElementById('tp').innerText=j.tp;
 document.getElementById('r_tag').innerText=j.rosita_tag; document.getElementById('r_txt').innerText=j.rosita;
 document.getElementById('m_tag').innerText=j.magna_tag; document.getElementById('m_txt').innerText=j.magna;
 document.getElementById('h_tag').innerText=j.harleen_tag; document.getElementById('h_txt').innerText=j.harleen;
 document.getElementById('det').innerText=j.details; document.getElementById('price').innerText=j.price;
}
renderTabs(); pick('GOLD');
</script></body></html>
"""

@web.route("/")
def h(): return "Swarm v18.2 - Old Swarm + All Assets + US30 | /desk",200
@web.route("/desk")
def desk(): return render_template_string(HTML_DESK)

@web.route("/api/price")
def api_price():
    a=request.args.get("asset","GOLD"); sym=SYM_MAP_DESK.get(a,"XAU/USD"); p=get_td_price(sym)
    c=get_candles(sym,"15min",50); b=tf_bias(c) if c else "neutral"
    if p is None and c: p=c[-1]["c"]
    if p is None: p=0
    return jsonify({"price":f"{p:,.2f}","bias":b.upper(),"raw":f"{sym} live"})

@web.route("/api/ask", methods=["POST"])
def api_ask():
    d=request.get_json() or {}; asset=d.get("asset","GOLD"); q=d.get("question","CAN I BUY NOW")
    sym=SYM_MAP_DESK.get(asset,"XAU/USD"); c4h=get_candles(sym,"4h",40); c1h=get_candles(sym,"1h",40); c15=get_candles(sym,"15min",50)
    price=get_td_price(sym) or (c15[-1]["c"] if c15 else 0)
    b4h=tf_bias(c4h); b1h=tf_bias(c1h); b15=tf_bias(c15)
    sh=max([x["h"] for x in c15[-20:]]) if c15 else price*1.01; sl0=min([x["l"] for x in c15[-20:]]) if c15 else price*0.99; eq=(sh+sl0)/2
    prompt=f"Asset {asset} {sym} price {price:.2f} 4h {b4h} 1h {b1h} 15m {b15} SH {sh:.2f} SL {sl0:.2f} EQ {eq:.2f} Question {q}. Return JSON only: {{yn:'YES - BUY or YES - SELL or NO - WAIT', desc:'short', entry:'zone', exit:'zone', sl:'price', tp:'price', rosita_tag:'BULL/BEAR', rosita:'top-down', magna_tag:'WAIT/TRIGGER', magna:'OTE sweep', harleen_tag:'0.5R', harleen:'invalidation', details:'HTF stack'}}. Do NOT always YES."
    try:
        r=client.chat.completions.create(model="openai/gpt-oss-20b",messages=[{"role":"system","content":"You are OBSIDIAN old swarm ROSITA HARLEEN MAGNA. Output JSON only."},{"role":"user","content":prompt}],temperature=0.2,max_tokens=600)
        txt=r.choices[0].message.content; m=re.search(r'\{.*\}',txt,re.S); j=json.loads(m.group(0)) if m else json.loads(txt)
    except:
        if "BUY" in q and b4h=="bullish" and b1h=="bullish": yn="YES - BUY"
        elif "SELL" in q and b4h=="bearish" and b1h=="bearish": yn="YES - SELL"
        else: yn="NO - WAIT"
        j={"yn":yn,"desc":f"4h {b4h} 1h {b1h} 15m {b15} near {'discount' if price<eq else 'premium'}","entry":f"{sl0*1.001:.2f} - {sl0*1.004:.2f}","exit":f"{sh*0.996:.2f}","sl":f"{sl0*0.998:.2f}","tp":f"{eq:.2f} / {sh:.2f}","rosita_tag":b4h.upper(),"rosita":f"HTF {b4h} stack.","magna_tag":"WAIT" if yn.startswith("NO") else "TRIGGER","magna":f"OTE 61.8-79% 15m {b15}.","harleen_tag":"0.5R","harleen":f"Invalidation beyond structure. 0.5R only.","details":f"HTF {b4h.upper()} | {b15}"}
    j["price"]=f"{price:,.2f}"; return jsonify(j)

async def handle_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    low=update.message.text.lower().strip()
    if low in ["hi","hello","hey","yo","gm"]:
        await update.message.reply_text("Hey Shay Swarm v18.2 online - old swarm + US30 👀 desk at /desk"); return
    if low.startswith("remember "):
        LONG_MEM[str(update.effective_chat.id)]=(LONG_MEM.get(str(update.effective_chat.id),"")+" "+update.message.text[9:]).strip()[-1000:]; save_mem()
        await update.message.reply_text("Got it Shay I'll remember"); return
    if "news" in low:
        if is_weekend_closed():
            await update.message.reply_text("Weekend Shay Markets closed, Harleen sleeping"); return
        w=get_news_warning()
        await update.message.reply_text(w if w else "No high-impact USD - Harleen clear"); return

    # MULTI-ASSET PARSER - GOLD SILVER US30 ETC
    found_sym=None; found_name="GOLD"
    for k,v in SYM_MAP.items():
        if k in low:
            found_sym=v; found_name=k.upper(); break
    if "analyze" in low or low in ["signal","scalp","analyze"] or found_sym:
        sym=found_sym if found_sym else "XAU/USD"
        name=found_name if found_sym else "GOLD"
        # weekend only blocks XAU
        if is_weekend_closed() and sym=="XAU/USD":
            await update.message.reply_text("Weekend Shay Gold closed - sleeping till Sunday 22:00 UTC - US30/NAS still open though")
            # continue anyway for indices
        await update.message.reply_text(f"Swarm scanning Shay {name} {sym} - Rosita + Harleen + Magna debating...")
        c4h=get_candles(sym,"4h",50); c1h=get_candles(sym,"1h",50); c15=get_candles(sym,"15min",60); c5=get_candles(sym,"5min",20)
        if c4h and c1h and c15 and c5: ctx_top=f"{name} {sym} 4h {tf_bias(c4h)} @ {c4h[-1]['c']:.2f} | 1h {tf_bias(c1h)} @ {c1h[-1]['c']:.2f} | 15m {tf_bias(c15)} @ {c15[-1]['c']:.2f} | 5m {c5[-1]['c']:.2f}"
        else: ctx_top=f"{name} {sym} partial data"
        fib=fib_levels(c15,50)
        if fib: ctx_top+=f" | Fib H {fib['high']:.2f} L {fib['low']:.2f} OTE 61.8 {fib['0.618']:.2f} 70.5 {fib['0.705']:.2f} 79 {fib['0.79']:.2f}"
        price=get_td_price(sym) or (c15[-1]["c"] if c15 else 0)
        sig=await ask_groq(f"{name} scalp {sym} {ctx_top} News:{get_news_warning()} Live {price} Debate then final manual.",update.effective_chat.id)
        await update.message.reply_text(sig); return

    price=get_live_price(); pc=f"\n[Live {price:.2f}]" if price else ""
    reply=await ask_groq(update.message.text+pc,update.effective_chat.id)
    await update.message.reply_text(reply)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Rosita + Harleen + Magna v18.2 online - All assets + US30 👀\nDesk: /desk\nTry: analyze us30 / analyze gold / analyze nas100")

async def auto_signal_loop(app):
    was_closed=is_weekend_closed(); await asyncio.sleep(10)
    while True:
        try:
            if is_weekend_closed(): was_closed=True; await asyncio.sleep(3600); continue
            if was_closed:
                if not is_weekend_closed():
                    if BOSS_CHAT_ID.strip():
                        try: await app.bot.send_message(chat_id=int(BOSS_CHAT_ID),text="GM Shay Markets open - Rosita + Harleen + Magna awake, scanning Gold now Type analyze gold for first signal")
                        except: pass
                    was_closed=False
            if BOSS_CHAT_ID.strip():
                hr=datetime.now(timezone.utc).hour
                if hr>=21 or hr<5: await asyncio.sleep(300); continue
                if get_news_warning(): await asyncio.sleep(1800); continue
                c15=get_candles("XAU/USD","15min",60)
                if c15:
                    last=c15[-1]["c"]; sig=await ask_groq(f"Auto-scan XAU/USD at {last}. Manual only. If no setup reply exactly No A/B/C setup",BOSS_CHAT_ID)
                    if "Entry:" in sig and "SL:" in sig:
                        if "No A/B/C" not in sig: await app.bot.send_message(chat_id=int(BOSS_CHAT_ID),text=f"{sig}\n\nManual only")
        except Exception as e: logger.error(e)
        await asyncio.sleep(300)

async def post_init(app): asyncio.create_task(auto_signal_loop(app))

def run_web():
    web.run(host="0.0.0.0", port=PORT, use_reloader=False)
threading.Thread(target=run_web, daemon=True).start()

def main():
    app=ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    app.run_polling()
if __name__=="__main__": main()
