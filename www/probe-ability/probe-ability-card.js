/**
 * Probe-ability Card v0.11.0
 *
 * Custom Lovelace card for the Probe-ability integration.
 * Shows cook status, predictions, and lets you start/stop cooks.
 *
 * Features:
 *  - Individual mode: up to 4 independent probes (e.g. 4 steaks), each in its
 *    own tile — stacked, side by side or in a 2-column grid (probe_layout),
 *    optionally folding to a one-line summary (collapsible).  Probes are
 *    called "Probe N" unless named in the integration's Reconfigure dialog
 *    (e.g. "Green") — names arrive in the probe_names sensor attribute.
 *  - Combined mode: multiple probes on one cook (e.g. brisket)
 *  - Circular SVG timer with two display modes:
 *      ⏱ Countdown — ring drains as time passes
 *      🌡 Temp-up  — ring fills as temperature rises toward target
 *
 * Installation (via HACS — recommended):
 *   Add as a Lovelace resource:
 *     URL: /probe_ability/probe-ability-card.js
 *     Type: JavaScript Module
 *
 * Card config:
 *   type: custom:probe-ability-card
 *   entity: sensor.probe_ability_time_remaining
 *   entry_id: <your_entry_id>                               (optional)
 *   probe_layout: vertical | horizontal | grid              (optional)
 *   collapsible: true | false                               (optional)
 */

const CARD_VERSION = "0.11.0";

// ─── Localisation ────────────────────────────────────────────────────────────
//
// Custom cards can't read Home Assistant's backend translations, so the card
// ships its own string table.  To add a language, add an entry to I18N below
// (copy the "en" block and translate the values) — missing keys/languages fall
// back to English automatically.  Preset labels (cut / doneness names) are
// localised separately in cook_presets.json, NOT here — see _displayLabel().
//
// See docs/TRANSLATIONS.md for the full guide.

const I18N = {
  en: {
    start_cook: "Start Cook",
    start_probe: "Start {name}",
    cancel_cook: "Cancel Cook",
    stop_cook: "Stop Cook",
    cancel_probe: "Cancel {name}",
    new_cook_probe: "New Cook ({name})",
    stop_probe: "Stop {name}",
    new_cook: "New Cook",
    combined: "🔗 Combined",
    individual_toggle: "⚡ Individual",
    mode_combined: "Combined",
    mode_individual: "Individual",
    individual_badge: "Individual",
    loading_presets: "Loading presets…",
    select_cut: "— Select cut —",
    select_doneness: "— Select doneness —",
    target_temp_label: "Target temperature ({unit})",
    target_label: "Target ({unit})",
    no_probe_sensors: "No probe sensors available",
    no_probe_sensors_hint: "Check that your thermometer probes are connected and visible in Home Assistant.",
    warming_up_target: "Warming up… target",
    collecting_data: "Collecting data ({count}/{needed})",
    readings: "Readings: {count}/{needed}",
    building_span: "Building data span…",
    ready_at: "ready at {time}",
    remaining: "remaining",
    estimating: "estimating…",
    tap_for_temp: "tap for temp",
    tap_for_time: "tap for time",
    done_at: "Done ~{eta}",
    eta: "ETA: {eta}",
    rate: "Rate: {rate} {unit}/min",
    stalled: "(stalled)",
    ambient: "Ambient",
    internal: "Internal",
    probe_n: "Probe {n}",
    of_temp: "of {temp}",
    remove_from_heat: "Remove from heat",
    remove_from_heat_now: "Remove from heat now!",
    carryover_full: "Carryover cooking will bring it to {temp}.",
    pull_temp: "Pull temperature: {temp}.",
    carryover_short: "Carryover will bring it to {temp}.",
    pull_temp_short: "Pull temp: {temp}.",
    stall_detected: "Temperature stall detected",
    stall_detail: "Time shown is the last stable estimate. It will resume updating when the temperature starts rising again.",
    stall_short: "Stall — showing last stable estimate",
    unreachable_detected: "Target cannot be reached",
    unreachable_detail: "The ambient temperature has dropped below the target. Increase the heat to finish the cook.",
    unreachable_short: "Ambient below target — increase the heat",
    target_reached: "Target reached!",
    cook_complete: "Cook Complete!",
    target_temp_reached: "Target temperature reached.",
    not_started: "Not started",
    are_you_sure: "Are you sure?",
    yes_cancel: "Yes, cancel",
    yes_stop: "Yes, stop",
    yes_new_cook: "Yes, new cook",
    keep_cooking: "Keep cooking",
    entity_not_found: "Entity not found: {entity}",
    err_define_entity: "Please define an entity (time_remaining sensor)",
    switch_to_temp: "Switch to temperature view",
    switch_to_countdown: "Switch to countdown view",
    hours_short: "h",
    minutes_short: "m",
    expand: "Show details",
    collapse: "Hide details",
    ed_sec_general: "General",
    ed_entity: "Time remaining entity (required)",
    ed_ambient: "Ambient sensor (optional)",
    ed_target_entity: "Target temperature input_number — probe 1 / combined (optional)",
    ed_target_entity_n: "Target temperature input_number — probe {n} (optional)",
    ed_probe_n: "Probe {n} sensor (optional)",
    ed_entry: "Entry ID (optional, for multi-instance)",
    ed_layout: "Probe layout",
    layout_vertical: "Vertical — stacked",
    layout_horizontal: "Horizontal — side by side",
    layout_grid: "Grid — 2 columns",
    ed_collapsible: "Collapsible tiles — tap a probe header to open or close it",
  },
  nl: {
    start_cook: "Kook starten",
    start_probe: "{name} starten",
    cancel_cook: "Kook annuleren",
    stop_cook: "Kook stoppen",
    cancel_probe: "{name} annuleren",
    new_cook_probe: "Nieuwe kook ({name})",
    stop_probe: "{name} stoppen",
    new_cook: "Nieuwe kook",
    combined: "🔗 Gecombineerd",
    individual_toggle: "⚡ Individueel",
    mode_combined: "Gecombineerd",
    mode_individual: "Individueel",
    individual_badge: "Individueel",
    loading_presets: "Presets laden…",
    select_cut: "— Kies stuk —",
    select_doneness: "— Kies gaarheid —",
    target_temp_label: "Doeltemperatuur ({unit})",
    target_label: "Doel ({unit})",
    no_probe_sensors: "Geen probe-sensoren beschikbaar",
    no_probe_sensors_hint: "Controleer of je thermometerprobes zijn aangesloten en zichtbaar zijn in Home Assistant.",
    warming_up_target: "Opwarmen… doel",
    collecting_data: "Gegevens verzamelen ({count}/{needed})",
    readings: "Metingen: {count}/{needed}",
    building_span: "Gegevensbereik opbouwen…",
    ready_at: "klaar om {time}",
    remaining: "resterend",
    estimating: "schatten…",
    tap_for_temp: "tik voor temp",
    tap_for_time: "tik voor tijd",
    done_at: "Klaar ~{eta}",
    eta: "ETA: {eta}",
    rate: "Snelheid: {rate} {unit}/min",
    stalled: "(gestagneerd)",
    ambient: "Omgeving",
    internal: "Kern",
    probe_n: "Probe {n}",
    of_temp: "van {temp}",
    remove_from_heat: "Van het vuur halen",
    remove_from_heat_now: "Nu van het vuur halen!",
    carryover_full: "Nagaren brengt het naar {temp}.",
    pull_temp: "Haaltemperatuur: {temp}.",
    carryover_short: "Nagaren brengt het naar {temp}.",
    pull_temp_short: "Haaltemp: {temp}.",
    stall_detected: "Temperatuurstagnatie gedetecteerd",
    stall_detail: "De getoonde tijd is de laatste stabiele schatting. Deze wordt hervat zodra de temperatuur weer stijgt.",
    stall_short: "Stagnatie — laatste stabiele schatting",
    unreachable_detected: "Doel kan niet worden bereikt",
    unreachable_detail: "De omgevingstemperatuur is onder het doel gezakt. Verhoog de warmte om de bereiding af te ronden.",
    unreachable_short: "Omgeving onder doel — verhoog de warmte",
    target_reached: "Doel bereikt!",
    cook_complete: "Kook voltooid!",
    target_temp_reached: "Doeltemperatuur bereikt.",
    not_started: "Niet gestart",
    are_you_sure: "Weet je het zeker?",
    yes_cancel: "Ja, annuleren",
    yes_stop: "Ja, stoppen",
    yes_new_cook: "Ja, nieuwe kook",
    keep_cooking: "Doorgaan met koken",
    entity_not_found: "Entiteit niet gevonden: {entity}",
    err_define_entity: "Definieer een entiteit (time_remaining-sensor)",
    switch_to_temp: "Naar temperatuurweergave",
    switch_to_countdown: "Naar aftelweergave",
    hours_short: "u",
    minutes_short: "m",
    expand: "Details tonen",
    collapse: "Details verbergen",
    ed_sec_general: "Algemeen",
    ed_entity: "Time remaining-entiteit (verplicht)",
    ed_ambient: "Omgevingssensor (optioneel)",
    ed_target_entity: "Doeltemperatuur-input_number — probe 1 / gecombineerd (optioneel)",
    ed_target_entity_n: "Doeltemperatuur-input_number — probe {n} (optioneel)",
    ed_probe_n: "Probe {n}-sensor (optioneel)",
    ed_entry: "Entry-ID (optioneel, voor meerdere instanties)",
    ed_layout: "Probe-indeling",
    layout_vertical: "Verticaal — gestapeld",
    layout_horizontal: "Horizontaal — naast elkaar",
    layout_grid: "Raster — 2 kolommen",
    ed_collapsible: "Inklapbare tegels — tik op een probe-kop om te openen of te sluiten",
  },
};

// Current UI language — set from hass.language at the start of every render.
// Module-level (not per-instance) is fine: hass.language is a single global
// user preference, so all cards on the page share it.
let _lang = "en";
let _locale = "en";

function _setLang(hass) {
  _locale = hass?.language || "en";
  _lang = _locale.split("-")[0];
}

// Translate `key`, interpolating {placeholder} tokens from `vars`.
// Falls back to English, then to the raw key, so a missing entry is never fatal.
function t(key, vars) {
  const s = (I18N[_lang] && I18N[_lang][key]) ?? I18N.en[key] ?? key;
  return vars ? s.replace(/\{(\w+)\}/g, (_, k) => (vars[k] != null ? vars[k] : `{${k}}`)) : s;
}

// Localised display label for a preset object (category / cut / doneness).
// The English `label` stays canonical — it feeds the backend cook_name and
// ml_predictor's lookup table (see _makeCookName), so it MUST NOT change per
// language.  Display-only translations live in `labels` in cook_presets.json.
function _displayLabel(obj) {
  if (!obj) return "";
  return (obj.labels && obj.labels[_lang]) || obj.label;
}

// ─── Preset data (loaded async from cook_presets.json) ───────────────────────
//
// _presets is:  null  = still loading
//               false = failed to load (card falls back to manual temp entry)
//               object = loaded successfully
//
// To add or edit presets edit  www/probe-ability/cook_presets.json  only.
// Python (ml_predictor.py) reads the same file, so no Python changes needed.

let _presets = null;
let _presetsWaiters = [];

function _loadPresets() {
  if (_presets !== null) return Promise.resolve(_presets);
  return new Promise((resolve) => {
    _presetsWaiters.push(resolve);
    if (_presetsWaiters.length === 1) {
      fetch("/probe_ability/cook_presets.json")
        .then((r) => r.json())
        .then((d) => {
          _presets = d;
          _presetsWaiters.forEach((fn) => fn(d));
          _presetsWaiters = [];
        })
        .catch(() => {
          _presets = false;
          _presetsWaiters.forEach((fn) => fn(false));
          _presetsWaiters = [];
        });
    }
  });
}

// Generate the cook_name string that is sent to the start_cook service and
// stored on the Python predictor.  Must match the formula in ml_predictor.py:
//   f"{cat['label']} {cut['label']} {don['label']}"
// INVARIANT: this uses the canonical English `.label` (NOT _displayLabel) so the
// cook_name is language-independent and keeps matching ml_predictor's lookup
// table.  Never swap these to localised labels.
function _makeCookName(category, cut, doneness) {
  // Degrades gracefully so a typed temperature keeps the meat identity:
  //   category+cut+doneness → "Beef Burger Medium"  (full preset)
  //   category+cut          → "Beef Burger"         (typed temperature: the model
  //                           uses the cut and the doneness nearest the target)
  //   category only         → "Beef"
  //   nothing               → "Custom"
  // ml_predictor.resolve_meat() understands all four forms.
  if (!_presets || !category) return "Custom";
  const catObj = _presets.categories.find((c) => c.id === category);
  if (!catObj) return "Custom";
  const cutObj = cut ? catObj.cuts.find((c) => c.id === cut) : null;
  const donObj = cutObj && doneness ? cutObj.doneness.find((d) => d.id === doneness) : null;
  if (cutObj && donObj) return `${catObj.label} ${cutObj.label} ${donObj.label}`;
  if (cutObj) return `${catObj.label} ${cutObj.label}`;
  return catObj.label;
}

// Render the 3-step hierarchical preset selector for one idle slot.
//   idSuffix  — unique string used as suffix for all element IDs and data-slot
//   slotState — { category, cut, doneness, temp }
//
// Step 1: row of icon-pill buttons (one per category)
// Step 2: cut <select> — appears after a category is chosen
// Step 3: doneness <select> — appears after a cut is chosen (skipped for
//         single-doneness cuts, which are auto-selected)
function _presetSelector(idSuffix, slotState, unit = "C") {
  const selStyle = `width:100%;box-sizing:border-box;padding:10px 12px;
    border:1px solid var(--divider-color);border-radius:8px;font-size:0.95em;
    background:var(--card-background-color);color:var(--primary-text-color);cursor:pointer;`;

  if (!_presets) {
    return `<div style="font-size:0.85em;color:var(--secondary-text-color);padding:8px 0;">
      ${t("loading_presets")}</div>`;
  }

  const { category, cut, doneness } = slotState;

  // Step 1 — category pill buttons
  const catBtns = _presets.categories
    .map((c) => {
      const sel = c.id === category;
      return `<button
        data-action="cat" data-slot="${idSuffix}" data-val="${c.id}"
        style="padding:6px 10px;border-radius:20px;font-size:0.82em;cursor:pointer;
               border:1px solid ${sel ? "var(--primary-color)" : "var(--divider-color)"};
               background:${sel ? "var(--primary-color)" : "var(--card-background-color)"};
               color:${sel ? "var(--text-primary-color)" : "var(--primary-text-color)"};
               font-weight:${sel ? "600" : "400"};">
        ${c.icon} ${_displayLabel(c)}
      </button>`;
    })
    .join("");
  let html = `<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px;">${catBtns}</div>`;

  if (!category) return html;

  // Step 2 — cut dropdown
  const catObj = _presets.categories.find((c) => c.id === category);
  if (!catObj) return html;

  const cutOpts = catObj.cuts
    .map((c) => `<option value="${c.id}"${c.id === cut ? " selected" : ""}>${_displayLabel(c)}</option>`)
    .join("");
  html += `<div style="margin-bottom:8px;">
    <select id="cp-cut-${idSuffix}" style="${selStyle}">
      <option value="">${t("select_cut")}</option>
      ${cutOpts}
    </select>
  </div>`;

  if (!cut) return html;

  // Step 3 — doneness dropdown (omitted for single-doneness cuts)
  const cutObj = catObj.cuts.find((c) => c.id === cut);
  if (!cutObj || cutObj.doneness.length <= 1) return html;

  const donOpts = cutObj.doneness
    .map(
      (d) =>
        `<option value="${d.id}"${d.id === doneness ? " selected" : ""}>${_displayLabel(d)} (${_toDisp(d.temp, unit)}${_unitLabel(unit)})</option>`
    )
    .join("");
  html += `<div style="margin-bottom:8px;">
    <select id="cp-don-${idSuffix}" style="${selStyle}">
      <option value="">${t("select_doneness")}</option>
      ${donOpts}
    </select>
  </div>`;

  return html;
}

// SVG ring constants (r=50, cx=cy=60)
const CIRC = 314.16; // 2π × 50

// Most probes one integration instance can have (internal_sensor … internal_sensor_4).
const MAX_PROBES = 4;

// Card-config key of the target-temp helper for probe index i.
const _targetKey = (i) => (i === 0 ? "target_temp_entity" : `target_temp_entity_${i + 1}`);

// Data-collection phase: readings needed before the first prediction, the
// assumed reading interval, and the data span the predictor waits for.
const NEEDED_READINGS = 10;
const READING_INTERVAL_S = 30;
const REQUIRED_SPAN_S = 600;

// Brand logo — inline SVG so it works without any extra file reference.
// A unique clipPath id avoids collisions when multiple cards are on the same page.
const LOGO_SVG = `<svg width="32" height="32" viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg" style="flex-shrink:0;">
  <circle cx="100" cy="100" r="95" fill="none" stroke="#e8622a" stroke-width="10"/>
  <clipPath id="pa-logo-clip">
    <circle cx="100" cy="100" r="88"/>
  </clipPath>
  <g clip-path="url(#pa-logo-clip)">
    <path d="M5 65 C30 50 50 30 75 40 C100 50 115 80 140 75 C165 70 180 55 195 60" fill="none" stroke="#e8622a" stroke-width="10" stroke-linecap="round"/>
    <path d="M5 100 C25 90 45 75 70 88 C95 101 115 125 140 115 C160 107 178 90 195 98" fill="none" stroke="#f0a882" stroke-width="10" stroke-linecap="round"/>
    <path d="M5 138 C28 132 50 120 72 128 C94 136 115 155 140 148 C162 141 178 128 195 133" fill="none" stroke="#f0a882" stroke-width="10" stroke-linecap="round"/>
  </g>
</svg>`;

// ─── Temperature unit helpers ─────────────────────────────────────────────────

function _cToF(c) { return Math.round(c * 9 / 5 + 32); }
function _fToC(f) { return (f - 32) * 5 / 9; }
function _toDisp(c, unit) { return unit === "F" ? _cToF(c) : c; }
function _fromDisp(v, unit) { return unit === "F" ? _fToC(v) : v; }
function _unitLabel(unit) { return unit === "F" ? "°F" : "°C"; }

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatTime(minutes) {
  if (minutes == null || isNaN(minutes)) return "—";
  if (minutes >= 60) {
    const h = Math.floor(minutes / 60);
    const m = Math.round(minutes % 60);
    return `${h}${t("hours_short")} ${m}${t("minutes_short")}`;
  }
  return `${Math.round(minutes)}${t("minutes_short")}`;
}

function etaFromMinutes(minutes) {
  if (!minutes || isNaN(minutes) || minutes <= 0) return "";
  const d = new Date(Date.now() + minutes * 60 * 1000);
  return d.toLocaleTimeString(_locale, { hour: "2-digit", minute: "2-digit" });
}

function tempInput(id, value, unit = "C") {
  const min = unit === "F" ? 86 : 30;
  const max = unit === "F" ? 392 : 200;
  return `<input id="${id}" type="number" value="${value}" min="${min}" max="${max}" step="${unit === "F" ? 1 : 0.5}"
    style="width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid var(--divider-color);
           border-radius:8px;font-size:1em;background:var(--card-background-color);
           color:var(--primary-text-color);" />`;
}

function modeToggle(current) {
  const btns = ["combined", "individual"].map((m) => {
    const active = current === m;
    return `<button data-mode="${m}"
      style="flex:1;padding:8px;border:1px solid var(--divider-color);border-radius:8px;
             background:${active ? "var(--primary-color)" : "var(--card-background-color)"};
             color:${active ? "var(--text-primary-color)" : "var(--primary-text-color)"};
             font-size:0.85em;cursor:pointer;font-weight:${active ? "600" : "400"};">
      ${m === "combined" ? t("combined") : t("individual_toggle")}
    </button>`;
  });
  return `<div id="cp-mode-toggle" style="display:flex;gap:8px;margin-bottom:16px;">${btns.join("")}</div>`;
}

// ─── Main card ────────────────────────────────────────────────────────────────

class CookPredictorCard extends HTMLElement {
  setConfig(config) {
    if (!config.entity) {
      throw new Error(t("err_define_entity"));
    }
    this._config = config;
    this._hass = null;
    this._probeSensors = config.probe_sensors || [];
    this._ambientSensor = config.ambient_sensor || null;
    // Per-probe target-temp helpers (index 0 = probe 1 / combined mode):
    // target_temp_entity, target_temp_entity_2 … target_temp_entity_4.
    this._targetTempEntities = Array.from({ length: MAX_PROBES }, (_, i) => config[_targetKey(i)] || null);
    // Individual-mode tile arrangement (see _tilesContainer) and whether tiles
    // fold to a summary row (see _probeTile).  Unknown values — including the
    // pre-release "collapsible" — fall back to the defaults: vertical, folding.
    this._probeLayout = ["vertical", "horizontal", "grid"].includes(config.probe_layout)
      ? config.probe_layout
      : "vertical";
    this._collapsible = config.collapsible !== false;
    // Per-slot form state: { category, cut, doneness, temp }
    // Key: "combined" or a probe index.
    // Backed by localStorage so selections survive page navigation.
    try {
      this._idleState = JSON.parse(localStorage.getItem("probe_ability_idle_state") || "{}");
      for (const key of Object.keys(this._idleState)) {
        const s = this._idleState[key];
        // Drop invalid entries or old format (had presetIndex instead of category/cut/doneness)
        if (!s || typeof s.temp !== "number" || isNaN(s.temp) || "presetIndex" in s) {
          delete this._idleState[key];
        }
      }
    } catch (e) {
      this._idleState = {};
    }
    // Migrate old active-preset store (used to hold a numeric index; now holds a string)
    try {
      const ap = JSON.parse(localStorage.getItem("probe_ability_active_presets") || "{}");
      let changed = false;
      for (const k of Object.keys(ap)) {
        if (typeof ap[k] === "number") { delete ap[k]; changed = true; }
      }
      if (changed) localStorage.setItem("probe_ability_active_presets", JSON.stringify(ap));
    } catch (e) {}
    // Tracks whether a stop confirmation prompt is open.
    // While true, hass() skips full re-renders so the prompt stays visible.
    this._confirmPending = false;

    // Start loading presets immediately so data is ready before first render
    _loadPresets().then(() => { if (this._hass) this._render(); });
  }

  set hass(hass) {
    const prev = this._hass;
    this._hass = hass;
    this._saveIdleFormState();

    // Never rebuild the card while the user is interacting with a form control
    // (category/cut/doneness dropdown or the temp input) — a re-render would
    // close an open dropdown or drop focus. This applies even when another probe
    // is running, because the active-individual view still shows idle setup
    // forms for the not-yet-started probes.
    const focused = document.activeElement;
    if (focused && this.contains(focused) &&
        (focused.tagName === "SELECT" || focused.tagName === "INPUT")) {
      return;
    }

    // Follow external changes to a linked target helper into stored idle temps.
    this._applyLinkedTempChanges(prev, hass);

    const entity = this._config?.entity;
    const ns = hass.states[entity];
    const na = ns?.attributes || {};
    const isIdle = !na.active;

    if (isIdle) {
      // During idle the form is driven entirely by local state, not HA state.
      // Skip if nothing that affects the idle view has changed — but a change to
      // a linked target helper must still trigger a re-render so the idle target
      // temp follows it.
      if (prev) {
        const ps = prev.states[entity];
        const pa = ps?.attributes || {};
        if (!pa.active && !na.active && pa.probe_count === na.probe_count &&
            !this._targetHelpersChanged(prev, hass)) {
          return;
        }
      }
    }

    // Skip full re-render while a stop confirmation prompt is open.
    // The prompt is an inline DOM replacement — a re-render would wipe it.
    if (!isIdle && this._confirmPending) return;

    this._render();
  }

  _saveIdleFormState() {
    // Only the manual temp input needs capturing — category/cut/doneness are
    // persisted immediately in the event handlers.
    const unit = this._tempUnit || "C";
    const saveTemp = (key, targetId) => {
      const el = this.querySelector(`#${targetId}`);
      if (!el) return;
      const dispVal = parseFloat(el.value);
      if (isNaN(dispVal)) return;
      const temp = _fromDisp(dispVal, unit);
      this._idleState[key] = { ...(this._idleState[key] || {}), temp };
    };
    saveTemp("combined", "cp-target-combined");
    for (let i = 0; i < MAX_PROBES; i++) {
      saveTemp(i, `cp-target-${i}`);           // individual idle slot
      saveTemp(i, `cp-target-idle-${i}`);      // idle slot inside active-individual view
      saveTemp(`sp-${i}`, `cp-target-sp-${i}`); // single-probe view
    }
    this._persistIdleState();
  }

  // Returns { category, cut, doneness, temp } for a slot. A linked target
  // helper seeds the default temp for a fresh slot (_defaultTemp) and external
  // changes to it are pushed into stored state via _applyLinkedTempChanges — but
  // it does NOT override here, so a chosen preset/manual temp always shows.
  _slotState(key) {
    return this._idleState[key] || { category: null, cut: null, doneness: null, temp: this._defaultTemp(key) };
  }

  // Reflect external changes to a linked target helper (dashboard/automation)
  // into stored idle temps, so the card still follows the input_number without
  // shadowing a locally chosen preset/manual value.
  _applyLinkedTempChanges(prev, hass) {
    if (!this._targetTempEntities || !prev) return;
    let changed = false;
    for (const key of Object.keys(this._idleState)) {
      const entity = this._targetEntityFor(key);
      if (!entity) continue;
      const ns = hass.states[entity];
      if (!ns) continue;
      const ps = prev.states[entity];
      if (ps && ps.state === ns.state) continue;   // unchanged externally
      const v = parseFloat(ns.state);
      if (isNaN(v)) continue;
      this._idleState[key] = { ...this._idleState[key], temp: _fromDisp(v, this._tempUnit || "C") };
      changed = true;
    }
    if (changed) this._persistIdleState();
  }

  // Map a slot key to its probe index (0-based).
  //   "combined" → 0 (probe 1's helper), number i → i,
  //   "sp-2"/"idle-1"/… → trailing digit.
  _probeIndexForKey(key) {
    if (key === "combined") return 0;
    if (typeof key === "number") return key;
    const m = /(\d+)\s*$/.exec(String(key));
    return m ? parseInt(m[1], 10) : 0;
  }

  // The linked input_number for a slot, or null. Probe 1 / combined use
  // target_temp_entity; probes 2 and 3 use target_temp_entity_2 / _3.
  _targetEntityFor(key) {
    const idx = this._probeIndexForKey(key);
    return (this._targetTempEntities && this._targetTempEntities[idx]) || null;
  }

  // Default idle target temperature (internal °C) for a slot. When that slot's
  // target helper (an input_number shared with e.g. a history-graph target
  // line) is linked, its value is the source of truth; otherwise 74 °C.
  _linkedTargetTemp(key) {
    const entity = this._targetEntityFor(key);
    if (!entity || !this._hass) return null;
    const s = this._hass.states[entity];
    const v = s && parseFloat(s.state);
    if (!s || v == null || isNaN(v)) return null;
    return _fromDisp(v, this._tempUnit || "C");
  }

  _defaultTemp(key) {
    const linked = this._linkedTargetTemp(key);
    return linked != null ? linked : 74;
  }

  // True if any configured target helper's state differs between two hass
  // objects — used to force an idle re-render when the input_number changes.
  _targetHelpersChanged(prev, next) {
    for (const entity of this._targetTempEntities || []) {
      if (!entity) continue;
      if (prev.states[entity]?.state !== next.states[entity]?.state) return true;
    }
    return false;
  }

  // Write the chosen target back to that slot's linked helper so the card and
  // any history-graph target line stay in sync. Only input_number is settable.
  // Clamp an internal-°C temp to the linked helper's min/max (which are
  // expressed in the card's display unit). No-op when no helper is linked or
  // its state/attributes are unavailable.
  _clampToLinkedRange(key, tempC) {
    const entity = this._targetEntityFor(key);
    if (!entity || !this._hass) return tempC;
    const cur = this._hass.states[entity];
    if (!cur) return tempC;
    const unit = this._tempUnit || "C";
    const min = parseFloat(cur.attributes?.min);
    const max = parseFloat(cur.attributes?.max);
    let disp = _toDisp(tempC, unit);
    if (!isNaN(min) && disp < min) disp = min;
    if (!isNaN(max) && disp > max) disp = max;
    return _fromDisp(disp, unit);
  }

  _syncTargetTemp(key, tempC) {
    const entity = this._targetEntityFor(key);
    if (!entity || !this._hass) return;
    if (entity.split(".")[0] !== "input_number") return;
    const disp = _toDisp(tempC, this._tempUnit || "C");
    const cur = this._hass.states[entity];
    // Avoid a write→state-change→write feedback loop.
    if (cur && parseFloat(cur.state) === disp) return;
    // Respect the helper's configured min/max — writing outside it just throws
    // an "Invalid value" error. Silently skip rather than spam the user.
    const min = cur && parseFloat(cur.attributes?.min);
    const max = cur && parseFloat(cur.attributes?.max);
    if (min != null && !isNaN(min) && disp < min) return;
    if (max != null && !isNaN(max) && disp > max) return;
    this._hass.callService("input_number", "set_value", {
      entity_id: entity,
      value: disp,
    });
  }

  _persistIdleState() {
    try {
      localStorage.setItem("probe_ability_idle_state", JSON.stringify(this._idleState));
    } catch (e) { /* ignore quota errors */ }
  }

  // Persist the cook name that was active when a cook was started.
  // Key: "combined" or a probe index.
  _saveActivePreset(key, cookName) {
    try {
      const store = JSON.parse(localStorage.getItem("probe_ability_active_presets") || "{}");
      if (cookName && cookName !== "Custom") {
        store[String(key)] = cookName;
      } else {
        delete store[String(key)];
      }
      localStorage.setItem("probe_ability_active_presets", JSON.stringify(store));
    } catch (e) {}
  }

  // Returns the cook name for a running cook slot, or null for custom temp.
  _getActivePresetName(key) {
    try {
      const store = JSON.parse(localStorage.getItem("probe_ability_active_presets") || "{}");
      const name = store[String(key)];
      return typeof name === "string" ? name : null;
    } catch (e) { return null; }
  }

  // Cache probe_count when attrs are available so we can show all probe slots
  // in the idle state even when the entity is unavailable (empty attributes).
  get _cachedProbeCount() {
    return parseInt(localStorage.getItem("probe_ability_probe_count") || "1", 10);
  }

  _cacheProbeCount(count) {
    try { localStorage.setItem("probe_ability_probe_count", String(count)); } catch (e) {}
  }

  // True if the ambient sensor is available (or not configured in card config).
  _ambientOk() {
    if (!this._ambientSensor) return true;
    const s = this._hass && this._hass.states[this._ambientSensor];
    return s && s.state !== "unavailable" && s.state !== "unknown"
           && !isNaN(parseFloat(s.state)) && parseFloat(s.state) !== 0;
  }

  // Returns the indices (0-based) of probes whose sensors are currently
  // available and reporting a numeric value.
  // If probe_sensors is not configured in the card config, all probes are
  // assumed available (backend validation will catch real problems).
  // entityProbeIndex: the integration probe index that probe_sensors[0] maps to.
  // Needed when a card shows a single non-first probe — e.g. a card whose
  // entity is the probe-2 time_remaining sensor has entityProbeIndex=1, so
  // probe_sensors[0] maps to integration probe 1, not probe 0.
  _availableProbeIndices(totalCount, entityProbeIndex = 0) {
    if (!this._probeSensors || !this._probeSensors.length) {
      return Array.from({ length: totalCount }, (_, i) => i);
    }
    return this._probeSensors
      .slice(0, totalCount)
      .map((id, i) => ({ id, idx: i + entityProbeIndex }))
      .filter(({ id }) => {
        const s = this._hass && this._hass.states[id];
        return s && s.state !== "unavailable" && s.state !== "unknown"
               && !isNaN(parseFloat(s.state)) && parseFloat(s.state) !== 0;
      })
      .map(({ idx }) => idx);
  }

  // Integration probe index (0-based) this card's entity represents.
  // Prefer the live probe_index attribute; fall back to parsing the
  // entity_id suffix ("..._time_remaining_probe_2" → 1) so the card still
  // targets the correct probe while the entity is briefly unavailable
  // (HA startup, integration reload) and its attributes are stripped.
  _entityProbeIndex(attrs) {
    if (attrs && attrs.probe_index != null) return attrs.probe_index;
    const m = /_probe_(\d+)$/.exec(this._config.entity || "");
    if (m) {
      const n = parseInt(m[1], 10);
      if (n >= 1) return n - 1;
    }
    return 0;
  }

  // Display name for probe i (0-based): the name configured in the
  // integration, else the localised "Probe N".
  _probeName(i) {
    const n = this._probeNames && this._probeNames[i];
    return typeof n === "string" && n.trim() ? n.trim() : t("probe_n", { n: i + 1 });
  }

  // Persistent display mode for the SVG timer (countdown vs temp-up)
  get _timerMode() {
    return localStorage.getItem("probe_ability_timer_mode") || "countdown";
  }

  // Persistent probe usage mode selection (for idle state UI)
  get _probeMode() {
    return localStorage.getItem("probe_ability_probe_mode") || "combined";
  }

  _setProbeMode(mode) {
    localStorage.setItem("probe_ability_probe_mode", mode);
    this._render();
  }

  _render() {
    if (!this._hass) return;
    _setLang(this._hass);
    // A full rebuild discards any open stop-confirmation prompt.
    this._confirmPending = false;
    // Card-size hint; only the individual-mode views set it (see getCardSize).
    this._lastTileCount = null;

    const entity = this._config.entity;
    const state = this._hass.states[entity];

    if (!state) {
      this.innerHTML = `
        <ha-card header="Probe-ability">
          <div style="padding:16px;color:var(--error-color);">
            ${t("entity_not_found", { entity })}
          </div>
        </ha-card>`;
      return;
    }

    const attrs = state.attributes;
    const probeMode = attrs.probe_mode || this._probeMode;
    const phase = attrs.phase || "idle";
    const isActive = attrs.active || false;
    if (attrs.temp_unit) {
      this._tempUnit = attrs.temp_unit;
      try { localStorage.setItem("probe_ability_temp_unit", attrs.temp_unit); } catch (e) {}
    } else {
      this._tempUnit = this._tempUnit
        || localStorage.getItem("probe_ability_temp_unit")
        || "C";
    }

    // Keep probe_count in sync while we have live attributes
    if (attrs.probe_count) this._cacheProbeCount(attrs.probe_count);

    // Probe display names configured in the integration ("Green" …); cached
    // per entity so the idle view keeps them while attributes are missing.
    const namesKey = `probe_ability_probe_names:${entity}`;
    if (Array.isArray(attrs.probe_names)) {
      this._probeNames = attrs.probe_names;
      try { localStorage.setItem(namesKey, JSON.stringify(attrs.probe_names)); } catch (e) {}
    } else if (!this._probeNames) {
      try { this._probeNames = JSON.parse(localStorage.getItem(namesKey) || "[]"); }
      catch (e) { this._probeNames = []; }
    }

    if (!isActive) {
      this._renderIdle(attrs);
    } else if (probeMode === "individual") {
      // Individual mode always uses the per-probe view — each probe manages
      // its own collecting / active / done state independently.
      this._renderActiveIndividual(state, attrs);
    } else if (phase === "collecting") {
      this._renderCollecting(attrs);
    } else if (phase === "done") {
      this._renderDone(attrs);
    } else {
      this._renderActive(state, attrs);
    }
  }

  // ── Idle ──────────────────────────────────────────────────────────────

  _renderIdle(attrs) {
    const probeMode = this._probeMode;
    // Use probe_sensors.length as the authoritative total when configured —
    // attrs.probe_count is absent while idle (sensor unavailable = no attrs),
    // and _cachedProbeCount defaults to 1 which causes the wrong branch.
    const probeCount = this._probeSensors.length || attrs.probe_count || this._cachedProbeCount;
    // probe_index tells us which integration probe this card's entity represents.
    // probe_sensors[0] maps to that probe, probe_sensors[1] to the next, etc.
    const entityProbeIndex = this._entityProbeIndex(attrs);
    const available = this._availableProbeIndices(probeCount, entityProbeIndex);

    // No sensors at all, or ambient unavailable → inform the user, no start button
    if (!this._ambientOk() || available.length === 0) {
      this._renderNoSensors();
      return;
    }

    // Only one probe available → single-probe form, no mode toggle
    if (available.length === 1) {
      this._renderIdleSingleProbe(available[0]);
      return;
    }

    // Two or more probes available → full UI with mode toggle
    let probeContent = "";
    if (probeMode === "individual") {
      probeContent = this._idleIndividualSlots(available);
    } else {
      probeContent = this._idleCombinedForm();
    }

    this.innerHTML = `
      <ha-card>
        <div style="padding:20px;">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:20px;">
            ${LOGO_SVG}
            <span style="font-size:1.3em;font-weight:500;">Probe-ability</span>
          </div>

          ${modeToggle(probeMode)}
          ${probeContent}
        </div>
      </ha-card>`;

    // Mode toggle buttons
    this.querySelectorAll("#cp-mode-toggle button").forEach((btn) => {
      btn.addEventListener("click", () => this._setProbeMode(btn.dataset.mode));
    });

    // Wire up preset dropdowns and start buttons
    if (probeMode === "individual") {
      for (const i of available) {
        this._wireIdleProbeSlot(i);
      }
      this._wireTileToggles(available.length);
    } else {
      this._wireIdleCombined();
    }
  }

  _renderNoSensors() {
    this.innerHTML = `
      <ha-card>
        <div style="padding:20px;">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:20px;">
            ${LOGO_SVG}
            <span style="font-size:1.3em;font-weight:500;">Probe-ability</span>
          </div>
          <div style="text-align:center;padding:20px 0;color:var(--warning-color);">
            <ha-icon icon="mdi:alert-outline" style="--mdc-icon-size:40px;"></ha-icon>
            <div style="font-size:1em;font-weight:500;margin-top:10px;">${t("no_probe_sensors")}</div>
            <div style="font-size:0.85em;color:var(--secondary-text-color);margin-top:6px;">
              ${t("no_probe_sensors_hint")}
            </div>
          </div>
        </div>
      </ha-card>`;
  }

  _renderIdleSingleProbe(probeIndex) {
    const slotKey = `sp-${probeIndex}`;
    const state = this._slotState(slotKey);
    const unit = this._tempUnit || "C";
    this.innerHTML = `
      <ha-card>
        <div style="padding:20px;">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:20px;">
            ${LOGO_SVG}
            <span style="font-size:1.3em;font-weight:500;">Probe-ability</span>
          </div>
          <div>
            <div id="cp-form-${slotKey}">
              ${_presetSelector(slotKey, state, unit)}
              <div style="margin-top:4px;">
                <label style="display:block;font-size:0.85em;color:var(--secondary-text-color);margin-bottom:4px;">${t("target_temp_label", { unit: _unitLabel(unit) })}</label>
                ${tempInput(`cp-target-${slotKey}`, _toDisp(state.temp, unit), unit)}
              </div>
            </div>
            <button id="cp-start-single"
              style="width:100%;padding:12px;margin-top:16px;background:var(--primary-color);
                     color:var(--text-primary-color);border:none;border-radius:8px;
                     font-size:1em;font-weight:500;cursor:pointer;">
              ${t("start_cook")}
            </button>
          </div>
        </div>
      </ha-card>`;

    this._wireIdleSlot(slotKey, slotKey, { startId: "cp-start-single", isIndividual: true, probeIndex });
  }

  _idleCombinedForm() {
    const state = this._slotState("combined");
    const unit = this._tempUnit || "C";
    return `
      <div>
        <div id="cp-form-combined">
          ${_presetSelector("combined", state, unit)}
          <div style="margin-top:4px;">
            <label style="display:block;font-size:0.85em;color:var(--secondary-text-color);margin-bottom:4px;">${t("target_temp_label", { unit: _unitLabel(unit) })}</label>
            ${tempInput("cp-target-combined", _toDisp(state.temp, unit), unit)}
          </div>
        </div>
        <button id="cp-start-combined"
          style="width:100%;padding:12px;margin-top:16px;background:var(--primary-color);
                 color:var(--text-primary-color);border:none;border-radius:8px;
                 font-size:1em;font-weight:500;cursor:pointer;">
          ${t("start_cook")}
        </button>
      </div>`;
  }

  _idleIndividualSlots(available) {
    const unit = this._tempUnit || "C";
    const shown = available.length;
    let html = "";
    let open = 0;
    for (const i of available) {
      const state = this._slotState(i);
      const expanded = this._isExpanded(i, shown);
      if (expanded) open++;
      const detail = `
          <div id="cp-form-${i}" style="margin-top:6px;">
            ${_presetSelector(i, state, unit)}
            <div style="margin-top:4px;">
              <label style="display:block;font-size:0.8em;color:var(--secondary-text-color);margin-bottom:4px;">${t("target_label", { unit: _unitLabel(unit) })}</label>
              ${tempInput(`cp-target-${i}`, _toDisp(state.temp, unit), unit)}
            </div>
          </div>
          <button id="cp-start-${i}"
            style="width:100%;padding:10px;margin-top:10px;background:var(--primary-color);
                   color:var(--text-primary-color);border:none;border-radius:8px;
                   font-size:0.9em;font-weight:500;cursor:pointer;">
            ${t("start_probe", { name: this._probeName(i) })}
          </button>`;
      html += this._probeTile(i, {
        expanded,
        titleColor: "var(--primary-color)",
        subtitle: this._idleCookName(i),
        summary: this._idleSummary(state),
        detail,
      });
    }
    this._lastTileCount = shown;
    this._lastOpenCount = open;
    return this._tilesContainer(html, shown);
  }

  // ── Probe tiles ───────────────────────────────────────────────────────
  //
  // Both individual-mode views (idle, and active with mixed probe states)
  // render one tile per probe.  With probe_layout "collapsible" (default)
  // the tile header doubles as a summary row that toggles the detail, so a
  // 4-probe card is a few short rows plus whatever the user opened.  With
  // "grid" every tile is open and tiles flow into 2 columns on wide cards.

  // Preset chosen for an idle slot, or "" for a custom temperature.
  _idleCookName(i) {
    const s = this._slotState(i);
    const name = _makeCookName(s.category, s.cut, s.doneness);
    return name === "Custom" ? "" : name;
  }

  _idleSummary(slotState) {
    const unit = this._tempUnit || "C";
    return {
      primary: `${_toDisp(slotState.temp, unit)}${_unitLabel(unit)}`,
      secondary: t("not_started"),
    };
  }

  // Collapsed-row figures for one probe: a bold primary value, a small
  // secondary line and a thin progress bar, so the key facts (and any alert)
  // stay visible without opening the tile.  pd is a probeData entry from
  // _renderActiveIndividual; phaseColor its phase colour.
  _probeSummary(i, pd, shouldPull, phaseColor) {
    if (!pd.active) return this._idleSummary(this._slotState(i));
    const unit = this._tempUnit || "C";
    const fmt = (v) => `${_toDisp(v, unit)}${_unitLabel(unit)}`;
    const cur = pd.currentTemp != null ? fmt(pd.currentTemp) : "—";

    if (pd.phase === "collecting") {
      // Same two phases as the open tile: readings, then the data span.
      const count = pd.readingsCount || 0;
      const color = "var(--warning-color)";
      if (count < NEEDED_READINGS) {
        return {
          primary: cur,
          secondary: t("readings", { count, needed: NEEDED_READINGS }),
          progress: { pct: (count / NEEDED_READINGS) * 100, color },
        };
      }
      const elapsedS = count * READING_INTERVAL_S;
      const spanRemainS = Math.max(0, REQUIRED_SPAN_S - elapsedS);
      const readyAt = spanRemainS > 0 ? etaFromMinutes(spanRemainS / 60) : "";
      return {
        primary: cur,
        secondary: readyAt ? t("ready_at", { time: readyAt }) : t("building_span"),
        progress: { pct: Math.min((elapsedS / REQUIRED_SPAN_S) * 100, 100), color },
      };
    }
    if (pd.phase === "done") {
      return {
        primary: t("target_reached"),
        primaryColor: "var(--success-color)",
        secondary: pd.currentTemp != null ? cur : "",
        progress: { pct: 100, color: "var(--success-color)" },
      };
    }

    // Prediction phases: temperature progress (current → target), coloured
    // like the open tile's bar.
    const tgt = pd.targetTemp != null ? fmt(pd.targetTemp) : "—";
    const primary = pd.timeRemaining ? formatTime(pd.timeRemaining) : "—";
    const progress = (pd.currentTemp != null && pd.targetTemp > 0)
      ? { pct: Math.min((pd.currentTemp / pd.targetTemp) * 100, 100),
          color: shouldPull ? "var(--warning-color)" : phaseColor }
      : null;
    if (shouldPull) {
      return {
        primary,
        primaryColor: "var(--warning-color)",
        secondary: t("remove_from_heat_now"),
        secondaryColor: "var(--warning-color)",
        progress,
      };
    }
    if (pd.phase === "unreachable") {
      return { primary, secondary: t("unreachable_short"), secondaryColor: "var(--error-color)", progress };
    }
    if (pd.phase === "stall") {
      return { primary, secondary: `${cur} → ${tgt} ${t("stalled")}`, secondaryColor: "var(--error-color)", progress };
    }
    return { primary, secondary: `${cur} → ${tgt}`, progress };
  }

  // One probe tile.
  //   opts.expanded   — render the detail block?
  //   opts.titleColor — colour of "Probe N" (and its icon)
  //   opts.icon       — mdi icon after the name, "" for none
  //   opts.subtitle   — preset name shown after the name while collapsed
  //   opts.rightHtml  — header right side while open (target, confidence…)
  //   opts.summary    — { primary, secondary, primaryColor?, secondaryColor?, progress? } while
  //                     collapsed; progress = { pct, color } draws a thin bar under the row
  //   opts.alert      — warning-coloured border (pull-from-heat)
  //   opts.detail     — HTML of the detail block (content + action button)
  _probeTile(i, opts) {
    const collapsible = this._collapsible;
    const expanded = !!opts.expanded;
    const icon = opts.icon
      ? `<ha-icon icon="${opts.icon}" style="--mdc-icon-size:16px;vertical-align:middle;margin-left:4px;"></ha-icon>`
      : "";
    const subtitle = !expanded && opts.subtitle
      ? `<span style="font-weight:400;color:var(--secondary-text-color);"> · ${opts.subtitle}</span>`
      : "";
    const sm = opts.summary || {};
    const right = expanded
      ? (opts.rightHtml || "")
      : `<div style="text-align:right;line-height:1.3;">
              <div style="font-size:0.95em;font-weight:600;color:${sm.primaryColor || "var(--primary-text-color)"};">${sm.primary ?? ""}</div>
              ${sm.secondary
                ? `<div style="font-size:0.72em;color:${sm.secondaryColor || "var(--secondary-text-color)"};">${sm.secondary}</div>`
                : ""}
            </div>`;
    const chevron = collapsible
      ? `<ha-icon icon="mdi:chevron-${expanded ? "up" : "down"}"
             style="--mdc-icon-size:20px;color:var(--secondary-text-color);flex-shrink:0;margin:-2px -4px 0 0;"></ha-icon>`
      : "";
    const toggle = collapsible
      ? ` data-toggle-probe="${i}" role="button" tabindex="0" title="${expanded ? t("collapse") : t("expand")}"`
      : "";
    // Open tile: the short title keeps its width and the right block (which
    // may hold a long preset name) wraps — or, in a narrow tile of a
    // multi-column layout, drops onto its own line under the title (the
    // header is allowed to wrap).  Collapsed row: single line — the right
    // block keeps its width and the title (name · preset) is ellipsised.
    const titleStyle = expanded
      ? "flex-shrink:0;white-space:nowrap;"
      : "min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;line-height:1.5;";
    const rightStyle = expanded ? "min-width:0;margin-left:auto;" : "flex-shrink:0;";
    // Collapsed headers get no inline flex-wrap so the container-query rule in
    // _tilesContainer (wrap inside narrow tiles) can apply.
    const headerWrap = expanded ? "flex-wrap:wrap;" : "";
    const bar = !expanded && sm.progress
      ? `<div style="background:var(--divider-color);border-radius:3px;height:4px;overflow:hidden;margin-top:8px;">
              <div style="background:${sm.progress.color};height:100%;width:${sm.progress.pct.toFixed(1)}%;
                          border-radius:3px;transition:width 1s ease;"></div>
            </div>`
      : "";
    return `
        <div class="pa-tile" style="border:1px solid ${opts.alert ? "var(--warning-color)" : "var(--divider-color)"};border-radius:10px;
                    padding:12px;container-type:inline-size;${this._probeLayout === "vertical" ? "margin-bottom:10px;" : ""}">
          <div${toggle} class="pa-head ${expanded ? "pa-open" : "pa-collapsed"}"
               style="display:flex;${headerWrap}justify-content:space-between;align-items:flex-start;gap:8px;
                      margin-bottom:${expanded ? 4 : 0}px;${collapsible ? "cursor:pointer;user-select:none;" : ""}">
            <div class="pa-title" style="${titleStyle}font-size:0.9em;font-weight:600;color:${opts.titleColor};">
              ${this._probeName(i)}${icon}${subtitle}
            </div>
            <div class="pa-right" style="display:flex;align-items:flex-start;gap:6px;${rightStyle}">
              ${right}${chevron}
            </div>
          </div>
          ${bar}
          ${expanded ? opts.detail : ""}
        </div>`;
  }

  // Wraps the `count` probe tiles according to probe_layout:
  //   vertical   — a plain stack (tiles carry their own bottom margin);
  //   grid       — 2 columns: each track is at least half the width (never
  //                more than 2 columns, however wide the card) and at least
  //                150 px (a very narrow card falls back to one column);
  //   horizontal — all tiles in one row when each can be ≥150 px wide,
  //                otherwise as many per row as fit.  Two probes sit side by
  //                side on any card from ~350 px; four need ~660 px.
  //
  // A collapsed row normally keeps to one line (name · preset | figures), but a
  // narrow tile in a multi-column layout has no room for both, so inside tiles
  // under ~210 px of content width the figures drop to a second line.  The
  // tile is a container-query container; browsers without container queries
  // just keep the single squeezed line.
  _tilesContainer(html, count) {
    const css = `<style>
      @container (max-width: 210px) {
        .pa-head.pa-collapsed { flex-wrap: wrap; }
        .pa-head.pa-collapsed > .pa-title { flex-basis: 100%; }
        .pa-head.pa-collapsed > .pa-right { margin-left: auto; }
      }
    </style>`;
    if (this._probeLayout === "vertical") return css + html;
    const n = Math.max(1, count || 1);
    const share = this._probeLayout === "grid"
      ? "calc(50% - 5px)"
      : `calc((100% - ${(n - 1) * 10}px) / ${n})`;
    return `${css}<div style="display:grid;
                        grid-template-columns:repeat(auto-fit,minmax(max(150px,${share}),1fr));
                        gap:10px;align-items:start;margin-bottom:10px;">${html}</div>`;
  }

  // Per-card map probeIndex → expanded, keyed by the card's entity so several
  // instances on one page don't share state.  Untouched tiles default to open
  // when at most two probes are shown (the card looks as it always did) and to
  // collapsed once a third probe would make it scroll.
  _expandedMap() {
    try {
      const all = JSON.parse(localStorage.getItem("probe_ability_expanded") || "{}");
      return all[this._config.entity] || {};
    } catch (e) { return {}; }
  }

  _isExpanded(i, shownCount) {
    if (!this._collapsible) return true;
    const v = this._expandedMap()[i];
    return typeof v === "boolean" ? v : shownCount <= 2;
  }

  _toggleExpanded(i, shownCount) {
    const next = !this._isExpanded(i, shownCount);
    try {
      const all = JSON.parse(localStorage.getItem("probe_ability_expanded") || "{}");
      all[this._config.entity] = { ...(all[this._config.entity] || {}), [i]: next };
      localStorage.setItem("probe_ability_expanded", JSON.stringify(all));
    } catch (e) { /* ignore quota errors */ }
    this._render();
  }

  _wireTileToggles(shownCount) {
    this.querySelectorAll("[data-toggle-probe]").forEach((el) => {
      const i = parseInt(el.dataset.toggleProbe, 10);
      el.addEventListener("click", () => this._toggleExpanded(i, shownCount));
      el.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          this._toggleExpanded(i, shownCount);
        }
      });
    });
  }

  // Rebuild only the preset selector + temp label inside one form wrapper div,
  // then re-wire its event handlers.  Much cheaper than a full card re-render
  // and avoids scroll jumps / losing focus on sibling elements.
  _refreshForm(idSuffix, stateKey, opts) {
    const container = this.querySelector(`#cp-form-${idSuffix}`);
    if (!container) { this._render(); return; }
    const state = this._slotState(stateKey);
    const unit = this._tempUnit || "C";
    container.innerHTML = `
      ${_presetSelector(idSuffix, state, unit)}
      <div style="margin-top:4px;">
        <label style="display:block;font-size:0.85em;color:var(--secondary-text-color);margin-bottom:4px;">
          ${t("target_temp_label", { unit: _unitLabel(unit) })}
        </label>
        ${tempInput(`cp-target-${idSuffix}`, _toDisp(state.temp, unit), unit)}
      </div>`;
    this._wireIdleSlot(stateKey, idSuffix, opts);
  }

  _wireIdleCombined() {
    this._wireIdleSlot("combined", "combined", { startId: "cp-start-combined" });
  }

  _wireIdleProbeSlot(i) {
    this._wireIdleSlot(i, i, { startId: `cp-start-${i}`, isIndividual: true, probeIndex: i });
  }

  // Shared event-wiring for any idle slot (combined, individual, single-probe).
  //   stateKey  — key in this._idleState  (e.g. "combined", 0, "sp-0")
  //   idSuffix  — suffix used in element IDs and data-slot attrs
  //   opts.startId     — id of the start button
  //   opts.isIndividual — if true, calls start_cook with probe_mode:"individual"
  //   opts.probeIndex  — probe index for individual mode
  _wireIdleSlot(stateKey, idSuffix, opts = {}) {
    const getS = () => this._slotState(stateKey);
    const upd = (patch) => {
      this._idleState[stateKey] = { ...getS(), ...patch };
      this._persistIdleState();
    };

    // Category pill buttons — use targeted form refresh to avoid scroll jumps
    this.querySelectorAll(`button[data-action="cat"][data-slot="${idSuffix}"]`).forEach((btn) => {
      btn.addEventListener("click", () => {
        upd({ category: btn.dataset.val, cut: null, doneness: null, temp: this._defaultTemp(stateKey) });
        this._refreshForm(idSuffix, stateKey, opts);
      });
    });

    // Cut dropdown — targeted refresh to show/hide doneness select
    const cutEl = this.querySelector(`#cp-cut-${idSuffix}`);
    if (cutEl) {
      cutEl.addEventListener("change", () => {
        if (!_presets) return;
        const s = getS();
        const catObj = _presets.categories.find((c) => c.id === s.category);
        const cutObj = catObj?.cuts.find((c) => c.id === cutEl.value);
        if (cutObj && cutObj.doneness.length === 1) {
          // Single-doneness cut — auto-select it immediately
          const t = cutObj.doneness[0].temp;
          upd({ cut: cutEl.value, doneness: cutObj.doneness[0].id, temp: t });
          this._syncTargetTemp(stateKey, t);
        } else {
          upd({ cut: cutEl.value, doneness: null });
        }
        this._refreshForm(idSuffix, stateKey, opts);
      });
    }

    // Doneness dropdown
    const targetEl = this.querySelector(`#cp-target-${idSuffix}`);
    const donEl = this.querySelector(`#cp-don-${idSuffix}`);
    const unit = this._tempUnit || "C";
    if (donEl) {
      donEl.addEventListener("change", () => {
        if (!_presets) return;
        const s = getS();
        const catObj = _presets.categories.find((c) => c.id === s.category);
        const cutObj = catObj?.cuts.find((c) => c.id === s.cut);
        const donObj = cutObj?.doneness.find((d) => d.id === donEl.value);
        const temp = donObj?.temp ?? s.temp;  // always °C
        upd({ doneness: donEl.value, temp });
        if (targetEl) targetEl.value = _toDisp(temp, unit);
        this._syncTargetTemp(stateKey, temp);
      });
    }

    // Manual temp input — store in °C internally.
    // Update local state on every keystroke, but only write the linked helper
    // on `change` (blur/Enter) so partial values ("5" while typing "55") aren't
    // pushed — they'd fail an input_number min/max and spam error toasts.
    if (targetEl) {
      targetEl.addEventListener("input", (e) => {
        const dispVal = parseFloat(e.target.value);
        if (!isNaN(dispVal)) upd({ temp: _fromDisp(dispVal, unit) });
      });
      targetEl.addEventListener("change", (e) => {
        const dispVal = parseFloat(e.target.value);
        if (!isNaN(dispVal)) {
          // Clamp to the linked helper's range so the card and the
          // input_number can't diverge, and reflect the clamp in the field.
          const temp = this._clampToLinkedRange(stateKey, _fromDisp(dispVal, unit));
          upd({ temp });
          e.target.value = _toDisp(temp, unit);
          this._syncTargetTemp(stateKey, temp);
        }
      });
    }

    // Start button.  _refreshForm re-runs this wiring after every category /
    // cut change while the button itself survives, so guard against stacking
    // a second click handler (which would send duplicate start_cook calls).
    const startBtn = opts.startId ? this.querySelector(`#${opts.startId}`) : null;
    if (startBtn && !startBtn.dataset.wired) {
      startBtn.dataset.wired = "1";
      startBtn.addEventListener("click", () => {
        const s = getS();
        const cookName = _makeCookName(s.category, s.cut, s.doneness);
        // Save/read the active-cook label under the probe index when one is
        // given (single-probe & individual), so the active view — which reads
        // by probe index — finds it.  Combined has no probeIndex → "combined".
        const presetKey = opts.probeIndex != null ? opts.probeIndex : stateKey;
        this._saveActivePreset(presetKey, cookName);
        this._syncTargetTemp(stateKey, s.temp);
        if (opts.isIndividual) {
          this._callStart({
            target_temp: s.temp,
            probe_mode: "individual",
            probe_index: opts.probeIndex,
            cook_name: cookName,
          });
        } else {
          this._callStart({ target_temp: s.temp, probe_mode: "combined", cook_name: cookName });
        }
      });
    }
  }

  // ── Collecting ────────────────────────────────────────────────────────

  _renderCollecting(attrs) {
    const count = attrs.readings_count || 0;
    const needed = 10;
    const pct = Math.min((count / needed) * 100, 100);
    const displayCount = Math.min(count, needed);
    const msg = attrs.message || t("collecting_data", { count: displayCount, needed });
    const probeMode = attrs.probe_mode || "combined";
    const probeActive = attrs.probe_active || [true];

    this.innerHTML = `
      <ha-card>
        <div style="padding:20px;">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;">
            ${LOGO_SVG}
            <span style="font-size:1.3em;font-weight:500;">Probe-ability</span>
            <span style="margin-left:auto;font-size:0.8em;color:var(--secondary-text-color);
                         text-transform:capitalize;background:var(--divider-color);
                         padding:2px 8px;border-radius:10px;">${t(`mode_${probeMode}`)}</span>
          </div>

          <div style="text-align:center;padding:16px 0;">
            <ha-icon icon="mdi:timer-sand" style="color:var(--secondary-text-color);--mdc-icon-size:40px;"></ha-icon>
            <div style="font-size:1em;color:var(--secondary-text-color);margin:10px 0 4px;">
              ${t("warming_up_target")} <strong>${attrs.target_temp != null ? `${_toDisp(attrs.target_temp, this._tempUnit || "C")}${_unitLabel(this._tempUnit || "C")}` : "—"}</strong>
            </div>
            <div style="font-size:0.85em;color:var(--secondary-text-color);margin-bottom:8px;">${msg}</div>
            <div style="background:var(--divider-color);border-radius:4px;height:6px;overflow:hidden;">
              <div style="background:var(--warning-color);height:100%;width:${pct}%;border-radius:4px;transition:width 0.5s;"></div>
            </div>
          </div>

          ${this._renderTempsRow(attrs)}

          <button id="cp-stop"
            style="width:100%;padding:10px;background:none;color:var(--error-color);
                   border:1px solid var(--error-color);border-radius:8px;
                   font-size:0.9em;cursor:pointer;margin-top:16px;">
            ${t("cancel_cook")}
          </button>
        </div>
      </ha-card>`;

    this._addStopConfirm(this.querySelector("#cp-stop"), () => this._callStop(), t("yes_cancel"));
  }

  // ── Active ────────────────────────────────────────────────────────────

  _renderActive(state, attrs) {
    const probeMode = attrs.probe_mode || "combined";

    if (probeMode === "individual") {
      this._renderActiveIndividual(state, attrs);
    } else {
      this._renderActiveCombined(state, attrs);
    }
  }

  _renderActiveCombined(state, attrs) {
    const _tr = parseFloat(state.state);
    // Guard: sensor returns "unknown" when the predictor has no estimate yet
    // (rate ≈ 0, no cached value).  Treat that as null so we show "—" rather
    // than clamping to 0 and displaying a full ring with "0m remaining".
    const timeRemaining = isNaN(_tr) || _tr < 0 ? null : _tr;
    const phase = attrs.phase || "heating";
    const confidence = attrs.confidence || "low";
    const phaseColor = { heating: "var(--warning-color)", stall: "var(--error-color)", finishing: "var(--success-color)", unreachable: "var(--error-color)" }[phase] || "var(--primary-color)";
    const phaseIcon = { heating: "mdi:fire", stall: "mdi:pause-circle-outline", finishing: "mdi:flag-checkered", unreachable: "mdi:fire-alert" }[phase] || "mdi:fire";
    const confDots = { low: "●○○", medium: "●●○", high: "●●●" }[confidence] || "";
    const modelBadge = attrs.prediction_model === "ml"
      ? `<span style="font-size:0.7em;background:rgba(76,175,80,0.15);color:#4caf50;border-radius:3px;padding:1px 4px;margin-left:5px;vertical-align:middle;">ML</span>`
      : attrs.prediction_model === "physics"
      ? `<span style="font-size:0.7em;color:var(--secondary-text-color);opacity:0.5;margin-left:5px;vertical-align:middle;">PHY</span>`
      : "";

    // ETA: now + time remaining (the estimated_completion sensor carries the same value)
    const etaDisplay = timeRemaining != null ? etaFromMinutes(timeRemaining) : "";

    // SVG ring values
    const timerMode = this._timerMode;
    let progress = 0;
    let centerPrimary = "—";
    let centerSecondary = "";

    const _unit = this._tempUnit || "C";
    if (timerMode === "tempup") {
      const cur = attrs.current_temp;
      const tgt = attrs.target_temp;
      progress = (cur != null && tgt > 0) ? Math.min(cur / tgt, 1) : 0;
      centerPrimary = cur != null ? `${_toDisp(cur, _unit)}${_unitLabel(_unit)}` : "—";
      centerSecondary = tgt ? t("of_temp", { temp: `${_toDisp(tgt, _unit)}${_unitLabel(_unit)}` }) : "";
    } else {
      // countdown: ring fills as time elapses
      if (timeRemaining != null) {
        const elapsed = (attrs.readings_count || 0) * 0.5; // each reading ≈ 30 s
        const total = timeRemaining + elapsed;
        progress = total > 0 ? Math.max(0, Math.min(elapsed / total, 1)) : 0;
        centerPrimary = formatTime(timeRemaining);
        centerSecondary = t("remaining");
      } else {
        // No estimate available yet (rate too low / no cached value)
        progress = 0;
        centerPrimary = "—";
        centerSecondary = t("estimating");
      }
    }

    // Pull-from-heat: alert when the COLDEST probe ≥ pull point AND close to
    // done (≤ 10 min remaining on the combined/slowest-probe timer).
    //
    // In combined mode attrs.current_temp is always probe 1 (the primary),
    // but the time remaining is driven by the slowest probe.  Using only
    // probe 1's temp causes false alerts when probe 1 is almost done but
    // the other probes are still 10°C away.  We take the minimum across all
    // active probes so the warning only fires when every probe is near done.
    const pullTemp = attrs.pull_temp ?? null;
    const probeTemps = Array.from({ length: MAX_PROBES }, (_, i) =>
      attrs[i === 0 ? "current_temp" : `current_temp_${i + 1}`]
    ).filter(v => v != null);
    const minProbeTemp = probeTemps.length ? Math.min(...probeTemps) : null;
    const shouldPull = pullTemp != null && minProbeTemp != null
      && minProbeTemp >= pullTemp && phase !== "done"
      && (timeRemaining == null || timeRemaining <= 10);

    // Ring colour shifts to warning orange when it's time to pull
    const ringColor = shouldPull ? "var(--warning-color)" : phaseColor;

    const offset = (CIRC * (1 - progress)).toFixed(2);
    const timerIcon = timerMode === "countdown" ? "⏱" : "🌡";
    const nextMode = timerMode === "countdown" ? "tempup" : "countdown";
    const nextLabel = timerMode === "countdown" ? t("switch_to_temp") : t("switch_to_countdown");
    const combinedPresetName = this._getActivePresetName("combined");

    this.innerHTML = `
      <ha-card>
        <div style="padding:20px;">

          <!-- Header: icon+title on left, target+confidence on right (mirrors individual tiles) -->
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
            <div style="display:flex;align-items:center;gap:10px;">
              <ha-icon icon="${shouldPull ? "mdi:fire-off" : phaseIcon}"
                style="color:${shouldPull ? "var(--warning-color)" : phaseColor};--mdc-icon-size:26px;"></ha-icon>
              <div>
                <div style="font-size:1.1em;font-weight:500;">Probe-ability</div>
                ${shouldPull
                  ? `<div style="font-size:0.78em;color:var(--warning-color);font-weight:600;">
                       ${t("remove_from_heat")}
                     </div>`
                  : combinedPresetName
                    ? `<div style="font-size:0.78em;color:var(--secondary-text-color);">
                         ${combinedPresetName}
                       </div>`
                    : ""}
              </div>
            </div>
            <div style="text-align:right;font-size:0.8em;color:var(--secondary-text-color);line-height:1.6;">
              <div>${attrs.target_temp != null ? `${_toDisp(attrs.target_temp, _unit)}${_unitLabel(_unit)}` : "?"}</div>
              ${!shouldPull && confDots
                ? `<div style="letter-spacing:2px;">${confDots}${modelBadge}</div>`
                : ""}
            </div>
          </div>

          <!-- SVG circular timer — tap anywhere to toggle mode -->
          <div id="cp-ring-container"
            title="${nextLabel}"
            style="position:relative;display:flex;flex-direction:column;align-items:center;
                   padding:4px 0 8px;cursor:pointer;user-select:none;">
            <svg viewBox="0 0 120 120" width="160" height="160">
              <!-- Background ring -->
              <circle cx="60" cy="60" r="50" fill="none"
                stroke="var(--divider-color)" stroke-width="10"
                transform="rotate(-90 60 60)" />
              <!-- Progress ring -->
              <circle cx="60" cy="60" r="50" fill="none"
                stroke="${ringColor}" stroke-width="10" stroke-linecap="round"
                stroke-dasharray="${CIRC}" stroke-dashoffset="${offset}"
                transform="rotate(-90 60 60)"
                style="transition:stroke-dashoffset 1s ease;" />
              <!-- Center text -->
              <text x="60" y="52" text-anchor="middle" dominant-baseline="middle"
                style="font-size:20px;font-weight:700;fill:var(--primary-text-color);">
                ${centerPrimary}
              </text>
              <text x="60" y="70" text-anchor="middle"
                style="font-size:10px;fill:var(--secondary-text-color);">
                ${centerSecondary}
              </text>
              <!-- Tap hint -->
              <text x="60" y="86" text-anchor="middle"
                style="font-size:8px;fill:var(--secondary-text-color);opacity:0.5;">
                ${timerMode === "countdown" ? t("tap_for_temp") : t("tap_for_time")}
              </text>
            </svg>
            ${etaDisplay ? `<div style="font-size:0.95em;color:var(--secondary-text-color);margin-top:2px;">${t("done_at", { eta: etaDisplay })}</div>` : ""}
          </div>

          <!-- Remove from heat banner -->
          ${shouldPull ? `
            <div style="display:flex;align-items:center;gap:12px;padding:12px 16px;margin-top:4px;
                        background:rgba(255,152,0,0.15);
                        border:2px solid var(--warning-color);border-radius:10px;">
              <ha-icon icon="mdi:fire-off"
                style="color:var(--warning-color);--mdc-icon-size:36px;flex-shrink:0;"></ha-icon>
              <div>
                <div style="font-size:1em;font-weight:700;color:var(--warning-color);">
                  ${t("remove_from_heat_now")}
                </div>
                <div style="font-size:0.8em;color:var(--secondary-text-color);margin-top:3px;">
                  ${t("carryover_full", { temp: `${_toDisp(attrs.target_temp, _unit)}${_unitLabel(_unit)}` })}
                  ${t("pull_temp", { temp: `${_toDisp(pullTemp, _unit)}${_unitLabel(_unit)}` })}
                </div>
              </div>
            </div>` : ""}

          <!-- Temperatures row -->
          ${this._renderTempsRow(attrs)}

          <!-- Stall banner — only shown when not already displaying pull warning -->
          ${phase === "stall" && !shouldPull ? `
            <div style="display:flex;align-items:center;gap:10px;padding:10px 14px;margin-top:12px;
                        background:rgba(var(--rgb-error-color,244,67,54),0.12);
                        border:1px solid var(--error-color);border-radius:10px;">
              <ha-icon icon="mdi:pause-circle" style="color:var(--error-color);--mdc-icon-size:28px;flex-shrink:0;"></ha-icon>
              <div>
                <div style="font-size:0.9em;font-weight:600;color:var(--error-color);">${t("stall_detected")}</div>
                <div style="font-size:0.78em;color:var(--secondary-text-color);margin-top:2px;">
                  ${t("stall_detail")}
                </div>
              </div>
            </div>` : ""}

          <!-- Unreachable banner — ambient has fallen below the target -->
          ${phase === "unreachable" ? `
            <div style="display:flex;align-items:center;gap:10px;padding:10px 14px;margin-top:12px;
                        background:rgba(var(--rgb-error-color,244,67,54),0.12);
                        border:1px solid var(--error-color);border-radius:10px;">
              <ha-icon icon="mdi:fire-alert" style="color:var(--error-color);--mdc-icon-size:28px;flex-shrink:0;"></ha-icon>
              <div>
                <div style="font-size:0.9em;font-weight:600;color:var(--error-color);">${t("unreachable_detected")}</div>
                <div style="font-size:0.78em;color:var(--secondary-text-color);margin-top:2px;">
                  ${t("unreachable_detail")}
                </div>
              </div>
            </div>` : ""}

          <!-- Rate -->
          ${attrs.rate_c_per_minute != null
            ? `<div style="text-align:center;font-size:0.82em;color:var(--secondary-text-color);margin-top:8px;">
                ${t("rate", { rate: _unit === "F" ? (attrs.rate_c_per_minute * 9/5).toFixed(2) : attrs.rate_c_per_minute.toFixed(2), unit: _unitLabel(_unit) })}
                ${phase === "stall" ? `<span style="color:var(--error-color);"> ${t("stalled")}</span>` : ""}
               </div>`
            : ""}

          <button id="cp-stop"
            style="width:100%;padding:10px;background:none;color:var(--error-color);
                   border:1px solid var(--error-color);border-radius:8px;
                   font-size:0.9em;cursor:pointer;margin-top:16px;">
            ${t("stop_cook")}
          </button>
        </div>
      </ha-card>`;

    this.querySelector("#cp-ring-container").addEventListener("click", () => {
      localStorage.setItem("probe_ability_timer_mode", nextMode);
      this._render();
    });
    this._addStopConfirm(this.querySelector("#cp-stop"), () => this._callStop(), t("yes_cancel"));
  }

  _renderActiveIndividual(state, attrs) {
    const probeCount = attrs.probe_count || this._cachedProbeCount;
    const probeActiveList = attrs.probe_active || Array(probeCount).fill(false);
    const entityProbeIndex = this._entityProbeIndex(attrs);

    // Which probe indices have a working sensor right now (non-zero reading).
    // Used to suppress idle setup slots for probes that aren't plugged in.
    const availableSet = new Set(this._availableProbeIndices(probeCount, entityProbeIndex));

    // Gather per-probe data — probes 2–4 use dedicated attrs written by sensor.py
    const probeData = [];
    for (let i = 0; i < probeCount; i++) {
      const n = i + 1;
      if (i === 0) {
        probeData.push({
          active: probeActiveList[0],
          currentTemp: attrs.current_temp,
          targetTemp: attrs.target_temp,
          phase: attrs.phase || "collecting",
          confidence: attrs.confidence || "low",
          predictionModel: attrs.prediction_model || "",
          timeRemaining: parseFloat(state.state) || null,
          readingsCount: attrs.readings_count || 0,
          pullTemp: attrs.pull_temp ?? null,
          ratePerMinute: attrs.rate_c_per_minute ?? null,
        });
      } else {
        probeData.push({
          active: attrs[`probe_${n}_active`] || false,
          currentTemp: attrs[`current_temp_${n}`],
          targetTemp: attrs[`target_temp_${n}`],
          phase: attrs[`probe_${n}_phase`] || "collecting",
          confidence: attrs[`probe_${n}_confidence`] || "low",
          predictionModel: attrs[`probe_${n}_prediction_model`] || "",
          timeRemaining: attrs[`probe_${n}_time_remaining`] || null,
          readingsCount: attrs[`probe_${n}_readings_count`] || 0,
          pullTemp: attrs[`probe_${n}_pull_temp`] ?? null,
          ratePerMinute: attrs[`probe_${n}_rate_c_per_minute`] ?? null,
        });
      }
    }

    const ambientTemp = attrs.ambient_temp;

    // Tiles that will render: active probes plus idle ones with a live sensor.
    const shown = probeData.filter((pd, i) => pd.active || availableSet.has(i)).length;
    let open = 0;

    let probeSlots = "";
    for (let i = 0; i < probeCount; i++) {
      const pd = probeData[i];

      // Skip inactive slots whose sensor reads 0 / unavailable
      if (!pd.active && !availableSet.has(i)) continue;

      const phaseColor = {
        heating: "var(--warning-color)",
        stall: "var(--error-color)",
        finishing: "var(--success-color)",
        done: "var(--success-color)",
        unreachable: "var(--error-color)",
      }[pd.phase] || "var(--primary-color)";
      const phaseIcon = {
        heating: "mdi:fire",
        stall: "mdi:pause-circle-outline",
        finishing: "mdi:flag-checkered",
        done: "mdi:check-circle",
        unreachable: "mdi:fire-alert",
      }[pd.phase] || "mdi:thermometer";

      // Pull-from-heat alert — only meaningful once a prediction is running.
      const shouldPull = pd.active
        && pd.phase !== "collecting" && pd.phase !== "done"
        && pd.pullTemp != null
        && pd.currentTemp != null
        && pd.currentTemp >= pd.pullTemp
        && (pd.timeRemaining == null || pd.timeRemaining <= 10);
      const expanded = this._isExpanded(i, shown);
      if (expanded) open++;

      let contentBlock = "";
      let actionBlock = "";

      if (!pd.active) {
        // ── Inactive: show setup form ──────────────────────────────────
        const idleState = this._slotState(i);
        contentBlock = `
          <div style="padding:8px 0 0;">
            <div id="cp-form-idle-${i}">
              ${_presetSelector(`idle-${i}`, idleState, this._tempUnit || "C")}
              <div style="margin-top:4px;">
                <label style="display:block;font-size:0.8em;color:var(--secondary-text-color);margin-bottom:4px;">${t("target_label", { unit: _unitLabel(this._tempUnit || "C") })}</label>
                ${tempInput(`cp-target-idle-${i}`, _toDisp(idleState.temp, this._tempUnit || "C"), this._tempUnit || "C")}
              </div>
            </div>
          </div>`;
        actionBlock = `
          <button class="cp-start-idle-probe" data-index="${i}"
            style="width:100%;padding:8px;margin-top:8px;background:var(--primary-color);
                   color:var(--text-primary-color);border:none;border-radius:6px;
                   font-size:0.85em;font-weight:500;cursor:pointer;">
            ${t("start_probe", { name: this._probeName(i) })}
          </button>`;

      } else if (pd.phase === "collecting") {
        // ── Collecting: two-phase progress ────────────────────────────
        // Phase 1: accumulate 10 readings.
        // Phase 2: wait for the 10-minute data span (30 s/reading assumed).
        const count = pd.readingsCount;
        const displayCount = Math.min(count, NEEDED_READINGS);
        const readingsDone = count >= NEEDED_READINGS;
        const elapsedS = count * READING_INTERVAL_S;
        const spanRemainS = Math.max(0, REQUIRED_SPAN_S - elapsedS);
        const spanPct = Math.min((elapsedS / REQUIRED_SPAN_S) * 100, 100);
        const readyAt = spanRemainS > 0 ? etaFromMinutes(spanRemainS / 60) : "";

        contentBlock = `
          <div style="padding:10px 0 4px;">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
              <ha-icon icon="mdi:timer-sand" style="color:var(--warning-color);--mdc-icon-size:22px;flex-shrink:0;"></ha-icon>
              <span style="font-size:0.85em;color:var(--secondary-text-color);">
                ${t("warming_up_target")} <strong>${pd.targetTemp != null ? `${_toDisp(pd.targetTemp, this._tempUnit || "C")}${_unitLabel(this._tempUnit || "C")}` : "—"}</strong>
              </span>
            </div>

            ${!readingsDone ? `
              <div style="font-size:0.78em;color:var(--secondary-text-color);margin-bottom:4px;">
                ${t("readings", { count: displayCount, needed: NEEDED_READINGS })}
              </div>
              <div style="background:var(--divider-color);border-radius:4px;height:6px;overflow:hidden;">
                <div style="background:var(--warning-color);height:100%;
                            width:${(count / NEEDED_READINGS) * 100}%;
                            border-radius:4px;transition:width 0.5s;"></div>
              </div>
            ` : `
              <div style="display:flex;align-items:center;gap:4px;font-size:0.78em;
                          color:var(--success-color);margin-bottom:6px;">
                <ha-icon icon="mdi:check" style="--mdc-icon-size:14px;"></ha-icon>
                ${t("readings", { count: NEEDED_READINGS, needed: NEEDED_READINGS })}
              </div>
              <div style="font-size:0.78em;color:var(--secondary-text-color);margin-bottom:4px;">
                ${t("building_span")}${readyAt ? ` ${t("ready_at", { time: readyAt })}` : ""}
              </div>
              <div style="background:var(--divider-color);border-radius:4px;height:6px;overflow:hidden;">
                <div style="background:var(--warning-color);height:100%;width:${spanPct}%;
                            border-radius:4px;transition:width 0.5s;"></div>
              </div>
            `}

            <div style="display:flex;flex-wrap:wrap;justify-content:space-between;gap:0 8px;margin-top:8px;
                        font-size:0.8em;color:var(--secondary-text-color);">
              ${pd.currentTemp != null
                ? `<span style="white-space:nowrap;">${t("internal")}: <strong>${_toDisp(pd.currentTemp, this._tempUnit || "C")}${_unitLabel(this._tempUnit || "C")}</strong></span>`
                : "<span></span>"}
              ${ambientTemp != null
                ? `<span style="white-space:nowrap;">${t("ambient")}: <strong>${_toDisp(ambientTemp, this._tempUnit || "C")}${_unitLabel(this._tempUnit || "C")}</strong></span>`
                : ""}
            </div>
          </div>`;
        actionBlock = `
          <button class="cp-stop-probe" data-index="${i}"
            style="width:100%;padding:8px;background:none;color:var(--error-color);
                   border:1px solid var(--error-color);border-radius:6px;
                   font-size:0.8em;cursor:pointer;margin-top:6px;">
            ${t("cancel_probe", { name: this._probeName(i) })}
          </button>`;

      } else if (pd.phase === "done") {
        // ── Done ──────────────────────────────────────────────────────
        contentBlock = `
          <div style="text-align:center;padding:12px 0 4px;">
            <ha-icon icon="mdi:check-circle"
              style="color:var(--success-color);--mdc-icon-size:40px;"></ha-icon>
            <div style="font-size:0.9em;font-weight:600;color:var(--success-color);margin-top:4px;">
              ${t("target_reached")}
            </div>
            ${pd.currentTemp != null
              ? `<div style="font-size:0.8em;color:var(--secondary-text-color);">${_toDisp(pd.currentTemp, this._tempUnit || "C")}${_unitLabel(this._tempUnit || "C")}</div>`
              : ""}
          </div>`;
        actionBlock = `
          <button class="cp-stop-probe" data-index="${i}"
            style="width:100%;padding:8px;background:var(--primary-color);
                   color:var(--text-primary-color);border:none;border-radius:6px;
                   font-size:0.8em;font-weight:500;cursor:pointer;margin-top:4px;">
            ${t("new_cook_probe", { name: this._probeName(i) })}
          </button>`;

      } else {
        // ── Active: ring + info rows ───────────────────────────────────
        // Countdown ring — always shows time remaining in individual mode
        let progress = 0;
        let centerPrimary = "—";
        let centerSecondary = t("estimating");
        if (pd.timeRemaining) {
          const elapsed = pd.readingsCount * 0.5;
          const total = pd.timeRemaining + elapsed;
          progress = total > 0 ? Math.min(elapsed / total, 1) : 0;
          centerPrimary = formatTime(pd.timeRemaining);
          centerSecondary = t("remaining");
        }

        const offset = (CIRC * (1 - progress)).toFixed(2);
        const ringColor = shouldPull ? "var(--warning-color)" : phaseColor;

        // Temp progress bar (current → target)
        const tempPct = (pd.currentTemp != null && pd.targetTemp > 0)
          ? Math.min((pd.currentTemp / pd.targetTemp) * 100, 100).toFixed(1)
          : null;

        const eta = etaFromMinutes(pd.timeRemaining);

        contentBlock = `
          <svg viewBox="0 0 120 120" width="100" height="100"
               style="display:block;margin:6px auto 0;">
            <circle cx="60" cy="60" r="50" fill="none"
              stroke="var(--divider-color)" stroke-width="10"
              transform="rotate(-90 60 60)" />
            <circle cx="60" cy="60" r="50" fill="none"
              stroke="${ringColor}" stroke-width="10" stroke-linecap="round"
              stroke-dasharray="${CIRC}" stroke-dashoffset="${offset}"
              transform="rotate(-90 60 60)"
              style="transition:stroke-dashoffset 1s ease;" />
            <text x="60" y="52" text-anchor="middle" dominant-baseline="middle"
              style="font-size:18px;font-weight:700;fill:var(--primary-text-color);">
              ${centerPrimary}
            </text>
            <text x="60" y="70" text-anchor="middle"
              style="font-size:9px;fill:var(--secondary-text-color);">
              ${centerSecondary}
            </text>
          </svg>

          ${tempPct != null ? `
            <div style="margin-top:10px;">
              <div style="display:flex;justify-content:space-between;
                          font-size:0.8em;color:var(--secondary-text-color);margin-bottom:3px;">
                <span><strong style="color:var(--primary-text-color);">${_toDisp(pd.currentTemp, this._tempUnit || "C")}${_unitLabel(this._tempUnit || "C")}</strong></span>
                <span>${_toDisp(pd.targetTemp, this._tempUnit || "C")}${_unitLabel(this._tempUnit || "C")}</span>
              </div>
              <div style="background:var(--divider-color);border-radius:4px;height:5px;overflow:hidden;">
                <div style="background:${ringColor};height:100%;width:${tempPct}%;
                            border-radius:4px;transition:width 1s ease;"></div>
              </div>
            </div>` : ""}

          <div style="display:flex;flex-wrap:wrap;justify-content:space-between;gap:0 8px;margin-top:8px;
                      font-size:0.78em;color:var(--secondary-text-color);">
            <span style="white-space:nowrap;">${pd.ratePerMinute != null
              ? t("rate", { rate: (this._tempUnit === "F" ? pd.ratePerMinute * 9/5 : pd.ratePerMinute).toFixed(2), unit: _unitLabel(this._tempUnit || "C") })
              : ""}</span>
            <span style="white-space:nowrap;">${eta ? t("eta", { eta }) : ""}</span>
          </div>
          ${ambientTemp != null ? `
            <div style="font-size:0.78em;color:var(--secondary-text-color);margin-top:2px;">
              ${t("ambient")}: ${_toDisp(ambientTemp, this._tempUnit || "C")}${_unitLabel(this._tempUnit || "C")}
            </div>` : ""}

          ${shouldPull ? `
            <div style="display:flex;align-items:center;gap:8px;padding:8px 10px;margin-top:8px;
                        background:rgba(255,152,0,0.15);
                        border:2px solid var(--warning-color);border-radius:10px;">
              <ha-icon icon="mdi:fire-off"
                style="color:var(--warning-color);--mdc-icon-size:22px;flex-shrink:0;"></ha-icon>
              <div>
                <div style="font-size:0.85em;font-weight:700;color:var(--warning-color);">
                  ${t("remove_from_heat_now")}
                </div>
                <div style="font-size:0.73em;color:var(--secondary-text-color);margin-top:1px;">
                  ${t("carryover_short", { temp: `${_toDisp(pd.targetTemp, this._tempUnit || "C")}${_unitLabel(this._tempUnit || "C")}` })} ${t("pull_temp_short", { temp: `${_toDisp(pd.pullTemp, this._tempUnit || "C")}${_unitLabel(this._tempUnit || "C")}` })}
                </div>
              </div>
            </div>` : ""}
          ${pd.phase === "stall" && !shouldPull ? `
            <div style="display:flex;align-items:center;gap:6px;padding:5px 8px;margin-top:6px;
                        background:rgba(var(--rgb-error-color,244,67,54),0.1);
                        border:1px solid var(--error-color);border-radius:8px;font-size:0.76em;">
              <ha-icon icon="mdi:pause-circle"
                style="color:var(--error-color);--mdc-icon-size:16px;flex-shrink:0;"></ha-icon>
              <span style="color:var(--error-color);">${t("stall_short")}</span>
            </div>` : ""}
          ${pd.phase === "unreachable" ? `
            <div style="display:flex;align-items:center;gap:6px;padding:5px 8px;margin-top:6px;
                        background:rgba(var(--rgb-error-color,244,67,54),0.1);
                        border:1px solid var(--error-color);border-radius:8px;font-size:0.76em;">
              <ha-icon icon="mdi:fire-alert"
                style="color:var(--error-color);--mdc-icon-size:16px;flex-shrink:0;"></ha-icon>
              <span style="color:var(--error-color);">${t("unreachable_short")}</span>
            </div>` : ""}`;

        actionBlock = `
          <button class="cp-stop-probe" data-index="${i}"
            style="width:100%;padding:8px;background:none;color:var(--error-color);
                   border:1px solid var(--error-color);border-radius:6px;
                   font-size:0.8em;cursor:pointer;margin-top:8px;">
            ${t("stop_probe", { name: this._probeName(i) })}
          </button>`;
      }

      const confDots = { low: "●○○", medium: "●●○", high: "●●●" }[pd.confidence] || "";
      const indivModelBadge = pd.predictionModel === "ml"
        ? `<span style="font-size:0.7em;background:rgba(76,175,80,0.15);color:#4caf50;border-radius:3px;padding:1px 4px;margin-left:5px;vertical-align:middle;">ML</span>`
        : pd.predictionModel === "physics"
        ? `<span style="font-size:0.7em;color:var(--secondary-text-color);opacity:0.5;margin-left:5px;vertical-align:middle;">PHY</span>`
        : "";
      const showPhaseDetail = pd.active && pd.phase !== "collecting" && pd.phase !== "done";
      const probePresetName = pd.active ? this._getActivePresetName(i) : null;

      // Header right side while the tile is open — unchanged from the
      // always-open layout: preset name, target, confidence, model badge.
      const rightHtml = `
            <div style="font-size:0.75em;color:var(--secondary-text-color);text-align:right;line-height:1.6;">
              ${pd.active
                ? `${probePresetName
                     ? `<div style="font-weight:500;color:var(--primary-text-color);">${probePresetName}</div>`
                     : ""}
                   <div>${pd.targetTemp != null ? `${_toDisp(pd.targetTemp, this._tempUnit || "C")}${_unitLabel(this._tempUnit || "C")}` : "?"}${showPhaseDetail && confDots
                     ? `<span style="margin-left:6px;letter-spacing:2px;">${confDots}</span>${indivModelBadge}`
                     : ""}</div>`
                : `<div>${t("not_started")}</div>`}
            </div>`;

      // Collapsed rows show an icon for every running state; open tiles keep
      // the icon only for the prediction phases, as before.
      const collapsedIcon = !pd.active ? ""
        : shouldPull ? "mdi:fire-off"
        : pd.phase === "collecting" ? "mdi:timer-sand"
        : phaseIcon;

      probeSlots += this._probeTile(i, {
        expanded,
        titleColor: shouldPull && !expanded ? "var(--warning-color)"
          : pd.active ? phaseColor : "var(--secondary-text-color)",
        icon: expanded ? (showPhaseDetail ? phaseIcon : "") : collapsedIcon,
        subtitle: pd.active ? (probePresetName || "") : this._idleCookName(i),
        rightHtml,
        summary: this._probeSummary(i, pd, shouldPull, phaseColor),
        alert: shouldPull && !expanded,   // open tiles already show the banner
        detail: contentBlock + actionBlock,
      });
    }
    this._lastTileCount = shown;
    this._lastOpenCount = open;

    this.innerHTML = `
      <ha-card>
        <div style="padding:20px;">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;">
            <div style="display:flex;align-items:center;gap:10px;">
              ${LOGO_SVG}
              <span style="font-size:1.2em;font-weight:500;">Probe-ability</span>
            </div>
            <span style="font-size:0.75em;color:var(--secondary-text-color);
                         background:var(--divider-color);padding:2px 8px;
                         border-radius:10px;">${t("individual_badge")}</span>
          </div>
          ${this._tilesContainer(probeSlots, shown)}
        </div>
      </ha-card>`;

    // Stop / cancel buttons — each gets its own confirmation prompt
    this.querySelectorAll(".cp-stop-probe").forEach((btn) => {
      const idx = parseInt(btn.dataset.index, 10);
      const pd = probeData[idx];
      const label = pd.phase === "collecting" ? t("yes_cancel")
                  : pd.phase === "done"       ? t("yes_new_cook")
                  :                             t("yes_stop");
      this._addStopConfirm(btn, () => this._callStop(idx), label);
    });

    // Start buttons for idle probe slots inside the active-individual view
    this.querySelectorAll(".cp-start-idle-probe").forEach((btn) => {
      const i = parseInt(btn.dataset.index, 10);
      this._wireIdleSlot(i, `idle-${i}`, {
        startId: null,   // start button wired separately via class selector below
        isIndividual: true,
        probeIndex: i,
      });
      btn.addEventListener("click", () => {
        const s = this._slotState(i);
        const cookName = _makeCookName(s.category, s.cut, s.doneness);
        this._saveActivePreset(i, cookName);
        this._syncTargetTemp(i, s.temp);
        this._callStart({ target_temp: s.temp, probe_mode: "individual", probe_index: i, cook_name: cookName });
      });
    });

    this._wireTileToggles(shown);
  }

  // ── Done ──────────────────────────────────────────────────────────────

  _renderDone(attrs) {
    this.innerHTML = `
      <ha-card>
        <div style="padding:20px;">
          <div style="text-align:center;padding:24px 0;">
            <ha-icon icon="mdi:check-circle"
              style="color:var(--success-color);--mdc-icon-size:64px;margin-bottom:12px;"></ha-icon>
            <div style="font-size:1.4em;font-weight:600;margin-bottom:4px;">${t("cook_complete")}</div>
            ${attrs.message && attrs.message.startsWith("Rested")
              ? `<div style="font-size:1em;color:${attrs.message.includes("below target") ? "var(--warning-color)" : "var(--success-color)"};">${attrs.message}</div>`
              : `<div style="font-size:1em;color:var(--success-color);">${t("target_temp_reached")}</div>`}
          </div>
          ${this._renderTempsRow(attrs)}
          <button id="cp-stop"
            style="width:100%;padding:12px;background:var(--primary-color);
                   color:var(--text-primary-color);border:none;border-radius:8px;
                   font-size:1em;font-weight:500;cursor:pointer;margin-top:16px;">
            ${t("new_cook")}
          </button>
        </div>
      </ha-card>`;

    this._addStopConfirm(this.querySelector("#cp-stop"), () => this._callStop(), t("yes_cancel"));
  }

  // ── Temperature display ───────────────────────────────────────────────

  _renderTempsRow(attrs) {
    const temps = [];

    if (attrs.current_temp != null) {
      temps.push({ label: attrs.probe_count > 1 ? this._probeName(0) : t("internal"), value: attrs.current_temp });
    }
    for (let n = 2; n <= MAX_PROBES; n++) {
      if (attrs[`current_temp_${n}`] != null) {
        temps.push({ label: this._probeName(n - 1), value: attrs[`current_temp_${n}`] });
      }
    }
    if (attrs.ambient_temp != null) {
      temps.push({ label: t("ambient"), value: attrs.ambient_temp });
    }

    if (temps.length === 0) return "";

    const _unit = this._tempUnit || "C";
    const cells = temps.map(
      (t) => `
        <div style="text-align:center;">
          <div style="font-size:0.75em;color:var(--secondary-text-color);">${t.label}</div>
          <div style="font-size:1.3em;font-weight:600;">${_toDisp(t.value, _unit)}${_unitLabel(_unit)}</div>
        </div>`
    ).join("");

    return `<div style="display:flex;flex-wrap:wrap;justify-content:center;gap:8px 24px;padding:10px 0;">${cells}</div>`;
  }

  // ── Stop confirmation ─────────────────────────────────────────────────

  // Replaces `btn` with an inline "Are you sure?" prompt.
  // Confirming calls stopFn(); denying restores the original button.
  // If HA pushes a state update while the prompt is open it will be wiped
  // by the re-render — the user simply clicks Stop again.
  _addStopConfirm(btn, stopFn, confirmLabel) {
    if (confirmLabel == null) confirmLabel = t("yes_stop");
    btn.addEventListener("click", () => {
      this._confirmPending = true;   // block hass() re-renders while prompt is open
      const wrapper = document.createElement("div");
      wrapper.style.cssText = "margin-top:4px;";
      wrapper.innerHTML = `
        <div style="font-size:0.82em;color:var(--error-color);text-align:center;margin-bottom:6px;font-weight:500;">
          ${t("are_you_sure")}
        </div>
        <div style="display:flex;gap:6px;">
          <button class="cp-confirm-yes"
            style="flex:1;padding:8px;background:var(--error-color);color:white;
                   border:none;border-radius:6px;font-size:0.82em;cursor:pointer;font-weight:500;">
            ${confirmLabel}
          </button>
          <button class="cp-confirm-no"
            style="flex:1;padding:8px;background:none;color:var(--primary-text-color);
                   border:1px solid var(--divider-color);border-radius:6px;
                   font-size:0.82em;cursor:pointer;">
            ${t("keep_cooking")}
          </button>
        </div>`;
      btn.replaceWith(wrapper);
      wrapper.querySelector(".cp-confirm-yes").addEventListener("click", () => {
        this._confirmPending = false;
        stopFn();
      });
      wrapper.querySelector(".cp-confirm-no").addEventListener("click", () => {
        this._confirmPending = false;
        wrapper.replaceWith(btn);
      });
    });
  }

  // ── Service helpers ───────────────────────────────────────────────────

  _callStart(serviceData) {
    this._hass.callService("probe_ability", "start_cook", {
      ...serviceData,
      ...(this._config.entry_id ? { entry_id: this._config.entry_id } : {}),
    });
  }

  _callStop(probeIndex) {
    const data = this._config.entry_id ? { entry_id: this._config.entry_id } : {};
    if (probeIndex != null) data.probe_index = probeIndex;
    this._hass.callService("probe_ability", "stop_cook", data);
  }

  getCardSize() {
    // Masonry hint (≈50 px rows): header + one row per tile row plus the
    // detail of each row holding open tiles.  5, as before, for the non-tile views.
    if (this._lastTileCount == null) return 5;
    const perRow = this._probeLayout === "horizontal" ? this._lastTileCount
      : this._probeLayout === "grid" ? 2 : 1;
    const rows = Math.ceil(this._lastTileCount / Math.max(1, perRow));
    const openRows = Math.ceil((this._lastOpenCount || 0) / Math.max(1, perRow));
    return 2 + rows + 4 * openRows;
  }

  static getConfigElement() {
    return document.createElement("probe-ability-card-editor");
  }

  static getStubConfig(hass) {
    const entity = hass
      ? Object.keys(hass.states).find((e) => /^sensor\.probe_ability_time_remaining/.test(e)) || ""
      : "";
    return { entity };
  }
}

// ─── Visual editor (ha-form based) ─────────────────────────────────────────────

// `tkey` maps each field to an I18N key; the label is resolved at render time
// via computeLabel so the editor follows the user's language.
//
// Fields are grouped into collapsible `expandable` sections (General + one per
// probe). Expandable groups are purely visual — the form data stays flat, so
// _toFormData / _fromFormData are unaffected. Section titles are resolved here
// because ha-form reads a section's `title` directly (not via computeLabel).
function _buildEditorSchema() {
  return [
    {
      type: "expandable", title: t("ed_sec_general"),
      icon: "mdi:cog", expanded: true,
      schema: [
        { name: "entity",         tkey: "ed_entity",  selector: { entity: {} } },
        { name: "ambient_sensor", tkey: "ed_ambient", selector: { entity: {} } },
        { name: "entry_id",       tkey: "ed_entry",   selector: { text: {} } },
        { name: "probe_layout",   tkey: "ed_layout",  selector: { select: {
            mode: "dropdown",
            options: [
              { value: "vertical",   label: t("layout_vertical") },
              { value: "horizontal", label: t("layout_horizontal") },
              { value: "grid",       label: t("layout_grid") },
            ],
        } } },
        { name: "collapsible",    tkey: "ed_collapsible", selector: { boolean: {} } },
      ],
    },
    // One section per probe: its target-temp helper and its sensor.
    ...Array.from({ length: MAX_PROBES }, (_, i) => ({
      type: "expandable", title: t("probe_n", { n: i + 1 }),
      icon: "mdi:thermometer", expanded: false,
      schema: [
        { name: _targetKey(i), tkey: i === 0 ? "ed_target_entity" : "ed_target_entity_n", tvars: { n: i + 1 },
          selector: { entity: { domain: "input_number" } } },
        { name: `probe_sensor_${i}`, tkey: "ed_probe_n", tvars: { n: i + 1 }, selector: { entity: {} } },
      ],
    })),
  ];
}

class CookPredictorCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    this._updateForm();
  }

  set hass(hass) {
    this._hass = hass;
    this._updateForm();
  }

  // Flatten probe_sensors array → individual schema keys
  _toFormData(cfg) {
    const ps = cfg.probe_sensors || [];
    const data = {
      entity:         cfg.entity         || "",
      ambient_sensor: cfg.ambient_sensor || "",
      entry_id:       cfg.entry_id       || "",
      probe_layout:   cfg.probe_layout   || "",
      collapsible:    cfg.collapsible !== false,
    };
    for (let i = 0; i < MAX_PROBES; i++) {
      data[_targetKey(i)] = cfg[_targetKey(i)] || "";
      data[`probe_sensor_${i}`] = ps[i] || "";
    }
    return data;
  }

  // Rebuild card config from flat form data
  _fromFormData(data) {
    // Start from existing config to preserve `type` and any other fields
    const cfg = { ...this._config };
    const setOrDelete = (key, value) => {
      if (value) cfg[key] = value;
      else delete cfg[key];
    };
    setOrDelete("entity", data.entity);
    setOrDelete("ambient_sensor", data.ambient_sensor);
    setOrDelete("entry_id", data.entry_id);
    setOrDelete("probe_layout", data.probe_layout);
    // Collapsible is on by default: only persist an explicit "off".
    if (data.collapsible === false) cfg.collapsible = false;
    else delete cfg.collapsible;
    delete cfg.eta_entity;   // retired option — tidy it out of edited configs
    const probes = [];
    for (let i = 0; i < MAX_PROBES; i++) {
      setOrDelete(_targetKey(i), data[_targetKey(i)]);
      probes.push(data[`probe_sensor_${i}`]);
    }
    setOrDelete("probe_sensors", probes.filter(Boolean).length ? probes.filter(Boolean) : null);
    return cfg;
  }

  _updateForm() {
    if (!this._hass || !this._config) return;
    _setLang(this._hass);

    // Create ha-form once; update its properties on subsequent calls
    let form = this.querySelector("ha-form");
    if (!form) {
      form = document.createElement("ha-form");
      form.computeLabel = (schema) => (schema.tkey ? t(schema.tkey, schema.tvars) : schema.label || schema.name);
      form.addEventListener("value-changed", (e) => {
        this._config = this._fromFormData(e.detail.value);
        this.dispatchEvent(new CustomEvent("config-changed", {
          detail: { config: { ...this._config } },
          bubbles: true,
          composed: true,
        }));
      });
      this.appendChild(form);
    }

    form.hass   = this._hass;
    form.schema = _buildEditorSchema();
    form.data   = this._toFormData(this._config);
  }
}

customElements.define("probe-ability-card", CookPredictorCard);
customElements.define("probe-ability-card-editor", CookPredictorCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "probe-ability-card",
  name: "Probe-ability",
  description: "Predictive meat thermometer card with multi-probe support, preset dropdown, and circular timer.",
  preview: true,
  version: CARD_VERSION,
});

console.info(`%c PROBE-ABILITY CARD %c v${CARD_VERSION} `, "color:#fff;background:#e8622a;font-weight:bold;", "color:#e8622a;background:#fff;font-weight:bold;");
