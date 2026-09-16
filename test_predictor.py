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

from predictor import CookPredictor, pull_temp


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
