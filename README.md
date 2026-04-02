# Probe-ability

A Home Assistant custom integration that predicts when your meat will reach a target internal temperature — like a Meater or other predictive thermometer, but using any temperature sensors you already have.

## How it works

Uses Newton's Law of Heating to fit an exponential curve to your temperature data in real time. After ~10 minutes of data collection, it starts predicting the time remaining and estimated completion time. Predictions improve as more data comes in.

Handles stalls (common with brisket/pork shoulder) by detecting the plateau and switching to linear extrapolation with a low-confidence flag.

## Installation

### Integration

1. Copy `custom_components/probe_ability` into your HA `config/custom_components/` directory.
2. Restart Home Assistant.
3. Go to **Settings → Devices & Services → Add Integration** and search for **Probe-ability**.
4. Select your internal (meat) and ambient (oven/smoker) temperature sensor entities.

### Lovelace Card

1. Copy `www/probe-ability-card.js` to your HA `config/www/` directory.
2. In Lovelace, go to **Resources** (three-dot menu → Resources) and add:
   - URL: `/local/probe-ability-card.js`
   - Type: JavaScript Module
3. Add the card to a dashboard:

```yaml
type: custom:probe-ability-card
entity: sensor.probe_ability_time_remaining
eta_entity: sensor.probe_ability_estimated_completion
```

## How to use

The config flow only asks for the two sensor entities — that's the hardware setup and is done once.

Everything per-cook is handled through the **Lovelace card**:

1. **Pick a preset** (or type a custom cook name and target temperature).
2. **Press Start Cook** — the integration begins collecting temperature data.
3. **Wait for predictions** — the card shows a progress bar while collecting (~10 min). Once enough data is gathered, it switches to showing the time remaining and ETA.
4. **Monitor** — the card shows current internal/ambient temps, heating rate, cook phase, and confidence level.
5. **Done** — when target is reached, the card shows a completion screen. Press **New Cook** to start again.

## Entities

| Entity | Description |
|---|---|
| **Time remaining** | Estimated minutes until target is reached. Unavailable while collecting or idle. |
| **Estimated completion** | Timestamp of predicted completion. Unavailable while collecting or idle. |

The **Time remaining** sensor exposes attributes: `active`, `cook_name`, `phase`, `confidence`, `rate_c_per_minute`, `current_temp`, `ambient_temp`, `target_temp`, `readings_count`, `message`.

## Services

| Service | Description |
|---|---|
| `probe_ability.start_cook` | Start a new cook. Parameters: `target_temp`, `cook_name`, `entry_id` (optional). |
| `probe_ability.stop_cook` | Stop the current cook and clear data. |
| `probe_ability.set_target` | Change target temperature mid-cook. |

These services can be called from automations, scripts, or the card.

## Automations

Notify 15 minutes before done:

```yaml
automation:
  - alias: "Cook almost done"
    trigger:
      - platform: numeric_state
        entity_id: sensor.probe_ability_time_remaining
        below: 15
    action:
      - service: notify.mobile_app
        data:
          title: "Almost done!"
          message: >
            {{ state_attr('sensor.probe_ability_time_remaining', 'cook_name') }}
            is estimated to be done in
            {{ states('sensor.probe_ability_time_remaining') }} minutes.
```

## Multi-probe support

Add multiple instances of the integration (one per probe pair). In the card config, set `entry_id` to the specific config entry ID to target each instance.

## Testing

Test the prediction algorithm standalone without Home Assistant:

```bash
python3 test_predictor.py
```

## Technical details

- Predictions are hidden (entities unavailable) until enough data is collected (~10 min)
- Readings debounced to one per 30 seconds
- 40-minute sliding window for curve fitting
- State persisted to `.storage` — survives HA restarts mid-cook
- No external dependencies beyond Home Assistant core
