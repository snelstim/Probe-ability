#!/usr/bin/env python3
"""Test the CookPredictor engine with simulated cook data.

Run standalone — no Home Assistant required.
Simulates an exponential heating curve with optional stall, then prints
predictions at each step to show convergence.
"""

import math
import sys
import os

# Allow importing predictor from same directory or parent
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "custom_components", "probe_ability"))

from predictor import CookPredictor, pull_temp, reading_plausible


def simulate_cook(
    ambient: float = 150.0,
    start_temp: float = 5.0,
    target_temp: float = 74.0,
    k: float = 0.0003,  # thermal constant (per second)
    stall_start: float = 65.0,  # set above target to disable stall
    stall_duration_min: float = 60,
    reading_interval: float = 30,  # seconds between readings
    total_minutes: float = 180,
):
    """Simulate a cook and test predictions."""
    print(f"{'':=<78}")
    print(f"Simulated cook: {start_temp}°C → {target_temp}°C in {ambient}°C ambient")
    print(f"Thermal constant k={k}, reading every {reading_interval}s")
    if stall_start < target_temp:
        print(f"Stall at {stall_start}°C for {stall_duration_min} min")
    print(f"{'':=<78}\n")

    predictor = CookPredictor(target_temp=target_temp)

    t = 0
    temp = start_temp
    stalling = False
    stall_remaining = stall_duration_min * 60
    total_seconds = total_minutes * 60

    # Calculate theoretical time to target (no stall)
    if ambient > target_temp:
        t_theory = -(1 / k) * math.log((ambient - target_temp) / (ambient - start_temp))
        print(f"Theoretical time (no stall): {t_theory / 60:.1f} min\n")

    print(f"{'Time':>8} {'Temp':>7} {'Predicted':>12} {'Phase':>10} {'Conf':>6}  Message")
    print(f"{'':->8} {'':->7} {'':->12} {'':->10} {'':->6}  {'':->30}")

    while t < total_seconds:
        # Physics step
        if stall_start < target_temp and temp >= stall_start and stall_remaining > 0:
            # Stall: minimal temperature change
            stalling = True
            temp += 0.001 * reading_interval  # ~0.002°C/min
            stall_remaining -= reading_interval
        else:
            stalling = False
            dt_temp = k * (ambient - temp) * reading_interval
            temp += dt_temp

        # Add some noise
        import random
        noisy_temp = temp + random.gauss(0, 0.2)
        noisy_ambient = ambient + random.gauss(0, 1.0)

        predictor.add_reading(t, noisy_temp, noisy_ambient)
        result = predictor.predict()

        # Print every 5 minutes
        if t % 300 < reading_interval:
            remaining_str = "—"
            if result.time_remaining_seconds is not None:
                remaining_str = f"{result.time_remaining_seconds / 60:.1f} min"

            print(
                f"{t / 60:7.1f}m {temp:6.1f}°C {remaining_str:>12} "
                f"{result.phase:>10} {result.confidence:>6}  {result.message}"
            )

        if temp >= target_temp:
            print(f"\n✓ Target reached at {t / 60:.1f} min")
            break

        t += reading_interval

    print()


def check_rest_and_pull() -> None:
    """Assert-based checks: rate-based pull temperature and rest / peak detection."""
    checks = 0

    def ok(cond, what):
        nonlocal checks
        assert cond, what
        checks += 1

    # pull_temp: carryover = 2 x heating rate, clamped to 1-8 C
    ok(pull_temp(82.0, 1.01) == 80.0, "chicken at 1.01 C/min: 2.0 C carryover -> pull at 80.0")
    ok(pull_temp(54.0, 0.39) == 53.0, "slow sirloin: carryover floors at 1.0")
    ok(pull_temp(60.0, 5.0) == 52.0, "hot grill: carryover caps at 8.0")
    ok(pull_temp(70.0, 0.0) is None and pull_temp(70.0, None) is None, "no positive rate -> no pull temp")

    def heat(p, t0, temp0, temp1, amb, steps, dt=30.0):
        for i in range(1, steps + 1):
            p.add_reading(t0 + i * dt, temp0 + (temp1 - temp0) * i / steps, amb)
            p.predict()
        return t0 + steps * dt

    # A: pulled 5 C short, coasts +1.8 C, peaks, cools -> finished with the shortfall reported
    p = CookPredictor(target_temp=82.0); p.add_reading(0.0, 20.0, 190.0)
    t = heat(p, 0.0, 20.0, 76.8, 190.0, 80)
    for temp in (77.2, 77.7, 77.9, 78.2, 78.4, 78.5, 78.6, 78.6, 78.5, 78.4, 78.3, 78.2, 78.1, 78.0):
        t += 30.0; p.add_reading(t, temp, 110.0); r = p.predict()
    ok(r.phase == "done", f"short rest should finish at its peak, got {r.phase}: {r.message}")
    ok(r.message.startswith("Rested") and "3.4°C below target" in r.message, f"done message: {r.message}")
    ok(p.rest_peak_c == 78.6 and abs(p.pulled_at_c - 77.2) < 0.5 and p.rest_short_c == 3.4, "rest fields")
    ok(p.predict().phase == "done", "rest-done stays latched")
    ok(CookPredictor.from_dict(p.to_dict()).predict().phase == "done", "rest-done survives save/restore")

    # B: lid opened for a minute mid-cook -> not a pull; the cook carries on and reaches target
    p = CookPredictor(target_temp=82.0); p.add_reading(0.0, 20.0, 190.0)
    t = heat(p, 0.0, 20.0, 74.0, 190.0, 70)
    t += 30.0; p.add_reading(t, 74.3, 120.0); p.predict()
    t += 30.0; p.add_reading(t, 74.6, 125.0); r = p.predict()
    ok(r.phase != "done", "a lid/door dip must not finish the cook")
    heat(p, t, 74.6, 82.0, 190.0, 20)
    r = p.predict()
    ok(r.phase == "done" and r.message == "Target temperature reached", f"after the dip: {r.phase} {r.message}")
    ok(p.rest_peak_c is None, "no rest recorded for a dip")

    # C: meat pulled with the probe coming out -> readings plunge -> no rest, not finished
    p = CookPredictor(target_temp=82.0); p.add_reading(0.0, 20.0, 190.0)
    t = heat(p, 0.0, 20.0, 76.8, 190.0, 80)
    for temp in (76.0, 70.0, 55.0, 40.0, 30.0):
        t += 30.0; p.add_reading(t, temp, 110.0); r = p.predict()
    ok(r.phase != "done" and p.rest_peak_c is None, f"probe-out must not finish: {r.phase} {r.message}")

    # D: a fire dip during a stall must not finish the cook; the heat returns and it reaches target
    p = CookPredictor(target_temp=96.0); p.add_reading(0.0, 20.0, 110.0)
    t = heat(p, 0.0, 20.0, 90.0, 110.0, 80)
    for _ in range(16):                                   # 8 min at 84 C ambient, meat flat at 90.0
        t += 30.0; p.add_reading(t, 90.0, 84.0); r = p.predict()
        ok(r.phase != "done", f"fire dip + stall must not finish: {r.phase} {r.message}")
    heat(p, t, 90.0, 96.0, 110.0, 24)
    r = p.predict()
    ok(r.phase == "done" and r.message == "Target temperature reached" and p.rest_peak_c is None,
       f"after the fire came back: {r.phase} {r.message} rest_peak={p.rest_peak_c}")

    # E: rested "done", then the meat goes back in the oven -> un-latches and finishes normally
    p = CookPredictor(target_temp=82.0); p.add_reading(0.0, 20.0, 190.0)
    t = heat(p, 0.0, 20.0, 76.8, 190.0, 80)
    for temp in (77.2, 77.7, 77.9, 78.2, 78.4, 78.5, 78.6, 78.6, 78.5, 78.4, 78.3, 78.2, 78.1, 78.0):
        t += 30.0; p.add_reading(t, temp, 110.0); r = p.predict()
    ok(r.phase == "done" and r.message.startswith("Rested"), "rested-done first")
    heat(p, t, 78.0, 83.0, 190.0, 20)
    r = p.predict()
    ok(r.phase == "done" and r.message == "Target temperature reached" and p.rest_peak_c is None,
       f"back in the oven: {r.phase} {r.message} rest_peak={p.rest_peak_c}")

    # F: target history — seeded at the first reading, appended on every mid-cook change
    p = CookPredictor(target_temp=71.0)
    ok(p.target_history == [], "no history before the first reading")
    p.add_reading(1000.0, 20.0, 190.0)
    ok(p.target_history == [[0.0, 71.0]], f"seeded with the start target: {p.target_history}")
    p.add_reading(1030.0, 21.0, 190.0); p.target_temp = 71.0
    ok(p.target_history == [[0.0, 71.0]], "unchanged target does not append")
    p.add_reading(1060.0, 22.0, 190.0); p.target_temp = 73.0
    ok(p.target_history == [[0.0, 71.0], [60.0, 73.0]], f"change appended at elapsed 60 s: {p.target_history}")
    p.target_temp = 74.0
    ok(p.target_history == [[0.0, 71.0], [60.0, 74.0]], "second change in the same reading replaces")
    ok(CookPredictor.from_dict(p.to_dict()).target_history == p.target_history, "history survives save/restore")
    old = p.to_dict(); old.pop("target_history")
    ok(CookPredictor.from_dict(old).target_history == [[0.0, 74.0]], "old save without history is seeded from its target")
    p.reset()
    ok(p.target_history == [], "reset clears the history")

    print(f"All {checks} checks passed.")


def check_smoothing_tracks_clock() -> None:
    """The EMA must age the previous estimate before blending.

    Feed a model that is *exactly* right at every reading.  The displayed
    value may lag while the EMA warms up, but must not settle at a steady
    offset behind the truth (the old smoother sat ~2.8 min pessimistic on
    every cook — invisible on a brisket, the whole endgame on a 25 min lamb).
    """
    checks = 0

    def ok(cond, what):
        nonlocal checks
        assert cond, what
        checks += 1

    t_fin = 3600.0
    p = CookPredictor(target_temp=74.0)
    p._ml_estimate = lambda: max(0.0, t_fin - p.readings[-1][0])  # perfect oracle
    errs = []
    for i in range(0, 100):
        now = i * 30.0
        p.add_reading(now, 20.0 + 50.0 * now / t_fin, 180.0)
        r = p.predict()
        if r.time_remaining_seconds is not None and now < t_fin - 300:
            errs.append(r.time_remaining_seconds - (t_fin - now))
    ok(len(errs) > 30, "oracle cook produced predictions")
    settled = errs[len(errs) // 2:]
    ok(max(abs(e) for e in settled) < 15.0, f"smoothed value tracks a perfect oracle (max offset {max(abs(e) for e in settled):.0f}s)")
    ok(min(settled) > -15.0, "no systematic optimism either")
    print(f"All {checks} checks passed.")


def check_names_and_readings() -> None:
    """Cook-name resolution (full / cut / category / fallback), inline-map parity with
    cook_presets.json, training-parity fallback, and the reading plausibility filter."""
    import json
    import ml_predictor as mlp
    checks = 0

    def ok(cond, what):
        nonlocal checks
        assert cond, what
        checks += 1

    # inline maps == cook_presets.json (the file the card and retrain.py use)
    here = os.path.dirname(os.path.abspath(__file__))
    presets = json.load(open(os.path.join(here, "custom_components", "probe_ability", "www", "cook_presets.json")))
    full, cuts, cats = {}, {}, {}
    for cat in presets["categories"]:
        cats[cat["label"]] = cat["cuts"][0]["id"]
        for cut in cat["cuts"]:
            cuts[f"{cat['label']} {cut['label']}"] = (cut["id"], tuple((d["id"], float(d["temp"])) for d in cut["doneness"]))
            for d in cut["doneness"]:
                full[f"{cat['label']} {cut['label']} {d['label']}"] = mlp._encode(cut["id"], d["id"])
    ok(mlp._COOK_NAME_MAP == full, f"_COOK_NAME_MAP drifted from cook_presets.json: {set(mlp._COOK_NAME_MAP) ^ set(full)}")
    ok(mlp._CUT_NAME_MAP == cuts, "_CUT_NAME_MAP drifted from cook_presets.json")
    ok(mlp._CATEGORY_NAME_MAP == cats, "_CATEGORY_NAME_MAP drifted from cook_presets.json")

    # fallback = what training used ("other"), never a steak
    ok(mlp._DEFAULT_MEAT == mlp._encode("other", "medium") == (3, 5, 4, 12, 2), f"fallback {mlp._DEFAULT_MEAT}")
    ok(mlp.resolve_meat("Custom") == mlp._DEFAULT_MEAT and mlp.resolve_meat("") == mlp._DEFAULT_MEAT, "unknown names -> fallback")

    # degradation ladder
    ok(mlp.resolve_meat("Beef Burger Medium") == mlp._encode("burger", "medium"), "full preset")
    ok(mlp.resolve_meat("Beef Burger", 56.0) == mlp._encode("burger", "medium_rare"), "cut + typed 56 -> nearest doneness (55 medium rare)")
    ok(mlp.resolve_meat("Beef Burger", 69.0) == mlp._encode("burger", "well_done"), "cut + typed 69 -> nearest doneness (71 well done)")
    ok(mlp.resolve_meat("Beef Burger") == mlp._encode("burger", "medium"), "cut, no target -> medium")
    ok(mlp.resolve_meat("Beef")[:2] == mlp._encode("sirloin", "medium")[:2] and mlp.resolve_meat("Beef")[2:] == (4, 12, 2), "category only -> beef codes, generic cut")
    ok(mlp.resolve_meat("Poultry Whole Bird Well Done") == mlp._encode("whole", "well_done"), "multi-word preset")

    # reading plausibility filter
    ok(reading_plausible(20.0, 100.0) and reading_plausible(-5.0, 0.0), "normal readings accepted")
    ok(not reading_plausible(-1838.2, 68.5), "glitch -1838 C rejected")
    ok(not reading_plausible(20.0, 2562.0) and not reading_plausible(float("nan"), 100.0), "bogus ambient / NaN rejected")
    p = CookPredictor(target_temp=56.0)
    p.add_reading(0.0, 9.0, 36.4); p.add_reading(31.7, -1838.2, 68.5); p.add_reading(61.9, 11.0, 85.4)
    ok(len(p.readings) == 2 and p.readings[1][1] == 11.0, f"glitch never entered the cook: {p.readings}")

    print(f"All {checks} checks passed.")


def check_collection_window() -> None:
    """Collecting ends early on a fast, steady rise and waits a little on a flat probe."""
    checks = 0

    def ok(cond: bool, what: str) -> None:
        nonlocal checks
        assert cond, what
        checks += 1
        print(f"  ok  {what}")

    def first_ready(curve, target=74.0, step=30.0, minutes=30):
        """Feed curve(t_s) -> (internal, ambient); return (ready_s, predictor)."""
        p = CookPredictor(target_temp=target)
        progress = []
        for n in range(int(minutes * 60 / step) + 1):
            t = n * step
            ti, ta = curve(t)
            p.add_reading(t, ti, ta)
            p.predict()
            progress.append(p.collect_progress)
            if p._collect_ready:
                return t, p, progress
        return None, p, progress

    # Hot and fast: ~2 °C/min from the start
    ready, p, progress = first_ready(lambda t: (8 + 2.0 * t / 60, 220.0))
    ok(ready is not None and ready < p._min_data_seconds, f"fast cook predicts before 10 min (at {ready}s)")
    ok(ready >= p._collect_floor_s, "...but not before the floor")
    ok(all(b >= a for a, b in zip(progress, progress[1:])), "progress never goes backwards")
    ok(progress[-1] == 100 and max(progress[:-1]) < 100, "progress hits 100 only when ready")

    # Normal low-and-slow: 0.3 °C/min — moving, so the usual 10 minutes
    ready, p, _ = first_ready(lambda t: (5 + 0.3 * t / 60, 110.0), target=96.0)
    ok(ready is not None and abs(ready - p._min_data_seconds) <= 30, f"slow cook starts at 10 min (at {ready}s)")

    # Barely moving: waits past 10 min, released at the cap
    ready, p, _ = first_ready(lambda t: (5 + 0.05 * t / 60, 110.0), target=96.0)
    ok(ready is not None and ready > p._min_data_seconds, f"flat probe waits past 10 min (at {ready}s)")
    ok(ready <= p._collect_max_s, "...but never beyond the cap")

    # Probe-insertion settle: warm from the air, drops into cold meat, then flat
    def insertion(t):
        return (max(4.0, 25.0 - 7.0 * t / 60), 110.0)
    ready, p, _ = first_ready(insertion, target=96.0)
    ok(ready is not None and ready > p._collect_floor_s, "insertion drop does not count as a rise")

    # A single spike after the floor is not a steady rise
    ready, p, _ = first_ready(lambda t: (20.0 + (10.0 if t >= 330 else 0.0), 180.0), minutes=8)
    ok(ready is None, "a one-off jump does not end collecting")

    # Latch: survives a flat spot and a save/restore
    ready, p, _ = first_ready(lambda t: (8 + 2.0 * t / 60, 220.0))
    t_last = p.readings[-1][0]
    for k in range(1, 6):
        p.add_reading(t_last + 30 * k, p.readings[-1][1], 220.0)
    ok(p.predict().phase != "collecting", "ready stays latched through a flat spot")
    restored = CookPredictor.from_dict(p.to_dict())
    ok(restored._collect_ready and restored.predict().phase != "collecting", "latch survives save/restore")

    # A cook saved before the dynamic window: predicting at >= 10 min stays predicting
    legacy = CookPredictor(target_temp=96.0)
    for n in range(25):
        legacy.add_reading(n * 30.0, 20.0, 110.0)  # 12 min, flat
    state = legacy.to_dict()
    state.pop("collect_ready")
    ok(CookPredictor.from_dict(state)._collect_ready, "legacy cook past 10 min is not sent back to collecting")
    p.reset()
    ok(not p._collect_ready and p.collect_progress == 0, "reset clears the latch")

    print(f"All {checks} checks passed.")


if __name__ == "__main__":
    print("\n━━━ TEST 1: Normal roast (no stall) ━━━\n")
    simulate_cook(
        ambient=180, start_temp=5, target_temp=74, k=0.0004,
        stall_start=999,  # no stall
        total_minutes=120,
    )

    print("\n━━━ TEST 2: Low-and-slow with stall (brisket) ━━━\n")
    simulate_cook(
        ambient=110, start_temp=5, target_temp=96, k=0.0002,
        stall_start=68, stall_duration_min=45,
        total_minutes=600,
    )

    print("\n━━━ TEST 3: Hot and fast (chicken) ━━━\n")
    simulate_cook(
        ambient=220, start_temp=8, target_temp=74, k=0.0006,
        stall_start=999,
        total_minutes=60,
    )

    print("\n━━━ TEST 4: pull temperature + rest detection (asserts) ━━━\n")
    check_rest_and_pull()

    print("\n━━━ TEST 5: cook-name resolution, preset parity, reading filter (asserts) ━━━\n")
    check_names_and_readings()

    print("\n━━━ TEST 6: EMA ages the previous estimate (asserts) ━━━\n")
    check_smoothing_tracks_clock()

    print("\n━━━ TEST 7: dynamic data-collection window (asserts) ━━━\n")
    check_collection_window()
