#!/usr/bin/env python3
"""Probe numbering by config slot.

Run standalone — no Home Assistant required:

    python3 test_probe_slots.py

Regression test for the v0.11.0 report "probes 1 and 4 configured: starting
probe 4 fails with 'list index out of range', and no second tile is offered
after starting probe 1".  The integration used to squeeze the configured
probes into indices 0..n-1 while the card numbers them by slot, so a card
sending probe_index 3 hit a two-entry list.  Now a probe's index is its
config slot everywhere (internal_sensor_4 → index 3) and empty slots in
between are simply skipped.

Home Assistant is replaced by minimal stand-ins so the real package imports;
every check exercises our own code: CookMonitor's slot discovery, the
start/stop index handling, reading routing, save/restore, and the sensor
platform (one entity pair per configured slot, stale-entity cleanup, the
attributes the card reads).
"""

import asyncio
import logging
import os
import sys
import types
from datetime import datetime, timedelta, timezone

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
    """Accepts anything: vol.Schema / vol.Required / StaticPathConfig …"""

    def __init__(self, *args, **kwargs) -> None:
        self.args, self.kwargs = args, kwargs


class _Names:
    """Enum look-alike: any attribute is just its own name."""

    def __getattr__(self, name: str) -> str:
        return name


class HomeAssistantError(Exception):
    def __init__(self, *args, translation_domain=None, translation_key=None,
                 translation_placeholders=None) -> None:
        super().__init__(*args)
        self.translation_key = translation_key
        self.translation_placeholders = dict(translation_placeholders or {})


class SensorEntity:
    def async_write_ha_state(self) -> None:
        pass


class FakeStore:
    """helpers.storage.Store: async_load() returns `preset`, async_save() records."""

    preset: dict | None = None
    saved: dict | None = None

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def async_load(self):
        return FakeStore.preset

    async def async_save(self, data) -> None:
        FakeStore.saved = data


TRACKED: list[list[str]] = []  # entity ids watched, per _start_listening() call


def _track_state_change(hass, entity_ids, action):
    TRACKED.append(list(entity_ids))
    return lambda: None


_stub("voluptuous", Schema=_Marker, Required=_Marker, Optional=_Marker,
      All=_Marker, Coerce=_Marker, Range=_Marker, In=_Marker)
_stub("homeassistant")
_stub("homeassistant.util")
_stub("homeassistant.util.dt", utcnow=lambda: datetime.now(timezone.utc))
_stub("homeassistant.components")
_stub("homeassistant.components.http", StaticPathConfig=_Marker)
_stub("homeassistant.components.sensor", SensorDeviceClass=_Names(), SensorEntity=SensorEntity)
_stub("homeassistant.config_entries", ConfigEntry=object)
_stub(
    "homeassistant.const",
    UnitOfTime=_Names(), Platform=_Names(),
    EVENT_HOMEASSISTANT_STARTED="homeassistant_started",
    EVENT_HOMEASSISTANT_STOP="homeassistant_stop",
)
_stub("homeassistant.core", HomeAssistant=object, Event=object, ServiceCall=object,
      callback=lambda f: f)
_stub("homeassistant.exceptions", HomeAssistantError=HomeAssistantError)
_stub("homeassistant.helpers")
_stub("homeassistant.helpers.config_validation", string=str,
      config_entry_only_config_schema=lambda domain: None)
_stub("homeassistant.helpers.event", async_call_later=lambda *a, **k: (lambda: None),
      async_track_state_change_event=_track_state_change)
_stub("homeassistant.helpers.storage", Store=FakeStore)
_stub("homeassistant.helpers.entity_platform", AddEntitiesCallback=object)
_stub(
    "homeassistant.helpers.entity_registry",
    async_get=lambda hass: hass.registry,
    async_entries_for_config_entry=lambda registry, entry_id: [
        e for e in registry.entities.values() if e.config_entry_id == entry_id
    ],
)

sys.path.insert(0, os.path.join(ROOT, "custom_components"))

import probe_ability  # noqa: E402  (runs __init__.py against the stubs)
from probe_ability import const, sensor  # noqa: E402
from probe_ability.predictor import CookPredictor  # noqa: E402

ENTRY_ID = "0123abcd"
P1, P2, P4, AMBIENT = "sensor.p1", "sensor.p2", "sensor.p4", "sensor.ambient"

# The reporter's setup: probes 1 and 4, nothing in slots 2 and 3.
SPARSE = {
    const.CONF_INTERNAL_SENSOR: P1,
    const.CONF_AMBIENT_SENSOR: AMBIENT,
    const.CONF_INTERNAL_SENSOR_4: P4,
}
CONTIGUOUS = {
    const.CONF_INTERNAL_SENSOR: P1,
    const.CONF_AMBIENT_SENSOR: AMBIENT,
    const.CONF_INTERNAL_SENSOR_2: P2,
}


class FakeState:
    def __init__(self, state, unit: str = "°C", age_s: float = 3600) -> None:
        self.state = str(state)
        self.attributes = {"unit_of_measurement": unit}
        self.last_changed = datetime.now(timezone.utc) - timedelta(seconds=age_s)


class FakeRegistryEntry:
    def __init__(self, entity_id: str, unique_id: str, config_entry_id: str) -> None:
        self.entity_id = entity_id
        self.unique_id = unique_id
        self.config_entry_id = config_entry_id


class FakeRegistry:
    def __init__(self, entries) -> None:
        self.entities = {e.entity_id: e for e in entries}
        self.removed: list[str] = []

    def async_remove(self, entity_id: str) -> None:
        del self.entities[entity_id]
        self.removed.append(entity_id)


class FakeHass:
    def __init__(self, states: dict) -> None:
        self.states = dict(states)
        self.data: dict = {}
        self.registry = FakeRegistry([])
        self.is_running = True
        self.bus = types.SimpleNamespace(async_listen_once=lambda *a, **k: None)

    def async_create_task(self, coro):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        return loop.create_task(coro)


class FakeEntry:
    def __init__(self, data: dict) -> None:
        self.entry_id = ENTRY_ID
        self.data = types.MappingProxyType(dict(data))
        self.options = types.MappingProxyType({})


def _states(p1=47.0, p2=30.0, p4=22.0, ambient=110.0) -> dict:
    return {
        P1: FakeState(p1), P2: FakeState(p2), P4: FakeState(p4), AMBIENT: FakeState(ambient),
    }


def _monitor(data: dict, states: dict):
    hass = FakeHass(states)
    entry = FakeEntry(data)
    monitor = probe_ability.CookMonitor(hass, entry)
    hass.data.setdefault(const.DOMAIN, {})[ENTRY_ID] = monitor
    return hass, entry, monitor


def _registry_entry(entity_id: str, tail: str, entry_id: str = ENTRY_ID) -> FakeRegistryEntry:
    return FakeRegistryEntry(entity_id, f"{entry_id}{tail}", entry_id)


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_slot_discovery() -> None:
    print("probe slots")
    _, _, m = _monitor(SPARSE, {})
    check("probes 1 and 4 → four slots, 2 and 3 empty",
          m._probe_sensors() == [P1, None, None, P4], str(m._probe_sensors()))
    check("probe count is the highest slot in use",
          m._probe_count() == 4 and len(m.predictors) == 4 and len(m.probe_active) == 4)
    check("probe_configured follows the slots",
          [m.probe_configured(i) for i in range(-1, 5)]
          == [False, True, False, False, True, False])
    check("unnamed probes have no labels", m.probe_labels == [None] * 4, str(m.probe_labels))
    check("probe 4 is called Probe 4, the empty slot 2 Probe 2",
          m.probe_label(3) == "Probe 4" and m.probe_label(1) == "Probe 2")

    named = dict(SPARSE, **{const.CONF_PROBE_NAME: " Green ", const.CONF_PROBE_NAME_4: "Red"})
    _, _, m = _monitor(named, {})
    check("names stay with their slot", m.probe_labels == ["Green", None, None, "Red"],
          str(m.probe_labels))
    check("probe_label uses the slot's name", m.probe_label(3) == "Red" and m.probe_label(0) == "Green")

    _, _, m = _monitor(CONTIGUOUS, {})
    check("a contiguous setup is unchanged",
          m._probe_sensors() == [P1, P2] and m._probe_count() == 2)
    _, _, m = _monitor({const.CONF_INTERNAL_SENSOR: P1, const.CONF_AMBIENT_SENSOR: AMBIENT}, {})
    check("a single probe is one slot", m._probe_sensors() == [P1] and m._probe_count() == 1)
    _, _, m = _monitor(dict(CONTIGUOUS, **{const.CONF_INTERNAL_SENSOR_4: ""}), {})
    check("an empty string is an empty slot and trailing empty slots are trimmed",
          m._probe_sensors() == [P1, P2])


def test_start_cook_individual() -> None:
    print("start_cook() individual")
    hass, _, m = _monitor(SPARSE, _states())
    m.start_cook(target_temp=60, cook_name="Lamb", probe_index=3,
                 probe_mode=const.PROBE_MODE_INDIVIDUAL)
    check("probe 4 starts on slot 3", m.probe_active == [False, False, False, True],
          str(m.probe_active))
    check("its predictor got the target and name",
          m.predictors[3].target_temp == 60 and m.probe_name[3] == "Lamb")
    check("only the configured sensors are watched", TRACKED[-1] == [P1, P4, AMBIENT],
          str(TRACKED[-1]))
    check("the save has one entry per slot", len(FakeStore.saved["probes"]) == 4
          and FakeStore.saved["probes"][3]["active"] is True)

    for bad, label in ((1, "Probe 2"), (2, "Probe 3"), (7, "Probe 8")):
        try:
            m.start_cook(target_temp=60, probe_index=bad, probe_mode=const.PROBE_MODE_INDIVIDUAL)
        except HomeAssistantError as err:
            check(f"probe_index {bad} is a clean 'not configured' error, not an IndexError",
                  err.translation_key == "probe_not_configured"
                  and err.translation_placeholders == {"probe": label},
                  f"{err.translation_key} {err.translation_placeholders}")
        else:
            raise AssertionError(f"probe_index {bad} did not raise")
    check("a rejected start changes nothing", m.probe_active == [False, False, False, True])

    m.stop_cook()
    check("stop_cook clears slot 3", m.probe_active == [False] * 4 and not m.active)
    hass.states[P4] = FakeState(0.0)
    try:
        m.start_cook(target_temp=60, probe_index=3, probe_mode=const.PROBE_MODE_INDIVIDUAL)
    except HomeAssistantError as err:
        check("probe 4 reading 0 is 'unavailable' and names its own sensor",
              err.translation_key == "probe_unavailable"
              and err.translation_placeholders == {"probe": "Probe 4", "sensor_id": P4},
              f"{err.translation_key} {err.translation_placeholders}")
    else:
        raise AssertionError("an unplugged probe 4 did not raise")


def test_start_cook_combined() -> None:
    print("start_cook() combined")
    records: list[str] = []
    handler = logging.Handler()
    handler.emit = lambda record: records.append(record.getMessage())
    logger = logging.getLogger("probe_ability")
    logger.addHandler(handler)
    try:
        hass, _, m = _monitor(SPARSE, _states())
        m.start_cook(target_temp=95, probe_mode=const.PROBE_MODE_COMBINED)
        check("combined starts probes 1 and 4", m.probe_active == [True, False, False, True],
              str(m.probe_active))
        check("empty slots are skipped without a warning",
              not any("skipping" in r for r in records), str(records))

        m.stop_cook()
        hass.states[P4] = FakeState("unavailable")
        m.start_cook(target_temp=95, probe_mode=const.PROBE_MODE_COMBINED)
        check("a down probe 4 is skipped with a warning naming probe 4",
              m.probe_active == [True, False, False, False]
              and [r for r in records if "skipping" in r] == [
                  "Probe 4 sensor unavailable — skipping for this cook"],
              str(records))
    finally:
        logger.removeHandler(handler)


def test_reading_routing() -> None:
    print("_async_on_state_change()")
    _, _, m = _monitor(SPARSE, _states(p1=47.0, p4=22.5))
    m.start_cook(target_temp=95, probe_mode=const.PROBE_MODE_COMBINED)
    m._async_on_state_change(None)
    check("probe 1's reading lands on slot 0",
          [r[1] for r in m.predictors[0].readings] == [47.0])
    check("probe 4's reading lands on slot 3",
          [r[1] for r in m.predictors[3].readings] == [22.5])
    check("the empty slots get nothing",
          not m.predictors[1].readings and not m.predictors[2].readings)


def test_sensor_platform() -> None:
    print("sensor.async_setup_entry()")
    hass, entry, m = _monitor(SPARSE, _states())
    # What v0.11.0 created for this setup: probe 1, plus a "probe 2" pair
    # that really was probe 4 — and another instance that must be left alone.
    hass.registry = FakeRegistry([
        _registry_entry("sensor.probe_ability_time_remaining", "_time_remaining"),
        _registry_entry("sensor.probe_ability_estimated_completion", "_eta"),
        _registry_entry("sensor.probe_ability_time_remaining_probe_2", "_time_remaining_2"),
        _registry_entry("sensor.probe_ability_estimated_completion_probe_2", "_eta_2"),
        _registry_entry("sensor.oven_time_remaining_probe_2", "_time_remaining_2", "ffffffff"),
    ])
    added: list = []
    asyncio.run(sensor.async_setup_entry(hass, entry, added.extend))
    check("one entity pair per configured slot",
          sorted(e._probe_index for e in added) == [0, 0, 3, 3])
    check("probe 4 gets the probe-4 unique ids",
          sorted(e._attr_unique_id for e in added) == sorted([
              f"{ENTRY_ID}_time_remaining", f"{ENTRY_ID}_eta",
              f"{ENTRY_ID}_time_remaining_4", f"{ENTRY_ID}_eta_4"]),
          str([e._attr_unique_id for e in added]))
    check("the stale probe-2 pair is removed from the registry",
          sorted(hass.registry.removed) == [
              "sensor.probe_ability_estimated_completion_probe_2",
              "sensor.probe_ability_time_remaining_probe_2"],
          str(hass.registry.removed))
    check("probe 1 and the other instance are untouched",
          set(hass.registry.entities) == {
              "sensor.probe_ability_time_remaining",
              "sensor.probe_ability_estimated_completion",
              "sensor.oven_time_remaining_probe_2"})
    check("entities are registered with the monitor", m._entities == added)

    tr0 = next(e for e in added
               if isinstance(e, sensor.CookTimeRemainingSensor) and e._probe_index == 0)
    tr3 = next(e for e in added
               if isinstance(e, sensor.CookTimeRemainingSensor) and e._probe_index == 3)
    attrs = tr0.extra_state_attributes
    check("probe_count counts slots", attrs["probe_count"] == 4)
    check("probe_sensors lists the sensor per slot",
          attrs["probe_sensors"] == [P1, None, None, P4], str(attrs["probe_sensors"]))
    check("probe_active / probe_names have one entry per slot",
          attrs["probe_active"] == [False] * 4 and attrs["probe_names"] == [None] * 4)
    check("idle: no per-probe data", "probe_4_active" not in attrs)

    m.start_cook(target_temp=60, probe_index=3, probe_mode=const.PROBE_MODE_INDIVIDUAL)
    attrs = tr0.extra_state_attributes
    check("a cook on probe 4 is reported as probe_4_*",
          attrs["probe_4_active"] is True and attrs["target_temp_4"] == 60
          and attrs["probe_active"] == [False, False, False, True])
    check("the empty slots are not reported",
          not any(k in attrs for k in ("probe_2_active", "probe_3_active",
                                       "target_temp_2", "target_temp_3")))
    check("the primary sensor is active while probe 4 cooks", attrs["active"] is True)
    a3 = tr3.extra_state_attributes
    check("probe 4's own entity is available, active and knows its index",
          tr3.available and a3["active"] is True and a3["probe_index"] == 3)
    check("probe_index_of() round-trips the unique ids",
          sensor.probe_index_of(ENTRY_ID, tr3._attr_unique_id) == 3
          and sensor.probe_index_of(ENTRY_ID, tr0._attr_unique_id) == 0
          and sensor.probe_index_of(ENTRY_ID, f"{ENTRY_ID}_eta_2") == 1
          and sensor.probe_index_of(ENTRY_ID, "ffffffff_eta_3") is None
          and sensor.probe_index_of(ENTRY_ID, f"{ENTRY_ID}_eta_x") is None)

    # A contiguous setup: nothing to clean up, the same entities as before.
    hass, entry, m = _monitor(CONTIGUOUS, _states())
    hass.registry = FakeRegistry([
        _registry_entry("sensor.probe_ability_time_remaining", "_time_remaining"),
        _registry_entry("sensor.probe_ability_estimated_completion", "_eta"),
        _registry_entry("sensor.probe_ability_time_remaining_probe_2", "_time_remaining_2"),
        _registry_entry("sensor.probe_ability_estimated_completion_probe_2", "_eta_2"),
    ])
    added = []
    asyncio.run(sensor.async_setup_entry(hass, entry, added.extend))
    check("a contiguous setup removes nothing and keeps its entity pairs",
          hass.registry.removed == [] and sorted(e._probe_index for e in added) == [0, 0, 1, 1])
    check("its attributes are the same shape as before",
          added[0].extra_state_attributes["probe_count"] == 2
          and added[0].extra_state_attributes["probe_sensors"] == [P1, P2])


def test_restore() -> None:
    print("async_load()")
    idle = {"active": False, "target": 74.0, "name": "Cook",
            "predictor": CookPredictor(target_temp=74.0).to_dict()}
    lamb = {"active": True, "target": 60.0, "name": "Lamb",
            "predictor": CookPredictor(target_temp=60.0).to_dict()}

    # A save written before slot numbering: probe 4 was stored as index 1.
    FakeStore.preset = {"active": True, "probe_mode": "individual", "probes": [idle, lamb]}
    try:
        _, _, m = _monitor(SPARSE, _states())
        asyncio.run(m.async_load())
    finally:
        FakeStore.preset = None
    check("the per-probe lists are padded to four slots",
          len(m.predictors) == 4 and len(m.probe_active) == 4 and len(m.probe_target) == 4)
    check("a restored cook on the empty slot 2 is dropped instead of freezing",
          m.probe_active == [False] * 4 and not m.active)

    # A save written with slot numbering restores in place.
    FakeStore.preset = {"active": True, "probe_mode": "individual",
                        "probes": [idle, idle, idle, lamb]}
    try:
        _, _, m = _monitor(SPARSE, _states())
        asyncio.run(m.async_load())
    finally:
        FakeStore.preset = None
    check("a cook on probe 4 is restored on slot 3",
          m.probe_active == [False, False, False, True] and m.probe_name[3] == "Lamb"
          and m.predictors[3].target_temp == 60.0)
    check("listening resumed on the configured sensors only", TRACKED[-1] == [P1, P4, AMBIENT])


def test_display_unit() -> None:
    print("display_unit()")
    cases = (({}, "C"), ({"temp_unit": "C"}, "C"), ({"temp_unit": "F"}, "F"),
             ({"temp_unit": "c"}, "C"), ({"temp_unit": "f"}, "F"), ({"temp_unit": None}, "C"))
    for data, want in cases:
        check(f"{data} reads as {want}", const.display_unit(data) == want, const.display_unit(data))
    check("new entries store the lowercase option keys hassfest requires",
          const.TEMP_UNIT_CELSIUS == "c" and const.TEMP_UNIT_FAHRENHEIT == "f")


def main() -> None:
    test_slot_discovery()
    test_start_cook_individual()
    test_start_cook_combined()
    test_reading_routing()
    test_sensor_platform()
    test_restore()
    test_display_unit()
    print(f"\nAll {PASSED} checks passed")


if __name__ == "__main__":
    main()
