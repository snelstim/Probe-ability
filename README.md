# Probe-ability

A Home Assistant custom integration that predicts when your meat will reach a target internal temperature — like a Meater or other predictive thermometer, but using any temperature sensors you already have.

---

## How it works

Probe-ability fits an exponential curve to your temperature readings in real time using Newton's Law of Heating. After collecting ~10 readings over ~10 minutes, it starts predicting the time remaining and estimated completion time. Predictions improve continuously as more data arrives.

**Stall detection** — During barbecue stalls (common with brisket and pork shoulder, caused by evaporative cooling), the exponential model stops fitting. Probe-ability detects this plateau and switches to linear extrapolation, flagging the prediction as low confidence until the stall ends and heating resumes.

**EMA smoothing** — The heating rate is smoothed using an exponential moving average (α = 0.15) to dampen sensor noise without hiding real trends. This prevents the estimated time remaining from jumping around between readings.

**Pull-from-heat warning** — Meat continues warming internally after being removed from heat (carryover cooking). Probe-ability calculates the pull temperature — the point at which you should remove the meat so it coasts up to your target. The pull temp is shown prominently once the meat is close to target.

---

## Installation

### 1. Integration

1. Copy the `custom_components/probe_ability` folder into your HA `config/custom_components/` directory.
2. Restart Home Assistant.
3. Go to **Settings → Devices & Services → Add Integration** and search for **Probe-ability**.
4. Fill in the configuration form (see [Configuration](#configuration) below).

### 2. Lovelace Card

1. Copy the `www/probe-ability/` folder to your HA `config/www/` directory (keeping the subfolder).
2. In Lovelace, go to **Edit Dashboard → Manage Resources** and add:
   - URL: `/local/probe-ability/probe-ability-card.js`
   - Type: JavaScript Module
3. Add the card to a dashboard (see [Card configuration](#card-configuration) below).

---

## Configuration

The config flow is a one-time hardware setup. It does **not** ask for target temperatures or cook names — those are set per-cook from the Lovelace card.

| Field | Required | Description |
|---|---|---|
| **Probe 1 sensor** | Yes | Internal (meat) temperature sensor — primary probe |
| **Ambient sensor** | Yes | Ambient (oven/smoker/air) temperature sensor |
| **Probe 2 sensor** | No | Second internal probe (optional) |
| **Probe 3 sensor** | No | Third internal probe (optional) |
| **Export cook data** | No | Save a CSV after every cook for analysis/fine-tuning |

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

Pick a **preset** from the dropdown (e.g. *Beef Medium Rare — 54°C*) or type a custom target temperature, then press **Start Cook** (combined) or **Start Probe N** (individual).

### Collecting data

After starting, the card shows a progress bar while gathering the minimum data needed to make a reliable prediction (~10 readings over ~10 minutes). The bar fills as readings accumulate. You can cancel during this phase.

### Active cook

Once enough data is collected:

- The card shows a circular ring timer with the time remaining
- Toggle between **⏱ countdown** (ring drains as time passes) and **🌡 temp-up** (ring fills as temperature rises toward target)
- Current internal and ambient temperatures, heating rate, cook phase, and confidence level are displayed
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
| `phase` | string | `collecting`, `heating`, `stall`, or `done` |
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

---

## Services

### `probe_ability.start_cook`

Start a new cook. If a sensor is unavailable when this is called, a red error notification is shown in the HA frontend.

| Parameter | Required | Default | Description |
|---|---|---|---|
| `target_temp` | No | 74 | Target internal temperature in °C |
| `cook_name` | No | `"Cook"` | Name label for this cook |
| `probe_mode` | No | `"combined"` | `"combined"` or `"individual"` |
| `probe_index` | No | — | Which probe to start (0–2). Only used in individual mode |
| `entry_id` | No | — | Target a specific integration instance (see below) |

**Combined mode** — omit `probe_index`. All configured probes with available sensors are started together.

**Individual mode** — set `probe_mode: "individual"` and `probe_index` to start one specific probe.

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
          cook_name: "Brisket"
          probe_mode: combined
```

---

## Data export

Enable **Export cook data** in the config flow to automatically save a CSV file after every cook. Files are written to `config/probe_ability_exports/` and are named `cook_YYYYMMDD_HHMMSS_probeN.csv`.

### File format

Lines starting with `#` are metadata headers and can be skipped by most tools.

```
# probe_ability_export_version: 3
# probe_index: 0
# probe_mode: combined
# target_temp_c: 96.0
# reached_target: true
# total_readings: 147
# export_timestamp: 2026-04-03T18:30:00.000000
elapsed_s,internal_temp_c,ambient_temp_c,predicted_remaining_s,confidence
0.0,22.50,120.00,,
32.1,22.75,121.00,,
...
```

Read in Python:

```python
import pandas as pd
df = pd.read_csv("cook_20260403_183000_probe1.csv", comment="#")
```

---

## Technical details

| Detail | Value |
|---|---|
| Minimum readings before prediction | 10 readings AND 10 minutes of data span |
| Reading debounce interval | 30 seconds |
| Curve fitting window | 40-minute sliding window |
| EMA smoothing factor (α) | 0.15 — half-life ≈ 4–5 readings (~2 min) |
| Carryover cooking model | `clamp(rate × 5, min=3°C, max=10°C)` |
| Stale probe exclusion (combined ETA) | Probe excluded after 5 minutes without a new reading |
| State persistence | Survives HA restarts — cook state written to `.storage` |
| External dependencies | None — only HA core |

### Prediction model

1. **Exponential (Newton's Law of Heating):** Used when ambient temperature is significantly above the meat temperature. Fits a curve of the form `T(t) = T_ambient - (T_ambient - T_0) × e^(-kt)` to the recent reading window, then solves for the time at which `T = target`.
2. **Linear fallback:** Used during stalls or when the meat temperature is close to ambient (e.g. crockpot/sous-vide). The rate of rise is estimated from recent readings and extrapolated linearly. Confidence is flagged as `low` until the model can fit the exponential again.

### Combined ETA

In combined mode the displayed ETA is `max(time_remaining)` across all active non-stale probes. This is correct because the cook is only *done* when **all** probes reach their target — so the slowest probe drives the timer.

---

## Testing

Test the prediction algorithm standalone, without running Home Assistant:

```bash
python3 test_predictor.py
```
