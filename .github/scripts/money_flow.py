#!/usr/bin/env python3
"""
Money Flow Dashboard — GitHub Gist Updater
Updates hourly via GitHub Actions.

Sources:
  - Yahoo Finance: VIX, VIX3M, sector ETFs, HYG
  - FRED: M2 money supply, HY OAS spread (needs API key)
  - SEC EDGAR: Form 4 (insider buys), Form D (private placements)
  - Polymarket: prediction market probabilities

Gist layout:
  Lines 1-5: Dense dashboard (visible in pinned preview)
  Lines 7-10: Explanations (visible when clicked in)
"""

import json
import os
import re
import subprocess
import sys
import unicodedata
import urllib.request
from datetime import datetime, timedelta, timezone

# === CONFIG ===
GIST_ID = os.environ.get("MONEY_GIST_ID", "")
FRED_KEY = os.environ.get("FRED_API_KEY", "")
FILENAME = "\u2800"
PT = timezone(timedelta(hours=-8))

WATCHED = {
    "NVDA": "0001045810",
    "AMD":  "0000002488",
    "TSM":  "0001046179",
    "INTC": "0000050863",
    "MSFT": "0000789019",
}

SECTORS = [
    ("SOXX", "Semi"), ("XLK", "Tech"), ("XLE", "Enrg"),
    ("XLF", "Fin"), ("XLV", "Hlth"),
]

POLY_KEYWORDS = ["fed", "tariff", "rate", "recession", "economy",
                  "inflation", "interest rate", "ipo",
                  "gdp", "debt", "treasury", "tax", "shutdown",
                  "ai model", "ai ", "largest company", "stock",
                  "s&p", "earnings", "nvidia", "openai", "anthropic",
                  "google", "apple", "microsoft", "semiconductor",
                  "chip", "climate", "temperature"]
POLY_SKIP = ["nba", "nfl", "premier league", "champions league", "fifa",
             "world cup", "la liga", "mvp", "deport", "dutch", "bitcoin",
             "crypto", "nhl", "mlb", "serie a", "stranger things",
             "gta", "oscars", "youtube", "views", "pikachu",
             "olympics", "ice hockey", "nobel", "f1 ", "bad bunny",
             "opensea", "fdv", "measles", "australian open",
             "super bowl", "logan paul", "war", "strike", "iran",
             "ukraine", "ceasefire", "greenland", "khamenei",
             "invade", "taiwan", "venezuela", "regime", "leader",
             "putin", "xi jinping", "aliens", "moon land",
             "ligue", "bundesliga", "europa", "nuggets", "mavericks",
             "bucks", "sentinels", "lol:", "paris mayor", "senate",
             "prime minister", "presidential", "silver", "gold",
             "polymarket", "puffpaw", "backpack", "metamask",
             "edgex", "hottest year", "weather"]


def fetch(url, headers=None, timeout=15):
    h = headers or {"User-Agent": "Mozilla/5.0"}
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def yahoo(sym, rng="12d"):
    d = fetch(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d")
    r = d["chart"]["result"][0]
    price = r["meta"]["regularMarketPrice"]
    closes = [c for c in r["indicators"]["quote"][0]["close"] if c is not None]
    return price, closes


# Consistent 3-column layout for all lines
# Col1: 14 chars, Col2: 13 chars, Col3: rest
# Total: emoji(2) + space(1) + 14 + "│ "(2) + 13 + "│ "(2) + ~8 = ~42
W1, W2 = 14, 13

def fmt3(emoji, c1, c2, c3):
    return f"{emoji} {c1:<{W1}}│ {c2:<{W2}}│ {c3}"

def fmt2(emoji, c1, c2):
    return f"{emoji} {c1:<{W1 + 2 + W2}}│ {c2}"


def safe_5d(closes):
    """5-day return, handling short arrays."""
    if len(closes) < 6:
        return (closes[-1] - closes[0]) / closes[0] * 100
    return (closes[-1] - closes[-6]) / closes[-6] * 100


# ────────────────────────────────────────
# LINE 1: REGIME
# ────────────────────────────────────────
def build_line1():
    info = {}
    parts = []
    expl = []

    # VIX + term structure
    vix, struct = None, "?"
    try:
        vix, _ = yahoo("^VIX")
        vix3m, _ = yahoo("^VIX3M")
        ratio = vix / vix3m
        if ratio < 0.97:
            struct = "cntgo"
            expl.append("vol calm (contango)")
        elif ratio > 1.03:
            struct = "bkwrd"
            expl.append("vol stressed (backwardation)")
        else:
            struct = "flat"
            expl.append("vol neutral")
        info["vix"] = vix
        info["struct"] = struct
    except Exception:
        pass

    # Credit proxy — HYG 5d return
    try:
        _, hc = yahoo("HYG")
        hyg_ret = safe_5d(hc)
        if hyg_ret > 0.3:
            credit = "HY↑"
            expl.append("credit tightening")
        elif hyg_ret < -0.5:
            credit = "HY↓"
            expl.append("credit widening")
        else:
            credit = "HY→"
            expl.append("credit stable")
        info["credit"] = credit
    except Exception:
        credit = None

    # HY OAS from FRED (more precise)
    if FRED_KEY:
        try:
            d = fetch(f"https://api.stlouisfed.org/fred/series/observations"
                      f"?series_id=BAMLH0A0HYM2&api_key={FRED_KEY}"
                      f"&file_type=json&sort_order=desc&limit=1")
            spread = float(d["observations"][0]["value"])
            credit = f"HY{int(spread * 100)}"
            status = "healthy" if spread < 4.0 else "elevated" if spread < 5.5 else "stressed"
            expl[-1] = f"credit {status} ({spread:.1f}%)"
            info["credit"] = credit
            info["hy_spread"] = spread
        except Exception:
            pass

    # M2 from FRED
    if FRED_KEY:
        try:
            d = fetch(f"https://api.stlouisfed.org/fred/series/observations"
                      f"?series_id=M2SL&api_key={FRED_KEY}"
                      f"&file_type=json&sort_order=desc&limit=2")
            cur = float(d["observations"][0]["value"])
            prev = float(d["observations"][1]["value"])
            g = (cur - prev) / prev * 100
            arrow = "▲" if g > 0 else "▼"
            m2_str = f"M2{arrow}{abs(g):.1f}%"
            info["m2"] = m2_str
            expl.append("liquidity " + ("expanding" if g > 0 else "contracting"))
        except Exception:
            pass

    # 10Y yield
    try:
        tny, _ = yahoo("^TNX")
        info["10y"] = tny
    except Exception:
        tny = None

    # Regime color
    if vix is not None:
        if vix < 15 and struct == "cntgo":
            dot = "🟢"
        elif vix > 25 or struct == "bkwrd":
            dot = "🔴"
        else:
            dot = "🟡"
    else:
        dot = "⚪"

    # Build line with consistent column layout
    c1 = f"VIX {vix:.0f} {struct}" if vix else "VIX ?"
    c2parts = []
    if credit:
        c2parts.append(credit)
    if "m2" in info:
        c2parts.append(info["m2"])
    c2 = " ".join(c2parts)
    c3 = f"10Y {tny:.1f}" if tny else ""
    line = fmt3(dot, c1, c2, c3)

    # Rich explanation: thresholds + context
    ex = []
    if vix is not None and "vix3m" not in info:
        # Store ratio for explanation
        pass
    if struct == "cntgo":
        ex.append("VIX<VIX3M = no crash expected")
    elif struct == "bkwrd":
        ex.append("VIX>VIX3M = market bracing")
    hy = info.get("hy_spread")
    if hy:
        ex.append(f"OAS {hy:.1f}% ({'<4=ok' if hy<4 else '>5=danger' if hy>5 else 'watch>5'})")
    elif credit:
        ex.append(f"HYG 5d {'rising=ok' if '↑' in credit else 'falling=stress' if '↓' in credit else 'flat'}")
    if "m2" in info:
        ex.append("M2 tide " + ("rising" if "▲" in info["m2"] else "falling"))
    else:
        ex.append("M2 needs FRED key")
    explain = "🔮 " + ", ".join(ex)

    return line, explain, info


# ────────────────────────────────────────
# LINE 2: SECTOR FLOWS
# ────────────────────────────────────────
def build_line2():
    try:
        _, sc = yahoo("SPY")
        spy_5d = safe_5d(sc)
    except Exception:
        return "$▶ flow unavail", "💸 market data unavailable", {}

    flows = []
    for sym, lbl in SECTORS:
        try:
            _, c = yahoo(sym)
            r = safe_5d(c)
            flows.append((lbl, r - spy_5d, r))
        except Exception:
            pass

    flows.sort(key=lambda x: x[1], reverse=True)

    # Show top 2 inflows + strongest outflow for contrast
    inflows = [(l, r) for l, r, _ in flows if r > 0.5]
    outflows = [(l, r) for l, r, _ in flows if r < -0.5]
    neutral = [(l, r) for l, r, _ in flows if -0.5 <= r <= 0.5]

    show = inflows[:2]
    if outflows:
        show.append(outflows[-1])  # worst outflow
    elif neutral:
        show.append(neutral[0])
    if len(show) < 3 and inflows[2:]:
        show.append(inflows[2])

    parts = []
    for lbl, rel in show:
        bars = min(int(abs(rel) * 1.5), 5)
        b = "▓" * bars + "░" * max(0, 5 - bars)
        if rel > 0.5:
            parts.append(f"▶{lbl}{b}")
        elif rel < -0.5:
            parts.append(f"◁{lbl}{b}")
        else:
            parts.append(f"→{lbl}{b}")

    # Use consistent 3-column layout
    while len(parts) < 3:
        parts.append("—")
    line = fmt3("💸", parts[0], parts[1], parts[2])

    # Rich explanation: actual percentages + context
    all_flow_strs = []
    for lbl, rel, abs_r in flows:
        arrow = "▲" if rel > 0.5 else "▼" if rel < -0.5 else "→"
        all_flow_strs.append(f"{lbl}{arrow}{rel:+.1f}%")
    explain = "💸 " + " ".join(all_flow_strs) + " (5d vs SPY)"

    return line, explain, {"flows": flows}


# ────────────────────────────────────────
# LINE 3: SEC EDGAR FILINGS
# ────────────────────────────────────────
def build_line3():
    edgar_h = {"User-Agent": "MoneyFlowDashboard contact@example.com"}
    insider_parts = []
    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    # Form 4: insider filings for watched tickers
    for ticker, cik in list(WATCHED.items())[:4]:
        try:
            d = fetch(f"https://data.sec.gov/submissions/CIK{cik}.json", edgar_h)
            recent = d["filings"]["recent"]
            count = sum(
                1 for i in range(min(30, len(recent["form"])))
                if recent["form"][i] == "4" and recent["filingDate"][i] >= cutoff
            )
            if count > 0:
                insider_parts.append(f"{ticker}:{count}")
        except Exception:
            pass

    insider_str = " ".join(insider_parts) if insider_parts else "quiet"

    # Form D: recent private placements
    form_d_count = 0
    form_d_total = 0
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        # Tech/AI Form D filings
        q = urllib.parse.quote('"technology" OR "software" OR "artificial intelligence" OR "machine learning"')
        url = (f"https://efts.sec.gov/LATEST/search-index?q={q}"
               f"&forms=D&dateRange=custom&startdt={week_ago}&enddt={today}&from=0&size=1")
        d = fetch(url, edgar_h)
        form_d_count = d["hits"]["total"]["value"]
        # Total Form D filings
        url2 = (f"https://efts.sec.gov/LATEST/search-index?"
                f"forms=D&dateRange=custom&startdt={week_ago}&enddt={today}&from=0&size=1")
        d2 = fetch(url2, edgar_h)
        form_d_total = d2["hits"]["total"]["value"]
    except Exception:
        pass

    c1 = f"insdr {insider_str}"
    c2 = f"formD {form_d_count} AI"
    c3 = f"{form_d_total} total wk"
    line = fmt3("📋", c1, c2, c3)

    # Rich explanation
    ex = []
    if insider_parts:
        ex.append(f"{', '.join(insider_parts)} insider filings (7d)")
    else:
        ex.append("no insider activity in watched tickers")
    ex.append(f"{form_d_count} tech/AI of {form_d_total} total Form D raises this wk")
    explain = "📋 " + " │ ".join(ex)

    return line, explain, {}


# ────────────────────────────────────────
# LINE 4: POLYMARKET
# ────────────────────────────────────────
def build_line4():
    markets = []
    today = datetime.now().strftime("%Y-%m-%d")

    try:
        url = ("https://gamma-api.polymarket.com/events"
               "?limit=200&active=true&closed=false&order=volume&ascending=false")
        events = fetch(url)
    except Exception:
        events = []

    for e in events:
        try:
            title_lower = e.get("title", "").lower()
            desc_lower = e.get("description", "").lower()
            search_text = title_lower + " " + desc_lower

            # Skip non-relevant events
            if any(s in title_lower for s in POLY_SKIP):
                continue
            if not any(k in search_text for k in POLY_KEYWORDS):
                continue

            event_title = e.get("title", "")
            event_markets = e.get("markets", [])
            if not event_markets:
                continue

            # Use first market (primary) for the event
            m = event_markets[0]

            # Skip expired events
            end_date = m.get("endDate", "")
            if end_date and end_date[:10] < today:
                continue

            prices = m.get("outcomePrices", "[]")
            if isinstance(prices, str):
                p = json.loads(prices)
            else:
                p = prices

            if not p or not p[0]:
                continue

            prob = float(p[0]) * 100

            # Skip near-resolved events (not interesting)
            if prob < 10 or prob > 85:
                continue

            # Build short label — pattern match known events first
            raw = event_title.split("?")[0].split("...")[0].strip()
            rl = raw.lower()
            if ("fed" in rl or "fomc" in rl) and ("rate" in rl or "cut" in rl or "decrease" in rl or "interest" in rl):
                short = "FedCut"
            elif "fed chair" in rl or ("nominate" in rl and "fed" in rl):
                short = "FedChr"
            elif "recession" in rl:
                short = "Recsn"
            elif "tariff" in rl and "supreme" in rl:
                short = "SCTarf"
            elif "tariff" in rl and "revenue" in rl:
                short = "TarRev"
            elif "tariff" in rl:
                short = "Tarif"
            elif "inflation" in rl:
                short = "Infln"
            elif "ai model" in rl or "best ai" in rl:
                short = "BestAI"
            elif "largest company" in rl:
                short = "BigCo"
            elif "ipo" in rl:
                short = "IPOs"
            elif "shutdown" in rl:
                short = "Shtdwn"
            elif "tax" in rl:
                short = "Tax"
            elif "midterm" in rl:
                short = "Midtrm"
            elif "gdp" in rl:
                short = "GDP"
            elif "s&p" in rl or "sp500" in rl:
                short = "SP500"
            else:
                for rm in ["Will ", "the ", "Trump ", "United States ",
                            "How many ", "What will ", "Who will "]:
                    raw = raw.replace(rm, "")
                short = raw.replace("  ", " ").strip()
                if len(short) > 8:
                    words = short[:9].rsplit(" ", 1)
                    short = words[0] if len(words) > 1 else short[:7]
            full_q = m.get("question", event_title)
            markets.append({"short": f"{short} {prob:.0f}%",
                            "full": full_q, "prob": prob})

            if len(markets) >= 3:
                break
        except Exception:
            continue

    if markets:
        while len(markets) < 3:
            markets.append({"short": "—", "full": "", "prob": 0})
        line = fmt3("⚖", markets[0]["short"], markets[1]["short"], markets[2]["short"])
    else:
        line = fmt2("⚖", "polymarket unavail", "—")

    # Rich explanation: fuller question text + probabilities
    if markets:
        def trim_q(q):
            q = q.split("?")[0].strip()
            for rm in ["Will ", "the ", "Trump ", "United States "]:
                q = q.replace(rm, "")
            return q[:40]
        ex = [f'{trim_q(m["full"])}: {m["prob"]:.0f}%' for m in markets[:3]]
        explain = "⚖ " + " │ ".join(ex)
    else:
        explain = "⚖ prediction markets unavailable"

    return line, explain, {"markets": markets}


# ────────────────────────────────────────
# LINE 5: SIGNAL SYNTHESIS
# ────────────────────────────────────────
def build_line5(info):
    score = 0
    reasons = []

    # VIX
    vix = info.get("vix", 20)
    if vix < 15:
        score += 2
    elif vix < 20:
        score += 1
    elif vix > 30:
        score -= 2
    elif vix > 25:
        score -= 1

    # Term structure
    struct = info.get("struct", "?")
    if struct == "cntgo":
        score += 1
    elif struct == "bkwrd":
        score -= 2

    # M2
    m2 = info.get("m2", "")
    if "▲" in m2:
        score += 1
        reasons.append("liq▲")
    elif "▼" in m2:
        score -= 1
        reasons.append("liq▼")

    # Credit
    credit = info.get("credit", "")
    if "↑" in credit:
        score += 1
    elif "↓" in credit:
        score -= 1
        reasons.append("credit↓")

    # HY spread (FRED)
    hy = info.get("hy_spread")
    if hy is not None:
        if hy < 3.5:
            score += 1
        elif hy > 5.5:
            score -= 2
            reasons.append("HYstress")

    # Top sector flow
    flows = info.get("flows", [])
    if flows:
        top_lbl, top_rel, _ = flows[0]
        if top_rel > 2:
            reasons.append(f"{top_lbl.lower()}")
        # Check if user's sectors (Semi) are in top flows
        for lbl, rel, _ in flows:
            if lbl == "Semi" and rel > 1:
                reasons.append("semi▲")
                score += 1
                break

    # Signal text
    if score >= 4:
        signal = "full risk on"
    elif score >= 2:
        signal = "lean long"
    elif score >= 0:
        signal = "selective"
    elif score >= -2:
        signal = "hedge + reduce"
    else:
        signal = "raise cash"

    # Add structural reasons too
    if struct == "cntgo" and "liq▲" not in reasons:
        reasons.append("cntgo")
    if info.get("credit") and "↑" in info.get("credit", ""):
        reasons.append("HY ok")

    reason_str = " ".join(reasons[:4]) if reasons else "mixed"
    line = fmt2("💡", reason_str, signal)

    # Rich explanation: score breakdown
    breakdown = []
    if info.get("vix"):
        v = info["vix"]
        vs = 2 if v < 15 else 1 if v < 20 else -1 if v > 25 else 0
        if vs != 0:
            breakdown.append(f"vix{vs:+d}")
    if struct == "cntgo":
        breakdown.append("cntgo+1")
    elif struct == "bkwrd":
        breakdown.append("bkwrd-2")
    if "▲" in m2:
        breakdown.append("M2+1")
    if flows:
        for lbl, rel, _ in flows:
            if lbl == "Semi" and rel > 1:
                breakdown.append("semi+1")
                break
    explain = f"💡 score {score:+d}: {' '.join(breakdown)}" if breakdown else f"💡 score {score:+d}"

    return line, explain


# ────────────────────────────────────────
# AGENT: ITERATIVE PROMPT REFINEMENT
# ────────────────────────────────────────
AGENT_MODEL = "gpt-5.2"

SYSTEM_PROMPT = """\
You format financial market data into a pinned GitHub gist dashboard.

HARD CONSTRAINTS (any violation = rejected):
- Exactly 5 lines for the dashboard (before the blank line)
- Each line MUST be ≤43 characters VISUAL width but AIM for 39-43 chars
- MAXIMIZE DENSITY: use all available space. Short lines waste precious space.
- Emoji = 2 chars visual width. │ = 1 char. All other chars = 1.
- ZWJ emoji sequences (e.g. 😮‍💨) = 2 chars total visual width.
- Each line starts with a specific emoji:
  Line 1: 🟢 or 🟡 or 🔴 (regime dot — based on VIX level)
  Line 2: 💸 (sector flows — show relative performance)
  Line 3: 📋 (SEC filings — insider trades + Form D counts)
  Line 4: ⚖ (Polymarket predictions — show probabilities)
  Line 5: 💡 (signal synthesis — your sharp take)
- Use │ as column separator (keeps monospace alignment)
- After the 5 dashboard lines: one blank line, then 4-5 explanation lines
- Explanation lines unpack the dashboard data for someone who clicks in
- Do NOT add a timestamp — it gets appended automatically

DATA ACCURACY (critical):
- Use EXACT numbers from the provided data. Never invent or round aggressively.
- Line 3 must include actual insider filing counts and Form D numbers from the data.
- Line 4 must use the actual Polymarket short labels and probabilities.
- If data says "AMD:2" for insider filings, show "AMD:2" — don't drop it.

STYLE:
- Be sharp and specific in Line 5 (synthesis). Not "markets mixed" but "semi leading, credit calm = lean into tech"
- Explanation lines should tell the story: connect the dots between VIX, flows, filings, and predictions
- Use abbreviations that fit: cntgo, bkwrd, liq, HY, 10Y, insdr, formD
- The explanation section is where you add real insight — what does this combination of signals mean?

OUTPUT: Only the gist content (5 dashboard lines + blank + explanations). Nothing else.\
"""


def visual_width(s):
    """Calculate visual width: emoji=2, box-drawing=1, others=1."""
    width = 0
    i = 0
    chars = list(s)
    n = len(chars)
    while i < n:
        cp = ord(chars[i])
        # Skip variation selectors and ZWJ (they don't add width)
        if 0xFE00 <= cp <= 0xFE0F or cp == 0x200D:
            i += 1
            continue
        # Emoji: check East Asian Width + common emoji ranges
        cat = unicodedata.category(chars[i])
        eaw = unicodedata.east_asian_width(chars[i])
        if eaw in ('W', 'F'):
            width += 2
        elif cp > 0x1F000:
            width += 2
        elif cat == 'So' and cp > 0x2600:
            width += 2
        else:
            width += 1
        i += 1
    return width


def validate_gist_output(output):
    """Validate gist formatting constraints. Returns list of errors (empty = valid)."""
    errors = []
    lines = output.split("\n")

    # Find dashboard lines (before first blank line)
    dashboard = []
    blank_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "":
            blank_idx = i
            break
        dashboard.append(line)

    if len(dashboard) != 5:
        errors.append(f"Expected 5 dashboard lines, got {len(dashboard)}")

    for i, line in enumerate(dashboard):
        w = visual_width(line)
        if w > 43:
            errors.append(f"Line {i+1} is {w} chars wide (max 43): '{line}'")
        elif w < 35:
            errors.append(f"Line {i+1} is only {w} chars wide (min 35). Fill the space with more data or insight.")

    # Check required emojis on correct lines
    expected = {0: ["🟢", "🟡", "🔴"], 1: ["💸"], 2: ["📋"], 3: ["⚖"], 4: ["💡"]}
    for idx, emojis in expected.items():
        if idx < len(dashboard):
            if not any(dashboard[idx].startswith(e) for e in emojis):
                errors.append(f"Line {idx+1} must start with one of {emojis}")

    if blank_idx is None:
        errors.append("Missing blank line between dashboard and explanations")

    return errors


def agent_refine(raw_lines, raw_explains, info):
    """Use GPT-5.2 to iteratively refine gist formatting."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
    except ImportError:
        print("⚠ openai SDK not installed, using deterministic output")
        return None

    # Build data context for the model
    data_context = json.dumps({
        "vix": info.get("vix"),
        "term_structure": info.get("struct"),
        "credit": info.get("credit"),
        "hy_spread": info.get("hy_spread"),
        "m2": info.get("m2"),
        "10y": info.get("10y"),
        "flows": [(l, f"{r:+.1f}%") for l, r, _ in info.get("flows", [])],
        "markets": [{"q": m.get("full", ""), "prob": m.get("prob", 0)}
                    for m in info.get("markets", [])],
    }, indent=2)

    deterministic = "\n".join(raw_lines) + "\n\n" + "\n".join(raw_explains)

    user_prompt = f"""Raw market data:
{data_context}

Current deterministic output (use as reference for data accuracy):
{deterministic}

Rewrite this dashboard. Rules:
1. ALL numbers must come from the raw data or deterministic output — never invent.
2. Lines 1-4: reformat for clarity/density but keep all key data points.
3. Line 5: write a sharp, specific synthesis — connect the dots between signals.
4. Explanations: tell the story. Why do these signals matter together?
5. Every line must be ≤43 visual chars (emoji=2, │=1, all else=1)."""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    for attempt in range(5):
        try:
            resp = client.chat.completions.create(
                model=AGENT_MODEL,
                messages=messages,
                temperature=0.7,
                max_completion_tokens=600,
            )
            output = resp.choices[0].message.content.strip()
            # Strip markdown code fences if the model wraps output
            if output.startswith("```"):
                output = "\n".join(output.split("\n")[1:])
            if output.endswith("```"):
                output = "\n".join(output.split("\n")[:-1])
            output = output.strip()

            errors = validate_gist_output(output)
            if not errors:
                print(f"✓ Agent produced valid output on attempt {attempt + 1}")
                return output

            # Feed errors back for refinement
            error_msg = "\n".join(errors)
            print(f"  Agent attempt {attempt + 1}: {len(errors)} error(s)")
            messages.append({"role": "assistant", "content": output})
            messages.append({"role": "user", "content": (
                f"Formatting errors found:\n{error_msg}\n\n"
                "Fix these errors. Each dashboard line must be ≤43 visual chars "
                "(emoji=2, │=1, others=1). Output ONLY the corrected gist content."
            )})

        except Exception as e:
            print(f"  Agent attempt {attempt + 1} error: {e}")
            break

    print("⚠ Agent failed after 5 attempts, using deterministic output")
    return None


# ────────────────────────────────────────
# MAIN
# ────────────────────────────────────────
def update_gist(content):
    if not GIST_ID:
        print("⚠ No MONEY_GIST_ID set")
        return False

    for attempt in range(3):
        try:
            subprocess.run(
                ["gh", "api", "--method", "PATCH", f"/gists/{GIST_ID}",
                 "-f", f"files[{FILENAME}][content]={content}"],
                check=True, capture_output=True
            )
            return True
        except subprocess.CalledProcessError:
            if attempt < 2:
                import time
                time.sleep(2)
    return False


def main():
    lines = []
    explains = []
    info = {}

    builders = [build_line1, build_line2, build_line3, build_line4]
    for builder in builders:
        try:
            line, explain, data = builder()
            lines.append(line)
            explains.append(explain)
            info.update(data)
        except Exception as e:
            lines.append("⚠ error")
            explains.append(f"⚠ {builder.__name__}: {e}")

    # Signal line (returns line + explain)
    try:
        sig_line, sig_explain = build_line5(info)
        lines.append(sig_line)
        explains.append(sig_explain)
    except Exception as e:
        lines.append("💡 insufficient data")
        explains.append(f"💡 signal error: {e}")

    # Try agent refinement, fall back to deterministic
    agent_output = agent_refine(lines, explains, info)

    if agent_output:
        content = agent_output
        source = "agent"
    else:
        content = "\n".join(lines) + "\n\n" + "\n".join(explains)
        source = "deterministic"

    # Timestamp
    now = datetime.now(PT)
    content += f"\n\n⏱ {now.strftime('%b %d %I:%M%p PT')} [{source}]"

    print(content)

    if "--update" in sys.argv:
        ok = update_gist(content)
        print("---")
        print("✓ gist updated" if ok else "✗ gist update failed")
    else:
        print("---")
        print("(dry run — pass --update to push to gist)")


if __name__ == "__main__":
    main()
