import pandas as pd
import ta

from naked_forex_strategies import find_zones, _nearest_zone, score_setup, compute_rr, _pattern_quality


def check_rsi_oversold(df, cfg):
    period    = cfg.get("rsi_period", 14)
    long_thr  = cfg.get("rsi_long_threshold", 35)
    short_thr = cfg.get("rsi_short_threshold", 65)

    df2 = df.copy()
    df2["rsi"] = ta.momentum.RSIIndicator(df2["Close"], window=period).rsi()

    last = df2.iloc[-1]
    rsi  = last["rsi"]

    if pd.isna(rsi):
        return None

    rsi = round(rsi, 2)

    if rsi <= long_thr:
        signal = "LONG"
        # Pattern quality: how extreme the RSI is below threshold
        excess = long_thr - rsi
        pq = _pattern_quality(excess, [5, 10, 15])
    elif rsi >= short_thr:
        signal = "SHORT"
        excess = rsi - short_thr
        pq = _pattern_quality(excess, [5, 10, 15])
    else:
        return None

    close = round(last["Close"], 4)

    # Find nearest zone to current price for scoring / R:R
    zones     = find_zones(df)
    zone_level = _nearest_zone(close, zones, tolerance_pct=1.5)
    if zone_level is None and zones:
        # Use nearest zone even if not within tolerance (for R:R calc)
        zone_level = min(zones, key=lambda z: abs(z - close))

    sc        = score_setup(df, signal, zone_level or close, pq)
    rr_result = compute_rr(df, signal, zone_level or close, zones)
    entry, sl, tp, rr = rr_result if rr_result else (close, None, None, 0.0)

    return {
        "strategy": "RSI Oversold" if signal == "LONG" else "RSI Overbought",
        "signal": signal,
        "rsi": rsi,
        "price": close,
        "score": sc,
        "entry": entry,
        "stop_loss": sl,
        "take_profit": tp,
        "rr_ratio": rr,
        "details": (
            f"RSI={rsi} ({'abaixo' if signal == 'LONG' else 'acima'} de "
            f"{long_thr if signal == 'LONG' else short_thr}) | "
            f"Score={sc}/10 | R:R=1:{rr}"
        ),
    }


def check_ema_pullback(df, cfg):
    ema_fast     = cfg.get("ema_fast", 21)
    ema_slow     = cfg.get("ema_slow", 50)
    rsi_period   = cfg.get("rsi_period", 14)
    proximity_pct = cfg.get("proximity_pct", 1.5)

    df2 = df.copy()
    df2["ema_fast"] = ta.trend.EMAIndicator(df2["Close"], window=ema_fast).ema_indicator()
    df2["ema_slow"] = ta.trend.EMAIndicator(df2["Close"], window=ema_slow).ema_indicator()
    df2["rsi"]      = ta.momentum.RSIIndicator(df2["Close"], window=rsi_period).rsi()

    last  = df2.iloc[-1]
    close = last["Close"]
    ef    = last["ema_fast"]
    es    = last["ema_slow"]
    rsi   = last["rsi"]

    if pd.isna(ef) or pd.isna(es) or pd.isna(rsi):
        return None

    in_uptrend = close > es and ef > es
    dist_pct   = abs(close - ef) / ef * 100
    pulled_back = dist_pct <= proximity_pct
    rsi_ok      = 35 <= rsi <= 60

    if not (in_uptrend and pulled_back and rsi_ok):
        return None

    # Pattern quality: EMA spread (trend strength) + proximity
    ema_spread_pct = abs(ef - es) / es * 100
    pq_spread  = _pattern_quality(ema_spread_pct, [1.0, 2.0, 3.0])
    pq_proximity = 4 - _pattern_quality(dist_pct, [0.3, 0.8, 1.2])  # closer = better
    pq = min(4, max(1, (pq_spread + pq_proximity) // 2 + 1))

    # EMA21 acts as dynamic support → use it as zone_level
    zones     = find_zones(df)
    sc        = score_setup(df, "LONG", float(ef), pq)
    rr_result = compute_rr(df, "LONG", float(ef), zones)
    entry, sl, tp, rr = rr_result if rr_result else (round(close, 4), None, None, 0.0)

    return {
        "strategy": "EMA Pullback",
        "signal": "LONG",
        "rsi": round(rsi, 2),
        "price": round(close, 4),
        "ema21": round(ef, 4),
        "ema50": round(es, 4),
        "score": sc,
        "entry": entry,
        "stop_loss": sl,
        "take_profit": tp,
        "rr_ratio": rr,
        "details": (
            f"Pullback para EMA{ema_fast} ({dist_pct:.1f}%) em uptrend | "
            f"Score={sc}/10 | R:R=1:{rr}"
        ),
    }


def check_macd_cross(df, cfg):
    fast   = cfg.get("fast", 12)
    slow   = cfg.get("slow", 26)
    signal = cfg.get("signal", 9)

    if len(df) < slow + signal + 5:
        return None

    df2      = df.copy()
    macd_obj = ta.trend.MACD(df2["Close"], window_fast=fast, window_slow=slow, window_sign=signal)
    df2["hist"]        = macd_obj.macd_diff()
    df2["macd"]        = macd_obj.macd()
    df2["signal_line"] = macd_obj.macd_signal()
    df2["rsi"]         = ta.momentum.RSIIndicator(df2["Close"], window=14).rsi()

    last = df2.iloc[-1]
    prev = df2.iloc[-2]

    if pd.isna(last["hist"]) or pd.isna(prev["hist"]):
        return None

    rsi_val = last["rsi"]

    if prev["hist"] < 0 and last["hist"] >= 0:
        sig = "LONG"
    elif prev["hist"] > 0 and last["hist"] <= 0:
        sig = "SHORT"
    else:
        return None

    # Pattern quality: RSI alignment at cross
    if not pd.isna(rsi_val):
        if sig == "LONG":
            pq = _pattern_quality(50 - rsi_val, [0, 10, 20])   # lower RSI → better LONG cross
        else:
            pq = _pattern_quality(rsi_val - 50, [0, 10, 20])   # higher RSI → better SHORT cross
    else:
        pq = 1

    close     = round(last["Close"], 4)
    zones     = find_zones(df)
    zone_level = _nearest_zone(close, zones, tolerance_pct=1.5)
    if zone_level is None and zones:
        zone_level = min(zones, key=lambda z: abs(z - close))

    sc        = score_setup(df, sig, zone_level or close, pq)
    rr_result = compute_rr(df, sig, zone_level or close, zones)
    entry, sl, tp, rr = rr_result if rr_result else (close, None, None, 0.0)

    strategy_name = "MACD Cross Bullish" if sig == "LONG" else "MACD Cross Bearish"

    return {
        "strategy": strategy_name,
        "signal": sig,
        "macd": round(last["macd"], 6),
        "macd_signal": round(last["signal_line"], 6),
        "price": close,
        "score": sc,
        "entry": entry,
        "stop_loss": sl,
        "take_profit": tp,
        "rr_ratio": rr,
        "details": (
            f"MACD cruzou {'acima' if sig == 'LONG' else 'abaixo'} da signal line | "
            f"Score={sc}/10 | R:R=1:{rr}"
        ),
    }


_STRATEGY_MAP = {
    "rsi_oversold": check_rsi_oversold,
    "ema_pullback":  check_ema_pullback,
    "macd_cross":    check_macd_cross,
}


def check_all_strategies(df, strategies_cfg):
    results = []
    for name, cfg in strategies_cfg.items():
        if not cfg.get("enabled", True):
            continue
        fn = _STRATEGY_MAP.get(name)
        if fn is None:
            continue
        try:
            result = fn(df, cfg)
            if result:
                results.append(result)
        except Exception:
            pass
    return results
