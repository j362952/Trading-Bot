# Strategie- und Risiko-Methodik des TradingBots

Diese Datei ist — wie `ANALYSE.md` beim ValueScreener — die maßgebliche
Beschreibung der Handelslogik und die Arbeitsgrundlage für ihre
Weiterentwicklung. Änderungen werden zuerst hier beschrieben, dann in
`tradingbot/strategies/` bzw. `tradingbot/risk.py` umgesetzt. Das
Änderungsprotokoll am Ende hält fest, was wann warum angepasst wurde.

**Oberstes Ziel: langfristig durch regelmäßiges Trading Gewinn erzielen.**
Daraus folgt die Grundhaltung dieses Dokuments: lieber wenige, empirisch
belegte Effekte sauber handeln und Verluste hart begrenzen, als viele
raffinierte Signale stapeln. Der größte Feind des Ziels ist nicht ein
schwaches Signal, sondern ein großer Drawdown und Überoptimierung
("80 % aller backgetesteten Strategien versagen live").

## 1. Datenlage (Antwort auf die Provider-Frage)

- **Tagesdaten (EOD):** Yahoo (kostenlos) ist für Backtests und den
  täglichen Swing-Betrieb ausreichend — mit Einschränkungen: inoffizielle
  API, Rate-Limits, gelegentliche Ausfälle. Der Kurs-Cache
  (`data_cache/prices/`) puffert das ab; ein verpasster Tag ist im
  Tagesrhythmus unkritisch.
- **Automatisierte Entscheidungen / Intraday:** Kostenlose Quellen sind
  hier NICHT zuverlässig genug (Verzögerung, Blockaden, keine Garantien).
  Sobald die IBKR-Verbindung steht, ist **IBKR selbst die Datenquelle**
  (`fetch_bars()`, bis 1-Minuten-Kerzen): ohne Marktdaten-Abo 15 Min
  verzögert, mit Abo (~1,50–15 USD/Monat je Börse) in Echtzeit.
- **Historische Intraday-Daten** (für Backtests): kostenlos gibt es nur
  FENSTER — Yahoo ~60 Tage (5/15 Min) bzw. ~2 Jahre (1 Std), Tiingo-IEX
  und FMP-Free jeweils nur jüngere Abschnitte. Unser Ansatz wie beim
  News-Archiv: `data/intraday.py` mergt jeden Abruf in ein wachsendes
  Archiv (`data_cache/intraday/`) — die nutzbare Historie wächst mit
  jedem Lauf. Für sofort verfügbare, jahrelange Minutenhistorie bräuchte
  es Bezahldaten (IBKR-Marktdaten-Abo, Polygon, Databento).
- Konsequenz im Code: Tagesmodus nutzt den Yahoo-Cache; Intraday nutzt
  IBKR (falls verbunden), sonst die Kette Yahoo → Tiingo → FMP mit
  wachsendem Archiv. API-Keys liegen lokal in `data_cache/bot_settings.json`.

### Tag vs. Intraday — Einschätzung

Beide Modi sind implementiert (ein Schalter). Ehrliche Einordnung zum
"größeren Potenzial" von Intraday: die akademische Evidenz zeigt das
Gegenteil für die meisten systematischen Händler. Auf kürzeren
Zeitebenen steigt der Rauschanteil, Gebühren + Slippage fallen öfter an
(bei uns: ~1 USD + 5 bp JE Trade), und die Gegenseite sind
Hochfrequenz-Profis. Die gut belegten Effekte (Momentum, Trendfolge,
kurzfristige Reversion) leben auf Tages- bis Monatsebene. Empfehlung:
Tagesmodus als Arbeitspferd, Intraday-Modus als Experimentierfeld — die
Backtest-Suite rechnet beide mit identischen Kosten, das Archiv sammelt
ab jetzt Intraday-Historie, und die Ergebnisse entscheiden.

## 2. Strategien (alle adaptierbar, Parameter in der GUI)

Ausgewählt nach dem Kriterium: **in der Forschung über Jahrzehnte und
Märkte hinweg dokumentiert**, nicht nach Backtest-Schönheit.

### 2.1 Trendfolge: SMA-Crossover (`sma_cross`)
Investiert, solange SMA(fast) > SMA(slow). Default 50/200 ("Golden
Cross"). Beleg: Faber (2007); Trendfolge liefert historisch Sharpe
~0,5–0,8 mit deutlich kleineren Drawdowns als Buy & Hold. Charakter:
wenige Trades, verliert oft klein, gewinnt selten groß.

### 2.2 Trendfolge: Donchian-Breakout (`donchian`)
Kauft Ausbrüche über das entry_n-Hoch (55), verkauft unter das
exit_n-Tief (20). Beleg: Kern der Turtle-Systeme (Dennis/Eckhardt),
Standardbaustein systematischer CTAs (Carver).

### 2.3 Mean-Reversion: RSI-Rücksetzer (`meanrev`)
Kauft stark überverkaufte Rücksetzer (RSI(2) < 10) NUR oberhalb des
200-Tage-Schnitts, Ausstieg bei Erholung. Beleg: Connors/Alvarez;
kurzfristige Reversion ist bei Aktien gut belegt. Charakter: hohe
Trefferquote (~60–80 %), viele kleine Gewinne — komplementär zur
Trendfolge.

### 2.4 Momentum-Rotation (`momentum`)
Hält die top_n Aktien der Watchlist nach 6-Monats-Rendite (ohne die
letzte Woche — Reversal-Effekt), Rebalance monatlich, nur Titel mit
positivem Momentum (sonst Kasse). Beleg: Jegadeesh/Titman (1993), von
Fama/French als "premier anomaly" bezeichnet; ~12 % Jahres-Exzessrendite
über 3–12-Monats-Fenster dokumentiert.

### 2.5 News-Sentiment-Gate (FinBERT, zuschaltbar)
Kein eigenes Signal, sondern ein **defensiver Filter über jeder
Strategie**: neue Einstiege werden blockiert, solange das Ø-Sentiment
der letzten 7 Tage unter der Schwelle (Default −0,2) liegt. Beleg:
Tetlock (2007) — stark negativer Nachrichtenton geht kurzfristig mit
weiteren Verlusten einher. Kein Sentiment verfügbar = Gate offen.
Das News-Archiv ist append-only mit Original-Zeitstempeln, Backtests
damit frei von Look-Ahead; die Sentiment-Historie wächst erst mit dem
Betrieb (Yahoo liefert kein Archiv).

### 2.6 NEU: Vol-adjustiertes Momentum + Qualität (`momo_quality`, "MoQu")

Die im Auftrag "entwickle eine neue Strategie" gebaute Rotation —
drei Verbesserungen gegenüber 2.4:

1. **Risikoadjustiertes Momentum**: gerankt wird Rendite ÷ realisierte
   Volatilität (60 Tage) statt roher Rendite. Ruhig steigende Trends
   setzen sich verlässlicher fort; entschärft Momentum-Crashs
   (Barroso/Santa-Clara 2015).
2. **Qualitäts-Overlay aus reporteten Quartalszahlen** (Daten-Hub):
   TTM-ROE + operative Marge als Perzentil-Rang, gewichtet mit
   quality_weight (Default 25 %). Point-in-Time-sauber über reporting_lag
   (60 Tage); Titel ohne Fundamentaldaten bekommen den neutralen Rang —
   die Abdeckung wächst mit jedem Screener-Lauf (AQR "Quality Minus Junk").
3. **Doppelte Krisenbremse**: absolutes Momentum > 0 je Titel (sonst
   Kasse) + Makro-Ampel (3.1).

### 2.7 Makro-Schicht (`macro.py`): Analysen und Ereignisse

Makro fließt MESSBAR ein, nicht als Meinung — alles Preiszeitreihen,
damit Backtests Point-in-Time-sauber bleiben:

| Ampel | Messung | Logik |
|---|---|---|
| Index-Trend | SPY > SMA(200) | Bullen-/Bärenmarkt-Schalter |
| Angstprämie | VIX < SMA(50)×1,15 | steigende implizite Vola geht Abverkäufen voraus |
| Kreditrisiko | HYG/LQD > SMA(100) | Bond-Markt riecht Stress früher als Aktien |
| Realisierte Vola | Index-20d-Vol < SMA(50)×1,25 | datenfreier VIX-Proxy — Ampel funktioniert überall |

Risk-on = Mehrheit der verfügbaren Ampeln grün; nur dann sind NEUE Käufe
erlaubt (Exits und Stops laufen immer). Wirkt im Live-Zyklus UND als
`regime_series` im Backtest. Dazu nur live: **Ereignis-Blackout** — an
Tagen mit Hochrisiko-Terminen (Fed-Entscheid, CPI, Arbeitsmarktbericht;
FMP Economic Calendar) keine Neueinstiege; im Backtest bewusst nicht
simuliert (kein freier Point-in-Time-Kalender verfügbar).

### 2.8 NEU: Regionale Makro-Rotation (`macro_rotation`, "MacroRot")

Antwort auf den Auftrag "beziehe die neuen Makro-Daten in eine neue
Strategie ein, unterscheide marktspezifisch (Fed für USA, EZB für
Europa)". Kern ist die bewährte vol-adjustierte Momentum-Rotation
(§2.6-Mechanik inkl. Halte-Puffer), NEU ist eine **regionale
Makro-Schicht** aus den FRED-Reihen des Daten-Hubs:

Jeder Titel wird über sein Börsen-Suffix einer Region zugeordnet
(US / Europa / Andere). Je Region entsteht zu jedem Rebalance-Termin ein
Score aus 0/1-Voten (verfügbare Voten gemittelt, fehlende Reihen stimmen
nicht ab): **USA**: Fed-Zinsrichtung (DFF nicht steigend über ~6M),
Zinskurve 10J−3M > 0, HY-Spread (BAMLH0A0HYM2) unter SMA200,
CPI-Jahresrate fallend. **Europa**: EZB-Einlagenzins nicht steigend,
DE-10J über EZB-Satz, HICP-Jahresrate fallend. **Andere**: Mittel aus
USA/Europa (kein eigener Datensatz). Wirkung über zwei Hebel:
Ranking-Tilt (macro_weight, Default 0,25) und Entry-Gate (Region-Score
< gate_threshold 0,3 → keine NEUEN Käufe aus der Region; Bestände
bleiben, Stops/Exits laufen immer). Belege: Zinsstraffung/inverse Kurve
gehen schwachen Aktienphasen historisch voraus (Estrella/Mishkin 1998);
Kreditspreads reagieren früher als Aktien; das Regionale folgt der Logik
"handle jede Region nach IHREN Rahmenbedingungen".

Point-in-Time-Ehrlichkeit (dokumentierte Grenzen): Zins-/Spread-/
Kurven-Reihen sind Marktdaten (nicht revidiert, 1 Tag Lag); CPI/HICP
sind REVIDIERTE Monatsreihen und wirken erst 45 Tage nach Monatsende
(Publikations-Näherung — Revisionsrisiko bleibt). Die Regionszuordnung
über Suffixe ist eine Näherung (CH/UK/Nordics unter EZB/Bund-Proxy,
Asien neutral). Ohne Makro-Daten im Hub läuft die Strategie unverändert
als reine vol-adjustierte Momentum-Rotation (alle Scores neutral).

Teststand: Mechanik vollständig verifiziert (Region-Mapping, Tilt,
hartes Gate blockiert rote Regionen komplett, Neutral-Fallback exakt
identisch zum Momentum-Kern, Voll-Backtest mit Risk-Schicht läuft) —
allerdings mit teils SYNTHETISCHEN Zinsreihen, da die Sandbox FRED
nicht erreicht. **Die Alpha-Messung steht aus** und läuft nach dem
ersten "Makro"-Abruf (Daten-Seite) über den Robustheits-Harness:
Backtest-Seite → Zufallsfenster, `macro_rotation` gegen `momo_quality`
und SPY, In-Sample-Seeds → frische Seeds (Protokoll wie §4.2).

## 3. Risk-Management (die eigentliche Gewinnsicherung)

Strategien sagen WAS und WANN — die Risk-Schicht sagt WIE VIEL und
notfalls NEIN. Reihenfolge im Zyklus: Kill-Switch → Trailing-Stops →
Strategie-Exits → Regime-Filter → Sentiment-Gate → Positionsgröße.

| Regel | Default | Zweck |
|---|---|---|
| 1%-Regel | risk_per_trade = 1 % | Verlust je Trade ≈ 1 % des Kapitals: Kapital / (3×ATR) Stück |
| Trailing-Stop | 3 × ATR(14) (Chandelier) | begrenzt jeden Einzeltrade, läuft Gewinnen hinterher |
| Max. Positionen | 10 | Streuung, kein Klumpen |
| Max. Gewicht | 20 % je Position | auch bei niedriger Volatilität kein Klumpen |
| Regime-Filter | SPY > SMA(200) | keine neuen Käufe im Bärenmarkt ("don't fight the tape") |
| Kill-Switch | 25 % Drawdown | alles verkaufen, Bot AUS; Reset nur manuell im Dashboard |

Kosten werden immer mitsimuliert: IBKR-artige Kommission
(max(1 USD; 0,005 USD/Aktie)) + 5 bp Slippage. Bei kleinen Konten sind
Gebühren der größte Renditefresser — deshalb wenige, große Signale statt
vieler kleiner.

## 4. Backtest-Protokoll

Regeln: Ausführung immer zur nächsten Kerze nach dem Signal (kein
Look-Ahead), Kosten immer an, Risk-Schicht immer an, Benchmark ist
gleichgewichtetes Buy & Hold über dieselbe Watchlist. Läufe über
`uv run run_backtests.py <watchlist>` oder den Backtest-Tab der GUI;
Ergebnisse als CSV in `reports/`.

Erste Validierung (SPY, 2010–2026, echte Daten, Einzelsymbol):

| Strategie | CAGR | MaxDD | Sharpe | Trades | Befund |
|---|---|---|---|---|---|
| Buy & Hold | +14,1 % | −33,7 % | 0,86 | 1 | Maßstab |
| SMA 50/200 (mit Risk-Schicht) | +4,8 % | −11,9 % | 0,74 | 98 | 1/3 des Drawdowns, ähnliche risikoadj. Rendite |
| Donchian 55/20 | +2,0 % | −16,1 % | 0,40 | 98 | auf Einzel-Index schwach — braucht Streuung |
| RSI(2)-MeanRev | +1,1 % | −9,8 % | 0,31 | 144 | Trefferquote 69 %, kleine Beiträge |

Zweiter Lauf (GUI-Suite, **S&P 500 komplett, ~503 Titel**, 2015–2026,
Tagesdaten, Risk-Schicht + Kosten aktiv):

| Strategie | CAGR | MaxDD | Sharpe | Trades | Treffer | Kill-Switch |
|---|---|---|---|---|---|---|
| Momentum-Rotation Top5 (126d) | **+15,6 %** | **−15,0 %** | **1,13** | 565 | 52 % | — |
| RSI(2)-MeanReversion <10 | +11,7 % | −21,4 % | 0,85 | 4154 | 61 % | — |
| Donchian-Breakout 55/20 | +5,7 % | −25,4 % | 0,49 | 474 | 42 % | ausgelöst |
| SMA-Crossover 50/200 | +4,9 % | −25,6 % | 0,49 | 225 | 49 % | ausgelöst |

Befunde: (1) **Momentum-Rotation dominiert** — deckt sich mit der
Literatur; braucht die Breite des Universums. (2) Beide Trendfolger
rissen das 25%-Kill-Switch-Limit (vmtl. Covid-Crash 2020) — Defaults
für breite Universen zu aggressiv, Risiko je Trade senken oder Limit
diskutieren. (3) MeanReversion stark, aber 4154 Trades — kostenintensiv.
(4) Vorsicht Survivorship-Bias: heutige Mitgliederliste rückwirkend
getestet, Ergebnisse eher geschönt. (5) Equal-Weight-Benchmark über
503 Titel lieferte 0 Trades (Positionsgröße rundet auf 0) — Benchmark
auf SPY-Vergleich umstellen (Backlog).

Ehrliche Lesart: **auf einem einzelnen Index schlägt in einer 16-jährigen
Hausse nichts Buy & Hold bei der Rohrendite** — der Mehrwert der
Strategien liegt in drastisch kleineren Drawdowns (Ziel "regelmäßig
Gewinn" heißt auch: 2008/2020/2022 überleben) und entfaltet sich erst
über einer breiteren Watchlist (Momentum-Rotation braucht Auswahl).
Nächster Schritt: Suite über DAX-/SMI-/eigene Watchlists laufen lassen
und die Tabelle hier fortschreiben.

### 4.1 Robustheits-Protokoll (Anforderung: "immer wieder testen")

Werkzeug: `uv run run_validation.py` (bzw. `tradingbot/validation.py`) —
zieht N ZUFÄLLIGE Kombinationen aus Zeitfenster (3 Monate bis 4 Jahre,
zufälliger Start) × Teiluniversum (40–150 zufällige Titel) und lässt die
Strategie jedes Mal mit voller Risk-Schicht und Kosten antreten.
Bewertet wird die Verteilung: Median-Rendite p.a., Anteil positiver
Fenster, Anteil über SPY und über der Equal-Weight-Benchmark desselben
Teiluniversums, schlechtestes Fenster. Reproduzierbar per --seed;
Ergebnisse als CSV in reports/. Wichtig bei der Lektüre: die
Equal-Weight-Benchmark heutiger Indexmitglieder ist durch Survivorship
massiv geschönt — SPY ist der fairere Vergleich.

Erster Sweep (S&P-500-Kurs-Cache 2010–2026, je Variante 3 Seeds × 30
Zufallsfenster à 3 Monate–4 Jahre × 40–150 Zufallstitel, alle Kosten +
Risk-Schicht aktiv; Werte über alle Fenster):

| Variante | Median p.a. | Fenster positiv | > SPY | worst Fenster | Median MaxDD | Kills |
|---|---|---|---|---|---|---|
| **MoQu 12M-Lookback** | **+13,4 %** | 83 % | **40 %** | −18,3 % | −12,7 % | 4/90 |
| MoQu Top8 (6M) | +12,4 % | 82 % | 39 % | −21,4 % | −12,9 % | 9/90 |
| MoQu Top5 (6M) | +10,3 % | **86 %** | 28 % | **−15,0 %** | **−11,0 %** | 2/90 |
| Momentum Top5 (alt, 2.4) | +9,7 % | 78 % | 34 % | −21,6 % | −11,0 % | 4/90 |

Befunde: (1) Die neue MoQu schlägt die alte Momentum-Rotation in jeder
Aggregat-Kennzahl. (2) 12-Monats-Lookback gewinnt → als Default gesetzt
(einmalige, offengelegte Kalibrierung über 3 Seeds — keine Feinjagd).
(3) Der Median-Exzess gegen SPY bleibt leicht negativ (−2,2 %): in einer
S&P-Dauerhausse ist SPY kaum zu schlagen — der Wert der Strategie liegt
in 83 % positiven Fenstern bei etwa halbem Drawdown. (4) Survivorship-
Vorbehalt gilt weiter; Out-of-Sample-Beweis = Paper-Betrieb.

### 4.2 Iterations-Protokoll "den Markt schlagen" (2026-07-08)

Vorgehen gegen Selbstbetrug: Hypothesen-Varianten auf In-Sample-Seeds
(42/7/2026) gesweept, Sieger auf FRISCHEN Seeds (1/99/555) bestätigt —
je 90 Zufallsfenster. Getestet: Halte-Puffer (Turnover ↓), Momentum-Blend,
aggressives Sizing, weite Stops (sizing-kompensiert), Regime-Filter aus.

| Konfiguration | Exzess vs SPY (Median) | Fenster > SPY | Kills |
|---|---|---|---|
| MoQu Basis (In-Sample) | −2,1 % | 37 % | 2/90 |
| Bester Kandidat "M" (In-Sample) | **+0,4 %** | 49 % | 14/90 |
| **"M" Out-of-Sample** | **−2,7 %** | 47 % | 16/90 |
| MoQu Basis Out-of-Sample | −6,9 % | 29 % | 4/90 |

Befunde (ehrlich): (1) Die Iteration hat die Strategie ROBUST verbessert
— auch Out-of-Sample +4,2 Prozentpunkte Exzess und 29 %→47 % Fenster
über SPY gegenüber der Basis. Der Halte-Puffer (exit_rank_mult=2) ist
seither Default. (2) Der In-Sample-Marktvorsprung (+0,4 %) überlebte die
frischen Seeds NICHT — klassische leichte Überanpassung, genau dafür ist
der OOS-Check da. Realistische Aussage: **Marktniveau bei ~50/50-Chance
je Fenster**, Mehrwert bleibt Regelmäßigkeit (77 % positive Fenster).
(3) Ohne Regime-Filter übernimmt der Kill-Switch allein den Crash-Schutz
→ 16/90 Läufe deaktiviert. Deshalb ZWEI dokumentierte Modi:

- **Robust-Modus (Default):** MoQu 12M + Puffer, Regime-Filter AN,
  Stops 3×ATR — Ziel: regelmäßig verdienen, überleben.
- **Markt-Modus (optional, Risiko-Tab):** regime_sma=0,
  atr_stop_mult=5, risk_per_trade=0.0167 — höchste Chance gegen SPY
  (~50 %), aber häufigere Kill-Switch-Stopps; nur mit Bewusstsein dafür.

Wichtige Einschränkung der Testumgebung: In diesen Läufen waren
Qualitäts-Overlay (keine Fundamentaldaten für US-Titel in der DB) und
Makro-Ampel (kein VIX/HYG/LQD im Kurs-Cache der Sandbox) FAKTISCH INAKTIV
— die Live-Version hat mehr Information als die getestete. Nächste
Hebel mit echtem Potenzial statt weiterem Parameterdrehen: VIX/HYG/LQD
in den Cache holen und Makro-Ampel im Backtest messen, Fundamentals-
Abdeckung per Screener-Läufen aufbauen, DAX/SMI-Caches füllen und den
Sweep dort wiederholen (anderes Marktregime als die US-Dauerhausse).

### 4.3 Makro-Ampel gemessen (2026-07-08, selbstständige Iteration)

Die vierte Ampel (realisierte Index-Volatilität) macht die Makro-Schicht
datenunabhängig; VIX/HYG/LQD kommen auf dem Nutzer-Rechner beim nächsten
Backtest-Lauf automatisch in den Cache (Sandbox-Netz blockierte den
Abruf — gemessen wurde hier mit 2 von 4 Ampeln: Trend + realisierte Vola).
Plausibilitätscheck: Risk-on-Anteil 92 % über 2010–2026, aber nur 12 %
im Covid-Crash-Fenster.

Wirkung im Markt-Modus, je 90 Zufallsfenster:

| Markt-Modus | Median p.a. | positiv | > SPY | worst | Kills |
|---|---|---|---|---|---|
| ohne Makro (In-Sample) | +12,9 % | 79 % | 49 % | −20,6 % | 14/90 |
| MIT Makro (In-Sample) | +14,0 % | 82 % | 50 % | −18,0 % | **7/90** |
| ohne Makro (**Out-of-Sample**) | +9,9 % | 77 % | 47 % | −23,8 % | 16/90 |
| MIT Makro (**Out-of-Sample**) | **+10,8 %** | **81 %** | 46 % | −22,7 % | **7/90** |

Befund: Die Makro-Ampel **halbiert die Kill-Switch-Läufe robust (auch
Out-of-Sample)** und hebt Rendite und Trefferquote leicht — bei
unverändertem Exzess gegen SPY. Sie kauft keinen Marktvorsprung, aber
sie entfernt Tail-Risiko gratis. Konsequenz: Makro-Ampel bleibt Default
(Einstellungen: macro_filter=true) und der Markt-Modus wird NUR in
Kombination mit ihr empfohlen. Mit allen 4 Ampeln (VIX + Kredit auf dem
Nutzer-Rechner) ist eher mehr Schutz zu erwarten — nach dem ersten
GUI-Lauf dort erneut messen.

### 4.4 Segment- und Marktphasen-Analyse (Standard seit 2026-07-08)

Auf Anweisung fester Bestandteil jedes Testlaufs (`summarize_by_phase`,
`trade_segments` in validation.py; run_validation.py gibt beides aus):
jedes Zufallsfenster wird nach Marktphase getaggt (Bulle/Seitwärts/Bär
anhand der SPY-Rendite im Fenster), jeder geschlossene Trade nach Sektor
und Volatilitäts-Drittel des Titels attribuiert.

Erste Befunde (Momentum-Rotation, Volllauf 2015–2026 + 40 Zufallsfenster):

- **Marktphasen:** Das Geld wird fast vollständig in Bullenphasen
  verdient (82–94 % positive Fenster); Seitwärtsphasen sind leicht
  negativ, im (einzigen erwischten) Bärenfenster fällt die Strategie
  etwa WIE der Markt, nicht schlimmer. Rotation ist ein
  Schönwetter-System mit Bremsen — genau deshalb tragen Makro-Ampel und
  Kill-Switch die Verantwortung für den Rest. (Bär-Stichprobe winzig —
  bei jedem künftigen Lauf weiter beobachten.)
- **Aktiengruppen:** Praktisch der GESAMTE Gewinn stammt aus dem
  volatilen Drittel des Universums (+303k von +310k); Trefferquote dort
  nur 50 % — wenige große Gewinner zahlen alles. Sektoren: IT liefert
  die Masse, Financials die beste Trefferquote (68 %), **Utilities und
  Consumer Staples sind Netto-Verlierer** — die Strategie verschwendet
  Trades an defensive Titel.
- **Daraus abgeleitete Hypothese** (noch NICHT umgesetzt, erst
  Out-of-Sample prüfen): defensives/ruhiges Drittel von der
  Kandidatenliste ausschließen könnte Kosten senken und Rendite heben —
  klassische Überanpassungsgefahr, daher erst als sauberes
  In-Sample→OOS-Experiment im nächsten Iterationszyklus.

## 5. Bekannte Grenzen

- Nur Long, keine Leerverkäufe/Derivate (bewusst, erst Basis beweisen).
- Tagesschluss-Logik: Signale entstehen auf der letzten abgeschlossenen
  Kerze; der Zyklus sollte nach Börsenschluss (Default 22:15) laufen.
- Trailing-Stops schützen nicht vor Overnight-Gaps; der Kill-Switch ist
  die letzte Bremse dahinter.
- Yahoo-Symbole ≠ IBKR-Kontrakte: Mapping in `broker/ibkr.py` ist best
  effort (US, Xetra, SIX, Euronext, LSE, Toronto, Tokio) — vor dem ersten
  Paper-Trade je Auslandssymbol prüfen.
- Backtests auf heutiger Watchlist = Survivorship-Bias; Ergebnisse
  konservativ lesen und Out-of-Sample (Paper-Betrieb!) bestätigen lassen.

## 6. Fahrplan zum Live-Betrieb

1. **Simulation** (PaperBroker): Strategie + Risiko-Parameter festlegen,
   Backtests über die eigene Watchlist, dann Wochen im Auto-Modus laufen
   lassen. Equity-Kurve und Entscheidungs-Log im Dashboard beobachten.
2. **IBKR Paper** (TWS/Gateway, Port 7497/4002): identischer Bot, echte
   Orderausführung gegen das Übungskonto. Mindestens 4–8 Wochen.
3. **IBKR Live** (allow_live erst dann setzen!): mit kleinem Betrag
   starten; Kill-Switch-Limit eher enger (15–20 %) als weiter.

## 7. Ideen-Backlog

- GUI-Benchmark: SPY-Buy&Hold statt Equal-Weight-Simulation (Bug bei großen Universen)
- Momentum-Matrix vektorisieren (Backtest über 500 Titel dauert ~10 Min)
- Volatilitäts-Targeting (Positionsgrößen an Portfoliovolatilität koppeln)
- Momentum-Rotation mit Sektor-Constraints
- Kopplung an den ValueScreener (Seite 3): dessen Ranking als Watchlist-Quelle
- Sentiment als Exit-Beschleuniger (nicht nur Entry-Gate)
- Walk-Forward-Optimierung der Parameter statt fixer Defaults
- Equity-Kurven-Grafik in der GUI
- Krypto über ccxt hinter dem Broker-Interface

## 8. Änderungsprotokoll

| Datum | Änderung | Begründung |
|---|---|---|
| 2026-07-10 | NEU: Strategie MacroRot (§2.8) — vol-adj. Momentum-Rotation mit regionalem Makro-Score (Fed/Kurve/HY-Spread/CPI für US-Titel, EZB/Bund/HICP für Europa) als Ranking-Tilt + Entry-Gate; FRED-Reihen im Hub dafür um DFF, ECBDFR, DE-10J, HICP erweitert (insgesamt 17 Reihen inkl. Dollar, Öl, NFP, Industrieproduktion, Konsumentenstimmung). Mechanik verifiziert (Gate blockiert rote Regionen komplett, Neutral-Fallback identisch zum Momentum-Kern); Alpha-Messung folgt nach erstem FRED-Abruf auf dem Nutzer-Rechner (Sandbox ohne FRED-Zugang) | Auftrag: neue Makro-Daten in neue Strategie einbeziehen, marktspezifisch differenziert (Fed/EZB) |
| 2026-07-10 | Umbau nach GUI_KONZEPT.md umgesetzt: Daten-Hub (hub.db: Fundamentals + Migration der Screener-DB, Quotes, Earnings-/Ereignis-Kalender, FRED-Makro, Corporate Actions, Universen-Snapshots, Score-Historie, fetch_log), eine GUI mit 4 Seiten (Daten/TradeBot/ValueScreener/Backtest, tradingbot/ui/), Profile "live"/"test", mehrere Strategien parallel mit Kapital-Budgets (Positions-Eigentümer in der Bot-DB), Screening-Registry (Value-Score, Piotroski, Magic Formula), MoQu-Qualitäts-Overlay liest jetzt den Hub, Feeds im Tageszyklus; EOD-Kurse/News-Archiv bleiben bewusst dateibasiert (im Hub registriert) | Auftrag: dokumentierte Umbauten umsetzen; Details und Abweichungen in GUI_KONZEPT.md §Stand |
| 2026-07-08 | Segment- (Sektor, Vol-Drittel) und Marktphasen-Analyse (Bulle/Seitwärts/Bär) als Standard-Output der Testumgebung; erste Befunde in §4.4 | Anweisung: bei Tests auf Gruppen- und Phasen-Outperformance achten |
| 2026-07-08 | Volllauf-Backtest (headless) deckte auf: MoQu wird über 2015–2026 vom Kill-Switch gestoppt — Ursache Vollinvestition (Vol-Ranking → große Positionen nach 1%-Regel), nicht die Zufallsfenster-Metriken; Stop-Out-Abkühlphase (cooldown_days=10) als struktureller Fix für die Rebuy-Schleife in Backtester+Engine; Paper-Trading-Start (5.000, S&P 500, Tageszyklus 22:15) bewusst mit Momentum-Rotation (einzige Konfig ohne Kill im Volllauf, CAGR +12,7 %, MaxDD −11,8 %); Trading-Schalter (aktiv/pausiert, persistent) im Dashboard; MoQu-Fix per Portfolio-Vol-Targeting bleibt oberster Backlog-Punkt | Volllauf ist der härtere Test als Fenster-Mediane; Paper-Konto verdient die überlebensfähigste Konfiguration |
| 2026-07-08 | Makro-Ampel um datenfreie 4. Komponente (realisierte Index-Vola) erweitert und im Harness gemessen: halbiert Kill-Läufe robust OOS (16→7/90) bei leicht besserer Rendite — bleibt Default; Markt-Modus nur noch mit Ampel empfohlen (§4.3) | Auftrag: Makro-Daten ergänzen, selbstständig verbessern |
| 2026-07-08 | Iteration "Markt schlagen": Halte-Puffer als Default (exit_rank_mult=2, robust bestätigt), Markt-Modus als dokumentiertes Preset; In-Sample-Sieg über SPY hielt Out-of-Sample nicht — Protokoll in §4.2 | Auftrag Iteration; OOS-Disziplin gegen Überanpassung |
| 2026-07-08 | NEU: Strategie MoQu (vol-adj. Momentum + Qualitäts-Overlay), Makro-Ampel (Index/VIX/Kredit) + Ereignis-Blackout, Robustheits-Harness (zufällige Fenster × Teiluniversen), Strategien vektorisiert (Backtests in Sekunden), SPY-Benchmark in GUI, NaT-Härtung Kurs-Cache | Aufträge: neue Strategie mit Business Case, Makro einbeziehen, wiederholt gegen zufällige Zeiträume testen |
| 2026-07-08 | Aktienquelle wie im Screener (Index-Universen S&P 500, Nasdaq 100, DAX, SMI, EuroStoxx 50, FTSE 100, Global 2000, Watchlists) für Bot UND Backtest-Suite; Intraday-Datenschicht mit wachsendem Archiv (IBKR/Yahoo/Tiingo/FMP); Backtest-Suite in der GUI mit Intervall-Wahl; API-Keys in Einstellungen | Nutzeranforderung: ganze Indizes tracken, Backtests aus der GUI, Intraday-Frage geklärt |
| 2026-07-08 | Erstfassung: 4 Strategien (SMA, Donchian, RSI-MeanRev, Momentum-Rotation), Sentiment-Gate, Risk-Schicht (1%-Regel, ATR-Stops, Regime-Filter, Kill-Switch), Portfolio-Backtester, PaperBroker + IBKR-Adapter (ib_async), Steuerungs-GUI | Ausbau vom Backtest-Skript zum steuerbaren Bot; Strategien nach Evidenzlage ausgewählt |
