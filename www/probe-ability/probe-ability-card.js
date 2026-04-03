/**
 * Probe-ability Card
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

const PRESETS = [
  { name: "Beef (Medium Rare)", temp: 54 },
  { name: "Beef (Medium)", temp: 60 },
  { name: "Beef (Well Done)", temp: 71 },
  { name: "Pork", temp: 63 },
  { name: "Chicken / Poultry", temp: 74 },
  { name: "Lamb (Medium Rare)", temp: 54 },
  { name: "Lamb (Medium)", temp: 63 },
  { name: "Brisket", temp: 96 },
  { name: "Pulled Pork", temp: 96 },
];

// SVG ring constants (r=50, cx=cy=60)
const CIRC = 314.16; // 2π × 50

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

// selectedIndex: the PRESETS array index of the chosen preset, or null for
// "no preset selected / custom temp".  Using the index (not the temp) as the
// option value avoids collisions between presets that share a temperature
// (e.g. Beef Medium Rare and Lamb Medium Rare are both 54 °C).
function presetDropdown(idSuffix, selectedIndex) {
  const opts = PRESETS.map(
    (p, idx) =>
      `<option value="${idx}"${idx === selectedIndex ? " selected" : ""}>${p.name} (${p.temp}°C)</option>`
  ).join("");
  return `
    <select id="cp-preset-${idSuffix}"
      style="width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid var(--divider-color);
             border-radius:8px;font-size:0.95em;background:var(--card-background-color);
             color:var(--primary-text-color);cursor:pointer;">
      <option value="">— Select preset —</option>
      ${opts}
    </select>`;
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
    // Per-slot form state: { presetIndex: number|null, temp: number }
    // Key: "combined" or probe index 0/1/2.
    // Backed by localStorage so selections survive page navigation.
    try {
      this._idleState = JSON.parse(localStorage.getItem("probe_ability_idle_state") || "{}");
      // Sanitise: ensure every stored temp is a real number, not null/NaN
      for (const key of Object.keys(this._idleState)) {
        const s = this._idleState[key];
        if (!s || typeof s.temp !== "number" || isNaN(s.temp)) {
          delete this._idleState[key];
        }
      }
    } catch (e) {
      this._idleState = {};
    }
  }

  set hass(hass) {
    this._hass = hass;
    // Snapshot the currently-displayed form before rebuilding HTML
    this._saveIdleFormState();
    this._render();
  }

  _saveIdleFormState() {
    const save = (key, presetEl, targetEl) => {
      if (!targetEl) return;
      const raw = presetEl ? presetEl.value : "";
      const presetIndex = raw !== "" ? parseInt(raw, 10) : null;
      const temp = parseFloat(targetEl.value) || 74;
      this._idleState[key] = { presetIndex, temp };
    };
    save("combined",
      this.querySelector("#cp-preset-combined"),
      this.querySelector("#cp-target-combined"));
    for (let i = 0; i < 3; i++) {
      save(i,
        this.querySelector(`#cp-preset-${i}`),
        this.querySelector(`#cp-target-${i}`));
    }
    this._persistIdleState();
  }

  // Returns { presetIndex, temp } for a slot, defaulting to no preset / 74 °C.
  _slotState(key) {
    return this._idleState[key] || { presetIndex: null, temp: 74 };
  }

  _persistIdleState() {
    try {
      localStorage.setItem("probe_ability_idle_state", JSON.stringify(this._idleState));
    } catch (e) { /* ignore quota errors */ }
  }

  // Persist the preset name that was active when a cook was started.
  // Key: "combined" or probe index 0/1/2.
  _saveActivePreset(key, presetIndex) {
    try {
      const store = JSON.parse(localStorage.getItem("probe_ability_active_presets") || "{}");
      if (presetIndex != null && PRESETS[presetIndex]) {
        store[String(key)] = presetIndex;
      } else {
        delete store[String(key)];
      }
      localStorage.setItem("probe_ability_active_presets", JSON.stringify(store));
    } catch (e) {}
  }

  // Returns the preset name for a running cook slot, or null for custom temp.
  _getActivePresetName(key) {
    try {
      const store = JSON.parse(localStorage.getItem("probe_ability_active_presets") || "{}");
      const idx = store[String(key)];
      return (idx != null && PRESETS[idx]) ? PRESETS[idx].name : null;
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
               && !isNaN(parseFloat(s.state));
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
    // attrs.probe_count is absent when entity is unavailable; fall back to cache
    const probeCount = attrs.probe_count || this._cachedProbeCount;
    const available = this._availableProbeIndices(probeCount);

    // No sensors at all → inform the user, no start button
    if (available.length === 0) {
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
            <ha-icon icon="mdi:thermometer" style="color:var(--primary-color);--mdc-icon-size:28px;"></ha-icon>
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
            <ha-icon icon="mdi:thermometer" style="color:var(--primary-color);--mdc-icon-size:28px;"></ha-icon>
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
    const { presetIndex, temp } = this._slotState(probeIndex);
    this.innerHTML = `
      <ha-card>
        <div style="padding:20px;">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:20px;">
            <ha-icon icon="mdi:thermometer" style="color:var(--primary-color);--mdc-icon-size:28px;"></ha-icon>
            <span style="font-size:1.3em;font-weight:500;">Probe-ability</span>
          </div>
          <div>
            <label style="display:block;font-size:0.85em;color:var(--secondary-text-color);margin-bottom:4px;">Quick preset</label>
            ${presetDropdown(`sp-${probeIndex}`, presetIndex)}
            <div style="margin-top:12px;">
              <label style="display:block;font-size:0.85em;color:var(--secondary-text-color);margin-bottom:4px;">Target temperature (°C)</label>
              ${tempInput(`cp-target-sp-${probeIndex}`, temp)}
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

    const presetEl = this.querySelector(`#cp-preset-sp-${probeIndex}`);
    const targetEl = this.querySelector(`#cp-target-sp-${probeIndex}`);
    if (presetEl) {
      presetEl.addEventListener("change", (e) => {
        const idx = e.target.value !== "" ? parseInt(e.target.value, 10) : null;
        if (idx !== null) {
          const t = PRESETS[idx].temp;
          if (targetEl) targetEl.value = t;
          this._idleState[probeIndex] = { presetIndex: idx, temp: t };
        } else {
          this._idleState[probeIndex] = { presetIndex: null, temp: parseFloat(targetEl?.value) || 74 };
        }
        this._persistIdleState();
      });
    }
    if (targetEl) {
      targetEl.addEventListener("input", (e) => {
        const current = this._idleState[probeIndex] || {};
        this._idleState[probeIndex] = { presetIndex: current.presetIndex ?? null, temp: parseFloat(e.target.value) || 74 };
        this._persistIdleState();
      });
    }
    const startBtn = this.querySelector("#cp-start-single");
    if (startBtn) {
      startBtn.addEventListener("click", () => {
        const target = parseFloat(targetEl ? targetEl.value : "74") || 74;
        const presetIdx = presetEl && presetEl.value !== "" ? parseInt(presetEl.value, 10) : null;
        this._saveActivePreset(probeIndex, presetIdx);
        this._callStart({ target_temp: target, probe_mode: "individual", probe_index: probeIndex });
      });
    }
  }

  _idleCombinedForm() {
    const { presetIndex, temp } = this._slotState("combined");
    return `
      <div>
        <label style="display:block;font-size:0.85em;color:var(--secondary-text-color);margin-bottom:4px;">Quick preset</label>
        ${presetDropdown("combined", presetIndex)}
        <div style="margin-top:12px;">
          <label style="display:block;font-size:0.85em;color:var(--secondary-text-color);margin-bottom:4px;">Target temperature (°C)</label>
          ${tempInput("cp-target-combined", temp)}
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
    // available: array of probe indices (0-based) that are currently reachable
    const probeLabels = ["Probe 1", "Probe 2", "Probe 3"];
    let html = "";
    for (const i of available) {
      const { presetIndex, temp } = this._slotState(i);
      html += `
        <div style="border:1px solid var(--divider-color);border-radius:10px;padding:14px;margin-bottom:12px;">
          <div style="font-size:0.9em;font-weight:600;margin-bottom:10px;color:var(--primary-color);">
            ${probeLabels[i] || `Probe ${i + 1}`}
          </div>
          <label style="display:block;font-size:0.8em;color:var(--secondary-text-color);margin-bottom:4px;">Quick preset</label>
          ${presetDropdown(i, presetIndex)}
          <div style="margin-top:10px;">
            <label style="display:block;font-size:0.8em;color:var(--secondary-text-color);margin-bottom:4px;">Target (°C)</label>
            ${tempInput(`cp-target-${i}`, temp)}
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

  _wireIdleCombined() {
    const presetEl = this.querySelector("#cp-preset-combined");
    const targetEl = this.querySelector("#cp-target-combined");
    if (presetEl) {
      presetEl.addEventListener("change", (e) => {
        const idx = e.target.value !== "" ? parseInt(e.target.value, 10) : null;
        if (idx !== null) {
          const temp = PRESETS[idx].temp;
          if (targetEl) targetEl.value = temp;
          this._idleState["combined"] = { presetIndex: idx, temp };
        } else {
          this._idleState["combined"] = { presetIndex: null, temp: parseFloat(targetEl?.value) || 74 };
        }
        this._persistIdleState();
      });
    }
    if (targetEl) {
      targetEl.addEventListener("input", (e) => {
        const current = this._idleState["combined"] || {};
        this._idleState["combined"] = { presetIndex: current.presetIndex ?? null, temp: parseFloat(e.target.value) || 74 };
        this._persistIdleState();
      });
    }
    const startBtn = this.querySelector("#cp-start-combined");
    if (startBtn) {
      startBtn.addEventListener("click", () => {
        const target = parseFloat(targetEl ? targetEl.value : "74") || 74;
        const presetIdx = presetEl && presetEl.value !== "" ? parseInt(presetEl.value, 10) : null;
        this._saveActivePreset("combined", presetIdx);
        this._callStart({ target_temp: target, probe_mode: "combined" });
      });
    }
  }

  _wireIdleProbeSlot(i) {
    const presetEl = this.querySelector(`#cp-preset-${i}`);
    const targetEl = this.querySelector(`#cp-target-${i}`);
    if (presetEl) {
      presetEl.addEventListener("change", (e) => {
        const idx = e.target.value !== "" ? parseInt(e.target.value, 10) : null;
        if (idx !== null) {
          const temp = PRESETS[idx].temp;
          if (targetEl) targetEl.value = temp;
          this._idleState[i] = { presetIndex: idx, temp };
        } else {
          this._idleState[i] = { presetIndex: null, temp: parseFloat(targetEl?.value) || 74 };
        }
        this._persistIdleState();
      });
    }
    if (targetEl) {
      targetEl.addEventListener("input", (e) => {
        const current = this._idleState[i] || {};
        this._idleState[i] = { presetIndex: current.presetIndex ?? null, temp: parseFloat(e.target.value) || 74 };
        this._persistIdleState();
      });
    }
    const startBtn = this.querySelector(`#cp-start-${i}`);
    if (startBtn) {
      startBtn.addEventListener("click", () => {
        const target = parseFloat(targetEl ? targetEl.value : 74);
        const presetIdx = presetEl && presetEl.value !== "" ? parseInt(presetEl.value, 10) : null;
        this._saveActivePreset(i, presetIdx);
        this._callStart({ target_temp: target, probe_mode: "individual", probe_index: i });
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
            <ha-icon icon="mdi:thermometer" style="color:var(--warning-color);--mdc-icon-size:28px;"></ha-icon>
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

    // Pull-from-heat: alert when current temp ≥ calculated pull point
    const pullTemp = attrs.pull_temp ?? null;
    const currentTemp = attrs.current_temp ?? null;
    const shouldPull = pullTemp != null && currentTemp != null
      && currentTemp >= pullTemp && phase !== "done";

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
                ? `<div style="letter-spacing:2px;">${confDots}</div>`
                : ""}
            </div>
          </div>

          <!-- SVG circular timer -->
          <div style="position:relative;display:flex;flex-direction:column;align-items:center;padding:4px 0 8px;">
            <button id="cp-timer-mode"
              title="${nextLabel}"
              style="position:absolute;top:0;right:0;background:none;border:none;cursor:pointer;
                     font-size:1.2em;padding:4px;color:var(--secondary-text-color);">
              ${timerIcon}
            </button>
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

    this.querySelector("#cp-timer-mode").addEventListener("click", () => {
      localStorage.setItem("probe_ability_timer_mode", nextMode);
      this._render();
    });
    this._addStopConfirm(this.querySelector("#cp-stop"), () => this._callStop(), "Yes, cancel");
  }

  _renderActiveIndividual(state, attrs) {
    const probeCount = attrs.probe_count || this._cachedProbeCount;
    const probeActiveList = attrs.probe_active || Array(probeCount).fill(false);
    const timerMode = this._timerMode;
    const timerIcon = timerMode === "countdown" ? "⏱" : "🌡";
    const nextMode = timerMode === "countdown" ? "tempup" : "countdown";

    // Gather per-probe data — probes 2/3 use dedicated attrs written by sensor.py
    const probeData = [];
    for (let i = 0; i < probeCount; i++) {
      const n = i + 1; // human-readable probe number
      if (i === 0) {
        probeData.push({
          active: probeActiveList[0],
          currentTemp: attrs.current_temp,
          targetTemp: attrs.target_temp,
          phase: attrs.phase || "collecting",
          confidence: attrs.confidence || "low",
          timeRemaining: parseFloat(state.state) || null,
          readingsCount: attrs.readings_count || 0,
          pullTemp: attrs.pull_temp ?? null,
        });
      } else {
        probeData.push({
          active: attrs[`probe_${n}_active`] || false,
          currentTemp: attrs[`current_temp_${n}`],
          targetTemp: attrs[`target_temp_${n}`],
          phase: attrs[`probe_${n}_phase`] || "collecting",
          confidence: attrs[`probe_${n}_confidence`] || "low",
          timeRemaining: attrs[`probe_${n}_time_remaining`] || null,
          readingsCount: attrs[`probe_${n}_readings_count`] || 0,
          pullTemp: attrs[`probe_${n}_pull_temp`] ?? null,
        });
      }
    }

    let probeSlots = "";
    for (let i = 0; i < probeCount; i++) {
      const pd = probeData[i];
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
        const { presetIndex: idlePresetIdx, temp: idleTemp } = this._slotState(i);
        contentBlock = `
          <div style="padding:8px 0 0;">
            <label style="display:block;font-size:0.8em;color:var(--secondary-text-color);margin-bottom:4px;">Quick preset</label>
            ${presetDropdown(`idle-${i}`, idlePresetIdx)}
            <div style="margin-top:8px;">
              <label style="display:block;font-size:0.8em;color:var(--secondary-text-color);margin-bottom:4px;">Target (°C)</label>
              ${tempInput(`cp-idle-target-${i}`, idleTemp)}
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
        // ── Collecting: progress bar ───────────────────────────────────
        const needed = 10;
        const count = pd.readingsCount;
        const displayCount = Math.min(count, needed);
        const pct = Math.min((count / needed) * 100, 100);
        contentBlock = `
          <div style="padding:10px 0 4px;">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
              <ha-icon icon="mdi:timer-sand" style="color:var(--warning-color);--mdc-icon-size:22px;flex-shrink:0;"></ha-icon>
              <span style="font-size:0.85em;color:var(--secondary-text-color);">
                Warming up… target <strong>${pd.targetTemp || "—"}°C</strong>
              </span>
            </div>
            <div style="font-size:0.78em;color:var(--secondary-text-color);margin-bottom:6px;">
              Collecting data (${displayCount}/${needed} readings)
            </div>
            <div style="background:var(--divider-color);border-radius:4px;height:6px;overflow:hidden;">
              <div style="background:var(--warning-color);height:100%;width:${pct}%;
                          border-radius:4px;transition:width 0.5s;"></div>
            </div>
            ${pd.currentTemp != null
              ? `<div style="font-size:0.8em;color:var(--secondary-text-color);margin-top:6px;">
                   Current: ${pd.currentTemp}°C
                 </div>`
              : ""}
          </div>`;
        actionBlock = `
          <button class="cp-stop-probe" data-index="${i}"
            style="width:100%;padding:8px;background:none;color:var(--error-color);
                   border:1px solid var(--error-color);border-radius:6px;
                   font-size:0.8em;cursor:pointer;margin-top:4px;">
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
        // ── Active: SVG ring (heating / stall / finishing) ─────────────
        let progress = 0;
        let centerPrimary = "—";
        let centerSecondary = "";

        if (timerMode === "tempup") {
          // Temperature-up mode: ring fills as temp rises toward target
          progress = (pd.currentTemp != null && pd.targetTemp > 0)
            ? Math.min(pd.currentTemp / pd.targetTemp, 1) : 0;
          centerPrimary = pd.currentTemp != null ? `${pd.currentTemp}°C` : "—";
          centerSecondary = pd.targetTemp ? `of ${pd.targetTemp}°C` : "";
        } else {
          // Countdown mode: show time remaining.
          // If no estimate yet, show "—" (NOT temperature — that keeps modes visually distinct).
          if (pd.timeRemaining) {
            const elapsed = pd.readingsCount * 0.5;
            const total = pd.timeRemaining + elapsed;
            progress = total > 0 ? Math.min(elapsed / total, 1) : 0;
            centerPrimary = formatTime(pd.timeRemaining);
            centerSecondary = "remaining";
          } else {
            // No time estimate yet — leave ring empty and show a dash
            progress = 0;
            centerPrimary = "—";
            centerSecondary = "estimating…";
          }
        }

        // "Remove from heat" warning: current temp has reached the pull point
        const shouldPull = pd.pullTemp != null
          && pd.currentTemp != null
          && pd.currentTemp >= pd.pullTemp
          && pd.phase !== "done";

        const offset = (CIRC * (1 - progress)).toFixed(2);
        const ringColor = shouldPull ? "var(--warning-color)" : phaseColor;

        contentBlock = `
          <svg viewBox="0 0 120 120" width="110" height="110"
               style="display:block;margin:8px auto 0;">
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
          ${shouldPull ? `
            <div style="display:flex;align-items:center;gap:8px;padding:10px 12px;margin-top:8px;
                        background:rgba(255,152,0,0.15);
                        border:2px solid var(--warning-color);border-radius:10px;">
              <ha-icon icon="mdi:fire-off"
                style="color:var(--warning-color);--mdc-icon-size:26px;flex-shrink:0;"></ha-icon>
              <div>
                <div style="font-size:0.88em;font-weight:700;color:var(--warning-color);">
                  Remove from heat now!
                </div>
                <div style="font-size:0.75em;color:var(--secondary-text-color);margin-top:2px;">
                  Carryover cooking will bring it to ${pd.targetTemp}°C.
                  Pull temp: ${pd.pullTemp}°C.
                </div>
              </div>
            </div>` : ""}
          ${pd.phase === "stall" && !shouldPull ? `
            <div style="display:flex;align-items:center;gap:6px;padding:6px 10px;margin-top:6px;
                        background:rgba(var(--rgb-error-color,244,67,54),0.1);
                        border:1px solid var(--error-color);border-radius:8px;font-size:0.78em;">
              <ha-icon icon="mdi:pause-circle"
                style="color:var(--error-color);--mdc-icon-size:18px;flex-shrink:0;"></ha-icon>
              <span style="color:var(--error-color);">
                Stall detected — showing last stable estimate
              </span>
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
      const showPhaseDetail = pd.active
        && pd.phase !== "collecting"
        && pd.phase !== "done";
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
                     ? `<span style="margin-left:6px;letter-spacing:2px;">${confDots}</span>`
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
              <ha-icon icon="mdi:thermometer"
                style="color:var(--primary-color);--mdc-icon-size:26px;"></ha-icon>
              <span style="font-size:1.2em;font-weight:500;">Probe-ability</span>
            </div>
            <div style="display:flex;align-items:center;gap:8px;">
              <button id="cp-timer-mode"
                title="Switch timer display mode"
                style="background:none;border:none;cursor:pointer;font-size:1.2em;
                       padding:4px;color:var(--secondary-text-color);">${timerIcon}</button>
              <span style="font-size:0.75em;color:var(--secondary-text-color);
                           background:var(--divider-color);padding:2px 8px;
                           border-radius:10px;">Individual</span>
            </div>
          </div>
          ${probeSlots}
        </div>
      </ha-card>`;

    // Timer mode toggle
    this.querySelector("#cp-timer-mode").addEventListener("click", () => {
      localStorage.setItem("probe_ability_timer_mode", nextMode);
      this._render();
    });

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
      const presetEl = this.querySelector(`#cp-preset-idle-${i}`);
      const targetEl = this.querySelector(`#cp-idle-target-${i}`);
      if (presetEl) {
        presetEl.addEventListener("change", (e) => {
          const idx = e.target.value !== "" ? parseInt(e.target.value, 10) : null;
          if (idx !== null) {
            const temp = PRESETS[idx].temp;
            if (targetEl) targetEl.value = temp;
            this._idleState[i] = { presetIndex: idx, temp };
          } else {
            this._idleState[i] = { presetIndex: null, temp: parseFloat(targetEl?.value) || 74 };
          }
          this._persistIdleState();
        });
      }
      if (targetEl) {
        targetEl.addEventListener("input", (e) => {
          const current = this._idleState[i] || {};
          this._idleState[i] = {
            presetIndex: current.presetIndex ?? null,
            temp: parseFloat(e.target.value) || 74,
          };
          this._persistIdleState();
        });
      }
      btn.addEventListener("click", () => {
        const target = parseFloat(targetEl ? targetEl.value : "74") || 74;
        const presetIdx = presetEl && presetEl.value !== "" ? parseInt(presetEl.value, 10) : null;
        this._saveActivePreset(i, presetIdx);
        this._callStart({ target_temp: target, probe_mode: "individual", probe_index: i });
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
});
