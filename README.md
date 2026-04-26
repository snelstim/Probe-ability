[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
# Probe-ability

A Home Assistant custom integration that predicts when your meat will reach a target internal temperature — like a Meater or other predictive thermometer, but using any temperature sensors you already have.

<p align="center">
  <img src="docs/screenshots/collecting.png" width="22%" alt="Collecting data">
  <img src="docs/screenshots/pull-warning.png" width="22%" alt="Pull from heat warning">
  <img src="docs/screenshots/two-probes.png" width="22%" alt="Two probes active">
  <img src="docs/screenshots/probe-done.png" width="22%" alt="Probe 2 done">
</p>

---

## How it works

Probe-ability uses a two-layer prediction system:

**1. ML model (primary)** — A Gradient Boosted Regressor trained on 140 real cooks (133 from a Meater device, 7 from Probe-ability exports) across beef, pork, poultry, lamb, and fish. It predicts time remaining from 17 features: current and starting temperatures, heating rate, deceleration, elapsed time, ambient temperature statistics, stall detection, and meat type. It achieves ~4 min cross-validated mean absolute error across all meat types and is accurate from the moment collecting ends. The model is embedded directly in `ml_model_code.py` (no external model file needed) and requires `scikit-learn` (installed automatically by Home Assistant on first run).

**2. Physics model (fallback)** — Newton's Law of Heating: fits an exponential curve to recent readings and solves for the time at which the meat will reach target temperature. Used automatically if the ML model is unavailable (model file missing, scikit-learn not yet installed, or prediction error).

Both layers share the same data pipeline: readings are collected for ~10 minutes before any prediction is made, ensuring there is enough temperature history to compute the features the ML model needs.

**Stall detection** — During barbecue stalls (common with brisket and pork shoulder), heating rate drops near zero. Probe-ability detects this plateau and flags predictions as low confidence. The ML model was trained on cooks that include stalls and handles them significantly better than the physics-only fallback.

**EMA smoothing** — The time-remaining estimate is smoothed using an exponential moving average (α = 0.15) to dampen sensor noise without hiding real trends, preventing the display from jumping between readings.

**Pull-from-heat warning** — Meat continues warming after removal from heat (carryover cooking). Probe-ability calculates the pull temperature and shows a prominent warning when the meat reaches it.

---

## Installation

### Via HACS (recommended)

1. In HACS, go to **Integrations → ⋮ → Custom repositories**.
2. Add `https://github.com/snelstim/Probe-ability` as an **Integration** repository.
3. Search for **Probe-ability** and install it.
4. Restart Home Assistant.
5. Go to **Settings → Devices & Services → Add Integration** and search for **Probe-ability**.
6. Fill in the configuration form (see [Configuration](#configuration) below).

### Manual installation

1. Copy the `custom_components/probe_ability` folder into your HA `config/custom_components/` directory.
2. Restart Home Assistant. On first run, HA will install `scikit-learn` automatically (this may take a minute).
3. Go to **Settings → Devices & Services → Add Integration** and search for **Probe-ability**.
4. Fill in the configuration form (see [Configuration](#configuration) below).

Check the HA log for:
```
Probe-ability: ML model loaded
```
If this line appears, the ML model is active. If it's absent, predictions fall back to the physics model.

### Lovelace card

The card JavaScript is served automatically by the integration — no manual file copying needed.

In Lovelace, go to **Edit Dashboard → Manage Resources** and add:
- URL: `/probe_ability/probe-ability-card.js`
- Type: JavaScript Module

Then add the card to a dashboard (see [Card configuration](#card-configuration) below).

---

## Configuration

The config flow is a one-time hardware setup. It does **not** ask for target temperatures or cook names — those are set per-cook from the Lovelace card.

| Field | Required | Description |
|---|---|---|
| **Probe 1 sensor** | Yes | Internal (meat) temperature sensor — primary probe |
| **Ambient sensor** | Yes | Ambient (oven/smoker/air) temperature sensor |
| **Probe 2 sensor** | No | Second internal probe (optional) |
| **Probe 3 sensor** | No | Third internal probe (optional) |
| **Export cook data** | No | Save a CSV after every cook for local analysis/fine-tuning |
| **Share anonymous cook data** | No | Opt-in: send completed cooks to improve the shared ML model (see [Anonymous data sharing](#anonymous-data-sharing)) |

> **Tip:** All sensor entities must have the `temperature` device class. The entity selector in the config flow filters for this automatically.

---

## Card configuration

```yaml
type: custom:probe-ability-card
entity: sensor.probe_ability_time_remaining
```

### All options

| Option | Required | Description |
|---|---|---|
| `entity` | **Yes** | The primary `time_remaining` sensor entity ID |
| `eta_entity` | No | The `estimated_completion` sensor entity ID. If omitted the ETA is computed client-side from the time remaining value |
| `entry_id` | No | Config entry ID — only needed when you have **multiple instances** of the integration installed. See [Multiple instances](#multiple-instances) |
| `probe_sensors` | No | List of internal probe sensor entity IDs — enables pre-flight availability checking in the card UI (see [Probe availability](#probe-availability)) |
| `ambient_sensor` | No | Ambient (oven/smoker) sensor entity ID — if set, the card shows "no sensors" until the ambient sensor is also available |

### Minimal (single instance)

```yaml
type: custom:probe-ability-card
entity: sensor.probe_ability_time_remaining
```

### Full example (3 probes, multi-instance)

```yaml
type: custom:probe-ability-card
entity: sensor.probe_ability_time_remaining
eta_entity: sensor.probe_ability_estimated_completion
entry_id: abc123def456
ambient_sensor: sensor.smoker_ambient_temperature
probe_sensors:
  - sensor.probe_1_temperature
  - sensor.probe_2_temperature
  - sensor.probe_3_temperature
```

---

## Using the card

### Idle state

The card starts in idle mode. Before pressing Start, choose your cook setup:

- **Combined mode** — all probes monitor the same piece of meat (e.g. a brisket with probes in different spots). One target temperature, one shared timer showing when the *slowest* probe reaches target.
- **Individual mode** — each probe is independent (e.g. 3 steaks at different doneness levels). Each probe gets its own target temperature and countdown timer.

Pick a **preset** from the dropdown (e.g. *Beef Sirloin Medium Rare — 54°C*) or type a custom target temperature, then press **Start Cook** (combined) or **Start Probe N** (individual).

### Collecting data

After starting, the card shows a progress bar while gathering the minimum data needed to make a reliable prediction (~10 readings over ~10 minutes). The bar fills in two phases:

1. **Phase 1** — reading count bar fills to 10/10
2. **Phase 2** — data span bar fills as the 10-minute window accumulates, with a "Ready at HH:MM" estimate

You can cancel during this phase.

### Active cook

Once enough data is collected:

- The card shows a circular ring timer with the time remaining
- **Tap the ring** to toggle between **countdown** (ring drains as time passes) and **temperature** (ring fills as temperature rises toward target). A faint hint inside the ring shows which mode you're in.
- Current internal and ambient temperatures, heating rate, ETA, cook phase, and confidence level are displayed
- When the meat approaches the pull temperature, a **prominent warning** appears telling you to remove it from heat now

### Done

When the target temperature is reached the card shows a completion screen. Press **New Cook** to reset and start again.

### Probe availability

If `probe_sensors` is configured in the card YAML, the card checks sensor availability in real time before showing the idle form:

| Available probes | UI shown |
|---|---|
| **0** | Warning message — no start button |
| **1** | Single form, no combined/individual toggle |
| **2–3** | Full UI with mode toggle; only available probe slots shown in individual mode |

Without `probe_sensors` configured the card assumes all probes are available and relies on the backend to raise an error if a probe is actually offline when you press Start. In that case a red notification toast appears in the HA frontend automatically.

---

## Entities

One pair of entities is created per configured probe:

| Entity | Probe 1 | Probe 2 | Probe 3 |
|---|---|---|---|
| **Time remaining** | `sensor.probe_ability_time_remaining` | `sensor.probe_ability_time_remaining_2` | `sensor.probe_ability_time_remaining_3` |
| **Estimated completion** | `sensor.probe_ability_estimated_completion` | `sensor.probe_ability_estimated_completion_2` | `sensor.probe_ability_estimated_completion_3` |

Entities are **unavailable** while idle or collecting (not enough data yet).

### Sensor attributes

The primary `time_remaining` sensor (probe 1) exposes all attributes the card needs, including cross-probe data for probes 2 and 3:

**Always present when active:**

| Attribute | Type | Description |
|---|---|---|
| `active` | bool | True if any probe is currently running |
| `probe_mode` | string | `"combined"` or `"individual"` |
| `probe_count` | int | Number of probes configured (1–3) |
| `probe_active` | list[bool] | Per-probe active state |

**Present when probe 1 is active:**

| Attribute | Type | Description |
|---|---|---|
| `phase` | string | `collecting`, `heating`, `stall`, `finishing`, or `done` |
| `confidence` | string | `low`, `medium`, or `high` |
| `target_temp` | float | Target internal temperature (°C) |
| `current_temp` | float | Latest internal temperature reading (°C) |
| `ambient_temp` | float | Latest ambient temperature reading (°C) |
| `rate_c_per_minute` | float | Current (smoothed) heating rate |
| `readings_count` | int | Number of readings collected so far |
| `pull_temp` | float | Temperature at which to remove from heat (carryover-adjusted) |
| `message` | string | Human-readable status message (during stall etc.) |

**Cross-probe attributes (when probes 2/3 are configured and active):**

| Attribute | Description |
|---|---|
| `current_temp_2` / `current_temp_3` | Current internal temp for probe 2/3 |
| `target_temp_2` / `target_temp_3` | Target temp for probe 2/3 |
| `probe_2_active` / `probe_3_active` | Whether that probe is running |
| `probe_2_phase` / `probe_3_phase` | Cook phase for probe 2/3 |
| `probe_2_confidence` / `probe_3_confidence` | Confidence for probe 2/3 |
| `probe_2_time_remaining` / `probe_3_time_remaining` | Minutes remaining for probe 2/3 |
| `probe_2_pull_temp` / `probe_3_pull_temp` | Pull temperature for probe 2/3 |
| `probe_2_rate_c_per_minute` / `probe_3_rate_c_per_minute` | Heating rate for probe 2/3 |

---

## Services

### `probe_ability.start_cook`

Start a new cook. If a sensor is unavailable when this is called, a red error notification is shown in the HA frontend.

| Parameter | Required | Default | Description |
|---|---|---|---|
| `target_temp` | No | 74 | Target internal temperature in °C |
| `cook_name` | No | `"Cook"` | Name label for this cook — also used by the ML model to select the correct meat type profile |
| `probe_mode` | No | `"combined"` | `"combined"` or `"individual"` |
| `probe_index` | No | — | Which probe to start (0–2). Only used in individual mode |
| `entry_id` | No | — | Target a specific integration instance (see below) |

**Combined mode** — omit `probe_index`. All configured probes with available sensors are started together.

**Individual mode** — set `probe_mode: "individual"` and `probe_index` to start one specific probe.

> **Tip:** Use a preset name matching one of the card's built-in presets as `cook_name` to give the ML model the most accurate meat type context. The format is `"Category Cut Doneness"` — for example:
> - `"Beef Sirloin Medium Rare"`, `"Beef Rib Eye Medium"`, `"Beef Brisket Fall Apart"`
> - `"Pork Shoulder Pulled"`, `"Pork Loin / Chop Well Done"`
> - `"Poultry Chicken Breast Medium"`, `"Poultry Duck Breast Medium"`
> - `"Lamb Leg Medium Rare"`, `"Lamb Rack / Ribs Rare"`
> - `"Other Fish / Salmon Medium Rare"`
>
> Custom names fall back to a generic beef profile.

### `probe_ability.stop_cook`

Stop a cook and clear data.

| Parameter | Required | Default | Description |
|---|---|---|---|
| `probe_index` | No | — | Stop only this probe (0–2). Omit to stop all probes |
| `entry_id` | No | — | Target a specific integration instance |

### `probe_ability.set_target`

Change the target temperature mid-cook without interrupting data collection.

| Parameter | Required | Default | Description |
|---|---|---|---|
| `target_temp` | **Yes** | — | New target temperature in °C |
| `probe_index` | No | — | Update only this probe (0–2). Omit to update all |
| `entry_id` | No | — | Target a specific integration instance |

---

## The `entry_id` parameter

### What it is

Every integration instance installed in HA gets a unique `entry_id` — a string like `abc123def456`. Probe-ability uses this to route service calls and card state to the correct instance.

### When you need it

You only need `entry_id` if you have **more than one instance** of Probe-ability installed (e.g. one for the smoker and one for the oven). With a single instance, `entry_id` can always be omitted — the integration finds the only available instance automatically.

### How to find your entry_id

1. Go to **Settings → Devices & Services → Probe-ability**
2. Click on the integration entry
3. The URL in your browser will contain the entry ID:
   `…/config/integrations/integration/probe_ability#entry_id=abc123def456`

Alternatively, check `config/.storage/core.config_entries` and look for `"domain": "probe_ability"`.

### Using it in the card

```yaml
type: custom:probe-ability-card
entity: sensor.probe_ability_time_remaining
entry_id: abc123def456
```

### Using it in automations

```yaml
service: probe_ability.start_cook
data:
  target_temp: 96
  entry_id: abc123def456
```

---

## Multiple instances

Install Probe-ability multiple times (once per independent set of sensors). Each instance gets its own config entry, entities, and `entry_id`.

**Example:** smoker + oven setup

| Instance | Sensors | Card entity |
|---|---|---|
| Smoker | `sensor.smoker_probe`, `sensor.smoker_ambient` | `sensor.probe_ability_time_remaining` |
| Oven | `sensor.oven_probe`, `sensor.oven_ambient` | `sensor.probe_ability_time_remaining_2` *(entity suffix set by HA)* |

Use `entry_id` in each card and in any automations to target the right instance.

> **Note:** Entity IDs for the second instance will be suffixed by HA to avoid collisions (e.g. `sensor.probe_ability_time_remaining_2`). The exact suffix depends on your HA version.

---

## Automations

### Notify 15 minutes before done

```yaml
automation:
  - alias: "Cook almost done"
    trigger:
      - platform: numeric_state
        entity_id: sensor.probe_ability_time_remaining
        below: 15
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "Almost done!"
          message: >
            Your cook is estimated to finish in
            {{ states('sensor.probe_ability_time_remaining') | round }} minutes
            (target {{ state_attr('sensor.probe_ability_time_remaining', 'target_temp') }}°C).
```

### Alert when to pull from heat

```yaml
automation:
  - alias: "Pull from heat"
    trigger:
      - platform: template
        value_template: >
          {% set cur = state_attr('sensor.probe_ability_time_remaining', 'current_temp') %}
          {% set pull = state_attr('sensor.probe_ability_time_remaining', 'pull_temp') %}
          {{ cur is not none and pull is not none and cur | float >= pull | float }}
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "Remove from heat now!"
          message: >
            Internal temp has reached the pull temperature.
            Remove from heat and rest — it will coast up to target.
```

### Auto-start a cook from an NFC tag or button

```yaml
script:
  start_brisket:
    alias: "Start brisket cook"
    sequence:
      - service: probe_ability.start_cook
        data:
          target_temp: 96
          cook_name: "Beef Brisket Fall Apart"
          probe_mode: combined
```

---

## Data export

Enable **Export cook data** in the config flow to automatically save a CSV file after every cook. Files are written to `config/probe_ability_exports/` and are named `cook_YYYYMMDD_HHMMSS_probeN.csv`.

### File format

Lines starting with `#` are metadata headers and can be skipped by most tools.

```
# probe_ability_export_version: 3
# integration_version: 0.6.1
# probe_index: 0
# probe_mode: combined
# cook_name: Beef Brisket Fall Apart
# target_temp_c: 96.0
# reached_target: true
# total_readings: 147
# export_timestamp: 2026-04-25T18:30:00.000000
elapsed_s,internal_temp_c,ambient_temp_c,predicted_remaining_s,confidence
0.0,22.50,120.00,,
32.1,22.75,121.00,,
645.0,29.00,125.00,4820.0,medium
...
```

`predicted_remaining_s` and `confidence` are empty during the initial collecting phase and populated from the moment predictions begin. They are generated by replaying the cook through a fresh predictor instance at export time, reproducing exactly what was shown live.

`integration_version` records which version of Probe-ability generated the file, useful for filtering data across versions when retraining the model.

Read in Python:

```python
import pandas as pd
df = pd.read_csv("cook_20260425_183000_probe1.csv", comment="#")
```

---

## Anonymous data sharing

Enable **Share anonymous cook data** in the config flow to automatically send completed cooks to a shared dataset used to retrain the ML model. This is entirely opt-in and off by default.

**What is sent:**
- Cook name, target temperature, duration
- Internal and ambient temperature readings (downsampled to ≤200 points)
- Median ambient temperature
- Integration version

**What is never sent:**
- Your Home Assistant URL
- Any device or user identifiers
- Incomplete cooks (only cooks where the probe reached the target temperature are shared)

Data is sent via an INSERT-only REST API secured with Row Level Security — anonymous clients can insert rows but cannot read, modify, or delete any data.

You can have export enabled without sharing, sharing enabled without export, both, or neither — they are independent settings.

---

## Technical details

| Detail | Value |
|---|---|
| Minimum readings before prediction | 10 readings AND 10 minutes of data span |
| Reading debounce interval | 30 seconds |
| Curve fitting window (physics fallback) | 40-minute sliding window |
| EMA smoothing factor (α) | 0.15 — half-life ≈ 4–5 readings (~2 min) |
| Carryover cooking model | `clamp((ambient − target) × 0.06, min=2°C, max=8°C)` — ambient-aware |
| Stale probe exclusion (combined ETA) | Probe excluded after 5 minutes without a new reading |
| State persistence | Survives HA restarts — cook state written to `.storage` |
| External dependencies | `scikit-learn>=1.3.0` (ML model) |

### Prediction model

**Primary — ML (Gradient Boosted Regressor):**

Trained on 140 cooks (133 Meater exports + 7 Probe-ability exports) across beef, pork, poultry, lamb, and fish. Target temperatures are derived from the cook's preset (e.g. medium rare beef → 54°C) rather than the peak temperature reached, ensuring training and inference are in the same distribution. Predicts minutes remaining from 17 features:

| Feature group | Features |
|---|---|
| Temperatures | Current internal, starting internal, target gap, current ambient, mean/std ambient so far |
| Rates | Initial rate (first 10 min), recent rate (last 5 min), deceleration ratio |
| Time | Elapsed minutes |
| State | Stall flag (rate < 0.2°C/min in 60–80°C zone) |
| Meat type | Category, animal, cut type, cut, doneness preset |

Cross-validated MAE: ~4 min overall; accurate from the end of the collecting phase. Meat type context is taken from the `cook_name` parameter — use one of the card's built-in preset names for best accuracy.

**Fallback — Physics (Newton's Law of Heating):**

Fits the curve `T(t) = T_ambient − (T_ambient − T₀) × e^(−kt)` to recent readings via least-squares regression, then solves for when `T = target`. Switches to linear extrapolation during stalls or when ambient is too close to target. Used automatically when `ml_model_code.py` cannot be loaded or scikit-learn is unavailable.

### Combined ETA

In combined mode the displayed ETA is `max(time_remaining)` across all active non-stale probes. This is correct because the cook is only *done* when **all** probes reach their target — so the slowest probe drives the timer.

### ML model file

The ML model is embedded in `ml_model_code.py` inside `custom_components/probe_ability/` and is committed to git. If you re-clone the repository the model is already there. To update it after retraining, re-run `retrain.py` and copy the generated `ml_model_code.py` into the component folder.

### Retraining the model

```bash
python3 retrain.py
```

Place Meater export files in `meater_exports/` and/or Probe-ability CSV exports in `probe_ability_exports/` before running. The script outputs a new `ml_model_code.py` (embedded model for HA, no `model.pkl` needed at runtime) and `retrain_output/model.pkl`. Copy `ml_model_code.py` to the component folder and restart HA.

---

## Testing

Test the prediction algorithm standalone, without running Home Assistant:

```bash
python3 test_predictor.py
```
