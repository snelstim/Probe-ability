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

from predictor import CookPredictor


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
