# Trading Tools

A personal equity trading and research platform in Python: data hub, pluggable
strategies, a mandatory risk-management layer, backtesting, screening and broker
integration (built-in simulator or Interactive Brokers), all driven from one desktop GUI.
Built end-to-end with Claude Code.

## Claude integration

Claude is integrated in three places, all optional (without an Anthropic API key
everything runs as before):

| Component | What it does | Details |
|---|---|---|
| **MCP server** | Read-only MCP server with 7 tools that makes the data hub, news archive, strategy ranking and bot log queryable from Claude Desktop or Claude Code ("Why did the strategy pick these stocks this month?") | [App/README.md → MCP server](App/README.md#1-mcp-server-ask-claude-about-the-bot) · [`mcp_server.py`](App/mcp_server.py) · [`mcp_tools.py`](App/tradingbot/mcp_tools.py) |
| **Claude as sentiment model** | Drop-in alternative to FinBERT for the news gate: company-aware ratings with a reason per headline, structured output via forced tool use, prompt-injection safeguards, automatic fallback to FinBERT | [App/README.md → Sentiment](App/README.md#2-claude-as-sentiment-model-alternative-to-finbert) · [`sentiment/claude.py`](App/tradingbot/sentiment/claude.py) |
| **Evaluation** | Harness comparing FinBERT and Claude on hand-labeled headlines (accuracy, macro-F1, missed negatives, false blocks, Cohen's κ, token cost) | [App/evals/README.md](App/evals/README.md) · [`run_sentiment_eval.py`](App/run_sentiment_eval.py) |

Unit tests for all three live in [`App/tests/`](App/tests).

## Repository layout

| Folder | Contents | Start |
|---|---|---|
| [`App/`](App) | **The active project**: one GUI with four pages (Data · TradeBot · ValueScreener · Backtest) on top of a shared data hub; trading strategies + risk management, backtests/robustness harness, screening, broker integration (paper/IBKR), Claude integration | `cd App && uv run bot_gui.py` |
| [`_archiv/MarketScreener/`](_archiv/MarketScreener) | Original screener tool, superseded by the ValueScreener page; data migrated into the hub, code kept for reference | — |

Individual GUI pages can also be opened on their own:
`gui_1_daten.py` … `gui_4_backtest.py` in the `App/` folder.

Methodology documents (in `App/`, currently in German):
[`STRATEGIE.md`](App/STRATEGIE.md) (trading and risk) and
[`ANALYSE.md`](App/ANALYSE.md) (screening score).
The target GUI architecture and implementation status are in
[`GUI_KONZEPT.md`](App/GUI_KONZEPT.md); all data sources and APIs are documented
there and on the Data page of the GUI.

Note: if you scheduled the daily cycle via Windows Task Scheduler
(`run_cycle.bat`), update the path once to `App\run_cycle.bat`
(the folder used to be called `TradingBot\`).

## Disclaimer

This is an experimental learning project. **Not investment advice.**
Backtest results do not guarantee future returns. Use, especially with real
money, is entirely at your own risk.
