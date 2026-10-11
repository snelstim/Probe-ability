#!/usr/bin/env python3
"""The graph view's websocket command (probe_ability/history).

Run standalone — no Home Assistant required:

    python3 test_history_ws.py

Home Assistant is replaced by minimal stand-ins so the real
``websocket_api`` module imports; the checks exercise our own code: the
downsampling, the payload builder, the entity → predictor resolution and the
handler's result / error replies.
"""

import json
import math
import os
import sys
import time
import types

ROOT = os.path.dirname(os.path.abspath(__file__))
PASSED = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSED
    if not cond:
        raise AssertionError(f"{name}: {detail}")
    PASSED += 1
    print(f"  ok  {name}")


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


class FakeRegistry:
    def __init__(self, entities: dict) -> None:
        self.entities = entities

    def async_get(self, entity_id):
        return self.entities.get(entity_id)


class FakeConnection:
    def __init__(self) -> None:
        self.result = None
        self.error = None

    def send_result(self, msg_id, result):
        self.result = (msg_id, result)

    def send_error(self, msg_id, code, message):
        self.error = (msg_id, code, message)


_stub("voluptuous", Schema=_Marker, Required=_Marker, Optional=_Marker,
      All=_Marker, Coerce=_Marker, Range=_Marker, In=_Marker)
_stub("homeassistant")
_stub("homeassistant.components")
_stub("homeassistant.components.websocket_api", ERR_NOT_FOUND="not_found",
      websocket_command=lambda schema: (lambda f: f),
      async_register_command=lambda hass, handler: None, ActiveConnection=object)
_stub("homeassistant.core", HomeAssistant=object, callback=lambda f: f)
_stub("homeassistant.helpers")
_stub("homeassistant.helpers.config_validation", entity_id=str)
_stub("homeassistant.helpers.entity_registry", async_get=lambda hass: hass.registry)

# A bare package object, so importing the submodules does not run __init__.py
# (which would need the whole Home Assistant surface stubbed).
_pkg = types.ModuleType("probe_ability")
_pkg.__path__ = [os.path.join(ROOT, "custom_components", "probe_ability")]
sys.modules["probe_ability"] = _pkg

from probe_ability import websocket_api as ws  # noqa: E402
from probe_ability.predictor import CookPredictor  # noqa: E402


def cook(minutes: int = 14, interval: float = 30.0) -> CookPredictor:
    p = CookPredictor(target_temp=74.0)
    for i in range(int(minutes * 60 / interval)):
        now = 1_000_000.0 + i * interval
        p.add_reading(now, 180.0 - 175.0 * math.exp(-0.0004 * i * interval), 180.0)
        p.predict()
    return p


print("downsample")
rows = [(float(i), 20.0 + i * 0.01, 180.0) for i in range(1900)]
small = ws.downsample(rows, 300)
check("bounded by max_points", len(small) <= 300, str(len(small)))
check("keeps the first reading exactly", small[0][0] == 0.0 and small[0][1] == 20.0)
check("keeps the last reading exactly", small[-1][0] == 1899.0 and abs(small[-1][1] - (20.0 + 1899 * 0.01)) < 0.01)
check("timestamps stay ascending", all(b[0] > a[0] for a, b in zip(small, small[1:])))
check("bucket means stay inside the data range", all(20.0 <= r[1] <= 20.0 + 1899 * 0.01 for r in small))
few = ws.downsample(rows[:5], 300)
check("short series passes through unchanged", len(few) == 5 and few[2] == [2.0, 20.02, 180.0])
check("empty series", ws.downsample([], 300) == [])

print("build_history")
empty = ws.build_history(CookPredictor(target_temp=74.0))
check("no readings -> empty payload", empty["readings"] == [] and empty["forecast"] is None
      and empty["start_ts"] is None and empty["now_ts"] is None)
p = cook()
state = json.dumps(p.to_dict(), sort_keys=True)
h = ws.build_history(p)
check("building history does not mutate the predictor", json.dumps(p.to_dict(), sort_keys=True) == state)
check("payload is JSON-serialisable", bool(json.dumps(h)))
check("target and its history are reported", h["target_temp"] == 74.0 and h["target_history"] == [[0.0, 74.0]])
check("start / now timestamps match the readings", h["start_ts"] == 1_000_000.0 and h["now_ts"] == p.readings[-1][0])
check("readings are [ts, internal, ambient] in °C", len(h["readings"][0]) == 3 and h["readings"][-1][2] == 180.0)
check("forecast included mid-cook", h["forecast"] is not None and h["forecast"]["curve"][-1][1] == 74.0)
long_cook = cook(minutes=150)
check("long cook is downsampled", len(ws.build_history(long_cook, 300)["readings"]) <= 300)

print("resolve_predictor / handler")
class Monitor:
    predictors = [p, CookPredictor(target_temp=60.0)]


hass = types.SimpleNamespace(
    registry=FakeRegistry({
        "sensor.cook_time_remaining": types.SimpleNamespace(config_entry_id="entry1"),
        "sensor.orphan": types.SimpleNamespace(config_entry_id=None),
        "sensor.other_integration": types.SimpleNamespace(config_entry_id="not_ours"),
    }),
    data={ws.DOMAIN: {"entry1": Monitor()}},
)
check("probe 0 resolves", ws.resolve_predictor(hass, "sensor.cook_time_remaining", 0) == (0, p))
check("probe 1 resolves", ws.resolve_predictor(hass, "sensor.cook_time_remaining", 1) == (1, Monitor.predictors[1]))
check("probe beyond the slots -> None", ws.resolve_predictor(hass, "sensor.cook_time_remaining", 2) is None)
check("unknown entity -> None", ws.resolve_predictor(hass, "sensor.nope", 0) is None)
check("entity without a config entry -> None", ws.resolve_predictor(hass, "sensor.orphan", 0) is None)
check("entry that is not ours -> None", ws.resolve_predictor(hass, "sensor.other_integration", 0) is None)
hass.data = {}
check("integration not loaded -> None", ws.resolve_predictor(hass, "sensor.cook_time_remaining", 0) is None)
hass.data = {ws.DOMAIN: {"entry1": Monitor()}}

conn = FakeConnection()
ws.ws_history(hass, conn, {"id": 7, "type": ws.WS_HISTORY, "entity_id": "sensor.cook_time_remaining", "probe": 0})
check("handler replies with the payload", conn.result is not None and conn.result[0] == 7
      and conn.result[1]["readings"] and conn.result[1]["probe"] == 0 and conn.error is None)
conn = FakeConnection()
ws.ws_history(hass, conn, {"id": 8, "type": ws.WS_HISTORY, "entity_id": "sensor.nope", "probe": 0})
check("handler replies not_found for an unknown entity", conn.error == (8, "not_found", conn.error[2]) and conn.result is None)

print("slowest_probe (combined mode follows the probe that sets the countdown)")


def timed(remaining_s: float, last_ts: float = 1000.0) -> CookPredictor:
    """A predictor whose published estimate is `remaining_s` at its newest reading."""
    q = CookPredictor(target_temp=74.0)
    q.add_reading(last_ts, 40.0, 180.0)
    q._last_stable_remaining, q._last_stable_ts = remaining_s, last_ts
    return q


def mon(preds, active, last_ts):
    return types.SimpleNamespace(predictors=preds, probe_active=active, _last_reading_ts=last_ts)


NOW = 1000.0
check("picks the probe with the most time left",
      ws.slowest_probe(mon([timed(600), timed(1800), timed(1200)], [True] * 3, [NOW] * 3), NOW) == 1)
check("ignores inactive probes",
      ws.slowest_probe(mon([timed(600), timed(1800)], [True, False], [NOW] * 2), NOW) == 0)
check("ignores a stale probe, as the sensor does",
      ws.slowest_probe(mon([timed(600), timed(1800)], [True, True], [NOW, NOW - 400]), NOW) == 0)
done = timed(1800)
done._done_latched = True
check("ignores a finished probe", ws.slowest_probe(mon([timed(600), done], [True, True], [NOW] * 2), NOW) == 0)
check("a probe still collecting (no estimate) does not set the countdown",
      ws.slowest_probe(mon([timed(600), CookPredictor(target_temp=74.0)], [True, True], [NOW] * 2), NOW) == 0)
check("nothing qualifies -> first active probe",
      ws.slowest_probe(mon([CookPredictor(target_temp=74.0), CookPredictor(target_temp=74.0)], [False, True], [0.0, 0.0]), NOW) == 1)
check("nothing active -> slot 0", ws.slowest_probe(mon([timed(600)], [False], [NOW]), NOW) == 0)
_preds = [timed(600), timed(1800)]
_before = json.dumps([q.to_dict() for q in _preds], sort_keys=True)
ws.slowest_probe(mon(_preds, [True, True], [NOW] * 2), NOW)
check("does not mutate the predictors", json.dumps([q.to_dict() for q in _preds], sort_keys=True) == _before)

class ComboMonitor:
    predictors = [timed(600), timed(1800)]
    probe_active = [True, True]
    _last_reading_ts = [time.time()] * 2


hass.data = {ws.DOMAIN: {"entry1": ComboMonitor()}}
check("combined resolves to the slowest, whatever slot was asked for",
      ws.resolve_predictor(hass, "sensor.cook_time_remaining", 0, combined=True) == (1, ComboMonitor.predictors[1]))
check("not combined keeps the requested slot",
      ws.resolve_predictor(hass, "sensor.cook_time_remaining", 0)[0] == 0)
conn = FakeConnection()
ws.ws_history(hass, conn, {"id": 9, "type": ws.WS_HISTORY, "entity_id": "sensor.cook_time_remaining",
                           "probe": 0, "combined": True})
check("handler reports which probe it followed", conn.result and conn.result[1]["probe"] == 1, str(conn.error))

print(f"\nAll {PASSED} checks passed")
