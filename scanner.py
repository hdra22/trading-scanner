import io
import json
import sys
import time
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import yfinance as yf

from strategies import check_all_strategies
from naked_forex_strategies import check_naked_forex_strategies
from notifier import send_scan_summary
from results_store import save_scan


TIMEFRAME_MAP = {
    "1m":  ("1m",  "7d"),
    "5m":  ("5m",  "60d"),
    "15m": ("15m", "60d"),
    "30m": ("30m", "60d"),
    "1h":  ("1h",  "730d"),
    "4h":  ("4h",  "730d"),
    "1d":  ("1d",  "5y"),
}


def load_config(path="config.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_data(symbol, timeframe):
    if timeframe not in TIMEFRAME_MAP:
        print(f"  Timeframe '{timeframe}' não suportado. Disponíveis: {list(TIMEFRAME_MAP)}")
        return None
    interval, period = TIMEFRAME_MAP[timeframe]
    try:
        df = yf.Ticker(symbol).history(period=period, interval=interval)
        if df.empty:
            print(f"  Sem dados para {symbol} [{timeframe}]")
            return None
        return df
    except Exception as e:
        print(f"  Erro ao buscar {symbol}: {e}")
        return None


def run_scan(config_path="config.json"):
    import os
    cfg        = load_config(config_path)
    watchlist  = cfg["watchlist"]
    timeframes = cfg["timeframes"]
    names      = cfg.get("symbol_names", {})

    # Allow GitHub Actions (or any CI) to override Telegram credentials via env vars
    tg = cfg["telegram"].copy()
    if os.getenv("TELEGRAM_TOKEN"):
        tg["token"]   = os.environ["TELEGRAM_TOKEN"]
        tg["chat_id"] = os.environ["TELEGRAM_CHAT_ID"]

    has_classic = "classic_strategies" in cfg
    has_naked   = "naked_forex_strategies" in cfg

    print(f"\n{'='*60}")
    print(f"  TRADING SCANNER  —  {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"  Ativos: {len(watchlist)}  |  Timeframes: {', '.join(timeframes)}")
    print(f"{'='*60}")

    all_results = []
    start_time  = time.time()

    for symbol in watchlist:
        for tf in timeframes:
            print(f"  {symbol} [{tf}]", end="  ", flush=True)
            df = fetch_data(symbol, tf)
            if df is None:
                continue

            results = []
            if has_classic:
                results += check_all_strategies(df, cfg["classic_strategies"])
            if has_naked:
                results += check_naked_forex_strategies(df, cfg["naked_forex_strategies"])

            if not results:
                print("sem setup")
                continue

            for r in results:
                r["symbol"]       = symbol
                r["display_name"] = names.get(symbol, symbol)
                r["timeframe"]    = tf
                all_results.append(r)
                score_str = f"  score={r.get('score', '?')}/10  R:R=1:{r.get('rr_ratio', '?')}"
                print(f"\n    ✓ {r['strategy']} → {r['signal']}{score_str}", end="")

            print()

    elapsed = time.time() - start_time

    # --- Quality filter ---
    filters   = cfg.get("filters", {})
    min_score = filters.get("min_score", 8)
    min_rr    = filters.get("min_rr", 2.0)

    before = len(all_results)
    all_results = [
        r for r in all_results
        if r.get("score", 0) >= min_score and r.get("rr_ratio", 0.0) >= min_rr
    ]
    filtered_out = before - len(all_results)

    print(f"\n{'='*60}")
    print(f"  Scan concluído em {int(elapsed)}s  |  Setups brutos: {before}")
    print(f"  Filtro  score>={min_score}  R:R>={min_rr}  →  {len(all_results)} aprovados  ({filtered_out} removidos)")
    print(f"{'='*60}\n")

    send_scan_summary(tg, all_results, timeframes, len(watchlist), elapsed)
    save_scan(all_results, len(watchlist), timeframes, elapsed, before)


if __name__ == "__main__":
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.json"
    run_scan(config_path)
