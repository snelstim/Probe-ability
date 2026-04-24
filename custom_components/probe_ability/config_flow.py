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

            return self.async_create_entry(
                title="Probe-ability",
                data=user_input,
            )

        return self.async_show_form(step_id="user", data_schema=SETUP_SCHEMA)
