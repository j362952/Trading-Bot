# TradingBot

Trades according to adaptable, empirically grounded strategies: controlled from a
GUI, protected by its own risk-management layer, and running either against the
built-in simulation (PaperBroker) or Interactive Brokers (paper/live via TWS/IB Gateway).

The trading and risk methodology is documented in [STRATEGIE.md](STRATEGIE.md)
(German); it is also the basis for further development.

## Getting started

```bash
cd App
uv run bot_gui.py            # GUI with all four pages (recommended)

# open individual pages on their own (independent of each other)
uv run gui_1_daten.py             # page 1: Data (hub, fetches)
uv run gui_2_tradebot.py          # page 2: TradeBot (profile "live")
uv run gui_3_valuescreener.py     # page 3: ValueScreener
uv run gui_4_backtest.py          # page 4: Backtest (profile "test")

# CLI tools
uv run run_backtests.py beispiel   # all strategies over a watchlist
uv run run_validation.py           # robustness harness (random windows)
uv run main.py SPY                 # single backtest SMA vs. buy & hold
uv run news.py AAPL NOVN.SW        # news sentiment (FinBERT)
uv run news.py AAPL --backend claude   # … with Claude (incl. reasoning)
uv run run_sentiment_eval.py run   # measure FinBERT vs. Claude (evals/README.md)
uv run mcp_server.py               # MCP server for Claude (see below)
uv run python -m unittest discover -s tests   # tests
```

## Claude integration

Two building blocks, both optional: without an Anthropic API key everything runs as before.

### 1. MCP server: ask Claude about the bot

`mcp_server.py` exposes the data hub, price cache, news archive and bot log as
[MCP](https://modelcontextprotocol.io) tools. This lets you ask questions in
Claude Desktop or Claude Code such as *"Why did MoQu pick exactly these stocks this
month?"*, *"Would the sentiment gate block SAP right now?"* or *"Which DAX
stocks have the highest operating margin?"*.

| Tool | Returns |
|---|---|
| `data_overview` | Tables/columns of both DBs, universes, data freshness, recent fetch errors |
| `run_sql` | One read-only SQL query against hub.db or bot.db |
| `company_profile` | Master data, quarterly figures, TTM ROE/margin/growth, price statistics, screener scores |
| `price_history` | Price series (D/W/M) with return, volatility, max drawdown |
| `moqu_ranking` | MoQu selection as of a given date with every ranking component per stock, plus excluded stocks with the reason |
| `news_sentiment` | Headlines with FinBERT and Claude scores, gate threshold |
| `bot_activity` | Decision log, orders, equity, stops, relevant settings (without keys) |

MoQu is the main strategy: volatility-adjusted momentum combined with a quality score.

**Read-only by design:** databases are opened read-only, `run_sql` only allows read
operations via a SQLite authorizer (with time and row limits), and prices come only
from the local cache. The server can neither trade nor change settings. `moqu_ranking`
uses the same formulas and parameters as the strategy; a test
(`tests/test_mcp_tools.py`) checks that the selection matches exactly on rebalance days.

Setup for Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "tradingbot": {
      "command": "uv",
      "args": ["--directory", "C:\\SW\\TradingBot\\App", "run", "mcp_server.py"]
    }
  }
}
```

Claude Code: `claude mcp add tradingbot -- uv --directory C:\SW\TradingBot\App run mcp_server.py`

### 2. Claude as sentiment model (alternative to FinBERT)

Gear icon → *Sentiment & Makro* → model `claude`, key under *API-Keys*
(or environment variable `ANTHROPIC_API_KEY`). Differences from FinBERT:

- rates **relative to the company**: headlines that are not about the stock at all
  (common in the Yahoo feed) count as neutral instead of distorting the sentiment
- returns a **short reason** per headline: when the gate blocks an entry, the
  triggering headline and its reason are written to the decision log
- structured output via a forced tool call (JSON schema), headlines wrapped as
  untrusted input, every response validated
- **falls back to FinBERT automatically on errors** (missing key, API unreachable),
  so the gate stays armed instead of silently staying open
- separate score cache (`data_cache/news_scores_claude/`); each headline is rated only once

Which model is better is measured by `run_sentiment_eval.py` on hand-labeled
headlines (accuracy, macro-F1, negative headlines caught, false blocks, token usage).
Instructions and labeling rules: [evals/README.md](evals/README.md).

## GUI quick guide (one GUI, four pages; see GUI_KONZEPT.md)

1. **Data**: overview of all APIs (which source provides what, configuration,
   last successful delivery/last error as a traffic light), state of the hub
   (coverage, freshness indicators, macro mini-charts, fetch errors) and
   **manual fetch buttons for every category**: EOD prices, current prices,
   fundamentals, FRED macro, earnings, event calendar, corporate actions,
   news archive, intraday, universe snapshot.
2. **TradeBot** (profile "live"): stock source and strategy (or several in parallel
   with capital budgets), trading switch, equity curve, positions (with owning
   strategy), orders, decision log. Broker/cycle/risk/keys behind the gear icon.
3. **ValueScreener**: choose a universe and algorithm (value/quality/growth score,
   Piotroski F-score, Magic Formula) → "update data + analysis" or "analysis only";
   results plus score history per stock. Replaces the separate MarketScreener GUI.
4. **Backtest** (profile "test", independent of live operation): fixed period
   (with segment analysis of trades) or randomized time windows (robustness
   harness with market-phase analysis); always with costs and the risk layer,
   SPY as benchmark.

## Broker & data

| Mode | Requirement | Data source |
|---|---|---|
| Simulation (default) | none | Yahoo daily data (cache) |
| IBKR paper | TWS/Gateway running, API enabled, port 7497/4002 | Yahoo (1d) or IBKR (`fetch_bars`, incl. intraday) |
| IBKR live | explicit live switch in the settings | same as paper |

Free Yahoo data is sufficient for backtests and daily swing trading; any
intraday interval requires the IBKR connection (details: STRATEGIE.md §1).
IBKR integration via [ib_async](https://github.com/ib-api-reloaded/ib_async).

## APIs (all visible live on the Data page)

| API | Key | Provides |
|---|---|---|
| Yahoo Finance | no | EOD + intraday prices, price batch, news, fundamentals fallback, corporate actions |
| Financial Modeling Prep | yes (gear → API-Keys) | fundamentals backfill (deep history), earnings calendar, event calendar, intraday fallback |
| Tiingo | yes (gear → API-Keys) | EOD price fallback, intraday IEX (US) |
| FRED (St. Louis Fed) | optional (recommended) | macro series; without key via fredgraph.csv (partly throttled), with a free key via the official API |
| ECB Data Portal | no | fallback for European series (ECB deposit rate, HICP) |
| Stooq | no | EOD price fallback (often blocked) |
| IBKR (TWS/Gateway) | connection | broker and best price/intraday source when connected |
| Anthropic (Claude) | optional | Claude sentiment model (see above) |
| Wikipedia / iShares / companiesmarketcap | no | index universes, MSCI World, Global 2000 |

The panel at the top of the Data page shows the status per API:
green = last delivery succeeded, red = last contact failed,
yellow = usable but no key configured, grey = never contacted, together with the
time of the last delivery and the number of price fetches per provider in the
current session.

## Architecture

```
App/
├── bot_gui.py               # start: one GUI, all four pages
├── gui_1_daten.py           # open page 1 on its own
├── gui_2_tradebot.py        # open page 2 on its own
├── gui_3_valuescreener.py   # open page 3 on its own
├── gui_4_backtest.py        # open page 4 on its own
├── run_backtests.py         # CLI: strategy suite over a universe
├── run_validation.py        # CLI: robustness harness (random windows)
├── run_sentiment_eval.py    # CLI: FinBERT vs. Claude on labeled headlines
├── mcp_server.py            # MCP server (read-only access for Claude)
├── evals/                   # label dataset + sentiment evaluation guide
├── tests/                   # unittest: Claude sentiment, MCP tools, eval metrics
├── STRATEGIE.md             # methodology + backtest protocol (authoritative, German)
├── GUI_KONZEPT.md           # target GUI architecture + data hub (+ status, German)
├── tradingbot/
│   ├── config.py            # paths + settings (profiles "live"/"test")
│   ├── botdb.py             # SQLite: decisions, orders, equity, stops
│   ├── engine.py            # cycle: data → signals → risk → orders
│   │                        #   (several strategies in parallel with budgets)
│   ├── risk.py              # 1% rule, ATR stops, limits, kill switch
│   ├── portfolio_backtest.py# multi-symbol backtester (identical logic)
│   ├── backtest.py          # single-symbol backtester (main.py)
│   ├── validation.py        # robustness harness + phase/segment analysis
│   ├── strategies/          # registry; new strategy = new file
│   ├── screening/           # registry of screener algorithms (page 3)
│   ├── broker/              # interface + PaperBroker + IBKR (ib_async)
│   ├── data/                # hub.py (data hub), feeds.py, fundamentals.py,
│   │                        #   prices (CSV cache), news archive, universes
│   ├── mcp_tools.py         # tools of the MCP server (read-only)
│   ├── sentiment/           # FinBERT, Claude + sentiment history (cached, fallback)
│   └── ui/                  # GUI: app.py + seite1_daten.py … seite4_backtest.py
├── data_cache/              # hub.db, prices, news, bot DB, profiles (not versioned)
├── reports/                 # backtest/screener/news CSVs
└── watchlists/              # custom symbol lists
```

## Roadmap

- [x] Strategy framework with GUI-editable parameters
- [x] Risk management (1% rule, trailing stops, regime filter, kill switch)
- [x] Portfolio backtester with costs
- [x] News sentiment as entry gate (FinBERT, local)
- [x] PaperBroker (persistent) + IBKR adapter (paper/live)
- [x] Control GUI with auto mode
- [x] Data hub (hub.db) + one GUI with 4 pages (GUI_KONZEPT.md)
- [x] Several strategies in parallel with capital budgets
- [x] ValueScreener in the bot GUI (screening registry, hub data)
- [x] Equity curve chart (TradeBot page)
- [x] MCP server: bot data and MoQu ranking queryable from Claude
- [x] Claude as alternative sentiment model (with fallback to FinBERT)
- [ ] Run the sentiment evaluation with ≥200 labeled headlines → justify the model choice
- [ ] Backtest suite over DAX/SMI/custom watchlists → STRATEGIE.md §4
- [ ] Weeks of paper trading (simulation first, then IBKR paper)
- [ ] Screener ranking as watchlist source for the bot (link page 3 → page 2)
- [ ] Live with a small amount (allow_live), tighter kill switch

**Disclaimer:** Experimental learning project. Not investment advice;
live trading only with money you can afford to lose.
