"""Accès à l'espace client GRDF par la bibliothèque pygazpar (la même que gazpar2haws)."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from homeassistant.core import HomeAssistant

from .const import TYPE_PUBLIEE

_LOGGER = logging.getLogger(__name__)


class ApiError(Exception):
    """GRDF ne répond pas ou répond mal."""


class AuthError(ApiError):
    """Identifiants refusés par GRDF."""


def _source(identifiant: str, mot_de_passe: str, type_conso: str):
    import pygazpar

    return pygazpar.JsonWebDataSource(
        username=identifiant,
        password=mot_de_passe,
        consumption_type=(
            pygazpar.ConsumptionType.PUBLISHED
            if type_conso == TYPE_PUBLIEE
            else pygazpar.ConsumptionType.INFORMATIVE
        ),
    )


def _traduire(err: Exception) -> ApiError:
    import pygazpar

    if isinstance(err, pygazpar.LoginError):
        return AuthError(str(err))
    return ApiError(f"{type(err).__name__} : {err}")


class GrdfClient:
    """Lecture des relevés d'un PCE. Les appels réseau (bloquants) passent par l'exécuteur de Home Assistant."""

    def __init__(
        self,
        hass: HomeAssistant,
        identifiant: str,
        mot_de_passe: str,
        pce: str,
        type_conso: str,
    ) -> None:
        self._hass = hass
        self._identifiant = identifiant
        self._mot_de_passe = mot_de_passe
        self.pce = pce
        self.type_conso = type_conso

    def _lire(self, debut: date, fin: date) -> list[dict[str, Any]]:
        import pygazpar

        source = _source(self._identifiant, self._mot_de_passe, self.type_conso)
        try:
            source.login()
            resultat = source.load(self.pce, debut, fin, [pygazpar.Frequency.DAILY])
        except Exception as err:
            raise _traduire(err) from err
        finally:
            try:
                source.logout()
            except Exception:
                _LOGGER.debug("Déconnexion GRDF impossible", exc_info=True)
        return list(
            resultat.get(pygazpar.Frequency.DAILY) or resultat.get("daily") or []
        )

    async def async_lire(self, debut: date, fin: date) -> list[dict[str, Any]]:
        """Relevés quotidiens de [debut ; fin]."""
        return await self._hass.async_add_executor_job(self._lire, debut, fin)


def _pces(identifiant: str, mot_de_passe: str) -> list[str]:
    source = _source(identifiant, mot_de_passe, "")
    try:
        source.login()
        return list(source.get_pce_identifiers())
    except Exception as err:
        raise _traduire(err) from err
    finally:
        try:
            source.logout()
        except Exception:
            _LOGGER.debug("Déconnexion GRDF impossible", exc_info=True)


async def async_pces(
    hass: HomeAssistant, identifiant: str, mot_de_passe: str
) -> list[str]:
    """PCE du compte (sert aussi de test de connexion)."""
    return await hass.async_add_executor_job(_pces, identifiant, mot_de_passe)
