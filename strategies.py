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


def check_fvg(df, cfg):
    """
    Fair Value Gap (FVG / Imbalance) — conceito ICT.

    Padrão de 3 velas onde a vela do meio cria um desequilíbrio (gap)
    entre a vela 1 e a vela 3. O preço tende a regressar para preencher
    esse gap antes de continuar na direção do impulso.

    Bullish FVG : low[i] > high[i-2]  →  gap abaixo do preço atual  → LONG
    Bearish FVG : high[i] < low[i-2]  →  gap acima do preço atual   → SHORT

    Condições de entrada:
      1. FVG identificado nos últimos <lookback> candles.
      2. Preço regresso ao interior do gap.
      3. Candle de confirmação na direção do impulso original.
      4. Impulso mínimo de <min_impulse_mult>x ATR (filtra gaps de ruído).
      5. Dimensão mínima do gap de <min_gap_mult>x ATR.
    """
    lookback          = cfg.get("lookback", 50)
    min_impulse_mult  = cfg.get("min_impulse_mult", 1.5)
    min_gap_mult      = cfg.get("min_gap_mult", 0.3)

    if len(df) < max(lookback, 20):
        return None

    highs  = df["High"].values
    lows   = df["Low"].values
    closes = df["Close"].values
    opens  = df["Open"].values
    n      = len(df)

    # ATR para validar tamanho do impulso e do gap
    try:
        atr = ta.volatility.AverageTrueRange(
            df["High"], df["Low"], df["Close"], window=14
        ).average_true_range().iloc[-1]
    except Exception:
        return None
    if pd.isna(atr) or atr <= 0:
        return None

    cur_high  = highs[-1]
    cur_low   = lows[-1]
    cur_close = closes[-1]
    cur_open  = opens[-1]
    cur_range = cur_high - cur_low

    best_signal = None
    best_score  = -1

    # Janela de pesquisa: FVG formado entre (n-lookback) e (n-3)
    # — i é a 3ª vela do padrão; deixamos pelo menos 1 barra entre o FVG e o candle atual
    for i in range(max(2, n - lookback), n - 2):
        h0, l0 = highs[i - 2], lows[i - 2]   # vela 1
        h1, l1 = highs[i - 1], lows[i - 1]   # vela impulso
        h2, l2 = highs[i],     lows[i]        # vela 3
        impulse_size = h1 - l1

        # ── Bullish FVG ─────────────────────────────────────────────────────
        # Gap:  low[3] > high[1]  →  zona = [high[1] , low[3]]
        if l2 > h0:
            gap_low  = h0
            gap_high = l2
            gap_size = gap_high - gap_low

            if impulse_size < min_impulse_mult * atr:
                continue
            if gap_size < min_gap_mult * atr:
                continue
            if closes[i - 1] <= opens[i - 1]:      # impulso deve ser bullish
                continue

            # Preço regressou ao interior do gap?
            inside = (gap_low <= cur_low <= gap_high) or \
                     (gap_low <= cur_close <= gap_high)
            if not inside:
                continue

            # Confirmação: candle atual bullish, fecha na metade superior
            if cur_range <= 0:
                continue
            if not (cur_close > cur_open and
                    cur_close >= cur_low + cur_range * 0.5):
                continue

            impulse_ratio = impulse_size / atr
            pq     = _pattern_quality(impulse_ratio, [1.5, 2.5, 4.0])
            zones  = find_zones(df)
            gap_mid = (gap_low + gap_high) / 2
            sc     = score_setup(df, "LONG", gap_mid, pq)
            rr_res = compute_rr(df, "LONG", gap_mid, zones)
            if rr_res is None:
                continue
            entry, sl, tp, rr = rr_res

            if sc > best_score:
                best_score  = sc
                best_signal = {
                    "strategy":   "FVG Bullish",
                    "signal":     "LONG",
                    "price":      round(cur_close, 5),
                    "fvg_low":    round(gap_low, 5),
                    "fvg_high":   round(gap_high, 5),
                    "score":      sc,
                    "entry":      entry,
                    "stop_loss":  sl,
                    "take_profit": tp,
                    "rr_ratio":   rr,
                    "details": (
                        f"FVG Bullish | Gap=[{round(gap_low, 4)}-{round(gap_high, 4)}] | "
                        f"Impulso={round(impulse_ratio, 1)}x ATR | "
                        f"Score={sc}/10 | R:R=1:{rr}"
                    ),
                }

        # ── Bearish FVG ─────────────────────────────────────────────────────
        # Gap:  high[3] < low[1]  →  zona = [high[3] , low[1]]
        if h2 < l0:
            gap_low  = h2
            gap_high = l0
            gap_size = gap_high - gap_low

            if impulse_size < min_impulse_mult * atr:
                continue
            if gap_size < min_gap_mult * atr:
                continue
            if closes[i - 1] >= opens[i - 1]:      # impulso deve ser bearish
                continue

            # Preço regressou ao interior do gap?
            inside = (gap_low <= cur_high <= gap_high) or \
                     (gap_low <= cur_close <= gap_high)
            if not inside:
                continue

            # Confirmação: candle atual bearish, fecha na metade inferior
            if cur_range <= 0:
                continue
            if not (cur_close < cur_open and
                    cur_close <= cur_low + cur_range * 0.5):
                continue

            impulse_ratio = impulse_size / atr
            pq     = _pattern_quality(impulse_ratio, [1.5, 2.5, 4.0])
            zones  = find_zones(df)
            gap_mid = (gap_low + gap_high) / 2
            sc     = score_setup(df, "SHORT", gap_mid, pq)
            rr_res = compute_rr(df, "SHORT", gap_mid, zones)
            if rr_res is None:
                continue
            entry, sl, tp, rr = rr_res

            if sc > best_score:
                best_score  = sc
                best_signal = {
                    "strategy":   "FVG Bearish",
                    "signal":     "SHORT",
                    "price":      round(cur_close, 5),
                    "fvg_low":    round(gap_low, 5),
                    "fvg_high":   round(gap_high, 5),
                    "score":      sc,
                    "entry":      entry,
                    "stop_loss":  sl,
                    "take_profit": tp,
                    "rr_ratio":   rr,
                    "details": (
                        f"FVG Bearish | Gap=[{round(gap_low, 4)}-{round(gap_high, 4)}] | "
                        f"Impulso={round(impulse_ratio, 1)}x ATR | "
                        f"Score={sc}/10 | R:R=1:{rr}"
                    ),
                }

    return best_signal


_STRATEGY_MAP = {
    "rsi_oversold": check_rsi_oversold,
    "ema_pullback":  check_ema_pullback,
    "macd_cross":    check_macd_cross,
    "fvg":           check_fvg,
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
