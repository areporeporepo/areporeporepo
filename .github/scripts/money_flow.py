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

POLY_KEYWORDS = ["fed", "tariff", "rate cut", "recession", "war",
                  "iran", "china", "strike", "economy", "inflation",
                  "interest rate", "trade"]
POLY_SKIP = ["nba", "nfl", "premier league", "champions league", "fifa",
             "world cup", "la liga", "mvp", "deport", "dutch", "bitcoin",
             "crypto", "nhl", "mlb", "serie a"]


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
            credit = f"HY+{int(spread * 100)}"
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

    # Build line with consistent format
    segs = [f"VIX {vix:.0f}" if vix else "VIX ?", struct]
    if credit:
        segs.append(credit)
    if "m2" in info:
        segs.append(info["m2"])
    if tny:
        segs.append(f"10Y{tny:.1f}")
    line = f"{dot} " + " │ ".join(segs)

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
        bars = min(int(abs(rel) * 1.5), 6)
        b = "▓" * bars + "░" * max(0, 5 - bars)
        if rel > 0.5:
            parts.append(f"▶{lbl}{b}")
        elif rel < -0.5:
            parts.append(f"◁{lbl}{b}")
        else:
            parts.append(f"→{lbl}")

    line = "💸 " + "  ".join(parts)

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

    line = f"📋 insdr {insider_str} │ formD {form_d_count} AI/{form_d_total} wk"

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

    try:
        url = ("https://gamma-api.polymarket.com/events"
               "?limit=50&active=true&closed=false&order=volume&ascending=false")
        events = fetch(url)

        for e in events:
            title_lower = e.get("title", "").lower()
            desc_lower = e.get("description", "").lower()
            search_text = title_lower + " " + desc_lower

            # Skip non-financial events
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
            prices = m.get("outcomePrices", "[]")
            if isinstance(prices, str):
                p = json.loads(prices)
            else:
                p = prices

            if not p or not p[0]:
                continue

            try:
                prob = float(p[0]) * 100
            except (ValueError, TypeError):
                continue

            # Build short label — pattern match known events first
            raw = event_title.split("?")[0].split("...")[0].strip()
            rl = raw.lower()
            if "fed chair" in rl or ("nominate" in rl and "fed" in rl):
                short = "Fed Chair"
            elif "strike" in rl and "iran" in rl:
                short = "Iran strk"
            elif ("fed" in rl or "fomc" in rl) and ("rate" in rl or "decision" in rl or "interest" in rl or "decrease" in rl):
                short = "rate cut"
            elif "recession" in rl:
                short = "recession"
            elif "tariff" in rl:
                short = "tariff"
            elif "inflation" in rl:
                short = "inflation"
            elif "war" in rl or "conflict" in rl:
                short = "conflict"
            else:
                for rm in ["Will ", "the ", "Trump ", "United States ",
                            "How many ", "What will ", "Who will "]:
                    raw = raw.replace(rm, "")
                short = raw.replace("  ", " ").strip()
                if len(short) > 12:
                    words = short[:13].rsplit(" ", 1)
                    short = words[0] if len(words) > 1 else short[:11]
            full_q = m.get("question", event_title)
            markets.append({"short": f"{short} {prob:.0f}%",
                            "full": full_q, "prob": prob})

            if len(markets) >= 3:
                break
    except Exception:
        pass

    if markets:
        line = "⚖ " + " │ ".join(m["short"] for m in markets[:3])
    else:
        line = "⚖ polymarket unavail"

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

    reason_str = " ".join(reasons[:4]) if reasons else "mixed signals"
    line = f"💡 {reason_str} │ {signal}"

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

    # Compose: lines 1-5, blank, lines 7-11 (explanations)
    content = "\n".join(lines) + "\n\n" + "\n".join(explains)

    # Timestamp
    now = datetime.now(PT)
    content += f"\n\n⏱ {now.strftime('%b %d %I:%M%p PT')}"

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
