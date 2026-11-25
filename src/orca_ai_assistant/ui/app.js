/* Orca AI Assistant v3.0 — Frontend State, Streaming, Dock UX & Wizards */

const I18N = (typeof window !== "undefined" && window.__LOCALES__) || { ru: {}, uk: {}, en: {} };

const DEFECT_ITEMS = [
  { id: "stringing", icon: "🕸" },
  { id: "warping", icon: "📐" },
  { id: "layer_shift", icon: "🔀" },
  { id: "under_extrusion", icon: "🕳" },
  { id: "overhang_curling", icon: "🌊" },
  { id: "z_banding", icon: "〰" },
  { id: "elephants_foot", icon: "🐘" },
  { id: "bed_adhesion", icon: "🧲" },
  { id: "support_scarring", icon: "🩹" },
  { id: "seam_blobs", icon: "💧" },
  { id: "heat_creep", icon: "🌡" },
  { id: "poor_top_surface", icon: "🧱" }
];

const CALIBRATION_STAGES = [
  { id: "temp_tower", i18n: "cal_st_temp_tower" },
  { id: "max_volumetric_speed", i18n: "cal_st_max_volumetric_speed" },
  { id: "pressure_advance", i18n: "cal_st_pressure_advance" },
  { id: "flow_rate", i18n: "cal_st_flow_rate" },
  { id: "retraction", i18n: "cal_st_retraction" }
];

const SLASH_COMMANDS = [
  { cmd: "/context", descKey: "slash_context" },
  { cmd: "/gcode", descKey: "slash_gcode" },
  { cmd: "/undo", descKey: "slash_undo" },
  { cmd: "/debug", descKey: "slash_debug" },
  { cmd: "/clear", descKey: "slash_clear" }
];

const GCODE_TABS = [
  { id: "start", i18n: "gcode_tab_start", keys: ["machine_start_gcode", "file_start_gcode"] },
  { id: "end", i18n: "gcode_tab_end", keys: ["machine_end_gcode"] },
  { id: "layer", i18n: "gcode_tab_layer", keys: ["before_layer_change_gcode", "layer_change_gcode"] },
  { id: "filament", i18n: "gcode_tab_filament", keys: ["filament_start_gcode", "filament_end_gcode", "change_filament_gcode", "filament_change_extrusion_role_gcode"] },
  { id: "other", i18n: "gcode_tab_other", keys: ["machine_pause_gcode", "time_lapse_gcode", "printing_by_object_gcode", "template_custom_gcode", "change_extrusion_role_gcode", "process_change_extrusion_role_gcode"] }
];

const STATE = {
  providers: {},
  settings: {
    language: "ru",
    provider: "anthropic",
    model: "",
    temperature: 0.3,
    max_tokens: 4096,
    reasoning_effort: "low",
    auto_attach_context: true,
    compact_context: true,
    include_custom_gcode: false,
    preflight_notifications: true,
    enable_slicing_audit: false,
    custom_user_instructions: "",
    api_keys: {},
    model_api_keys: {},
    base_urls: {},
    custom_protocol: "openai",
    favorite_models: [],
    cached_models: {},
    mcp_enabled: false,
    mcp_port: 18765,
    mcp_require_auth: true,
    mcp_token: "",
    mcp_allow_write: true,
    mcp_allow_gcode_write: true
  },
  mcp: null,
  chats: { active_id: "", sessions: [] },
  plate: { has_model: false, objects: [], warnings: [] },
  presets: { groups: {}, flat_values: {}, filament_slots: [], custom_gcode: {}, dirty_diff: [] },
  preflight: { score: 100, status: "ok", counts: { danger: 0, warn: 0, ok: 0 }, checks: [] },
  last_slice: null,
  slice_delta: null,
  snapshots: [],
  apply_history: [],
  usage: {
    month: { msgs: 0, input_tokens: 0, output_tokens: 0 },
    total: { msgs: 0, input_tokens: 0, output_tokens: 0 }
  },
  busy: false
};

let ACTIVE_REQUEST_ID = null;
let ACTIVE_STREAM_CHAT_ID = null;
let ACTIVE_TAB = "chat";
let ACTIVE_WIZARD_SUB = "defect";
let SELECTED_DEFECT_ID = "";
let ACTIVE_CAL_STAGE = "temp_tower";
let ACTIVE_GCODE_TAB = "start";
let LAST_CAL_RESULT = null;
let ATTACHED_IMAGE = null;
let DEFECT_IMAGE = null;
let LAST_SUGGESTIONS_MAP = {};
let LAST_GCODE_MAP = {};
let APPLIED_CARD_RECORDS = {};
let PENDING_APPLY_CARD_ID = null;
let STREAM_THINKING_OPEN = false;
let ACTIVE_MCP_CLIENT = "antigravity";

/* ==================== I18N ==================== */
function curLang() {
  const l = (STATE.settings && STATE.settings.language) || "ru";
  return (l === "uk" || l === "en") ? l : "ru";
}

function t(key, vars) {
  const lang = curLang();
  const dict = I18N[lang] || I18N.en || I18N.ru || {};
  let str = dict[key];
  if (str === undefined) {
    str = (I18N.en && I18N.en[key]) || (I18N.ru && I18N.ru[key]) || key;
  }
  str = String(str);
  if (vars && typeof vars === "object") {
    Object.keys(vars).forEach(function (k) {
      const val = vars[k] == null ? "" : String(vars[k]);
      str = str.replace(new RegExp("\\{" + k + "\\}", "g"), function () {
        return val;
      });
    });
  }
  return str;
}
window.t = t;

function getProviderHint(pInfo) {
  if (!pInfo) return "";
  if (pInfo.hint_i18n && pInfo.hint_i18n[curLang()]) {
    return pInfo.hint_i18n[curLang()];
  }
  return pInfo.hint || "";
}

function applyStaticI18n() {
  const l = curLang();
  document.documentElement.lang = l;

  ["topLangSelect", "dockLangSelect", "cfgLangSelect"].forEach(function (id) {
    const el = document.getElementById(id);
    if (el) el.value = l;
  });

  document.querySelectorAll("[data-i18n]").forEach(function (el) {
    const k = el.getAttribute("data-i18n");
    if (k) el.textContent = t(k);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach(function (el) {
    const k = el.getAttribute("data-i18n-placeholder");
    if (k) el.placeholder = t(k);
  });
  document.querySelectorAll("[data-i18n-title]").forEach(function (el) {
    const k = el.getAttribute("data-i18n-title");
    if (k) el.title = t(k);
  });

  updateSendButtonUI();
  renderDefectGrid();
  renderCalibrationStages();
  renderCalibrationInputs();
  renderGcodeTabs();
}

function onChangeLanguage(newLang) {
  const clean = (newLang === "uk" || newLang === "en") ? newLang : "ru";
  STATE.settings.language = clean;
  applyStaticI18n();
  populateProvidersUI();
  renderContextAndInspector();
  renderPreflight();
  renderUsageMeter();
  renderChats();
  sendAction("change_language", { language: clean });
}

/* ==================== HOST BRIDGE ==================== */
function sendToHost(payload) {
  if (window.orca && typeof window.orca.postMessage === "function") {
    window.orca.postMessage(payload);
  } else if (window.orca && typeof window.orca.sendMessage === "function") {
    window.orca.sendMessage(JSON.stringify(payload));
  }
}

function sendAction(action, extra) {
  sendToHost(Object.assign({ action: action }, extra || {}));
}

function genRequestId() {
  return "req_" + Date.now() + "_" + Math.random().toString(36).slice(2, 8);
}

function showToast(text, isError) {
  const el = document.getElementById("statusToast");
  if (!el) return;
  el.textContent = String(text || "");
  el.style.background = isError ? "var(--bg-toast-err)" : "var(--bg-toast-ok)";
  el.style.borderColor = isError ? "var(--danger)" : "var(--accent)";
  el.style.display = "block";
  clearTimeout(window._toastTimer);
  window._toastTimer = setTimeout(function () {
    el.style.display = "none";
  }, 4500);
}
window.showToast = showToast;

function copyPlainText(text) {
  const val = String(text || "");
  const done = function () {
    showToast(t("toast_copied"));
  };
  if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
    navigator.clipboard.writeText(val).then(done, function () {
      if (typeof copyTextFallback === "function") copyTextFallback(val);
      done();
    });
  } else {
    if (typeof copyTextFallback === "function") copyTextFallback(val);
    done();
  }
}

/* ==================== NAVIGATION & DRAWERS ==================== */
function switchTab(tabName) {
  ACTIVE_TAB = tabName;
  ["chat", "preflight", "wizards", "inspector", "settings"].forEach(function (tab) {
    const view = document.getElementById("view-" + tab);
    if (view) view.classList.toggle("active", tab === tabName);
    const btn = document.getElementById("tabBtn-" + tab);
    if (btn) btn.classList.toggle("btn-primary", tab === tabName);
    const dBtn = document.getElementById("dockTabBtn-" + tab);
    if (dBtn) dBtn.classList.toggle("btn-primary", tab === tabName);
  });
  if (tabName === "preflight") renderPreflight();
  if (tabName === "inspector") renderInspector();
  if (tabName === "wizards") {
    renderDefectGrid();
    populateCalibrationSlotSelect();
    renderCalibrationStages();
    renderCalibrationInputs();
  }
  if (tabName === "settings") {
    renderUsageMeter();
    renderMcpSection();
  }
}

function switchWizardSub(sub) {
  ACTIVE_WIZARD_SUB = sub;
  ["defect", "calib"].forEach(function (name) {
    const panel = document.getElementById("wizPanel-" + name);
    if (panel) panel.classList.toggle("active", name === sub);
    const btn = document.getElementById("wizSub-" + name);
    if (btn) btn.classList.toggle("btn-primary", name === sub);
  });
  if (sub === "calib") {
    populateCalibrationSlotSelect();
    renderCalibrationStages();
    renderCalibrationInputs();
  }
}

function toggleHistoryDrawer(forceState) {
  const drawer = document.getElementById("historyDrawer");
  const backdrop = document.getElementById("historyDrawerBackdrop");
  if (!drawer || !backdrop) return;
  const open = (forceState !== undefined) ? !!forceState : !drawer.classList.contains("open");
  drawer.classList.toggle("open", open);
  backdrop.classList.toggle("open", open);
}

function toggleKeyDrawer(forceState) {
  const drawer = document.getElementById("inlineKeyDrawer");
  if (!drawer) return;
  const willOpen = (forceState !== undefined) ? !!forceState : !drawer.classList.contains("open");
  drawer.classList.toggle("open", willOpen);
  if (willOpen) syncInlineKeyBar();
}

function toggleKeyVisibility(inputId) {
  const inp = document.getElementById(inputId || "cfgApiKey");
  if (!inp) return;
  inp.type = inp.type === "password" ? "text" : "password";
}

/* ==================== PROVIDERS, MODELS & KEYS ==================== */
function getEffectiveKey(provId, modelId) {
  const mKeys = (STATE.settings && STATE.settings.model_api_keys) || {};
  const specific = mKeys[provId + "::" + modelId] || mKeys[modelId] || "";
  if (specific) return specific;
  const pKeys = (STATE.settings && STATE.settings.api_keys) || {};
  return pKeys[provId] || "";
}

function hasKeyForCurrent() {
  const prov = (STATE.settings && STATE.settings.provider) || "anthropic";
  const model = (STATE.settings && STATE.settings.model) || "";
  const pInfo = STATE.providers[prov] || {};
  if (pInfo.needs_key === false) return true;
  return !!String(getEffectiveKey(prov, model) || "").trim();
}

function getAvailableModelsForProvider(provId) {
  const cached = (STATE.settings.cached_models && STATE.settings.cached_models[provId]) || [];
  const suggested = ((STATE.providers[provId] || {}).suggested_models || []).map(function (m) {
    return typeof m === "string" ? { id: m, name: m } : { id: m.id, name: m.name || m.id };
  });
  const seen = new Set();
  const result = [];
  suggested.concat(cached).forEach(function (item) {
    const id = typeof item === "string" ? item : item.id;
    if (id && !seen.has(id)) {
      seen.add(id);
      result.push({ id: id, name: (item && item.name) || id });
    }
  });
  return result;
}

function shortModelLabel(modelId) {
  const raw = String(modelId || "").trim();
  if (!raw) return "Model";
  const parts = raw.split("/");
  return parts[parts.length - 1];
}

function populateProvidersUI() {
  const selects = [
    document.getElementById("topProviderSelect"),
    document.getElementById("dockProviderSelect"),
    document.getElementById("cfgProvider")
  ];
  const provIds = Object.keys(STATE.providers || {});
  selects.forEach(function (sel) {
    if (!sel) return;
    sel.innerHTML = "";
    provIds.forEach(function (pid) {
      const p = STATE.providers[pid] || {};
      const opt = document.createElement("option");
      opt.value = pid;
      opt.textContent = p.name || pid;
      sel.appendChild(opt);
    });
  });

  const curProv = STATE.settings.provider || provIds[0] || "anthropic";
  selects.forEach(function (sel) {
    if (sel) sel.value = curProv;
  });

  populateModelDropdowns(curProv, STATE.settings.model || "");

  const chkAuto = document.getElementById("chkAutoContext");
  if (chkAuto) chkAuto.checked = STATE.settings.auto_attach_context !== false;
  const chkGcode = document.getElementById("chkIncludeGcode");
  if (chkGcode) chkGcode.checked = !!STATE.settings.include_custom_gcode;
  const effEl = document.getElementById("chatEffortSelect");
  if (effEl) effEl.value = STATE.settings.reasoning_effort || "low";

  syncSettingsForm(curProv);
  syncInlineKeyBar();
  renderFavoritesBar();
  renderModelsBrowser();
  renderUsageMeter();
  renderMcpSection();
}

function populateModelDropdowns(provId, activeModelId) {
  const list = getAvailableModelsForProvider(provId);
  const targets = [
    { sel: document.getElementById("topModelSelect"), inp: document.getElementById("topModelCustomInput") },
    { sel: document.getElementById("dockModelSelect"), inp: document.getElementById("dockModelCustomInput") }
  ];

  let resolvedModel = activeModelId;
  targets.forEach(function (pair) {
    const sel = pair.sel;
    const inp = pair.inp;
    if (!sel) return;
    sel.innerHTML = "";
    let found = false;
    list.forEach(function (m) {
      const opt = document.createElement("option");
      opt.value = m.id;
      opt.textContent = (m.name && m.name !== m.id) ? (m.name + " [" + m.id + "]") : m.id;
      if (m.id === activeModelId) found = true;
      sel.appendChild(opt);
    });
    if (activeModelId && !found) {
      const customOpt = document.createElement("option");
      customOpt.value = activeModelId;
      customOpt.textContent = t("custom_model_prefix") + activeModelId;
      sel.insertBefore(customOpt, sel.firstChild);
    }
    if (activeModelId) {
      sel.value = activeModelId;
      if (inp) inp.value = activeModelId;
    } else if (sel.options.length > 0) {
      sel.selectedIndex = 0;
      resolvedModel = sel.value;
      if (inp) inp.value = sel.value;
    }
  });

  if (resolvedModel && !STATE.settings.model) {
    STATE.settings.model = resolvedModel;
  }
  updateDockModelPill();
}

function updateDockModelPill() {
  const lbl = document.getElementById("dockModelLabel");
  const dot = document.getElementById("dockKeyDot");
  if (lbl) lbl.textContent = shortModelLabel(STATE.settings.model || STATE.settings.provider);
  if (dot) {
    const ok = hasKeyForCurrent();
    dot.className = "key-dot " + (ok ? "ok" : "missing");
  }
}

function syncInlineKeyBar() {
  const prov = STATE.settings.provider || "anthropic";
  const model = STATE.settings.model || "";
  const pInfo = STATE.providers[prov] || {};
  const scopeEl = document.getElementById("inlineKeyScope");
  const scope = scopeEl ? scopeEl.value : "provider";
  const keyBtn = document.getElementById("btnToggleKeyDrawer");
  const statusEl = document.getElementById("inlineKeyStatusText");
  const statusMsg = document.getElementById("inlineKeyStatusMsg");

  const mKeys = STATE.settings.model_api_keys || {};
  const pKeys = STATE.settings.api_keys || {};
  const curKey = (scope === "model")
    ? (mKeys[prov + "::" + model] || "")
    : (pKeys[prov] || "");

  const keyInp = document.getElementById("inlineApiKeyInput");
  if (keyInp) {
    keyInp.value = curKey;
    keyInp.placeholder = pInfo.key_placeholder || "API Key...";
  }
  const urlInp = document.getElementById("inlineBaseUrlInput");
  if (urlInp) {
    urlInp.value = (STATE.settings.base_urls && STATE.settings.base_urls[prov]) || pInfo.base_url || "";
  }
  const hintEl = document.getElementById("inlineProviderHint");
  if (hintEl) hintEl.textContent = getProviderHint(pInfo);

  const keyOk = hasKeyForCurrent();
  if (keyBtn) {
    keyBtn.className = keyOk ? "btn btn-sm btn-ok" : "btn btn-sm btn-warn";
    keyBtn.textContent = keyOk ? t("btn_key_set") : t("btn_key_enter");
  }
  if (statusEl) {
    statusEl.className = keyOk ? "key-drawer-help" : "key-drawer-help missing";
  }
  if (statusMsg) {
    statusMsg.textContent = keyOk
      ? t("key_ok_status", { prov: pInfo.name || prov, model: model })
      : t("key_missing_status", { prov: pInfo.name || prov });
  }
  updateDockModelPill();
}

function saveInlineKeyAndFetch(doFetch) {
  const prov = STATE.settings.provider || "anthropic";
  const model = STATE.settings.model || "";
  const scope = document.getElementById("inlineKeyScope").value;
  const keyVal = document.getElementById("inlineApiKeyInput").value.trim();
  const baseUrlVal = document.getElementById("inlineBaseUrlInput").value.trim();

  if (!STATE.settings.base_urls) STATE.settings.base_urls = {};
  STATE.settings.base_urls[prov] = baseUrlVal;

  const patch = {
    provider: prov,
    model: model,
    base_urls: { [prov]: baseUrlVal }
  };

  if (scope === "model") {
    if (!STATE.settings.model_api_keys) STATE.settings.model_api_keys = {};
    STATE.settings.model_api_keys[prov + "::" + model] = keyVal;
    patch.model_api_keys = { [prov + "::" + model]: keyVal };
  } else {
    if (!STATE.settings.api_keys) STATE.settings.api_keys = {};
    STATE.settings.api_keys[prov] = keyVal;
    patch.api_keys = { [prov]: keyVal };
  }

  sendAction("save_settings", { settings: patch });
  syncSettingsForm(prov);
  syncInlineKeyBar();

  if (doFetch) {
    fetchModelsFromApi(keyVal, baseUrlVal, scope === "model");
  } else {
    showToast(t("toast_key_saved"));
  }
}

function syncSettingsForm(provId) {
  const p = STATE.providers[provId] || {};
  const setVal = function (id, val) {
    const el = document.getElementById(id);
    if (el) el.value = val;
  };
  const setChk = function (id, val) {
    const el = document.getElementById(id);
    if (el) el.checked = !!val;
  };

  setVal("cfgProvider", provId);
  const hint = document.getElementById("cfgProviderHint");
  if (hint) hint.textContent = getProviderHint(p);
  setVal("cfgBaseUrl", (STATE.settings.base_urls && STATE.settings.base_urls[provId]) || p.base_url || "");
  setVal("cfgApiKey", (STATE.settings.api_keys && STATE.settings.api_keys[provId]) || "");
  setVal("cfgModel", STATE.settings.model || p.default_model || "");
  const protoGrp = document.getElementById("cfgProtocolGroup");
  if (protoGrp) protoGrp.style.display = (provId === "custom") ? "flex" : "none";
  setVal("cfgCustomProtocol", STATE.settings.custom_protocol || "openai");

  const tempVal = (typeof STATE.settings.temperature === "number" && !isNaN(STATE.settings.temperature))
    ? STATE.settings.temperature
    : 0.3;
  setVal("cfgTemperature", tempVal);
  setVal("cfgMaxTokens", STATE.settings.max_tokens || 4096);
  setChk("cfgCompactContext", STATE.settings.compact_context !== false);
  setChk("cfgPreflightNotif", STATE.settings.preflight_notifications !== false);
  setChk("cfgSlicingAudit", !!STATE.settings.enable_slicing_audit);
  setVal("cfgCustomInstructions", STATE.settings.custom_user_instructions || "");
  syncPerModelKeyInput();
}

function syncPerModelKeyInput() {
  const provEl = document.getElementById("cfgProvider");
  const modEl = document.getElementById("cfgModel");
  const outEl = document.getElementById("cfgModelSpecificKey");
  if (!outEl) return;
  const prov = (provEl && provEl.value) || STATE.settings.provider;
  const model = (modEl && modEl.value.trim()) || STATE.settings.model;
  const mKeys = STATE.settings.model_api_keys || {};
  outEl.value = mKeys[prov + "::" + model] || "";
}

function renderFavoritesBar() {
  const bar = document.getElementById("favModelsBar");
  const dockBar = document.getElementById("dockFavBar");
  const mgr = document.getElementById("favManagerList");
  const favs = STATE.settings.favorite_models || [];

  if (bar) {
    bar.innerHTML = '<span style="font-size:11px; color:var(--text-muted); margin-right:4px;">' + escapeHtml(t("fav_bar_label")) + "</span>";
  }
  if (dockBar) dockBar.innerHTML = "";
  if (mgr) mgr.innerHTML = "";

  favs.forEach(function (f, idx) {
    const isAct = (f.provider === STATE.settings.provider && f.model === STATE.settings.model);
    const makeChip = function () {
      const chip = document.createElement("button");
      chip.className = "fav-chip" + (isAct ? " active" : "");
      chip.textContent = f.label || f.model;
      chip.title = f.provider + " → " + f.model;
      chip.onclick = function () {
        STATE.settings.provider = f.provider;
        STATE.settings.model = f.model;
        populateProvidersUI();
        sendAction("save_settings", { settings: { provider: f.provider, model: f.model } });
      };
      return chip;
    };
    if (bar) bar.appendChild(makeChip());
    if (dockBar) dockBar.appendChild(makeChip());

    if (mgr) {
      const mChip = document.createElement("div");
      mChip.className = "c-badge";
      mChip.style.display = "inline-flex";
      mChip.style.alignItems = "center";
      mChip.style.gap = "6px";
      mChip.innerHTML = "<strong>" + escapeHtml(f.label || f.model) + "</strong> <span>(" + escapeHtml(f.provider) + ")</span>";
      const delBtn = document.createElement("button");
      delBtn.className = "btn btn-danger btn-xs";
      delBtn.textContent = "✕";
      delBtn.title = t("tip_remove_fav");
      delBtn.onclick = function () { removeFavorite(idx); };
      mChip.appendChild(delBtn);
      mgr.appendChild(mChip);
    }
  });
}

function renderModelsBrowser() {
  const box = document.getElementById("modelsBrowser");
  if (!box) return;
  const provEl = document.getElementById("cfgProvider");
  const provId = (provEl && provEl.value) || STATE.settings.provider;
  const filterInp = document.getElementById("modelFilterInput");
  const filter = (filterInp ? filterInp.value : "").toLowerCase().trim();
  const list = getAvailableModelsForProvider(provId).filter(function (m) {
    return !filter || m.id.toLowerCase().includes(filter) || (m.name && m.name.toLowerCase().includes(filter));
  });

  if (!list.length) {
    box.innerHTML = '<div style="padding:10px; color:var(--text-muted);">' + escapeHtml(t("no_models_found")) + "</div>";
    return;
  }

  box.innerHTML = "";
  list.slice(0, 300).forEach(function (m) {
    const row = document.createElement("div");
    row.className = "model-row-item";
    const left = document.createElement("div");
    left.style.overflow = "hidden";
    left.style.textOverflow = "ellipsis";
    left.innerHTML = "<strong>" + escapeHtml(m.name || m.id) + '</strong> <code style="font-size:11px;">' + escapeHtml(m.id) + "</code>";
    const right = document.createElement("div");
    right.style.display = "flex";
    right.style.gap = "4px";

    const useBtn = document.createElement("button");
    useBtn.className = "btn btn-xs btn-primary";
    useBtn.textContent = t("btn_select_model");
    useBtn.onclick = function () {
      const cfgM = document.getElementById("cfgModel");
      if (cfgM) cfgM.value = m.id;
      STATE.settings.provider = provId;
      STATE.settings.model = m.id;
      populateProvidersUI();
      sendAction("save_settings", { settings: { provider: provId, model: m.id } });
      showToast(m.id);
    };

    const favBtn = document.createElement("button");
    favBtn.className = "btn btn-xs";
    favBtn.textContent = "⭐";
    favBtn.onclick = function () { addModelToFavorites(provId, m.id, m.name); };

    right.appendChild(useBtn);
    right.appendChild(favBtn);
    row.appendChild(left);
    row.appendChild(right);
    box.appendChild(row);
  });
}

function _applyProviderSelection(prov) {
  const p = STATE.providers[prov] || {};
  STATE.settings.provider = prov;
  STATE.settings.model = p.default_model || "";
  populateProvidersUI();
  sendAction("save_settings", { settings: { provider: prov, model: STATE.settings.model } });
  if (!hasKeyForCurrent()) {
    toggleKeyDrawer(true);
  }
}

function onTopProviderChange() {
  _applyProviderSelection(document.getElementById("topProviderSelect").value);
}

function onDockProviderChange() {
  _applyProviderSelection(document.getElementById("dockProviderSelect").value);
}

function _applyModelSelection(m, notify) {
  if (!m) return;
  STATE.settings.model = m;
  populateModelDropdowns(STATE.settings.provider, m);
  const cfgM = document.getElementById("cfgModel");
  if (cfgM) cfgM.value = m;
  syncInlineKeyBar();
  renderFavoritesBar();
  sendAction("save_settings", { settings: { model: m } });
  if (notify) showToast(m);
}

function onTopModelSelectChange() {
  _applyModelSelection(document.getElementById("topModelSelect").value, false);
}

function onDockModelSelectChange() {
  _applyModelSelection(document.getElementById("dockModelSelect").value, false);
}

function onTopCustomModelInput() {
  _applyModelSelection(document.getElementById("topModelCustomInput").value.trim(), true);
}

function onDockCustomModelInput() {
  _applyModelSelection(document.getElementById("dockModelCustomInput").value.trim(), true);
}

function onCfgProviderSelect() {
  const prov = document.getElementById("cfgProvider").value;
  const p = STATE.providers[prov] || {};
  syncSettingsForm(prov);
  document.getElementById("cfgModel").value = p.default_model || "";
  syncPerModelKeyInput();
  renderModelsBrowser();
}

function saveProviderConfig() {
  const prov = document.getElementById("cfgProvider").value;
  const baseUrl = document.getElementById("cfgBaseUrl").value.trim();
  const apiKey = document.getElementById("cfgApiKey").value.trim();
  const model = document.getElementById("cfgModel").value.trim();
  const modelSpecKey = document.getElementById("cfgModelSpecificKey").value.trim();

  // Fix temperature = 0 bug: use isNaN instead of `|| 0.3`
  const rawTemp = parseFloat(document.getElementById("cfgTemperature").value);
  const temp = isNaN(rawTemp) ? 0.3 : Math.max(0, Math.min(2.0, rawTemp));
  const rawMaxTok = parseInt(document.getElementById("cfgMaxTokens").value, 10);
  const maxTok = isNaN(rawMaxTok) ? 4096 : Math.max(256, rawMaxTok);

  const compactCtx = document.getElementById("cfgCompactContext").checked;
  const pfNotif = document.getElementById("cfgPreflightNotif").checked;
  const slicingAudit = document.getElementById("cfgSlicingAudit").checked;
  const customInstr = document.getElementById("cfgCustomInstructions").value;
  const customProto = document.getElementById("cfgCustomProtocol").value;

  if (!STATE.settings.base_urls) STATE.settings.base_urls = {};
  if (!STATE.settings.api_keys) STATE.settings.api_keys = {};
  if (!STATE.settings.model_api_keys) STATE.settings.model_api_keys = {};

  STATE.settings.provider = prov;
  if (model) STATE.settings.model = model;
  STATE.settings.temperature = temp;
  STATE.settings.max_tokens = maxTok;
  STATE.settings.compact_context = compactCtx;
  STATE.settings.preflight_notifications = pfNotif;
  STATE.settings.enable_slicing_audit = slicingAudit;
  STATE.settings.custom_user_instructions = customInstr;
  STATE.settings.custom_protocol = customProto;
  STATE.settings.base_urls[prov] = baseUrl;
  STATE.settings.api_keys[prov] = apiKey;
  STATE.settings.model_api_keys[prov + "::" + STATE.settings.model] = modelSpecKey;

  populateProvidersUI();
  sendAction("save_settings", {
    settings: {
      provider: prov,
      model: STATE.settings.model,
      temperature: temp,
      max_tokens: maxTok,
      compact_context: compactCtx,
      preflight_notifications: pfNotif,
      enable_slicing_audit: slicingAudit,
      custom_user_instructions: customInstr,
      custom_protocol: customProto,
      base_urls: { [prov]: baseUrl },
      api_keys: { [prov]: apiKey },
      model_api_keys: { [prov + "::" + STATE.settings.model]: modelSpecKey }
    }
  });
  showToast(t("toast_key_saved"));
}

function saveQuickToggle() {
  const autoCtx = document.getElementById("chkAutoContext").checked;
  const incGcode = document.getElementById("chkIncludeGcode").checked;
  STATE.settings.auto_attach_context = autoCtx;
  STATE.settings.include_custom_gcode = incGcode;
  sendAction("save_settings", {
    settings: {
      auto_attach_context: autoCtx,
      include_custom_gcode: incGcode
    }
  });
}

function onEffortChange(val) {
  STATE.settings.reasoning_effort = val || "low";
  sendAction("save_settings", { settings: { reasoning_effort: STATE.settings.reasoning_effort } });
}

function fetchModelsFromApi(overrideKey, overrideUrl, isModelSpecificKey) {
  const isSettingsTab = ACTIVE_TAB === "settings";
  const prov = isSettingsTab
    ? document.getElementById("cfgProvider").value
    : (STATE.settings.provider || document.getElementById("topProviderSelect").value);
  const pInfo = STATE.providers[prov] || {};
  const baseUrl = overrideUrl || (isSettingsTab
    ? document.getElementById("cfgBaseUrl").value.trim()
    : ((STATE.settings.base_urls && STATE.settings.base_urls[prov]) || pInfo.base_url || ""));
  const apiKey = (overrideKey !== undefined)
    ? overrideKey
    : (isSettingsTab
      ? document.getElementById("cfgApiKey").value.trim()
      : getEffectiveKey(prov, STATE.settings.model || ""));
  const customProto = document.getElementById("cfgCustomProtocol").value || STATE.settings.custom_protocol || "openai";

  showToast(t("toast_loading_models", { prov: pInfo.name || prov }));
  sendAction("fetch_models", {
    provider: prov,
    model: STATE.settings.model || "",
    base_url: baseUrl,
    api_key: apiKey,
    custom_protocol: customProto,
    key_source: isModelSpecificKey ? "model" : "provider"
  });
}

function addCurrentToFavorites() {
  const prov = STATE.settings.provider || document.getElementById("topProviderSelect").value;
  const model = STATE.settings.model || document.getElementById("topModelSelect").value;
  if (!model) return;
  addModelToFavorites(prov, model);
}

function addModelToFavorites(prov, model, displayName) {
  const favs = STATE.settings.favorite_models || [];
  if (favs.some(function (f) { return f.provider === prov && f.model === model; })) return;
  const shortLabel = displayName || shortModelLabel(model);
  favs.push({ provider: prov, model: model, label: shortLabel });
  STATE.settings.favorite_models = favs;
  renderFavoritesBar();
  sendAction("save_settings", { settings: { favorite_models: favs } });
  showToast("⭐ " + shortLabel);
}

function removeFavorite(idx) {
  const favs = STATE.settings.favorite_models || [];
  favs.splice(idx, 1);
  STATE.settings.favorite_models = favs;
  renderFavoritesBar();
  sendAction("save_settings", { settings: { favorite_models: favs } });
}

/* ==================== CONTEXT STRIP & PRE-FLIGHT PILLS ==================== */
function updatePreflightPills() {
  const pf = STATE.preflight || { score: 100, status: "ok" };
  const score = typeof pf.score === "number" ? Math.round(pf.score) : 100;
  const status = pf.status || (score >= 85 ? "ok" : (score >= 60 ? "warn" : "danger"));
  const icon = status === "danger" ? "🔴" : (status === "warn" ? "🟡" : "🟢");
  const cls = "pf-pill pf-" + status;

  ["dockPreflightPill", "pagePreflightPill"].forEach(function (id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.className = cls;
    el.textContent = icon + " " + score;
  });
}

function renderContextBadges() {
  const badges = document.getElementById("contextBadges");
  if (!badges) return;
  const p = STATE.plate || {};
  const pr = STATE.presets || {};
  const ls = STATE.last_slice;
  let html = "";

  html += '<span class="c-badge">' + escapeHtml(t("badge_printer")) + " <strong>" + escapeHtml(pr.printer_preset || "—") + "</strong></span>";
  html += '<span class="c-badge">' + escapeHtml(t("badge_profile")) + " <strong>" + escapeHtml(pr.process_preset || "—") + "</strong></span>";

  const slots = pr.filament_slots || [];
  if (slots.length > 1) {
    html += '<span class="c-badge" style="cursor:pointer" onclick="switchTab(\'preflight\')">' +
      escapeHtml(t("badge_slots")) + " <strong>" + slots.length + " AMS</strong></span>";
  } else {
    const fils = (pr.filament_presets && pr.filament_presets.length) ? pr.filament_presets[0] : "—";
    html += '<span class="c-badge">' + escapeHtml(t("badge_filament")) + " <strong>" + escapeHtml(fils) + "</strong></span>";
  }

  if (p.has_model) {
    html += '<span class="c-badge ok">' + escapeHtml(t("badge_on_plate")) + " <strong>" +
      p.object_count + " " + escapeHtml(t("badge_pcs")) + " (" + p.total_volume_cm3 + " cm³)</strong></span>";
    if (p.total_overhang_45_mm2 > 50) {
      html += '<span class="c-badge warn">' + escapeHtml(t("badge_overhangs")) + " <strong>" + p.total_overhang_45_mm2 + " mm²</strong></span>";
    }
  } else {
    html += '<span class="c-badge">' + escapeHtml(t("badge_empty")) + "</span>";
  }

  if (ls && (ls.estimated_time_str || ls.print_time_str || ls.total_filament_g)) {
    const tStr = ls.estimated_time_str || ls.print_time_str || "";
    const gStr = ls.total_filament_g != null ? (ls.total_filament_g + "g") : "";
    const joined = [tStr, gStr].filter(Boolean).join(" / ");
    if (joined) {
      html += '<span class="c-badge ok" style="cursor:pointer" onclick="switchTab(\'preflight\')">' +
        escapeHtml(t("badge_last_slice")) + " <strong>" + escapeHtml(joined) + "</strong></span>";
    }
  }

  const cp = pr.connected_printer;
  if (cp && (cp.online || cp.connected)) {
    html += '<span class="c-badge ok">' + escapeHtml(t("badge_connected")) + " <strong>" +
      escapeHtml(cp.model_id || cp.agent || "OK") + "</strong></span>";
  }

  badges.innerHTML = html;

  const auditBtn = document.getElementById("btnAuditLastSlice");
  if (auditBtn) {
    auditBtn.classList.toggle("q-btn-accent", !!ls);
  }
}

function renderContextAndInspector() {
  updatePreflightPills();
  renderContextBadges();
  renderPreflight();
  renderInspector();
  populateCalibrationSlotSelect();
}

/* ==================== TAB 2: PRE-FLIGHT, LAST SLICE & AMS ==================== */
function renderPreflight() {
  updatePreflightPills();
  const pf = STATE.preflight || { score: 100, status: "ok", counts: { danger: 0, warn: 0, ok: 0 }, checks: [] };
  const score = typeof pf.score === "number" ? Math.round(pf.score) : 100;
  const status = pf.status || (score >= 85 ? "ok" : (score >= 60 ? "warn" : "danger"));
  const counts = pf.counts || { danger: 0, warn: 0, ok: 0 };

  const hero = document.getElementById("pfHero");
  if (hero) {
    const statusKey = status === "danger" ? "pf_status_danger" : (status === "warn" ? "pf_status_warn" : "pf_status_ok");
    hero.innerHTML =
      '<div class="pf-gauge ' + status + '">' +
      '<div class="pf-gauge-num">' + score + "</div>" +
      '<div class="pf-gauge-max">/100</div>' +
      "</div>" +
      '<div class="pf-hero-meta">' +
      '<div class="pf-hero-status">' + escapeHtml(t("pf_score_label")) + " — " + escapeHtml(t(statusKey)) + "</div>" +
      '<div class="pf-counts">' +
      '<span class="c-badge danger">' + escapeHtml(t("pf_cnt_danger", { n: counts.danger || 0 })) + "</span>" +
      '<span class="c-badge warn">' + escapeHtml(t("pf_cnt_warn", { n: counts.warn || 0 })) + "</span>" +
      '<span class="c-badge ok">' + escapeHtml(t("pf_cnt_ok", { n: counts.ok || 0 })) + "</span>" +
      "</div></div>";
  }

  const listEl = document.getElementById("pfChecksList");
  if (listEl) {
    const checks = Array.isArray(pf.checks) ? pf.checks : [];
    if (!checks.length) {
      listEl.innerHTML = '<div class="warn-box ok">' + escapeHtml(t("pf_no_checks")) + "</div>";
    } else {
      listEl.innerHTML = "";
      checks.forEach(function (chk) {
        const lvl = chk.level || chk.severity || "ok";
        const title = chk.title || chk.rule || chk.id || "";
        const detail = chk.detail || chk.message || chk.description || "";
        const fixes = chk.fix || chk.fix_changes || chk.fixes || chk.changes || [];

        const item = document.createElement("div");
        item.className = "pf-check-item " + lvl;

        const top = document.createElement("div");
        top.className = "pf-check-top";
        const icon = lvl === "danger" ? "🔴 " : (lvl === "warn" ? "🟡 " : "🟢 ");
        const titleEl = document.createElement("div");
        titleEl.className = "pf-check-title";
        titleEl.textContent = icon + title;
        top.appendChild(titleEl);

        const acts = document.createElement("div");
        acts.className = "pf-check-actions";

        if (Array.isArray(fixes) && fixes.length) {
          const fixBtn = document.createElement("button");
          fixBtn.className = "btn btn-xs btn-primary";
          fixBtn.textContent = t("pf_btn_fix");
          fixBtn.onclick = function () {
            sendAction("apply_settings", { changes: fixes, source: "preflight" });
          };
          acts.appendChild(fixBtn);
        }

        if (lvl !== "ok") {
          const askBtn = document.createElement("button");
          askBtn.className = "btn btn-xs";
          askBtn.textContent = t("pf_btn_ask_ai");
          askBtn.onclick = function () {
            switchTab("chat");
            const promptText = chk.ask_prompt && chk.ask_prompt !== detail
              ? chk.ask_prompt
              : t("pf_ask_prompt", { title: title, detail: detail });
            sendMessage(promptText);
          };
          acts.appendChild(askBtn);
        }

        top.appendChild(acts);
        item.appendChild(top);

        if (detail) {
          const detEl = document.createElement("div");
          detEl.className = "pf-check-detail";
          detEl.textContent = detail;
          item.appendChild(detEl);
        }
        listEl.appendChild(item);
      });
    }
  }

  renderLastSliceCard();
  renderAmsSlotsCard();
}

function renderLastSliceCard() {
  const body = document.getElementById("sliceMetricsBody");
  const deltaBox = document.getElementById("sliceDeltaBox");
  const auditBtn = document.getElementById("btnSliceCardAudit");
  if (!body || !deltaBox) return;

  const ls = STATE.last_slice;
  if (auditBtn) auditBtn.disabled = !ls;

  if (!ls) {
    body.innerHTML = '<div class="hint-text">' + escapeHtml(t("slice_none")) + "</div>";
    deltaBox.innerHTML = "";
    return;
  }

  const timeStr = ls.estimated_time_str || ls.print_time_str || "—";
  const weightVal = ls.total_filament_g != null ? (ls.total_filament_g + " g") : "—";
  const wasteG = ls.waste_g != null ? ls.waste_g : ((Number(ls.flush_g || 0) + Number(ls.tower_g || ls.wipe_tower_g || 0)) || 0);
  const wastePctStr = (ls.waste_pct && Number(ls.waste_pct) > 0) ? (" (" + ls.waste_pct + "%)") : "";
  const wasteStr = wasteG > 0 ? (Math.round(wasteG * 10) / 10 + " g" + wastePctStr) : "0 g";
  const layers = ls.layer_count != null ? String(ls.layer_count) : "—";
  const maxZ = ls.max_z != null ? (ls.max_z + " mm") : "—";

  let html = '<div class="kpi-grid">' +
    '<div class="kpi-tile"><span class="kpi-label">' + escapeHtml(t("slice_time")) + '</span><span class="kpi-val">' + escapeHtml(timeStr) + "</span></div>" +
    '<div class="kpi-tile"><span class="kpi-label">' + escapeHtml(t("slice_weight")) + '</span><span class="kpi-val">' + escapeHtml(weightVal) + "</span></div>" +
    '<div class="kpi-tile"><span class="kpi-label">' + escapeHtml(t("slice_waste")) + '</span><span class="kpi-val">' + escapeHtml(wasteStr) + "</span></div>" +
    '<div class="kpi-tile"><span class="kpi-label">' + escapeHtml(t("slice_layers")) + '</span><span class="kpi-val">' + escapeHtml(layers) + "</span></div>" +
    '<div class="kpi-tile"><span class="kpi-label">' + escapeHtml(t("slice_max_z")) + '</span><span class="kpi-val">' + escapeHtml(maxZ) + "</span></div>" +
    "</div>";

  const perSlot = ls.filament_used_g_per_slot || ls.per_slot_g || ls.filament_per_slot_g || [];
  if (Array.isArray(perSlot) && perSlot.length) {
    html += '<div style="display:flex; gap:6px; flex-wrap:wrap; align-items:center;">' +
      '<span class="hint-text">' + escapeHtml(t("slice_per_slot")) + ":</span>";
    perSlot.forEach(function (g, idx) {
      if (Number(g) > 0) {
        html += '<span class="c-badge">' + escapeHtml(t("badge_slot", { n: idx + 1 })) + ": <strong>" + escapeHtml(g) + "g</strong></span>";
      }
    });
    html += "</div>";
  }
  body.innerHTML = html;

  const d = STATE.slice_delta;
  if (!d) {
    deltaBox.innerHTML = "";
    return;
  }

  const fmtDelta = function (num, unit) {
    if (num == null || isNaN(Number(num))) return null;
    const n = Math.round(Number(num) * 10) / 10;
    const sign = n > 0 ? "+" : "";
    const cls = n <= 0 ? "delta-good" : "delta-bad";
    return '<span class="' + cls + '">' + sign + n + unit + "</span>";
  };

  const parts = [];
  if (d.time_delta_str) {
    const tCls = (d.time_delta_sec || 0) <= 0 ? "delta-good" : "delta-bad";
    parts.push('<span class="c-badge">' + escapeHtml(t("slice_delta_time")) + ': <span class="' + tCls + '">' + escapeHtml(d.time_delta_str) + "</span></span>");
  }
  const gVal = d.grams_delta != null ? d.grams_delta : (d.weight_delta_g != null ? d.weight_delta_g : d.filament_delta_g);
  const gFmt = fmtDelta(gVal, "g");
  if (gFmt) {
    parts.push('<span class="c-badge">' + escapeHtml(t("slice_delta_weight")) + ": " + gFmt + "</span>");
  }
  const wFmt = fmtDelta(d.waste_delta_g, "g");
  if (wFmt) {
    parts.push('<span class="c-badge">' + escapeHtml(t("slice_delta_waste")) + ": " + wFmt + "</span>");
  }
  if (!parts.length && d.summary) {
    parts.push('<span class="c-badge">' + escapeHtml(d.summary) + "</span>");
  }

  deltaBox.innerHTML = parts.length
    ? '<div class="slice-delta-banner"><div class="slice-delta-head">' + escapeHtml(t("slice_delta_title")) +
      '</div><div class="delta-chips">' + parts.join("") + "</div></div>"
    : "";
}

function renderAmsSlotsCard() {
  const box = document.getElementById("amsSlotsBody");
  if (!box) return;
  const slots = (STATE.presets && STATE.presets.filament_slots) || [];
  if (!slots.length) {
    box.innerHTML = '<div class="hint-text">' + escapeHtml(t("ams_empty")) + "</div>";
    return;
  }

  let html = '<div style="overflow-x:auto;"><table class="settings-table"><thead><tr>' +
    "<th>" + escapeHtml(t("ams_col_slot")) + "</th>" +
    "<th>" + escapeHtml(t("ams_col_name")) + "</th>" +
    "<th>" + escapeHtml(t("ams_col_type")) + "</th>" +
    "<th>" + escapeHtml(t("ams_col_nozzle")) + "</th>" +
    "<th>" + escapeHtml(t("ams_col_bed")) + "</th>" +
    "<th>" + escapeHtml(t("ams_col_flow")) + "</th>" +
    "<th>" + escapeHtml(t("ams_col_vmax")) + "</th>" +
    "<th>" + escapeHtml(t("ams_col_pa")) + "</th>" +
    "</tr></thead><tbody>";

  slots.forEach(function (s) {
    const slotNum = s.slot || 1;
    const paVal = (s.enable_pressure_advance === "0") ? "OFF" : (s.pressure_advance || "—");
    html += "<tr>" +
      '<td><span class="slot-pill">' + escapeHtml(t("badge_slot", { n: slotNum })) + "</span></td>" +
      "<td><strong>" + escapeHtml(s.name || "—") + "</strong></td>" +
      "<td>" + escapeHtml(s.type || "—") + "</td>" +
      "<td>" + escapeHtml(s.nozzle_temp ? (s.nozzle_temp + "°C") : "—") + "</td>" +
      "<td>" + escapeHtml(s.bed_temp ? (s.bed_temp + "°C") : "—") + "</td>" +
      "<td>" + escapeHtml(s.flow_ratio || "—") + "</td>" +
      "<td>" + escapeHtml(s.max_volumetric_speed ? (s.max_volumetric_speed + " mm³/s") : "—") + "</td>" +
      "<td>" + escapeHtml(paVal) + "</td>" +
      "</tr>";
  });
  html += "</tbody></table></div>";
  box.innerHTML = html;
}

/* ==================== TAB 3: DEFECT WIZARD & CALIBRATION CO-PILOT ==================== */
function renderDefectGrid() {
  const grid = document.getElementById("defectGrid");
  if (!grid) return;
  grid.innerHTML = "";
  DEFECT_ITEMS.forEach(function (item) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "defect-card" + (SELECTED_DEFECT_ID === item.id ? " selected" : "");
    btn.innerHTML =
      '<span class="defect-card-icon">' + item.icon + "</span>" +
      '<span class="defect-card-name">' + escapeHtml(t("def_name_" + item.id)) + "</span>" +
      '<span class="defect-card-desc">' + escapeHtml(t("def_desc_" + item.id)) + "</span>";
    btn.onclick = function () {
      SELECTED_DEFECT_ID = item.id;
      renderDefectGrid();
    };
    grid.appendChild(btn);
  });
}

function clearDefectAttachment() {
  DEFECT_IMAGE = null;
  const inp = document.getElementById("defectPhotoInput");
  if (inp) inp.value = "";
  const bar = document.getElementById("defectAttachmentBar");
  if (bar) bar.style.display = "none";
}

function runDefectWizard() {
  if (STATE.busy) return;
  if (!SELECTED_DEFECT_ID) {
    showToast(t("toast_select_defect"), true);
    return;
  }
  if (!hasKeyForCurrent()) {
    toggleKeyDrawer(true);
    showToast(t("toast_enter_key_first"), true);
    return;
  }
  const notes = (document.getElementById("defectNotes").value || "").trim();
  const reqId = genRequestId();
  ACTIVE_REQUEST_ID = reqId;
  ACTIVE_STREAM_CHAT_ID = (STATE.chats && STATE.chats.active_id) || "";
  setBusy(true, t("status_working"));
  switchTab("chat");

  sendAction("run_defect_wizard", {
    symptom_id: SELECTED_DEFECT_ID,
    notes: notes,
    image: DEFECT_IMAGE,
    provider: STATE.settings.provider,
    model: STATE.settings.model,
    request_id: reqId
  });
  clearDefectAttachment();
}

function populateCalibrationSlotSelect() {
  const sel = document.getElementById("calSlotSelect");
  if (!sel) return;
  const prev = sel.value || "1";
  const slots = (STATE.presets && STATE.presets.filament_slots) || [];
  sel.innerHTML = "";
  const count = Math.max(slots.length, 1);
  for (let i = 1; i <= count; i++) {
    const info = slots[i - 1];
    const opt = document.createElement("option");
    opt.value = String(i);
    opt.textContent = t("badge_slot", { n: i }) + (info && info.name ? (" — " + info.name) : "");
    sel.appendChild(opt);
  }
  if (Number(prev) <= count) sel.value = prev;
}

function onCalSlotChange() {
  renderCalibrationInputs();
}

function renderCalibrationStages() {
  const bar = document.getElementById("calStagesBar");
  if (!bar) return;
  bar.innerHTML = "";
  CALIBRATION_STAGES.forEach(function (st) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-sm" + (ACTIVE_CAL_STAGE === st.id ? " btn-primary" : "");
    btn.textContent = t(st.i18n);
    btn.onclick = function () {
      ACTIVE_CAL_STAGE = st.id;
      LAST_CAL_RESULT = null;
      renderCalibrationStages();
      renderCalibrationInputs();
      renderCalibrationResult(null);
    };
    bar.appendChild(btn);
  });
}

function _getSelectedSlotInfo() {
  const sel = document.getElementById("calSlotSelect");
  const slotNum = parseInt((sel && sel.value) || "1", 10) || 1;
  const slots = (STATE.presets && STATE.presets.filament_slots) || [];
  return { slot: slotNum, info: slots[slotNum - 1] || {} };
}

function renderCalibrationInputs() {
  const box = document.getElementById("calInputsBox");
  if (!box) return;
  const slotData = _getSelectedSlotInfo();
  const sInfo = slotData.info || {};
  const fields = [];

  if (ACTIVE_CAL_STAGE === "temp_tower") {
    const defTemp = sInfo.nozzle_temp || "215";
    const defFirst = sInfo.nozzle_temp_initial || defTemp;
    fields.push({ id: "best_temp", label: t("cal_in_best_temp"), val: defTemp, step: "1" });
    fields.push({ id: "first_layer_temp", label: t("cal_in_first_layer_temp"), val: defFirst, step: "1" });
  } else if (ACTIVE_CAL_STAGE === "max_volumetric_speed") {
    fields.push({ id: "start_flow", label: t("cal_in_start_flow"), val: "5", step: "0.5" });
    fields.push({ id: "measured_height", label: t("cal_in_height"), val: "20", step: "0.5" });
    fields.push({ id: "step_per_mm", label: t("cal_in_step"), val: "0.5", step: "0.1" });
    fields.push({ id: "safety_margin_pct", label: t("cal_in_margin"), val: "15", step: "1" });
  } else if (ACTIVE_CAL_STAGE === "pressure_advance") {
    fields.push({ id: "start_pa", label: t("cal_in_pa_start"), val: "0", step: "0.005" });
    fields.push({ id: "measured_height", label: t("cal_in_height"), val: "15", step: "0.5" });
    fields.push({ id: "step_per_mm", label: t("cal_in_pa_step"), val: "0.002", step: "0.001" });
  } else if (ACTIVE_CAL_STAGE === "flow_rate") {
    fields.push({ id: "old_flow", label: t("cal_in_old_flow"), val: sInfo.flow_ratio || "0.98", step: "0.01" });
    fields.push({ id: "modifier", label: t("cal_in_modifier"), val: "0", step: "1" });
  } else if (ACTIVE_CAL_STAGE === "retraction") {
    fields.push({ id: "start_retraction", label: t("cal_in_ret_start"), val: "0", step: "0.1" });
    fields.push({ id: "measured_height", label: t("cal_in_height"), val: "8", step: "0.5" });
    fields.push({ id: "step_per_mm", label: t("cal_in_ret_step"), val: "0.1", step: "0.05" });
  }

  box.innerHTML = "";
  fields.forEach(function (f) {
    const grp = document.createElement("div");
    grp.className = "form-group";
    grp.innerHTML =
      '<label for="calIn_' + f.id + '">' + escapeHtml(f.label) + "</label>" +
      '<input type="number" id="calIn_' + f.id + '" class="ctrl-input" step="' + f.step + '" value="' + escapeHtml(f.val) + '" />';
    box.appendChild(grp);
  });
}

function _collectCalMeasurements() {
  const measurements = { lang: curLang() };
  document.querySelectorAll('[id^="calIn_"]').forEach(function (inp) {
    const key = inp.id.replace("calIn_", "");
    const num = parseFloat(inp.value);
    if (!isNaN(num)) measurements[key] = num;
  });
  if (measurements.best_temp !== undefined && measurements.first_layer_temp !== undefined) {
    measurements.initial_layer_offset = measurements.first_layer_temp - measurements.best_temp;
  }
  if (measurements.measured_height !== undefined) measurements.height = measurements.measured_height;
  if (measurements.step_per_mm !== undefined) measurements.step = measurements.step_per_mm;
  if (measurements.start_flow !== undefined) measurements.start = measurements.start_flow;
  if (measurements.start_pa !== undefined) measurements.start = measurements.start_pa;
  if (measurements.start_retraction !== undefined) measurements.start = measurements.start_retraction;
  return measurements;
}

function runCalibrationCalc(askAi) {
  const slotData = _getSelectedSlotInfo();
  const measurements = _collectCalMeasurements();
  if (askAi) {
    if (STATE.busy) return;
    if (!hasKeyForCurrent()) {
      toggleKeyDrawer(true);
      showToast(t("toast_enter_key_first"), true);
      return;
    }
    const reqId = genRequestId();
    ACTIVE_REQUEST_ID = reqId;
    ACTIVE_STREAM_CHAT_ID = (STATE.chats && STATE.chats.active_id) || "";
    setBusy(true, t("status_working"));
    switchTab("chat");
    sendAction("calc_calibration", {
      stage: ACTIVE_CAL_STAGE,
      slot: slotData.slot,
      measurements: measurements,
      ask_ai: true,
      request_id: reqId
    });
  } else {
    sendAction("calc_calibration", {
      stage: ACTIVE_CAL_STAGE,
      slot: slotData.slot,
      measurements: measurements,
      ask_ai: false
    });
  }
}

function renderCalibrationResult(res) {
  const box = document.getElementById("calResultBox");
  if (!box) return;
  if (!res) {
    box.innerHTML = "";
    return;
  }
  LAST_CAL_RESULT = res;
  if (res.error) {
    box.innerHTML = '<div class="warn-box danger">⚠ ' + escapeHtml(res.error) + "</div>";
    return;
  }

  const slotNum = res.slot || _getSelectedSlotInfo().slot || 1;
  const changes = Array.isArray(res.changes) ? res.changes : [];
  let html = '<div class="settings-apply-card">' +
    '<div class="settings-apply-head">' +
    "<span>" + escapeHtml(t("cal_result_title")) + "</span>";
  if (changes.length) {
    html += '<button class="btn btn-sm btn-primary" onclick="applyCalibrationChanges()">' +
      escapeHtml(t("cal_apply_btn", { slot: slotNum })) + "</button>";
  }
  html += "</div>";

  if (res.formula) {
    html += '<div style="margin-bottom:6px;"><code>' + escapeHtml(res.formula) + "</code></div>";
  }
  const summaryText = res.result_summary || res.summary || "";
  if (summaryText) {
    html += '<div style="margin-bottom:8px; font-size:12.5px;">' + escapeHtml(summaryText) + "</div>";
  }
  if (res.warning) {
    html += '<div class="warn-box" style="margin-bottom:8px;">' + escapeHtml(res.warning) + "</div>";
  }
  if (changes.length) {
    html += '<table class="settings-table"><thead><tr>' +
      "<th>" + escapeHtml(t("th_param")) + "</th>" +
      "<th>" + escapeHtml(t("th_change")) + "</th>" +
      "<th>" + escapeHtml(t("th_reason")) + "</th>" +
      "</tr></thead><tbody>";
    changes.forEach(function (c) {
      const slotBadge = (c.category === "filament" || c.slot)
        ? '<span class="slot-pill">' + escapeHtml(t("badge_slot", { n: c.slot || slotNum })) + "</span>"
        : "";
      html += "<tr>" +
        "<td><strong>" + escapeHtml(c.label || c.key) + "</strong>" + slotBadge + '<br/><code style="font-size:10.5px;">' + escapeHtml(c.key) + "</code></td>" +
        '<td><span class="val-new">' + escapeHtml(c.value) + "</span></td>" +
        '<td style="color:var(--text-muted)">' + escapeHtml(c.reason || "") + "</td>" +
        "</tr>";
    });
    html += "</tbody></table>";
  }
  html += "</div>";
  box.innerHTML = html;
}

function applyCalibrationChanges() {
  if (!LAST_CAL_RESULT || !Array.isArray(LAST_CAL_RESULT.changes) || !LAST_CAL_RESULT.changes.length) return;
  sendAction("apply_settings", { changes: LAST_CAL_RESULT.changes, source: "calibration" });
}

/* ==================== TAB 4: INSPECTOR (3D, G-CODE, SNAPSHOTS, UNDO) ==================== */
function renderInspector() {
  const p = STATE.plate || {};
  const pr = STATE.presets || {};
  const wBox = document.getElementById("inspectorWarnings");
  const oBox = document.getElementById("inspectorObjects");
  const prBox = document.getElementById("inspectorPresets");
  const dirtyBox = document.getElementById("inspectorDirtyDiff");

  if (wBox) {
    if (p.warnings && p.warnings.length) {
      wBox.innerHTML = p.warnings.map(function (w) {
        return '<div class="warn-box ' + (w.level === "danger" ? "danger" : "") + '">⚠ ' + escapeHtml(w.text) + "</div>";
      }).join("");
    } else {
      wBox.innerHTML = p.has_model
        ? '<div class="warn-box ok">' + escapeHtml(t("mesh_ok")) + "</div>"
        : "";
    }
  }

  if (oBox) {
    if (!p.has_model) {
      oBox.innerHTML = '<div class="hint-text">' + escapeHtml(t("plate_empty_hint")) + "</div>";
    } else {
      let tbl = '<div style="overflow-x:auto;"><table class="settings-table"><thead><tr>' +
        "<th>" + escapeHtml(t("th_obj")) + "</th>" +
        "<th>" + escapeHtml(t("th_dim")) + "</th>" +
        "<th>" + escapeHtml(t("th_vol")) + "</th>" +
        "<th>" + escapeHtml(t("th_bed")) + "</th>" +
        "<th>" + escapeHtml(t("th_ovh")) + "</th>" +
        "<th>" + escapeHtml(t("th_slots")) + "</th>" +
        "<th>" + escapeHtml(t("th_mesh")) + "</th>" +
        "</tr></thead><tbody>";
      (p.objects || []).forEach(function (o) {
        const mStatus = (!o.is_manifold || o.mesh_errors > 0)
          ? '<span style="color:var(--danger-text)">' + escapeHtml(t("mesh_err")) + " (" + o.mesh_errors + ")</span>"
          : '<span style="color:var(--ok-text)">' + escapeHtml(t("mesh_manifold_ok")) + "</span>";
        const extIds = Array.isArray(o.extruder_ids) && o.extruder_ids.length
          ? o.extruder_ids.map(function (id) {
              return '<span class="slot-pill">' + escapeHtml(t("badge_slot", { n: id })) + "</span>";
            }).join(" ")
          : "—";
        const objOvCnt = o.object_overrides ? Object.keys(o.object_overrides).length : 0;
        const modOvCnt = Array.isArray(o.modifier_overrides) ? o.modifier_overrides.length : 0;
        const ovHtml = (objOvCnt + modOvCnt) > 0
          ? '<div class="hint-text">' + escapeHtml(t("insp_overrides_lbl", { n: objOvCnt + modOvCnt })) + "</div>"
          : "";

        tbl += "<tr>" +
          "<td><strong>" + escapeHtml(o.name) + "</strong> (x" + (o.instances || 1) + ")</td>" +
          "<td>" + o.size_x + " × " + o.size_y + " × " + o.size_z + " mm (H/B " + o.height_to_base_ratio + ":1)</td>" +
          "<td>" + o.volume_cm3 + " cm³ (" + o.triangles + " tri)</td>" +
          "<td>" + o.bed_contact_mm2 + " mm²</td>" +
          "<td>" + o.overhang_45_mm2 + " mm² (" + o.overhang_45_pct + "%) / " + o.overhang_60_mm2 + " mm²</td>" +
          "<td>" + extIds + ovHtml + "</td>" +
          "<td>" + mStatus + "</td>" +
          "</tr>";
      });
      tbl += "</tbody></table></div>";
      oBox.innerHTML = tbl;
    }
  }

  if (dirtyBox) {
    const dirty = Array.isArray(pr.dirty_diff) ? pr.dirty_diff : [];
    if (dirty.length) {
      let dHtml = '<div class="warn-box" style="margin-bottom:10px;"><strong>' +
        escapeHtml(t("insp_dirty_title")) + " (" + dirty.length + ")</strong><div style=\"margin-top:4px; display:flex; flex-wrap:wrap; gap:6px;\">";
      dirty.slice(0, 15).forEach(function (d) {
        const sl = d.slot ? (" [" + t("badge_slot", { n: d.slot }) + "]") : "";
        dHtml += '<span class="c-badge"><code>' + escapeHtml(d.key) + "</code>" + escapeHtml(sl) + ": " +
          '<span class="val-old">' + escapeHtml(d.saved || "—") + '</span> → <span class="val-new">' + escapeHtml(d.current || "—") + "</span></span>";
      });
      dHtml += "</div></div>";
      dirtyBox.innerHTML = dHtml;
    } else {
      dirtyBox.innerHTML = "";
    }
  }

  if (prBox) {
    const groups = pr.groups || {};
    let pHtml = '<div class="grid-2">';
    Object.keys(groups).forEach(function (gTitle) {
      const items = groups[gTitle] || [];
      pHtml += '<div style="background:var(--bg-input); border:1px solid var(--border); border-radius:8px; padding:10px;">';
      pHtml += '<div style="font-weight:700; color:var(--accent-text); margin-bottom:6px;">' + escapeHtml(gTitle) + "</div>";
      pHtml += '<table class="settings-table"><tbody>';
      items.forEach(function (it) {
        pHtml += '<tr><td style="color:var(--text-muted)">' + escapeHtml(it.label) +
          ' <code style="font-size:10.5px;">' + escapeHtml(it.key) + "</code></td>" +
          '<td style="text-align:right; font-weight:600;">' + escapeHtml(it.value) + "</td></tr>";
      });
      pHtml += "</tbody></table></div>";
    });
    pHtml += "</div>";
    prBox.innerHTML = pHtml;
  }

  renderGcodeTabs();
  renderSnapshotsList();
  renderApplyHistoryList();
}

function _getGcodeTabContent(tabId) {
  const cg = (STATE.presets && STATE.presets.custom_gcode) || {};
  const tab = GCODE_TABS.find(function (x) { return x.id === tabId; }) || GCODE_TABS[0];
  const blocks = [];

  if (tab.id === "filament") {
    const slots = (STATE.presets && STATE.presets.filament_slots) || [];
    slots.forEach(function (s) {
      if (s.start_gcode && s.start_gcode.trim()) {
        blocks.push("; === filament_start_gcode (" + t("badge_slot", { n: s.slot || 1 }) + ": " + (s.name || "") + ") ===\n" + s.start_gcode);
      }
      if (s.end_gcode && s.end_gcode.trim()) {
        blocks.push("; === filament_end_gcode (" + t("badge_slot", { n: s.slot || 1 }) + ": " + (s.name || "") + ") ===\n" + s.end_gcode);
      }
    });
    ["change_filament_gcode", "filament_change_extrusion_role_gcode"].forEach(function (k) {
      if (cg[k] && String(cg[k]).trim()) {
        blocks.push("; === " + k + " ===\n" + cg[k]);
      }
    });
    if (!blocks.length) {
      tab.keys.forEach(function (k) {
        if (cg[k] && String(cg[k]).trim()) {
          blocks.push("; === " + k + " ===\n" + cg[k]);
        }
      });
    }
  } else {
    tab.keys.forEach(function (k) {
      if (cg[k] && String(cg[k]).trim()) {
        blocks.push("; === " + k + " ===\n" + cg[k]);
      }
    });
  }
  return blocks.join("\n\n");
}

function renderGcodeTabs() {
  const bar = document.getElementById("gcodeTabsBar");
  const viewer = document.getElementById("inspectorGcodeViewer");
  if (!bar || !viewer) return;

  bar.innerHTML = "";
  GCODE_TABS.forEach(function (tab) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-xs" + (ACTIVE_GCODE_TAB === tab.id ? " btn-primary" : "");
    btn.textContent = t(tab.i18n);
    btn.onclick = function () {
      ACTIVE_GCODE_TAB = tab.id;
      renderGcodeTabs();
    };
    bar.appendChild(btn);
  });

  const text = _getGcodeTabContent(ACTIVE_GCODE_TAB);
  if (!text) {
    viewer.innerHTML = '<div class="hint-text">' + escapeHtml(t("insp_gcode_empty")) + "</div>";
  } else {
    viewer.innerHTML = '<pre class="gcode-viewer-pre">' + escapeHtml(text) + "</pre>";
  }
}

function copyCurrentGcodeTab() {
  const text = _getGcodeTabContent(ACTIVE_GCODE_TAB);
  if (!text) return;
  copyPlainText(text);
}

function askAiAboutCustomGcode() {
  const chk = document.getElementById("chkIncludeGcode");
  if (chk) chk.checked = true;
  STATE.settings.include_custom_gcode = true;
  switchTab("chat");
  sendMessage(t("prompt_inspect_gcode"), true);
}

function savePresetSnapshot() {
  const inp = document.getElementById("snapNameInput");
  const name = (inp ? inp.value : "").trim();
  if (!name) {
    showToast(t("toast_snap_enter_name"), true);
    if (inp) inp.focus();
    return;
  }
  if (inp) inp.value = "";
  sendAction("save_snapshot", { name: name });
}

function renderSnapshotsList() {
  const list = document.getElementById("snapshotsList");
  if (!list) return;
  const snaps = Array.isArray(STATE.snapshots) ? STATE.snapshots : [];
  if (!snaps.length) {
    list.innerHTML = '<div class="hint-text">' + escapeHtml(t("snap_empty")) + "</div>";
    return;
  }
  list.innerHTML = "";
  snaps.forEach(function (s) {
    const row = document.createElement("div");
    row.className = "list-row-card";
    const left = document.createElement("div");
    left.innerHTML = "<strong>" + escapeHtml(s.name || s.id) + "</strong>" +
      '<div class="list-row-meta">' + escapeHtml(s.created_at || "") + "</div>";
    const right = document.createElement("div");
    right.style.display = "flex";
    right.style.gap = "5px";

    const resBtn = document.createElement("button");
    resBtn.className = "btn btn-xs btn-ok";
    resBtn.textContent = t("snap_btn_restore");
    resBtn.onclick = function () { sendAction("restore_snapshot", { snap_id: s.id, snapshot_id: s.id }); };

    const delBtn = document.createElement("button");
    delBtn.className = "btn btn-xs btn-danger";
    delBtn.textContent = t("snap_btn_delete");
    delBtn.onclick = function () { sendAction("delete_snapshot", { snap_id: s.id, snapshot_id: s.id }); };

    right.appendChild(resBtn);
    right.appendChild(delBtn);
    row.appendChild(left);
    row.appendChild(right);
    list.appendChild(row);
  });
}

function renderApplyHistoryList() {
  const list = document.getElementById("applyHistoryList");
  if (!list) return;
  const hist = Array.isArray(STATE.apply_history) ? STATE.apply_history : [];
  if (!hist.length) {
    list.innerHTML = '<div class="hint-text">' + escapeHtml(t("hist_empty")) + "</div>";
    return;
  }
  list.innerHTML = "";
  hist.forEach(function (rec) {
    const applied = rec.applied || rec.rollback_changes || [];
    const keysPreview = applied.slice(0, 4).map(function (a) { return a.key || a.label; }).filter(Boolean).join(", ");
    const row = document.createElement("div");
    row.className = "list-row-card";
    const left = document.createElement("div");
    left.innerHTML = "<strong>" + escapeHtml(t("hist_params_count", { n: applied.length })) + "</strong> " +
      '<code style="font-size:11px;">' + escapeHtml(keysPreview) + (applied.length > 4 ? "…" : "") + "</code>" +
      '<div class="list-row-meta">' + escapeHtml(rec.timestamp || rec.created_at || "") + "</div>";
    const undoBtn = document.createElement("button");
    undoBtn.className = "btn btn-xs btn-warn";
    undoBtn.textContent = t("hist_btn_undo");
    undoBtn.onclick = function () {
      sendAction("undo_apply", { record_id: rec.id });
    };
    row.appendChild(left);
    row.appendChild(undoBtn);
    list.appendChild(row);
  });
}

/* ==================== TAB 5: USAGE & TOKEN METER ==================== */
function _fmtNum(n) {
  const v = Number(n || 0);
  if (v >= 1000000) return (v / 1000000).toFixed(2) + "M";
  if (v >= 1000) return (v / 1000).toFixed(1) + "k";
  return String(v);
}

function renderUsageMeter() {
  const body = document.getElementById("usageMeterBody");
  if (!body) return;
  const u = STATE.usage || {};
  const month = u.month || { msgs: 0, input_tokens: 0, output_tokens: 0 };
  const total = u.total || { msgs: 0, input_tokens: 0, output_tokens: 0 };

  const makeBox = function (title, b) {
    return '<div class="usage-box">' +
      '<div class="usage-box-title">' + escapeHtml(title) + "</div>" +
      '<div class="usage-stats-row">' +
      '<div class="usage-stat"><div class="usage-stat-lbl">' + escapeHtml(t("usage_msgs")) + '</div><div class="usage-stat-num">' + escapeHtml(_fmtNum(b.msgs)) + "</div></div>" +
      '<div class="usage-stat"><div class="usage-stat-lbl">' + escapeHtml(t("usage_in_tok")) + '</div><div class="usage-stat-num">' + escapeHtml(_fmtNum(b.input_tokens)) + "</div></div>" +
      '<div class="usage-stat"><div class="usage-stat-lbl">' + escapeHtml(t("usage_out_tok")) + '</div><div class="usage-stat-num">' + escapeHtml(_fmtNum(b.output_tokens)) + "</div></div>" +
      "</div></div>";
  };

  body.innerHTML = makeBox(t("usage_month"), month) + makeBox(t("usage_total"), total);
}

/* ==================== TAB 5: LOCAL MCP SERVER ==================== */
function _effectiveMcpState() {
  const m = STATE.mcp || {};
  const s = STATE.settings || {};
  const port = m.port || s.mcp_port || 18765;
  const url = m.url || ("http://127.0.0.1:" + port + "/mcp");
  const token = (m.token !== undefined && m.token !== "") ? m.token : (s.mcp_token || "");
  return {
    running: !!m.running,
    enabled: m.enabled !== undefined ? !!m.enabled : !!s.mcp_enabled,
    port: port,
    url: url,
    require_auth: m.require_auth !== undefined ? !!m.require_auth : (s.mcp_require_auth !== false),
    token: token,
    allow_write: m.allow_write !== undefined ? !!m.allow_write : (s.mcp_allow_write !== false),
    allow_gcode_write: m.allow_gcode_write !== undefined ? !!m.allow_gcode_write : (s.mcp_allow_gcode_write !== false),
    error: m.error || "",
    recent_calls: Array.isArray(m.recent_calls) ? m.recent_calls : []
  };
}

function buildMcpClientConfigJson(clientKind) {
  const info = _effectiveMcpState();
  const kind = clientKind || ACTIVE_MCP_CLIENT || "antigravity";
  const tokenDisplay = info.token || "<GENERATE_OR_ENABLE_FIRST>";
  const authHeaderVal = "Bearer " + tokenDisplay;

  if (kind === "cursor") {
    const entry = { url: info.url };
    if (info.require_auth) entry.headers = { Authorization: authHeaderVal };
    return JSON.stringify({ mcpServers: { orcaslicer: entry } }, null, 2);
  }

  if (kind === "claude_desktop") {
    const args = ["-y", "mcp-remote", info.url];
    if (info.require_auth) {
      args.push("--header", "Authorization:" + authHeaderVal);
    }
    return JSON.stringify({
      mcpServers: {
        orcaslicer: {
          command: "npx",
          args: args
        }
      }
    }, null, 2);
  }

  // Antigravity (serverUrl)
  const agyEntry = { serverUrl: info.url };
  if (info.require_auth) agyEntry.headers = { Authorization: authHeaderVal };
  return JSON.stringify({ mcpServers: { orcaslicer: agyEntry } }, null, 2);
}

function renderMcpSection() {
  const info = _effectiveMcpState();
  const badge = document.getElementById("mcpStatusBadge");
  if (badge) {
    if (info.error) {
      badge.className = "mcp-status-pill error";
      badge.textContent = "⚠ " + t("mcp_status_error");
    } else if (info.running) {
      badge.className = "mcp-status-pill running";
      badge.textContent = "🟢 " + t("mcp_status_running", { port: info.port });
    } else {
      badge.className = "mcp-status-pill stopped";
      badge.textContent = "⚪ " + t("mcp_status_stopped");
    }
  }

  const setChk = function (id, val) {
    const el = document.getElementById(id);
    if (el) el.checked = !!val;
  };
  const setVal = function (id, val) {
    const el = document.getElementById(id);
    if (el) el.value = val;
  };

  setChk("cfgMcpEnabled", info.enabled);
  setVal("cfgMcpPort", info.port);
  setChk("cfgMcpRequireAuth", info.require_auth);
  setVal("cfgMcpToken", info.token);
  setChk("cfgMcpAllowWrite", info.allow_write);
  setChk("cfgMcpAllowGcodeWrite", info.allow_gcode_write);
  setVal("mcpEndpointDisplay", info.url);

  const errBox = document.getElementById("mcpErrorBox");
  if (errBox) {
    if (info.error) {
      errBox.style.display = "block";
      errBox.textContent = info.error;
    } else {
      errBox.style.display = "none";
      errBox.textContent = "";
    }
  }

  ["antigravity", "cursor", "claude_desktop"].forEach(function (k) {
    const b = document.getElementById("mcpCliBtn-" + k);
    if (b) b.classList.toggle("btn-primary", k === ACTIVE_MCP_CLIENT);
  });

  const pre = document.getElementById("mcpConfigSnippet");
  if (pre) pre.textContent = buildMcpClientConfigJson(ACTIVE_MCP_CLIENT);

  const logBox = document.getElementById("mcpRecentCalls");
  if (logBox) {
    if (!info.recent_calls.length) {
      logBox.innerHTML = '<div class="hint-text">' + escapeHtml(t("mcp_recent_empty")) + "</div>";
    } else {
      logBox.innerHTML = "";
      info.recent_calls.forEach(function (c) {
        const row = document.createElement("div");
        row.className = "mcp-log-item" + (c.ok ? "" : " err");
        const namePart = c.tool ? (c.method + " · " + c.tool) : c.method;
        row.innerHTML =
          '<span><strong>' + escapeHtml(namePart || "") + "</strong>" +
          (c.summary ? (" — " + escapeHtml(c.summary)) : "") + "</span>" +
          '<span style="color:var(--text-muted)">' + escapeHtml(c.time || "") + "</span>";
        logBox.appendChild(row);
      });
    }
  }
}

function selectMcpClientPreset(kind) {
  ACTIVE_MCP_CLIENT = kind || "antigravity";
  renderMcpSection();
}

function copyMcpConfig() {
  copyPlainText(buildMcpClientConfigJson(ACTIVE_MCP_CLIENT));
}

function copyMcpToken() {
  const info = _effectiveMcpState();
  if (!info.token) {
    showToast(t("mcp_toast_enable_first"), true);
    return;
  }
  copyPlainText(info.token);
}

function regenerateMcpToken() {
  sendAction("mcp_regenerate_token");
}

function saveMcpConfig() {
  const enabled = !!(document.getElementById("cfgMcpEnabled") || {}).checked;
  const rawPort = parseInt(((document.getElementById("cfgMcpPort") || {}).value || "18765"), 10);
  const port = (!isNaN(rawPort) && rawPort >= 1024 && rawPort <= 65535) ? rawPort : 18765;
  const requireAuth = !!(document.getElementById("cfgMcpRequireAuth") || {}).checked;
  const allowWrite = !!(document.getElementById("cfgMcpAllowWrite") || {}).checked;
  const allowGcode = !!(document.getElementById("cfgMcpAllowGcodeWrite") || {}).checked;

  STATE.settings.mcp_enabled = enabled;
  STATE.settings.mcp_port = port;
  STATE.settings.mcp_require_auth = requireAuth;
  STATE.settings.mcp_allow_write = allowWrite;
  STATE.settings.mcp_allow_gcode_write = allowGcode;

  sendAction("save_settings", {
    settings: {
      mcp_enabled: enabled,
      mcp_port: port,
      mcp_require_auth: requireAuth,
      mcp_allow_write: allowWrite,
      mcp_allow_gcode_write: allowGcode
    }
  });
  showToast(t("mcp_toast_saved"));
}

/* ==================== CHAT SESSIONS & MESSAGES ==================== */
function createNewChat() {
  sendAction("new_chat");
}

function clearCurrentChat() {
  sendAction("clear_chat");
}

function renameChatPrompt(chatId, currentTitle) {
  const next = window.prompt(t("prompt_rename_chat"), currentTitle || "");
  if (next && next.trim()) {
    sendAction("rename_chat", { chat_id: chatId, title: next.trim() });
  }
}

function _renderSessionListInto(container, sessions, activeId, closeDrawerOnClick) {
  if (!container) return;
  container.innerHTML = "";
  sessions.forEach(function (s) {
    const item = document.createElement("div");
    item.className = "session-item" + (s.id === activeId ? " active" : "");

    const titleSpan = document.createElement("span");
    titleSpan.className = "session-title";
    titleSpan.textContent = s.title || t("default_chat_title");
    titleSpan.onclick = function () {
      sendAction("select_chat", { chat_id: s.id });
      if (closeDrawerOnClick) toggleHistoryDrawer(false);
    };

    const actions = document.createElement("div");
    actions.className = "session-actions";

    const renBtn = document.createElement("button");
    renBtn.className = "session-act-btn";
    renBtn.textContent = "✏️";
    renBtn.title = t("tip_rename_chat");
    renBtn.onclick = function (e) {
      e.stopPropagation();
      renameChatPrompt(s.id, s.title || "");
    };

    const delBtn = document.createElement("button");
    delBtn.className = "session-act-btn del";
    delBtn.textContent = "✕";
    delBtn.title = t("tip_delete_chat");
    delBtn.onclick = function (e) {
      e.stopPropagation();
      sendAction("delete_chat", { chat_id: s.id });
    };

    actions.appendChild(renBtn);
    actions.appendChild(delBtn);
    item.appendChild(titleSpan);
    item.appendChild(actions);
    container.appendChild(item);
  });
}

function _catBadgeHtml(cat) {
  const key = cat === "filament" ? "badge_cat_filament" : (cat === "printer" ? "badge_cat_printer" : "badge_cat_process");
  return '<span class="cat-pill">' + escapeHtml(t(key)) + "</span>";
}

function _buildSuggestionsCard(m, msgIdx) {
  const cardId = "sug_" + msgIdx;
  LAST_SUGGESTIONS_MAP[cardId] = m.suggestions;
  const appliedRecId = APPLIED_CARD_RECORDS[cardId] || m.applied_record_id || "";

  const card = document.createElement("div");
  card.className = "settings-apply-card";
  card.id = "card_" + cardId;

  let head = '<div class="settings-apply-head">' +
    "<span>" + escapeHtml(t("sug_head", { n: m.suggestions.length })) + "</span>" +
    '<div class="settings-apply-actions">';
  if (appliedRecId) {
    head += '<span class="c-badge ok">' + escapeHtml(t("btn_applied_done")) + "</span>" +
      '<button type="button" class="btn btn-warn btn-sm" onclick="undoApplyRecord(\'' + escapeHtml(appliedRecId) + '\', \'' + cardId + '\')">' +
      escapeHtml(t("btn_undo_apply")) + "</button>";
  }
  head += '<button type="button" class="btn btn-primary btn-sm" onclick="applySelectedSuggestions(\'' + cardId + '\')">' +
    escapeHtml(t("btn_apply_sug")) + "</button></div></div>";

  // Desktop 4-col table
  let tbl = '<table class="settings-table settings-table-desktop"><thead><tr>' +
    '<th style="width:26px;"><input type="checkbox" checked onchange="toggleAllSug(\'' + cardId + '\', this.checked)" /></th>' +
    "<th>" + escapeHtml(t("th_param")) + "</th>" +
    "<th>" + escapeHtml(t("th_change")) + "</th>" +
    "<th>" + escapeHtml(t("th_reason")) + "</th></tr></thead><tbody>";

  // Narrow / Dock vertical stacked cards
  let stacked = '<div class="settings-stacked-list">';

  m.suggestions.forEach(function (s, sIdx) {
    const curVal = s.current_value || (STATE.presets && STATE.presets.flat_values && STATE.presets.flat_values[s.key]) || "—";
    const hasErr = !!s.validation_error;
    const checkedAttr = hasErr ? "" : "checked";
    const slotBadge = (s.category === "filament" || (s.slot && Number(s.slot) > 1))
      ? '<span class="slot-pill">' + escapeHtml(t("badge_slot", { n: s.slot || 1 })) + "</span>"
      : "";
    const catBadge = _catBadgeHtml(s.category);
    const valNoteHtml = s.validation_note
      ? '<div class="val-note">ℹ ' + escapeHtml(t("val_note_prefix")) + " " + escapeHtml(s.validation_note) + "</div>"
      : "";
    const valErrHtml = hasErr
      ? '<div class="val-err">⚠ ' + escapeHtml(t("val_err_prefix")) + " " + escapeHtml(s.validation_error) + "</div>"
      : "";

    tbl += "<tr>" +
      '<td><input type="checkbox" class="chk-' + cardId + '" data-idx="' + sIdx + '" ' + checkedAttr +
      ' onchange="syncSugCheckbox(\'' + cardId + '\', ' + sIdx + ', this.checked)" /></td>' +
      "<td><strong>" + escapeHtml(s.label || s.key) + "</strong>" + slotBadge + catBadge +
      '<br/><code style="font-size:10.5px;">' + escapeHtml(s.key) + "</code>" + valNoteHtml + valErrHtml + "</td>" +
      '<td><span class="val-old">' + escapeHtml(curVal) + '</span> → <span class="val-new">' + escapeHtml(s.value) + "</span></td>" +
      '<td style="color:var(--text-muted)">' + escapeHtml(s.reason || "") + "</td>" +
      "</tr>";

    stacked += '<div class="sug-stack-item">' +
      '<div class="sug-stack-top">' +
      '<input type="checkbox" class="chk-stack-' + cardId + '" data-idx="' + sIdx + '" ' + checkedAttr +
      ' onchange="syncSugCheckbox(\'' + cardId + '\', ' + sIdx + ', this.checked)" />' +
      '<div><strong>' + escapeHtml(s.label || s.key) + "</strong>" + slotBadge + catBadge +
      ' <code style="font-size:10.5px;">' + escapeHtml(s.key) + "</code></div></div>" +
      '<div class="sug-stack-vals"><span class="val-old">' + escapeHtml(curVal) + '</span> → <span class="val-new">' + escapeHtml(s.value) + "</span></div>" +
      (s.reason ? ('<div class="sug-stack-reason">' + escapeHtml(s.reason) + "</div>") : "") +
      valNoteHtml + valErrHtml +
      "</div>";
  });

  tbl += "</tbody></table>";
  stacked += "</div>";
  card.innerHTML = head + tbl + stacked;
  return card;
}

function _formatUnifiedDiffHtml(diffText) {
  const raw = String(diffText || "").trim();
  if (!raw) {
    return '<span class="diff-line-ctx">' + escapeHtml(t("gcode_diff_empty")) + "</span>";
  }
  return raw.split(/\r?\n/).map(function (line) {
    if (line.startsWith("+++") || line.startsWith("---")) {
      return '<span class="diff-line-hunk">' + escapeHtml(line) + "</span>";
    }
    if (line.startsWith("+")) {
      return '<span class="diff-line-add">' + escapeHtml(line) + "</span>";
    }
    if (line.startsWith("-")) {
      return '<span class="diff-line-del">' + escapeHtml(line) + "</span>";
    }
    if (line.startsWith("@@")) {
      return '<span class="diff-line-hunk">' + escapeHtml(line) + "</span>";
    }
    return '<span class="diff-line-ctx">' + escapeHtml(line) + "</span>";
  }).join("");
}

function _buildGcodeSafetyCard(m, msgIdx) {
  const cardId = "gc_" + msgIdx;
  LAST_GCODE_MAP[cardId] = m.gcode_changes;
  const appliedRecId = APPLIED_CARD_RECORDS[cardId] || "";

  const card = document.createElement("div");
  card.className = "gcode-diff-card";
  card.id = "card_" + cardId;

  let html = '<div class="gcode-diff-head">' +
    "<span>" + escapeHtml(t("gcode_card_title", { n: m.gcode_changes.length })) + "</span>";
  if (appliedRecId) {
    html += '<div class="settings-apply-actions">' +
      '<span class="c-badge ok">' + escapeHtml(t("btn_applied_done")) + "</span>" +
      '<button type="button" class="btn btn-warn btn-sm" onclick="undoApplyRecord(\'' + escapeHtml(appliedRecId) + '\', \'' + cardId + '\')">' +
      escapeHtml(t("btn_undo_apply")) + "</button></div>";
  }
  html += "</div>";

  m.gcode_changes.forEach(function (gc, idx) {
    const slotBadge = (gc.category === "filament" || (gc.slot && Number(gc.slot) > 1))
      ? '<span class="slot-pill">' + escapeHtml(t("badge_slot", { n: gc.slot || 1 })) + "</span>"
      : "";
    const catBadge = _catBadgeHtml(gc.category);
    const warnings = Array.isArray(gc.lint_warnings) ? gc.lint_warnings : [];

    let lintHtml = '<div class="gcode-lint-list">';
    if (!warnings.length) {
      lintHtml += '<div class="warn-box ok" style="margin:0;">' + escapeHtml(t("gcode_no_warnings")) + "</div>";
    } else {
      warnings.forEach(function (w) {
        const cls = w.level === "danger" ? "danger" : "";
        lintHtml += '<div class="warn-box ' + cls + '" style="margin:0;">⚠ ' + escapeHtml(w.text || w.message || "") + "</div>";
      });
    }
    lintHtml += "</div>";

    html += '<div class="gcode-diff-item">' +
      '<div class="gcode-diff-item-head">' +
      '<input type="checkbox" class="chk-gc-' + cardId + '" data-idx="' + idx + '" checked />' +
      "<strong>" + escapeHtml(gc.label || gc.key) + "</strong>" + slotBadge + catBadge +
      ' <code style="font-size:11px;">' + escapeHtml(gc.key) + "</code>" +
      "</div>" +
      (gc.reason ? ('<div class="hint-text" style="margin-bottom:4px;">' + escapeHtml(gc.reason) + "</div>") : "") +
      '<pre class="gcode-diff-pre">' + _formatUnifiedDiffHtml(gc.diff || "") + "</pre>" +
      '<div class="hint-text" style="font-weight:700; margin-top:4px;">' + escapeHtml(t("gcode_safety_title")) + "</div>" +
      lintHtml +
      "</div>";
  });

  html += '<div class="gcode-confirm-bar">' +
    '<label class="gcode-confirm-chk">' +
    '<input type="checkbox" id="confirm_' + cardId + '" onchange="onGcodeConfirmToggle(\'' + cardId + '\')" />' +
    "<span>" + escapeHtml(t("gcode_confirm_label")) + "</span>" +
    "</label>" +
    '<button type="button" class="btn btn-warn btn-sm" id="applyBtn_' + cardId + '" disabled onclick="applyGcodeChanges(\'' + cardId + '\')">' +
    escapeHtml(t("btn_apply_gcode")) + "</button>" +
    "</div>";

  card.innerHTML = html;
  return card;
}

function onGcodeConfirmToggle(cardId) {
  const chk = document.getElementById("confirm_" + cardId);
  const btn = document.getElementById("applyBtn_" + cardId);
  if (btn) btn.disabled = !(chk && chk.checked);
}

function applyGcodeChanges(cardId) {
  const chk = document.getElementById("confirm_" + cardId);
  if (!chk || !chk.checked) {
    showToast(t("toast_confirm_gcode"), true);
    return;
  }
  const list = LAST_GCODE_MAP[cardId] || [];
  const selected = [];
  document.querySelectorAll(".chk-gc-" + cardId).forEach(function (cb) {
    if (cb.checked) {
      const idx = parseInt(cb.getAttribute("data-idx"), 10);
      if (list[idx]) selected.push(list[idx]);
    }
  });
  if (!selected.length) {
    showToast(t("toast_select_one"), true);
    return;
  }
  PENDING_APPLY_CARD_ID = cardId;
  sendAction("apply_settings", { changes: selected, allow_gcode: true, card_id: cardId });
}

function syncSugCheckbox(cardId, idx, checked) {
  document.querySelectorAll(".chk-" + cardId + '[data-idx="' + idx + '"], .chk-stack-' + cardId + '[data-idx="' + idx + '"]').forEach(function (cb) {
    cb.checked = checked;
  });
}

function toggleAllSug(cardId, checked) {
  document.querySelectorAll(".chk-" + cardId + ", .chk-stack-" + cardId).forEach(function (cb) {
    cb.checked = checked;
  });
}

function applySelectedSuggestions(cardId) {
  const list = LAST_SUGGESTIONS_MAP[cardId] || [];
  const selected = [];
  document.querySelectorAll(".chk-" + cardId).forEach(function (cb) {
    if (cb.checked) {
      const idx = parseInt(cb.getAttribute("data-idx"), 10);
      if (list[idx]) selected.push(list[idx]);
    }
  });
  if (!selected.length) {
    showToast(t("toast_select_one"), true);
    return;
  }
  PENDING_APPLY_CARD_ID = cardId;
  sendAction("apply_settings", { changes: selected, card_id: cardId });
}

function undoApplyRecord(recordId, cardId) {
  if (cardId) delete APPLIED_CARD_RECORDS[cardId];
  sendAction("undo_apply", { record_id: recordId });
}

function renderChats() {
  const sList = document.getElementById("sessionList");
  const dList = document.getElementById("drawerSessionList");
  const mArea = document.getElementById("messagesArea");
  const sessions = (STATE.chats && STATE.chats.sessions) || [];
  const activeId = STATE.chats && STATE.chats.active_id;

  _renderSessionListInto(sList, sessions, activeId, false);
  _renderSessionListInto(dList, sessions, activeId, true);

  if (!mArea) return;
  const activeSession = sessions.find(function (s) { return s.id === activeId; }) || sessions[0];
  const msgs = (activeSession && activeSession.messages) || [];
  mArea.innerHTML = "";
  LAST_SUGGESTIONS_MAP = {};
  LAST_GCODE_MAP = {};

  if (!msgs.length) {
    mArea.innerHTML =
      '<div class="card welcome-card">' +
      "<h3>" + escapeHtml(t("welcome_title")) + "</h3>" +
      "<p>" + t("welcome_desc") + "</p>" +
      '<div class="welcome-actions">' +
      '<button class="btn btn-warn" onclick="toggleKeyDrawer(true)">' + escapeHtml(t("welcome_btn_key")) + "</button>" +
      '<button class="btn btn-primary" onclick="runQuickPrompt(\'full_audit\')">' + escapeHtml(t("q_full_audit")) + "</button>" +
      '<button class="btn" onclick="switchTab(\'preflight\')">' + escapeHtml(t("welcome_btn_preflight")) + "</button>" +
      '<button class="btn" onclick="switchTab(\'wizards\')">' + escapeHtml(t("welcome_btn_wizards")) + "</button>" +
      "</div></div>";
    return;
  }

  msgs.forEach(function (m, msgIdx) {
    const row = document.createElement("div");
    row.className = "msg-row " + (m.role === "user" ? "user" : "assistant");

    const meta = document.createElement("div");
    meta.className = "msg-meta";
    meta.textContent = (m.role === "user" ? t("you_label") : ("🤖 " + (m.model || t("ai_label")))) +
      (m.timestamp ? " • " + m.timestamp : "");

    const bubble = document.createElement("div");
    bubble.className = "msg-bubble";

    const imgName = (m.image_meta && m.image_meta.name) || m.image_name || "";
    if (imgName) {
      const imgTag = document.createElement("div");
      imgTag.className = "msg-photo-tag";
      imgTag.textContent = t("msg_photo_attached", { name: imgName });
      bubble.appendChild(imgTag);
    }

    const reasoningText = m.reasoning || m.thinking || "";
    if (m.role !== "user" && reasoningText) {
      const details = document.createElement("details");
      details.className = "thinking-box";
      details.innerHTML = "<summary>" + escapeHtml(t("thinking_label")) + "</summary>" +
        '<div class="thinking-content">' + escapeHtml(reasoningText) + "</div>";
      bubble.appendChild(details);
    }

    const bodyDiv = document.createElement("div");
    bodyDiv.innerHTML = renderMarkdown(m.content || "");
    bubble.appendChild(bodyDiv);

    if (m.parse_error) {
      const errBanner = document.createElement("div");
      errBanner.className = "warn-box danger";
      errBanner.style.marginTop = "8px";
      errBanner.textContent = t("parse_error_banner", { err: m.parse_error });
      bubble.appendChild(errBanner);
    }

    if (Array.isArray(m.suggestions) && m.suggestions.length) {
      bubble.appendChild(_buildSuggestionsCard(m, msgIdx));
    }

    if (Array.isArray(m.gcode_changes) && m.gcode_changes.length) {
      bubble.appendChild(_buildGcodeSafetyCard(m, msgIdx));
    }

    row.appendChild(meta);
    row.appendChild(bubble);
    mArea.appendChild(row);
  });

  mArea.scrollTop = mArea.scrollHeight;
}

/* ==================== IMAGE RESIZE (<canvas>), PASTE & DRAG-DROP ==================== */
function resizeImageFile(file, callback) {
  if (!file) return;
  const maxDim = 1600;
  const reader = new FileReader();
  reader.onload = function (ev) {
    const rawDataUrl = String(ev.target.result || "");
    const img = new Image();
    img.onload = function () {
      let w = img.naturalWidth || img.width;
      let h = img.naturalHeight || img.height;
      let resized = false;
      if (w > maxDim || h > maxDim) {
        const scale = Math.min(maxDim / w, maxDim / h);
        w = Math.max(1, Math.round(w * scale));
        h = Math.max(1, Math.round(h * scale));
        resized = true;
      }
      try {
        const canvas = document.createElement("canvas");
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(img, 0, 0, w, h);
        const jpegUrl = canvas.toDataURL("image/jpeg", 0.85);
        const parts = jpegUrl.split(",");
        callback({
          name: file.name || "clipboard.jpg",
          mime: "image/jpeg",
          base64: parts[1] || "",
          dataUrl: jpegUrl,
          width: w,
          height: h,
          resized: resized
        });
      } catch (_err) {
        const parts = rawDataUrl.split(",");
        const mimeMatch = parts[0].match(/data:([^;]+);base64/);
        callback({
          name: file.name || "image.jpg",
          mime: mimeMatch ? mimeMatch[1] : (file.type || "image/jpeg"),
          base64: parts[1] || "",
          dataUrl: rawDataUrl,
          width: w,
          height: h,
          resized: false
        });
      }
    };
    img.onerror = function () {
      const parts = rawDataUrl.split(",");
      if (parts.length === 2) {
        const mimeMatch = parts[0].match(/data:([^;]+);base64/);
        callback({
          name: file.name || "image.jpg",
          mime: mimeMatch ? mimeMatch[1] : (file.type || "image/jpeg"),
          base64: parts[1],
          dataUrl: rawDataUrl,
          width: 0,
          height: 0,
          resized: false
        });
      }
    };
    img.src = rawDataUrl;
  };
  reader.readAsDataURL(file);
}

function attachResizedImage(imgObj, target) {
  if (!imgObj || !imgObj.base64) return;
  const note = imgObj.resized ? (" (" + t("img_resized_note", { w: imgObj.width, h: imgObj.height }) + ")") : "";
  const payload = {
    name: imgObj.name,
    mime: imgObj.mime,
    base64: imgObj.base64
  };

  if (target === "defect") {
    DEFECT_IMAGE = payload;
    const lbl = document.getElementById("defectAttachmentLabel");
    const thumb = document.getElementById("defectAttachmentThumb");
    const bar = document.getElementById("defectAttachmentBar");
    if (lbl) lbl.textContent = "📷 " + imgObj.name + note;
    if (thumb && imgObj.dataUrl) {
      thumb.src = imgObj.dataUrl;
      thumb.style.display = "block";
    }
    if (bar) bar.style.display = "flex";
  } else {
    ATTACHED_IMAGE = payload;
    const lbl = document.getElementById("attachmentLabel");
    const thumb = document.getElementById("attachmentThumb");
    const bar = document.getElementById("attachmentBar");
    if (lbl) lbl.textContent = "📷 " + imgObj.name + note;
    if (thumb && imgObj.dataUrl) {
      thumb.src = imgObj.dataUrl;
      thumb.style.display = "block";
    }
    if (bar) bar.style.display = "flex";
  }
}

function onPhotoSelected(e, target) {
  const file = e.target.files && e.target.files[0];
  e.target.value = "";
  if (!file) return;
  resizeImageFile(file, function (res) {
    attachResizedImage(res, target || "chat");
  });
}

function clearAttachment() {
  ATTACHED_IMAGE = null;
  const inp = document.getElementById("photoInput");
  if (inp) inp.value = "";
  const bar = document.getElementById("attachmentBar");
  if (bar) bar.style.display = "none";
}

function _handleGcodeFile(file) {
  if (!file || STATE.busy) return;
  const maxBytes = 15 * 1024 * 1024;
  if (file.size > maxBytes) {
    showToast(t("toast_gcode_too_large", { mb: (file.size / (1024 * 1024)).toFixed(1) }), true);
    return;
  }
  const reader = new FileReader();
  reader.onload = function (ev) {
    const reqId = genRequestId();
    ACTIVE_REQUEST_ID = reqId;
    ACTIVE_STREAM_CHAT_ID = (STATE.chats && STATE.chats.active_id) || "";
    setBusy(true, t("status_working"));
    sendAction("audit_gcode_content", {
      filename: file.name,
      content: String(ev.target.result || ""),
      request_id: reqId
    });
  };
  reader.readAsText(file);
}

function onGcodeFilePicked(e) {
  const file = e.target.files && e.target.files[0];
  e.target.value = "";
  _handleGcodeFile(file);
}

function onAuditLastSliceClick() {
  if (STATE.busy) return;
  if (STATE.last_slice) {
    if (!hasKeyForCurrent()) {
      toggleKeyDrawer(true);
      showToast(t("toast_enter_key_first"), true);
      return;
    }
    const reqId = genRequestId();
    ACTIVE_REQUEST_ID = reqId;
    ACTIVE_STREAM_CHAT_ID = (STATE.chats && STATE.chats.active_id) || "";
    setBusy(true, t("status_working"));
    switchTab("chat");
    sendAction("audit_last_slice", { request_id: reqId });
  } else {
    showToast(t("toast_no_last_slice"));
    const inp = document.getElementById("gcodeFileInput");
    if (inp) inp.click();
  }
}

/* ==================== SLASH COMMANDS ==================== */
function onChatInputChange() {
  const inp = document.getElementById("chatInput");
  const menu = document.getElementById("slashMenu");
  if (!inp || !menu) return;
  const val = inp.value;
  if (!val.startsWith("/") || val.includes(" ") || val.includes("\n")) {
    menu.classList.remove("open");
    return;
  }
  const q = val.toLowerCase();
  const matches = SLASH_COMMANDS.filter(function (c) { return c.cmd.startsWith(q); });
  if (!matches.length) {
    menu.classList.remove("open");
    return;
  }
  let html = '<div class="slash-menu-head">' + escapeHtml(t("slash_title")) + "</div>";
  matches.forEach(function (c) {
    html += '<div class="slash-item" onclick="pickSlashCommand(\'' + c.cmd + '\')">' +
      "<code>" + escapeHtml(c.cmd) + "</code>" +
      "<span>" + escapeHtml(t(c.descKey)) + "</span></div>";
  });
  menu.innerHTML = html;
  menu.classList.add("open");
}

function pickSlashCommand(cmd) {
  const inp = document.getElementById("chatInput");
  const menu = document.getElementById("slashMenu");
  if (menu) menu.classList.remove("open");
  if (inp) inp.value = "";
  sendMessage(cmd);
}

function _isLocalSlashCommand(text) {
  const first = String(text || "").trim().split(/\s+/)[0].toLowerCase();
  return SLASH_COMMANDS.some(function (c) { return c.cmd === first; });
}

/* ==================== BUSY / SEND / STOP ==================== */
function updateSendButtonUI() {
  const btn = document.getElementById("btnSend");
  const statusEl = document.getElementById("statusLine");
  if (btn) {
    if (STATE.busy) {
      btn.className = "btn btn-stop";
      btn.disabled = false;
      btn.textContent = t("btn_stop");
    } else {
      btn.className = "btn btn-primary";
      btn.disabled = false;
      btn.textContent = t("btn_send");
    }
  }
  if (statusEl && !STATE.busy) {
    statusEl.textContent = t("status_ready");
  }
}

function setBusy(isBusy, statusText) {
  STATE.busy = !!isBusy;
  updateSendButtonUI();
  const statusEl = document.getElementById("statusLine");
  if (statusEl) {
    statusEl.textContent = statusText || (STATE.busy ? t("status_working") : t("status_ready"));
  }
}

function onSendOrStopClick() {
  if (STATE.busy) {
    stopGeneration();
  } else {
    sendMessage();
  }
}

function stopGeneration() {
  if (!STATE.busy) return;
  const statusEl = document.getElementById("statusLine");
  if (statusEl) statusEl.textContent = t("status_stopping");
  sendAction("stop_generation", {
    request_id: ACTIVE_REQUEST_ID || "",
    chat_id: ACTIVE_STREAM_CHAT_ID || (STATE.chats && STATE.chats.active_id) || ""
  });
}

function onChatKeydown(e) {
  if (e.key === "Escape") {
    const menu = document.getElementById("slashMenu");
    if (menu) menu.classList.remove("open");
    return;
  }
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    if (!STATE.busy) sendMessage();
  }
}

function _mentionsCustomGcode(text) {
  return /\b(start\s*g-?code|end\s*g-?code|layer\s*g-?code|machine_start_gcode|machine_end_gcode|filament_start_gcode|filament_end_gcode|change_filament_gcode)\b|стартов\w*\s+g-?code|конечн\w*\s+g-?code|початков\w*\s+g-?code|кінце\w*\s+g-?code/i.test(text);
}

function sendMessage(overrideText, forceIncludeGcode) {
  if (STATE.busy) return;
  const inp = document.getElementById("chatInput");
  const menu = document.getElementById("slashMenu");
  if (menu) menu.classList.remove("open");

  const text = (overrideText !== undefined ? overrideText : (inp ? inp.value : "")).trim();
  if (!text) return;

  const isLocalSlash = _isLocalSlashCommand(text);
  if (!isLocalSlash && !hasKeyForCurrent()) {
    toggleKeyDrawer(true);
    const keyInp = document.getElementById("inlineApiKeyInput");
    if (keyInp) keyInp.focus();
    showToast(t("toast_enter_key_first"), true);
    return;
  }

  if (overrideText === undefined && inp) inp.value = "";

  const prov = STATE.settings.provider || document.getElementById("topProviderSelect").value;
  const model = STATE.settings.model || document.getElementById("topModelSelect").value;
  const attachCtx = document.getElementById("chkAutoContext").checked;
  const includeGcode = !!(forceIncludeGcode || document.getElementById("chkIncludeGcode").checked || _mentionsCustomGcode(text));
  const reqId = genRequestId();

  ACTIVE_REQUEST_ID = reqId;
  ACTIVE_STREAM_CHAT_ID = (STATE.chats && STATE.chats.active_id) || "";
  STREAM_THINKING_OPEN = false;

  if (!isLocalSlash) {
    setBusy(true, t("status_working"));
  }

  sendAction("send_chat", {
    text: text,
    chat_id: ACTIVE_STREAM_CHAT_ID,
    provider: prov,
    model: model,
    reasoning_effort: STATE.settings.reasoning_effort || "low",
    attach_context: attachCtx,
    include_gcode: includeGcode,
    image: ATTACHED_IMAGE,
    request_id: reqId
  });
  clearAttachment();
}

function runQuickPrompt(kind) {
  const map = {
    full_audit: t("prompt_full_audit"),
    orientation_supports: t("prompt_supports"),
    strength_functional: t("prompt_strength"),
    quality_surface: t("prompt_quality"),
    speed_optimize: t("prompt_speed"),
    filament_check: t("prompt_filament")
  };
  switchTab("chat");
  sendMessage(map[kind] || map.full_audit);
}

/* ==================== HOST MESSAGE DISPATCHER ==================== */
function _applyOptionalStateFields(msg) {
  if (msg.providers) STATE.providers = msg.providers;
  if (msg.plate) STATE.plate = msg.plate;
  if (msg.presets) STATE.presets = msg.presets;
  if (msg.preflight) STATE.preflight = msg.preflight;
  if (msg.last_slice !== undefined) STATE.last_slice = msg.last_slice;
  if (msg.slice_delta !== undefined) STATE.slice_delta = msg.slice_delta;
  if (msg.snapshots) STATE.snapshots = msg.snapshots;
  if (msg.apply_history) STATE.apply_history = msg.apply_history;
  if (msg.usage) STATE.usage = msg.usage;
  if (msg.mcp) STATE.mcp = msg.mcp;
}

function handleHostPayload(msg) {
  if (!msg || typeof msg !== "object") return;

  if (msg.type === "full_state") {
    STATE.settings = Object.assign({}, STATE.settings, msg.settings || {});
    STATE.chats = msg.chats || STATE.chats;
    _applyOptionalStateFields(msg);
    applyStaticI18n();
    populateProvidersUI();
    renderContextAndInspector();
    renderChats();
    if (msg.active_request_id) {
      ACTIVE_REQUEST_ID = msg.active_request_id;
      ACTIVE_STREAM_CHAT_ID = msg.active_stream_chat_id || (STATE.chats && STATE.chats.active_id) || "";
      setBusy(true, t("status_working"));
    } else {
      ACTIVE_REQUEST_ID = null;
      ACTIVE_STREAM_CHAT_ID = null;
      setBusy(false, t("status_ready"));
    }
    if (!hasKeyForCurrent()) {
      toggleKeyDrawer(true);
    }
  } else if (msg.type === "settings_updated") {
    if (msg.settings) {
      STATE.settings = Object.assign({}, STATE.settings, msg.settings);
    }
    _applyOptionalStateFields(msg);
    applyStaticI18n();
    populateProvidersUI();
    renderUsageMeter();
    if (msg.toast) showToast(msg.toast);
  } else if (msg.type === "context_updated") {
    _applyOptionalStateFields(msg);
    renderContextAndInspector();
    if (msg.toast) showToast(msg.toast);
  } else if (msg.type === "stream_chunk") {
    // Race-free check: verify request_id and active chat_id (fixes P0 #2)
    if (ACTIVE_REQUEST_ID && msg.request_id && msg.request_id !== ACTIVE_REQUEST_ID) {
      return;
    }
    const activeChatId = STATE.chats && STATE.chats.active_id;
    if (msg.chat_id && activeChatId && msg.chat_id !== activeChatId) {
      return;
    }

    const mArea = document.getElementById("messagesArea");
    if (!mArea) return;
    const nearBottom = (mArea.scrollHeight - mArea.scrollTop - mArea.clientHeight) < 120;

    let row = document.getElementById("streamingBubbleRow");
    if (!row) {
      row = document.createElement("div");
      row.id = "streamingBubbleRow";
      row.className = "msg-row assistant";
      row.innerHTML =
        '<div class="msg-meta">🤖 ' + escapeHtml(msg.model || t("ai_label")) + " ⏳</div>" +
        '<div class="msg-bubble">' +
        '<details class="thinking-box" id="streamingThinkingBox" style="display:none;">' +
        "<summary>" + escapeHtml(t("thinking_label")) + "…</summary>" +
        '<div class="thinking-content" id="streamingThinkingBody"></div>' +
        "</details>" +
        '<div id="streamingBubbleBody"></div>' +
        "</div>";
      mArea.appendChild(row);
      const tb = document.getElementById("streamingThinkingBox");
      if (tb) {
        tb.addEventListener("toggle", function () {
          STREAM_THINKING_OPEN = tb.open;
        });
      }
    }

    const thinkBox = document.getElementById("streamingThinkingBox");
    const thinkBody = document.getElementById("streamingThinkingBody");
    if (msg.thinking && thinkBox && thinkBody) {
      thinkBox.style.display = "block";
      thinkBox.open = STREAM_THINKING_OPEN;
      thinkBody.textContent = String(msg.thinking);
    }

    const bodyEl = document.getElementById("streamingBubbleBody");
    if (bodyEl && msg.text !== undefined) {
      bodyEl.innerHTML = renderMarkdown(msg.text || "");
    }
    if (nearBottom) {
      mArea.scrollTop = mArea.scrollHeight;
    }
  } else if (msg.type === "chats_updated") {
    STATE.chats = msg.chats || STATE.chats;
    _applyOptionalStateFields(msg);
    renderContextAndInspector();
    renderUsageMeter();
    renderChats();

    // Fixes P0 #1: ONLY clear busy when backend signals no active_request_id!
    if (msg.active_request_id) {
      ACTIVE_REQUEST_ID = msg.active_request_id;
      if (msg.active_stream_chat_id || msg.chat_id) {
        ACTIVE_STREAM_CHAT_ID = msg.active_stream_chat_id || msg.chat_id;
      }
      setBusy(true, t("status_working"));
    } else {
      ACTIVE_REQUEST_ID = null;
      ACTIVE_STREAM_CHAT_ID = null;
      setBusy(false, msg.cancelled ? t("status_cancelled") : t("status_ready"));
    }
  } else if (msg.type === "models_loaded") {
    if (msg.ok) {
      if (msg.settings) STATE.settings = Object.assign({}, STATE.settings, msg.settings);
      populateProvidersUI();
      showToast(t("toast_models_loaded", { n: msg.count || 0 }));
    } else {
      if (msg.needs_key) {
        toggleKeyDrawer(true);
        const inp = document.getElementById("inlineApiKeyInput");
        if (inp) inp.focus();
      }
      showToast(msg.error || "Error", true);
    }
  } else if (msg.type === "settings_applied") {
    _applyOptionalStateFields(msg);
    const isUndo = !!(msg.undone || msg.is_undo);
    if (isUndo && msg.record_id) {
      Object.keys(APPLIED_CARD_RECORDS).forEach(function (cid) {
        if (APPLIED_CARD_RECORDS[cid] === msg.record_id) {
          delete APPLIED_CARD_RECORDS[cid];
        }
      });
    } else {
      const targetCardId = msg.card_id || PENDING_APPLY_CARD_ID;
      PENDING_APPLY_CARD_ID = null;
      if (msg.ok && msg.record_id && targetCardId) {
        APPLIED_CARD_RECORDS[targetCardId] = msg.record_id;
      }
    }
    renderContextAndInspector();
    renderChats();

    const appliedCount = Array.isArray(msg.applied) ? msg.applied.length : 0;
    const errList = Array.isArray(msg.errors) ? msg.errors : [];
    if (isUndo) {
      showToast(t("toast_undo_done", { n: appliedCount }));
    } else if (msg.ok && !errList.length) {
      showToast(t("toast_settings_applied", { n: appliedCount }));
    } else if (appliedCount > 0 && errList.length > 0) {
      showToast(t("toast_settings_partial", { ok: appliedCount, err: errList.length }) + " — " + errList.join("; "), true);
    } else {
      showToast("⚠ " + errList.join("; "), true);
    }
  } else if (msg.type === "snapshots_updated") {
    if (msg.snapshots) STATE.snapshots = msg.snapshots;
    if (msg.presets) STATE.presets = msg.presets;
    if (msg.preflight) STATE.preflight = msg.preflight;
    renderContextAndInspector();
    if (msg.toast) showToast(msg.toast, !!msg.is_error);
  } else if (msg.type === "calibration_result") {
    renderCalibrationResult(msg.result || msg);
  } else if (msg.type === "mcp_status_updated") {
    if (msg.settings) {
      STATE.settings = Object.assign({}, STATE.settings, msg.settings);
    }
    if (msg.mcp) STATE.mcp = msg.mcp;
    renderMcpSection();
  } else if (msg.type === "toast") {
    if (msg.clear_busy) {
      ACTIVE_REQUEST_ID = null;
      ACTIVE_STREAM_CHAT_ID = null;
      setBusy(false, t("status_ready"));
    }
    showToast(msg.text || "", !!msg.is_error);
  }
}

/* ==================== GLOBAL EVENTS (PASTE, DRAG-DROP, BOOT) ==================== */
function _initDragAndPaste() {
  // Clipboard Ctrl+V image paste
  document.addEventListener("paste", function (e) {
    const items = (e.clipboardData && e.clipboardData.items) || [];
    for (let i = 0; i < items.length; i++) {
      if (items[i].type && items[i].type.indexOf("image/") === 0) {
        const blob = items[i].getAsFile();
        if (blob) {
          e.preventDefault();
          const target = (ACTIVE_TAB === "wizards" && ACTIVE_WIZARD_SUB === "defect") ? "defect" : "chat";
          resizeImageFile(blob, function (res) {
            attachResizedImage(res, target);
          });
          return;
        }
      }
    }
  });

  // Prevent browser navigation on file drop anywhere
  ["dragover", "drop"].forEach(function (evName) {
    window.addEventListener(evName, function (e) { e.preventDefault(); }, true);
  });

  const zone = document.getElementById("chatDropZone");
  const overlay = document.getElementById("dropOverlay");
  if (!zone || !overlay) return;
  let dragDepth = 0;

  zone.addEventListener("dragenter", function (e) {
    e.preventDefault();
    dragDepth++;
    overlay.classList.add("active");
  });
  zone.addEventListener("dragleave", function (e) {
    e.preventDefault();
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) overlay.classList.remove("active");
  });
  zone.addEventListener("drop", function (e) {
    e.preventDefault();
    dragDepth = 0;
    overlay.classList.remove("active");
    const files = (e.dataTransfer && e.dataTransfer.files) || [];
    if (!files.length) return;
    const f = files[0];
    if (f.type && f.type.indexOf("image/") === 0) {
      resizeImageFile(f, function (res) {
        attachResizedImage(res, "chat");
      });
    } else if (/\.(gcode|gco|g)$/i.test(f.name || "")) {
      _handleGcodeFile(f);
    }
  });
}

window.onHostMessage = handleHostPayload;
if (window.orca && typeof window.orca.onMessage === "function") {
  window.orca.onMessage(handleHostPayload);
}

window.addEventListener("DOMContentLoaded", function () {
  applyStaticI18n();
  _initDragAndPaste();
  sendAction("init");
});
