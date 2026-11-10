"""Lecture des relevés pygazpar."""

from datetime import date

from custom_components.conso_grdf.donnees import (
    premier_du_mois,
    releves_par_jour,
    somme,
)


def test_releves():
    jours = releves_par_jour([
        {"time_period": "08/11/2026", "volume_m3": 3.2, "energy_kwh": 36.1, "end_index_m3": 12345.6,
         "temperature_degC": 7.5, "converter_factor_kwh/m3": 11.28},
        {"time_period": "09/11/2026", "volume_m3": None, "energy_kwh": None},
        {"time_period": "pas une date", "volume_m3": 1},
        {"time_period": "2026-11-07", "volume_m3": "2.5", "energy_kwh": "28.2"},
    ])
    assert set(jours) == {date(2026, 11, 8), date(2026, 11, 7)}
    assert jours[date(2026, 11, 8)] == {"volume": 3.2, "energie": 36.1, "index": 12345.6, "temperature": 7.5, "coef": 11.28}
    assert jours[date(2026, 11, 7)]["volume"] == 2.5


def test_somme():
    jours = {date(2026, 10, 31): {"energie": 10.0}, date(2026, 11, 1): {"energie": 20.0}, date(2026, 11, 2): {"energie": None}}
    assert somme(jours, "energie", date(2026, 11, 1), date(2026, 12, 1)) == (20.0, 1)
    assert somme(jours, "energie", date(2026, 9, 1), date(2026, 10, 1)) == (None, 0)
    assert premier_du_mois(date(2026, 1, 3), -1) == date(2025, 12, 1)
