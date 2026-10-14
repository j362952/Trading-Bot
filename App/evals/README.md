# Sentiment evaluation: FinBERT vs. Claude

Goal: measure instead of believe. Which model more reliably detects the news
situation the sentiment gate is supposed to react to, and what does it cost?

## Workflow

```bash
cd App
# 1) Pull headlines from the news archive (existing labels are kept,
#    new rows are appended). Use --fetch to load news for a universe first.
uv run run_sentiment_eval.py export --universe dax --fetch --n 200

# 2) Open evals/sentiment_labels.csv (Excel/editor) and fill in the "label" column

# 3) Measure
uv run run_sentiment_eval.py run
uv run run_sentiment_eval.py run --backends finbert,claude --price-in 1 --price-out 5
```

Output: `reports/sentiment_eval_<date>.md` (metrics, confusion matrices,
examples of disagreement) and `reports/sentiment_eval_items_<date>.csv` (every
single judgment, including Claude's reasoning).

## Labeling rules (fix them before labeling, then don't change them)

Question per row: **Is this headline good, bad or irrelevant for the stock price of
`symbol` in the short term (days to a few weeks)?**

| Label | Short form | When |
|---|---|---|
| `positive` | `+` | concrete good news for exactly this company: earnings/revenue above expectations, guidance raised, takeover offer for the company, approval, major order, upgrade |
| `negative` | `-` | concrete bad news: profit warning, guidance cut, lawsuit/fine, recall, investigations, CEO departure, downgrade, crash of the stock itself |
| `neutral` | `0` | no clear direction, plain market reports, listicles ("3 stocks for …"), **and anything that is not about this company at all** (the Yahoo feed often delivers news about other companies) |

Further rules:
- Only judge what the headline says: don't read the article, and don't let
  knowledge of the later price movement influence the label.
- When in doubt, `neutral`. Note unclear cases in `comment`.
- Ideally label in one go, without looking at the model judgments first
  (otherwise they bias you).

## Why a custom dataset?

The well-known Financial PhraseBank dataset was used to train FinBERT, so a
comparison on it would be biased in FinBERT's favor. Besides, what matters for the
gate is the actual situation: Yahoo headlines per stock, including the many items
that are not about the stock at all.

## Limitations

- 200 headlines are a start: differences of a few percentage points are not
  reliable. More data → run `export` again and keep labeling.
- A single labeler is a source of error; ideally a second person labels the same
  set and the agreement is measured (Cohen's κ, included in the report).
