"""Capteurs : gaz du dernier jour, du mois, du mois dernier, de l'année ; index ; température."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfEnergy,
    UnitOfTemperature,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import ConsoGrdfConfigEntry, ConsoGrdfCoordinator
from .donnees import premier_du_mois, somme

type Valeur = tuple[Any, dict[str, Any]]


def _dernier(cle: str, decimales: int = 3) -> Callable[[dict[str, Any], date], Valeur]:
    def calcul(data: dict[str, Any], _a: date) -> Valeur:
        jours = {j: v for j, v in data["jours"].items() if v.get(cle) is not None}
        if not jours:
            return None, {}
        j = max(jours)
        attrs: dict[str, Any] = {"date": j.isoformat()}
        if cle in ("volume", "energie"):
            for extra in ("temperature", "coef"):
                if data["jours"][j].get(extra) is not None:
                    attrs[extra] = data["jours"][j][extra]
        return round(jours[j][cle], decimales), attrs

    return calcul


def _periode(
    cle: str, debut: Callable[[date], date], fin: Callable[[date], date]
) -> Callable[[dict[str, Any], date], Valeur]:
    def calcul(data: dict[str, Any], aujourdhui: date) -> Valeur:
        d1, d2 = debut(aujourdhui), fin(aujourdhui)
        total, nb = somme(data["jours"], cle, d1, d2)
        if total is None:
            # Début de mois ou d'année : GRDF n'a encore rien publié
            return (0.0 if d1 >= aujourdhui - timedelta(days=4) else None), {"jours": 0}
        dernier = max(
            j
            for j, v in data["jours"].items()
            if d1 <= j < d2 and v.get(cle) is not None
        )
        return total, {
            "du": d1.isoformat(),
            "jusqu_au": dernier.isoformat(),
            "jours": nb,
        }

    return calcul


_MOIS = (premier_du_mois, lambda a: premier_du_mois(a, 1))
_MOIS_DERNIER = (lambda a: premier_du_mois(a, -1), premier_du_mois)
_ANNEE = (lambda a: date(a.year, 1, 1), lambda a: date(a.year + 1, 1, 1))


@dataclass(frozen=True, kw_only=True)
class ConsoGrdfDescription(SensorEntityDescription):
    calcul: Callable[[dict[str, Any], date], Valeur]


def _energie(key: str, calcul) -> ConsoGrdfDescription:
    return ConsoGrdfDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        calcul=calcul,
    )


def _volume(key: str, calcul) -> ConsoGrdfDescription:
    return ConsoGrdfDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.GAS,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=2,
        calcul=calcul,
    )


DESCRIPTIONS: tuple[ConsoGrdfDescription, ...] = (
    _energie("energie_jour", _dernier("energie")),
    _energie("energie_mois", _periode("energie", *_MOIS)),
    _energie("energie_mois_dernier", _periode("energie", *_MOIS_DERNIER)),
    _energie("energie_annee", _periode("energie", *_ANNEE)),
    _volume("volume_jour", _dernier("volume")),
    _volume("volume_mois", _periode("volume", *_MOIS)),
    _volume("volume_mois_dernier", _periode("volume", *_MOIS_DERNIER)),
    _volume("volume_annee", _periode("volume", *_ANNEE)),
    _volume("index", _dernier("index", 2)),
    ConsoGrdfDescription(
        key="temperature",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        calcul=_dernier("temperature", 1),
    ),
    ConsoGrdfDescription(
        key="tarif_kwh",
        translation_key="tarif_kwh",
        native_unit_of_measurement="EUR/kWh",
        suggested_display_precision=4,
        entity_category=EntityCategory.DIAGNOSTIC,
        calcul=lambda _d, _a: (
            None,
            {},
        ),  # remplacé par ConsoGrdfSensor (dépend des options)
    ),
    ConsoGrdfDescription(
        key="derniere_lecture",
        translation_key="derniere_lecture",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        calcul=lambda d, _a: (d.get("lu_le"), {}),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConsoGrdfConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(ConsoGrdfSensor(coordinator, d) for d in DESCRIPTIONS)


class ConsoGrdfSensor(CoordinatorEntity[ConsoGrdfCoordinator], SensorEntity):
    _attr_has_entity_name = True
    entity_description: ConsoGrdfDescription

    def __init__(
        self, coordinator: ConsoGrdfCoordinator, description: ConsoGrdfDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        pce = coordinator.client.pce
        self._attr_unique_id = f"{pce}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, pce)},
            name=f"Gazpar {pce}",
            manufacturer=MANUFACTURER,
            model=MODEL,
            entry_type=DeviceEntryType.SERVICE,
        )

    def _valeur(self) -> Valeur:
        if self.entity_description.key == "tarif_kwh":
            t = self.coordinator.tarifs
            if not t:
                return None, {}
            return round(t["prix_kwh"] + t["taxes_kwh"], 5), {
                "prix_kwh": t["prix_kwh"],
                "taxes_kwh": t["taxes_kwh"],
                "abonnement_jour": t["abonnement_jour"],
                "transport_jour": t["transport_jour"],
                "fixe_mois": round(
                    (t["abonnement_jour"] + t["transport_jour"]) * 365 / 12, 2
                ),
            }
        return self.entity_description.calcul(
            self.coordinator.data, dt_util.now().date()
        )

    @property
    def native_value(self) -> Any:
        return self._valeur()[0]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._valeur()[1]
