# Analyse-Methodik des ValueScreeners

Diese Datei ist die maßgebliche Beschreibung der Value-Investing-Analyse
und zugleich die Arbeitsgrundlage für ihre Weiterentwicklung: Änderungen an
der Methodik werden zuerst hier beschrieben (oder hier vorgeschlagen) und
dann in `tradingbot/screening/value_score.py` umgesetzt (ValueScreener-Seite
der GUI; früher: `marketscreener/scoring.py` im inzwischen archivierten
MarketScreener-Projekt). Das Änderungsprotokoll am Ende hält fest, was wann
warum angepasst wurde. Datenbasis ist der Daten-Hub (`data_cache/hub.db`);
wo unten von `data/screener.db` die Rede ist, gilt heute die Tabelle
`fundamentals` im Hub.

## 1. Datenbasis

- **Quartals-Fundamentaldaten, wie reportet** (GuV, Bilanz, Cashflow) je
  Aktie, gespeichert in SQLite (`data/screener.db`, Tabelle `quarterly`,
  eine Zeile pro Aktie und Fiskalquartal). Quellen: Financial Modeling Prep
  (tiefe Historie, API-Key) mit Yahoo Finance als Basis/Fallback
  (~5 Quartale). Die Historie wächst mit jedem Lauf.
- **Marktpreise** werden bei jedem Analyse-Lauf frisch als Batch geholt.
  Marktkapitalisierung = Preis × jüngste bekannte Aktienzahl aus der Bilanz.
- **Zeitlichkeit:** Flussgrößen (Umsatz, Gewinn, Cashflow) werden als
  **TTM** (trailing twelve months = Summe der letzten 4 reporteten Quartale)
  verwendet; Bestandsgrößen (Bilanzposten) aus dem jüngsten Quartal.
  Liegt das jüngste Quartal mehr als 300 Tage zurück, wird die Aktie nicht
  bewertet (veraltete Datenlage).

## 2. Kennzahlen und Säulen

Jede Kennzahl gehört zu einer von drei Säulen. Richtung: ↑ = höher ist
besser, ↓ = niedriger ist besser.

### Value — Ist die Aktie günstig? (Gewicht 45 %)

| Kennzahl | Formel | Richtung |
|---|---|---|
| Gewinnrendite | TTM-Nettogewinn / Marktkapitalisierung | ↑ |
| FCF-Rendite | TTM-Free-Cashflow / Marktkapitalisierung | ↑ |
| EBITDA/EV-Rendite | TTM-EBITDA / Enterprise Value (MCap + Schulden − Cash) | ↑ |
| Buchwert/Preis | Eigenkapital / Marktkapitalisierung | ↑ |

Bewusst **Renditen statt Multiples** (Gewinnrendite statt KGV): so ranken
Verlustfirmen automatisch schlecht, statt wegen negativer Multiples aus der
Wertung zu fallen.

### Quality — Ist das Geschäft gut? (Gewicht 40 %)

| Kennzahl | Formel | Richtung |
|---|---|---|
| Eigenkapitalrendite | TTM-Nettogewinn / Ø Eigenkapital (letzte 5 Quartale) | ↑ |
| Operative Marge | TTM-EBIT / TTM-Umsatz | ↑ |
| Bruttomarge | TTM-Bruttogewinn / TTM-Umsatz | ↑ |
| Verschuldung | Schulden / Eigenkapital (nur bei positivem EK) | ↓ |
| Liquidität | Umlaufvermögen / kurzfristige Verbindlichkeiten | ↑ |
| Margen-Stabilität | Streuung (Std.-Abw.) der operativen Quartalsmarge über bis zu 8 Quartale | ↓ |

Die Quality-Säule schützt davor, "billige" Firmen zu kaufen, die zu Recht
billig sind (Value Traps). Die Margen-Stabilität ist die erste Kennzahl,
die die Quartals-**Historie** wirklich ausnutzt.

### Growth — Wächst das Geschäft? (Gewicht 15 %)

| Kennzahl | Formel | Richtung |
|---|---|---|
| Umsatzwachstum | TTM-Umsatz / Vorjahres-TTM − 1 | ↑ |
| Gewinnwachstum | TTM-Nettogewinn / Vorjahres-TTM − 1 (nur bei positivem Vorjahr) | ↑ |

Kleines Gewicht, als Korrektiv: reine Value-Rankings bevorzugen sonst
schrumpfende Geschäftsmodelle.

## 3. Score-Berechnung

1. **Perzentil-Ränge:** Jede Kennzahl wird innerhalb des gewählten
   Universums als Perzentil-Rang bewertet (0 = schlechteste, 100 = beste
   Aktie; bei ↓-Kennzahlen umgekehrt). Absolute Schwellen ("KGV < 15")
   funktionieren über Branchen und Zinsniveaus hinweg schlecht — relative
   Ränge vergleichen jede Aktie mit ihrer aktuellen Konkurrenz.
   Fehlende Kennzahlen erhalten keinen Rang (kein Strafwert).
2. **Säulen-Scores:** Mittelwert der vorhandenen Kennzahl-Ränge der Säule.
3. **Gesamt-Score:** gewichtetes Mittel der Säulen
   (Value 0,45 / Quality 0,40 / Growth 0,15). Fehlt eine Säule komplett,
   werden die Gewichte der übrigen proportional hochskaliert.
4. **Mindest-Abdeckung:** Aktien mit weniger als 50 % vorhandenen
   Kennzahlen werden aussortiert (statt mit Phantasie-Scores zu ranken).
   Die Abdeckung wird als `coverage` mit ausgegeben.

Der Score ist ein **relatives Ranking innerhalb des gewählten Universums**,
kein absolutes Kaufsignal. Dieselbe Aktie kann im S&P 500 anders ranken als
im MSCI World.

## 4. Bekannte Grenzen (ehrlich gesagt)

- **Währungen:** Alle Kennzahlen sind Verhältniszahlen, daher weitgehend
  währungsneutral — solange Kurs- und Bilanzwährung übereinstimmen.
  Londoner Pence-Kurse werden korrigiert (÷100). Nicht behandelt sind
  Fälle wie ADRs oder Firmen, die in einer anderen Währung berichten als
  sie notieren — einzelne Ausreißer im MSCI World sind möglich.
- **Yahoo-Historie:** ohne FMP-Key nur ~5 Quartale → Growth- und
  Stabilitäts-Kennzahlen haben anfangs dünne Basis; die DB-Historie
  wächst mit jedem Quartal.
- **Banken/Versicherer:** EBITDA, Current Ratio und Debt/Equity sind für
  Finanzwerte wenig aussagekräftig; sie ranken dort systematisch schief.
  Perspektivisch: Finanzsektor eigene Kennzahlen geben.
- **Survivorship:** Universen sind die heutigen Mitglieder; historische
  Scores sagen nichts über damalige Index-Zusammensetzung.
- **Keine Anlageberatung.** Der Score ist ein Screening-Werkzeug, das die
  Kandidatenliste verkürzt — nicht die Analyse ersetzt.

## 5. Ideen-Backlog (Weiterentwicklung)

- Piotroski F-Score aus Jahresvergleichen der Quartalsdaten
- Sektor-relative Ränge (Kennzahlen nur innerhalb des Sektors ranken)
- Score-Historie visualisieren (Läufe sind bereits in der DB: `score_runs`)
- Earnings-Momentum: Gewinnrevisionen über die letzten Quartale
- Shareholder Yield: Dividenden + Aktienrückkäufe aus dem Cashflow
- Eigene Kennzahlen-Sets für Finanzwerte
- Weitere Datenquellen: SEC EDGAR (US, "as reported", gratis), EODHD

## 6. Änderungsprotokoll

| Datum | Änderung | Begründung |
|---|---|---|
| 2026-07-10 | Scoring in die App-GUI (TradingBot) portiert (`App/tradingbot/screening/value_score.py`, Datenbasis Daten-Hub); zusätzlich Piotroski F-Score und Magic Formula als weitere Registry-Algorithmen; Screener-DB in den Hub migriert. Methodik unverändert — diese Datei bleibt maßgeblich | Umbau nach GUI_KONZEPT.md: eine GUI, MarketScreener-GUI abgelöst |
| 2026-07-08 | Erstfassung: TTM-basierte Kennzahlen auf Quartals-Historie, 3 Säulen (45/40/15), Perzentil-Ränge, Margen-Stabilität neu | Umstellung von Tages-Snapshots (Yahoo info) auf reportete Quartalszahlen mit Historie |
