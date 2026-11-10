"""Configuration : identifiants de l'espace client GRDF, choix du PCE, options."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import ApiError, AuthError, async_pces
from .const import (
    CONF_ABONNEMENT_JOUR,
    CONF_COUTS,
    CONF_PCE,
    CONF_PREFIXE,
    CONF_PRIX_KWH,
    CONF_STATISTIQUES,
    CONF_TAXES_KWH,
    CONF_TRANSPORT_JOUR,
    CONF_TYPE_CONSO,
    DOMAIN,
    PREFIXE_DEFAUT,
    TYPE_INFORMATIVE,
    TYPE_PUBLIEE,
)

_LOGGER = logging.getLogger(__name__)

_EMAIL = TextSelector(TextSelectorConfig(type=TextSelectorType.EMAIL))
_MDP = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
_PREFIXE_OK = vol.Match(r"^[a-z0-9_]+$")
# 0 = repris automatiquement des coûts enregistrés par gazpar2haws
_TARIF = NumberSelector(
    NumberSelectorConfig(
        min=0, max=10, step="any", mode=NumberSelectorMode.BOX, unit_of_measurement="€"
    )
)


class ConsoGrdfConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._identifiants: dict[str, str] = {}
        self._pces: list[str] = []

    async def _async_pces(
        self, identifiant: str, mot_de_passe: str
    ) -> tuple[list[str], str | None]:
        try:
            pces = await async_pces(self.hass, identifiant, mot_de_passe)
        except AuthError:
            return [], "invalid_auth"
        except ApiError:
            return [], "cannot_connect"
        except Exception:
            _LOGGER.exception("Erreur inattendue pendant la connexion à GRDF")
            return [], "unknown"
        return pces, None if pces else "no_pce"

    async def _async_creer(self, pce: str) -> ConfigFlowResult:
        await self.async_set_unique_id(pce)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=f"Gazpar {pce}",
            data={**self._identifiants, CONF_PCE: pce},
            options={
                CONF_TYPE_CONSO: TYPE_INFORMATIVE,
                CONF_STATISTIQUES: False,
                CONF_PREFIXE: PREFIXE_DEFAUT,
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            identifiant = user_input[CONF_USERNAME].strip()
            pces, erreur = await self._async_pces(
                identifiant, user_input[CONF_PASSWORD]
            )
            if erreur:
                errors["base"] = erreur
            else:
                self._identifiants = {
                    CONF_USERNAME: identifiant,
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                }
                self._pces = pces
                if len(pces) == 1:
                    return await self._async_creer(pces[0])
                return await self.async_step_pce()
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_USERNAME, default=(user_input or {}).get(CONF_USERNAME, "")
                ): _EMAIL,
                vol.Required(CONF_PASSWORD): _MDP,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_pce(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return await self._async_creer(user_input[CONF_PCE])
        return self.async_show_form(
            step_id="pce",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PCE): SelectSelector(
                        SelectSelectorConfig(options=self._pces)
                    )
                }
            ),
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            pces, erreur = await self._async_pces(
                entry.data[CONF_USERNAME], user_input[CONF_PASSWORD]
            )
            if erreur:
                errors["base"] = erreur
            elif entry.data[CONF_PCE] not in pces:
                errors["base"] = "no_pce"
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): _MDP}),
            description_placeholders={"email": entry.data[CONF_USERNAME]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ConsoGrdfOptionsFlow()


class ConsoGrdfOptionsFlow(OptionsFlow):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            prefixe = (user_input.get(CONF_PREFIXE) or PREFIXE_DEFAUT).strip().lower()
            try:
                _PREFIXE_OK(prefixe)
            except vol.Invalid:
                errors[CONF_PREFIXE] = "invalid_prefixe"
            else:
                return self.async_create_entry(
                    data={**user_input, CONF_PREFIXE: prefixe}
                )
        options = {**self.config_entry.options, **(user_input or {})}
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_TYPE_CONSO,
                    default=options.get(CONF_TYPE_CONSO, TYPE_INFORMATIVE),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[TYPE_INFORMATIVE, TYPE_PUBLIEE],
                        translation_key=CONF_TYPE_CONSO,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
                vol.Required(
                    CONF_STATISTIQUES, default=options.get(CONF_STATISTIQUES, False)
                ): BooleanSelector(),
                vol.Required(
                    CONF_PREFIXE, default=options.get(CONF_PREFIXE, PREFIXE_DEFAUT)
                ): TextSelector(),
                vol.Required(
                    CONF_COUTS, default=options.get(CONF_COUTS, True)
                ): BooleanSelector(),
                **{
                    vol.Optional(cle, default=float(options.get(cle) or 0)): _TARIF
                    for cle in (
                        CONF_PRIX_KWH,
                        CONF_TAXES_KWH,
                        CONF_ABONNEMENT_JOUR,
                        CONF_TRANSPORT_JOUR,
                    )
                },
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
