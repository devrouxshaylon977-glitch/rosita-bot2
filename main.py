
def v22_score_bonus(direction, market):
    """Additional conservative confluence points, capped at 12."""
    bonus = 0
    direction = direction.upper()
    div = market.get("divergence", {}) or {}
    if direction == "LONG" and div.get("bullish"):
        bonus += 2
    if direction == "SHORT" and div.get("bearish"):
        bonus += 2

    br = market.get("break_retest", {}) or {}
    br_side = br.get("resistance" if direction == "LONG" else "support", {}) or {}
    if br_side.get("confirmed"):
        bonus += 3

    pp = market.get("v22_levels", {}).get("previous_periods", {}) or {}
    if pp:
        bonus += 1

    sessions = market.get("v22_levels", {}).get("sessions", {}) or {}
    if sessions:
        bonus += 1

    fibext = (market.get("fib_extensions", {}) or {}).get(direction, {})
    if fibext:
        bonus += 1

    # Reward objective 5M S/R presence without assuming direction.
    if market.get("support_resistance", {}).get("5m"):
        bonus += 1

    return min(bonus, 12)



# =========================
# v22: ADVANCED LEVELS / CONFIRMATIONS
# =========================

SESSION_WINDOWS_UTC = {
    "ASIAN": (0, 8),
    "LONDON": (7, 16),
    "NEW_YORK": (13, 21),
}

def _candle_ts(c):
    return c.get("t") or c.get("datetime") or c.get("time") or c.get("timestamp")

def _hour_utc(c):
    try:
        ts = str(_candle_ts(c))
        # ISO timestamps: YYYY-MM-DDTHH:MM:SS...
        m = re.search(r"T(\d{2}):", ts)
        return int(m.group(1)) if m else None
    except Exception:
        return None

def previous_period_levels(candles):
    """Objective previous-day and previous-week OHLC levels from candle timestamps."""
    if not candles:
        return {}
    rows = []
    for c in candles:
        try:
            ts = str(_candle_ts(c)).replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts)
            rows.append((dt, float(c["h"]), float(c["l"]), float(c["c"])))
        except Exception:
            continue
    if not rows:
        return {}

    latest_date = rows[-1][0].date()
    prev_day = [x for x in rows if x[0].date() < latest_date and x[0].date() == max(
        y[0].date() for y in rows if y[0].date() < latest_date
    )] if any(x[0].date() < latest_date for x in rows) else []

    latest_week = rows[-1][0].isocalendar()[:2]
    older_weeks = [x[0].isocalendar()[:2] for x in rows if x[0].isocalendar()[:2] < latest_week]
    prev_week_key = max(older_weeks) if older_weeks else None
    prev_week = [x for x in rows if prev_week_key and x[0].isocalendar()[:2] == prev_week_key]

    def pack(items):
        if not items:
            return {}
        return {
            "high": max(x[1] for x in items),
            "low": min(x[2] for x in items),
            "open": items[0][3],
            "close": items[-1][3],
        }

    return {"previous_day": pack(prev_day), "previous_week": pack(prev_week)}

def session_levels(candles):
    """Approximate UTC session high/low levels using candle timestamps."""
    out = {}
    for name, (start_h, end_h) in SESSION_WINDOWS_UTC.items():
        subset = []
        for c in candles or []:
            h = _hour_utc(c)
            if h is None:
                continue
            # Handles windows that cross midnight.
            inside = start_h <= h < end_h if start_h < end_h else (h >= start_h or h < end_h)
            if inside:
                try:
                    subset.append((float(c["h"]), float(c["l"])))
                except Exception:
                    pass
        if subset:
            out[name] = {
                "high": max(x[0] for x in subset),
                "low": min(x[1] for x in subset),
                "range": max(x[0] for x in subset) - min(x[1] for x in subset),
            }
    return out

def fibonacci_extensions(swing_high, swing_low, direction="LONG"):
    """Objective 1.272/1.618/2.0 extension references."""
    try:
        hi, lo = float(swing_high), float(swing_low)
        rng = abs(hi - lo)
        if rng <= 0:
            return {}
        if direction.upper() == "LONG":
            base = hi
            return {
                "1.272": base + rng * 0.272,
                "1.618": base + rng * 0.618,
                "2.000": base + rng * 1.000,
            }
        base = lo
        return {
            "1.272": base - rng * 0.272,
            "1.618": base - rng * 0.618,
            "2.000": base - rng * 1.000,
        }
    except Exception:
        return {}

def _pivot_series(candles, field="close", lookback=120):
    vals = []
    for c in (candles or [])[-lookback:]:
        try:
            vals.append(float(c[field]))
        except Exception:
            vals.append(None)
    return vals

def _local_pivots(values, left=2, right=2):
    highs, lows = [], []
    for i in range(left, len(values) - right):
        if values[i] is None:
            continue
        window = [v for v in values[i-left:i+right+1] if v is not None]
        if not window:
            continue
        if values[i] == max(window):
            highs.append((i, values[i]))
        if values[i] == min(window):
            lows.append((i, values[i]))
    return highs, lows

def divergence_detection(candles, indicator_values, lookback=100):
    """Classic-price vs momentum divergence proxy. Returns confirmed pivot-pair signals."""
    if not candles or not indicator_values:
        return {"bullish": False, "bearish": False, "details": "unknown"}

    n = min(len(candles), len(indicator_values), lookback)
    prices = []
    inds = []
    for c, ind in zip(candles[-n:], indicator_values[-n:]):
        try:
            prices.append(float(c["c"]))
            inds.append(float(ind))
        except Exception:
            prices.append(None)
            inds.append(None)

    ph, pl = _local_pivots(prices)
    ih, il = _local_pivots(inds)

    bullish = bearish = False
    details = []
    if len(pl) >= 2 and len(il) >= 2:
        p1, p2 = pl[-2][1], pl[-1][1]
        i1, i2 = il[-2][1], il[-1][1]
        if p2 < p1 and i2 > i1:
            bullish = True
            details.append("bullish divergence")
    if len(ph) >= 2 and len(ih) >= 2:
        p1, p2 = ph[-2][1], ph[-1][1]
        i1, i2 = ih[-2][1], ih[-1][1]
        if p2 > p1 and i2 < i1:
            bearish = True
            details.append("bearish divergence")

    return {"bullish": bullish, "bearish": bearish, "details": ", ".join(details) or "none"}

def sr_state(price, zone, tolerance=0.0015):
    """Classifies a zone as fresh/active/tested/broken using current price."""
    try:
        p = float(price)
        lo = float(zone["low"])
        hi = float(zone["high"])
        mid = (lo + hi) / 2
        width = max(hi - lo, abs(mid) * tolerance)
        if lo <= p <= hi:
            return "ACTIVE"
        if p > hi + width:
            return "BROKEN_ABOVE"
        if p < lo - width:
            return "BROKEN_BELOW"
        return "TESTING"
    except Exception:
        return "UNKNOWN"

def break_retest_confirmation(candles, level, direction, atr_value=None):
    """Detects a simple objective break + retest sequence."""
    if not candles or level is None:
        return {"confirmed": False, "reason": "missing data"}
    try:
        lev = float(level)
        tol = float(atr_value) * 0.20 if atr_value else max(lev * 0.0005, 0.25)
        recent = candles[-12:]
        closes = [float(c["c"]) for c in recent]
        highs = [float(c["h"]) for c in recent]
        lows = [float(c["l"]) for c in recent]
        if direction.upper() == "LONG":
            broke = any(x > lev + tol for x in closes[:-2])
            retest = any(abs(x - lev) <= tol or lo <= lev + tol for x, lo in zip(closes[-3:], lows[-3:]))
            held = closes[-1] > lev
        else:
            broke = any(x < lev - tol for x in closes[:-2])
            retest = any(abs(x - lev) <= tol or hi >= lev - tol for x, hi in zip(closes[-3:], highs[-3:]))
            held = closes[-1] < lev
        return {"confirmed": bool(broke and retest and held), "broke": broke, "retest": retest, "held": held}
    except Exception as e:
        return {"confirmed": False, "reason": str(e)}

def fib_extension_targets(entry, swing_high, swing_low, direction):
    """Extension targets measured from the most recent swing range."""
    ext = fibonacci_extensions(swing_high, swing_low, direction)
    return {k: round(v, 2) for k, v in ext.items()} if ext else {}


from math import isfinite
import os
import asyncio
import logging
import requests
import threading
import json
import base64
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
import math
import uuid
from datetime import datetime, timezone
from collections import defaultdict, deque

from flask import Flask
from telegram import Update, ReplyKeyboardMarkup, BotCommand
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from groq import Groq

# ============================================================
# SWARM v22.0 — ROSITA + HARLEEN QUINZEL + MAGNA
# Objective Python market engine + Groq explanation layer
#
# IMPORTANT:
# - Manual/educational analysis only.
# - Python calculates technical measurements and trade levels.
# - Groq is NOT allowed to invent Entry/SL/TP.
# - Backtesting is included, but historical performance is not
#   a guarantee of future results.
# ============================================================

try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Swarm22")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
TWELVEDATA_KEY = os.getenv("TWELVEDATA_KEY", "")
BOSS_CHAT_ID = os.getenv("BOSS_CHAT_ID", "")
PORT = int(os.getenv("PORT", "10000") or 10000)

MEM_FILE = "rosita_memory.json"

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.6-27b")

CACHE = {}
NEWS_CACHE = {"t": 0, "d": []}
ANALYSIS_CACHE = {"t": 0, "d": None}
ANALYSIS_CACHE_TTL = 10
HISTORY = defaultdict(lambda: deque(maxlen=12))
LOCK = threading.Lock()

# ============================================================
# V19 RESEARCH JOURNAL / SIGNAL REGISTRY
# ============================================================

JOURNAL_FILE = os.getenv("JOURNAL_FILE", "swarm_signal_journal.jsonl")

def make_signal_id():
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6]

def journal_signal(result, outcome=None, r_result=None, event="SIGNAL"):
    """Append an immutable-ish JSONL research record."""
    try:
        record = {
            "event": event,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "signal_id": result.get("signal_id"),
            "symbol": result.get("symbol"),
            "price": result.get("price"),
            "direction": result.get("magna", {}).get("direction"),
            "valid": result.get("valid"),
            "score": result.get("score"),
            "grade": result.get("grade"),
            "regime": result.get("regime"),
            "rosita": result.get("rosita", {}),
            "harleen": result.get("harleen", {}),
            "magna": result.get("magna", {}),
            "risk": result.get("risk", {}),
            "confluences": result.get("confluences", []),
            "outcome": outcome,
            "r_result": r_result,
        }
        with LOCK:
            with open(JOURNAL_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")
    except Exception as e:
        logger.error("Journal error: %s", e)

def load_journal(limit=5000):
    rows = []
    try:
        with LOCK:
            with open(JOURNAL_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        continue
    except FileNotFoundError:
        return []
    except Exception as e:
        logger.error("Journal read error: %s", e)
        return []
    return rows[-limit:]


# ============================================================
# WEB SERVER
# ============================================================

web = Flask(__name__)

@web.route("/")
def health():
    return "Swarm v22.0 Rosita + Harleen Quinzel + Magna — objective engine alive", 200

def run_flask():
    web.run(host="0.0.0.0", port=PORT, use_reloader=False)

threading.Thread(target=run_flask, daemon=True).start()

# ============================================================
# MEMORY
# ============================================================

try:
    with open(MEM_FILE, "r", encoding="utf-8") as f:
        LONG_MEM = json.load(f)
except Exception:
    LONG_MEM = {}

def save_mem():
    try:
        with open(MEM_FILE, "w", encoding="utf-8") as f:
            json.dump(LONG_MEM, f)
    except Exception:
        pass

# ============================================================
# DATA
# ============================================================

def get_candles(symbol="XAU/USD", interval="4h", n=200):
    key = f"{symbol}_{interval}_{n}"
    now = datetime.now().timestamp()

    if key in CACHE and now - CACHE[key]["t"] < 120:
        return CACHE[key]["d"]

    if not TWELVEDATA_KEY:
        return None

    try:
        r = requests.get(
            "https://api.twelvedata.com/time_series",
            params={
                "symbol": symbol,
                "interval": interval,
                "outputsize": n,
                "apikey": TWELVEDATA_KEY,
            },
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()

        vals = data.get("values", [])
        if not vals:
            logger.warning("Twelve Data returned no values: %s", data)
            return None

        candles = []
        for v in reversed(vals):
            candles.append({
                "t": v["datetime"],
                "o": float(v["open"]),
                "h": float(v["high"]),
                "l": float(v["low"]),
                "c": float(v["close"]),
            })

        CACHE[key] = {"t": now, "d": candles}
        return candles

    except Exception as e:
        logger.error("Candle error %s %s: %s", symbol, interval, e)
        return None

def get_live_price():
    candles = get_candles("XAU/USD", "5min", 5)
    return candles[-1]["c"] if candles else None

# ============================================================
# BASIC INDICATORS
# ============================================================

def ema(values, period):
    if not values:
        return []

    k = 2 / (period + 1)
    e = values[0]
    out = []

    for v in values:
        e = v * k + e * (1 - k)
        out.append(e)

    return out

def rsi_series(values, period=14):
    """Return a Wilder-style RSI series aligned to input values."""
    if not values:
        return []
    vals = [float(v) for v in values]
    if len(vals) <= period:
        return []

    gains = []
    losses = []
    for i in range(1, len(vals)):
        change = vals[i] - vals[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    out = [None] * period

    def calc(g, l):
        if l == 0:
            return 100.0 if g > 0 else 50.0
        rs = g / l
        return 100.0 - (100.0 / (1.0 + rs))

    out.append(calc(avg_gain, avg_loss))
    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period
        out.append(calc(avg_gain, avg_loss))
    return out

def rsi(values, period=14):
    """Return the latest RSI value."""
    series = rsi_series(values, period)
    valid = [x for x in series if x is not None]
    return valid[-1] if valid else None

def true_ranges(candles):
    if not candles:
        return []

    tr = []
    prev_close = candles[0]["c"]

    for c in candles:
        tr.append(max(
            c["h"] - c["l"],
            abs(c["h"] - prev_close),
            abs(c["l"] - prev_close),
        ))
        prev_close = c["c"]

    return tr

def atr(candles, period=14):
    if not candles or len(candles) < period:
        return None

    trs = true_ranges(candles)
    return sum(trs[-period:]) / period

def tf_bias(candles):
    if not candles or len(candles) < 22:
        return "unknown"

    closes = [c["c"] for c in candles]
    e9 = ema(closes, 9)
    e21 = ema(closes, 21)

    if e9[-1] > e21[-1]:
        return "bullish"
    if e9[-1] < e21[-1]:
        return "bearish"
    return "neutral"

# ============================================================
# SWING / MARKET STRUCTURE
# ============================================================

def swing_points(candles, left=2, right=2):
    highs = []
    lows = []

    if len(candles) < left + right + 1:
        return highs, lows

    for i in range(left, len(candles) - right):
        h = candles[i]["h"]
        l = candles[i]["l"]

        left_highs = [candles[j]["h"] for j in range(i-left, i)]
        right_highs = [candles[j]["h"] for j in range(i+1, i+right+1)]
        left_lows = [candles[j]["l"] for j in range(i-left, i)]
        right_lows = [candles[j]["l"] for j in range(i+1, i+right+1)]

        if h > max(left_highs) and h >= max(right_highs):
            highs.append((i, h))

        if l < min(left_lows) and l <= min(right_lows):
            lows.append((i, l))

    return highs, lows

def structure_state(candles):
    if not candles or len(candles) < 12:
        return {
            "state": "unknown",
            "bos": None,
            "choch": None,
            "swing_high": None,
            "swing_low": None,
        }

    highs, lows = swing_points(candles)

    if len(highs) < 2 or len(lows) < 2:
        return {
            "state": "range",
            "bos": None,
            "choch": None,
            "swing_high": highs[-1][1] if highs else None,
            "swing_low": lows[-1][1] if lows else None,
        }

    prev_h = highs[-2][1]
    last_h = highs[-1][1]
    prev_l = lows[-2][1]
    last_l = lows[-1][1]

    if last_h > prev_h and last_l > prev_l:
        state = "bullish"
    elif last_h < prev_h and last_l < prev_l:
        state = "bearish"
    else:
        state = "range"

    close = candles[-1]["c"]

    recent_high = highs[-1][1]
    recent_low = lows[-1][1]

    bos = None
    choch = None

    # Breaks are deliberately confirmed using candle CLOSE.
    if close > recent_high:
        bos = "bullish"
    elif close < recent_low:
        bos = "bearish"

    # CHoCH approximation: price breaks the opposite-side swing
    # after the previous structure was directional.
    if state == "bearish" and close > recent_high:
        choch = "bullish"
    elif state == "bullish" and close < recent_low:
        choch = "bearish"

    return {
        "state": state,
        "bos": bos,
        "choch": choch,
        "swing_high": recent_high,
        "swing_low": recent_low,
    }

# ============================================================
# LIQUIDITY SWEEPS
# ============================================================

def liquidity_sweep(candles, lookback=20, tolerance=0.0008):
    """
    Finds a recent wick through a prior high/low followed by a close
    back inside the prior range.

    This is an objective approximation, not a claim of institutional
    order-flow visibility.
    """
    if not candles or len(candles) < lookback + 3:
        return None

    recent = candles[-1]
    prior = candles[-lookback-1:-1]

    prior_high = max(c["h"] for c in prior)
    prior_low = min(c["l"] for c in prior)

    high_tol = max(prior_high * tolerance, 0.01)
    low_tol = max(prior_low * tolerance, 0.01)

    # Bearish liquidity sweep:
    # wick above previous high, close below it.
    if recent["h"] > prior_high + high_tol and recent["c"] < prior_high:
        return {
            "type": "buy_side_sweep",
            "level": prior_high,
            "direction": "bearish",
        }

    # Bullish liquidity sweep:
    # wick below previous low, close above it.
    if recent["l"] < prior_low - low_tol and recent["c"] > prior_low:
        return {
            "type": "sell_side_sweep",
            "level": prior_low,
            "direction": "bullish",
        }

    return None

# ============================================================
# FVG
# ============================================================

def find_fvgs(candles, max_age=20):
    """
    Three-candle imbalance approximation.

    Bullish FVG:
        candle[i].high < candle[i+2].low

    Bearish FVG:
        candle[i].low > candle[i+2].high
    """
    out = []

    if not candles or len(candles) < 3:
        return out

    start = max(0, len(candles) - max_age - 2)

    for i in range(start, len(candles) - 2):
        a = candles[i]
        c = candles[i + 2]

        if a["h"] < c["l"]:
            out.append({
                "type": "bullish",
                "low": a["h"],
                "high": c["l"],
                "index": i + 1,
            })

        if a["l"] > c["h"]:
            out.append({
                "type": "bearish",
                "low": c["h"],
                "high": a["l"],
                "index": i + 1,
            })

    return out

def nearest_fvg(candles, direction, price):
    fvgs = find_fvgs(candles)

    candidates = [
        f for f in fvgs
        if f["type"] == direction
    ]

    if not candidates:
        return None

    # Prefer the nearest zone to current price.
    def distance(f):
        if f["low"] <= price <= f["high"]:
            return 0
        return min(abs(price - f["low"]), abs(price - f["high"]))

    return min(candidates, key=distance)

# ============================================================
# ORDER BLOCK CANDIDATE
# ============================================================

def order_block_candidate(candles, direction, lookback=30):
    """
    Conservative price-action approximation:
    - Bullish OB = most recent bearish candle before a strong bullish move.
    - Bearish OB = most recent bullish candle before a strong bearish move.

    "Order block" is treated as a price-action zone, not proof of
    institutional orders.
    """
    if not candles or len(candles) < 8:
        return None

    start = max(1, len(candles) - lookback)

    ranges = [
        c["h"] - c["l"]
        for c in candles[start:]
        if c["h"] > c["l"]
    ]

    if not ranges:
        return None

    avg_range = sum(ranges) / len(ranges)

    for i in range(len(candles) - 2, start - 1, -1):
        c = candles[i]
        nxt = candles[i + 1]

        body = abs(c["c"] - c["o"])
        next_body = abs(nxt["c"] - nxt["o"])

        if direction == "bullish":
            if c["c"] < c["o"] and nxt["c"] > nxt["o"]:
                if next_body >= max(avg_range * 0.8, body * 1.2):
                    return {
                        "type": "bullish",
                        "low": c["l"],
                        "high": c["h"],
                        "index": i,
                    }

        if direction == "bearish":
            if c["c"] > c["o"] and nxt["c"] < nxt["o"]:
                if next_body >= max(avg_range * 0.8, body * 1.2):
                    return {
                        "type": "bearish",
                        "low": c["l"],
                        "high": c["h"],
                        "index": i,
                    }

    return None

# ============================================================
# FIB / OTE
# ============================================================

def fib_ote(candles, lookback=50):
    if not candles or len(candles) < lookback:
        return None

    window = candles[-lookback:]
    high = max(c["h"] for c in window)
    low = min(c["l"] for c in window)

    if high <= low:
        return None

    diff = high - low

    return {
        "high": high,
        "low": low,
        "range": diff,
        "0.618": high - diff * 0.618,
        "0.65": high - diff * 0.65,
        "0.705": high - diff * 0.705,
        "0.79": high - diff * 0.79,
    }

def in_ote(price, fib, direction):
    if not fib:
        return False

    if direction == "long":
        zone_low = fib["0.79"]
        zone_high = fib["0.618"]
    else:
        # Mirror the zone for bearish retracement.
        zone_low = fib["low"] + fib["range"] * 0.618
        zone_high = fib["low"] + fib["range"] * 0.79

    return min(zone_low, zone_high) <= price <= max(zone_low, zone_high)

# ============================================================
# SESSION
# ============================================================

def session_name():
    """
    Uses UTC internally. Change these if your preferred session
    definition differs.

    London: 08:00-11:00 UTC
    New York: 13:30-16:00 UTC
    """
    hour_min = datetime.now(timezone.utc).hour * 60 + datetime.now(timezone.utc).minute

    if 8 * 60 <= hour_min <= 11 * 60:
        return "London killzone"

    if 13 * 60 + 30 <= hour_min <= 16 * 60:
        return "New York killzone"

    return "outside killzone"

# ============================================================
# NEWS
# ============================================================

def get_news_warning():
    now_ts = datetime.now(timezone.utc).timestamp()

    if now_ts - NEWS_CACHE["t"] < 1800:
        events = NEWS_CACHE["d"]
    else:
        try:
            r = requests.get(
                "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
                timeout=15,
            )
            r.raise_for_status()
            events = r.json()

            NEWS_CACHE["t"] = now_ts
            NEWS_CACHE["d"] = events

        except Exception as e:
            logger.error("News error: %s", e)
            return ""

    warns = []
    now = datetime.now(timezone.utc)

    for ev in events:
        try:
            if ev.get("country") != "USD":
                continue

            if ev.get("impact") != "High":
                continue

            dt = datetime.fromisoformat(
                ev["date"].replace("Z", "+00:00")
            )

            diff = (dt - now).total_seconds() / 60

            if -30 <= diff <= 60:
                warns.append(
                    f"{ev.get('title', 'USD event')} ({int(diff)}m)"
                )

        except Exception:
            continue

    if warns:
        return (
            "HIGH IMPACT USD: "
            + ", ".join(warns[:3])
            + " — HARLEEN VETO"
        )

    return ""

# ============================================================
# OBJECTIVE SWARM ENGINE
# ============================================================


def average_range(candles, period=20):
    if not candles:
        return None
    sample = candles[-min(period, len(candles)):]
    if not sample:
        return None
    return sum(max(x["h"] - x["l"], 0) for x in sample) / len(sample)

def price_levels(candles, lookback=50):
    """Objective liquidity reference levels from completed historical candles."""
    if not candles:
        return {}
    sample = candles[-min(lookback, len(candles)):]
    return {
        "recent_high": max(x["h"] for x in sample),
        "recent_low": min(x["l"] for x in sample),
        "equal_high": detect_equal_level(sample, "high"),
        "equal_low": detect_equal_level(sample, "low"),
    }

def detect_equal_level(candles, side, tolerance=0.0015, min_hits=2):
    """Approximate equal highs/lows without claiming order-book knowledge."""
    if len(candles) < 5:
        return None
    vals = [c["h"] if side == "high" else c["l"] for c in candles[-40:]]
    clusters = []
    for v in vals:
        placed = False
        for cluster in clusters:
            center = sum(cluster) / len(cluster)
            if center and abs(v - center) / center <= tolerance:
                cluster.append(v)
                placed = True
                break
        if not placed:
            clusters.append([v])
    good = [x for x in clusters if len(x) >= min_hits]
    if not good:
        return None
    best = max(good, key=len)
    return round(sum(best) / len(best), 2)

def session_levels(candles):
    """Previous-day/session-style levels when timestamps are parseable."""
    if not candles:
        return {}
    # Twelve Data timestamps can vary; use the last UTC date as a stable,
    # non-predictive reference and the immediately preceding date.
    parsed = []
    for c in candles:
        try:
            dt = datetime.fromisoformat(str(c["t"]).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            parsed.append((dt.astimezone(timezone.utc).date(), c))
        except Exception:
            continue

    if not parsed:
        return {}

    latest_day = parsed[-1][0]
    previous = [c for d, c in parsed if d < latest_day]
    current = [c for d, c in parsed if d == latest_day]

    out = {}
    if previous:
        out["previous_day_high"] = round(max(c["h"] for c in previous), 2)
        out["previous_day_low"] = round(min(c["l"] for c in previous), 2)
    if current:
        out["current_session_high"] = round(max(c["h"] for c in current), 2)
        out["current_session_low"] = round(min(c["l"] for c in current), 2)
    return out

def market_regime(candles, atr_period=14, trend_period=50):
    """Classify trend/range/volatility using deterministic price statistics."""
    if not candles or len(candles) < max(atr_period + 5, trend_period + 5):
        return {"name": "unknown", "trend_strength": 0, "volatility": "unknown"}

    a = atr(candles, atr_period)
    avg_r = average_range(candles, atr_period)
    closes = [c["c"] for c in candles]
    fast_series = ema(closes, 9)
    slow_series = ema(closes, 21)
    base_series = ema(closes, trend_period)

    # EMA() returns a full series.  The regime classifier needs the latest
    # scalar values; subtracting the series themselves caused the deployed
    # auto loop error: "list" - "list".
    fast = fast_series[-1] if fast_series else None
    slow = slow_series[-1] if slow_series else None
    base = base_series[-1] if base_series else None

    if None in (a, avg_r, fast, slow, base) or base == 0:
        return {"name": "unknown", "trend_strength": 0, "volatility": "unknown"}

    trend_gap = abs(float(fast) - float(slow)) / float(base)
    volatility_ratio = float(a) / float(base)

    if trend_gap >= 0.0025:
        trend = "trending"
    elif trend_gap <= 0.0010:
        trend = "ranging"
    else:
        trend = "transition"

    # Relative thresholds are intentionally broad and instrument-aware.
    if volatility_ratio >= 0.0040:
        vol = "high"
    elif volatility_ratio <= 0.0015:
        vol = "low"
    else:
        vol = "normal"

    return {
        "name": f"{trend}_{vol}",
        "trend_strength": round(trend_gap * 10000, 2),
        "volatility": vol,
        "atr": round(a, 2),
        "avg_range": round(avg_r, 2),
    }

def zone_distance(price, zone):
    if not zone or price is None:
        return None
    try:
        hi = max(float(zone["high"]), float(zone["low"]))
        lo = min(float(zone["high"]), float(zone["low"]))
        if lo <= price <= hi:
            return 0.0
        return min(abs(price - lo), abs(price - hi))
    except Exception:
        return None



def cluster_levels(values, tolerance):
    """Cluster nearby prices into objective zones."""
    if not values:
        return []
    vals = sorted(float(v) for v in values if v is not None)
    clusters = []
    for v in vals:
        if not clusters:
            clusters.append([v])
            continue
        center = sum(clusters[-1]) / len(clusters[-1])
        if abs(v - center) <= tolerance:
            clusters[-1].append(v)
        else:
            clusters.append([v])
    return clusters

def support_resistance(candles, lookback=120, atr_period=14):
    """
    Build S/R zones from repeated swing reactions.

    This is a price-action S/R model, not a claim about hidden institutional
    orders. A level gets stronger when multiple independent swing points
    cluster around the same price.
    """
    if not candles or len(candles) < 20:
        return {"supports": [], "resistances": []}

    sample = candles[-min(lookback, len(candles)):]
    a = atr(sample, atr_period) or average_range(sample, 20) or 1.0
    tolerance = max(a * 0.30, sample[-1]["c"] * 0.0008)

    lows = []
    highs = []
    for i in range(2, len(sample) - 2):
        if sample[i]["l"] <= min(sample[i-2]["l"], sample[i-1]["l"],
                                  sample[i+1]["l"], sample[i+2]["l"]):
            lows.append(sample[i]["l"])
        if sample[i]["h"] >= max(sample[i-2]["h"], sample[i-1]["h"],
                                  sample[i+1]["h"], sample[i+2]["h"]):
            highs.append(sample[i]["h"])

    def make_zones(points, kind):
        zones = []
        for cluster in cluster_levels(points, tolerance):
            if len(cluster) < 2:
                continue
            level = sum(cluster) / len(cluster)
            # Count later reactions around the cluster.
            reactions = sum(
                1 for c in sample
                if c["l"] <= level + tolerance and c["h"] >= level - tolerance
            )
            recency = sum(
                1 for c in sample[-30:]
                if c["l"] <= level + tolerance and c["h"] >= level - tolerance
            )
            strength = min(100, len(cluster) * 18 + min(reactions, 8) * 5)
            zones.append({
                "type": kind,
                "low": round(level - tolerance, 2),
                "high": round(level + tolerance, 2),
                "level": round(level, 2),
                "touch_clusters": len(cluster),
                "reactions": reactions,
                "recent_reactions": recency,
                "strength": strength,
            })
        return sorted(zones, key=lambda x: x["strength"], reverse=True)

    return {
        "supports": make_zones(lows, "support"),
        "resistances": make_zones(highs, "resistance"),
    }

def nearest_sr(price, sr):
    candidates = []
    for z in sr.get("supports", []) + sr.get("resistances", []):
        dist = zone_distance(price, z)
        if dist is not None:
            candidates.append((dist, z))
    if not candidates:
        return None
    return min(candidates, key=lambda x: x[0])[1]

def psychological_levels(price, step=10.0, tolerance_ratio=0.35):
    """
    Round-number / psychological price levels.

    For XAU/USD this uses $10 major increments and $5 half-levels.
    The exact level is a reference, not a prediction.
    """
    if price is None:
        return {"nearest_major": None, "nearest_half": None, "near": False}

    major = round(price / step) * step
    half_step = step / 2
    half = round(price / half_step) * half_step

    distance_major = abs(price - major)
    distance_half = abs(price - half)

    tolerance = step * tolerance_ratio
    near_level = min(distance_major, distance_half) <= tolerance

    return {
        "nearest_major": round(major, 2),
        "nearest_half": round(half, 2),
        "distance_major": round(distance_major, 2),
        "distance_half": round(distance_half, 2),
        "near": near_level,
        "major_step": step,
        "half_step": half_step,
    }

def sr_confluence(direction, price, sr):
    """Return nearest S/R context and whether it supports the direction."""
    supports = sr.get("supports", [])
    resistances = sr.get("resistances", [])

    if direction == "long":
        below = [z for z in supports if z["level"] <= price]
        nearest = max(below, key=lambda z: z["level"]) if below else None
        return nearest, bool(nearest and price - nearest["level"] <=
                             max((z["high"] - z["low"]) * 2 for z in supports) if supports else False)

    if direction == "short":
        above = [z for z in resistances if z["level"] >= price]
        nearest = min(above, key=lambda z: z["level"]) if above else None
        return nearest, bool(nearest and nearest["level"] - price <=
                             max((z["high"] - z["low"]) * 2 for z in resistances) if resistances else False)

    return None, False

def order_flow_proxy(candles, period=20):
    """
    Candle/volume-based order-flow PROXY.

    Twelve Data OHLCV does not provide true bid/ask aggressor volume or a
    Level-2 order book. Therefore this module must never call this 'true
    order flow'. It estimates pressure from candle location, range and
    available volume/tick-volume.
    """
    if not candles or len(candles) < period:
        return {
            "bias": "unknown", "score": 0, "imbalance": 0,
            "cvd_proxy": 0, "absorption": False, "displacement": False
        }

    sample = candles[-period:]
    buy_pressure = 0.0
    sell_pressure = 0.0
    signed_flow = 0.0
    displacement_count = 0
    absorption_count = 0

    avg_range = sum(max(c["h"] - c["l"], 1e-9) for c in sample) / len(sample)
    avg_vol = sum(float(c.get("v", 0) or 0) for c in sample) / len(sample)

    for c in sample:
        rng = max(c["h"] - c["l"], 1e-9)
        close_location = ((c["c"] - c["l"]) - (c["h"] - c["c"])) / rng
        vol = float(c.get("v", 0) or 0)

        # -1 to +1 pressure estimate based on candle close location.
        pressure = max(-1.0, min(1.0, close_location))
        weighted = pressure * (vol if vol > 0 else 1.0)

        if pressure > 0:
            buy_pressure += abs(weighted)
        elif pressure < 0:
            sell_pressure += abs(weighted)

        signed_flow += weighted

        if rng >= avg_range * 1.5 and abs(pressure) >= 0.55:
            displacement_count += 1

        # Large volume/range with a poor close can indicate absorption.
        if avg_vol > 0 and vol >= avg_vol * 1.5 and abs(pressure) <= 0.20:
            absorption_count += 1

    total = buy_pressure + sell_pressure
    imbalance = signed_flow / total if total else 0.0

    if imbalance >= 0.18:
        bias = "bullish"
    elif imbalance <= -0.18:
        bias = "bearish"
    else:
        bias = "neutral"

    return {
        "bias": bias,
        "score": round(max(-100, min(100, imbalance * 100)), 2),
        "imbalance": round(imbalance, 4),
        "cvd_proxy": round(signed_flow, 2),
        "absorption": absorption_count >= 1,
        "displacement": displacement_count >= 1,
        "displacement_count": displacement_count,
        "absorption_count": absorption_count,
        "note": "OHLCV pressure proxy; not true bid/ask order flow",
    }

def vwap(candles, period=50):
    if not candles:
        return None
    sample = candles[-min(period, len(candles)):]
    total_vol = sum(float(c.get("v", 0) or 0) for c in sample)
    if total_vol <= 0:
        return sum(c["c"] for c in sample) / len(sample)
    return sum(((c["h"] + c["l"] + c["c"]) / 3) * float(c.get("v", 0) or 0)
               for c in sample) / total_vol

def momentum_confluence(candles):
    if len(candles) < 30:
        return {"bias": "unknown", "adx_proxy": 0, "rsi": 50, "ema_slope": 0}

    closes = [c["c"] for c in candles]
    e9_series = ema(closes, 9)
    e21_series = ema(closes, 21)
    e50_series = ema(closes, 50)
    e9 = e9_series[-1] if e9_series else None
    e21 = e21_series[-1] if e21_series else None
    e50 = e50_series[-1] if e50_series else None
    r = rsi(closes, 14) if "rsi" in globals() else None

    # Simple deterministic directional-strength proxy.
    atr_v = atr(candles, 14)
    adx_proxy = 0
    if atr_v and e50 is not None and e9 is not None and e21 is not None:
        adx_proxy = abs(float(e9) - float(e21)) / float(atr_v) * 10

    slope = 0
    if len(closes) >= 10:
        slope = closes[-1] - closes[-10]

    if e9 > e21 > e50:
        bias = "bullish"
    elif e9 < e21 < e50:
        bias = "bearish"
    else:
        bias = "neutral"

    return {
        "bias": bias,
        "adx_proxy": round(adx_proxy, 2),
        "rsi": round(r, 2) if r is not None else None,
        "ema_slope": round(slope, 2),
    }

def displacement_quality(candles, direction, period=20):
    if len(candles) < period + 2:
        return False
    sample = candles[-period:]
    avg = sum(max(c["h"] - c["l"], 1e-9) for c in sample[:-1]) / max(len(sample)-1, 1)
    c = sample[-1]
    rng = max(c["h"] - c["l"], 1e-9)
    body = abs(c["c"] - c["o"])
    if avg <= 0:
        return False
    if direction == "long":
        return c["c"] > c["o"] and body / rng >= 0.60 and rng >= avg * 1.5
    if direction == "short":
        return c["c"] < c["o"] and body / rng >= 0.60 and rng >= avg * 1.5
    return False

def premium_discount(candles, lookback=60):
    if len(candles) < 5:
        return {"zone": "unknown", "mid": None, "high": None, "low": None}
    sample = candles[-min(lookback, len(candles)):]
    hi = max(c["h"] for c in sample)
    lo = min(c["l"] for c in sample)
    mid = (hi + lo) / 2
    price = sample[-1]["c"]
    return {
        "zone": "premium" if price > mid else "discount",
        "mid": round(mid, 2),
        "high": round(hi, 2),
        "low": round(lo, 2),
    }

def quality_score(direction, price, c15, c5, bias4, bias1, s15, s5,
                  sweep, fvg, ob, fib, regime, levels, flow=None,
                  momentum=None, pd=None, sr=None, psy=None,
                  sr_near=None, sr_aligned=False, market=None):
    """
    V20 expanded confluence model.
    Maximum = 100. Numbers are deterministic weights, not probabilities.
    """
    if direction not in ("long", "short"):
        return 0, []

    wanted = "bullish" if direction == "long" else "bearish"
    points = 0
    reasons = []

    checks = [
        (bias4 == wanted, 10, "4H direction aligned"),
        (bias1 == wanted, 10, "1H direction aligned"),
        (s15.get("state") == wanted, 8, "15M structure aligned"),
        (s15.get("bos") == wanted or s15.get("choch") == wanted, 8, "15M BOS/CHoCH aligned"),
        (s5.get("state") == wanted, 5, "5M structure aligned"),
        (sweep and sweep.get("direction") == direction, 12, "Liquidity sweep confirmed"),
        (bool(fvg), 5, "FVG present"),
        (bool(ob), 5, "Order-block candidate present"),
        (in_ote(price, fib, direction), 5, "OTE aligned"),
        (regime.get("name", "").startswith("trending"), 4, "Trending regime"),
        (flow and flow.get("bias") == wanted, 12, "Order-flow proxy aligned"),
        (flow and flow.get("displacement"), 3, "Flow displacement"),
        (flow and flow.get("absorption"), 2, "Absorption context"),
        (momentum and momentum.get("bias") == wanted, 4, "Momentum aligned"),
        (momentum and momentum.get("adx_proxy", 0) >= 10, 2, "Momentum strength"),
        (pd and ((direction == "long" and pd.get("zone") == "discount") or
                 (direction == "short" and pd.get("zone") == "premium")), 3,
         "Premium/discount aligned"),
        (levels.get("equal_low") is not None and direction == "long", 1, "Equal-low liquidity reference"),
        (levels.get("equal_high") is not None and direction == "short", 1, "Equal-high liquidity reference"),
        (sr_near is not None and sr_aligned, 5, "Support/resistance aligned"),
        (sr_near is not None and sr_near.get("strength", 0) >= 55, 3, "Strong S/R zone"),
        (psy and psy.get("near"), 3, "Psychological level nearby"),
        (psy and direction == "long" and psy.get("nearest_major") is not None and
         psy.get("nearest_major") <= price, 1, "Long below/at major round level"),
        (psy and direction == "short" and psy.get("nearest_major") is not None and
         psy.get("nearest_major") >= price, 1, "Short above/at major round level"),
    ]

    for ok, weight, label in checks:
        if ok:
            points += weight
            reasons.append(label)

    # v22: advanced-level confirmation bonus (capped by helper).
    # This used to reference undefined local variables and was silently
    # swallowed by an exception handler, so v22 scoring never applied.
    market = market or {}
    bonus = v22_score_bonus(direction, market)
    if bonus:
        points += bonus
        reasons.append(f"v22 advanced confluence +{bonus}")

    return min(points, 100), reasons

def score_grade(score):
    if score >= 85:
        return "A+"
    if score >= 75:
        return "A"
    if score >= 65:
        return "B"
    if score >= 55:
        return "C"
    return "NO-TRADE"

def risk_engine(direction, price, s5, c5, atr_value):
    """Single source of truth for entry, invalidation and R ladder."""
    if direction not in ("long", "short") or not atr_value or atr_value <= 0:
        return {"entry": None, "sl": None, "tp": [], "risk": None, "rr_tp10": None}

    entry = float(price)

    if direction == "long":
        structural_low = s5.get("swing_low") or min(c["l"] for c in c5[-20:])
        sl = min(structural_low - atr_value * 0.25, entry - atr_value * 1.2)
        risk = entry - sl
        tps = [round(entry + risk * x, 2)
               for x in [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]]
    else:
        structural_high = s5.get("swing_high") or max(c["h"] for c in c5[-20:])
        sl = max(structural_high + atr_value * 0.25, entry + atr_value * 1.2)
        risk = sl - entry
        tps = [round(entry - risk * x, 2)
               for x in [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]]

    if risk <= 0:
        return {"entry": None, "sl": None, "tp": [], "risk": None, "rr_tp10": None}

    return {
        "entry": round(entry, 2),
        "sl": round(sl, 2),
        "tp": tps,
        "risk": round(risk, 2),
        "rr_tp10": 10.0,
    }

def analyze_market():
    # Reuse a very recent completed scan so repeated Telegram commands do not
    # hit the data provider again. Ten seconds is short enough for manual use.
    now_ts = datetime.now().timestamp()
    if ANALYSIS_CACHE["d"] is not None and now_ts - ANALYSIS_CACHE["t"] < ANALYSIS_CACHE_TTL:
        return ANALYSIS_CACHE["d"]

    # Fetch market data and news concurrently. Previously the four candle
    # requests and news request were partly serialized, increasing latency.
    requests_to_fetch = [("4h", 160), ("1h", 160), ("15min", 220), ("5min", 140)]
    with ThreadPoolExecutor(max_workers=5) as pool:
        candle_futures = [
            pool.submit(get_candles, "XAU/USD", interval, n)
            for interval, n in requests_to_fetch
        ]
        news_future = pool.submit(get_news_warning)
        results = [f.result() for f in candle_futures]
        news = news_future.result()

    c4h, c1h, c15, c5 = results
    if not all([c4h, c1h, c15, c5]):
        return {"valid": False, "reason": "Insufficient market data"}

    price = c5[-1]["c"]

    # ---------------- ROSITA ----------------
    bias4 = tf_bias(c4h)
    bias1 = tf_bias(c1h)

    s4 = structure_state(c4h)
    s1 = structure_state(c1h)
    s15 = structure_state(c15)
    s5 = structure_state(c5)

    # Rosita is deliberately conservative: continuation requires 4H+1H
    # alignment. A sweep can suggest reversal, but does not override the
    # higher-timeframe bias automatically.
    rosita_direction = None
    if bias4 == "bullish" and bias1 == "bullish":
        rosita_direction = "long"
    elif bias4 == "bearish" and bias1 == "bearish":
        rosita_direction = "short"

    # ---------------- MAGNA ----------------
    sweep = liquidity_sweep(c15, lookback=24)
    fib = fib_ote(c15, 60)

    long_fvg = nearest_fvg(c15, "bullish", price)
    short_fvg = nearest_fvg(c15, "bearish", price)
    long_ob = order_block_candidate(c15, "bullish")
    short_ob = order_block_candidate(c15, "bearish")

    # A sweep can identify a reversal candidate, but V19 records both the
    # Rosita trend direction and Magna's candidate direction separately.
    candidate = rosita_direction
    if sweep:
        if sweep["direction"] == "bullish":
            candidate = "long"
        elif sweep["direction"] == "bearish":
            candidate = "short"

    fvg = long_fvg if candidate == "long" else short_fvg if candidate == "short" else None
    ob = long_ob if candidate == "long" else short_ob if candidate == "short" else None

    # ---------------- HARLEEN -----------------
    session = session_name()
    regime = market_regime(c15)
    levels = {}
    levels.update(price_levels(c15, 60))
    levels.update(session_levels(c15))

    # Multi-timeframe S/R maps. 15M is the primary execution map while 1H/4H
    # are used as higher-timeframe references.
    sr4 = support_resistance(c4h, 120)
    sr1 = support_resistance(c1h, 120)
    sr15 = support_resistance(c15, 160)
    psy = psychological_levels(price, step=10.0)

    flow = order_flow_proxy(c5, 20)
    momentum = momentum_confluence(c15)
    pd = premium_discount(c15, 60)
    vwap_value = vwap(c15, 50)

    # Harleen hard vetoes remain separate from the quality score.
    veto_reasons = []
    if news:
        veto_reasons.append(news)

    # Avoid treating unknown regime as a veto; it simply lowers confidence.
    if regime.get("name") == "unknown":
        veto_reasons.append("Market regime could not be classified")

    harleen_veto = bool(news)

    # ---------------- v22 ADVANCED ENRICHMENT ----------------
    # ATR is calculated once here and reused by v22 confirmations and risk.
    a = atr(c5, 14)

    # Keep all v22 calculations inside analyze_market() so the values are
    # available to scoring, veto logic, output and journaling.
    market = {
        "candles": {
            "15min": c15,
            "5min": c5,
            "1h": c1h,
            "4h": c4h,
        },
        "support_resistance": {
            "4h": sr4,
            "1h": sr1,
            "15m": sr15,
        },
        "psychological_levels": psy,
        "atr": a,
        "structure": s5,
        "rsi_values": None,
        "momentum_values": None,
    }

    base15 = c15
    base5 = c5
    level_source = base15 or base5 or c1h

    market["v22_levels"] = {
        "previous_periods": previous_period_levels(level_source),
        "sessions": session_levels(level_source),
    }

    # Add dedicated 5M S/R to the v22 map.
    market["support_resistance"]["5m"] = support_resistance(base5, 120)

    # Nearest zone state for every timeframe.
    sr_states = {}
    for tf, srdata in market["support_resistance"].items():
        sr_states[tf] = {}
        if not isinstance(srdata, dict):
            continue
        for side, key in (("support", "supports"), ("resistance", "resistances")):
            zones = srdata.get(key) or []
            if zones:
                z = min(zones, key=lambda zone: zone_distance(price, zone)
                        if zone_distance(price, zone) is not None else float("inf"))
                sr_states[tf][side] = {**z, "state": sr_state(price, z)}
    market["sr_states"] = sr_states

    # Break/retest confirmation uses the nearest 15M level and 5M candles.
    market["break_retest"] = {}
    br_atr = atr(base5, 14)
    for side, direction in (("resistance", "LONG"), ("support", "SHORT")):
        z = sr_states.get("15m", {}).get(side)
        if z:
            market["break_retest"][side] = break_retest_confirmation(
                base5, z.get("level"), direction, br_atr
            )

    # Fibonacci extensions from the latest objective 5M swing pair.
    sh = s5.get("swing_high")
    sl = s5.get("swing_low")
    market["fib_extensions"] = {}
    if sh is not None and sl is not None:
        market["fib_extensions"] = {
            "LONG": fib_extension_targets(price, sh, sl, "LONG"),
            "SHORT": fib_extension_targets(price, sh, sl, "SHORT"),
        }

    # RSI series was not previously retained by the engine. Calculate it
    # locally when the rsi() helper exists; otherwise leave divergence neutral.
    if "rsi" in globals():
        try:
            market["rsi_values"] = rsi_series([c["c"] for c in base15], 14)
        except Exception:
            market["rsi_values"] = None

    if market.get("rsi_values"):
        market["divergence"] = divergence_detection(base15, market["rsi_values"])
    else:
        market["divergence"] = {
            "bullish": False, "bearish": False,
            "details": "indicator series unavailable"
        }

    market["level_confluence"] = {
        "sr_available": bool(market["support_resistance"]),
        "psychological_available": bool(psy),
        "previous_periods_available": bool(market["v22_levels"]["previous_periods"]),
        "sessions_available": bool(market["v22_levels"]["sessions"]),
        "break_retest": market["break_retest"],
        "divergence": market["divergence"],
        "fib_extensions": bool(market["fib_extensions"]),
    }

    # ---------------- OBJECTIVE SCORE ----------------
    score, confluences = quality_score(
        candidate, price, c15, c5, bias4, bias1, s15, s5,
        sweep, fvg, ob, fib, regime, levels,
        flow=flow, momentum=momentum, pd=pd,
        sr=sr15, psy=psy,
        sr_near=nearest_sr(price, sr15),
        sr_aligned=sr_confluence(candidate, price, sr15)[1] if candidate else False,
        market=market
    )
    grade = score_grade(score)

    # V19 threshold: 75+ required, plus no hard Harleen veto.
    flow_aligned = flow.get("bias") == ("bullish" if candidate == "long" else "bearish")
    setup_valid = (
        candidate in ("long", "short")
        and score >= 75
        and not harleen_veto
        and regime.get("name") != "unknown"
        and flow.get("bias") != "unknown"
    )
    if candidate and not flow_aligned:
        veto_reasons.append("Order-flow proxy conflicts with setup direction")

    # ---------------- RISK ENGINE ----------------
    a = atr(c5, 14)
    risk = risk_engine(candidate, price, s5, c5, a)

    if setup_valid and risk["sl"] is None:
        setup_valid = False
        veto_reasons.append("Risk engine could not produce valid invalidation")

    if score < 75:
        veto_reasons.append(f"Objective score {score}/100 below A-grade threshold")

    if candidate is None:
        veto_reasons.append("4H/1H directional bias is not aligned")

    if rosita_direction and sweep and sweep["direction"] != rosita_direction:
        confluences.append("Magna sweep conflicts with Rosita trend")

    signal_id = make_signal_id()

    result = {
        "valid": setup_valid,
        "signal_id": signal_id,
        "symbol": "XAU/USD",
        "price": round(price, 2),

        "rosita": {
            "role": "Boss / top-down trend analyst",
            "bias_4h": bias4,
            "bias_1h": bias1,
            "direction": rosita_direction,
            "structure_4h": s4["state"],
            "structure_1h": s1["state"],
            "structure_15m": s15["state"],
            "structure_5m": s5["state"],
            "bos_15m": s15["bos"],
            "choch_15m": s15["choch"],
        },

        "harleen": {
            "role": "Risk manager / veto",
            "verdict": "VETO" if harleen_veto else "PASS",
            "news": news or "No high-impact USD warning in configured window",
            "session": session,
            "veto_reasons": veto_reasons[:6],
        },

        "magna": {
            "role": "Sniper / setup analyst",
            "direction": candidate,
            "sweep": sweep,
            "fvg": fvg,
            "order_block": ob,
            "fib": fib,
            "ote": in_ote(price, fib, candidate) if candidate else False,
        },

        "market": {
            "regime": regime,
            "levels": levels,
            "vwap": round(vwap_value, 2) if vwap_value else None,
            "premium_discount": pd,
            "momentum": momentum,
            "order_flow_proxy": flow,
            "support_resistance": {
                "4h": sr4,
                "1h": sr1,
                "15m": sr15,
                "nearest": nearest_sr(price, sr15),
            },
            "psychological_levels": psy,
            "v22_levels": market.get("v22_levels", {}),
            "sr_states": market.get("sr_states", {}),
            "break_retest": market.get("break_retest", {}),
            "fib_extensions": market.get("fib_extensions", {}),
            "divergence": market.get("divergence", {}),
            "level_confluence": market.get("level_confluence", {}),
        },

        "risk": {
            "atr_5m": round(a, 2) if a else None,
            **risk,
        },

        "score": score,
        "grade": grade,
        "confluences": confluences[:12],
        "reasons": veto_reasons[:8],
    }

    # Record every scan that reaches the objective engine. This makes
    # later research possible even for rejected setups.
    journal_signal(result, event="SCAN")
    ANALYSIS_CACHE["t"] = datetime.now().timestamp()
    ANALYSIS_CACHE["d"] = result
    return result

# ============================================================
# GROQ EXPLANATION
# ============================================================

SYSTEM = """
You are SWARM v22.0 — three girls in one brain, backed by an objective Python referee.

ALWAYS include: 🫦 👀 💕

ROSITA (Boss/Alice)
- Top-down analyst.
- Reads 4H -> 1H -> 15M -> 5M.
- Focuses on trend and market structure.
- Does NOT invent technical values.

HARLEEN QUINZEL (Risk/Azariah)
- Risk controller and veto.
- If news says VETO, the final answer MUST be VETO.
- Looks at session context and setup quality.
- Manual execution only.

MAGNA (Sniper/Nora)
- Looks for liquidity sweep, BOS/CHoCH, FVG, order-block candidate and OTE.
- Uses ONLY the values supplied by the Python engine.
- Does NOT invent Entry, SL or TP.
- If Magna conflicts with Rosita, explicitly say so.\n- Treat order-flow as an OHLCV proxy unless a real bid/ask feed is connected.

CRITICAL:
The Python engine is the source of truth for all numerical technical measurements.
Never invent an Entry, SL, TP, ATR, score, Fibonacci level, or market structure value.
If Python says no valid setup, say no valid setup.

This is educational/manual analysis only, not guaranteed financial advice.
Call the user Shay.

Response style:
- Be concise and decision-focused.
- Keep normal signal replies under 350 words.
- ALWAYS give separate Rosita, Magna, and Harleen breakdowns, even when the setup is invalid.
- For an invalid setup, explain what each agent found before stating the final no-setup/veto decision.
- Preserve important findings supplied by the Python engine; do not invent missing values.

Preferred format:

SWARM v22.0
Bias 4H/1H: ...
Rosita: ...
Harleen Verdict: PASS/VETO — reason
Magna Snipe: ...
Direction: ...
Entry: ...
SL: ...
TP1-TP10: ...
Objective Score: ...
Reason: ...
Confluences:
- ...
- ...
- ...

If invalid:
NO VALID A/B/C SETUP
Harleen: ...
Reason: ...
"""

async def ask_groq(user_text, chat_id):
    cid = str(chat_id)

    HISTORY[cid].append({
        "role": "user",
        "content": user_text,
    })

    mem = LONG_MEM.get(cid, "")

    if not client:
        return "No brain yet Shay 🫦 👀 add GROQ_API_KEY 💕"

    msgs = [{
        "role": "system",
        "content": SYSTEM + f"\n[Memory] {mem}",
    }]

    for m in list(HISTORY[cid])[-10:]:
        msgs.append(m)

    try:
        r = await asyncio.to_thread(
            client.chat.completions.create,
            model="openai/gpt-oss-20b",
            messages=msgs,
            temperature=0.1,
            max_tokens=550,
        )

        txt = r.choices[0].message.content.strip()

        HISTORY[cid].append({
            "role": "assistant",
            "content": txt,
        })

        return txt

    except Exception as e:
        logger.error("Groq error: %s", e)
        return f"Brain fog Shay 🫦 👀 {e} 💕"

# ============================================================
# TELEGRAM SCREENSHOT / CHART VISION
# ============================================================

VISION_SYSTEM = """
You are the visual-analysis layer of SWARM v22.0.
The user may send a screenshot of an XAU/USD chart, broker quote panel,
technical-analysis chart, or related market screen.

Analyze ONLY what is actually visible and legible in the image. Never invent
prices, candles, indicators, timeframes, support/resistance, entry, SL, TP,
news, or order-flow data that cannot be read from the screenshot.

FIRST classify the screenshot (one or more):
- PRICE CHART: candlesticks/line chart with price and time.
- ORDER-FLOW / FOOTPRINT: bid x ask or buy/sell volume printed at individual
  price levels inside candles, footprint numbers, delta, stacked imbalance,
  POC, VAH/VAL, or similar footprint data.
- VOLUME PROFILE: horizontal volume-at-price distribution, POC, VAH, VAL,
  high/low-volume nodes.
- DOM / ORDER BOOK: bid/ask depth, resting liquidity, market depth, ladder.
- CVD / DELTA: cumulative delta, bar delta, aggressive buy/sell volume.
- QUOTES: bid, ask, spread, last price or broker quote panel.
- NEWS / CALENDAR: economic events or scheduled releases.
- MIXED: more than one of the above.

ORDER-FLOW READING RULES:
- If a true footprint/order-flow chart is visible, read the actual bid/ask,
  delta, imbalance, POC/value-area or absorption information shown on it.
- Distinguish bid/ask volume from ordinary candle volume. Do NOT call ordinary
  OHLCV volume, a volume histogram, or the bot's OHLCV pressure calculation
  'true order flow'.
- Look for visible clues such as buy/sell imbalance, stacked imbalance,
  absorption, exhaustion, initiative buying/selling, trapped traders, delta
  divergence, POC migration, value-area acceptance/rejection, and liquidity
  concentration — ONLY when the chart actually displays enough information.
- For DOM/order-book screenshots, describe visible resting bids/asks and
  liquidity walls carefully, but do not claim they will remain or be executed.
- If the screenshot does not contain the relevant order-flow fields, say
  'order-flow data not visible' rather than estimating it from candles.
- Never infer exact bid/ask volume, delta or CVD from a normal candlestick chart.

Return a concise but useful breakdown with these sections:

📷 SCREENSHOT READ
- Symbol/instrument (if visible)
- Timeframe (if visible)
- Visible price/quote (if visible)
- Indicators/markings visible

🌹 ROSITA — VISUAL STRUCTURE
- Trend/bias visible on the chart
- Market structure / BOS / CHoCH if visibly supported
- Key visible levels

💜 MAGNA — VISUAL SETUP
- Liquidity sweep if visible
- FVG/imbalance if visible
- Order-block candidate if visibly supported
- OTE/fib information only if visible

🛡️ HARLEEN — RISK CHECK
- Visible volatility/context
- Conflicts or missing information
- Whether the screenshot alone is sufficient for a setup

VERDICT
- Valid visual setup / watchlist only / insufficient data

Important: this is screenshot-only analysis. Do not pretend the image provides
real-time market data, news, or true bid/ask order flow. If a quote or level is
blurry, cropped, or ambiguous, say so instead of guessing.
"""

async def analyze_screenshot(update, image_bytes, mime_type="image/jpeg"):
    """Analyze a Telegram chart screenshot with Groq's vision model."""
    if not client:
        await update.message.reply_text(
            "📷 Screenshot received, but the vision brain is unavailable. "
            "Add GROQ_API_KEY first 🫦 👀"
        )
        return

    if not image_bytes:
        await update.message.reply_text("I couldn't read that image. Please resend the screenshot.")
        return

    # Keep requests safely below Groq's documented image request limit.
    if len(image_bytes) > 18 * 1024 * 1024:
        await update.message.reply_text(
            "That screenshot is too large. Please send a smaller/compressed image (under 18 MB)."
        )
        return

    await update.message.chat.send_action("typing")
    caption = (update.message.caption or "").strip()
    user_prompt = (
        "Analyze this screenshot for a manual/educational XAU/USD-style chart review. "
        "First classify what kind of market screenshot it is (price chart, footprint/order-flow, "
        "volume profile, DOM/order book, CVD/delta, quotes, news/calendar, or mixed). "
        "If it is an order-flow/footprint chart, prioritize the actual bid/ask and delta information "
        "visible in the image and explain the strongest readable imbalances/absorption/POC/value-area clues. "
        "If it is a normal candlestick chart, do not manufacture order-flow numbers. "
        "Read visible chart data carefully and mark anything cropped, blurry, or ambiguous as unknown. "
        "If the screenshot is not a chart, explain what market information is actually visible.\n\n"
        f"User note: {caption or 'No additional note.'}"
    )

    encoded = base64.b64encode(image_bytes).decode("utf-8")
    data_url = f"data:{mime_type};base64,{encoded}"

    try:
        r = await asyncio.to_thread(
            client.chat.completions.create,
            model=VISION_MODEL,
            messages=[
                {"role": "system", "content": VISION_SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
            temperature=0.1,
            max_completion_tokens=900,
        )
        reply = r.choices[0].message.content.strip()
        await update.message.reply_text(
            reply + "\n\n📷 Screenshot-only analysis — live price/news/order-flow are not assumed.",
            reply_markup=MENU_KEYBOARD,
        )
    except Exception as e:
        logger.error("Vision analysis error: %s", e)
        await update.message.reply_text(
            "📷 I received the screenshot but couldn't analyze it right now. "
            f"Vision error: {e}"
        )

async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    try:
        if update.message.photo:
            photo = update.message.photo[-1]
            tg_file = await photo.get_file()
            buf = BytesIO()
            await tg_file.download_to_memory(out=buf)
            image_bytes = buf.getvalue()
            mime_type = "image/jpeg"
        elif update.message.document and (update.message.document.mime_type or "").startswith("image/"):
            tg_file = await update.message.document.get_file()
            buf = BytesIO()
            await tg_file.download_to_memory(out=buf)
            image_bytes = buf.getvalue()
            mime_type = update.message.document.mime_type or "image/jpeg"
        else:
            return

        await analyze_screenshot(update, image_bytes, mime_type)
    except Exception as e:
        logger.error("Telegram image download error: %s", e)
        await update.message.reply_text(
            "📷 I couldn't download that image. Please send the screenshot again."
        )

# ============================================================
# FORMAT OBJECTIVE RESULT
# ============================================================

def objective_text(a):
    m = a.get("magna", {})
    r = a.get("risk", {})
    h = a.get("harleen", {})
    ros = a.get("rosita", {})
    market = a.get("market", {})
    regime = market.get("regime", {})

    if not a.get("valid"):
        # Keep all three agent breakdowns available to the explanation layer,
        # even when the objective engine rejects the setup.
        magna_direction = m.get("direction")
        magna_sweep = m.get("sweep")
        magna_fvg = m.get("fvg")
        magna_ob = m.get("order_block")
        magna_ote = m.get("ote")

        return (
            "SWARM v22.0 OBJECTIVE SCAN\n"
            f"Signal ID: {a.get('signal_id', 'N/A')}\n"
            f"Price: {a.get('price', 'N/A')}\n\n"
            "ROSITA BREAKDOWN\n"
            f"4H bias: {ros.get('bias_4h')}\n"
            f"1H bias: {ros.get('bias_1h')}\n"
            f"Direction: {ros.get('direction')}\n"
            f"4H structure: {ros.get('structure_4h')}\n"
            f"1H structure: {ros.get('structure_1h')}\n"
            f"15M structure: {ros.get('structure_15m')}\n"
            f"5M structure: {ros.get('structure_5m')}\n"
            f"15M BOS: {ros.get('bos_15m')}\n"
            f"15M CHoCH: {ros.get('choch_15m')}\n\n"
            "MAGNA BREAKDOWN\n"
            f"Candidate direction: {magna_direction}\n"
            f"Liquidity sweep: {magna_sweep}\n"
            f"FVG: {magna_fvg}\n"
            f"Order block: {magna_ob}\n"
            f"OTE: {magna_ote}\n\n"
            "HARLEEN BREAKDOWN\n"
            f"Verdict: {h.get('verdict')}\n"
            f"Session: {h.get('session')}\n"
            f"News: {h.get('news')}\n"
            f"Veto reasons: {', '.join(h.get('veto_reasons', [])) or 'None'}\n\n"
            f"Regime: {regime.get('name')}\n"
            f"Objective score: {a.get('score', 0)}/100 ({a.get('grade')})\n"
            "NO VALID SETUP\n"
            "Reasons:\n"
            + "\n".join(f"- {x}" for x in a.get("reasons", []))
        )

    return (
        "SWARM v22.0 OBJECTIVE SCAN\n"
        f"Signal ID: {a['signal_id']}\n"
        f"Price: {a['price']}\n"
        f"Rosita 4H/1H: {ros.get('bias_4h')} / {ros.get('bias_1h')}\n"
        f"Rosita direction: {ros.get('direction')}\n"
        f"15M/5M structure: {ros.get('structure_15m')} / {ros.get('structure_5m')}\n"
        f"Harleen: {h.get('verdict')}\n"
        f"Session: {h.get('session')}\n"
        f"Regime: {regime.get('name')}\n"
        f"VWAP: {market.get('vwap')}\n"
        f"Premium/Discount: {market.get('premium_discount', {}).get('zone')}\n"
        f"Nearest S/R: {market.get('support_resistance', {}).get('nearest')}\n"
        f"Psychological level: {market.get('psychological_levels', {}).get('nearest_major')} "
        f"/ {market.get('psychological_levels', {}).get('nearest_half')}\n"
        f"Momentum: {market.get('momentum', {}).get('bias')}\n"
        f"Order-flow proxy: {market.get('order_flow_proxy', {}).get('bias')} "
        f"(imbalance {market.get('order_flow_proxy', {}).get('imbalance')})\n"
        f"Direction: {m.get('direction')}\n"
        f"Liquidity sweep: {m.get('sweep')}\n"
        f"FVG: {m.get('fvg')}\n"
        f"Order block: {m.get('order_block')}\n"
        f"OTE: {m.get('ote')}\n"
        f"ATR 5M: {r.get('atr_5m')}\n"
        f"Entry: {r.get('entry')}\n"
        f"SL: {r.get('sl')}\n"
        f"TP1-TP10: {r.get('tp')}\n"
        f"Risk per unit: {r.get('risk')}\n"
        f"Objective score: {a.get('score')}/100 ({a.get('grade')})\n"
        "Confluences:\n"
        + "\n".join(f"- {x}" for x in a.get("confluences", []))
    )

# ============================================================
# JOURNAL ANALYTICS
# ============================================================

def journal_stats():
    rows = load_journal()
    scans = [x for x in rows if x.get("event") == "SCAN"]
    resolved = [x for x in rows if x.get("outcome") in ("win", "loss") and x.get("r_result") is not None]

    valid = [x for x in scans if x.get("valid")]
    by_grade = {}
    for row in valid:
        g = row.get("grade", "UNKNOWN")
        by_grade[g] = by_grade.get(g, 0) + 1

    return {
        "total_scans": len(scans),
        "valid_setups": len(valid),
        "resolved": len(resolved),
        "grades": by_grade,
    }

def format_journal_stats():
    s = journal_stats()
    grades = ", ".join(f"{k}: {v}" for k, v in sorted(s["grades"].items())) or "none"
    return (
        "SWARM v22.0 JOURNAL\n"
        f"Scans recorded: {s['total_scans']}\n"
        f"Valid setups recorded: {s['valid_setups']}\n"
        f"Resolved trades: {s['resolved']}\n"
        f"Grades: {grades}\n\n"
        "The journal stores research data; it does not prove profitability."
    )

# ============================================================
# WALK-FORWARD RESEARCH
# ============================================================

def evaluate_fixed_r(candles, start, end, min_score=75, lookahead=30):
    """Evaluate V19-style objective logic on a historical slice."""
    if end <= start or end > len(candles):
        return []

    trades = []
    warmup = 70

    for i in range(max(start, warmup), min(end, len(candles) - lookahead)):
        hist = candles[:i + 1]
        price = hist[-1]["c"]

        bias = tf_bias(hist)
        s = structure_state(hist)
        sweep = liquidity_sweep(hist, lookback=min(24, len(hist) - 3))
        fib = fib_ote(hist, min(60, len(hist)))
        fvg = nearest_fvg(hist, "bullish" if bias == "bullish" else "bearish", price)
        ob = order_block_candidate(hist, "bullish" if bias == "bullish" else "bearish")
        regime = market_regime(hist)

        direction = None
        if bias == "bullish" and s["state"] == "bullish":
            direction = "long"
        elif bias == "bearish" and s["state"] == "bearish":
            direction = "short"

        if sweep and sweep["direction"] in ("long", "short"):
            # Sweep is confirmation/reversal evidence, not an unconditional
            # override of the higher-timeframe direction in the tester.
            if direction is None:
                direction = sweep["direction"]

        if not direction:
            continue

        wanted = "bullish" if direction == "long" else "bearish"
        score = 0
        if bias == wanted: score += 20
        if s["state"] == wanted: score += 20
        if s["bos"] == wanted or s["choch"] == wanted: score += 10
        if sweep and sweep["direction"] == direction: score += 20
        if fvg: score += 8
        if ob: score += 8
        if in_ote(price, fib, direction): score += 8
        if regime.get("name", "").startswith("trending"): score += 6

        if score < min_score:
            continue

        a = atr(hist, 14)
        risk = risk_engine(direction, price, s, hist, a)
        if not risk["sl"]:
            continue

        outcome = None
        r_value = None
        for c in candles[i + 1:i + 1 + lookahead]:
            if direction == "long":
                hit_sl = c["l"] <= risk["sl"]
                hit_tp = c["h"] >= risk["tp"][2]  # 2R
            else:
                hit_sl = c["h"] >= risk["sl"]
                hit_tp = c["l"] <= risk["tp"][2]

            # Conservative same-candle handling: SL is counted first if both
            # levels appear inside the same candle.
            if hit_sl:
                outcome, r_value = "loss", -1.0
                break
            if hit_tp:
                outcome, r_value = "win", 2.0
                break

        if outcome:
            trades.append({
                "index": i,
                "direction": direction,
                "score": score,
                "outcome": outcome,
                "r": r_value,
            })

    return trades

def summarize_trades(trades):
    if not trades:
        return {
            "trades": 0, "wins": 0, "losses": 0, "win_rate": 0,
            "net_r": 0, "profit_factor": 0, "max_drawdown_r": 0
        }

    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    wins = losses = 0
    gross_profit = gross_loss = 0.0

    for t in trades:
        r = t["r"]
        equity += r
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        if r > 0:
            wins += 1
            gross_profit += r
        else:
            losses += 1
            gross_loss += abs(r)

    return {
        "trades": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / len(trades) * 100, 2),
        "net_r": round(equity, 2),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss else 0,
        "max_drawdown_r": round(max_dd, 2),
    }

def walk_forward_backtest(candles, folds=5):
    """
    Sequential walk-forward evaluation. Each fold is an out-of-sample
    evaluation window; no future candles are used by the signal logic.
    """
    if not candles or len(candles) < 700:
        return {"error": "Need at least ~700 candles for a meaningful 5-fold test"}

    n = len(candles)
    step = n // folds
    fold_results = []

    for fold in range(folds):
        start = fold * step
        end = n if fold == folds - 1 else (fold + 1) * step
        # Give each fold the candles before its start as historical context.
        test_start = max(0, start)
        trades = evaluate_fixed_r(candles, test_start, end)
        fold_results.append({
            "fold": fold + 1,
            "start": candles[start]["t"],
            "end": candles[end - 1]["t"],
            **summarize_trades(trades),
        })

    all_trades = []
    for fr in fold_results:
        # Fold-level summaries are enough for the Telegram output; the
        # aggregate is recomputed from their net/win/loss counts.
        all_trades.extend([{"r": 2.0 if i < fr["wins"] else -1.0}
                           for i in range(fr["trades"])])

    return {
        "folds": fold_results,
        "aggregate": summarize_trades(all_trades),
    }


# ============================================================
# BACKTEST
# ============================================================

def backtest_engine(candles, warmup=60, lookahead=30, min_score=75):
    """Compatibility wrapper: V19's primary research mode is walk-forward."""
    if not candles or len(candles) < warmup + lookahead + 20:
        return {
            "trades": 0, "wins": 0, "losses": 0,
            "win_rate": 0, "net_r": 0, "profit_factor": 0,
            "max_drawdown_r": 0
        }
    trades = evaluate_fixed_r(
        candles,
        start=warmup,
        end=len(candles) - lookahead,
        min_score=min_score,
        lookahead=lookahead,
    )
    return summarize_trades(trades)


# ============================================================
# TELEGRAM HANDLERS
# ============================================================

async def handle_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    low = update.message.text.lower().strip()

    # Menu buttons are ordinary text prompts, so they work on every Telegram client.
    if low in ["🔎 analyze gold", "analyze gold"]:
        low = "analyze gold"
    elif low in ["🧠 full breakdown", "full breakdown", "breakdown"]:
        low = "analyze gold"
    elif low in ["🌹 rosita", "rosita"]:
        low = "rosita"
    elif low in ["💜 magna", "magna"]:
        low = "magna"
    elif low in ["🛡️ harleen", "harleen"]:
        low = "harleen"
    elif low in ["📰 news", "news"]:
        low = "news"
    elif low in ["📊 s/r", "s/r", "support resistance"]:
        low = "support"
    elif low in ["🌊 order flow", "order flow"]:
        low = "orderflow"
    elif low in ["📓 journal", "journal"]:
        low = "journal"
    elif low in ["📷 chart screenshot", "chart screenshot", "screenshot", "chart"]:
        low = "screenshot"
    elif low in ["🧪 backtest", "backtest"]:
        low = "backtest"

    if low in ["hi", "hello", "hey", "yo"]:
        await update.message.reply_text(
            "Hey Shay 🫦 👀 Swarm v22.0 online — "
            "Rosita + Harleen Quinzel + Magna + objective Python engine 💕"
        )
        return

    if low.startswith("remember "):
        cid = str(update.effective_chat.id)

        LONG_MEM[cid] = (
            LONG_MEM.get(cid, "") + " " + update.message.text[9:]
        ).strip()[-1000:]

        save_mem()

        await update.message.reply_text(
            "Got it Shay 🫦 👀 I'll remember 💕"
        )
        return

    if low in ["rosita", "magna", "harleen"]:
        await update.message.reply_text("Swarm scanning — building the requested breakdown…")
        result = analyze_market()
        ros = result.get("rosita", {})
        magna = result.get("magna", {})
        harleen = result.get("harleen", {})

        if low == "rosita":
            reply = (
                "🌹 ROSITA BREAKDOWN\n"
                f"4H bias: {ros.get('bias_4h')}\n"
                f"1H bias: {ros.get('bias_1h')}\n"
                f"Direction: {ros.get('direction')}\n"
                f"4H structure: {ros.get('structure_4h')}\n"
                f"1H structure: {ros.get('structure_1h')}\n"
                f"15M structure: {ros.get('structure_15m')}\n"
                f"5M structure: {ros.get('structure_5m')}\n"
                f"15M BOS: {ros.get('bos_15m')}\n"
                f"15M CHoCH: {ros.get('choch_15m')}"
            )
        elif low == "magna":
            reply = (
                "💜 MAGNA BREAKDOWN\n"
                f"Direction: {magna.get('direction')}\n"
                f"Liquidity sweep: {magna.get('sweep')}\n"
                f"FVG: {magna.get('fvg')}\n"
                f"Order block: {magna.get('order_block')}\n"
                f"OTE: {magna.get('ote')}\n"
                f"Score: {result.get('score')}/100 ({result.get('grade')})"
            )
        else:
            reply = (
                "🛡️ HARLEEN BREAKDOWN\n"
                f"Verdict: {harleen.get('verdict')}\n"
                f"Session: {harleen.get('session')}\n"
                f"News: {harleen.get('news')}\n"
                f"Veto reasons: {', '.join(harleen.get('veto_reasons', [])) or 'None'}\n"
                f"Overall valid: {result.get('valid')}"
            )

        await update.message.reply_text(reply, reply_markup=MENU_KEYBOARD)
        return

    if low == "screenshot":
        await update.message.reply_text(
            "📷 CHART SCREENSHOT GUIDE\n\n"
            "For the BEST full analysis, send these screenshots:\n\n"
            "1️⃣ 4H chart — full chart + price scale\n"
            "2️⃣ 1H chart — full chart + price scale\n"
            "3️⃣ 15M chart — full chart + price scale\n"
            "4️⃣ 5M chart — full chart + price scale\n\n"
            "OPTIONAL 📌\n"
            "5️⃣ Quotes panel — current bid/ask or live quote\n"
            "6️⃣ Indicators panel — if indicators aren't visible on the chart\n"
            "7️⃣ Economic calendar/news — if you want Harleen to assess visible events\n\n"
            "⚡ You do NOT need all 7. For a full Rosita + Magna + Harleen breakdown, "
            "start with 4H + 1H + 15M + 5M.\n\n"
            "📱 You can send the screenshots one after another. I’ll analyze what is "
            "actually visible and tell you if anything important is missing or unreadable.\n\n"
            "💡 Tip: Keep the price scale visible and avoid cropping out the candles.\n"
            "Add a caption if useful, e.g. 'XAU/USD 5M'.",
            reply_markup=MENU_KEYBOARD,
        )
        return

    if "news" in low:
        warning = get_news_warning()

        await update.message.reply_text(
            warning
            if warning
            else "No high-impact USD warning in the configured window — Harleen PASS 🫦 👀 💕"
        )
        return

    if low in ["signal", "scalp", "analyze gold", "gold", "xau"] or (
        "analyze" in low and "gold" in low
    ):
        await update.message.reply_text(
            "Swarm scanning Shay 🫦 👀 "
            "Rosita + Harleen Quinzel + Magna + Python engine..."
        )

        result = analyze_market()
        obj = objective_text(result)

        # Groq receives objective measurements, not permission to
        # invent the numerical trade.
        explanation = await ask_groq(
            "Analyze this OBJECTIVE PYTHON ENGINE result. "
            "Do not alter any numerical value.\n\n" + obj,
            update.effective_chat.id,
        )

        await update.message.reply_text(explanation)
        return

    if low in ["support", "resistance", "support resistance", "sr"]:
        a = analyze_market()
        sr = a.get("market", {}).get("support_resistance", {})
        psy = a.get("market", {}).get("psychological_levels", {})
        await update.message.reply_text(
            "SWARM v22.0 S/R + PSYCHOLOGICAL LEVELS\n"
            f"Price: {a.get('price')}\n"
            f"Nearest 15M S/R: {sr.get('nearest')}\n"
            f"Psychological major: {psy.get('nearest_major')}\n"
            f"Psychological half-level: {psy.get('nearest_half')}\n\n"
            "S/R strength is based on repeated historical swing reactions."
        )
        return

    if low in ["orderflow", "flow", "order flow"]:
        a = analyze_market()
        flow = a.get("market", {}).get("order_flow_proxy", {})
        await update.message.reply_text(
            "SWARM v22.0 ORDER-FLOW PROXY\n"
            f"Signal ID: {a.get('signal_id')}\n"
            f"Bias: {flow.get('bias')}\n"
            f"Imbalance: {flow.get('imbalance')}\n"
            f"CVD proxy: {flow.get('cvd_proxy')}\n"
            f"Displacement: {flow.get('displacement')}\n"
            f"Absorption: {flow.get('absorption')}\n\n"
            "Important: Twelve Data OHLCV is not true bid/ask order flow. "
            "This is a candle/volume pressure proxy."
        )
        return

    if low in ["journal", "stats", "journal stats"]:
        await update.message.reply_text(format_journal_stats())
        return

    if low in ["backtest", "test", "backtest gold", "walkforward", "walk-forward"]:
        await update.message.reply_text(
            "Running research backtest on the available XAU/USD dataset Shay 🫦 👀..."
        )

        candles = get_candles("XAU/USD", "15min", 2000)

        if not candles:
            await update.message.reply_text(
                "Backtest unavailable — Twelve Data did not return enough candles."
            )
            return

        result = backtest_engine(candles)

        await update.message.reply_text(
            "SWARM v22.0 RESEARCH BACKTEST\n"
            f"Trades: {result['trades']}\n"
            f"Wins: {result['wins']}\n"
            f"Losses: {result['losses']}\n"
            f"Win rate: {result['win_rate']}%\n"
            f"Net R: {result['net_r']}\n"
            f"Profit factor: {result['profit_factor']}\n"
            f"Max drawdown: {result['max_drawdown_r']} R\n\n"
            "This is historical research only; it excludes live spread/slippage "
            "and is not a guarantee of future performance."
        )
        return

    # General questions can still use Groq, with current live price.
    p = get_live_price()
    price_ctx = f"\n[Live XAU/USD: {p:.2f}]" if p else ""

    reply = await ask_groq(
        update.message.text + price_ctx,
        update.effective_chat.id,
    )

    await update.message.reply_text(reply)

MENU_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["🔎 Analyze Gold", "🧠 Full Breakdown"],
        ["🌹 Rosita", "💜 Magna", "🛡️ Harleen"],
        ["📰 News", "📊 S/R", "🌊 Order Flow"],
        ["📷 Chart Screenshot", "📓 Journal", "🧪 Backtest"],
    ],
    resize_keyboard=True,
    is_persistent=True,
)


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Rosita + Harleen Quinzel + Magna online 🫦 👀 💕\n"
        "Objective Python engine active.\n\n"
        "Choose an option below, or use /menu anytime.\n"
        "Manual/educational mode only.",
        reply_markup=MENU_KEYBOARD,
    )


async def menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 SWARM MENU\n\n"
        "🔎 Analyze Gold — full objective scan\n"
        "🧠 Full Breakdown — Rosita + Magna + Harleen\n"
        "🌹 Rosita — trend/structure breakdown\n"
        "💜 Magna — setup/confluence breakdown\n"
        "🛡️ Harleen — veto/news/session decision\n"
        "📰 News — high-impact USD check\n"
        "📊 S/R — support/resistance levels\n"
        "🌊 Order Flow — OHLCV pressure proxy\n"
        "📓 Journal — scan statistics\n"
        "📷 Chart Screenshot — send a chart/quote screenshot for visual analysis\n"
        "🧪 Backtest — historical research",
        reply_markup=MENU_KEYBOARD,
    )

# ============================================================
# AUTO SIGNAL
# ============================================================

async def auto_signal_loop(app):
    await asyncio.sleep(10)

    while True:
        try:
            if BOSS_CHAT_ID.strip():
                # UTC schedule.
                hr = datetime.now(timezone.utc).hour

                if hr >= 21 or hr < 5:
                    await asyncio.sleep(300)
                    continue

                # analyze_market() already fetches the news veto in parallel
                # with market data. Do not call it a second time here.
                result = analyze_market()

                if result.get("valid"):
                    obj = objective_text(result)

                    sig = await ask_groq(
                        "Explain this objective result exactly. "
                        "Do not change Entry, SL or TP.\n\n" + obj,
                        BOSS_CHAT_ID,
                    )

                    await app.bot.send_message(
                        chat_id=int(BOSS_CHAT_ID),
                        text=(
                            sig
                            + "\n\n"
                            "Manual/educational analysis only 🫦 👀 💕\n"
        "Python is the numerical source of truth."
                        ),
                    )

        except Exception as e:
            logger.error("Auto loop error: %s", e)

        await asyncio.sleep(300)

async def post_init(app):
    await app.bot.set_my_commands([
        BotCommand("start", "Open the Swarm menu"),
        BotCommand("menu", "Show analysis menu"),
        BotCommand("analyze", "Analyze gold"),
        BotCommand("news", "Check USD news"),
        BotCommand("orderflow", "Order-flow proxy"),
        BotCommand("support", "Support and resistance"),
        BotCommand("journal", "Journal statistics"),
        BotCommand("screenshot", "Analyze a chart screenshot"),
        BotCommand("backtest", "Historical research"),
    ])
    asyncio.create_task(auto_signal_loop(app))

# ============================================================
# MAIN
# ============================================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("analyze", handle_msg))
    app.add_handler(CommandHandler("news", handle_msg))
    app.add_handler(CommandHandler("orderflow", handle_msg))
    app.add_handler(CommandHandler("support", handle_msg))
    app.add_handler(CommandHandler("journal", handle_msg))
    app.add_handler(CommandHandler("screenshot", handle_msg))
    app.add_handler(CommandHandler("backtest", handle_msg))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.IMAGE, handle_photo))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg)
    )

    print(
        "Swarm v22.0 Rosita + Harleen Quinzel + Magna "
        "objective engine starting..."
    )

    app.run_polling()

if __name__ == "__main__":
    main()
