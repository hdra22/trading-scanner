# 📊 Trading Scanner

Scanner automático de setups de trading com alertas Telegram, dashboard web e comandos via bot.

---

## Índice

1. [Arquitectura](#arquitectura)
2. [Como funciona](#como-funciona)
3. [Ficheiros](#ficheiros)
4. [Estratégias](#estratégias)
5. [Sistema de Score](#sistema-de-score)
6. [Cálculo de R:R](#cálculo-de-rr)
7. [Adicionar ativos](#adicionar-ativos)
8. [Adicionar timeframes](#adicionar-timeframes)
9. [Adicionar estratégias](#adicionar-estratégias)
10. [Filtros de qualidade](#filtros-de-qualidade)
11. [Referência do config.json](#referência-do-configjson)
12. [Comandos Telegram](#comandos-telegram)
13. [Dashboard](#dashboard)
14. [Credenciais e Secrets](#credenciais-e-secrets)
15. [Manutenção](#manutenção)

---

## Arquitectura

```
┌─────────────────────────────────────────────────────────────┐
│  GitHub Actions (cloud — não precisa PC ligado)             │
│  • Corre de 4 em 4 horas (ou manual via /scan)              │
│  • scanner.py → analisa todos os ativos e timeframes        │
│  • Envia resultados ao Telegram                             │
│  • Commita scan_history.json de volta ao repo               │
└──────────────────────┬──────────────────────────────────────┘
                       │ git push
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  GitHub Repo (hdra22/trading-scanner)                       │
│  • Código fonte                                             │
│  • scan_history.json (histórico dos últimos 60 scans)       │
└──────────┬──────────────────────────────────────────────────┘
           │ auto-deploy on push
           ▼
┌─────────────────────────────────────────────────────────────┐
│  Streamlit Community Cloud                                  │
│  • Dashboard web acessível no telemóvel                     │
│  • hdra22-trading-scanner-dashboard-wgbqya.streamlit.app    │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  Telegram Bot  ←→  Vercel Webhook                           │
│  • /scan → dispara GitHub Actions via API                   │
│  • /help → mostra comandos                                  │
│  Webhook URL: trading-scanner-alpha.vercel.app/webhook      │
└─────────────────────────────────────────────────────────────┘
```

---

## Como funciona

### Fluxo completo de um scan

```
1. Trigger (schedule ou /scan)
        │
2. Fetch de dados — yfinance (OHLCV)
        │
3. Para cada (ativo × timeframe):
   ├── check_all_strategies()          ← estratégias clássicas
   └── check_naked_forex_strategies()  ← estratégias Naked Forex
        │
4. Cada estratégia devolve:
   ├── signal: LONG | SHORT
   ├── score: 0–10
   ├── entry, stop_loss, take_profit
   └── rr_ratio
        │
5. Filtro de qualidade
   ├── score >= 8
   └── rr_ratio >= 2.0
        │
6. Envio ao Telegram (notifier.py)
        │
7. Guardar histórico (results_store.py → scan_history.json)
        │
8. Git push do scan_history.json → Streamlit Cloud actualiza
```

### Horários automáticos (hora de Portugal)

| Hora PT | Hora UTC |
|---------|----------|
| 00:05   | 23:05    |
| 04:05   | 03:05    |
| 08:05   | 07:05    |
| 12:05   | 11:05    |
| 16:05   | 15:05    |
| 20:05   | 19:05    |

---

## Ficheiros

| Ficheiro | Descrição |
|----------|-----------|
| `scanner.py` | Ponto de entrada. Coordena fetch de dados, execução de estratégias, filtros e envio |
| `strategies.py` | Estratégias clássicas (RSI Oversold, EMA Pullback, MACD Cross) |
| `naked_forex_strategies.py` | Estratégias Naked Forex (Kangaroo Tail, Big Shadow, Wammie/Moolah, Big Belt, Last Kiss, Trendy Kangaroo). Contém também as funções `find_zones`, `score_setup`, `compute_rr` |
| `notifier.py` | Formatação e envio de mensagens Telegram. Inclui mapeamento de símbolos para TradingView |
| `results_store.py` | Leitura/escrita do `scan_history.json` |
| `dashboard.py` | Dashboard Streamlit (local e cloud) |
| `config.json` | Toda a configuração: watchlist, timeframes, estratégias, filtros |
| `api/webhook.py` | Serverless function Vercel — recebe comandos do Telegram |
| `.github/workflows/scanner.yml` | Workflow GitHub Actions |

---

## Estratégias

### Clássicas (`strategies.py`)

#### RSI Oversold / Overbought
- **LONG**: RSI < 35 → mercado sobrevendido, potencial reversão para cima
- **SHORT**: RSI > 65 → mercado sobrecomprado, potencial reversão para baixo
- Parâmetros em `config.json → classic_strategies.rsi_oversold`:
  - `rsi_period` (default: 14)
  - `rsi_long_threshold` (default: 35)
  - `rsi_short_threshold` (default: 65)

#### EMA Pullback
- Tendência definida por EMA21 > EMA50 (LONG) ou EMA21 < EMA50 (SHORT)
- Setup: preço recua até à EMA21/50 e dá sinal de retoma
- Parâmetros: `ema_fast` (21), `ema_slow` (50), `proximity_pct` (1.5%)

#### MACD Cross
- **LONG**: linha MACD cruza acima da linha de sinal
- **SHORT**: linha MACD cruza abaixo da linha de sinal
- Parâmetros: `fast` (12), `slow` (26), `signal` (9)

---

### Naked Forex (`naked_forex_strategies.py`)

Todas as estratégias Naked Forex baseiam-se em **zonas de suporte/resistência** identificadas automaticamente por concentração de pivots nos últimos 150 barras.

#### Kangaroo Tail (Cauda de Canguru)
- Pavio longo (≥ 2× o corpo) que toca uma zona
- **LONG**: pavio para baixo numa zona de suporte
- **SHORT**: pavio para cima numa zona de resistência

#### Big Shadow (Vela Sombra Grande)
- Vela exterior que engloba a anterior e fecha perto do extremo
- Sinal de reversão forte numa zona

#### Wammie / Moolah (Double Bottom / Double Top)
- **Wammie (LONG)**: dois mínimos próximos de uma zona de suporte (double bottom)
- **Moolah (SHORT)**: dois máximos próximos de uma zona de resistência (double top)
- Mínimo de 6 velas entre os dois toques

#### Big Belt (Vela Marubozu)
- Vela de corpo grande sem pavio (ou pavio muito pequeno) numa zona
- **LONG**: vela de alta que fecha no máximo
- **SHORT**: vela de baixa que fecha no mínimo

#### Last Kiss (Último Beijo)
- Preço rompe uma zona, recua para a testar de novo (pullback) e retoma
- O reteste valida a zona como novo suporte/resistência

#### Trendy Kangaroo
- Variante do Kangaroo Tail em contexto de tendência
- Exige pausa de consolidação (3–12 velas) antes do pavio

---

## Sistema de Score

Cada setup recebe uma pontuação de **0 a 10** composta por 4 componentes:

| Componente | Pontos | Critério |
|------------|--------|----------|
| **Qualidade do padrão** | 1–4 | Específico de cada estratégia (ex: tamanho do pavio, força do corpo) |
| **Toques na zona** | 0–2 | ≥ 4 toques → +2 pts; ≥ 3 toques → +1 pt |
| **Alinhamento EMA21/50** | 0–2 | EMA21 > EMA50 para LONG (e vice-versa) → +2 pts |
| **Confirmação RSI** | 0–2 | LONG: RSI < 40 → +2; RSI < 50 → +1 / SHORT: RSI > 60 → +2; RSI > 50 → +1 |

**Filtro activo**: apenas setups com score ≥ 8 são enviados.

---

## Cálculo de R:R

```
LONG:
  Entry   = Close da vela actual
  SL      = min(zona - 0.5%, Low da vela)
  Risk    = Entry - SL
  TP      = zona mais próxima que garanta Reward ≥ 2.0 × Risk

SHORT:
  Entry   = Close da vela actual
  SL      = max(zona + 0.5%, High da vela)
  Risk    = SL - Entry
  TP      = zona mais próxima que garanta Reward ≥ 2.0 × Risk
```

- A pesquisa de zonas para TP usa lookback de **300 barras** (mais alcance)
- **Filtro activo**: apenas setups com R:R ≥ 2.0 são enviados (nunca inferior a 1:2)

---

## Adicionar ativos

Edita `config.json`:

```json
"watchlist": [
  "EURUSD=X",
  "AAPL",          ← acção americana
  "BTC-USD",       ← cripto
  "GC=F",          ← futures ouro
  "^GSPC"          ← índice S&P 500
],
"symbol_names": {
  "AAPL": "Apple (AAPL)"
}
```

### Formatos de símbolo (yfinance)

| Tipo | Formato | Exemplo |
|------|---------|---------|
| Forex | `XXXYYY=X` | `EURUSD=X`, `GBPJPY=X` |
| Cripto | `XXX-USD` | `BTC-USD`, `SOL-USD` |
| Acções EUA | Ticker directo | `AAPL`, `MSFT`, `TSLA` |
| Acções BR | `XXXX.SA` | `PETR4.SA`, `VALE3.SA` |
| Futures | `XX=F` | `GC=F` (ouro), `CL=F` (petróleo), `ES=F` (S&P fut.) |
| Índices | `^XXXX` | `^GSPC`, `^FTSE`, `^GDAXI` |

### Adicionar link TradingView para novo ativo

Se o ativo não é Forex (auto-derivado), adiciona em `notifier.py → _TV_SYMBOL_MAP`:

```python
_TV_SYMBOL_MAP = {
    "AAPL":   "NASDAQ:AAPL",
    "ES=F":   "CME_MINI:ES1!",
    # ...
}
```

---

## Adicionar timeframes

Em `config.json`:

```json
"timeframes": ["4h", "1d", "1h"]
```

Timeframes suportados e dados disponíveis:

| Timeframe | Período de dados |
|-----------|-----------------|
| `1m`  | 7 dias |
| `5m`  | 60 dias |
| `15m` | 60 dias |
| `30m` | 60 dias |
| `1h`  | 730 dias (~2 anos) |
| `4h`  | 730 dias (~2 anos) |
| `1d`  | 5 anos |

> ⚠️ Adicionar mais timeframes aumenta o tempo de scan. Com 47 ativos × 3 TFs o scan leva ~20–25s.

---

## Adicionar estratégias

### Estratégia clássica (`strategies.py`)

```python
def check_minha_estrategia(df: pd.DataFrame, cfg: dict):
    results = []
    # ... lógica ...

    # Calcular score e R:R (obrigatório)
    pq     = _pattern_quality(valor, [limiar1, limiar2, limiar3])
    score  = score_setup(df, signal, zone_level, pq)
    rr_out = compute_rr(df, signal, zone_level, all_zones)

    if rr_out:
        entry, sl, tp, rr = rr_out
    else:
        entry, sl, tp, rr = close, None, None, 0.0

    results.append({
        "strategy":   "Minha Estratégia",
        "signal":     signal,       # "LONG" ou "SHORT"
        "score":      score,
        "rr_ratio":   rr,
        "entry":      entry,
        "stop_loss":  sl,
        "take_profit": tp,
    })
    return results
```

Depois registar em `check_all_strategies()` no mesmo ficheiro, e adicionar os parâmetros em `config.json → classic_strategies`.

### Estratégia Naked Forex (`naked_forex_strategies.py`)

Mesma estrutura, mas registar em `check_naked_forex_strategies()` e em `config.json → naked_forex_strategies`.

---

## Filtros de qualidade

Em `config.json`:

```json
"filters": {
  "min_score": 8,    ← mínimo de score (0–10)
  "min_rr": 2.0      ← mínimo de R:R (ex: 2.0 = 1:2)
}
```

Para receber mais alertas (menos exigente): reduz `min_score` para 7 ou `min_rr` para 1.5.  
Para receber só os melhores: aumenta `min_score` para 9.

---

## Referência do config.json

```jsonc
{
  "telegram": {
    "token":   "...",   // token do bot (@BotFather)
    "chat_id": "..."    // o teu chat ID
  },
  "watchlist":    [...],  // lista de símbolos yfinance
  "symbol_names": {...},  // nomes para exibição (opcional por símbolo)
  "timeframes":   [...],  // ex: ["4h", "1d"]
  "filters": {
    "min_score": 8,       // 0–10
    "min_rr":    2.0      // ex: 2.0 = 1:2
  },
  "classic_strategies": {
    "rsi_oversold":  { "enabled": true, ... },
    "ema_pullback":  { "enabled": true, ... },
    "macd_cross":    { "enabled": true, ... }
  },
  "naked_forex_strategies": {
    "kangaroo_tail":  { "enabled": true, ... },
    "big_shadow":     { "enabled": true, ... },
    "wammie_moolah":  { "enabled": true, ... },
    "big_belt":       { "enabled": true, ... },
    "last_kiss":      { "enabled": true, ... },
    "trendy_kangaroo":{ "enabled": true, ... }
  }
}
```

Para **desactivar** uma estratégia sem a apagar: `"enabled": false`.

---

## Comandos Telegram

| Comando | Acção |
|---------|-------|
| `/scan` | Dispara um scan imediatamente (resultado em ~2 min) |
| `/help` | Mostra os comandos disponíveis |

O bot só responde ao teu Chat ID (`776402509`). Mensagens de outros utilizadores são ignoradas.

---

## Dashboard

**URL**: `https://hdra22-trading-scanner-dashboard-wgbqya.streamlit.app`

Funcionalidades:
- Últimos setups com entry / SL / TP e link TradingView
- Filtros por sinal (LONG/SHORT), timeframe, estratégia e score mínimo
- Histórico dos últimos 60 scans em gráfico
- Estatísticas globais (estratégias e ativos mais frequentes)
- Botão **▶ Scan Now** (dispara GitHub Actions)
- Botão **🔄 Refresh** (recarrega dados)

> O dashboard actualiza automaticamente após cada scan (~1–2 min de delay).

---

## Credenciais e Secrets

### GitHub Secrets (`hdra22/trading-scanner → Settings → Secrets`)
| Secret | Descrição |
|--------|-----------|
| `TELEGRAM_TOKEN` | Token do bot Telegram |
| `TELEGRAM_CHAT_ID` | O teu Chat ID no Telegram |

### Vercel Environment Variables (`trading-scanner → Settings → Environment Variables`)
| Variável | Descrição |
|----------|-----------|
| `TELEGRAM_TOKEN` | Token do bot Telegram |
| `TELEGRAM_CHAT_ID` | O teu Chat ID |
| `GITHUB_PAT` | Personal Access Token GitHub (scope: workflow) |

### Streamlit Cloud Secrets (`App → Settings → Secrets`)
```toml
GITHUB_PAT = "ghp_..."   # mesmo token do Vercel
```

---

## Manutenção

### Correr localmente
```bash
cd C:\Users\arauj\trading-scanner
pip install -r requirements.txt
python scanner.py

# Dashboard local
python -m streamlit run dashboard.py
# ou usar o run_dashboard.bat
```

### Forçar scan manual
- Telegram: enviar `/scan` ao bot
- GitHub: `Actions → Trading Scanner → Run workflow`
- Dashboard: clicar **▶ Scan Now**

### Ver logs de um scan
```
https://github.com/hdra22/trading-scanner/actions
```

### Actualizar a watchlist ou parâmetros
1. Editar `config.json` localmente
2. `git add config.json && git commit -m "..." && git push`
3. O próximo scan usa já a nova configuração

### O dashboard mostra dados antigos
O Streamlit Cloud pode demorar 1–2 minutos a detectar o novo commit. Clica **🔄 Refresh** ou aguarda.

### Rotação do GITHUB_PAT (expira em 1 ano)
1. Gerar novo PAT em `github.com/settings/tokens`
2. Actualizar em Vercel → Environment Variables → `GITHUB_PAT`
3. Actualizar em Streamlit Cloud → Secrets → `GITHUB_PAT`

---

*Última actualização: Junho 2026*
