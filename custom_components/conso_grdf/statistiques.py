"""Statistiques du tableau Énergie, avec les mêmes identifiants que gazpar2haws.

sensor.<préfixe>_volume (m³), sensor.<préfixe>_energy (kWh) et les coûts
sensor.<préfixe>_{consumption,subscription,transport,energy_taxes,total}_cost (EUR) :
une valeur par jour, à minuit (heure locale), avec la somme cumulée. L'import reprend à la
suite de la dernière valeur enregistrée, qu'elle vienne de gazpar2haws ou de cette intégration.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
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
    statistics_during_period,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

type Jours = dict[date, dict[str, float | None]]
type Tarifs = dict[str, float]

# Clés des tarifs (TTC) : €/kWh pour la consommation et les taxes, €/jour pour l'abonnement et le transport
TARIFS = ("prix_kwh", "taxes_kwh", "abonnement_jour", "transport_jour")


def _energie(
    cle_tarif: str,
) -> Callable[[dict[str, float | None], Tarifs], float | None]:
    return lambda v, t: (
        None if v.get("energie") is None else v["energie"] * t[cle_tarif]
    )


def _fixe(cle_tarif: str) -> Callable[[dict[str, float | None], Tarifs], float | None]:
    return lambda v, t: None if v.get("energie") is None else t[cle_tarif]


# (suffixe, nom gazpar2haws, classe d'unité, unité, valeur du jour)
SERIES = (
    ("volume", "Gazpar2HAWS Volume", "volume", "m³", lambda v, t: v.get("volume")),
    ("energy", "Gazpar2HAWS Energy", "energy", "kWh", lambda v, t: v.get("energie")),
)
SERIES_COUTS = (
    (
        "consumption_cost",
        "Gazpar2HAWS Consumption Cost",
        None,
        "EUR",
        _energie("prix_kwh"),
    ),
    (
        "subscription_cost",
        "Gazpar2HAWS Subscription Cost",
        None,
        "EUR",
        _fixe("abonnement_jour"),
    ),
    (
        "transport_cost",
        "Gazpar2HAWS Transport Cost",
        None,
        "EUR",
        _fixe("transport_jour"),
    ),
    (
        "energy_taxes_cost",
        "Gazpar2HAWS Energy Taxes Cost",
        None,
        "EUR",
        _energie("taxes_kwh"),
    ),
    (
        "total_cost",
        "Gazpar2HAWS Total Cost",
        None,
        "EUR",
        lambda v, t: (
            None
            if v.get("energie") is None
            else v["energie"] * (t["prix_kwh"] + t["taxes_kwh"])
            + t["abonnement_jour"]
            + t["transport_jour"]
        ),
    ),
)


def statistic_id(prefixe: str, suffixe: str) -> str:
    return f"sensor.{prefixe}_{suffixe}"


def series(tarifs: Tarifs | None) -> tuple:
    return SERIES + (SERIES_COUTS if tarifs else ())


async def async_dernier_jour(
    hass: HomeAssistant, sid: str
) -> tuple[date | None, float]:
    """(jour de la dernière valeur, somme cumulée) ou (None, 0)."""
    resultat = await get_instance(hass).async_add_executor_job(
        get_last_statistics, hass, 1, sid, True, {"sum"}
    )
    lignes = resultat.get(sid) or []
    if not lignes:
        return None, 0.0
    debut = lignes[0]["start"]
    if isinstance(debut, (int, float)):
        debut = dt_util.utc_from_timestamp(debut)
    return dt_util.as_local(debut).date(), float(lignes[0].get("sum") or 0.0)


async def async_besoin(
    hass: HomeAssistant,
    prefixe: str,
    tarifs: Tarifs | None,
    jours_initiaux: int,
    aujourdhui: date,
) -> date:
    """Premier jour à importer, toutes séries confondues."""
    debuts = []
    for suffixe, *_ in series(tarifs):
        dernier, _somme = await async_dernier_jour(hass, statistic_id(prefixe, suffixe))
        debuts.append(
            dernier + timedelta(days=1)
            if dernier
            else aujourdhui - timedelta(days=jours_initiaux)
        )
    return min(debuts)


async def async_apprendre_tarifs(
    hass: HomeAssistant, prefixe: str, nb_jours: int = 60
) -> Tarifs | None:
    """Retrouve les tarifs dans les coûts déjà enregistrés par gazpar2haws (sur les derniers jours connus)."""
    dernier, _ = await async_dernier_jour(hass, statistic_id(prefixe, "total_cost"))
    if dernier is None:
        return None
    fuseau = dt_util.get_default_time_zone()
    debut = datetime.combine(dernier - timedelta(days=nb_jours), time(), fuseau)
    ids = {statistic_id(prefixe, s) for s in ("energy", *(c[0] for c in SERIES_COUTS))}
    res = await get_instance(hass).async_add_executor_job(
        statistics_during_period, hass, debut, None, ids, "hour", None, {"sum"}
    )
    lignes = res.get(statistic_id(prefixe, "total_cost")) or []
    if len(lignes) < 2:
        return None
    # Fenêtre commune : du premier au dernier relevé de coût total (écart réel en jours)
    t0, t1 = lignes[0]["start"], lignes[-1]["start"]
    jours = round((t1 - t0) / 86400)

    def variation(suffixe: str) -> float:
        par_t = {
            r["start"]: r.get("sum")
            for r in res.get(statistic_id(prefixe, suffixe)) or []
        }
        if par_t.get(t0) is None or par_t.get(t1) is None:
            return 0.0
        return float(par_t[t1]) - float(par_t[t0])

    energie = variation("energy")
    if energie <= 0 or jours <= 0:
        return None
    return {
        "prix_kwh": round(variation("consumption_cost") / energie, 5),
        "taxes_kwh": round(variation("energy_taxes_cost") / energie, 5),
        "abonnement_jour": round(variation("subscription_cost") / jours, 5),
        "transport_jour": round(variation("transport_cost") / jours, 5),
    }


async def async_mettre_a_jour(
    hass: HomeAssistant,
    prefixe: str,
    jours: Jours,
    tarifs: Tarifs | None,
    jours_initiaux: int,
    aujourdhui: date,
) -> date | None:
    """Ajoute les jours manquants ; retourne le dernier jour présent dans toutes les séries."""
    fuseau = dt_util.get_default_time_zone()
    fins: list[date | None] = []
    for suffixe, nom, classe, unite, valeur_du_jour in series(tarifs):
        sid = statistic_id(prefixe, suffixe)
        dernier, somme = await async_dernier_jour(hass, sid)
        depuis = (
            dernier + timedelta(days=1)
            if dernier
            else aujourdhui - timedelta(days=jours_initiaux)
        )
        nouvelles: list[StatisticData] = []
        for jour in sorted(j for j in jours if depuis <= j < aujourdhui):
            valeur = valeur_du_jour(jours[jour], tarifs)
            if valeur is None:
                break  # pas de trou : on reprendra à ce jour-là
            somme += valeur
            nouvelles.append(
                StatisticData(
                    start=datetime.combine(jour, time(), fuseau),
                    state=round(somme, 4),
                    sum=round(somme, 4),
                )
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
