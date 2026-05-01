"""Config flow for Probe-ability."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
)

from .const import (
    CONF_AMBIENT_SENSOR,
    CONF_EXPORT_DATA,
    CONF_INTERNAL_SENSOR,
    CONF_INTERNAL_SENSOR_2,
    CONF_INTERNAL_SENSOR_3,
    CONF_SHARE_DATA,
    DOMAIN,
)

SETUP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_INTERNAL_SENSOR): EntitySelector(
            EntitySelectorConfig(domain="sensor", device_class="temperature")
        ),
        vol.Required(CONF_AMBIENT_SENSOR): EntitySelector(
            EntitySelectorConfig(domain="sensor", device_class="temperature")
        ),
        vol.Optional(CONF_INTERNAL_SENSOR_2): EntitySelector(
            EntitySelectorConfig(domain="sensor", device_class="temperature")
        ),
        vol.Optional(CONF_INTERNAL_SENSOR_3): EntitySelector(
            EntitySelectorConfig(domain="sensor", device_class="temperature")
        ),
        vol.Optional(CONF_EXPORT_DATA, default=False): BooleanSelector(),
        vol.Optional(CONF_SHARE_DATA, default=False): BooleanSelector(),
    }
)


class CookPredictorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Probe-ability."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        if user_input is not None:
            # Use internal sensor entity_id as unique id to prevent duplicates
            await self.async_set_unique_id(user_input[CONF_INTERNAL_SENSOR])
            self._abort_if_unique_id_configured()

            # Title the entry after the sensor's friendly name so multiple
            # instances (e.g. smoker + oven) are easy to tell apart in the UI.
            state = self.hass.states.get(user_input[CONF_INTERNAL_SENSOR])
            title = state.name if state else user_input[CONF_INTERNAL_SENSOR]

            return self.async_create_entry(title=title, data=user_input)

        return self.async_show_form(step_id="user", data_schema=SETUP_SCHEMA)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of an existing entry.

        Shown when the user clicks '⋮ → Reconfigure' on the integration card
        in Settings → Devices & Services.  Lets the user change sensors or
        toggle the export / share options without removing and re-adding the
        integration.
        """
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            return self.async_update_reload_and_abort(
                entry,
                data_updates=user_input,
            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                SETUP_SCHEMA, entry.data
            ),
        )
