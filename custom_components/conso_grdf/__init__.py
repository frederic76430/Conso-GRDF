"""Intégration Conso GRDF : consommation de gaz (compteur Gazpar) depuis l'espace client GRDF."""

from __future__ import annotations

import random
from datetime import datetime

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_change

from .api import GrdfClient
from .const import CONF_PCE, CONF_TYPE_CONSO, HEURES_RELECTURE, TYPE_INFORMATIVE
from .coordinator import ConsoGrdfConfigEntry, ConsoGrdfCoordinator

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConsoGrdfConfigEntry) -> bool:
    client = GrdfClient(
        hass,
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        entry.data[CONF_PCE],
        entry.options.get(CONF_TYPE_CONSO, TYPE_INFORMATIVE),
    )
    coordinator = ConsoGrdfCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    minute = random.Random(entry.entry_id).randint(0, 59)

    async def _relire(_now: datetime) -> None:
        await coordinator.async_refresh()

    entry.async_on_unload(
        async_track_time_change(
            hass, _relire, hour=list(HEURES_RELECTURE), minute=minute, second=0
        )
    )
    entry.async_on_unload(entry.add_update_listener(_async_options_modifiees))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_modifiees(
    hass: HomeAssistant, entry: ConsoGrdfConfigEntry
) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConsoGrdfConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
