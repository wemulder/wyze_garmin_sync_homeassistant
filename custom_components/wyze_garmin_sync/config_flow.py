"""Config and options flows for Wyze Garmin Sync."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from . import api
from .const import (
    CONF_GARMIN_ACCOUNTS,
    CONF_SYNC_TIME,
    CONF_WYZE_API_KEY,
    CONF_WYZE_EMAIL,
    CONF_WYZE_KEY_ID,
    CONF_WYZE_PASSWORD,
    DEFAULT_SYNC_TIME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class WyzeGarminConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Set up Wyze credentials."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> FlowResult:
        """Collect Wyze login details and verify access."""
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_WYZE_EMAIL].strip().lower())
            self._abort_if_unique_id_configured()
            token_file = api.wyze_token_file(self.hass.config.path(".storage", DOMAIN))
            try:
                await self.hass.async_add_executor_job(
                    api.authenticate_wyze,
                    user_input[CONF_WYZE_EMAIL],
                    user_input[CONF_WYZE_PASSWORD],
                    user_input[CONF_WYZE_KEY_ID],
                    user_input[CONF_WYZE_API_KEY],
                    token_file,
                )
            except Exception:
                _LOGGER.error("Wyze authentication failed during integration setup")
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title="Wyze Garmin Sync",
                    data=user_input,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_WYZE_EMAIL): str,
                vol.Required(CONF_WYZE_PASSWORD): str,
                vol.Required(CONF_WYZE_KEY_ID): str,
                vol.Required(CONF_WYZE_API_KEY): str,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> WyzeGarminOptionsFlow:
        """Create the options flow."""
        return WyzeGarminOptionsFlow()


class WyzeGarminOptionsFlow(config_entries.OptionsFlow):
    """Configure the daily sync time and Garmin mappings for Wyze profiles."""

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> FlowResult:
        """Configure Garmin credentials for each currently discovered profile."""
        errors: dict[str, str] = {}
        entry = self.config_entry
        data = entry.options
        accounts = dict(data.get(CONF_GARMIN_ACCOUNTS, {}))
        coordinator = self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
        profiles = coordinator.data.get("profiles", {}) if coordinator and coordinator.data else {}

        if user_input is not None:
            sync_time = user_input[CONF_SYNC_TIME]
            token_root = self.hass.config.path(".storage", DOMAIN)
            profile_id = user_input.get("profile_id")
            email = user_input.get("garmin_email", "").strip()
            password = user_input.get("garmin_password", "")
            mfa_code = user_input.get("garmin_mfa", "").strip()
            if email or password or mfa_code:
                if not profile_id or not email or not password:
                    errors["base"] = "incomplete_garmin_account"
                else:
                    token_dir = api.profile_token_dir(token_root, profile_id)
                    try:
                        await self.hass.async_add_executor_job(
                            api.authenticate_garmin,
                            email,
                            password,
                            mfa_code,
                            token_dir,
                        )
                    except Exception:
                        _LOGGER.error(
                            "Garmin authentication failed for a configured Wyze profile"
                        )
                        errors["base"] = "garmin_auth_failed"
                    else:
                        accounts[profile_id] = {
                            "email": email,
                            "password": password,
                        }

            if not errors:
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_SYNC_TIME: sync_time,
                        CONF_GARMIN_ACCOUNTS: accounts,
                    },
                )

        fields = {
            vol.Required(
                CONF_SYNC_TIME,
                default=data.get(CONF_SYNC_TIME, DEFAULT_SYNC_TIME),
            ): selector.TimeSelector()
        }
        if profiles:
            fields[vol.Optional("profile_id")] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {
                            "label": f"{profile['name']} ({profile_id})",
                            "value": profile_id,
                        }
                        for profile_id, profile in profiles.items()
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        fields[vol.Optional("garmin_email")] = str
        fields[vol.Optional("garmin_password")] = selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        )
        fields[vol.Optional("garmin_mfa")] = selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        )

        profile_map = ", ".join(
            f"{profile['name']} ({profile_id})"
            for profile_id, profile in profiles.items()
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(fields),
            errors=errors,
            description_placeholders={
                "profiles": profile_map or "No profiles discovered yet",
            },
        )
