"""Evaluation: FinBERT vs. Claude als News-Sentiment-Modell fürs Gate.

Zwei Schritte (Details und Label-Regeln: evals/README.md):

    # 1) Schlagzeilen zum Labeln exportieren (bestehende Labels bleiben erhalten)
    uv run run_sentiment_eval.py export --n 200
    uv run run_sentiment_eval.py export --universe dax --fetch --n 200

    # 2) Spalte "label" in evals/sentiment_labels.csv von Hand füllen
    #    (positive / negative / neutral, Kurzform + / - / 0), dann:
    uv run run_sentiment_eval.py run
    uv run run_sentiment_eval.py run --backends finbert,claude,claude-plain

Backends:
    finbert       lokales Modell, nur die Schlagzeile
    claude        Claude mit Bezug zum Titel (Firmenname + Symbol) — so läuft es im Bot
    claude-plain  Claude nur mit der Schlagzeile (fairer 1:1-Vergleich zu FinBERT)

Ergebnis: Kennzahlen je Modell (Accuracy, Macro-F1, Konfusionsmatrix),
die fürs Gate entscheidenden Werte (erkannte negative Meldungen,
Fehlblockaden), Übereinstimmung der Modelle, Laufzeit, Token-Verbrauch —
als Markdown-Report + CSV mit allen Einzelurteilen in reports/.
"""

from __future__ import annotations

import argparse
import random
import time
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd

from tradingbot.config import PROJECT_ROOT, REPORTS_DIR, load_settings

LABELS = ["positive", "neutral", "negative"]
SHORT = {"+": "positive", "pos": "positive", "-": "negative", "neg": "negative",
         "0": "neutral", "neu": "neutral", "o": "neutral"}
DEFAULT_FILE = PROJECT_ROOT / "evals" / "sentiment_labels.csv"
COLUMNS = ["id", "symbol", "published", "title", "label", "comment"]


# ------------------------------------------------------------------ Export

def export(args) -> None:
    from tradingbot.data.news import NEWS_CACHE_DIR, load_news

    if args.universe and args.fetch:
        from tradingbot.data.universe import load_universe

        symbols = list(load_universe(args.universe)["symbol"])
        print(f"Hole aktuelle News für {len(symbols)} Titel ins Archiv …")
        for s in symbols:
            try:
                load_news(s)
            except Exception as exc:
                print(f"  {s}: {exc}")

    frames = []
    for file in sorted(NEWS_CACHE_DIR.glob("*.csv")):
        df = pd.read_csv(file)
        if not df.empty:
            frames.append(df.assign(symbol=file.stem))
    if not frames:
        raise SystemExit("News-Archiv ist leer — erst News laden (Daten-Seite oder --fetch)")
    pool = pd.concat(frames, ignore_index=True).drop_duplicates("title")
    if args.universe and not args.fetch:
        from tradingbot.data.universe import load_universe

        pool = pool[pool["symbol"].isin(set(load_universe(args.universe)["symbol"]))]

    out = Path(args.out)
    existing = pd.read_csv(out) if out.exists() else pd.DataFrame(columns=COLUMNS)
    pool = pool[~pool["title"].isin(set(existing["title"]))]

    # gleichmäßig über Titel ziehen (Round-Robin), damit kein Symbol dominiert
    rng = random.Random(args.seed)
    by_symbol = {s: list(g.sample(frac=1, random_state=args.seed).itertuples())
                 for s, g in pool.groupby("symbol")}
    order = list(by_symbol)
    rng.shuffle(order)
    picked = []
    while len(picked) < args.n and any(by_symbol.values()):
        for s in order:
            if by_symbol[s] and len(picked) < args.n:
                picked.append(by_symbol[s].pop())
    start_id = int(existing["id"].max()) + 1 if len(existing) else 1
    new = pd.DataFrame([{
        "id": start_id + i, "symbol": r.symbol, "published": r.published,
        "title": r.title, "label": "", "comment": ""} for i, r in enumerate(picked)])
    result = pd.concat([existing, new], ignore_index=True)[COLUMNS]
    out.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(out, index=False, encoding="utf-8")
    labeled = result["label"].fillna("").astype(str).str.strip().ne("").sum()
    print(f"{len(new)} neue Schlagzeilen → {out} (gesamt {len(result)}, gelabelt {labeled})")
    print("Spalte 'label' füllen: positive / negative / neutral (oder + / - / 0). "
          "Regeln: evals/README.md")


# ------------------------------------------------------------------ Modelle

def _predict_finbert(titles, symbols, usage):
    from tradingbot.sentiment.finbert import classify_headlines

    return classify_headlines(titles)


def _predict_claude(titles, symbols, usage, with_subject=True, model=None):
    from tradingbot.sentiment.claude import classify_headlines
    from tradingbot.sentiment.history import _subject

    if not with_subject:
        return classify_headlines(titles, model=model, usage=usage)
    out = [None] * len(titles)
    groups: dict[str, list[int]] = {}
    for i, s in enumerate(symbols):
        groups.setdefault(s, []).append(i)
    for s, idx in groups.items():  # je Symbol ein Bezug → batchweise je Symbol
        res = classify_headlines([titles[i] for i in idx], subject=_subject(s),
                                 model=model, usage=usage)
        for i, r in zip(idx, res):
            out[i] = r
    return out


BACKENDS = {
    "finbert": _predict_finbert,
    "claude": lambda t, s, u, model=None: _predict_claude(t, s, u, True, model),
    "claude-plain": lambda t, s, u, model=None: _predict_claude(t, s, u, False, model),
}


# ------------------------------------------------------------------ Metriken

def confusion(gold, pred) -> dict:
    return {g: {p: sum(1 for a, b in zip(gold, pred) if a == g and b == p) for p in LABELS}
            for g in LABELS}


def metrics(gold, pred, scores, threshold) -> dict:
    n = len(gold)
    per_class = {}
    for c in LABELS:
        tp = sum(1 for a, b in zip(gold, pred) if a == c and b == c)
        fp = sum(1 for a, b in zip(gold, pred) if a != c and b == c)
        fn = sum(1 for a, b in zip(gold, pred) if a == c and b != c)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        per_class[c] = {"precision": prec, "recall": rec, "f1": f1, "support": tp + fn}
    neg = [i for i, g in enumerate(gold) if g == "negative"]
    non_neg = [i for i, g in enumerate(gold) if g != "negative"]
    return {
        "n": n,
        "accuracy": sum(a == b for a, b in zip(gold, pred)) / n if n else 0.0,
        "macro_f1": sum(v["f1"] for v in per_class.values()) / len(LABELS),
        "per_class": per_class,
        # Gate-Sicht: Score unter Schwelle = "würde blockieren"
        "neg_caught": (sum(scores[i] < threshold for i in neg) / len(neg)) if neg else None,
        "false_block": (sum(scores[i] < threshold for i in non_neg) / len(non_neg))
        if non_neg else None,
        "confusion": confusion(gold, pred),
    }


def cohen_kappa(a, b) -> float:
    n = len(a)
    if not n:
        return float("nan")
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[c] * cb[c] for c in LABELS) / (n * n)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def _pct(x) -> str:
    return "–" if x is None else f"{x:.0%}"


# ------------------------------------------------------------------ Run

def run(args) -> None:
    file = Path(args.labels)
    if not file.exists():
        raise SystemExit(f"{file} fehlt — erst 'export' ausführen und labeln")
    data = pd.read_csv(file)
    data["label"] = (data["label"].fillna("").astype(str).str.strip().str.lower()
                     .map(lambda x: SHORT.get(x, x)))
    data = data[data["label"].isin(LABELS)].reset_index(drop=True)
    if data.empty:
        raise SystemExit("Keine gelabelten Zeilen gefunden (Spalte 'label' leer?)")
    gold = list(data["label"])
    titles, symbols = list(data["title"]), list(data["symbol"].astype(str))
    model = args.model or load_settings().get("claude_model") or None
    print(f"{len(data)} gelabelte Schlagzeilen · Verteilung: {dict(Counter(gold))}")

    results = {}
    for name in [b.strip() for b in args.backends.split(",") if b.strip()]:
        if name not in BACKENDS:
            raise SystemExit(f"Unbekanntes Backend {name!r} — erlaubt: {', '.join(BACKENDS)}")
        usage: dict = {}
        print(f"→ {name} …", flush=True)
        t0 = time.perf_counter()
        try:
            fn = BACKENDS[name]
            preds = fn(titles, symbols, usage) if name == "finbert" else \
                fn(titles, symbols, usage, model=model)
        except Exception as exc:
            print(f"  {name} übersprungen: {exc}")
            continue
        seconds = time.perf_counter() - t0
        labels = [p["label"] for p in preds]
        scores = [float(p["score"]) for p in preds]
        m = metrics(gold, labels, scores, args.threshold)
        m.update(seconds=seconds, usage=usage)
        results[name] = {"metrics": m, "preds": preds}
        print(f"  Accuracy {m['accuracy']:.0%} · Macro-F1 {m['macro_f1']:.2f} · "
              f"neg. erkannt {_pct(m['neg_caught'])} · Fehlblockaden {_pct(m['false_block'])} · "
              f"{seconds:.1f} s")

    if not results:
        raise SystemExit("Kein Backend lief erfolgreich")
    _write_reports(data, gold, results, args, model)


def _write_reports(data, gold, results, args, model) -> None:
    REPORTS_DIR.mkdir(exist_ok=True)
    stamp = date.today().isoformat()
    items = data[["id", "symbol", "title", "label"]].rename(columns={"label": "gold"}).copy()
    for name, r in results.items():
        items[f"{name}_label"] = [p["label"] for p in r["preds"]]
        items[f"{name}_score"] = [round(float(p["score"]), 3) for p in r["preds"]]
        if any("reason" in p for p in r["preds"]):
            items[f"{name}_reason"] = [p.get("reason", "") for p in r["preds"]]
    items_file = REPORTS_DIR / f"sentiment_eval_items_{stamp}.csv"
    items.to_csv(items_file, index=False, encoding="utf-8")

    names = list(results)
    lines = [f"# Sentiment-Evaluation {stamp}", "",
             f"- Datensatz: `{Path(args.labels).name}`, {len(gold)} handgelabelte Schlagzeilen "
             f"({', '.join(f'{k}: {v}' for k, v in Counter(gold).items())})",
             f"- Gate-Schwelle: Score < {args.threshold} = Einstieg blockiert",
             f"- Claude-Modell: `{model or 'Default'}`", "",
             "## Ergebnis", "",
             "| Modell | Accuracy | Macro-F1 | neg. erkannt (Gate) | Fehlblockaden | Laufzeit | Tokens in/out |",
             "|---|---|---|---|---|---|---|"]
    for name in names:
        m = results[name]["metrics"]
        u = m["usage"]
        tok = f"{u.get('input_tokens', 0):,} / {u.get('output_tokens', 0):,}" if u else "–"
        lines.append(f"| {name} | {m['accuracy']:.0%} | {m['macro_f1']:.2f} | "
                     f"{_pct(m['neg_caught'])} | {_pct(m['false_block'])} | "
                     f"{m['seconds']:.1f} s | {tok} |")
    if args.price_in or args.price_out:
        lines += ["", "Kosten (laut angegebenen Preisen je Mio. Tokens):"]
        for name in names:
            u = results[name]["metrics"]["usage"]
            if u:
                cost = (u.get("input_tokens", 0) * args.price_in
                        + u.get("output_tokens", 0) * args.price_out) / 1e6
                lines.append(f"- {name}: {cost:.4f} USD für {len(gold)} Schlagzeilen")
    lines += ["", "**neg. erkannt** = Anteil der als negativ gelabelten Meldungen mit Score unter "
              "der Schwelle (das Gate hätte gegriffen). **Fehlblockaden** = Anteil der "
              "positiven/neutralen Meldungen mit Score unter der Schwelle.", ""]

    for name in names:
        m = results[name]["metrics"]
        lines += [f"## {name}", "", "| Klasse | Precision | Recall | F1 | n |", "|---|---|---|---|---|"]
        for c in LABELS:
            v = m["per_class"][c]
            lines.append(f"| {c} | {v['precision']:.2f} | {v['recall']:.2f} | {v['f1']:.2f} | {v['support']} |")
        lines += ["", "Konfusionsmatrix (Zeile = Label, Spalte = Vorhersage):", "",
                  "| | " + " | ".join(LABELS) + " |", "|---" * (len(LABELS) + 1) + "|"]
        for g in LABELS:
            lines.append(f"| **{g}** | " + " | ".join(str(m["confusion"][g][p]) for p in LABELS) + " |")
        lines.append("")

    if len(names) > 1:
        lines += ["## Übereinstimmung der Modelle (Cohen's κ)", ""]
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                la = [p["label"] for p in results[a]["preds"]]
                lb = [p["label"] for p in results[b]["preds"]]
                lines.append(f"- {a} vs. {b}: κ = {cohen_kappa(la, lb):.2f}")
        lines.append("")
        a, b = names[0], names[1]
        diff = items[items[f"{a}_label"] != items[f"{b}_label"]].head(15)
        if len(diff):
            lines += [f"## Beispiele: {a} ≠ {b}", "",
                      f"| Symbol | Schlagzeile | Label | {a} | {b} |", "|---|---|---|---|---|"]
            for _, r in diff.iterrows():
                title = str(r["title"]).replace("|", "/")[:90]
                extra = f" ({r[f'{b}_reason']})" if f"{b}_reason" in r and r[f"{b}_reason"] else ""
                lines.append(f"| {r['symbol']} | {title} | {r['gold']} | {r[f'{a}_label']} | "
                             f"{r[f'{b}_label']}{extra} |")
            lines.append("")

    lines += ["## Einordnung", "",
              "- Kleiner Datensatz → Unterschiede von wenigen Prozentpunkten sind nicht belastbar.",
              "- Labels stammen von einer Person; ideal wäre ein zweiter Labeler (Übereinstimmung messen).",
              "- `claude` sieht den Firmenbezug, FinBERT nicht — das ist der reale Einsatzfall im Bot; "
              "`claude-plain` zeigt den reinen Modellvergleich.", "",
              f"Einzelurteile: `{items_file.name}`"]
    report = REPORTS_DIR / f"sentiment_eval_{stamp}.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {report}\nEinzelurteile: {items_file}")


def main() -> None:
    parser = argparse.ArgumentParser(description="FinBERT vs. Claude Sentiment-Evaluation")
    sub = parser.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export", help="Schlagzeilen zum Labeln exportieren")
    ex.add_argument("--out", default=str(DEFAULT_FILE))
    ex.add_argument("--n", type=int, default=200, help="Anzahl neuer Schlagzeilen")
    ex.add_argument("--universe", help="nur Titel dieses Universums/dieser Watchlist")
    ex.add_argument("--fetch", action="store_true", help="vorher News für das Universum laden")
    ex.add_argument("--seed", type=int, default=42)
    rn = sub.add_parser("run", help="Modelle gegen die Labels messen")
    rn.add_argument("--labels", default=str(DEFAULT_FILE))
    rn.add_argument("--backends", default="finbert,claude,claude-plain")
    rn.add_argument("--threshold", type=float, default=load_settings().get("sentiment_min", -0.2))
    rn.add_argument("--model", help="Claude-Modell (Default: Einstellung claude_model)")
    rn.add_argument("--price-in", type=float, default=0.0, help="USD je Mio. Input-Tokens")
    rn.add_argument("--price-out", type=float, default=0.0, help="USD je Mio. Output-Tokens")
    args = parser.parse_args()
    export(args) if args.cmd == "export" else run(args)


if __name__ == "__main__":
    main()
