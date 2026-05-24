"""
Persists scan results to scan_history.json so the dashboard can read them.
"""
import json
import os
from datetime import datetime

_HERE         = os.path.dirname(os.path.abspath(__file__))
RESULTS_FILE  = os.path.join(_HERE, "scan_history.json")
MAX_SCANS     = 60   # keep last 60 scans (~10 days at 4 h/scan)


def save_scan(results, n_symbols, timeframes, elapsed, total_raw):
    """Append a completed scan to the history file."""
    history = load_history()

    # Keep only JSON-serialisable scalar fields from each result dict
    serialisable = []
    for r in results:
        serialisable.append({
            k: v for k, v in r.items()
            if isinstance(v, (str, int, float, bool, type(None)))
        })

    history.append({
        "timestamp":      datetime.now().isoformat(),
        "n_symbols":      n_symbols,
        "timeframes":     list(timeframes),
        "elapsed":        round(float(elapsed), 1),
        "total_raw":      int(total_raw),
        "total_approved": len(results),
        "results":        serialisable,
    })

    # Trim to max
    if len(history) > MAX_SCANS:
        history = history[-MAX_SCANS:]

    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def load_history():
    """Return the full list of past scans (oldest first)."""
    if not os.path.exists(RESULTS_FILE):
        return []
    try:
        with open(RESULTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def load_latest():
    """Return the most recent scan dict, or None."""
    h = load_history()
    return h[-1] if h else None
