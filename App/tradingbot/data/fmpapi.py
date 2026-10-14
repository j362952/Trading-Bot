"""Zentraler FMP-Zugriff mit stable/v3-Fallback.

Hintergrund: FMP hat die alten `/api/v3/…`-Endpunkte für NEU registrierte
Keys abgeschaltet ("Legacy Endpoint") — neue Keys funktionieren nur mit
der `/stable/…`-API, alte Keys teils nur mit v3. Dieser Helfer probiert
beide Familien durch und liefert den ersten Treffer; FMP-Fehlertexte
(auch als HTTP-200-JSON verpackt) werden gesammelt und im Fehlerfall
komplett gemeldet — so zeigt das Abruf-Log der Daten-Seite die echte
Ursache (z.B. "Exclusive Endpoint" = im Gratis-Tarif nicht enthalten).
"""

from __future__ import annotations

import requests

BASE_STABLE = "https://financialmodelingprep.com/stable"
BASE_V3 = "https://financialmodelingprep.com/api/v3"


class ProviderLimitReached(Exception):
    """FMP-Tageslimit (HTTP 429) — Aufrufer schaltet FMP für den Rest des Laufs ab."""


def fmp_get(stable_path: str | None, v3_path: str | None,
            params: dict, key: str, timeout: int = 30):
    """GET gegen FMP: erst /stable (neue Keys), dann /api/v3 (alte Keys).

    Rückgabe: geparstes JSON (Liste/Dict). Wirft ProviderLimitReached bei
    Limit, sonst RuntimeError mit allen gesammelten Fehlertexten.
    """
    errors: list[str] = []
    for base, path in ((BASE_STABLE, stable_path), (BASE_V3, v3_path)):
        if not path:
            continue
        label = f"{base.rsplit('/', 1)[-1]}/{path.split('?')[0]}"
        try:
            resp = requests.get(f"{base}/{path}", params={**params, "apikey": key},
                                timeout=timeout)
            if resp.status_code == 429:
                raise ProviderLimitReached("FMP-Tageslimit erreicht (HTTP 429)")
            try:
                data = resp.json()
            except ValueError:
                errors.append(f"{label}: HTTP {resp.status_code}, kein JSON")
                continue
            # FMP verpackt Fehler oft als JSON-Dict (auch mit HTTP 200/403)
            if isinstance(data, dict):
                msg = (data.get("Error Message") or data.get("message")
                       or data.get("error"))
                if msg:
                    errors.append(f"{label}: {msg}")
                    continue
            if resp.status_code >= 400:
                errors.append(f"{label}: HTTP {resp.status_code}")
                continue
            return data
        except ProviderLimitReached:
            raise
        except Exception as exc:
            errors.append(f"{label}: {exc}")
    raise RuntimeError(" | ".join(errors) or "FMP: keine Endpunkte konfiguriert")
