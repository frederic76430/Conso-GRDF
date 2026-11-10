"""Tests avec Home Assistant : configuration, capteurs, statistiques gazpar2haws."""

from datetime import date, datetime, time, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    statistics_during_period,
)
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
)
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.conso_grdf.api import ApiError, AuthError
from custom_components.conso_grdf.const import (
    CONF_PCE,
    CONF_PREFIXE,
    CONF_STATISTIQUES,
    CONF_TYPE_CONSO,
    DOMAIN,
)

PCE = "21546000000000"
LIRE = "custom_components.conso_grdf.api.GrdfClient.async_lire"
PCES = "custom_components.conso_grdf.config_flow.async_pces"


class FauxGrdf:
    """3 m³ et 33 kWh par jour, index qui monte ; données jusqu'à « dernier » inclus."""

    def __init__(self, dernier: date) -> None:
        self.dernier = dernier
        self.appels: list[tuple[date, date]] = []

    async def lire(self, debut: date, fin: date):
        self.appels.append((debut, fin))
        res, j = [], debut
        while j <= min(fin, self.dernier):
            n = (j - date(2025, 1, 1)).days
            res.append({"time_period": j.strftime("%d/%m/%Y"), "volume_m3": 3.0, "energy_kwh": 33.0,
                        "end_index_m3": 1000 + 3.0 * n, "temperature_degC": 8.0, "converter_factor_kwh/m3": 11.0})
            j += timedelta(days=1)
        return res


def entree(options=None) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN, unique_id=PCE, title=f"Gazpar {PCE}",
        data={CONF_USERNAME: "moi@exemple.fr", CONF_PASSWORD: "x", CONF_PCE: PCE},
        options=options or {CONF_TYPE_CONSO: "informative", CONF_STATISTIQUES: False, CONF_PREFIXE: "gazpar2haws"},
    )


async def installer(hass, entry, faux):
    entry.add_to_hass(hass)
    with patch(LIRE, new_callable=AsyncMock, side_effect=faux.lire):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


def etat(hass, cle):
    eid = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{PCE}_{cle}")
    return hass.states.get(eid) if eid else None


async def stats(hass, sid):
    res = await get_instance(hass).async_add_executor_job(
        statistics_during_period, hass, dt_util.parse_datetime("2024-01-01T00:00:00+00:00"), None, {sid}, "hour", None, {"state", "sum"}
    )
    return res.get(sid, [])


@pytest.fixture
async def paris(hass, freezer):
    await hass.config.async_set_time_zone("Europe/Paris")
    freezer.move_to("2026-11-10 09:00:00+01:00")
    return freezer


async def test_capteurs(hass, paris):
    faux = FauxGrdf(date(2026, 11, 9))
    entry = entree()
    await installer(hass, entry, faux)
    assert entry.state is ConfigEntryState.LOADED
    assert etat(hass, "energie_jour").state == "33.0"
    assert etat(hass, "energie_jour").attributes["date"] == "2026-11-09"
    assert etat(hass, "energie_jour").attributes["temperature"] == 8.0
    assert float(etat(hass, "energie_mois").state) == 297.0
    assert float(etat(hass, "volume_mois_dernier").state) == 93.0
    assert float(etat(hass, "energie_annee").state) == pytest.approx(33.0 * 313)
    assert float(etat(hass, "index").state) == pytest.approx(1000 + 3.0 * 677)
    # Lecture depuis le 1er janvier, une seule connexion
    assert faux.appels == [(date(2026, 1, 1), date(2026, 11, 10))]


async def test_relecture_seulement_si_manque(hass, paris):
    faux = FauxGrdf(date(2026, 11, 8))  # GRDF en retard d'un jour
    await installer(hass, entree(), faux)
    with patch(LIRE, new_callable=AsyncMock, side_effect=faux.lire):
        coordinator = hass.config_entries.async_entries(DOMAIN)[0].runtime_data
        await coordinator.async_refresh()
        assert len(faux.appels) == 2  # il manquait le 9 : relu
        faux.dernier = date(2026, 11, 9)
        await coordinator.async_refresh()
        await coordinator.async_refresh()
    assert len(faux.appels) == 3  # complet : plus d'appel
    assert etat(hass, "energie_jour").attributes["date"] == "2026-11-09"


async def test_erreur_garde_les_valeurs(hass, paris):
    faux = FauxGrdf(date(2026, 11, 8))
    await installer(hass, entree(), faux)
    with patch(LIRE, new_callable=AsyncMock, side_effect=ApiError("429")):
        await hass.config_entries.async_entries(DOMAIN)[0].runtime_data.async_refresh()
    assert etat(hass, "energie_jour").state == "33.0"


async def test_mot_de_passe_refuse(hass, paris):
    entry = entree()
    entry.add_to_hass(hass)
    with patch(LIRE, new_callable=AsyncMock, side_effect=AuthError("non")):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert any(f["context"]["source"] == SOURCE_REAUTH for f in hass.config_entries.flow.async_progress())


async def test_statistiques_premier_import(hass, paris):
    faux = FauxGrdf(date(2026, 11, 9))
    await installer(hass, entree({CONF_TYPE_CONSO: "informative", CONF_STATISTIQUES: True, CONF_PREFIXE: "gazpar2haws"}), faux)
    await async_wait_recording_done(hass)
    energie = await stats(hass, "sensor.gazpar2haws_energy")
    assert len(energie) == 365
    assert energie[-1]["sum"] == pytest.approx(33.0 * 365)
    assert dt_util.as_local(dt_util.utc_from_timestamp(energie[-1]["start"])) == datetime(2026, 11, 9, tzinfo=dt_util.get_default_time_zone())
    volume = await stats(hass, "sensor.gazpar2haws_volume")
    assert volume[-1]["sum"] == pytest.approx(3.0 * 365)
    # Lecture élargie à 365 jours pour le premier import
    assert faux.appels[0][0] == date(2025, 11, 10)


async def test_statistiques_reprise_gazpar2haws(hass, paris):
    fuseau = dt_util.get_default_time_zone()
    for suffixe, classe, unite, somme in (("volume", "volume", "m³", 5000.0), ("energy", "energy", "kWh", 55000.0)):
        async_import_statistics(
            hass,
            StatisticMetaData(mean_type=StatisticMeanType.NONE, has_sum=True, name="x", source="recorder",
                              statistic_id=f"sensor.maison_gaz_{suffixe}", unit_class=classe, unit_of_measurement=unite),
            [StatisticData(start=datetime.combine(date(2026, 11, 6), time(), fuseau), state=somme, sum=somme)],
        )
    await async_wait_recording_done(hass)
    faux = FauxGrdf(date(2026, 11, 9))
    await installer(hass, entree({CONF_TYPE_CONSO: "informative", CONF_STATISTIQUES: True, CONF_PREFIXE: "maison_gaz"}), faux)
    await async_wait_recording_done(hass)
    energie = await stats(hass, "sensor.maison_gaz_energy")
    assert [e["sum"] for e in energie] == pytest.approx([55000.0, 55033.0, 55066.0, 55099.0])
    # Rien n'est relu avant le 1er janvier : les statistiques ne manquaient que depuis le 7 novembre
    assert faux.appels[0][0] == date(2026, 1, 1)

    # Le lendemain, avec les statistiques à jour et les données complètes : aucun appel
    with patch(LIRE, new_callable=AsyncMock, side_effect=faux.lire):
        await hass.config_entries.async_entries(DOMAIN)[0].runtime_data.async_refresh()
    assert len(faux.appels) == 1


async def test_ajout_par_l_interface(hass, paris):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    with patch(PCES, new_callable=AsyncMock, side_effect=AuthError("non")):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_USERNAME: "a@b.fr", CONF_PASSWORD: "x"})
    assert result["errors"] == {"base": "invalid_auth"}
    with patch(PCES, new_callable=AsyncMock, return_value=[PCE, "1"]), patch(
        "custom_components.conso_grdf.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_USERNAME: "a@b.fr", CONF_PASSWORD: "x"})
        assert result["step_id"] == "pce"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_PCE: PCE})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_USERNAME: "a@b.fr", CONF_PASSWORD: "x", CONF_PCE: PCE}


async def test_options(hass, paris):
    faux = FauxGrdf(date(2026, 11, 9))
    entry = entree()
    await installer(hass, entry, faux)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_TYPE_CONSO: "published", CONF_STATISTIQUES: False, CONF_PREFIXE: "Mon Gaz"}
    )
    assert result["errors"] == {CONF_PREFIXE: "invalid_prefixe"}
    with patch(LIRE, new_callable=AsyncMock, side_effect=faux.lire):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_TYPE_CONSO: "published", CONF_STATISTIQUES: False, CONF_PREFIXE: "gazpar2haws"}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert hass.config_entries.async_entries(DOMAIN)[0].runtime_data.client.type_conso == "published"
