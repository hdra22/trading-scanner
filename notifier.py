import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict

_PT = ZoneInfo("Europe/Lisbon")


MAX_CHARS = 3800  # Telegram limit is 4096; stay safe

# ---------------------------------------------------------------------------
# TradingView URL helpers
# ---------------------------------------------------------------------------

# yfinance symbol → TradingView "EXCHANGE:SYMBOL" format
_TV_SYMBOL_MAP = {
    # Forex (most are auto-derived, overrides only where needed)
    # Crypto
    "BTC-USD":   "BITSTAMP:BTCUSD",
    "ETH-USD":   "BITSTAMP:ETHUSD",
    "SOL-USD":   "BINANCE:SOLUSDT",
    # Metals & energy futures
    "GC=F":      "COMEX:GC1!",
    "SI=F":      "COMEX:SI1!",
    "CL=F":      "NYMEX:CL1!",
    "NG=F":      "NYMEX:NG1!",
    # Global indices
    "^GSPC":     "SP:SPX",
    "^DJI":      "DJ:DJI",
    "^GDAXI":    "XETR:DAX",
    "^FTSE":     "SPREADEX:FTSE",
    "^N225":     "INDEX:NKY",
    "^AXJO":     "ASX:XJO",
    "000016.SS": "SSE:000016",
    "^FCHI":     "EURONEXT:PX1",
    "^IBEX":     "BME:IBC",
    # Brazilian stocks
    "PETR4.SA":  "BMFBOVESPA:PETR4",
    "VALE3.SA":  "BMFBOVESPA:VALE3",
    "ITUB4.SA":  "BMFBOVESPA:ITUB4",
    "BBDC4.SA":  "BMFBOVESPA:BBDC4",
}

_TV_TF_MAP = {
    "1m": "1", "5m": "5", "15m": "15", "30m": "30",
    "1h": "60", "4h": "240", "1d": "D", "1w": "W",
}


def _fmt_price(price):
    """Format a price with appropriate decimal places based on magnitude."""
    if price is None:
        return "—"
    if price >= 10_000:
        return f"{price:,.0f}"
    elif price >= 1_000:
        return f"{price:,.1f}"
    elif price >= 100:
        return f"{price:.2f}"
    elif price >= 10:
        return f"{price:.3f}"
    elif price >= 1:
        return f"{price:.4f}"
    else:
        return f"{price:.5f}"


def _tv_symbol(yf_symbol):
    """Convert a yfinance symbol to TradingView EXCHANGE:SYMBOL format."""
    if yf_symbol in _TV_SYMBOL_MAP:
        return _TV_SYMBOL_MAP[yf_symbol]
    # Forex: EURUSD=X  →  FX:EURUSD
    if yf_symbol.endswith("=X"):
        return f"FX:{yf_symbol[:-2]}"
    return None


def _tv_url(yf_symbol, timeframe):
    """Return a TradingView chart URL for the given symbol and timeframe, or None."""
    tv_sym = _tv_symbol(yf_symbol)
    if not tv_sym:
        return None
    tv_tf = _TV_TF_MAP.get(timeframe, "D")
    return f"https://www.tradingview.com/chart/?symbol={tv_sym}&interval={tv_tf}"


# ---------------------------------------------------------------------------
# Telegram helpers
# ---------------------------------------------------------------------------

def send_telegram_message(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        print(f"  Erro ao enviar Telegram: {e}")
        return False


def _send_chunked(token, chat_id, lines):
    """Send lines as one or more messages respecting Telegram's character limit."""
    chunk, size = [], 0
    for line in lines:
        line_len = len(line) + 1  # +1 for newline
        if size + line_len > MAX_CHARS and chunk:
            send_telegram_message(token, chat_id, "\n".join(chunk))
            chunk, size = [], 0
        chunk.append(line)
        size += line_len
    if chunk:
        send_telegram_message(token, chat_id, "\n".join(chunk))


# ---------------------------------------------------------------------------
# Main summary sender
# ---------------------------------------------------------------------------

def send_scan_summary(telegram_cfg, results, timeframes, n_symbols, elapsed_seconds=None):
    """
    Send a single (or multi-part) summary message at end of scan.
    Groups signals by asset — one line per (symbol, timeframe), showing
    best score and R:R, with a direct TradingView chart link.
    """
    token   = telegram_cfg["token"]
    chat_id = telegram_cfg["chat_id"]
    now     = datetime.now(_PT)

    next_run = now.replace(minute=5, second=0, microsecond=0) + timedelta(hours=4)

    # Group results by (display_name, timeframe) under each signal direction.
    # Each slot holds a list of dicts {strategy, score, rr, symbol}.
    grouped = defaultdict(lambda: defaultdict(list))
    for r in results:
        key_name = r.get("display_name", r["symbol"])
        key_tf   = r["timeframe"]
        grouped[r["signal"]][(key_name, key_tf)].append({
            "strategy": r["strategy"],
            "score":    r.get("score", 0),
            "rr":       r.get("rr_ratio", 0.0),
            "symbol":   r["symbol"],
            "entry":    r.get("entry"),
            "sl":       r.get("stop_loss"),
            "tp":       r.get("take_profit"),
        })

    longs  = grouped.get("LONG",  {})
    shorts = grouped.get("SHORT", {})

    elapsed_str = f"  |  ⏱ {int(elapsed_seconds)}s" if elapsed_seconds else ""

    lines = [
        "📊 <b>Trading Scanner — Resumo</b>",
        f"🕐 {now.strftime('%d/%m/%Y %H:%M')}  |  TF: {', '.join(timeframes)}{elapsed_str}",
        f"📂 {n_symbols} ativos  |  ⏭ próximo: {next_run.strftime('%H:%M')}",
        "",
    ]

    if not results:
        lines.append("🔍 <b>Nenhum setup encontrado.</b>")
        send_telegram_message(token, chat_id, "\n".join(lines))
        print("  → Resumo enviado ao Telegram (0 setups)")
        return

    n_long_assets  = len(longs)
    n_short_assets = len(shorts)
    total_setups   = len(results)
    lines.append(
        f"✅ <b>{total_setups} setups</b> em "
        f"{n_long_assets + n_short_assets} ativos  |  score ≥ 8  |  R:R ≥ 1:2"
    )
    lines.append("")

    SEP = "    <code>─────────────────────</code>"

    def _format_group(direction_dict):
        out = []
        items = sorted(direction_dict.items())
        for idx, ((name, tf), setups) in enumerate(items):
            # Deduplicate strategy names (preserve first occurrence)
            seen = {}
            for s in setups:
                seen.setdefault(s["strategy"], s)
            unique = list(seen.values())

            strats    = " · ".join(s["strategy"] for s in unique)
            max_score = max(s["score"] for s in unique)
            # Use entry/SL/TP from the highest-scoring strategy
            best = max(unique, key=lambda s: (s["score"], s["rr"]))
            best_rr = best["rr"]
            rr_str  = f"{best_rr:.1f}" if best_rr > 0 else "—"

            # TradingView link (opens chart at correct symbol + timeframe)
            tv_link = ""
            yf_sym  = best["symbol"]
            url     = _tv_url(yf_sym, tf)
            if url:
                tv_link = f'  <a href="{url}">📈 TV</a>'

            entry_s = _fmt_price(best["entry"])
            sl_s    = _fmt_price(best["sl"])
            tp_s    = _fmt_price(best["tp"])

            out.append(
                f"  • <b>{name}</b>  {tf}  ⭐{max_score}/10  ⚖️1:{rr_str}"
            )
            out.append(
                f"    📌 {strats}{tv_link}"
            )
            out.append(
                f"    ▶ Entrada  <code>{entry_s}</code>"
            )
            out.append(
                f"    🛑 SL      <code>{sl_s}</code>"
            )
            out.append(
                f"    🎯 TP      <code>{tp_s}</code>"
            )
            if idx < len(items) - 1:
                out.append(SEP)
        return out

    if longs:
        lines.append(f"📈 <b>LONG — {n_long_assets} ativo(s)</b>")
        lines.extend(_format_group(longs))
        lines.append("")

    if shorts:
        lines.append(f"📉 <b>SHORT — {n_short_assets} ativo(s)</b>")
        lines.extend(_format_group(shorts))
        lines.append("")

    lines.append("⚠️ <i>Faça a sua análise antes de operar.</i>")

    _send_chunked(token, chat_id, lines)
    print(f"  → Resumo enviado ao Telegram ({total_setups} setups, {n_long_assets + n_short_assets} ativos)")
