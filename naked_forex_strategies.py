"""
Naked Forex strategies based on: "Naked Forex" by Alex Nekritin & Walter Peters.
All setups are price-action only — no indicators.
Core concept: price must be at a support/resistance ZONE for a signal to be valid.
"""
import numpy as np
import pandas as pd
import ta


# ---------------------------------------------------------------------------
# Zone detection
# ---------------------------------------------------------------------------

def find_zones(df, lookback=150, tolerance_pct=0.5, min_touches=2):
    """
    Find support/resistance zones where price has repeatedly reversed.
    Returns list of price levels.
    """
    data = df.tail(lookback).copy()
    highs = data['High'].values
    lows = data['Low'].values

    # Collect swing highs and swing lows (local extrema, 2-bar window)
    levels = []
    for i in range(2, len(data) - 2):
        if highs[i] >= highs[i-1] and highs[i] >= highs[i-2] and \
           highs[i] >= highs[i+1] and highs[i] >= highs[i+2]:
            levels.append(highs[i])
        if lows[i] <= lows[i-1] and lows[i] <= lows[i-2] and \
           lows[i] <= lows[i+1] and lows[i] <= lows[i+2]:
            levels.append(lows[i])

    if len(levels) < 2:
        return []

    levels.sort()

    # Cluster nearby levels (within tolerance_pct of each other)
    clusters = []
    used = [False] * len(levels)
    for i in range(len(levels)):
        if used[i]:
            continue
        cluster = [levels[i]]
        for j in range(i + 1, len(levels)):
            if used[j]:
                continue
            if abs(levels[j] - levels[i]) / levels[i] * 100 <= tolerance_pct:
                cluster.append(levels[j])
                used[j] = True
        used[i] = True
        clusters.append(float(np.mean(cluster)))

    # Keep only zones with enough touches
    valid_zones = []
    for zone in clusters:
        tol = zone * tolerance_pct / 100
        touches = sum(
            1 for i in range(len(data))
            if lows[i] <= zone + tol and highs[i] >= zone - tol
        )
        if touches >= min_touches:
            valid_zones.append(round(zone, 6))

    return valid_zones


def _nearest_zone(price, zones, tolerance_pct=0.75):
    """Return the closest zone within tolerance, or None."""
    for zone in zones:
        if abs(price - zone) / zone * 100 <= tolerance_pct:
            return zone
    return None


def _room_to_left(df, idx, price_level, tolerance_pct=0.5, min_candles=7):
    """Count consecutive candles to the left that did NOT touch price_level."""
    tol = price_level * tolerance_pct / 100
    count = 0
    for i in range(idx - 1, max(0, idx - 80), -1):
        row = df.iloc[i]
        if row['Low'] <= price_level + tol and row['High'] >= price_level - tol:
            break
        count += 1
    return count


# ---------------------------------------------------------------------------
# Scoring & R:R helpers  (also imported by strategies.py)
# ---------------------------------------------------------------------------

def _count_touches(df, zone_level, lookback=150, tolerance_pct=0.5):
    """Count candles that touched zone_level within lookback bars."""
    data = df.tail(lookback)
    tol = zone_level * tolerance_pct / 100
    highs = data['High'].values
    lows  = data['Low'].values
    return sum(
        1 for i in range(len(data))
        if lows[i] <= zone_level + tol and highs[i] >= zone_level - tol
    )


def score_setup(df, signal, zone_level, pattern_quality_0to4):
    """
    Compute a 0-10 quality score for any setup.

    Components:
      0-4 pts  Pattern quality    (passed in — strategy-specific)
      0-2 pts  Zone quality       (touch count at zone_level)
      0-2 pts  Trend alignment    (EMA21 vs EMA50)
      0-2 pts  RSI confirmation   (RSI position relative to 50)

    Args:
        df                  : full OHLCV DataFrame
        signal              : 'LONG' or 'SHORT'
        zone_level          : price level of the S/R zone (None if not applicable)
        pattern_quality_0to4: 0-4 integer from the strategy's own quality metric
    """
    score = int(pattern_quality_0to4)

    # Zone quality (0-2): based on how many times price has respected this zone
    if zone_level and zone_level > 0:
        touches = _count_touches(df, zone_level)
        if touches >= 4:
            score += 2
        elif touches >= 3:
            score += 1

    # Trend alignment via EMA21/50 (0-2)
    closes = df['Close'].values
    if len(closes) >= 50:
        ema21 = float(pd.Series(closes).ewm(span=21, adjust=False).mean().iloc[-1])
        ema50 = float(pd.Series(closes).ewm(span=50, adjust=False).mean().iloc[-1])
        if signal == 'LONG' and ema21 > ema50:
            score += 2
        elif signal == 'SHORT' and ema21 < ema50:
            score += 2

    # RSI confirmation (0-2): extremes add 2 pts, mild favour adds 1 pt
    try:
        rsi_val = ta.momentum.RSIIndicator(df['Close'], window=14).rsi().iloc[-1]
        if not pd.isna(rsi_val):
            if signal == 'LONG':
                if rsi_val < 40:
                    score += 2
                elif rsi_val < 50:
                    score += 1
            else:  # SHORT
                if rsi_val > 60:
                    score += 2
                elif rsi_val > 50:
                    score += 1
    except Exception:
        pass

    return min(score, 10)


def compute_rr(df, signal, zone_level, all_zones, min_rr=2.0):
    """
    Compute risk/reward using zone-based SL and a qualifying opposing zone as TP.

    SL placement:
      LONG  → just below the zone (zone * 0.995), or candle low if lower
      SHORT → just above the zone (zone * 1.005), or candle high if higher

    TP placement (uses extended 300-bar lookback):
      Finds the NEAREST zone on the profit side that provides >= min_rr R:R.
      Skips zones that are too close to produce a meaningful reward.
      Returns None if no such zone exists in the data (e.g. ATH with no resistance).

    Returns (entry, stop_loss, take_profit, rr_ratio) or None.
    """
    entry       = float(df['Close'].iloc[-1])
    candle_low  = float(df['Low'].iloc[-1])
    candle_high = float(df['High'].iloc[-1])

    zone_tol = (zone_level * 0.005) if (zone_level and zone_level > 0) else 0.0

    # Wider zone search for TP (up to 300 bars gives ~1yr on 1d, ~50d on 4h)
    extended_zones = find_zones(df, lookback=min(len(df), 300), tolerance_pct=0.5)
    tp_zones = list({round(z, 6) for z in all_zones + extended_zones})

    if signal == 'LONG':
        zone_sl = (zone_level - zone_tol) if zone_level else candle_low
        sl      = min(zone_sl, candle_low)
        risk    = entry - sl
        if risk <= 0:
            return None
        # Find the NEAREST zone that delivers at least min_rr R:R
        min_tp  = entry + min_rr * risk
        candidates = sorted(z for z in tp_zones if z >= min_tp)
        if not candidates:
            return None
        tp     = candidates[0]
        reward = tp - entry

    else:  # SHORT
        zone_sl = (zone_level + zone_tol) if zone_level else candle_high
        sl      = max(zone_sl, candle_high)
        risk    = sl - entry
        if risk <= 0:
            return None
        max_tp     = entry - min_rr * risk
        candidates = sorted(
            (z for z in tp_zones if z <= max_tp), reverse=True
        )
        if not candidates:
            return None
        tp     = candidates[0]
        reward = entry - tp

    if risk <= 0 or reward <= 0:
        return None

    rr = round(reward / risk, 2)
    return round(entry, 6), round(sl, 6), round(tp, 6), rr


def _pattern_quality(value, thresholds):
    """Map a numeric value to 1-4 using ascending thresholds list [t1, t2, t3]."""
    if value >= thresholds[2]:
        return 4
    if value >= thresholds[1]:
        return 3
    if value >= thresholds[0]:
        return 2
    return 1


# ---------------------------------------------------------------------------
# Strategy 1 — Kangaroo Tail (Pin Bar)  [Chapter 8]
# ---------------------------------------------------------------------------

def check_kangaroo_tail(df, cfg):
    """
    Bullish: long lower tail, body in top 1/3, on support zone.
    Bearish: long upper tail, body in bottom 1/3, on resistance zone.
    Rules:
      - Open & close inside previous candle's range
      - Tail >= 2x body
      - Must be on a zone
      - Room to the left >= 7 candles
    """
    if len(df) < 20:
        return None

    tol      = cfg.get('zone_tolerance_pct', 0.5)
    tail_ratio = cfg.get('min_tail_body_ratio', 2.0)
    room_req = cfg.get('min_room_to_left', 7)

    zones = find_zones(df, tolerance_pct=tol)
    if not zones:
        return None

    idx  = len(df) - 1
    c    = df.iloc[idx]
    prev = df.iloc[idx - 1]
    o, h, l, close = c['Open'], c['High'], c['Low'], c['Close']
    candle_range = h - l
    if candle_range == 0:
        return None

    body_high = max(o, close)
    body_low  = min(o, close)
    body_size = max(body_high - body_low, candle_range * 0.005)
    lower_tail = body_low - l
    upper_tail = h - body_high

    bullish = (
        body_low >= l + candle_range * (2 / 3) and
        lower_tail >= tail_ratio * body_size and
        body_high <= prev['High'] and body_low >= prev['Low']
    )
    bearish = (
        body_high <= l + candle_range * (1 / 3) and
        upper_tail >= tail_ratio * body_size and
        body_high <= prev['High'] and body_low >= prev['Low']
    )

    if not bullish and not bearish:
        return None

    signal     = 'LONG' if bullish else 'SHORT'
    tail_price = l if bullish else h
    zone       = _nearest_zone(tail_price, zones, tolerance_pct=tol * 1.5)
    if zone is None:
        return None

    room = _room_to_left(df, idx, tail_price, tolerance_pct=tol, min_candles=room_req)
    if room < room_req:
        return None

    # Pattern quality: actual tail/body ratio
    actual_tail = lower_tail if bullish else upper_tail
    pq = _pattern_quality(actual_tail / body_size, [3.0, 4.0, 5.0])

    sc  = score_setup(df, signal, zone, pq)
    rr_result = compute_rr(df, signal, zone, zones)
    entry, sl, tp, rr = rr_result if rr_result else (close, None, None, 0.0)

    return {
        'strategy': 'Kangaroo Tail',
        'signal': signal,
        'price': round(close, 5),
        'zone': round(zone, 5),
        'tail': round(tail_price, 5),
        'room_to_left': room,
        'score': sc,
        'entry': entry,
        'stop_loss': sl,
        'take_profit': tp,
        'rr_ratio': rr,
        'details': (
            f'{"Bullish" if bullish else "Bearish"} Kangaroo Tail | '
            f'Zona={round(zone, 4)} | Tail={round(tail_price, 4)} | '
            f'{room} candles sem toque | Score={sc}/10 | R:R=1:{rr}'
        ),
    }


# ---------------------------------------------------------------------------
# Strategy 2 — Big Shadow (Engulfing)  [Chapter 6]
# ---------------------------------------------------------------------------

def check_big_shadow(df, cfg):
    """
    2-candle formation where the second candle completely engulfs the first.
    Close must be near extreme (top 1/3 for bullish, bottom 1/3 for bearish).
    Must print on a zone with room to the left.
    """
    if len(df) < 15:
        return None

    tol       = cfg.get('zone_tolerance_pct', 0.5)
    extremity = cfg.get('close_extremity_pct', 0.33)
    room_req  = cfg.get('min_room_to_left', 7)

    zones = find_zones(df, tolerance_pct=tol)
    if not zones:
        return None

    idx    = len(df) - 1
    shadow = df.iloc[idx]
    prev   = df.iloc[idx - 1]
    o, h, l, c = shadow['Open'], shadow['High'], shadow['Low'], shadow['Close']
    s_range = h - l
    if s_range == 0:
        return None

    if not (h > prev['High'] and l < prev['Low']):
        return None

    prev_range = prev['High'] - prev['Low']
    if s_range <= prev_range:
        return None

    bullish = c >= l + s_range * (1 - extremity)
    bearish = c <= l + s_range * extremity

    if not bullish and not bearish:
        return None

    signal      = 'LONG' if bullish else 'SHORT'
    check_price = l if bullish else h
    zone        = _nearest_zone(check_price, zones, tolerance_pct=tol * 1.5)
    if zone is None:
        zone = _nearest_zone(h if bullish else l, zones, tolerance_pct=tol * 1.5)
    if zone is None:
        return None

    room = _room_to_left(df, idx, check_price, tolerance_pct=tol, min_candles=room_req)
    if room < room_req:
        return None

    # Pattern quality: engulf ratio
    engulf_ratio = s_range / prev_range if prev_range > 0 else 1.0
    pq = _pattern_quality(engulf_ratio, [1.5, 2.0, 3.0])

    sc        = score_setup(df, signal, zone, pq)
    rr_result = compute_rr(df, signal, zone, zones)
    entry, sl, tp, rr = rr_result if rr_result else (c, None, None, 0.0)

    return {
        'strategy': 'Big Shadow',
        'signal': signal,
        'price': round(c, 5),
        'zone': round(zone, 5),
        'range': round(s_range, 5),
        'room_to_left': room,
        'score': sc,
        'entry': entry,
        'stop_loss': sl,
        'take_profit': tp,
        'rr_ratio': rr,
        'details': (
            f'{"Bullish" if bullish else "Bearish"} Big Shadow | '
            f'Zona={round(zone, 4)} | Range={round(s_range, 4)} | '
            f'{room} candles sem toque | Score={sc}/10 | R:R=1:{rr}'
        ),
    }


# ---------------------------------------------------------------------------
# Strategy 3 — Wammie & Moolah (Double Bottom / Top)  [Chapter 7]
# ---------------------------------------------------------------------------

def check_wammie_moolah(df, cfg):
    """
    Wammie = double bottom with HIGHER second touch (higher low → bullish).
    Moolah = double top  with LOWER second touch (lower high  → bearish).
    """
    if len(df) < 30:
        return None

    tol     = cfg.get('zone_tolerance_pct', 0.5)
    min_gap = cfg.get('min_candles_between_touches', 6)

    zones = find_zones(df, tolerance_pct=tol)
    if not zones:
        return None

    lows   = df['Low'].values
    highs  = df['High'].values
    closes = df['Close'].values
    opens  = df['Open'].values
    n      = len(df)

    for zone in zones:
        zone_tol = zone * tol / 100

        sup_touches = [
            i for i in range(n - 1)
            if zone - zone_tol * 2 <= lows[i] <= zone + zone_tol
        ]
        res_touches = [
            i for i in range(n - 1)
            if zone - zone_tol <= highs[i] <= zone + zone_tol * 2
        ]

        # --- Wammie ---
        for k in range(len(sup_touches) - 1):
            t1, t2 = sup_touches[k], sup_touches[k + 1]
            if t2 - t1 < min_gap:
                continue
            if lows[t2] <= lows[t1]:
                continue
            if n - 1 - t2 > 5:
                continue
            for sig in range(t2, min(t2 + 5, n)):
                rng = highs[sig] - lows[sig]
                if rng == 0:
                    continue
                if closes[sig] >= lows[sig] + rng * 0.6 and closes[sig] > opens[sig]:
                    gap    = t2 - t1
                    pq     = _pattern_quality(gap, [10, 15, 20])
                    sc     = score_setup(df, 'LONG', zone, pq)
                    rr_res = compute_rr(df, 'LONG', zone, zones)
                    entry, sl, tp, rr = rr_res if rr_res else (closes[-1], None, None, 0.0)
                    return {
                        'strategy': 'Wammie (Double Bottom)',
                        'signal': 'LONG',
                        'price': round(closes[-1], 5),
                        'zone': round(zone, 5),
                        'first_touch': round(lows[t1], 5),
                        'second_touch': round(lows[t2], 5),
                        'candles_between': gap,
                        'score': sc,
                        'entry': entry,
                        'stop_loss': sl,
                        'take_profit': tp,
                        'rr_ratio': rr,
                        'details': (
                            f'Wammie | Zona={round(zone, 4)} | '
                            f'1º={round(lows[t1], 4)} 2º={round(lows[t2], 4)} '
                            f'({gap} candles) | Score={sc}/10 | R:R=1:{rr}'
                        ),
                    }

        # --- Moolah ---
        for k in range(len(res_touches) - 1):
            t1, t2 = res_touches[k], res_touches[k + 1]
            if t2 - t1 < min_gap:
                continue
            if highs[t2] >= highs[t1]:
                continue
            if n - 1 - t2 > 5:
                continue
            for sig in range(t2, min(t2 + 5, n)):
                rng = highs[sig] - lows[sig]
                if rng == 0:
                    continue
                if closes[sig] <= lows[sig] + rng * 0.4 and closes[sig] < opens[sig]:
                    gap    = t2 - t1
                    pq     = _pattern_quality(gap, [10, 15, 20])
                    sc     = score_setup(df, 'SHORT', zone, pq)
                    rr_res = compute_rr(df, 'SHORT', zone, zones)
                    entry, sl, tp, rr = rr_res if rr_res else (closes[-1], None, None, 0.0)
                    return {
                        'strategy': 'Moolah (Double Top)',
                        'signal': 'SHORT',
                        'price': round(closes[-1], 5),
                        'zone': round(zone, 5),
                        'first_touch': round(highs[t1], 5),
                        'second_touch': round(highs[t2], 5),
                        'candles_between': gap,
                        'score': sc,
                        'entry': entry,
                        'stop_loss': sl,
                        'take_profit': tp,
                        'rr_ratio': rr,
                        'details': (
                            f'Moolah | Zona={round(zone, 4)} | '
                            f'1º={round(highs[t1], 4)} 2º={round(highs[t2], 4)} '
                            f'({gap} candles) | Score={sc}/10 | R:R=1:{rr}'
                        ),
                    }

    return None


# ---------------------------------------------------------------------------
# Strategy 4 — Big Belt (Marubozu with gap)  [Chapter 9]
# ---------------------------------------------------------------------------

def check_big_belt(df, cfg):
    """
    Bearish Big Belt: gaps up, opens near high, closes near low — on resistance zone.
    Bullish Big Belt: gaps down, opens near low,  closes near high — on support zone.
    """
    if len(df) < 10:
        return None

    tol       = cfg.get('zone_tolerance_pct', 0.5)
    extremity = cfg.get('close_extremity_pct', 0.25)

    zones = find_zones(df, tolerance_pct=tol)
    if not zones:
        return None

    idx  = len(df) - 1
    belt = df.iloc[idx]
    prev = df.iloc[idx - 1]
    o, h, l, c = belt['Open'], belt['High'], belt['Low'], belt['Close']
    rng = h - l
    if rng == 0:
        return None

    bearish = (
        o > prev['Close'] and
        o >= l + rng * (1 - extremity) and
        c <= l + rng * extremity
    )
    bullish = (
        o < prev['Close'] and
        o <= l + rng * extremity and
        c >= l + rng * (1 - extremity)
    )

    if not bearish and not bullish:
        return None

    signal      = 'LONG' if bullish else 'SHORT'
    check_price = l if bullish else h
    zone        = _nearest_zone(check_price, zones, tolerance_pct=tol * 2)
    if zone is None:
        zone = _nearest_zone(h if bullish else l, zones, tolerance_pct=tol * 2)
    if zone is None:
        return None

    room = _room_to_left(df, idx, check_price, tolerance_pct=tol)

    # Pattern quality: gap size relative to candle range
    gap_pct = abs(o - prev['Close']) / rng * 100 if rng > 0 else 0
    pq = _pattern_quality(gap_pct, [5.0, 10.0, 20.0])

    sc        = score_setup(df, signal, zone, pq)
    rr_result = compute_rr(df, signal, zone, zones)
    entry, sl, tp, rr = rr_result if rr_result else (c, None, None, 0.0)

    return {
        'strategy': 'Big Belt',
        'signal': signal,
        'price': round(c, 5),
        'zone': round(zone, 5),
        'open': round(o, 5),
        'gap': round(abs(o - prev['Close']), 5),
        'room_to_left': room,
        'score': sc,
        'entry': entry,
        'stop_loss': sl,
        'take_profit': tp,
        'rr_ratio': rr,
        'details': (
            f'{"Bullish" if bullish else "Bearish"} Big Belt | '
            f'Zona={round(zone, 4)} | Gap={"↑" if bearish else "↓"}{round(abs(o - prev["Close"]), 4)} | '
            f'Score={sc}/10 | R:R=1:{rr}'
        ),
    }


# ---------------------------------------------------------------------------
# Strategy 5 — Last Kiss (Breakout Retest)  [Chapter 5]
# ---------------------------------------------------------------------------

def check_last_kiss(df, cfg):
    """
    1. Market breaks out beyond a zone.
    2. Market returns to the broken zone for a retest ("last kiss").
    3. Strong candle in the direction of the breakout triggers entry.
    """
    if len(df) < 40:
        return None

    tol   = cfg.get('zone_tolerance_pct', 0.5)
    zones = find_zones(df, tolerance_pct=tol)
    if len(zones) < 2:
        return None

    recent = df.tail(40)
    closes = recent['Close'].values
    highs  = recent['High'].values
    lows   = recent['Low'].values
    n      = len(recent)

    for zone in zones:
        zone_tol = zone * tol / 100

        # --- Bullish Last Kiss ---
        crossed_up = None
        for i in range(n - 5, 5, -1):
            if closes[i] > zone + zone_tol and closes[i - 1] <= zone + zone_tol:
                crossed_up = i
                break

        if crossed_up and crossed_up < n - 2:
            min_low_after = min(lows[crossed_up:])
            if min_low_after <= zone + zone_tol * 2 and closes[-1] > zone:
                last = recent.iloc[-1]
                rng  = last['High'] - last['Low']
                if rng > 0 and last['Close'] >= last['Low'] + rng * 0.6 and last['Close'] > last['Open']:
                    close_pct = (last['Close'] - last['Low']) / rng
                    pq        = _pattern_quality(close_pct, [0.7, 0.8, 0.9])
                    sc        = score_setup(df, 'LONG', zone, pq)
                    rr_res    = compute_rr(df, 'LONG', zone, zones)
                    entry, sl, tp, rr = rr_res if rr_res else (closes[-1], None, None, 0.0)
                    return {
                        'strategy': 'Last Kiss',
                        'signal': 'LONG',
                        'price': round(closes[-1], 5),
                        'zone': round(zone, 5),
                        'score': sc,
                        'entry': entry,
                        'stop_loss': sl,
                        'take_profit': tp,
                        'rr_ratio': rr,
                        'details': (
                            f'Last Kiss Bullish | Zona={round(zone, 4)} | '
                            f'Score={sc}/10 | R:R=1:{rr}'
                        ),
                    }

        # --- Bearish Last Kiss ---
        crossed_dn = None
        for i in range(n - 5, 5, -1):
            if closes[i] < zone - zone_tol and closes[i - 1] >= zone - zone_tol:
                crossed_dn = i
                break

        if crossed_dn and crossed_dn < n - 2:
            max_high_after = max(highs[crossed_dn:])
            if max_high_after >= zone - zone_tol * 2 and closes[-1] < zone:
                last = recent.iloc[-1]
                rng  = last['High'] - last['Low']
                if rng > 0 and last['Close'] <= last['Low'] + rng * 0.4 and last['Close'] < last['Open']:
                    close_pct = (last['High'] - last['Close']) / rng
                    pq        = _pattern_quality(close_pct, [0.7, 0.8, 0.9])
                    sc        = score_setup(df, 'SHORT', zone, pq)
                    rr_res    = compute_rr(df, 'SHORT', zone, zones)
                    entry, sl, tp, rr = rr_res if rr_res else (closes[-1], None, None, 0.0)
                    return {
                        'strategy': 'Last Kiss',
                        'signal': 'SHORT',
                        'price': round(closes[-1], 5),
                        'zone': round(zone, 5),
                        'score': sc,
                        'entry': entry,
                        'stop_loss': sl,
                        'take_profit': tp,
                        'rr_ratio': rr,
                        'details': (
                            f'Last Kiss Bearish | Zona={round(zone, 4)} | '
                            f'Score={sc}/10 | R:R=1:{rr}'
                        ),
                    }

    return None


# ---------------------------------------------------------------------------
# Strategy 6 — Trendy Kangaroo  [Chapter 10]
# ---------------------------------------------------------------------------

def check_trendy_kangaroo(df, cfg):
    """
    Kangaroo tail during a trending market, printed after a short market pause.
    The tail must stick OUT beyond the consolidation range.
    """
    if len(df) < 50:
        return None

    tol                  = cfg.get('zone_tolerance_pct', 0.5)
    tail_ratio           = cfg.get('min_tail_body_ratio', 2.0)
    min_pause            = cfg.get('min_pause_candles', 3)
    max_pause            = cfg.get('max_pause_candles', 12)
    max_consolidation_pct = cfg.get('max_consolidation_pct', 1.0)

    closes = df['Close'].values
    ema21  = pd.Series(closes).ewm(span=21).mean().values
    ema50  = pd.Series(closes).ewm(span=50).mean().values

    uptrend   = ema21[-1] > ema50[-1] and ema21[-10] > ema50[-10]
    downtrend = ema21[-1] < ema50[-1] and ema21[-10] < ema50[-10]

    if not uptrend and not downtrend:
        return None

    recent_highs = df['High'].values[-30:]
    recent_lows  = df['Low'].values[-30:]

    for pause_len in range(min_pause, max_pause + 1):
        pause_start = len(recent_highs) - 1 - pause_len
        pause_end   = len(recent_highs) - 1

        if pause_start < 0:
            continue

        ph  = max(recent_highs[pause_start:pause_end])
        pl  = min(recent_lows[pause_start:pause_end])
        avg = (ph + pl) / 2

        if avg == 0 or (ph - pl) / avg * 100 > max_consolidation_pct:
            continue

        t_c = df.iloc[-1]
        to, th, tl, tc = t_c['Open'], t_c['High'], t_c['Low'], t_c['Close']
        trng = th - tl
        if trng == 0:
            continue

        body_high = max(to, tc)
        body_low  = min(to, tc)
        body_size = max(body_high - body_low, trng * 0.005)

        if uptrend:
            sticks_out = tl < pl
            body_top   = body_low >= tl + trng * 2 / 3
            tail_ok    = (body_low - tl) >= tail_ratio * body_size
            if sticks_out and body_top and tail_ok:
                actual_ratio = (body_low - tl) / body_size
                pq           = _pattern_quality(actual_ratio, [3.0, 4.0, 5.0])
                # Use consolidation low as quasi-zone level for scoring/RR
                zones        = find_zones(df, tolerance_pct=tol)
                sc           = score_setup(df, 'LONG', pl, pq)
                rr_res       = compute_rr(df, 'LONG', pl, zones or [pl * 0.995])
                entry, sl, tp, rr = rr_res if rr_res else (tc, None, None, 0.0)
                return {
                    'strategy': 'Trendy Kangaroo',
                    'signal': 'LONG',
                    'price': round(tc, 5),
                    'trend': 'Uptrend (EMA21 > EMA50)',
                    'pause_range': f'{round(pl, 4)} - {round(ph, 4)}',
                    'tail_low': round(tl, 5),
                    'score': sc,
                    'entry': entry,
                    'stop_loss': sl,
                    'take_profit': tp,
                    'rr_ratio': rr,
                    'details': (
                        f'Trendy Kangaroo Bullish | Uptrend | '
                        f'Pausa={round(pl, 4)}-{round(ph, 4)} | '
                        f'Tail={round(tl, 4)} | Score={sc}/10 | R:R=1:{rr}'
                    ),
                }

        if downtrend:
            sticks_out  = th > ph
            body_bottom = body_high <= tl + trng * 1 / 3
            tail_ok     = (th - body_high) >= tail_ratio * body_size
            if sticks_out and body_bottom and tail_ok:
                actual_ratio = (th - body_high) / body_size
                pq           = _pattern_quality(actual_ratio, [3.0, 4.0, 5.0])
                zones        = find_zones(df, tolerance_pct=tol)
                sc           = score_setup(df, 'SHORT', ph, pq)
                rr_res       = compute_rr(df, 'SHORT', ph, zones or [ph * 1.005])
                entry, sl, tp, rr = rr_res if rr_res else (tc, None, None, 0.0)
                return {
                    'strategy': 'Trendy Kangaroo',
                    'signal': 'SHORT',
                    'price': round(tc, 5),
                    'trend': 'Downtrend (EMA21 < EMA50)',
                    'pause_range': f'{round(pl, 4)} - {round(ph, 4)}',
                    'tail_high': round(th, 5),
                    'score': sc,
                    'entry': entry,
                    'stop_loss': sl,
                    'take_profit': tp,
                    'rr_ratio': rr,
                    'details': (
                        f'Trendy Kangaroo Bearish | Downtrend | '
                        f'Pausa={round(pl, 4)}-{round(ph, 4)} | '
                        f'Tail={round(th, 4)} | Score={sc}/10 | R:R=1:{rr}'
                    ),
                }

    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

_STRATEGY_MAP = {
    'kangaroo_tail':   check_kangaroo_tail,
    'big_shadow':      check_big_shadow,
    'wammie_moolah':   check_wammie_moolah,
    'big_belt':        check_big_belt,
    'last_kiss':       check_last_kiss,
    'trendy_kangaroo': check_trendy_kangaroo,
}


def check_naked_forex_strategies(df, strategies_cfg):
    results = []
    for name, cfg in strategies_cfg.items():
        if not cfg.get('enabled', True):
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
