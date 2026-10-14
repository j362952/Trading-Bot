"""Robustheits-Validierung: Strategien gegen zufällige Zeiträume/Universen.

    uv run run_validation.py                      # neue Strategie (MoQu), 40 Läufe
    uv run run_validation.py --strategy momentum --runs 60
    uv run run_validation.py --compare            # alle Strategien vergleichen
    uv run run_validation.py --seed 42            # reproduzierbar

Datenbasis: der lokale Kurs-Cache. Ergebnisse als CSV in reports/.
"""

from __future__ import annotations

import argparse
from datetime import date

import pandas as pd

from tradingbot.config import REPORTS_DIR
from tradingbot.strategies import STRATEGIES, make_strategy
from tradingbot.validation import (load_cached_bars, robustness_test, summarize,
                                   summarize_by_phase, summary_text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Robustheits-Validierung")
    parser.add_argument("--strategy", default="momo_quality", choices=list(STRATEGIES))
    parser.add_argument("--runs", type=int, default=40)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--compare", action="store_true", help="alle Strategien")
    args = parser.parse_args()

    print("Lade Kurs-Cache ...")
    bars = load_cached_bars()
    print(f"{len(bars)} Titel mit ausreichend Historie\n")

    todo = list(STRATEGIES) if args.compare else [args.strategy]
    REPORTS_DIR.mkdir(exist_ok=True)
    all_summaries = []
    for key in todo:
        results = robustness_test(
            lambda k=key: make_strategy(STRATEGIES[k], {}), bars,
            n_runs=args.runs, seed=args.seed, progress=print)
        s = summarize(results)
        print("\n" + summary_text(STRATEGIES[key]().name, s) + "\n")
        print("Nach Marktphase:")
        print(summarize_by_phase(results).to_string(float_format=lambda v: f"{v:+.1%}"), "\n")
        out = REPORTS_DIR / f"validation_{key}_{date.today().isoformat()}.csv"
        results.to_csv(out, index=False)
        print(f"Einzel-Läufe: {out}\n")
        all_summaries.append({"strategy": key, **s})
    if len(all_summaries) > 1:
        print(pd.DataFrame(all_summaries).set_index("strategy").to_string())


if __name__ == "__main__":
    main()
