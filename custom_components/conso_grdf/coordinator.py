"""Coordinateur : relit GRDF quelques fois par jour, seulement s'il manque des données."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import ApiError, AuthError, GrdfClient
from .const import (
    CONF_PREFIXE,
    CONF_STATISTIQUES,
    DOMAIN,
    JOURS_INITIAUX,
    PREFIXE_DEFAUT,
    STORAGE_VERSION,
)
from .donnees import premier_du_mois, releves_par_jour
from .statistiques import async_besoin, async_mettre_a_jour

_LOGGER = logging.getLogger(__name__)

type ConsoGrdfConfigEntry = ConfigEntry[ConsoGrdfCoordinator]


class ConsoGrdfCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """data = {"jours": {date: {...}}, "lu_le": datetime | None}"""

    config_entry: ConsoGrdfConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConsoGrdfConfigEntry, client: GrdfClient) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=None)
        self.client = client
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._charge = False
        self._stats_jusqua: date | None = None
        self._stats_connues = False

    @property
    def statistiques(self) -> bool:
        return bool(self.config_entry.options.get(CONF_STATISTIQUES, False))

    @property
    def prefixe(self) -> str:
        return (self.config_entry.options.get(CONF_PREFIXE) or PREFIXE_DEFAUT).strip()

    async def _async_charger(self) -> dict[str, Any]:
        brut = await self._store.async_load() or {}
        lu_le = brut.get("lu_le")
        return {
            "jours": {date.fromisoformat(k): v for k, v in (brut.get("jours") or {}).items()},
            "lu_le": dt_util.parse_datetime(lu_le) if lu_le else None,
        }

    async def _async_sauver(self, data: dict[str, Any]) -> None:
        await self._store.async_save(
            {
                "jours": {k.isoformat(): v for k, v in data["jours"].items()},
                "lu_le": data["lu_le"].isoformat() if data.get("lu_le") else None,
            }
        )

    def _complet(self, data: dict[str, Any], hier: date) -> bool:
        jours = data["jours"]
        if not jours or max(jours) < hier:
            return False
        if self.statistiques and (self._stats_jusqua is None or self._stats_jusqua < hier):
            return False
        return True

    async def _async_update_data(self) -> dict[str, Any]:
        if not self._charge:
            self._charge = True
            data = await self._async_charger()
        else:
            data = dict(self.data or {})

        aujourdhui = dt_util.now().date()
        hier = aujourdhui - timedelta(days=1)
        besoin_stats: date | None = None
        if self.statistiques:
            besoin_stats = await async_besoin(self.hass, self.prefixe, JOURS_INITIAUX, aujourdhui)
            self._stats_jusqua = besoin_stats - timedelta(days=1)

        if data.get("lu_le") and self._complet(data, hier):
            return data

        # Lecture : depuis le 1er janvier (ou le 1er du mois dernier), plus tôt si les statistiques en ont besoin
        debut = min(date(aujourdhui.year, 1, 1), premier_du_mois(aujourdhui, -1))
        if besoin_stats is not None:
            debut = min(debut, besoin_stats)
        try:
            jours = releves_par_jour(await self.client.async_lire(debut, aujourdhui))
        except AuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ApiError as err:
            if data.get("lu_le"):
                _LOGGER.warning("Relecture GRDF impossible, valeurs précédentes conservées : %s", err)
                return data
            raise UpdateFailed(str(err)) from err

        garde = min(date(aujourdhui.year, 1, 1), premier_du_mois(aujourdhui, -1))
        data["jours"] = {j: v for j, v in {**data["jours"], **jours}.items() if j >= garde}

        if self.statistiques:
            self._stats_jusqua = await async_mettre_a_jour(
                self.hass, self.prefixe, {**data["jours"], **jours}, JOURS_INITIAUX, aujourdhui
            )

        data["lu_le"] = dt_util.now()
        await self._async_sauver(data)
        return data
