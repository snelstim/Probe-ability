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

from predictor import CookPredictor, has_carryover, pull_temp, reading_plausible


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

    # G: bread has no carryover — the target is the removal point (a sourdough heating at
    # 7 C/min was told to pull at 85 C for a 93 C target), and an ambient collapse near the
    # target is the oven door, not a rest
    ok(not has_carryover("Bread Sourdough Baked") and not has_carryover("Bread")
       and not has_carryover("Bread Rye") and not has_carryover(" Bread Yeasted Baked "),
       "bread presets and the bare category have no carryover")
    ok(has_carryover("Beef Sirloin Rare") and has_carryover("Custom") and has_carryover("")
       and has_carryover(None) and has_carryover("Breadfruit Roast"), "everything else keeps carryover")
    for name, expect_rest in (("Bread Sourdough Baked", False), ("Beef Sirloin Rare", True)):
        p = CookPredictor(target_temp=93.0); p.cook_name = name; p.add_reading(0.0, 20.0, 240.0)
        t = heat(p, 0.0, 20.0, 86.0, 240.0, 60)
        for temp in (86.4, 86.9, 87.3, 87.6, 87.8, 87.9, 88.0, 88.0, 87.9, 87.8, 87.7, 87.6, 87.5, 87.4):
            t += 30.0; p.add_reading(t, temp, 130.0); r = p.predict()     # oven off / door open, probe still in
        ok((p.rest_peak_c is not None) == expect_rest and (r.message.startswith("Rested") == expect_rest),
           f"{name}: rest tracking {'on' if expect_rest else 'off'}, got rest_peak={p.rest_peak_c} {r.message}")

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


def check_forecast_curve() -> None:
    """forecast_curve(): pure, anchored on the published ETA, shaped by Newton's law."""
    import json
    checks = 0

    def ok(cond, what):
        nonlocal checks
        assert cond, what
        checks += 1

    def cook(ambient=180.0, minutes=14, target=74.0):
        p = CookPredictor(target_temp=target)
        for i in range(minutes * 2):
            now = i * 30.0
            temp = ambient - (ambient - 5.0) * math.exp(-0.0004 * now)
            p.add_reading(now, temp, ambient)
            p.predict()
        return p

    p = CookPredictor(target_temp=74.0)
    ok(p.forecast_curve() is None, "no readings -> None")
    p.add_reading(0.0, 5.0, 180.0)
    p.predict()
    ok(p.forecast_curve() is None, "collecting -> None")

    p = cook()
    last = p.predict()
    ok(last.time_remaining_seconds is not None, "simulated cook has an ETA")
    before = json.dumps(p.to_dict(), sort_keys=True)
    fc = p.forecast_curve()
    ok(json.dumps(p.to_dict(), sort_keys=True) == before, "forecast_curve does not mutate predictor state")
    ok(fc is not None, "mid-cook forecast exists")
    now_ts, cur, amb = p.readings[-1]
    curve = fc["curve"]
    ok(abs(curve[0][0] - now_ts) < 1 and abs(curve[0][1] - cur) < 0.05, "curve starts at the latest reading")
    ok(abs(curve[-1][1] - 74.0) < 0.05, "curve ends at the target")
    ok(abs(curve[-1][0] - fc["eta_ts"]) < 1, "curve ends at the ETA")
    ok(all(b[1] >= a[1] - 1e-6 for a, b in zip(curve, curve[1:])), "curve is monotonic rising")
    ok(all(c[1] <= amb for c in curve), "curve stays below the ambient")
    served = p._serve_stale(now_ts)
    ok(abs((fc["eta_ts"] - now_ts) - served) < 1, "ETA matches the one the sensor serves")
    # Newton shape: heating slows as the gap to the ambient closes
    half = len(curve) // 2
    ok(curve[half][1] - curve[0][1] > curve[-1][1] - curve[half][1], "curve flattens toward the target")
    band = fc["band"]
    ok(fc["early_ts"] <= fc["eta_ts"] - 60.0 + 1e-6, "range reaches at least 1 min before the ETA")
    ok(fc["late_ts"] >= fc["eta_ts"] + 60.0 - 1e-6, "range reaches at least 1 min after the ETA")
    ok(all(lo <= hi + 1e-6 for _, lo, hi in band), "band lower edge never above upper edge")
    ok(abs(band[-1][0] - fc["late_ts"]) < 1, "band ends at the latest ETA")
    ok(abs(band[-1][1] - 74.0) < 0.05, "late edge reaches the target at the band's end")
    ok(all(lo - 0.05 <= curve[0][1] <= hi + 0.05 for _, lo, hi in band[:1]), "band starts around the current temp")
    first_hi = next(i for i, (_, _, hi) in enumerate(band) if hi >= 74.0 - 0.05)
    ok(band[first_hi][0] < fc["eta_ts"] + 1 and first_hi < len(band) - 1, "early edge reaches the target before the ETA")
    ok(all(lo < 74.0 - 0.05 for _, lo, _ in band[:-1]), "late edge stays below the target until the band ends")

    # Earliest / latest published ETA drive the band
    def with_etas(offsets):
        """A mid-cook predictor whose recent published ETAs sit at now + offsets (s)."""
        r = cook()
        now = r.readings[-1][0]
        r._recent_etas = [(now - 30.0 * (len(offsets) - i), now + off) for i, off in enumerate(offsets)]
        r._last_stable_remaining, r._last_stable_ts = 1000.0, now   # current ETA = now + 1000
        return r, now

    r, now = with_etas([880.0, 1100.0, 940.0, 1010.0])
    f2 = r.forecast_curve()
    ok(abs(f2["early_ts"] - (now + 880.0)) < 0.1, "early_ts is the earliest recent ETA")
    ok(abs(f2["late_ts"] - (now + 1100.0)) < 0.1, "late_ts is the latest recent ETA")
    ok(abs(f2["eta_ts"] - (now + 1000.0)) < 0.1, "eta_ts stays the published ETA")
    ok(abs(f2["band"][-1][0] - (now + 1100.0)) < 0.1, "band runs to the latest ETA")
    r, now = with_etas([1000.0, 1000.0, 1000.0])
    f3 = r.forecast_curve()
    ok(abs((f3["eta_ts"] - f3["early_ts"]) - 60.0) < 0.1 and abs((f3["late_ts"] - f3["eta_ts"]) - 60.0) < 0.1,
       "steady ETAs still get the +/-1 min floor")
    r, now = with_etas([100.0, 9000.0])
    f4 = r.forecast_curve()
    ok(abs((f4["eta_ts"] - f4["early_ts"]) - 500.0) < 0.1, "range is capped at 50 % earlier than the ETA")
    ok(abs((f4["late_ts"] - f4["eta_ts"]) - 500.0) < 0.1, "range is capped at 50 % later than the ETA")
    r, now = with_etas([1500.0, 1600.0])   # every recent ETA is later than the current one
    f5 = r.forecast_curve()
    ok(f5["early_ts"] <= f5["eta_ts"] <= f5["late_ts"], "current ETA is always inside the range")
    ok(abs(f5["late_ts"] - (now + 1500.0)) < 0.1, "capped at 150 % of the remaining time")

    # Ambient barely above the target -> straight line
    q = CookPredictor(target_temp=74.0)
    q._last_stable_remaining, q._last_stable_ts = 1200.0, 0.0
    for i in range(12):
        q.add_reading(float(i * 30), 60.0 + i * 0.3, 74.5)
    q._last_stable_ts = q.readings[-1][0]
    fc2 = q.forecast_curve()
    ok(fc2 is not None, "near-ambient target still forecasts")
    c2 = fc2["curve"]
    d1 = c2[1][1] - c2[0][1]
    d2 = c2[-1][1] - c2[-2][1]
    ok(abs(d1 - d2) < 0.02, "linear fallback has constant slope")

    ok(abs(p.remaining_seconds() - served) < 1e-6, "remaining_seconds is the published estimate")
    ok(json.dumps(p.to_dict(), sort_keys=True) == before, "remaining_seconds does not mutate state")

    # Done / rest / stale -> None
    done = CookPredictor(target_temp=74.0)
    done._last_stable_remaining, done._last_stable_ts = 600.0, 0.0
    done.add_reading(0.0, 74.2, 180.0)
    ok(done.forecast_curve() is None, "at target -> None")
    done._done_latched = True
    ok(done.remaining_seconds() is None, "done -> no remaining")
    ok(CookPredictor(target_temp=74.0).remaining_seconds() is None, "no readings -> no remaining")
    stale = cook()
    stale._last_stable_ts = stale.readings[-1][0] - 3600.0
    ok(stale.forecast_curve() is None, "stale ETA -> None")
    resting = cook()
    resting._rest_pulled_at = 70.0
    ok(resting.forecast_curve() is None, "resting -> None")

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

    print("\n━━━ TEST 8: forecast curve for the graph view (asserts) ━━━\n")
    check_forecast_curve()
