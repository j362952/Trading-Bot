# Sentiment-Evaluation: FinBERT vs. Claude

Ziel: messen statt glauben. Welches Modell erkennt die Nachrichtenlage, auf die das
Sentiment-Gate reagieren soll, zuverlässiger — und was kostet es?

## Ablauf

```bash
cd App
# 1) Schlagzeilen aus dem News-Archiv ziehen (bestehende Labels bleiben erhalten,
#    neue Zeilen werden angehängt). Mit --fetch vorher News für ein Universum laden.
uv run run_sentiment_eval.py export --universe dax --fetch --n 200

# 2) evals/sentiment_labels.csv öffnen (Excel/Editor) und Spalte "label" füllen

# 3) messen
uv run run_sentiment_eval.py run
uv run run_sentiment_eval.py run --backends finbert,claude --price-in 1 --price-out 5
```

Ergebnis: `reports/sentiment_eval_<datum>.md` (Kennzahlen, Konfusionsmatrizen,
Beispiele für Uneinigkeit) und `reports/sentiment_eval_items_<datum>.csv` (jedes
Einzelurteil inkl. Claude-Begründung).

## Label-Regeln (vor dem Labeln festlegen, dann nicht mehr ändern)

Frage je Zeile: **Ist diese Schlagzeile kurzfristig (Tage bis wenige Wochen) gut,
schlecht oder egal für den Aktienkurs von `symbol`?**

| Label | Kurzform | Wann |
|---|---|---|
| `positive` | `+` | konkrete gute Nachricht für genau diese Firma: Gewinn/Umsatz über Erwartung, Prognose angehoben, Übernahmeangebot für die Firma, Zulassung, Großauftrag, Upgrade |
| `negative` | `-` | konkrete schlechte Nachricht: Gewinnwarnung, Prognose gesenkt, Klage/Strafe, Rückruf, Ermittlungen, Abgang des CEO, Downgrade, Kurssturz der Aktie selbst |
| `neutral` | `0` | keine klare Richtung, reine Marktberichte, Listicles ("3 Aktien für …"), **und alles, was gar nicht von dieser Firma handelt** (der Yahoo-Feed liefert oft Meldungen über andere Firmen) |

Weitere Regeln:
- Nur werten, was in der Schlagzeile steht — nicht den Artikel nachlesen, kein Wissen
  über den späteren Kursverlauf einfließen lassen.
- Im Zweifel `neutral`. Unklare Fälle in `comment` notieren.
- Am besten in einem Rutsch labeln, ohne vorher die Modell-Urteile anzusehen
  (sonst färben sie ab).

## Warum ein eigener Datensatz?

Der bekannte Financial PhraseBank-Datensatz wurde zum Training von FinBERT benutzt —
ein Vergleich darauf wäre zugunsten von FinBERT verzerrt. Außerdem zählt für das Gate
die eigene Situation: Yahoo-Schlagzeilen, je Aktie, inklusive der vielen Meldungen,
die gar nicht von der Aktie handeln.

## Grenzen

- 200 Schlagzeilen sind ein Anfang: Unterschiede von wenigen Prozentpunkten sind nicht
  belastbar. Mehr Daten → `export` erneut ausführen und weiterlabeln.
- Ein einzelner Labeler ist eine Fehlerquelle; ideal labelt eine zweite Person
  denselben Satz, und man misst die Übereinstimmung (Cohen's κ, steht im Report).
