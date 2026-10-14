"""FinBERT-Sentiment: bewertet Finanz-Schlagzeilen lokal und kostenlos.

FinBERT (ProsusAI/finbert) ist ein BERT-Modell, das auf Finanztexten
nachtrainiert wurde. Es klassifiziert jeden Text als positiv/negativ/
neutral. Wir verdichten das zu einem Score = P(positiv) − P(negativ),
also -1 (sehr negativ) bis +1 (sehr positiv); Werte um 0 sind neutral.

Der erste Aufruf lädt das Modell (~440 MB) von Hugging Face herunter,
danach liegt es im lokalen Cache. Läuft komplett auf der CPU.
"""

from __future__ import annotations

from functools import lru_cache

MODEL_NAME = "ProsusAI/finbert"


@lru_cache(maxsize=1)
def _pipeline():
    print("Lade FinBERT-Modell (erster Lauf: ~440 MB Download) ...")
    from transformers import pipeline

    return pipeline("text-classification", model=MODEL_NAME, top_k=None)


def score_headlines(headlines: list[str]) -> list[float]:
    """Sentiment-Score je Schlagzeile, Reihenfolge bleibt erhalten."""
    if not headlines:
        return []
    results = _pipeline()(list(headlines), truncation=True)
    scores = []
    for label_probs in results:
        probs = {entry["label"]: entry["score"] for entry in label_probs}
        scores.append(probs.get("positive", 0.0) - probs.get("negative", 0.0))
    return scores
