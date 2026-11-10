"""Statistiques du tableau Énergie, avec les mêmes identifiants que gazpar2haws.

sensor.<préfixe>_volume (m³) et sensor.<préfixe>_energy (kWh) : une valeur par jour, à minuit
(heure locale), avec la somme cumulée. L'import reprend à la suite de la dernière valeur
enregistrée, qu'elle vienne de gazpar2haws ou de cette intégration.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    get_last_statistics,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

# (suffixe, clé dans les relevés, nom, classe d'unité, unité) — comme gazpar2haws
SERIES = (
    ("volume", "volume", "Gazpar2HAWS Volume", "volume", "m³"),
    ("energy", "energie", "Gazpar2HAWS Energy", "energy", "kWh"),
)


def statistic_id(prefixe: str, suffixe: str) -> str:
    return f"sensor.{prefixe}_{suffixe}"


async def async_dernier_jour(hass: HomeAssistant, sid: str) -> tuple[date | None, float]:
    """(jour de la dernière valeur, somme cumulée) ou (None, 0)."""
    resultat = await get_instance(hass).async_add_executor_job(get_last_statistics, hass, 1, sid, True, {"sum"})
    lignes = resultat.get(sid) or []
    if not lignes:
        return None, 0.0
    debut = lignes[0]["start"]
    if isinstance(debut, (int, float)):
        debut = dt_util.utc_from_timestamp(debut)
    return dt_util.as_local(debut).date(), float(lignes[0].get("sum") or 0.0)


async def async_besoin(hass: HomeAssistant, prefixe: str, jours_initiaux: int, aujourdhui: date) -> date:
    """Premier jour à importer, toutes séries confondues."""
    debuts = []
    for suffixe, *_ in SERIES:
        dernier, _somme = await async_dernier_jour(hass, statistic_id(prefixe, suffixe))
        debuts.append(dernier + timedelta(days=1) if dernier else aujourdhui - timedelta(days=jours_initiaux))
    return min(debuts)


async def async_mettre_a_jour(
    hass: HomeAssistant,
    prefixe: str,
    jours: dict[date, dict[str, float | None]],
    jours_initiaux: int,
    aujourdhui: date,
) -> date | None:
    """Ajoute les jours manquants ; retourne le dernier jour présent dans toutes les séries."""
    fuseau = dt_util.get_default_time_zone()
    fins: list[date | None] = []
    for suffixe, cle, nom, classe, unite in SERIES:
        sid = statistic_id(prefixe, suffixe)
        dernier, somme = await async_dernier_jour(hass, sid)
        depuis = dernier + timedelta(days=1) if dernier else aujourdhui - timedelta(days=jours_initiaux)
        nouvelles: list[StatisticData] = []
        for jour in sorted(j for j in jours if depuis <= j < aujourdhui):
            valeur = jours[jour].get(cle)
            if valeur is None:
                break  # pas de trou : on reprendra à ce jour-là
            somme += valeur
            nouvelles.append(
                StatisticData(start=datetime.combine(jour, time(), fuseau), state=round(somme, 3), sum=round(somme, 3))
            )
        if nouvelles:
            async_import_statistics(
                hass,
                StatisticMetaData(
                    mean_type=StatisticMeanType.NONE,
                    has_sum=True,
                    name=nom,
                    source="recorder",
                    statistic_id=sid,
                    unit_class=classe,
                    unit_of_measurement=unite,
                ),
                nouvelles,
            )
            _LOGGER.debug("%s : %d jours ajoutés", sid, len(nouvelles))
            fins.append(nouvelles[-1]["start"].date())
        else:
            fins.append(dernier)
    return None if any(f is None for f in fins) else min(fins)
