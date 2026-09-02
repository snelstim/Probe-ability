#!/usr/bin/env python3
"""Test the Companion-app Live Activity payload / throttle logic.

Run standalone — no Home Assistant required:

    python3 test_live_activity.py
"""

import asyncio
import math
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "custom_components", "probe_ability"))

from live_activity import (  # noqa: E402
    ACTIVITY_MAX_AGE_S,
    ETA_DELTA_S,
    MIN_PUSH_INTERVAL_S,
    LiveActivityManager,
    PushRecord,
    SlotState,
    activity_generation,
    activity_title,
    build_clear_payload,
    build_payload,
    compute_progress,
    format_temp,
    is_silent,
    should_alert,
    make_record,
    make_tag,
    should_push,
    use_chronometer,
)
from predictor import CookPredictor  # noqa: E402

TAG_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
PASSED = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSED
    if not cond:
        raise AssertionError(f"{name}: {detail}")
    PASSED += 1
    print(f"  ok  {name}")


def slot(**kw) -> SlotState:
    base = dict(
        tag="probe_ability_abcdef12_c",
        title="Brisket",
        phase="heating",
        confidence="medium",
        current_c=63.5,
        start_c=5.0,
        target_c=95.0,
        time_remaining_s=2700.0,
        eta_ts=1_700_000_000.0,
        temp_unit="C",
    )
    base.update(kw)
    return SlotState(**base)


# ── 1. format_temp ───────────────────────────────────────────────────────────

print("format_temp")
check("C one decimal", format_temp(63.46, "C") == "63.5°")
check("C with unit", format_temp(63.46, "C", with_unit=True) == "63.5°C")
check("F integer", format_temp(63.46, "F") == "146°")
check("F with unit", format_temp(63.46, "F", with_unit=True) == "146°F")

# ── 2. compute_progress ──────────────────────────────────────────────────────

print("compute_progress")
check("midway", compute_progress(5, 50, 95, "heating") == 50)
check("below start clamps to 0", compute_progress(5, 3, 95, "heating") == 0)
check("above target clamps to 100", compute_progress(5, 120, 95, "heating") == 100)
check("done is 100", compute_progress(5, 40, 95, "done") == 100)
check("no start is 0", compute_progress(None, 40, 95, "heating") == 0)
check("no current is 0", compute_progress(5, None, 95, "heating") == 0)
check("target <= start is 0", compute_progress(95, 96, 95, "heating") == 0)

# ── 3. build_payload ─────────────────────────────────────────────────────────

print("build_payload")
for phase in ("collecting", "heating", "stall", "finishing", "done", "unreachable"):
    p = build_payload(slot(phase=phase), silent=True)
    d = p["data"]
    check(f"{phase}: required keys", all(k in d for k in ("tag", "live_update", "progress", "progress_max")))
    check(f"{phase}: live_update true", d["live_update"] is True)
    check(f"{phase}: tag format", bool(TAG_RE.match(d["tag"])))
    check(f"{phase}: title/message", p["title"] == "Brisket" and isinstance(p["message"], str) and p["message"])
    if phase in ("heating", "stall", "finishing"):
        check(f"{phase}: chronometer", d.get("chronometer") is True and isinstance(d["when"], int) and d["when"] == 1_700_000_000)
    else:
        check(f"{phase}: no chronometer", "chronometer" not in d and "when" not in d)
    check(f"{phase}: icon+colour", d["notification_icon"].startswith("mdi:") and d["notification_icon_color"].startswith("#"))

p = build_payload(slot(phase="heating", eta_ts=None), silent=True)
check("heating without ETA: no chronometer", "chronometer" not in p["data"])
check("done progress 100", build_payload(slot(phase="done"), silent=False)["data"]["progress"] == 100)
check("silent propagated", build_payload(slot(), silent=False)["data"]["silent"] is False)
check("alert_once by default", build_payload(slot(), silent=True)["data"]["alert_once"] is True)
check("alert re-enables buzz", build_payload(slot(phase="done"), silent=False, alert=True)["data"]["alert_once"] is False)
check("critical_text C", build_payload(slot(), silent=True)["data"]["critical_text"] == "63.5°C")
check("critical_text F", build_payload(slot(temp_unit="F"), silent=True)["data"]["critical_text"] == "146°F")
check("no reading: no critical_text", "critical_text" not in build_payload(slot(current_c=None, start_c=None), silent=True)["data"])
check("message heating", build_payload(slot(), silent=True)["message"] == "Heating · 63.5° / 95.0°")
check("message low confidence", build_payload(slot(confidence="low"), silent=True)["message"].endswith("· low confidence"))
check("message done", build_payload(slot(phase="done", current_c=95.2), silent=True)["message"] == "Target reached · 95.0°")
check("message unreachable", build_payload(slot(phase="unreachable"), silent=True)["message"].startswith("Target unreachable"))
check("clear payload", build_clear_payload("t") == {"message": "clear_notification", "data": {"tag": "t"}})
check("use_chronometer collecting false", not use_chronometer(slot(phase="collecting")))

# ── 4. should_push truth table ───────────────────────────────────────────────

print("should_push")


def rec(ts=0.0, phase="heating", target=95.0, cur=60.0, progress=61, when=1_700_000_000):
    return PushRecord(ts=ts, phase=phase, target_c=target, current_c=cur, progress=progress, when=when)


base = rec()
check("first push", should_push(None, rec()))
check("force", should_push(base, rec(ts=1), force=True))
check("phase change", should_push(base, rec(ts=1, phase="stall")))
check("target change", should_push(base, rec(ts=1, target=90.0)))
check("chronometer appears", should_push(rec(when=None), rec(ts=1)))
check("chronometer disappears", should_push(base, rec(ts=1, when=None)))
check("same state within interval", not should_push(base, rec(ts=MIN_PUSH_INTERVAL_S - 1, cur=61.0, progress=62, when=1_700_000_000 + 600)))
check("0.4°C after interval", not should_push(base, rec(ts=MIN_PUSH_INTERVAL_S + 1, cur=60.4)))
check("0.5°C after interval", should_push(base, rec(ts=MIN_PUSH_INTERVAL_S + 1, cur=60.5)))
check("ETA +119 s", not should_push(base, rec(ts=MIN_PUSH_INTERVAL_S + 1, when=1_700_000_000 + ETA_DELTA_S - 1)))
check("ETA +120 s", should_push(base, rec(ts=MIN_PUSH_INTERVAL_S + 1, when=1_700_000_000 + ETA_DELTA_S)))
check("progress int change", should_push(base, rec(ts=MIN_PUSH_INTERVAL_S + 1, progress=62)))
check("first reading bypasses interval", should_push(rec(cur=None, progress=0), rec(ts=5, cur=20.0)))
check("silent: first push is loud", not is_silent(None, rec()))
check("silent: done is loud", not is_silent(base, rec(phase="done")))
check("silent: target change is loud", not is_silent(base, rec(target=90.0)))
check("silent: routine is silent", is_silent(base, rec(ts=100, cur=61.0)))
check("alert: start does not re-alert", not should_alert(None, rec()))
check("alert: routine does not alert", not should_alert(base, rec(ts=100, cur=61.0)))
check("alert: target change does not alert", not should_alert(base, rec(target=90.0)))
check("alert: done alerts", should_alert(base, rec(phase="done")))
check("alert: unreachable alerts", should_alert(base, rec(phase="unreachable")))

# ── 5. tags / generations ────────────────────────────────────────────────────

print("tags")
check("gen 0 tag", make_tag("3f2a9c1d-long-entry-id", "c") == "probe_ability_3f2a9c1d_c")
check("gen 1 tag", make_tag("3f2a9c1d", "p2", 1) == "probe_ability_3f2a9c1d_p2_g1")
check("tag length", len(make_tag("x" * 40, "p3", 99)) <= 64)
check("gen at 7h49m", activity_generation(0.0, 7 * 3600 + 49 * 60) == 0)
check("gen at 7h51m", activity_generation(0.0, 7 * 3600 + 51 * 60) == 1)
check("gen at 16h", activity_generation(0.0, 16 * 3600) == 2)
check("gen no readings", activity_generation(None, 1e9) == 0)
check("title default name", activity_title("Cook") == "Probe-ability")
check("title with probe", activity_title("Cook", 1) == "Probe-ability · Probe 2")
check("title cook name", activity_title("Beef Brisket", None) == "Beef Brisket")

# ── 6. End-to-end: simulated cook through a real CookPredictor ──────────────


class FakeMonitor:
    def __init__(self, predictors, names=None, mode="combined"):
        self.predictors = predictors
        self.probe_active = [True] * len(predictors)
        self.probe_name = names or ["Beef Brisket"] * len(predictors)
        self.probe_mode = mode

    @property
    def cook_name(self):
        return self.probe_name[0]


class FakeHass:
    def __init__(self, available):
        self.available = set(available)
        self.calls = []
        self.tasks = []
        self.services = self

    def has_service(self, domain, service):
        return service in self.available

    async def async_call(self, domain, service, data, blocking=False):
        self.calls.append((service, data))

    def async_create_task(self, coro):
        self.tasks.append(asyncio.get_event_loop().create_task(coro))

    async def drain(self):
        while self.tasks:
            tasks, self.tasks = self.tasks, []
            await asyncio.gather(*tasks)


class FakeLogger:
    def __init__(self):
        self.warnings = []

    def warning(self, msg, *args, **kw):
        self.warnings.append(msg % args if args else msg)

    def debug(self, *a, **kw):
        pass


def simulate(manager, hass, monitor, pred, ambient=110.0, start=5.0, target=74.0, k=0.0001, step=30):
    """Exponential heating curve (~3 h to target); returns (readings, elapsed_s)."""
    t = 0.0
    readings = 0
    manager.refresh(monitor, force=True, now=t)
    while True:
        t += step
        temp = ambient - (ambient - start) * math.exp(-k * t)
        pred.add_reading(t, temp, ambient)
        readings += 1
        manager.refresh(monitor, now=t)
        if pred.predict().phase == "done" or t > 8 * 3600:
            manager.refresh(monitor, now=t)
            break
    return readings, t


async def end_to_end():
    print("end-to-end")
    hass = FakeHass({"mobile_app_phone"})
    log = FakeLogger()
    pred = CookPredictor(target_temp=74.0)
    mon = FakeMonitor([pred])
    mgr = LiveActivityManager(hass, "abcdef12-entry", "C", ["mobile_app_phone"], log)
    readings, elapsed = simulate(mgr, hass, mon, pred)
    await hass.drain()
    pushes = [c for c in hass.calls if c[1].get("message") != "clear_notification"]
    print(f"      {readings} readings over {elapsed / 60:.0f} min -> {len(pushes)} pushes")
    check("cook reached target", pred.predict().phase == "done")
    # Guarantee: routine pushes are capped at one per MIN_PUSH_INTERVAL_S;
    # the only extras are forced/phase-change pushes (a handful per cook).
    check("at most ~1 push/min", len(pushes) <= elapsed / MIN_PUSH_INTERVAL_S + 8, f"{len(pushes)} over {elapsed / 60:.0f} min")
    check("pushes rarer than readings", len(pushes) < readings * 0.6, f"{len(pushes)}/{readings}")
    check("all pushes same tag", len({c[1]["data"]["tag"] for c in pushes}) == 1)
    check("first push is loud", pushes[0][1]["data"]["silent"] is False)
    check("first push title", pushes[0][1]["title"] == "Beef Brisket")
    last = pushes[-1][1]["data"]
    check("last push is done at 100", last["progress"] == 100 and "chronometer" not in last)
    check("last push is loud", last["silent"] is False)
    check("last push buzzes", last["alert_once"] is False)
    check("routine pushes never buzz", all(c[1]["data"]["alert_once"] for c in pushes[1:-1]))
    check("chronometer seen mid-cook", any(c[1]["data"].get("chronometer") for c in pushes))
    check("progress monotonic-ish", all(b[1]["data"]["progress"] >= a[1]["data"]["progress"] - 1 for a, b in zip(pushes, pushes[1:])))
    check("no warnings", not log.warnings, str(log.warnings))

    # stop -> clear
    mon.probe_active = [False]
    mgr.refresh(mon, now=99999.0)
    await hass.drain()
    check("stop clears", hass.calls[-1][1] == build_clear_payload(pushes[0][1]["data"]["tag"]))


async def manager_behaviour():
    print("manager")
    hass = FakeHass({"mobile_app_good"})
    log = FakeLogger()
    p0, p1 = CookPredictor(target_temp=60.0), CookPredictor(target_temp=55.0)
    mon = FakeMonitor([p0, p1], names=["Steak", "Steak"], mode="combined")
    mgr = LiveActivityManager(hass, "deadbeef-x", "F", ["mobile_app_good", "mobile_app_missing"], log)

    mgr.refresh(mon, force=True, now=0.0)
    await hass.drain()
    check("one push to good service", [c[0] for c in hass.calls] == ["mobile_app_good"])
    check("combined tag", hass.calls[0][1]["data"]["tag"] == "probe_ability_deadbeef_c")
    check("missing service warned once", len(log.warnings) == 1 and "mobile_app_missing" in log.warnings[0])
    check("F unit in payload", "critical_text" not in hass.calls[0][1]["data"])  # no readings yet

    p0.add_reading(30, 20.0, 200.0)
    p1.add_reading(30, 25.0, 200.0)
    mgr.refresh(mon, now=30.0)
    await hass.drain()
    check("no repeat warning", len(log.warnings) == 1)
    check("F critical text", hass.calls[-1][1]["data"]["critical_text"] == "68°F")  # p0 (lowest temp) drives

    # combined -> individual: clear _c, start _p1 and _p2
    n = len(hass.calls)
    mon.probe_mode = "individual"
    mgr.refresh(mon, now=200.0)
    await hass.drain()
    new = hass.calls[n:]
    check("mode switch clears combined", new[0][1] == build_clear_payload("probe_ability_deadbeef_c"))
    tags = sorted(c[1]["data"]["tag"] for c in new[1:])
    check("mode switch starts per-probe", tags == ["probe_ability_deadbeef_p1", "probe_ability_deadbeef_p2"])
    check("individual titles", sorted(c[1]["title"] for c in new[1:]) == ["Steak · Probe 1", "Steak · Probe 2"])

    # per-probe stop clears only that tag
    n = len(hass.calls)
    mon.probe_active = [True, False]
    mgr.refresh(mon, now=300.0)
    await hass.drain()
    check("per-probe stop clears p2 only", hass.calls[n:] == [("mobile_app_good", build_clear_payload("probe_ability_deadbeef_p2"))])

    # set_targets: remove good -> clear on good; add another -> fresh push
    n = len(hass.calls)
    hass.available.add("mobile_app_new")
    mgr.set_targets(["mobile_app_new"], mon, now=350.0)
    await hass.drain()
    new = hass.calls[n:]
    check("removed service gets clear", new[0] == ("mobile_app_good", build_clear_payload("probe_ability_deadbeef_p1")))
    check("added service gets start", new[1][0] == "mobile_app_new" and new[1][1]["data"]["tag"] == "probe_ability_deadbeef_p1")

    # disable entirely
    n = len(hass.calls)
    mgr.set_targets([], mon, now=360.0)
    await hass.drain()
    check("disable clears", hass.calls[n:] == [("mobile_app_new", build_clear_payload("probe_ability_deadbeef_p1"))])
    check("disabled: refresh is a no-op", (mgr.refresh(mon, force=True, now=400.0), len(hass.calls))[1] == n + 1)

    # generation rollover
    hass2 = FakeHass({"mobile_app_good"})
    mgr2 = LiveActivityManager(hass2, "cafebabe-x", "C", ["mobile_app_good"], FakeLogger())
    pr = CookPredictor(target_temp=95.0)
    mon2 = FakeMonitor([pr], names=["Brisket"])
    pr.add_reading(0.0, 5.0, 110.0)
    mgr2.refresh(mon2, force=True, now=10.0)
    pr.add_reading(ACTIVITY_MAX_AGE_S + 5, 70.0, 110.0)
    mgr2.refresh(mon2, now=ACTIVITY_MAX_AGE_S + 5)
    await hass2.drain()
    check("rollover clears old tag", hass2.calls[1][1] == build_clear_payload("probe_ability_cafebabe_c"))
    check("rollover starts g1 tag", hass2.calls[2][1]["data"]["tag"] == "probe_ability_cafebabe_c_g1")
    check("record helper", make_record(slot(), 1.0).progress == 65)


async def main():
    await end_to_end()
    await manager_behaviour()


asyncio.run(main())
print(f"\nAll {PASSED} checks passed.")
