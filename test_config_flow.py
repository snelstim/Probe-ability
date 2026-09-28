#!/usr/bin/env python3
"""Test the Reconfigure flow and the config-entry update listener.

Run standalone — no Home Assistant required:

    python3 test_config_flow.py

Home Assistant and voluptuous are replaced by minimal stand-ins so the real
package (including __init__.py) imports; every check exercises our own logic:

  * clearing an optional probe or probe name in the Reconfigure dialog really
    removes it from the config entry (the form omits cleared fields, so a plain
    merge would keep the old value — see config_flow.reconfigured_data()),
  * the flow does not reload the entry itself; the update listener schedules
    a reload for a data change and applies an options-only change in place
    (from HA 2026.12 a config flow may not reload an entry that has a listener),
  * the initial step never asks HA to reload on a duplicate unique_id.

The sensor platform's stale-entity cleanup is covered by test_probe_slots.py.
"""

import asyncio
import os
import sys
import types
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
PASSED = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSED
    if not cond:
        raise AssertionError(f"{name}: {detail}")
    PASSED += 1
    print(f"  ok  {name}")


# ── Stand-ins for the Home Assistant / voluptuous symbols the package imports ──


def _stub(name: str, **attrs) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    sys.modules[name] = module
    parent, _, child = name.rpartition(".")
    if parent:
        setattr(sys.modules[parent], child, module)
    return module


class _Marker:
    def __init__(self, *args, **kwargs) -> None:
        self.args, self.kwargs = args, kwargs


class _Names:
    def __getattr__(self, name: str) -> str:
        return name


class _ConfigFlow:
    def __init_subclass__(cls, domain=None, **kwargs) -> None:
        super().__init_subclass__(**kwargs)


_stub("voluptuous", Schema=_Marker, Required=_Marker, Optional=_Marker,
      All=_Marker, Coerce=_Marker, Range=_Marker, In=_Marker)
_stub("homeassistant")
_stub("homeassistant.util")
_stub("homeassistant.util.dt", utcnow=lambda: datetime.now(timezone.utc))
_stub("homeassistant.components")
_stub("homeassistant.components.http", StaticPathConfig=_Marker)
_stub("homeassistant.components.sensor", SensorDeviceClass=_Names(), SensorEntity=object)
_stub("homeassistant.config_entries", ConfigEntry=object, ConfigFlow=_ConfigFlow,
      ConfigFlowResult=dict, OptionsFlow=object)
_stub(
    "homeassistant.const",
    MAJOR_VERSION=2026, MINOR_VERSION=9, UnitOfTime=_Names(), Platform=_Names(),
    EVENT_CORE_CONFIG_UPDATE="core_config_updated",
    EVENT_HOMEASSISTANT_STARTED="homeassistant_started",
    EVENT_HOMEASSISTANT_STOP="homeassistant_stop",
)
_stub("homeassistant.core", HomeAssistant=object, Event=object, ServiceCall=object,
      callback=lambda f: f)
_stub("homeassistant.exceptions", HomeAssistantError=Exception)
_stub("homeassistant.helpers")
_stub("homeassistant.helpers.config_validation", string=str,
      config_entry_only_config_schema=lambda domain: None)
_stub("homeassistant.helpers.event", async_call_later=lambda *a, **k: (lambda: None),
      async_track_state_change_event=lambda *a, **k: (lambda: None))
_stub("homeassistant.helpers.storage", Store=_Marker)
_stub("homeassistant.helpers.translation", async_get_translations=None)
_stub(
    "homeassistant.helpers.selector",
    BooleanSelector=_Marker, EntitySelector=_Marker, EntitySelectorConfig=_Marker,
    SelectOptionDict=dict, SelectSelector=_Marker, SelectSelectorConfig=_Marker,
    SelectSelectorMode=_Names(), TextSelector=_Marker,
)
_stub("homeassistant.helpers.entity_platform", AddEntitiesCallback=object)
_stub("homeassistant.helpers.entity_registry", async_get=None,
      async_entries_for_config_entry=None)

sys.path.insert(0, os.path.join(ROOT, "custom_components"))

import probe_ability  # noqa: E402  (runs __init__.py against the stubs)
from probe_ability import config_flow, const  # noqa: E402
from probe_ability.texts import Texts  # noqa: E402

ENTRY_ID = "0123abcd"
TEXTS = Texts.from_translation_file(
    os.path.join(ROOT, "custom_components", "probe_ability", "translations", "en.json")
)

CURRENT = {
    const.CONF_INTERNAL_SENSOR: "sensor.probe_1",
    const.CONF_PROBE_NAME: "Green",
    const.CONF_AMBIENT_SENSOR: "sensor.ambient",
    const.CONF_INTERNAL_SENSOR_2: "sensor.probe_2",
    const.CONF_PROBE_NAME_2: "Red",
    const.CONF_INTERNAL_SENSOR_3: "sensor.probe_3",
    const.CONF_TEMP_UNIT: const.TEMP_UNIT_FAHRENHEIT,
    const.CONF_EXPORT_DATA: True,
    const.CONF_SHARE_DATA: True,
    "added_by_a_later_version": "kept",
}

# What the Reconfigure dialog submits after the user clears probe 3, clears
# probe 2's name and unticks sharing: cleared fields are simply absent.
PROBE_3_CLEARED = {
    const.CONF_INTERNAL_SENSOR: "sensor.probe_1",
    const.CONF_PROBE_NAME: "Green",
    const.CONF_AMBIENT_SENSOR: "sensor.ambient",
    const.CONF_INTERNAL_SENSOR_2: "sensor.probe_2",
    const.CONF_TEMP_UNIT: const.TEMP_UNIT_FAHRENHEIT,
    const.CONF_EXPORT_DATA: True,
    const.CONF_SHARE_DATA: False,
}


class FakeEntry:
    def __init__(self, data: dict, options: dict | None = None) -> None:
        self.entry_id = ENTRY_ID
        self.data = types.MappingProxyType(dict(data))
        self.options = types.MappingProxyType(dict(options or {}))
        self.unique_id = data[const.CONF_INTERNAL_SENSOR]


class FakeConfigEntries:
    def __init__(self) -> None:
        self.updates: list[tuple] = []
        self.reloads: list[str] = []

    def async_update_entry(self, entry, **kwargs) -> bool:
        self.updates.append((entry, kwargs))
        return True

    def async_schedule_reload(self, entry_id: str) -> None:
        self.reloads.append(entry_id)


class FakeHass:
    def __init__(self) -> None:
        self.data: dict = {}
        self.config_entries = FakeConfigEntries()
        self.states = types.SimpleNamespace(get=lambda entity_id: None)
        self.bus = types.SimpleNamespace(async_listen_once=lambda *a, **k: None)

    def async_create_task(self, coro):
        return asyncio.run(coro)


class Flow(config_flow.CookPredictorConfigFlow):
    """The real steps on top of a recording ConfigFlow base."""

    def __init__(self, entry: FakeEntry | None = None) -> None:
        self.hass = FakeHass()
        self.entry = entry
        self.aborts: list[dict] = []
        self.forms: list[dict] = []
        self.unique_id_calls: list[dict] = []
        self.created: list[dict] = []

    def _get_reconfigure_entry(self):
        return self.entry

    async def async_set_unique_id(self, unique_id):
        self.unique_id = unique_id

    def _abort_if_unique_id_configured(self, **kwargs):
        self.unique_id_calls.append(kwargs)

    def async_create_entry(self, **kwargs):
        self.created.append(kwargs)
        return {"type": "create_entry", **kwargs}

    def async_abort(self, **kwargs):
        self.aborts.append(kwargs)
        return {"type": "abort", **kwargs}

    def async_update_reload_and_abort(self, *args, **kwargs):
        raise AssertionError("must not use the self-reloading helper (deprecated with an update listener)")

    def async_show_form(self, **kwargs):
        self.forms.append(kwargs)
        return {"type": "form"}

    def add_suggested_values_to_schema(self, schema, suggested_values):
        return (schema, dict(suggested_values))


def test_reconfigured_data() -> None:
    print("reconfigured_data()")
    new = config_flow.reconfigured_data(CURRENT, PROBE_3_CLEARED)
    check("cleared probe 3 is gone", const.CONF_INTERNAL_SENSOR_3 not in new, str(new))
    check("cleared probe-2 name is gone", const.CONF_PROBE_NAME_2 not in new, str(new))
    check("probe 2 and its sensor kept", new[const.CONF_INTERNAL_SENSOR_2] == "sensor.probe_2")
    check("probe 1, its name and ambient kept", new[const.CONF_INTERNAL_SENSOR] == "sensor.probe_1"
          and new[const.CONF_PROBE_NAME] == "Green" and new[const.CONF_AMBIENT_SENSOR] == "sensor.ambient")
    check("submitted values win", new[const.CONF_SHARE_DATA] is False)
    check("non-probe keys carried over", new[const.CONF_TEMP_UNIT] == const.TEMP_UNIT_FAHRENHEIT
          and new[const.CONF_EXPORT_DATA] is True and new["added_by_a_later_version"] == "kept")
    check("inputs not mutated", const.CONF_INTERNAL_SENSOR_3 in CURRENT
          and const.CONF_INTERNAL_SENSOR_3 not in PROBE_3_CLEARED)

    only_probe_1 = {k: v for k, v in PROBE_3_CLEARED.items() if k != const.CONF_INTERNAL_SENSOR_2}
    new = config_flow.reconfigured_data(CURRENT, only_probe_1)
    check("clearing every optional probe leaves only probe 1",
          [k for k in const.PROBE_SENSOR_KEYS if k in new] == [const.CONF_INTERNAL_SENSOR])

    added = dict(PROBE_3_CLEARED, **{const.CONF_INTERNAL_SENSOR_4: "sensor.new_probe_4"})
    new = config_flow.reconfigured_data(CURRENT, added)
    check("adding probe 4 with slots 3 empty works",
          new[const.CONF_INTERNAL_SENSOR_4] == "sensor.new_probe_4" and const.CONF_INTERNAL_SENSOR_3 not in new)

    swapped = dict(PROBE_3_CLEARED, **{const.CONF_INTERNAL_SENSOR: "sensor.replacement"})
    new = config_flow.reconfigured_data(CURRENT, swapped)
    check("replacing probe 1 works", new[const.CONF_INTERNAL_SENSOR] == "sensor.replacement")


def test_user_step() -> None:
    print("async_step_user()")
    flow = Flow()
    asyncio.run(flow.async_step_user(dict(CURRENT)))
    check("duplicate check never asks HA to reload", flow.unique_id_calls == [{"reload_on_update": False}],
          str(flow.unique_id_calls))
    check("entry created from the form", len(flow.created) == 1 and flow.created[0]["data"] == CURRENT)


def test_reconfigure_step() -> None:
    print("async_step_reconfigure()")
    entry = FakeEntry(CURRENT)
    flow = Flow(entry)

    result = asyncio.run(flow.async_step_reconfigure(None))
    check("first call shows the form", result == {"type": "form"} and flow.forms[0]["step_id"] == "reconfigure")
    schema, suggested = flow.forms[0]["data_schema"]
    check("form is prefilled with the current data",
          schema is config_flow.SETUP_SCHEMA and suggested[const.CONF_INTERNAL_SENSOR_3] == "sensor.probe_3")
    check("showing the form changes nothing", flow.hass.config_entries.updates == [])

    result = asyncio.run(flow.async_step_reconfigure(PROBE_3_CLEARED))
    check("submit aborts with reconfigure_successful",
          result["type"] == "abort" and flow.aborts == [{"reason": "reconfigure_successful"}])
    updates = flow.hass.config_entries.updates
    check("updates the reconfigured entry exactly once", len(updates) == 1 and updates[0][0] is entry)
    kwargs = updates[0][1]
    check("passes data=, not data_updates=", set(kwargs) == {"data"}, str(kwargs))
    check("stored data no longer has probe 3", const.CONF_INTERNAL_SENSOR_3 not in kwargs["data"])
    check("stored data equals reconfigured_data()",
          kwargs["data"] == config_flow.reconfigured_data(CURRENT, PROBE_3_CLEARED))
    check("unique_id is not touched", "unique_id" not in kwargs and entry.unique_id == "sensor.probe_1")
    check("the flow leaves the reload to the update listener", flow.hass.config_entries.reloads == [])


def _monitor(hass: FakeHass, entry: FakeEntry):
    monitor = probe_ability.CookMonitor(hass, entry, TEXTS)
    hass.data.setdefault(const.DOMAIN, {})[entry.entry_id] = monitor
    return monitor


def test_update_listener() -> None:
    print("_async_entry_updated()")
    hass = FakeHass()
    entry = FakeEntry(CURRENT)
    monitor = _monitor(hass, entry)
    applied: list = []
    monitor.live_activity.set_targets = lambda targets, mon, **kw: applied.append((targets, mon))
    check("fresh monitor: config unchanged", monitor.config_changed is False)
    check("monitor sees three probe slots", len(monitor.predictors) == 3)

    # ⋮ → Configure: only entry.options changed → applied in place, no reload
    entry.options = types.MappingProxyType({const.CONF_LIVE_ACTIVITY_TARGETS: ["mobile_app_phone"]})
    asyncio.run(probe_ability._async_entry_updated(hass, entry))
    check("options change is applied in place", applied == [(["mobile_app_phone"], monitor)])
    check("options change does not reload", hass.config_entries.reloads == [])

    # ⋮ → Reconfigure: entry.data replaced (probe 3 cleared) → reload
    entry.data = types.MappingProxyType(config_flow.reconfigured_data(CURRENT, PROBE_3_CLEARED))
    check("replaced data is detected", monitor.config_changed is True)
    asyncio.run(probe_ability._async_entry_updated(hass, entry))
    check("data change schedules a reload", hass.config_entries.reloads == [ENTRY_ID])
    check("data change does not touch live activity", len(applied) == 1)

    # After the reload a new monitor is built from the new data
    new_monitor = _monitor(hass, entry)
    check("reloaded monitor: config unchanged again", new_monitor.config_changed is False)
    check("reloaded monitor has two probe slots", len(new_monitor.predictors) == 2)
    check("reloaded monitor lost probe 2's name", new_monitor.probe_label(1) == "Probe 2")

    # Same data re-submitted (dict equality, not identity) is not a change
    entry.data = types.MappingProxyType(dict(entry.data))
    check("equal data is not a change", new_monitor.config_changed is False)

    hass.data[const.DOMAIN].clear()
    asyncio.run(probe_ability._async_entry_updated(hass, entry))
    check("unloaded entry is ignored", hass.config_entries.reloads == [ENTRY_ID])


def main() -> None:
    test_reconfigured_data()
    test_user_step()
    test_reconfigure_step()
    test_update_listener()
    print(f"\nAll {PASSED} checks passed")


if __name__ == "__main__":
    main()
