"""News-Sentiment-Analyse mit FinBERT: uv run news.py [SYMBOL ...]

    uv run news.py AAPL MSFT NOVN.SW     # einzelne Symbole
    uv run news.py --universe beispiel   # Watchlist oder Index (dax, smi, ...)

Score je Schlagzeile: -1 (sehr negativ) bis +1 (sehr positiv).
Vollständiges Ergebnis landet als CSV in reports/.
"""

import argparse
from datetime import date

import pandas as pd

from tradingbot.config import REPORTS_DIR
from tradingbot.data.news import load_news
from tradingbot.data.universe import load_universe
from tradingbot.sentiment.finbert import score_headlines


def main() -> None:
    parser = argparse.ArgumentParser(description="News-Sentiment (FinBERT)")
    parser.add_argument("symbols", nargs="*", help="Ticker-Symbole (Yahoo-Schreibweise)")
    parser.add_argument("--universe", help="Watchlist- oder Index-Name statt einzelner Symbole")
    parser.add_argument("--days", type=int, default=14, help="News-Fenster in Tagen")
    args = parser.parse_args()

    if args.universe:
        symbols = list(load_universe(args.universe)["symbol"])
    elif args.symbols:
        symbols = args.symbols
    else:
        parser.error("Symbole oder --universe angeben")

    all_news = []
    for symbol in symbols:
        news = load_news(symbol, max_age_days=args.days)
        if news.empty:
            print(f"\n{symbol}  —  keine News in den letzten {args.days} Tagen")
            continue

        news = news.assign(symbol=symbol, sentiment=score_headlines(list(news["title"])))
        all_news.append(news)

        print(f"\n{symbol}  —  Ø Sentiment {news['sentiment'].mean():+.2f}  ({len(news)} Meldungen)")
        for _, row in news.iterrows():
            print(f"  {row['published']:%d.%m.} {row['sentiment']:+.2f}  {row['title'][:90]}")

    if all_news:
        REPORTS_DIR.mkdir(exist_ok=True)
        csv_path = REPORTS_DIR / f"news_{date.today().isoformat()}.csv"
        pd.concat(all_news, ignore_index=True).to_csv(csv_path, index=False)
        print(f"\nVollständiger Report: {csv_path}")


if __name__ == "__main__":
    main()
