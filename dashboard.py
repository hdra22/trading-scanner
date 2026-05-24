"""
Trading Scanner Dashboard — Streamlit
Run: streamlit run dashboard.py
"""
import subprocess
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st
import pandas as pd

from results_store import load_history
from notifier import _tv_url, _fmt_price

# ─────────────────────────────────────────────
# Page setup
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Trading Scanner",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
    /* tighten default padding */
    .block-container { padding-top: 1.5rem; padding-bottom: 1rem; }
    /* signal badges */
    .badge-long  { background:#1a6b3c; color:#fff; padding:2px 10px;
                   border-radius:12px; font-size:.82rem; font-weight:600; }
    .badge-short { background:#9e2020; color:#fff; padding:2px 10px;
                   border-radius:12px; font-size:.82rem; font-weight:600; }
    /* metric delta colours */
    [data-testid="stMetricDelta"] { font-size:.78rem; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Data helpers
# ─────────────────────────────────────────────
def _next_run(ts: datetime) -> datetime:
    """Return next scheduled run (every 4 h at :05) after ts."""
    base = ts.replace(minute=5, second=0, microsecond=0)
    while base <= ts:
        base += timedelta(hours=4)
    return base


def _build_df(results: list) -> pd.DataFrame:
    rows = []
    for r in results:
        rows.append({
            "Ativo":      r.get("display_name", r.get("symbol", "")),
            "TF":         r.get("timeframe", ""),
            "Estratégia": r.get("strategy", ""),
            "Sinal":      r.get("signal", ""),
            "⭐":          r.get("score", 0),
            "⚖️ R:R":      f"1:{r.get('rr_ratio', 0):.1f}" if r.get("rr_ratio") else "—",
            "➤ Entrada":  _fmt_price(r.get("entry")),
            "🛑 SL":       _fmt_price(r.get("stop_loss")),
            "🎯 TP":       _fmt_price(r.get("take_profit")),
            "_rr_raw":    r.get("rr_ratio", 0),
            "_symbol":    r.get("symbol", ""),
            "_tf":        r.get("timeframe", ""),
        })
    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ─────────────────────────────────────────────
# Load data
# ─────────────────────────────────────────────
history = load_history()
latest  = history[-1] if history else None

# ─────────────────────────────────────────────
# Header row
# ─────────────────────────────────────────────
title_col, btn_col = st.columns([8, 2])
title_col.title("📊 Trading Scanner")

with btn_col:
    bc1, bc2 = st.columns(2)
    if bc1.button("▶ Scan Now", use_container_width=True, type="primary"):
        scanner_py = Path(__file__).parent / "scanner.py"
        subprocess.Popen(
            [sys.executable, "-X", "utf8", str(scanner_py)],
            cwd=str(scanner_py.parent),
        )
        st.toast("⏳ Scan iniciado — clica em Refresh em ~25 segundos", icon="🚀")
    if bc2.button("🔄 Refresh", use_container_width=True):
        st.rerun()

st.divider()

# ─────────────────────────────────────────────
# Status bar
# ─────────────────────────────────────────────
if latest:
    ts_last = datetime.fromisoformat(latest["timestamp"])
    ts_next = _next_run(ts_last)
    mins_ago = int((datetime.now() - ts_last).total_seconds() / 60)
    ago_str  = f"{mins_ago}m atrás" if mins_ago < 60 else f"{mins_ago//60}h{mins_ago%60:02d}m atrás"

    st.markdown(
        f"🕐 **Último scan:** {ts_last.strftime('%d/%m/%Y %H:%M')} ({ago_str})"
        f"&ensp;|&ensp;⏳ **Próximo:** {ts_next.strftime('%H:%M')}"
        f"&ensp;|&ensp;⏱ {latest.get('elapsed', '?'):.0f}s"
        f"&ensp;|&ensp;📂 {latest['n_symbols']} ativos"
        f"&ensp;|&ensp;TF: {', '.join(latest['timeframes'])}"
    )
else:
    st.info("Nenhum scan encontrado. Clica em **▶ Scan Now** para correr o primeiro scan.", icon="ℹ️")

# ─────────────────────────────────────────────
# Metric cards
# ─────────────────────────────────────────────
if latest:
    results  = latest["results"]
    longs    = [r for r in results if r.get("signal") == "LONG"]
    shorts   = [r for r in results if r.get("signal") == "SHORT"]
    scores   = [r.get("score", 0) for r in results]
    rrs      = [r.get("rr_ratio", 0) for r in results if r.get("rr_ratio", 0) > 0]

    # Delta vs previous scan
    prev_approved = history[-2]["total_approved"] if len(history) >= 2 else None

    st.markdown("&nbsp;")
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric(
        "Setups aprovados",
        len(results),
        delta=len(results) - prev_approved if prev_approved is not None else None,
    )
    m2.metric("📈 LONG",  len(longs))
    m3.metric("📉 SHORT", len(shorts))
    m4.metric("⭐ Score médio",  f"{sum(scores)/len(scores):.1f}" if scores else "—")
    m5.metric("⚖️ R:R médio",    f"1:{sum(rrs)/len(rrs):.1f}"    if rrs    else "—")
    m6.metric("Brutos analisados", latest.get("total_raw", "—"))

    st.divider()

    # ─────────────────────────────────────────
    # Filters (inline row)
    # ─────────────────────────────────────────
    all_strats = sorted({r.get("strategy", "") for r in results})
    all_tfs    = sorted({r.get("timeframe", "") for r in results})

    f1, f2, f3, f4 = st.columns([2, 2, 3, 2])
    filt_sig   = f1.selectbox("Sinal",        ["Todos", "📈 LONG", "📉 SHORT"], label_visibility="collapsed")
    filt_tf    = f2.multiselect("Timeframe",  all_tfs,    default=all_tfs,    placeholder="Timeframe",    label_visibility="collapsed")
    filt_strat = f3.multiselect("Estratégia", all_strats, default=all_strats, placeholder="Estratégia",   label_visibility="collapsed")
    filt_score = f4.slider("Score mín.", 0, 10, 8, label_visibility="collapsed")

    sig_map = {"Todos": None, "📈 LONG": "LONG", "📉 SHORT": "SHORT"}
    sig_filter = sig_map[filt_sig]

    filtered = [
        r for r in results
        if (sig_filter is None or r.get("signal") == sig_filter)
        and r.get("timeframe") in filt_tf
        and r.get("strategy") in filt_strat
        and r.get("score", 0) >= filt_score
    ]

    # ─────────────────────────────────────────
    # Results table
    # ─────────────────────────────────────────
    st.subheader(f"Setups — {len(filtered)} resultado(s)")

    if filtered:
        # Sort: score desc, then rr desc
        filtered_sorted = sorted(
            filtered,
            key=lambda r: (-r.get("score", 0), -r.get("rr_ratio", 0)),
        )

        rows = []
        for r in filtered_sorted:
            tv = _tv_url(r.get("symbol", ""), r.get("timeframe", "")) or ""
            sinal = "📈 LONG" if r.get("signal") == "LONG" else "📉 SHORT"
            rows.append({
                "Ativo":      r.get("display_name", r.get("symbol", "")),
                "TF":         r.get("timeframe", ""),
                "Estratégia": r.get("strategy", ""),
                "Sinal":      sinal,
                "⭐ Score":   r.get("score", 0),
                "⚖️ R:R":     f"1:{r.get('rr_ratio', 0):.1f}" if r.get("rr_ratio") else "—",
                "➤ Entrada":  _fmt_price(r.get("entry")),
                "🛑 SL":       _fmt_price(r.get("stop_loss")),
                "🎯 TP":       _fmt_price(r.get("take_profit")),
                "📊 Chart":   tv,
            })

        df = pd.DataFrame(rows)
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            height=min(38 + len(rows) * 38, 600),
            column_config={
                "Ativo":      st.column_config.TextColumn(width="medium"),
                "TF":         st.column_config.TextColumn(width="small"),
                "Estratégia": st.column_config.TextColumn(width="medium"),
                "Sinal":      st.column_config.TextColumn(width="small"),
                "⭐ Score":   st.column_config.NumberColumn(
                                  format="%d /10", width="small",
                              ),
                "⚖️ R:R":     st.column_config.TextColumn(width="small"),
                "➤ Entrada":  st.column_config.TextColumn(width="small"),
                "🛑 SL":      st.column_config.TextColumn(width="small"),
                "🎯 TP":      st.column_config.TextColumn(width="small"),
                "📊 Chart":   st.column_config.LinkColumn(
                                  "📊 Chart",
                                  display_text="Abrir ↗",
                                  width="small",
                              ),
            },
        )
    else:
        st.info("Nenhum setup com os filtros seleccionados.")

    st.divider()

# ─────────────────────────────────────────────
# History section
# ─────────────────────────────────────────────
if len(history) >= 2:
    st.subheader("📈 Histórico de Scans")

    hist_rows = []
    for scan in history[-40:]:          # last 40 scans
        ts = datetime.fromisoformat(scan["timestamp"])
        hist_rows.append({
            "Data/Hora":  ts.strftime("%d/%m %H:%M"),
            "Aprovados":  scan["total_approved"],
            "LONG":       sum(1 for r in scan["results"] if r.get("signal") == "LONG"),
            "SHORT":      sum(1 for r in scan["results"] if r.get("signal") == "SHORT"),
            "Brutos":     scan.get("total_raw", 0),
        })

    hist_df = pd.DataFrame(hist_rows).set_index("Data/Hora")

    tab1, tab2 = st.tabs(["LONG / SHORT por scan", "Brutos vs Aprovados"])

    with tab1:
        st.bar_chart(
            hist_df[["LONG", "SHORT"]],
            color=["#1a6b3c", "#9e2020"],
            use_container_width=True,
            height=280,
        )
    with tab2:
        st.line_chart(
            hist_df[["Brutos", "Aprovados"]],
            color=["#4a90d9", "#f5a623"],
            use_container_width=True,
            height=280,
        )

    # Summary stats across all history
    st.divider()
    st.subheader("📋 Estatísticas Globais")
    all_results_flat = [r for scan in history for r in scan["results"]]
    if all_results_flat:
        from collections import Counter
        strat_count = Counter(r.get("strategy") for r in all_results_flat)
        sym_count   = Counter(r.get("display_name", r.get("symbol")) for r in all_results_flat)

        sc1, sc2 = st.columns(2)
        with sc1:
            st.markdown("**Estratégias mais frequentes**")
            strat_df = pd.DataFrame(
                strat_count.most_common(10),
                columns=["Estratégia", "Aparições"],
            )
            st.dataframe(strat_df, hide_index=True, use_container_width=True, height=200)

        with sc2:
            st.markdown("**Ativos mais frequentes**")
            sym_df = pd.DataFrame(
                sym_count.most_common(10),
                columns=["Ativo", "Aparições"],
            )
            st.dataframe(sym_df, hide_index=True, use_container_width=True, height=200)

elif history:
    st.info("Corre mais um scan para ver o histórico de evolução.", icon="ℹ️")

# ─────────────────────────────────────────────
# Footer
# ─────────────────────────────────────────────
st.divider()
st.caption(
    f"Página carregada às {datetime.now().strftime('%H:%M:%S')}  ·  "
    f"{len(history)} scan(s) no histórico  ·  "
    "Trading Scanner v1.0"
)
