"""News-Sentiment als Einstiegs-Filter ("Gate") über jeder Strategie.

Beleg: Tetlock (2007, Journal of Finance) u.a. — stark negativer
Nachrichtenton geht kurzfristig mit weiteren Kursverlusten einher.
Wir nutzen das defensiv: das Gate erzeugt KEINE eigenen Signale,
es blockiert nur NEUE Einstiege, solange das Ø-Sentiment der letzten
Tage unter der Schwelle liegt ("nicht ins fallende Messer greifen,
wenn die Nachrichtenlage giftig ist"). Bestehende Positionen werden
nicht zwangsverkauft — dafür sind Stops/Strategie-Exits zuständig.

Kein Sentiment verfügbar = Gate offen (neutral), damit dünne
News-Abdeckung die Strategie nicht lahmlegt.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def apply_sentiment_gate(
    matrix: pd.DataFrame,
    sentiment: dict[str, pd.Series],
    min_score: float = -0.2,
    window_days: int = 7,
) -> pd.DataFrame:
    """Filtert eine Positions-Matrix (Datum × Symbol, 0/1):
    Einstiege an Tagen mit Ø-Sentiment < min_score werden unterdrückt,
    bis entweder das Signal zurückgeht (Reset) oder das Sentiment sich
    erholt (dann wird eingestiegen)."""
    gated = matrix.copy()
    for symbol in matrix.columns:
        series = sentiment.get(symbol)
        if series is None or series.empty:
            continue
        rolling = (
            series.reindex(
                pd.date_range(series.index.min(), matrix.index.max(), freq="D")
            )
            .rolling(f"{window_days}D", min_periods=1).mean()
            .reindex(matrix.index)
        )
        blocked = (rolling < min_score).to_numpy()  # NaN = kein News-Flow = offen

        signal = matrix[symbol].to_numpy()
        out = np.zeros(len(signal))
        holding = 0.0
        for i in range(len(signal)):
            if signal[i] <= 0:
                holding = 0.0
            elif holding == 0 and not blocked[i]:
                holding = signal[i]
            out[i] = holding
        gated[symbol] = out
    return gated
