"""Config flow for Probe-ability."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import MAJOR_VERSION, MINOR_VERSION
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_AMBIENT_SENSOR,
    CONF_EXPORT_DATA,
    CONF_INTERNAL_SENSOR,
    CONF_INTERNAL_SENSOR_2,
    CONF_INTERNAL_SENSOR_3,
    CONF_LIVE_ACTIVITY_TARGETS,
    CONF_SHARE_DATA,
    CONF_TEMP_UNIT,
    DOMAIN,
    LIVE_ACTIVITY_MIN_HA,
    TEMP_UNIT_CELSIUS,
    TEMP_UNIT_FAHRENHEIT,
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
        vol.Optional(CONF_TEMP_UNIT, default=TEMP_UNIT_CELSIUS): SelectSelector(
            SelectSelectorConfig(
                options=[TEMP_UNIT_CELSIUS, TEMP_UNIT_FAHRENHEIT],
                translation_key="temp_unit",
            )
        ),
        vol.Optional(CONF_EXPORT_DATA, default=False): BooleanSelector(),
        vol.Optional(CONF_SHARE_DATA, default=False): BooleanSelector(),
    }
)


class CookPredictorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Probe-ability."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> ProbeAbilityOptionsFlow:
        """Return the options flow (⋮ → Configure on the integration card)."""
        return ProbeAbilityOptionsFlow()

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


class ProbeAbilityOptionsFlow(OptionsFlow):
    """Options: which Companion-app devices receive a cook-progress Live Activity.

    Applied in place by the entry's update listener — no reload, so an
    active cook is not interrupted.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    CONF_LIVE_ACTIVITY_TARGETS: list(
                        user_input.get(CONF_LIVE_ACTIVITY_TARGETS, [])
                    )
                },
            )

        current = list(self.config_entry.options.get(CONF_LIVE_ACTIVITY_TARGETS, []))
        discovered = [
            name
            for name in self.hass.services.async_services_for_domain("notify")
            if name.startswith("mobile_app_")
        ]
        # Keep currently selected services in the list even if the phone is
        # not registered right now, so reopening the dialog never drops them.
        options = [
            SelectOptionDict(value=name, label=name)
            for name in sorted(set(discovered) | set(current))
        ]
        schema = vol.Schema(
            {
                vol.Optional(CONF_LIVE_ACTIVITY_TARGETS, default=current): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        multiple=True,
                        custom_value=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        too_old = (MAJOR_VERSION, MINOR_VERSION) < LIVE_ACTIVITY_MIN_HA
        note = (
            " ⚠️ This Home Assistant is older than "
            f"{LIVE_ACTIVITY_MIN_HA[0]}.{LIVE_ACTIVITY_MIN_HA[1]} — iOS Live Activities "
            "will not work until you upgrade."
            if too_old
            else ""
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders={"ha_version_note": note},
        )
