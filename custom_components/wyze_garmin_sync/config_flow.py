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
    CONF_POLL_INTERVAL_MINUTES,
    CONF_WYZE_API_KEY,
    CONF_WYZE_EMAIL,
    CONF_WYZE_KEY_ID,
    CONF_WYZE_PASSWORD,
    DEFAULT_POLL_INTERVAL_MINUTES,
    DOMAIN,
    MAX_POLL_INTERVAL_MINUTES,
    MIN_POLL_INTERVAL_MINUTES,
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

    async def async_step_reconfigure(
        self, user_input: dict | None = None
    ) -> FlowResult:
        """Update Wyze credentials and validate them before replacing the entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
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
                _LOGGER.exception("Wyze re-authentication failed")
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data=user_input,
                )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_WYZE_EMAIL,
                    default=entry.data[CONF_WYZE_EMAIL],
                ): str,
                vol.Required(
                    CONF_WYZE_PASSWORD,
                    default=entry.data[CONF_WYZE_PASSWORD],
                ): str,
                vol.Required(
                    CONF_WYZE_KEY_ID,
                    default=entry.data[CONF_WYZE_KEY_ID],
                ): str,
                vol.Required(
                    CONF_WYZE_API_KEY,
                    default=entry.data[CONF_WYZE_API_KEY],
                ): str,
            }
        )
        return self.async_show_form(
            step_id="reconfigure",
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
    """Configure Garmin account mappings for Wyze profiles."""

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> FlowResult:
        """Configure Garmin credentials for a discovered profile."""
        errors: dict[str, str] = {}
        entry = self.config_entry
        data = entry.options
        accounts = dict(data.get(CONF_GARMIN_ACCOUNTS, {}))
        coordinator = self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
        profiles = coordinator.data.get("profiles", {}) if coordinator and coordinator.data else {}

        if user_input is not None:
            token_root = self.hass.config.path(".storage", DOMAIN)
            poll_interval = int(user_input[CONF_POLL_INTERVAL_MINUTES])
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
                        CONF_GARMIN_ACCOUNTS: accounts,
                        CONF_POLL_INTERVAL_MINUTES: poll_interval,
                    },
                )

        fields = {
            vol.Required(
                CONF_POLL_INTERVAL_MINUTES,
                default=data.get(
                    CONF_POLL_INTERVAL_MINUTES,
                    DEFAULT_POLL_INTERVAL_MINUTES,
                ),
            ): vol.All(
                selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=MAX_POLL_INTERVAL_MINUTES,
                        step=1,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="min",
                    )
                ),
                vol.Any(0, vol.Range(min=MIN_POLL_INTERVAL_MINUTES)),
            )
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
