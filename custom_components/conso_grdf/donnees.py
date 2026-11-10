"""Lecture des relevés pygazpar et calculs (sans dépendance à Home Assistant)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

CHAMPS = {
    "volume": "volume_m3",
    "energie": "energy_kwh",
    "index": "end_index_m3",
    "temperature": "temperature_degC",
    "coef": "converter_factor_kwh/m3",
}


def _nombre(valeur: Any) -> float | None:
    if valeur in (None, ""):
        return None
    try:
        return float(valeur)
    except (TypeError, ValueError):
        return None


def _jour(texte: Any) -> date | None:
    """« 09/11/2026 » (format pygazpar) ou « 2026-11-09 »."""
    texte = str(texte or "")[:10]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(texte, fmt).date()
        except ValueError:
            continue
    return None


def releves_par_jour(
    releves: list[dict[str, Any]],
) -> dict[date, dict[str, float | None]]:
    """{jour: {"volume": m³, "energie": kWh, "index": m³, "temperature": °C, "coef": kWh/m³}}.

    Les jours sans volume ni énergie sont ignorés (GRDF n'a pas encore la donnée).
    """
    resultat: dict[date, dict[str, float | None]] = {}
    for releve in releves:
        jour = _jour(releve.get("time_period") or releve.get("start_date"))
        if jour is None:
            continue
        valeurs = {cle: _nombre(releve.get(champ)) for cle, champ in CHAMPS.items()}
        if valeurs["volume"] is None and valeurs["energie"] is None:
            continue
        resultat[jour] = valeurs
    return resultat


def somme(
    jours: dict[date, dict[str, float | None]], cle: str, debut: date, fin: date
) -> tuple[float | None, int]:
    """(somme de « cle » sur [debut ; fin[, nombre de jours), (None, 0) sans donnée."""
    valeurs = [
        v[cle] for j, v in jours.items() if debut <= j < fin and v.get(cle) is not None
    ]
    return (round(sum(valeurs), 3), len(valeurs)) if valeurs else (None, 0)


def premier_du_mois(jour: date, decalage: int = 0) -> date:
    mois = jour.year * 12 + jour.month - 1 + decalage
    return date(mois // 12, mois % 12 + 1, 1)
