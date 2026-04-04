/**
 * Probe-ability Card v1.0.0
 *
 * Custom Lovelace card for the Probe-ability integration.
 * Shows cook status, predictions, and lets you start/stop cooks.
 *
 * Features:
 *  - Individual mode: up to 3 independent probes (e.g. 3 steaks)
 *  - Combined mode: multiple probes on one cook (e.g. brisket)
 *  - Circular SVG timer with two display modes:
 *      ⏱ Countdown — ring drains as time passes
 *      🌡 Temp-up  — ring fills as temperature rises toward target
 *
 * Installation:
 *   1. Copy this file to config/www/probe-ability-card.js
 *   2. Add as a resource in Lovelace:
 *      URL: /local/probe-ability-card.js
 *      Type: JavaScript Module
 *
 * Card config:
 *   type: custom:probe-ability-card
 *   entity: sensor.probe_ability_time_remaining
 *   eta_entity: sensor.probe_ability_estimated_completion  (optional)
 *   entry_id: <your_entry_id>                               (optional)
 */

const CARD_VERSION = "1.0.0";

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
      fetch("/local/probe-ability/cook_presets.json")
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
function _makeCookName(category, cut, doneness) {
  if (!_presets || !category || !cut || !doneness) return "Custom";
  const catObj = _presets.categories.find((c) => c.id === category);
  const cutObj = catObj?.cuts.find((c) => c.id === cut);
  const donObj = cutObj?.doneness.find((d) => d.id === doneness);
  return catObj && cutObj && donObj
    ? `${catObj.label} ${cutObj.label} ${donObj.label}`
    : "Custom";
}

// Render the 3-step hierarchical preset selector for one idle slot.
//   idSuffix  — unique string used as suffix for all element IDs and data-slot
//   slotState — { category, cut, doneness, temp }
//
// Step 1: row of icon-pill buttons (one per category)
// Step 2: cut <select> — appears after a category is chosen
// Step 3: doneness <select> — appears after a cut is chosen (skipped for
//         single-doneness cuts, which are auto-selected)
function _presetSelector(idSuffix, slotState) {
  const selStyle = `width:100%;box-sizing:border-box;padding:10px 12px;
    border:1px solid var(--divider-color);border-radius:8px;font-size:0.95em;
    background:var(--card-background-color);color:var(--primary-text-color);cursor:pointer;`;

  if (!_presets) {
    return `<div style="font-size:0.85em;color:var(--secondary-text-color);padding:8px 0;">
      Loading presets…</div>`;
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
        ${c.icon} ${c.label}
      </button>`;
    })
    .join("");
  let html = `<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px;">${catBtns}</div>`;

  if (!category) return html;

  // Step 2 — cut dropdown
  const catObj = _presets.categories.find((c) => c.id === category);
  if (!catObj) return html;

  const cutOpts = catObj.cuts
    .map((c) => `<option value="${c.id}"${c.id === cut ? " selected" : ""}>${c.label}</option>`)
    .join("");
  html += `<div style="margin-bottom:8px;">
    <select id="cp-cut-${idSuffix}" style="${selStyle}">
      <option value="">— Select cut —</option>
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
        `<option value="${d.id}"${d.id === doneness ? " selected" : ""}>${d.label} (${d.temp}°C)</option>`
    )
    .join("");
  html += `<div style="margin-bottom:8px;">
    <select id="cp-don-${idSuffix}" style="${selStyle}">
      <option value="">— Select doneness —</option>
      ${donOpts}
    </select>
  </div>`;

  return html;
}

// SVG ring constants (r=50, cx=cy=60)
const CIRC = 314.16; // 2π × 50

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

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatTime(minutes) {
  if (minutes == null || isNaN(minutes)) return "—";
  if (minutes >= 60) {
    const h = Math.floor(minutes / 60);
    const m = Math.round(minutes % 60);
    return `${h}h ${m}m`;
  }
  return `${Math.round(minutes)}m`;
}

function etaFromMinutes(minutes) {
  if (!minutes || isNaN(minutes) || minutes <= 0) return "";
  const d = new Date(Date.now() + minutes * 60 * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function tempInput(id, value) {
  return `<input id="${id}" type="number" value="${value}" min="30" max="200" step="0.5"
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
      ${m === "combined" ? "🔗 Combined" : "⚡ Individual"}
    </button>`;
  });
  return `<div id="cp-mode-toggle" style="display:flex;gap:8px;margin-bottom:16px;">${btns.join("")}</div>`;
}

// ─── Main card ────────────────────────────────────────────────────────────────

class CookPredictorCard extends HTMLElement {
  setConfig(config) {
    if (!config.entity) {
      throw new Error("Please define an entity (time_remaining sensor)");
    }
    this._config = config;
    this._hass = null;
    this._probeSensors = config.probe_sensors || [];
    this._ambientSensor = config.ambient_sensor || null;
    // Per-slot form state: { category, cut, doneness, temp }
    // Key: "combined" or probe index 0/1/2.
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
    // Start loading presets immediately so data is ready before first render
    _loadPresets().then(() => { if (this._hass) this._render(); });
  }

  set hass(hass) {
    const prev = this._hass;
    this._hass = hass;
    this._saveIdleFormState();

    const entity = this._config?.entity;
    const ns = hass.states[entity];
    const na = ns?.attributes || {};
    const isIdle = !na.active;

    if (isIdle) {
      // During idle the form is driven entirely by local state, not HA state.
      // Rebuilding on every hass push destroys open dropdowns and focused inputs.

      // 1. Skip if a form element in this card currently has focus.
      const focused = document.activeElement;
      if (focused && this.contains(focused) &&
          (focused.tagName === "SELECT" || focused.tagName === "INPUT")) {
        return;
      }

      // 2. Skip if nothing that affects the idle view has changed.
      if (prev) {
        const ps = prev.states[entity];
        const pa = ps?.attributes || {};
        if (!pa.active && !na.active && pa.probe_count === na.probe_count) {
          return;
        }
      }
    }

    this._render();
  }

  _saveIdleFormState() {
    // Only the manual temp input needs capturing — category/cut/doneness are
    // persisted immediately in the event handlers.
    const saveTemp = (key, targetId) => {
      const el = this.querySelector(`#${targetId}`);
      if (!el) return;
      const temp = parseFloat(el.value) || 74;
      this._idleState[key] = { ...(this._idleState[key] || {}), temp };
    };
    saveTemp("combined", "cp-target-combined");
    for (let i = 0; i < 3; i++) {
      saveTemp(i, `cp-target-${i}`);           // individual idle slot
      saveTemp(i, `cp-target-idle-${i}`);      // idle slot inside active-individual view
      saveTemp(`sp-${i}`, `cp-target-sp-${i}`); // single-probe view
    }
    this._persistIdleState();
  }

  // Returns { category, cut, doneness, temp } for a slot.
  _slotState(key) {
    return this._idleState[key] || { category: null, cut: null, doneness: null, temp: 74 };
  }

  _persistIdleState() {
    try {
      localStorage.setItem("probe_ability_idle_state", JSON.stringify(this._idleState));
    } catch (e) { /* ignore quota errors */ }
  }

  // Persist the cook name that was active when a cook was started.
  // Key: "combined" or probe index 0/1/2.
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
  _availableProbeIndices(totalCount) {
    if (!this._probeSensors || !this._probeSensors.length) {
      return Array.from({ length: totalCount }, (_, i) => i);
    }
    return this._probeSensors
      .slice(0, totalCount)
      .map((id, i) => ({ id, i }))
      .filter(({ id }) => {
        const s = this._hass && this._hass.states[id];
        return s && s.state !== "unavailable" && s.state !== "unknown"
               && !isNaN(parseFloat(s.state)) && parseFloat(s.state) !== 0;
      })
      .map(({ i }) => i);
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

    const entity = this._config.entity;
    const state = this._hass.states[entity];

    if (!state) {
      this.innerHTML = `
        <ha-card header="Probe-ability">
          <div style="padding:16px;color:var(--error-color);">
            Entity not found: ${entity}
          </div>
        </ha-card>`;
      return;
    }

    const attrs = state.attributes;
    const probeMode = attrs.probe_mode || this._probeMode;
    const phase = attrs.phase || "idle";
    const isActive = attrs.active || false;

    // Keep probe_count in sync while we have live attributes
    if (attrs.probe_count) this._cacheProbeCount(attrs.probe_count);

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
    const available = this._availableProbeIndices(probeCount);

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
            <div style="font-size:1em;font-weight:500;margin-top:10px;">No probe sensors available</div>
            <div style="font-size:0.85em;color:var(--secondary-text-color);margin-top:6px;">
              Check that your thermometer probes are connected and visible in Home Assistant.
            </div>
          </div>
        </div>
      </ha-card>`;
  }

  _renderIdleSingleProbe(probeIndex) {
    const slotKey = `sp-${probeIndex}`;
    const state = this._slotState(slotKey);
    this.innerHTML = `
      <ha-card>
        <div style="padding:20px;">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:20px;">
            ${LOGO_SVG}
            <span style="font-size:1.3em;font-weight:500;">Probe-ability</span>
          </div>
          <div>
            <div id="cp-form-${slotKey}">
              ${_presetSelector(slotKey, state)}
              <div style="margin-top:4px;">
                <label style="display:block;font-size:0.85em;color:var(--secondary-text-color);margin-bottom:4px;">Target temperature (°C)</label>
                ${tempInput(`cp-target-${slotKey}`, state.temp)}
              </div>
            </div>
            <button id="cp-start-single"
              style="width:100%;padding:12px;margin-top:16px;background:var(--primary-color);
                     color:var(--text-primary-color);border:none;border-radius:8px;
                     font-size:1em;font-weight:500;cursor:pointer;">
              Start Cook
            </button>
          </div>
        </div>
      </ha-card>`;

    this._wireIdleSlot(slotKey, slotKey, { startId: "cp-start-single", isIndividual: true, probeIndex });
  }

  _idleCombinedForm() {
    const state = this._slotState("combined");
    return `
      <div>
        <div id="cp-form-combined">
          ${_presetSelector("combined", state)}
          <div style="margin-top:4px;">
            <label style="display:block;font-size:0.85em;color:var(--secondary-text-color);margin-bottom:4px;">Target temperature (°C)</label>
            ${tempInput("cp-target-combined", state.temp)}
          </div>
        </div>
        <button id="cp-start-combined"
          style="width:100%;padding:12px;margin-top:16px;background:var(--primary-color);
                 color:var(--text-primary-color);border:none;border-radius:8px;
                 font-size:1em;font-weight:500;cursor:pointer;">
          Start Cook
        </button>
      </div>`;
  }

  _idleIndividualSlots(available) {
    const probeLabels = ["Probe 1", "Probe 2", "Probe 3"];
    let html = "";
    for (const i of available) {
      const state = this._slotState(i);
      html += `
        <div style="border:1px solid var(--divider-color);border-radius:10px;padding:14px;margin-bottom:12px;">
          <div style="font-size:0.9em;font-weight:600;margin-bottom:10px;color:var(--primary-color);">
            ${probeLabels[i] || `Probe ${i + 1}`}
          </div>
          <div id="cp-form-${i}">
            ${_presetSelector(i, state)}
            <div style="margin-top:4px;">
              <label style="display:block;font-size:0.8em;color:var(--secondary-text-color);margin-bottom:4px;">Target (°C)</label>
              ${tempInput(`cp-target-${i}`, state.temp)}
            </div>
          </div>
          <button id="cp-start-${i}"
            style="width:100%;padding:10px;margin-top:10px;background:var(--primary-color);
                   color:var(--text-primary-color);border:none;border-radius:8px;
                   font-size:0.9em;font-weight:500;cursor:pointer;">
            Start Probe ${i + 1}
          </button>
        </div>`;
    }
    return html;
  }

  // Rebuild only the preset selector + temp label inside one form wrapper div,
  // then re-wire its event handlers.  Much cheaper than a full card re-render
  // and avoids scroll jumps / losing focus on sibling elements.
  _refreshForm(idSuffix, stateKey, opts) {
    const container = this.querySelector(`#cp-form-${idSuffix}`);
    if (!container) { this._render(); return; }
    const state = this._slotState(stateKey);
    container.innerHTML = `
      ${_presetSelector(idSuffix, state)}
      <div style="margin-top:4px;">
        <label style="display:block;font-size:0.85em;color:var(--secondary-text-color);margin-bottom:4px;">
          Target temperature (°C)
        </label>
        ${tempInput(`cp-target-${idSuffix}`, state.temp)}
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
    const getS = () => this._idleState[stateKey] || { category: null, cut: null, doneness: null, temp: 74 };
    const upd = (patch) => {
      this._idleState[stateKey] = { ...getS(), ...patch };
      this._persistIdleState();
    };

    // Category pill buttons — use targeted form refresh to avoid scroll jumps
    this.querySelectorAll(`button[data-action="cat"][data-slot="${idSuffix}"]`).forEach((btn) => {
      btn.addEventListener("click", () => {
        upd({ category: btn.dataset.val, cut: null, doneness: null, temp: 74 });
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
          upd({ cut: cutEl.value, doneness: cutObj.doneness[0].id, temp: cutObj.doneness[0].temp });
        } else {
          upd({ cut: cutEl.value, doneness: null });
        }
        this._refreshForm(idSuffix, stateKey, opts);
      });
    }

    // Doneness dropdown
    const targetEl = this.querySelector(`#cp-target-${idSuffix}`);
    const donEl = this.querySelector(`#cp-don-${idSuffix}`);
    if (donEl) {
      donEl.addEventListener("change", () => {
        if (!_presets) return;
        const s = getS();
        const catObj = _presets.categories.find((c) => c.id === s.category);
        const cutObj = catObj?.cuts.find((c) => c.id === s.cut);
        const donObj = cutObj?.doneness.find((d) => d.id === donEl.value);
        const temp = donObj?.temp ?? s.temp;
        upd({ doneness: donEl.value, temp });
        if (targetEl) targetEl.value = temp;
      });
    }

    // Manual temp input
    if (targetEl) {
      targetEl.addEventListener("input", (e) => {
        upd({ temp: parseFloat(e.target.value) || 74 });
      });
    }

    // Start button
    const startBtn = opts.startId ? this.querySelector(`#${opts.startId}`) : null;
    if (startBtn) {
      startBtn.addEventListener("click", () => {
        const s = getS();
        const cookName = _makeCookName(s.category, s.cut, s.doneness);
        this._saveActivePreset(stateKey, cookName);
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
    const msg = attrs.message || `Collecting data (${displayCount}/${needed})`;
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
                         padding:2px 8px;border-radius:10px;">${probeMode}</span>
          </div>

          <div style="text-align:center;padding:16px 0;">
            <ha-icon icon="mdi:timer-sand" style="color:var(--secondary-text-color);--mdc-icon-size:40px;"></ha-icon>
            <div style="font-size:1em;color:var(--secondary-text-color);margin:10px 0 4px;">
              Warming up… target <strong>${attrs.target_temp || "—"}°C</strong>
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
            Cancel Cook
          </button>
        </div>
      </ha-card>`;

    this._addStopConfirm(this.querySelector("#cp-stop"), () => this._callStop(), "Yes, cancel");
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
    const phaseColor = { heating: "var(--warning-color)", stall: "var(--error-color)", finishing: "var(--success-color)" }[phase] || "var(--primary-color)";
    const phaseIcon = { heating: "mdi:fire", stall: "mdi:pause-circle-outline", finishing: "mdi:flag-checkered" }[phase] || "mdi:fire";
    const confDots = { low: "●○○", medium: "●●○", high: "●●●" }[confidence] || "";
    const modelBadge = attrs.prediction_model === "ml"
      ? `<span style="font-size:0.7em;background:rgba(76,175,80,0.15);color:#4caf50;border-radius:3px;padding:1px 4px;margin-left:5px;vertical-align:middle;">ML</span>`
      : attrs.prediction_model === "physics"
      ? `<span style="font-size:0.7em;color:var(--secondary-text-color);opacity:0.5;margin-left:5px;vertical-align:middle;">PHY</span>`
      : "";

    // ETA: from eta_entity if configured, else compute from timeRemaining
    let etaDisplay = "";
    const etaEntity = this._config.eta_entity;
    if (etaEntity && this._hass.states[etaEntity]) {
      const etaState = this._hass.states[etaEntity].state;
      if (etaState && etaState !== "unavailable" && etaState !== "unknown") {
        try { etaDisplay = new Date(etaState).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); } catch (e) { /* ignore */ }
      }
    }
    if (!etaDisplay && timeRemaining != null) etaDisplay = etaFromMinutes(timeRemaining);

    // SVG ring values
    const timerMode = this._timerMode;
    let progress = 0;
    let centerPrimary = "—";
    let centerSecondary = "";

    if (timerMode === "tempup") {
      const cur = attrs.current_temp;
      const tgt = attrs.target_temp;
      progress = (cur != null && tgt > 0) ? Math.min(cur / tgt, 1) : 0;
      centerPrimary = cur != null ? `${cur}°C` : "—";
      centerSecondary = tgt ? `of ${tgt}°C` : "";
    } else {
      // countdown: ring fills as time elapses
      if (timeRemaining != null) {
        const elapsed = (attrs.readings_count || 0) * 0.5; // each reading ≈ 30 s
        const total = timeRemaining + elapsed;
        progress = total > 0 ? Math.max(0, Math.min(elapsed / total, 1)) : 0;
        centerPrimary = formatTime(timeRemaining);
        centerSecondary = "remaining";
      } else {
        // No estimate available yet (rate too low / no cached value)
        progress = 0;
        centerPrimary = "—";
        centerSecondary = "estimating…";
      }
    }

    // Pull-from-heat: alert when current temp ≥ calculated pull point AND
    // close to done (≤ 10 min remaining). Without the time guard, the alert
    // fires whenever the current temp coincidentally equals the pull temp —
    // which can happen 30+ minutes before the cook finishes.
    const pullTemp = attrs.pull_temp ?? null;
    const currentTemp = attrs.current_temp ?? null;
    const shouldPull = pullTemp != null && currentTemp != null
      && currentTemp >= pullTemp && phase !== "done"
      && (timeRemaining == null || timeRemaining <= 10);

    // Ring colour shifts to warning orange when it's time to pull
    const ringColor = shouldPull ? "var(--warning-color)" : phaseColor;

    const offset = (CIRC * (1 - progress)).toFixed(2);
    const timerIcon = timerMode === "countdown" ? "⏱" : "🌡";
    const nextMode = timerMode === "countdown" ? "tempup" : "countdown";
    const nextLabel = timerMode === "countdown" ? "Switch to temperature view" : "Switch to countdown view";
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
                       Remove from heat
                     </div>`
                  : combinedPresetName
                    ? `<div style="font-size:0.78em;color:var(--secondary-text-color);">
                         ${combinedPresetName}
                       </div>`
                    : ""}
              </div>
            </div>
            <div style="text-align:right;font-size:0.8em;color:var(--secondary-text-color);line-height:1.6;">
              <div>${attrs.target_temp || "?"}°C</div>
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
                ${timerMode === "countdown" ? "tap for temp" : "tap for time"}
              </text>
            </svg>
            ${etaDisplay ? `<div style="font-size:0.95em;color:var(--secondary-text-color);margin-top:2px;">Done ~${etaDisplay}</div>` : ""}
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
                  Remove from heat now!
                </div>
                <div style="font-size:0.8em;color:var(--secondary-text-color);margin-top:3px;">
                  Carryover cooking will bring it to ${attrs.target_temp}°C.
                  Pull temperature: ${pullTemp}°C.
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
                <div style="font-size:0.9em;font-weight:600;color:var(--error-color);">Temperature stall detected</div>
                <div style="font-size:0.78em;color:var(--secondary-text-color);margin-top:2px;">
                  Time shown is the last stable estimate. It will resume updating when the temperature starts rising again.
                </div>
              </div>
            </div>` : ""}

          <!-- Rate -->
          ${attrs.rate_c_per_minute != null
            ? `<div style="text-align:center;font-size:0.82em;color:var(--secondary-text-color);margin-top:8px;">
                Rate: ${attrs.rate_c_per_minute.toFixed(2)} °C/min
                ${phase === "stall" ? '<span style="color:var(--error-color);"> (stalled)</span>' : ""}
               </div>`
            : ""}

          <button id="cp-stop"
            style="width:100%;padding:10px;background:none;color:var(--error-color);
                   border:1px solid var(--error-color);border-radius:8px;
                   font-size:0.9em;cursor:pointer;margin-top:16px;">
            Stop Cook
          </button>
        </div>
      </ha-card>`;

    this.querySelector("#cp-ring-container").addEventListener("click", () => {
      localStorage.setItem("probe_ability_timer_mode", nextMode);
      this._render();
    });
    this._addStopConfirm(this.querySelector("#cp-stop"), () => this._callStop(), "Yes, cancel");
  }

  _renderActiveIndividual(state, attrs) {
    const probeCount = attrs.probe_count || this._cachedProbeCount;
    const probeActiveList = attrs.probe_active || Array(probeCount).fill(false);

    // Which probe indices have a working sensor right now (non-zero reading).
    // Used to suppress idle setup slots for probes that aren't plugged in.
    const availableSet = new Set(this._availableProbeIndices(probeCount));

    // Gather per-probe data — probes 2/3 use dedicated attrs written by sensor.py
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
      }[pd.phase] || "var(--primary-color)";
      const phaseIcon = {
        heating: "mdi:fire",
        stall: "mdi:pause-circle-outline",
        finishing: "mdi:flag-checkered",
        done: "mdi:check-circle",
      }[pd.phase] || "mdi:thermometer";

      let contentBlock = "";
      let actionBlock = "";

      if (!pd.active) {
        // ── Inactive: show setup form ──────────────────────────────────
        const idleState = this._slotState(i);
        contentBlock = `
          <div style="padding:8px 0 0;">
            <div id="cp-form-idle-${i}">
              ${_presetSelector(`idle-${i}`, idleState)}
              <div style="margin-top:4px;">
                <label style="display:block;font-size:0.8em;color:var(--secondary-text-color);margin-bottom:4px;">Target (°C)</label>
                ${tempInput(`cp-target-idle-${i}`, idleState.temp)}
              </div>
            </div>
          </div>`;
        actionBlock = `
          <button class="cp-start-idle-probe" data-index="${i}"
            style="width:100%;padding:8px;margin-top:8px;background:var(--primary-color);
                   color:var(--text-primary-color);border:none;border-radius:6px;
                   font-size:0.85em;font-weight:500;cursor:pointer;">
            Start Probe ${i + 1}
          </button>`;

      } else if (pd.phase === "collecting") {
        // ── Collecting: two-phase progress ────────────────────────────
        // Phase 1: accumulate 10 readings.
        // Phase 2: wait for the 10-minute data span (30 s/reading assumed).
        const NEEDED_READINGS = 10;
        const READING_INTERVAL_S = 30;
        const REQUIRED_SPAN_S = 600;
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
                Warming up… target <strong>${pd.targetTemp || "—"}°C</strong>
              </span>
            </div>

            ${!readingsDone ? `
              <div style="font-size:0.78em;color:var(--secondary-text-color);margin-bottom:4px;">
                Readings: ${displayCount}/${NEEDED_READINGS}
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
                Readings: ${NEEDED_READINGS}/${NEEDED_READINGS}
              </div>
              <div style="font-size:0.78em;color:var(--secondary-text-color);margin-bottom:4px;">
                Building data span…${readyAt ? ` ready at ${readyAt}` : ""}
              </div>
              <div style="background:var(--divider-color);border-radius:4px;height:6px;overflow:hidden;">
                <div style="background:var(--warning-color);height:100%;width:${spanPct}%;
                            border-radius:4px;transition:width 0.5s;"></div>
              </div>
            `}

            <div style="display:flex;justify-content:space-between;margin-top:8px;
                        font-size:0.8em;color:var(--secondary-text-color);">
              ${pd.currentTemp != null
                ? `<span>Internal: <strong>${pd.currentTemp}°C</strong></span>`
                : "<span></span>"}
              ${ambientTemp != null
                ? `<span>Ambient: <strong>${ambientTemp}°C</strong></span>`
                : ""}
            </div>
          </div>`;
        actionBlock = `
          <button class="cp-stop-probe" data-index="${i}"
            style="width:100%;padding:8px;background:none;color:var(--error-color);
                   border:1px solid var(--error-color);border-radius:6px;
                   font-size:0.8em;cursor:pointer;margin-top:6px;">
            Cancel Probe ${i + 1}
          </button>`;

      } else if (pd.phase === "done") {
        // ── Done ──────────────────────────────────────────────────────
        contentBlock = `
          <div style="text-align:center;padding:12px 0 4px;">
            <ha-icon icon="mdi:check-circle"
              style="color:var(--success-color);--mdc-icon-size:40px;"></ha-icon>
            <div style="font-size:0.9em;font-weight:600;color:var(--success-color);margin-top:4px;">
              Target reached!
            </div>
            ${pd.currentTemp != null
              ? `<div style="font-size:0.8em;color:var(--secondary-text-color);">${pd.currentTemp}°C</div>`
              : ""}
          </div>`;
        actionBlock = `
          <button class="cp-stop-probe" data-index="${i}"
            style="width:100%;padding:8px;background:var(--primary-color);
                   color:var(--text-primary-color);border:none;border-radius:6px;
                   font-size:0.8em;font-weight:500;cursor:pointer;margin-top:4px;">
            New Cook (Probe ${i + 1})
          </button>`;

      } else {
        // ── Active: ring + info rows ───────────────────────────────────
        const shouldPull = pd.pullTemp != null
          && pd.currentTemp != null
          && pd.currentTemp >= pd.pullTemp
          && pd.phase !== "done"
          && (pd.timeRemaining == null || pd.timeRemaining <= 10);

        // Countdown ring — always shows time remaining in individual mode
        let progress = 0;
        let centerPrimary = "—";
        let centerSecondary = "estimating…";
        if (pd.timeRemaining) {
          const elapsed = pd.readingsCount * 0.5;
          const total = pd.timeRemaining + elapsed;
          progress = total > 0 ? Math.min(elapsed / total, 1) : 0;
          centerPrimary = formatTime(pd.timeRemaining);
          centerSecondary = "remaining";
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
                <span><strong style="color:var(--primary-text-color);">${pd.currentTemp}°C</strong></span>
                <span>${pd.targetTemp}°C</span>
              </div>
              <div style="background:var(--divider-color);border-radius:4px;height:5px;overflow:hidden;">
                <div style="background:${ringColor};height:100%;width:${tempPct}%;
                            border-radius:4px;transition:width 1s ease;"></div>
              </div>
            </div>` : ""}

          <div style="display:flex;justify-content:space-between;margin-top:8px;
                      font-size:0.78em;color:var(--secondary-text-color);">
            <span>${pd.ratePerMinute != null
              ? `Rate: ${pd.ratePerMinute.toFixed(2)}°C/min`
              : ""}</span>
            <span>${eta ? `ETA: ${eta}` : ""}</span>
          </div>
          ${ambientTemp != null ? `
            <div style="font-size:0.78em;color:var(--secondary-text-color);margin-top:2px;">
              Ambient: ${ambientTemp}°C
            </div>` : ""}

          ${shouldPull ? `
            <div style="display:flex;align-items:center;gap:8px;padding:8px 10px;margin-top:8px;
                        background:rgba(255,152,0,0.15);
                        border:2px solid var(--warning-color);border-radius:10px;">
              <ha-icon icon="mdi:fire-off"
                style="color:var(--warning-color);--mdc-icon-size:22px;flex-shrink:0;"></ha-icon>
              <div>
                <div style="font-size:0.85em;font-weight:700;color:var(--warning-color);">
                  Remove from heat now!
                </div>
                <div style="font-size:0.73em;color:var(--secondary-text-color);margin-top:1px;">
                  Carryover will bring it to ${pd.targetTemp}°C. Pull temp: ${pd.pullTemp}°C.
                </div>
              </div>
            </div>` : ""}
          ${pd.phase === "stall" && !shouldPull ? `
            <div style="display:flex;align-items:center;gap:6px;padding:5px 8px;margin-top:6px;
                        background:rgba(var(--rgb-error-color,244,67,54),0.1);
                        border:1px solid var(--error-color);border-radius:8px;font-size:0.76em;">
              <ha-icon icon="mdi:pause-circle"
                style="color:var(--error-color);--mdc-icon-size:16px;flex-shrink:0;"></ha-icon>
              <span style="color:var(--error-color);">Stall — showing last stable estimate</span>
            </div>` : ""}`;

        actionBlock = `
          <button class="cp-stop-probe" data-index="${i}"
            style="width:100%;padding:8px;background:none;color:var(--error-color);
                   border:1px solid var(--error-color);border-radius:6px;
                   font-size:0.8em;cursor:pointer;margin-top:8px;">
            Stop Probe ${i + 1}
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

      probeSlots += `
        <div style="border:1px solid var(--divider-color);border-radius:10px;
                    padding:12px;margin-bottom:10px;">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:4px;">
            <div style="font-size:0.9em;font-weight:600;
                        color:${pd.active ? phaseColor : "var(--secondary-text-color)"};">
              Probe ${i + 1}
              ${showPhaseDetail
                ? `<ha-icon icon="${phaseIcon}"
                     style="--mdc-icon-size:16px;vertical-align:middle;margin-left:4px;"></ha-icon>`
                : ""}
            </div>
            <div style="font-size:0.75em;color:var(--secondary-text-color);text-align:right;line-height:1.6;">
              ${pd.active
                ? `${probePresetName
                     ? `<div style="font-weight:500;color:var(--primary-text-color);">${probePresetName}</div>`
                     : ""}
                   <div>${pd.targetTemp || "?"}°C${showPhaseDetail && confDots
                     ? `<span style="margin-left:6px;letter-spacing:2px;">${confDots}</span>${indivModelBadge}`
                     : ""}</div>`
                : `<div>Not started</div>`}
            </div>
          </div>
          ${contentBlock}
          ${actionBlock}
        </div>`;
    }

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
                         border-radius:10px;">Individual</span>
          </div>
          ${probeSlots}
        </div>
      </ha-card>`;

    // Stop / cancel buttons — each gets its own confirmation prompt
    this.querySelectorAll(".cp-stop-probe").forEach((btn) => {
      const idx = parseInt(btn.dataset.index, 10);
      const pd = probeData[idx];
      const label = pd.phase === "collecting" ? "Yes, cancel"
                  : pd.phase === "done"       ? "Yes, new cook"
                  :                             "Yes, stop";
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
        this._callStart({ target_temp: s.temp, probe_mode: "individual", probe_index: i, cook_name: cookName });
      });
    });
  }

  // ── Done ──────────────────────────────────────────────────────────────

  _renderDone(attrs) {
    this.innerHTML = `
      <ha-card>
        <div style="padding:20px;">
          <div style="text-align:center;padding:24px 0;">
            <ha-icon icon="mdi:check-circle"
              style="color:var(--success-color);--mdc-icon-size:64px;margin-bottom:12px;"></ha-icon>
            <div style="font-size:1.4em;font-weight:600;margin-bottom:4px;">Cook Complete!</div>
            <div style="font-size:1em;color:var(--success-color);">Target temperature reached.</div>
          </div>
          ${this._renderTempsRow(attrs)}
          <button id="cp-stop"
            style="width:100%;padding:12px;background:var(--primary-color);
                   color:var(--text-primary-color);border:none;border-radius:8px;
                   font-size:1em;font-weight:500;cursor:pointer;margin-top:16px;">
            New Cook
          </button>
        </div>
      </ha-card>`;

    this._addStopConfirm(this.querySelector("#cp-stop"), () => this._callStop(), "Yes, cancel");
  }

  // ── Temperature display ───────────────────────────────────────────────

  _renderTempsRow(attrs) {
    const temps = [];

    if (attrs.current_temp != null) {
      temps.push({ label: attrs.probe_count > 1 ? "Probe 1" : "Internal", value: attrs.current_temp });
    }
    if (attrs.current_temp_2 != null) {
      temps.push({ label: "Probe 2", value: attrs.current_temp_2 });
    }
    if (attrs.current_temp_3 != null) {
      temps.push({ label: "Probe 3", value: attrs.current_temp_3 });
    }
    if (attrs.ambient_temp != null) {
      temps.push({ label: "Ambient", value: attrs.ambient_temp });
    }

    if (temps.length === 0) return "";

    const cells = temps.map(
      (t) => `
        <div style="text-align:center;">
          <div style="font-size:0.75em;color:var(--secondary-text-color);">${t.label}</div>
          <div style="font-size:1.3em;font-weight:600;">${t.value}°C</div>
        </div>`
    ).join("");

    return `<div style="display:flex;justify-content:center;gap:24px;padding:10px 0;">${cells}</div>`;
  }

  // ── Stop confirmation ─────────────────────────────────────────────────

  // Replaces `btn` with an inline "Are you sure?" prompt.
  // Confirming calls stopFn(); denying restores the original button.
  // If HA pushes a state update while the prompt is open it will be wiped
  // by the re-render — the user simply clicks Stop again.
  _addStopConfirm(btn, stopFn, confirmLabel = "Yes, stop") {
    btn.addEventListener("click", () => {
      const wrapper = document.createElement("div");
      wrapper.style.cssText = "margin-top:4px;";
      wrapper.innerHTML = `
        <div style="font-size:0.82em;color:var(--error-color);text-align:center;margin-bottom:6px;font-weight:500;">
          Are you sure?
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
            Keep cooking
          </button>
        </div>`;
      btn.replaceWith(wrapper);
      wrapper.querySelector(".cp-confirm-yes").addEventListener("click", stopFn);
      wrapper.querySelector(".cp-confirm-no").addEventListener("click", () => wrapper.replaceWith(btn));
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
    return 5;
  }

  static getConfigElement() {
    return document.createElement("probe-ability-card-editor");
  }

  static getStubConfig() {
    return { entity: "", eta_entity: "", probe_sensors: [] };
  }
}

// ─── Visual editor ─────────────────────────────────────────────────────────────

class CookPredictorCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
  }

  _render() {
    this.innerHTML = `
      <div style="padding:16px;">
        <div style="margin-bottom:12px;">
          <label style="display:block;margin-bottom:4px;font-size:0.9em;">Time Remaining Entity</label>
          <input id="entity" value="${this._config.entity || ""}"
            placeholder="sensor.probe_ability_time_remaining"
            style="width:100%;box-sizing:border-box;padding:8px;border:1px solid var(--divider-color);border-radius:4px;" />
        </div>
        <div style="margin-bottom:12px;">
          <label style="display:block;margin-bottom:4px;font-size:0.9em;">ETA Entity (optional — auto-computed if omitted)</label>
          <input id="eta_entity" value="${this._config.eta_entity || ""}"
            placeholder="sensor.probe_ability_estimated_completion"
            style="width:100%;box-sizing:border-box;padding:8px;border:1px solid var(--divider-color);border-radius:4px;" />
        </div>
        <div>
          <label style="display:block;margin-bottom:4px;font-size:0.9em;">Entry ID (optional, for multi-instance)</label>
          <input id="entry_id" value="${this._config.entry_id || ""}"
            placeholder="Leave empty for single instance"
            style="width:100%;box-sizing:border-box;padding:8px;border:1px solid var(--divider-color);border-radius:4px;" />
        </div>
      </div>`;

    ["entity", "eta_entity", "entry_id"].forEach((field) => {
      this.querySelector(`#${field}`).addEventListener("change", (e) => {
        const newConfig = { ...this._config, [field]: e.target.value };
        if (!newConfig[field]) delete newConfig[field];
        this._config = newConfig;
        this.dispatchEvent(
          new CustomEvent("config-changed", {
            detail: { config: this._config },
            bubbles: true,
            composed: true,
          })
        );
      });
    });
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
