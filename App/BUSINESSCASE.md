# Business Case: Systematisches Trading mit dem TradingBot

Stand 2026-07-08. Grundlage: Robustheits-Sweep über 90 zufällige
(Zeitfenster × Teiluniversum)-Backtests je Variante auf echten
S&P-500-Daten 2010–2026 (STRATEGIE.md §4.1), alle Zahlen NACH
Handelskosten (IBKR-Kommission + 5 bp Slippage). Kein Renditeversprechen,
keine Anlageberatung — ein Rechenmodell mit offengelegten Annahmen.

## 1. Das Produkt

**Strategie:** MoQu — vol-adjustiertes 12-Monats-Momentum über einen
Index (Default S&P 500), Top 8 Titel, monatliche Rotation,
Qualitäts-Overlay aus reporteten Quartalszahlen, Makro-Ampel
(Index-Trend/VIX/Kredit) und Ereignis-Blackout als Bremsen, volle
Risk-Schicht (1%-Regel, Trailing-Stops, Kill-Switch).

**Rhythmus: Tagesbasis — bewusst.** Ein Zyklus pro Tag nach
Börsenschluss reicht für monatliche Rotation vollständig aus, kostet
nichts extra (Yahoo EOD gratis) und hält die Handelskosten klein
(~50–70 Orders/Jahr). Intraday würde Datenabos (~180–400 €/Jahr),
mehr Orders und mehr Fehlerquellen bedeutet — bei UNBELEGTER
Mehrrendite (STRATEGIE.md §1). Tagesbasis ist damit nicht die bequeme,
sondern die wirtschaftlich richtige Wahl für dieses Produkt.

## 2. Ertragsannahmen (aus dem Robustheits-Sweep, nicht aus einem Chart)

| Szenario | Annahme p.a. | Herkunft |
|---|---|---|
| Basis | +13,4 % | Median über 90 Zufallsfenster |
| Konservativ | +5 % | ~25 %-Quantil der Fenster, Sicherheitsabschlag für Survivorship |
| Stress (Einzeljahr) | −18 % | schlechtestes beobachtetes Fenster; Kill-Switch begrenzt bei −25 % hart |

## 3. Kosten (jährlich)

| Posten | Stufe 0/1 (Paper) | Stufe 2 (Live, Basis) | Optionale Ausbaustufe |
|---|---|---|---|
| Kursdaten EOD (Yahoo/Tiingo free) | 0 € | 0 € | — |
| Fundamentaldaten (FMP free) | 0 € | 0 € | FMP Starter ~250 €/J (tiefe Historie, Kalender) |
| IBKR Marktdaten-Abo | 0 € | 0 € (verzögert reicht für EOD) | ~170 €/J (Echtzeit, nur für Intraday nötig) |
| IBKR Kommissionen (~60 Orders × ~1–2 USD) | 0 € | ~60–120 € | steigt mit Ordergröße kaum |
| Slippage | in Backtests enthalten | dito | — |
| Strom/PC | vernachlässigbar | vernachlässigbar | — |
| **Summe Fixkosten** | **0 €** | **~60–120 €** | +~420 €/J |

Investitions-Grundsatz: **Abos erst, wenn der Robustheits-Harness deren
Mehrwert beweist** (z.B. Intraday-Variante schlägt Tagesvariante nach
Kosten über viele Zufallsfenster). Bis dahin: Basis-Setup, 0 € Fixkosten.

## 4. Netto-Cashflow-Rechnung (Basis-Setup, Kosten ~100 €/Jahr)

| Kapital | Basis (+13,4 %) | Konservativ (+5 %) | Stressjahr (−18 %) |
|---|---|---|---|
| 5.000 € | +570 € | +150 € | −1.000 € |
| 10.000 € | +1.240 € | +400 € | −1.900 € |
| 25.000 € | +3.250 € | +1.150 € | −4.600 € |
| 50.000 € | +6.600 € | +2.400 € | −9.100 € |
| 100.000 € | +13.300 € | +4.900 € | −18.100 € |

**Break-even:** Im konservativen Szenario ist der Cashflow ab ~2.000 €
Kapital positiv; unter ~5.000 € fressen Mindestkommissionen und
Rundungseffekte (Positionsgrößen!) aber spürbar an der Rendite —
sinnvolle Untergrenze für Stufe 2 ist daher **≥ 10.000 €**. Mit der
optionalen Abo-Stufe (+420 €/J) verschiebt sich der konservative
Break-even auf ~10.500 € — ein weiterer Grund, sie erst nach bewiesenem
Mehrwert zu buchen. Steuern (in DE: Abgeltungsteuer auf realisierte
Gewinne) sind nicht modelliert und individuell zu prüfen.

## 5. Stufenplan (Gate-Kriterien statt Bauchgefühl)

| Stufe | Dauer | Gate zum Weitergehen |
|---|---|---|
| 0: Simulation (PaperBroker, Auto-Modus täglich) | 4+ Wochen | Equity-Kurve konsistent mit Backtest-Verteilung, keine technischen Aussetzer |
| 1: IBKR Paper (TWS/Gateway) | 4–8 Wochen | Fills/Kosten real wie simuliert, Entscheidungs-Log sauber |
| 2: Live, klein (≥10.000 €, Kill-Switch 20 %) | 6+ Monate | rollierende 6-Monats-Rendite innerhalb der Sweep-Verteilung |
| 3: Skalieren / Abos / Intraday-Experimente | — | Harness beweist Mehrwert der Investition NACH Kosten |

## 6. Risiken (ehrlich)

- **Survivorship-Bias:** Getestet wurde die heutige Indexliste — reale
  Erwartung eher Richtung konservatives Szenario. Der Paper-Betrieb ist
  der eigentliche Out-of-Sample-Test.
- **Verteilung statt Garantie:** 17 % der Zufallsfenster waren negativ;
  einzelne Jahre können deutlich verlieren (Kill-Switch begrenzt hart).
- **SPY schlagen ist nicht das Ziel-Kriterium:** In der US-Dauerhausse
  lag der Median-Exzess gegen SPY bei −2 %. Der Mehrwert ist
  Regelmäßigkeit (83 % positive Fenster) bei ~halbem Drawdown — wer
  reinen Indexertrag will, kauft den ETF.
- **Betriebsrisiken:** Datenausfälle (gepuffert durch Cache/Provider-
  Kette), IBKR-Verbindung, Bugs — deshalb Stufen mit Gates.

## 7. Fortschreibung

Dieses Dokument wird wie STRATEGIE.md/ANALYSE.md fortgeschrieben: neue
Sweep-Ergebnisse (weitere Indizes wie DAX/SMI, sobald deren Kurs-Cache
gefüllt ist; wachsende Fundamentals-/News-/Intraday-Archive) ersetzen
die Annahmen in §2 — Änderungen mit Datum und Begründung in STRATEGIE.md §8.
