/* DataInsight frontend: a small, zero-build v2 workspace. */
(function () {
  "use strict";

  const App = {
    sessionId: null,
    sources: [],
    snapshots: [],
    columns: [],
    lineage: [],
    plan: null,
    results: null,
    pins: [],
    pollingTimer: null,
  };
  const SESSION_KEY = "datainsight.sessionId";
  const $ = (selector) => document.querySelector(selector);
  const dom = {};

  class ApiError extends Error {
    constructor(message, status, detail) {
      super(message);
      this.status = status;
      this.detail = detail;
    }
  }

  function cacheDom() {
    dom.sessionDot = $("#session-dot");
    dom.sessionId = $("#session-id");
    dom.btnNew = $("#btn-new-session");
    dom.uploadZone = $("#upload-zone");
    dom.uploadEmpty = $("#upload-empty");
    dom.uploadFile = $("#upload-file");
    dom.fileName = $("#file-name");
    dom.fileShape = $("#file-shape");
    dom.fileInput = $("#file-input");
    dom.uploadError = $("#upload-error");
    dom.sourcesList = $("#sources-list");
    dom.columnList = $("#column-list");
    dom.workspaceArea = $("#workspace-area");
    dom.btnAddUnit = $("#btn-add-unit");
    dom.addUnitOperation = $("#add-unit-operation");
    dom.btnGenPlan = $("#btn-generate-plan");
    dom.btnExecute = $("#btn-execute");
    dom.execBadge = $("#exec-status-badge");
    dom.execSpinner = $("#exec-spinner");
    dom.executionSummary = $("#execution-summary");
    dom.resultsArea = $("#results-area");
    dom.resultsList = $("#results-list");
    dom.dialogueMessages = $("#dialogue-messages");
    dom.dialogueInput = $("#dialogue-input");
    dom.dialogueSend = $("#dialogue-send");
    dom.dashboardGrid = $("#dashboard-grid");
    dom.btnGenReport = $("#btn-generate-report");
    dom.reportOutput = $("#report-output");
  }

  function detailMessage(detail) {
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object") {
      const messages = Array.isArray(detail.issues)
        ? detail.issues.map((issue) => issue.message).filter(Boolean)
        : [];
      if (messages.length) return `${detail.message || detail.code}: ${messages.join("; ")}`;
      return detail.message || detail.code || JSON.stringify(detail);
    }
    return "Unknown error";
  }

  async function api(path, opts = {}) {
    if (!App.sessionId && !path.startsWith("/api/sessions")) {
      throw new Error("No session");
    }
    const base = `/api/sessions/${App.sessionId}`;
    const url = path.startsWith("/api/sessions") ? path : `${base}${path}`;
    const config = { headers: {}, ...opts };
    if (config.body && typeof config.body === "object" && !(config.body instanceof FormData)) {
      config.headers["Content-Type"] = "application/json";
      config.body = JSON.stringify(config.body);
    }
    const response = await fetch(url, config);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      const error = new ApiError(detailMessage(body.detail || response.statusText), response.status, body.detail);
      throw error;
    }
    return response.json();
  }

  function activateSession(sessionId) {
    App.sessionId = sessionId;
    localStorage.setItem(SESSION_KEY, sessionId);
    const url = new URL(window.location.href);
    url.searchParams.set("session", sessionId);
    history.replaceState(null, "", url);
    dom.sessionId.textContent = sessionId.slice(0, 8);
    dom.sessionDot.style.background = "var(--success)";
  }

  async function createSession() {
    const response = await fetch("/api/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_requirement: "" }),
    });
    if (!response.ok) throw new Error("Unable to create session");
    activateSession((await response.json()).session_id);
  }

  async function initSession() {
    const urlSession = new URLSearchParams(window.location.search).get("session");
    const savedSession = urlSession || localStorage.getItem(SESSION_KEY);
    if (!savedSession) {
      await createSession();
      return;
    }
    const response = await fetch(`/api/sessions/${encodeURIComponent(savedSession)}`);
    if (response.ok) {
      activateSession(savedSession);
      return;
    }
    if (response.status === 409) {
      const body = await response.json().catch(() => ({}));
      await createSession();
      showError("panel-left", `Saved session is incompatible. A new session was created. ${detailMessage(body.detail)}`);
      return;
    }
    await createSession();
  }

  async function newSession() {
    if (App.pollingTimer) clearInterval(App.pollingTimer);
    App.sources = [];
    App.snapshots = [];
    App.columns = [];
    App.lineage = [];
    App.plan = null;
    App.results = null;
    App.pins = [];
    await createSession();
    renderAll();
  }

  function initUpload() {
    const zone = dom.uploadZone;
    const input = dom.fileInput;
    zone.addEventListener("click", (event) => {
      if (event.target !== input) input.click();
    });
    zone.addEventListener("dragover", (event) => {
      event.preventDefault();
      zone.classList.add("drag-over");
    });
    zone.addEventListener("dragleave", () => zone.classList.remove("drag-over"));
    zone.addEventListener("drop", (event) => {
      event.preventDefault();
      zone.classList.remove("drag-over");
      uploadFiles(Array.from(event.dataTransfer.files || []));
    });
    input.addEventListener("change", () => {
      uploadFiles(Array.from(input.files || []));
      input.value = "";
    });
  }

  async function uploadFiles(files) {
    const accepted = files.filter((file) => /\.(csv|xlsx?|xls)$/i.test(file.name));
    if (!accepted.length) {
      showError("panel-left", "Choose at least one CSV or Excel file.");
      return;
    }
    dom.uploadError.classList.add("hidden");
    dom.uploadZone.classList.add("uploading");
    try {
      for (const file of accepted) {
        const form = new FormData();
        form.append("file", file);
        await api("/data/upload", { method: "POST", body: form });
      }
      await refreshData();
    } catch (error) {
      dom.uploadError.textContent = error.message;
      dom.uploadError.classList.remove("hidden");
    } finally {
      dom.uploadZone.classList.remove("uploading");
    }
  }

  async function refreshData() {
    const [sources, snapshots, columns, lineage] = await Promise.all([
      api("/data/sources"),
      api("/data/snapshots"),
      api("/data/columns"),
      api("/data/lineage"),
    ]);
    App.sources = sources.sources || [];
    App.snapshots = snapshots.snapshots || [];
    App.columns = (columns.columns || []).filter((column) => column.name !== "__di_row_id");
    App.lineage = lineage.columns || [];
    renderSources();
    renderColumns();
    renderWorkspace();
  }

  function renderSources() {
    const list = dom.sourcesList;
    if (!App.sources.length) {
      list.innerHTML = '<div class="empty-state">Upload one or more files to create Snapshots.</div>';
      dom.uploadEmpty.classList.remove("hidden");
      dom.uploadFile.classList.add("hidden");
      dom.uploadZone.classList.remove("has-file");
      return;
    }
    dom.uploadEmpty.classList.add("hidden");
    dom.uploadFile.classList.remove("hidden");
    dom.uploadZone.classList.add("has-file");
    dom.fileName.textContent = `${App.sources.length} source${App.sources.length === 1 ? "" : "s"}`;
    dom.fileShape.textContent = `${App.sources.reduce((sum, source) => sum + source.row_count, 0)} rows`;
    list.innerHTML = App.sources.map((source) => `
      <div class="source-card">
        <div class="source-card-header">
          <span class="source-name" title="${esc(source.display_name)}">${esc(source.display_name)}</span>
          <span class="source-count">${source.row_count} rows</span>
        </div>
        <div class="source-snapshot">Snapshot <code>${esc(source.snapshot_name)}</code></div>
        <div class="source-checkpoint">head ${esc(source.checkpoint_id)}</div>
      </div>`).join("");
  }

  function groupColumns(columns) {
    const groups = new Map();
    columns.forEach((column) => {
      const snapshot = column.snapshot || (column.ref || "").split(".")[0] || "source";
      if (!groups.has(snapshot)) groups.set(snapshot, []);
      groups.get(snapshot).push(column);
    });
    return groups;
  }

  function renderColumns() {
    if (!App.columns.length) {
      dom.columnList.innerHTML = '<div class="empty-state">Upload a file to see columns</div>';
      return;
    }
    const groups = groupColumns(App.columns);
    dom.columnList.innerHTML = Array.from(groups.entries()).map(([snapshot, columns]) => `
      <div class="column-group">
        <div class="column-group-title">Snapshot <code>${esc(snapshot)}</code></div>
        ${columns.map((column) => `
          <div class="column-item" draggable="true" data-column="${esc(column.ref)}">
            <span class="column-dtype">${esc(column.dtype || "?")}</span>
            <span class="column-details">
              <span class="column-name" title="${esc(column.ref)}">${esc(column.ref)}</span>
              ${renderColumnLineage(column.ref)}
            </span>
            <span class="column-null">${column.null_pct != null ? `${Number(column.null_pct).toFixed(1)}%` : ""}</span>
          </div>`).join("")}
      </div>`).join("");
    dom.columnList.querySelectorAll(".column-item").forEach((item) => {
      item.addEventListener("dragstart", (event) => {
        event.dataTransfer.setData("text/plain", item.dataset.column);
        event.dataTransfer.effectAllowed = "copy";
        item.classList.add("dragging");
      });
      item.addEventListener("dragend", () => item.classList.remove("dragging"));
    });
  }

  function renderColumnLineage(ref) {
    const record = App.lineage.find((column) => column.ref === ref);
    if (!record) return "";
    const direct = record.derived_from || [];
    const origins = record.origin_refs || [];
    if (direct.length) {
      return `<span class="column-origin" title="${esc(direct.join(", "))}">derived from ${esc(direct.join(", "))}</span>`;
    }
    if (origins.length) {
      return `<span class="column-origin" title="${esc(origins.join(", "))}">source ${esc(origins.join(", "))}</span>`;
    }
    return "";
  }

  function operationLabel(operation) {
    return {
      derive_column: "Derive",
      filter: "Filter",
      join: "Join",
      terminal: "Terminal",
      legacy: "Legacy",
    }[operation] || operation;
  }

  function localName(ref, snapshot) {
    const prefix = `${snapshot}.`;
    return ref && ref.startsWith(prefix) ? ref.slice(prefix.length) : ref;
  }

  function snapshotRefs() {
    const refs = {};
    App.snapshots.forEach((snapshot) => {
      refs[snapshot.name] = [...(snapshot.column_refs || [])];
    });
    const units = App.plan && App.plan.units ? [...App.plan.units].sort((a, b) => a.unit_id - b.unit_id) : [];
    units.forEach((unit) => {
      if (unit.operation === "derive_column") {
        const ref = (unit.output_columns || [])[0];
        if (ref) {
          const snapshot = unit.input_snapshot;
          refs[snapshot] = refs[snapshot] || [];
          if (!refs[snapshot].includes(ref)) refs[snapshot].push(ref);
        }
      } else if (unit.operation === "filter") {
        const sourceRefs = refs[unit.input_snapshot] || [];
        refs[unit.output_snapshot] = sourceRefs.map((ref) => `${unit.output_snapshot}.${localName(ref, unit.input_snapshot)}`);
      } else if (unit.operation === "join") {
        refs[unit.output_snapshot] = (unit.select || []).map((selected) => `${unit.output_snapshot}.${selected.as || selected.as_}`);
      }
    });
    return refs;
  }

  function snapshotNames() {
    return Object.keys(snapshotRefs());
  }

  function defaultDependencies() {
    const units = App.plan && App.plan.units ? [...App.plan.units].sort((a, b) => a.unit_id - b.unit_id) : [];
    const lastProducer = [...units].reverse().find((unit) => ["derive_column", "filter", "join"].includes(unit.operation));
    return lastProducer ? [lastProducer.unit_id] : [];
  }

  function aliasFor(ref, snapshot, duplicateSide) {
    const local = localName(ref, snapshot) || "column";
    return duplicateSide ? `${snapshot}_${local}`.replace(/[^A-Za-z0-9_-]/g, "_") : local;
  }

  function newUnitPayload(operation, unitId) {
    const refs = snapshotRefs();
    const names = Object.keys(refs);
    const snapshot = names[0] || "source";
    const firstRefs = refs[snapshot] || [];
    const depends = defaultDependencies();
    if (operation === "derive_column") {
      const inputs = firstRefs.slice(0, 2);
      return {
        operation, purpose: "Derive a useful metric", execution_mode: inputs.length >= 2 ? "template" : "llm",
        cautious: "", depends_on: depends, input_snapshot: snapshot,
        input_columns: inputs.length ? inputs : firstRefs.slice(0, 1),
        output_columns: [`${snapshot}.derived_${unitId}`],
        template_name: inputs.length >= 2 ? "column_arithmetic" : null,
        template_params: { operator: "*", new_column: `derived_${unitId}` },
      };
    }
    if (operation === "filter") {
      return {
        operation, purpose: "Filter a focused Snapshot", execution_mode: "template",
        cautious: "", depends_on: depends, input_snapshot: snapshot,
        input_columns: firstRefs.slice(0, 1), output_snapshot: `${snapshot}_filtered_${unitId}`,
        template_name: "filter_by_date", template_params: { condition: "" },
      };
    }
    if (operation === "join") {
      const right = names[1] || snapshot;
      const leftRefs = refs[snapshot] || [];
      const rightRefs = refs[right] || [];
      const common = leftRefs.find((left) => rightRefs.some((candidate) => localName(candidate, right) === localName(left, snapshot)));
      const leftKey = common || leftRefs[0] || `${snapshot}.key`;
      const rightKey = common ? rightRefs.find((candidate) => localName(candidate, right) === localName(common, snapshot)) : rightRefs[0] || `${right}.key`;
      const leftSelected = leftRefs[0] || leftKey;
      const rightSelected = rightRefs[0] || rightKey;
      const leftAlias = aliasFor(leftSelected, snapshot, false);
      const rightAlias = aliasFor(rightSelected, right, leftAlias === aliasFor(rightSelected, right, false));
      return {
        operation, purpose: "Join related Snapshots", execution_mode: "template",
        cautious: "Check key uniqueness and unmatched rows.", depends_on: depends,
        inputs: [{ role: "left", snapshot }, { role: "right", snapshot: right }],
        keys: [{ left: leftKey, right: rightKey }],
        select: [{ from: leftSelected, as: leftAlias }, { from: rightSelected, as: rightAlias }],
        how: "left", output_snapshot: `joined_${unitId}`,
      };
    }
    const terminalRefs = firstRefs.slice(0, 2);
    return {
      operation: "terminal", purpose: "Inspect and report results", execution_mode: terminalRefs.length >= 2 ? "template" : "llm",
      cautious: "", depends_on: depends, input_snapshot: snapshot,
      input_columns: terminalRefs.length ? terminalRefs : firstRefs.slice(0, 1),
      template_name: terminalRefs.length >= 2 ? "scatter_plot" : null,
      template_params: {},
    };
  }

  function optionHtml(options, selected, placeholder) {
    const values = [...new Set(options.filter((value) => value != null && value !== ""))];
    if (selected && !values.includes(selected)) values.unshift(selected);
    const first = placeholder ? `<option value="">${esc(placeholder)}</option>` : "";
    return first + values.map((value) => `<option value="${esc(value)}" ${value === selected ? "selected" : ""}>${esc(value)}</option>`).join("");
  }

  function selectControl(className, options, selected, dataAttrs, multiple) {
    const attrs = Object.entries(dataAttrs || {}).map(([key, value]) => `data-${key}="${esc(value)}"`).join(" ");
    return `<select class="${className}" ${attrs}${multiple ? " multiple" : ""}>${optionHtml(options, selected, "Choose...")}</select>`;
  }

  function renderRefEditor(unit, field, label, snapshot) {
    const values = [...new Set(unit[field] || [])];
    const options = snapshot ? (snapshotRefs()[snapshot] || []) : App.columns.map((column) => column.ref);
    return `
      <div class="field-editor">
        <div class="field-editor-label">${esc(label)}</div>
        <div class="field-drop-target" data-drop-unit="${unit.unit_id}" data-drop-field="${esc(field)}">
          ${values.length ? values.map((ref) => `<span class="field-chip" data-value="${esc(ref)}">${esc(ref)} <button class="chip-remove" data-remove-unit="${unit.unit_id}" data-remove-field="${esc(field)}" data-remove-value="${esc(ref)}" title="Remove column">x</button></span>`).join("") : '<span class="unit-drop-hint">drop qualified columns here</span>'}
          <select class="ref-add-select" data-add-unit="${unit.unit_id}" data-add-field="${esc(field)}">
            ${optionHtml(options.filter((ref) => !values.includes(ref)), "", "Add column")}
          </select>
        </div>
      </div>`;
  }

  function renderDependencies(unit) {
    const ids = (App.plan && App.plan.units ? App.plan.units : []).map((candidate) => candidate.unit_id).filter((id) => id !== unit.unit_id);
    if (!ids.length) return '<span class="dependency-none">Root unit</span>';
    return `
      <label class="dependency-control">Depends on
        <select class="unit-dependencies" data-unit-id="${unit.unit_id}" multiple title="Select upstream units">
          ${ids.map((id) => `<option value="${id}" ${(unit.depends_on || []).includes(id) ? "selected" : ""}>#${id}</option>`).join("")}
        </select>
      </label>`;
  }

  function renderTemplateControl(unit, templates) {
    if (unit.operation === "join") return '<span class="template-note">deterministic pandas join</span>';
    return `<label class="compact-control">Template
      <select class="unit-template" data-unit-id="${unit.unit_id}">
        ${optionHtml(templates, unit.template_name || "", "LLM generated")}
      </select>
    </label>`;
  }

  function renderJoinFields(unit) {
    const refs = snapshotRefs();
    const inputs = unit.inputs || [];
    const left = inputs.find((item) => item.role === "left") || { role: "left", snapshot: Object.keys(refs)[0] || "" };
    const right = inputs.find((item) => item.role === "right") || { role: "right", snapshot: Object.keys(refs)[1] || Object.keys(refs)[0] || "" };
    const names = Object.keys(refs);
    const keyRows = (unit.keys || []).map((key, index) => `
      <div class="join-key-row" data-key-index="${index}">
        <select class="join-key-left">${optionHtml(refs[left.snapshot] || [], key.left, "Left key")}</select>
        <span class="join-arrow">=</span>
        <select class="join-key-right">${optionHtml(refs[right.snapshot] || [], key.right, "Right key")}</select>
        <button class="chip-remove join-remove-key" data-unit-id="${unit.unit_id}" data-key-index="${index}" title="Remove key">x</button>
      </div>`).join("");
    const selectRows = (unit.select || []).map((selected, index) => {
      const source = selected.from || selected.from_ || "";
      const alias = selected.as || selected.as_ || "";
      return `<div class="join-select-row" data-select-index="${index}">
        <select class="join-selected-source">${optionHtml([...(refs[left.snapshot] || []), ...(refs[right.snapshot] || [])], source, "Output column")}</select>
        <input class="join-selected-alias" value="${esc(alias)}" aria-label="Join output alias">
        <button class="chip-remove join-remove-select" data-unit-id="${unit.unit_id}" data-select-index="${index}" title="Remove output">x</button>
      </div>`;
    }).join("");
    return `
      <div class="join-inputs">
        <label class="compact-control">Left Snapshot
          <select class="join-snapshot-left">${optionHtml(names, left.snapshot, "Choose left Snapshot")}</select>
        </label>
        <label class="compact-control">Right Snapshot
          <select class="join-snapshot-right">${optionHtml(names, right.snapshot, "Choose right Snapshot")}</select>
        </label>
      </div>
      <div class="field-editor"><div class="field-editor-label">Keys</div>
        <div class="join-keys">${keyRows || '<span class="unit-drop-hint">Add at least one key pair</span>'}</div>
        <button class="btn btn-sm btn-secondary join-add-key" data-unit-id="${unit.unit_id}">+ key pair</button>
      </div>
      <div class="join-select-editor"><div class="field-editor-label">Selected outputs</div>
        ${selectRows || '<span class="unit-drop-hint">Select at least one output column</span>'}
        <button class="btn btn-sm btn-secondary join-add-select" data-unit-id="${unit.unit_id}">+ output</button>
      </div>
      <div class="join-options">
        <label class="compact-control">How
          <select class="join-how">${optionHtml(["left", "right", "inner", "outer", "cross", "semi", "anti"], unit.how || "left")}</select>
        </label>
        <label class="compact-control">Output Snapshot
          <input class="join-output-snapshot" value="${esc(unit.output_snapshot || "joined")}">
        </label>
      </div>`;
  }

  function renderUnitFields(unit) {
    const refs = snapshotRefs();
    const names = Object.keys(refs);
    if (unit.operation === "derive_column") {
      const snapshot = unit.input_snapshot || names[0] || "";
      const params = unit.template_params || {};
      return `
        <div class="operation-grid">
          <label class="compact-control">Input Snapshot
            <select class="unit-input-snapshot" data-unit-id="${unit.unit_id}">${optionHtml(names, snapshot, "Choose Snapshot")}</select>
          </label>
          <label class="compact-control">Output column
            <input class="unit-output-column" data-unit-id="${unit.unit_id}" value="${esc((unit.output_columns || [""])[0])}" placeholder="snapshot.new_column">
          </label>
          <label class="compact-control">Operator
            <select class="derive-operator" data-unit-id="${unit.unit_id}">${optionHtml(["+", "-", "*", "/"], params.operator || "*")}</select>
          </label>
        </div>
        ${renderRefEditor(unit, "input_columns", "Input columns", snapshot)}
        ${renderTemplateControl(unit, ["column_arithmetic", "linear_regression"])}
      `;
    }
    if (unit.operation === "filter") {
      const snapshot = unit.input_snapshot || names[0] || "";
      const params = unit.template_params || {};
      return `
        <div class="operation-grid">
          <label class="compact-control">Input Snapshot
            <select class="unit-input-snapshot" data-unit-id="${unit.unit_id}">${optionHtml(names, snapshot, "Choose Snapshot")}</select>
          </label>
          <label class="compact-control">Output Snapshot
            <input class="filter-output-snapshot" data-unit-id="${unit.unit_id}" value="${esc(unit.output_snapshot || "filtered")}">
          </label>
          <label class="compact-control condition-control">Predicate
            <input class="filter-condition" data-unit-id="${unit.unit_id}" value="${esc(params.condition || "")}" placeholder="region == 'East'">
          </label>
        </div>
        ${renderRefEditor(unit, "input_columns", "Predicate columns", snapshot)}
        ${renderTemplateControl(unit, ["filter_by_date"])}
      `;
    }
    if (unit.operation === "join") return renderJoinFields(unit);
    if (unit.operation === "terminal") {
      const snapshot = unit.input_snapshot || names[0] || "";
      return `
        <div class="operation-grid">
          <label class="compact-control">Input Snapshot
            <select class="unit-input-snapshot" data-unit-id="${unit.unit_id}">${optionHtml(names, snapshot, "Choose Snapshot")}</select>
          </label>
          <span class="terminal-note">Artifacts only; no output columns or Snapshot.</span>
        </div>
        ${renderRefEditor(unit, "input_columns", "Terminal inputs", snapshot)}
        ${renderTemplateControl(unit, ["scatter_plot"])}
      `;
    }
    return '<div class="inline-error">This Plan contains a legacy unit. Recreate it with an operation-specific v2 unit.</div>';
  }

  function renderWorkspace() {
    const units = App.plan && App.plan.units ? App.plan.units : [];
    if (!units.length) {
      dom.workspaceArea.innerHTML = '<div class="empty-state">Add an operation to build the analysis DAG.</div>';
      return;
    }
    dom.workspaceArea.innerHTML = units.map((unit) => `
      <article class="unit-card" data-unit-id="${unit.unit_id}">
        <div class="unit-header">
          <span class="unit-id">#${unit.unit_id}</span>
          <select class="unit-operation" data-unit-id="${unit.unit_id}" aria-label="Operation">
            ${optionHtml(["derive_column", "filter", "join", "terminal", "legacy"], unit.operation, "Operation")}
          </select>
          <input class="unit-purpose" value="${esc(unit.purpose || "")}" placeholder="Purpose" data-unit-id="${unit.unit_id}">
          <button class="unit-delete" data-unit-id="${unit.unit_id}" title="Delete unit">x</button>
        </div>
        <div class="unit-meta">
          <label class="compact-control">Mode
            <select class="unit-mode" data-unit-id="${unit.unit_id}">${optionHtml(["template", "llm"], unit.execution_mode || "llm")}</select>
          </label>
          ${renderDependencies(unit)}
          ${unit.stale ? '<span class="stale-label">stale</span>' : ""}
        </div>
        <div class="unit-fields">${renderUnitFields(unit)}</div>
      </article>`).join("");
    bindWorkspaceEvents();
  }

  function bindWorkspaceEvents() {
    const area = dom.workspaceArea;
    area.querySelectorAll(".unit-purpose").forEach((input) => {
      input.addEventListener("change", () => updateUnitField(Number(input.dataset.unitId), { purpose: input.value }));
    });
    area.querySelectorAll(".unit-operation").forEach((select) => {
      select.addEventListener("change", async () => {
        const id = Number(select.dataset.unitId);
        const payload = newUnitPayload(select.value, id);
        const current = App.plan.units.find((unit) => unit.unit_id === id);
        payload.purpose = current ? current.purpose : payload.purpose;
        payload.cautious = current ? current.cautious : "";
        payload.depends_on = current ? current.depends_on : payload.depends_on;
        await updateUnitField(id, payload);
      });
    });
    area.querySelectorAll(".unit-mode").forEach((select) => {
      select.addEventListener("change", () => updateUnitField(Number(select.dataset.unitId), { execution_mode: select.value }));
    });
    area.querySelectorAll(".unit-dependencies").forEach((select) => {
      select.addEventListener("change", () => {
        const dependsOn = Array.from(select.selectedOptions).map((option) => Number(option.value));
        updateUnitField(Number(select.dataset.unitId), { depends_on: dependsOn });
      });
    });
    area.querySelectorAll(".unit-delete").forEach((button) => {
      button.addEventListener("click", () => deleteUnit(Number(button.dataset.unitId)));
    });
    area.querySelectorAll(".unit-input-snapshot").forEach((select) => {
      select.addEventListener("change", () => {
        const unit = App.plan.units.find((candidate) => candidate.unit_id === Number(select.dataset.unitId));
        if (!unit) return;
        const nextRefs = snapshotRefs()[select.value] || [];
        const patch = { input_snapshot: select.value, input_columns: nextRefs.slice(0, Math.max(1, Math.min(2, nextRefs.length))) };
        if (unit.operation === "derive_column" && unit.output_columns && unit.output_columns[0]) {
          patch.output_columns = [`${select.value}.${localName(unit.output_columns[0], unit.input_snapshot) || `derived_${unit.unit_id}`}`];
        }
        updateUnitField(unit.unit_id, patch);
      });
    });
    area.querySelectorAll(".unit-output-column").forEach((input) => {
      input.addEventListener("change", () => {
        const unit = App.plan.units.find((candidate) => candidate.unit_id === Number(input.dataset.unitId));
        const params = { ...(unit ? unit.template_params : {}) };
        params.new_column = localName(input.value, unit ? unit.input_snapshot : "");
        updateUnitField(Number(input.dataset.unitId), { output_columns: [input.value], template_params: params });
      });
    });
    area.querySelectorAll(".derive-operator").forEach((select) => {
      const id = Number(select.dataset.unitId);
      const unit = App.plan.units.find((candidate) => candidate.unit_id === id);
      select.addEventListener("change", () => updateUnitField(id, { template_params: { ...(unit ? unit.template_params : {}), operator: select.value } }));
    });
    area.querySelectorAll(".filter-output-snapshot").forEach((input) => {
      input.addEventListener("change", () => updateUnitField(Number(input.dataset.unitId), { output_snapshot: input.value }));
    });
    area.querySelectorAll(".filter-condition").forEach((input) => {
      const id = Number(input.dataset.unitId);
      const unit = App.plan.units.find((candidate) => candidate.unit_id === id);
      input.addEventListener("change", () => updateUnitField(id, { template_params: { ...(unit ? unit.template_params : {}), condition: input.value } }));
    });
    area.querySelectorAll(".unit-template").forEach((select) => {
      select.addEventListener("change", () => updateUnitField(Number(select.dataset.unitId), { template_name: select.value || null }));
    });
    area.querySelectorAll(".ref-add-select").forEach((select) => {
      select.addEventListener("change", () => {
        if (!select.value) return;
        const id = Number(select.dataset.addUnit);
        const field = select.dataset.addField;
        const unit = App.plan.units.find((candidate) => candidate.unit_id === id);
        const values = [...(unit && unit[field] ? unit[field] : [])];
        if (!values.includes(select.value)) values.push(select.value);
        updateUnitField(id, { [field]: values });
      });
    });
    area.querySelectorAll(".chip-remove").forEach((button) => {
      if (!button.dataset.removeUnit) return;
      button.addEventListener("click", () => {
        const id = Number(button.dataset.removeUnit);
        const unit = App.plan.units.find((candidate) => candidate.unit_id === id);
        const field = button.dataset.removeField;
        const values = (unit && unit[field] ? unit[field] : []).filter((value) => value !== button.dataset.removeValue);
        updateUnitField(id, { [field]: values });
      });
    });
    area.querySelectorAll(".field-drop-target").forEach((target) => {
      target.addEventListener("dragover", (event) => {
        event.preventDefault();
        target.classList.add("drag-over");
      });
      target.addEventListener("dragleave", () => target.classList.remove("drag-over"));
      target.addEventListener("drop", (event) => {
        event.preventDefault();
        target.classList.remove("drag-over");
        const ref = event.dataTransfer.getData("text/plain");
        if (!ref) return;
        const id = Number(target.dataset.dropUnit);
        const field = target.dataset.dropField;
        const unit = App.plan.units.find((candidate) => candidate.unit_id === id);
        const values = [...(unit && unit[field] ? unit[field] : [])];
        if (!values.includes(ref)) values.push(ref);
        updateUnitField(id, { [field]: values });
      });
    });
    bindJoinEvents(area);
  }

  function bindJoinEvents(area) {
    area.querySelectorAll(".join-snapshot-left, .join-snapshot-right").forEach((select) => {
      select.addEventListener("change", () => {
        const card = select.closest(".unit-card");
        const id = Number(card.dataset.unitId);
        const unit = App.plan.units.find((candidate) => candidate.unit_id === id);
        const leftSelect = card.querySelector(".join-snapshot-left");
        const rightSelect = card.querySelector(".join-snapshot-right");
        const next = normalizeJoin(unit, leftSelect.value, rightSelect.value);
        updateUnitField(id, next);
      });
    });
    area.querySelectorAll(".join-how").forEach((select) => {
      select.addEventListener("change", () => updateUnitField(Number(select.closest(".unit-card").dataset.unitId), { how: select.value }));
    });
    area.querySelectorAll(".join-output-snapshot").forEach((input) => {
      input.addEventListener("change", () => updateUnitField(Number(input.closest(".unit-card").dataset.unitId), { output_snapshot: input.value }));
    });
    area.querySelectorAll(".join-key-left, .join-key-right").forEach((select) => {
      select.addEventListener("change", () => {
        const card = select.closest(".unit-card");
        const keys = Array.from(card.querySelectorAll(".join-key-row")).map((row) => ({
          left: row.querySelector(".join-key-left").value,
          right: row.querySelector(".join-key-right").value,
        }));
        updateUnitField(Number(card.dataset.unitId), { keys });
      });
    });
    area.querySelectorAll(".join-selected-source, .join-selected-alias").forEach((control) => {
      control.addEventListener("change", () => {
        const card = control.closest(".unit-card");
        const select = Array.from(card.querySelectorAll(".join-select-row")).map((row) => ({
          from: row.querySelector(".join-selected-source").value,
          as: row.querySelector(".join-selected-alias").value,
        }));
        updateUnitField(Number(card.dataset.unitId), { select });
      });
    });
    area.querySelectorAll(".join-add-key").forEach((button) => {
      button.addEventListener("click", () => {
        const unit = App.plan.units.find((candidate) => candidate.unit_id === Number(button.dataset.unitId));
        const refs = snapshotRefs();
        const left = (unit.inputs || []).find((input) => input.role === "left");
        const right = (unit.inputs || []).find((input) => input.role === "right");
        const next = { left: (refs[left.snapshot] || [])[0] || "", right: (refs[right.snapshot] || [])[0] || "" };
        updateUnitField(unit.unit_id, { keys: [...(unit.keys || []), next] });
      });
    });
    area.querySelectorAll(".join-remove-key").forEach((button) => {
      button.addEventListener("click", () => {
        const unit = App.plan.units.find((candidate) => candidate.unit_id === Number(button.closest(".unit-card").dataset.unitId));
        updateUnitField(unit.unit_id, { keys: (unit.keys || []).filter((_, index) => index !== Number(button.dataset.keyIndex)) });
      });
    });
    area.querySelectorAll(".join-add-select").forEach((button) => {
      button.addEventListener("click", () => {
        const unit = App.plan.units.find((candidate) => candidate.unit_id === Number(button.dataset.unitId));
        const refs = snapshotRefs();
        const inputs = unit.inputs || [];
        const all = [...(refs[inputs[0] ? inputs[0].snapshot : ""] || []), ...(refs[inputs[1] ? inputs[1].snapshot : ""] || [])];
        const used = (unit.select || []).map((selected) => selected.from || selected.from_);
        const source = all.find((ref) => !used.includes(ref)) || all[0] || "";
        updateUnitField(unit.unit_id, { select: [...(unit.select || []), { from: source, as: localName(source, (inputs[0] || {}).snapshot) || "output" }] });
      });
    });
    area.querySelectorAll(".join-remove-select").forEach((button) => {
      button.addEventListener("click", () => {
        const unit = App.plan.units.find((candidate) => candidate.unit_id === Number(button.closest(".unit-card").dataset.unitId));
        updateUnitField(unit.unit_id, { select: (unit.select || []).filter((_, index) => index !== Number(button.dataset.selectIndex)) });
      });
    });
  }

  function normalizeJoin(unit, leftSnapshot, rightSnapshot) {
    const refs = snapshotRefs();
    const leftRefs = refs[leftSnapshot] || [];
    const rightRefs = refs[rightSnapshot] || [];
    const common = leftRefs.find((left) => rightRefs.some((right) => localName(right, rightSnapshot) === localName(left, leftSnapshot)));
    const rightCommon = common ? rightRefs.find((right) => localName(right, rightSnapshot) === localName(common, leftSnapshot)) : null;
    const keys = (unit.keys || []).filter((key) => leftRefs.includes(key.left) && rightRefs.includes(key.right));
    if (!keys.length && common && rightCommon) keys.push({ left: common, right: rightCommon });
    if (!keys.length && leftRefs[0] && rightRefs[0]) keys.push({ left: leftRefs[0], right: rightRefs[0] });
    const selected = (unit.select || []).filter((item) => {
      const source = item.from || item.from_;
      return leftRefs.includes(source) || rightRefs.includes(source);
    });
    if (!selected.length) {
      const left = leftRefs[0];
      const right = rightRefs[0];
      if (left) selected.push({ from: left, as: aliasFor(left, leftSnapshot, false) });
      if (right) selected.push({ from: right, as: aliasFor(right, rightSnapshot, left && localName(left, leftSnapshot) === localName(right, rightSnapshot)) });
    }
    return { inputs: [{ role: "left", snapshot: leftSnapshot }, { role: "right", snapshot: rightSnapshot }], keys, select: selected };
  }

  async function loadWorkspace() {
    const data = await api("/workspace");
    App.plan = data.plan;
    renderWorkspace();
  }

  async function addUnit() {
    if (!App.snapshots.length && !App.columns.length) {
      showError("panel-center", "Upload a source before adding an operation.");
      return;
    }
    const operation = dom.addUnitOperation.value;
    const id = Math.max(0, ...(App.plan && App.plan.units ? App.plan.units.map((unit) => unit.unit_id) : [])) + 1;
    try {
      const data = await api("/workspace/units", { method: "POST", body: newUnitPayload(operation, id) });
      App.plan = data.plan;
      renderWorkspace();
    } catch (error) {
      showError("panel-center", error.message);
    }
  }

  async function updateUnitField(unitId, patch) {
    try {
      const data = await api(`/workspace/units/${unitId}`, { method: "PUT", body: patch });
      App.plan = data.plan;
      renderWorkspace();
      if (App.results) await loadResults();
    } catch (error) {
      showError("workspace-area", error.message);
    }
  }

  async function deleteUnit(unitId, cascade) {
    if (!cascade && !window.confirm(`Delete unit #${unitId}?`)) return;
    const suffix = cascade ? "?cascade=true" : "";
    try {
      const data = await api(`/workspace/units/${unitId}${suffix}`, { method: "DELETE" });
      App.plan = data.plan;
      renderWorkspace();
      if (App.results) await loadResults();
    } catch (error) {
      if (error.status === 409 && error.detail && error.detail.code === "DOWNSTREAM_DEPENDENTS") {
        const ids = (error.detail.dependent_unit_ids || []).map((id) => `#${id}`).join(", ");
        if (window.confirm(`Unit ${unitId} has downstream dependents (${ids}). Delete the dependent chain too?`)) {
          await deleteUnit(unitId, true);
          return;
        }
      }
      showError("workspace-area", error.message);
    }
  }

  async function generatePlan() {
    dom.btnGenPlan.disabled = true;
    dom.btnGenPlan.textContent = "Generating...";
    try {
      const data = await api("/plan/generate", { method: "POST" });
      App.plan = data.plan;
      renderWorkspace();
    } catch (error) {
      showError("workspace-area", error.message);
    } finally {
      dom.btnGenPlan.disabled = false;
      dom.btnGenPlan.textContent = "Generate Plan";
    }
  }

  function initDialogue() {
    dom.dialogueSend.addEventListener("click", sendMessage);
    dom.dialogueInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
      }
    });
  }

  async function sendMessage() {
    const input = dom.dialogueInput;
    const message = input.value.trim();
    if (!message) return;
    input.value = "";
    input.disabled = true;
    dom.dialogueSend.disabled = true;
    appendMessage("user", message);
    const assistant = appendMessage("assistant", "Thinking...");
    const content = assistant.querySelector(".content");
    try {
      const data = await api("/copilot", {
        method: "POST",
        body: { message },
      });
      content.textContent = data.message || data.error || "No response";
    } catch (error) {
      content.textContent = `Error: ${error.message}`;
    } finally {
      input.disabled = false;
      dom.dialogueSend.disabled = false;
    }
  }

  function appendMessage(role, text) {
    const message = document.createElement("div");
    message.className = `dialogue-msg ${role}`;
    message.innerHTML = `<div class="sender">${role === "user" ? "YOU" : "AI"}</div><div class="content">${esc(text)}</div>`;
    dom.dialogueMessages.appendChild(message);
    dom.dialogueMessages.scrollTop = dom.dialogueMessages.scrollHeight;
    return message;
  }

  async function runExecution() {
    try {
      await api("/execution/run", { method: "POST" });
      setExecutionStatus("running");
      dom.btnExecute.disabled = true;
      startPolling();
    } catch (error) {
      showError("panel-center", error.message);
    }
  }

  function setExecutionStatus(status) {
    dom.execBadge.textContent = status;
    dom.execBadge.className = `status-badge ${status}`;
    dom.execSpinner.classList.toggle("hidden", status !== "running");
  }

  function startPolling() {
    if (App.pollingTimer) clearInterval(App.pollingTimer);
    App.pollingTimer = setInterval(pollStatus, 1000);
  }

  async function pollStatus() {
    try {
      const data = await api("/execution/status");
      setExecutionStatus(data.status);
      if (data.status === "completed" || data.status === "failed") {
        clearInterval(App.pollingTimer);
        App.pollingTimer = null;
        dom.btnExecute.disabled = false;
        if (data.status === "failed") showError("results-list", data.error || "Execution failed");
        await loadResults();
        await refreshData();
      }
    } catch (_) {
      clearInterval(App.pollingTimer);
      App.pollingTimer = null;
      dom.btnExecute.disabled = false;
      setExecutionStatus("failed");
    }
  }

  async function loadResults() {
    try {
      const data = await api("/execution/results");
      App.results = data;
      renderResults(data);
    } catch (error) {
      showError("results-list", error.message);
    }
  }

  function warningMarkup(warnings) {
    if (!warnings || !warnings.length) return "";
    return `<div class="result-warnings">${warnings.map((warning) => `
      <div class="warning-item"><strong>${esc(warning.code || "WARNING")}</strong><span>${esc(warning.message || JSON.stringify(warning))}</span></div>`).join("")}</div>`;
  }

  function renderResults(data) {
    dom.resultsArea.classList.remove("hidden");
    const units = data.units || [];
    const stale = data.stale_unit_ids || units.filter((unit) => unit.stale).map((unit) => unit.unit_id);
    dom.executionSummary.textContent = `${units.length} unit${units.length === 1 ? "" : "s"}${stale.length ? ` · ${stale.length} stale` : ""}`;
    if (!units.length) {
      dom.resultsList.innerHTML = '<div class="empty-state">No results yet</div>';
      return;
    }
    dom.resultsList.innerHTML = units.map((unit) => {
      const successful = unit.status === "success";
      const statusClass = unit.stale ? "stale" : (successful ? "success" : "failed");
      const rowCounts = unit.row_count_before != null && unit.row_count_after != null
        ? `<div class="result-metadata">Rows ${unit.row_count_before} → ${unit.row_count_after} (${unit.row_count_delta >= 0 ? "+" : ""}${unit.row_count_delta})</div>` : "";
      const checkpoints = [...(unit.input_checkpoint_ids || [])];
      if (unit.output_checkpoint_id) checkpoints.push(`output ${unit.output_checkpoint_id}`);
      return `<article class="result-card ${unit.stale ? "is-stale" : ""}">
        <div class="result-header"><span class="result-unit-id">Unit #${unit.unit_id}</span><span class="result-status ${statusClass}">${unit.stale ? "stale" : esc(unit.status)}</span>
          ${successful && !unit.stale ? renderPinBtns(unit) : ""}
          <button class="btn btn-sm btn-secondary result-rerun" data-unit-id="${unit.unit_id}">Rerun</button>
          <button class="btn btn-sm btn-secondary result-rerun-cascade" data-unit-id="${unit.unit_id}">Rerun chain</button>
        </div>
        ${unit.stale ? '<div class="stale-note">Upstream data changed. This result is retained for provenance but is not current.</div>' : ""}
        ${rowCounts}
        ${checkpoints.length ? `<div class="result-metadata checkpoint-line">Checkpoint: ${checkpoints.map((id) => `<code>${esc(id)}</code>`).join(" → ")}</div>` : ""}
        ${unit.error ? `<div class="result-error">${esc(unit.error)}</div>` : ""}
        ${warningMarkup(unit.warnings)}
        ${unit.insights && unit.insights.length ? `<ul class="result-insights">${unit.insights.map((insight) => `<li>${esc(insight)}</li>`).join("")}</ul>` : ""}
        ${unit.charts && unit.charts.length ? renderChartGallery(unit) : ""}
      </article>`;
    }).join("");
    dom.resultsList.querySelectorAll(".result-rerun").forEach((button) => button.addEventListener("click", () => rerunUnit(Number(button.dataset.unitId), false)));
    dom.resultsList.querySelectorAll(".result-rerun-cascade").forEach((button) => button.addEventListener("click", () => rerunUnit(Number(button.dataset.unitId), true)));
    dom.resultsList.querySelectorAll(".btn-pin").forEach((button) => button.addEventListener("click", () => {
      const path = button.dataset.chartPath;
      const pin = App.pins.find((item) => item.chart_path === path);
      if (pin) unpinChart(pin.pin_id); else pinChart(Number(button.dataset.unitId), path, button.dataset.label);
    }));
  }

  async function rerunUnit(unitId, cascade) {
    try {
      const suffix = cascade ? "?cascade=true" : "";
      const data = await api(`/execution/units/${unitId}/rerun${suffix}`, { method: "POST" });
      await loadResults();
      await refreshData();
      showError("results-list", `${cascade ? "Chain" : "Unit"} rerun complete${data.stale_units && data.stale_units.length ? `; stale units: ${data.stale_units.join(", ")}` : ""}.`);
    } catch (error) {
      showError("results-list", error.message);
    }
  }

  function renderPinBtns(unit) {
    return (unit.charts || []).map((chart) => {
      const pinned = App.pins.some((pin) => pin.chart_path === chart);
      return `<button class="btn-pin ${pinned ? "pinned" : ""}" data-unit-id="${unit.unit_id}" data-chart-path="${esc(chart)}" data-label="${esc(chart)}">${pinned ? "Pinned" : "Pin"}</button>`;
    }).join("");
  }

  function renderChartGallery(unit) {
    return `<div class="result-charts">${(unit.charts || []).map((chart) => `<img class="result-chart-img" src="${chartUrl(chart)}" alt="${esc(chart)}" loading="lazy">`).join("")}</div>`;
  }

  function chartUrl(chartPath) {
    const safe = String(chartPath).replaceAll("\\", "/").split("/").filter(Boolean).map(encodeURIComponent).join("/");
    return `/api/sessions/${App.sessionId}/execution/charts/${safe}`;
  }

  async function loadDashboard() {
    try {
      const data = await api("/dashboard");
      App.pins = data.pins || [];
      renderDashboard();
    } catch (_) {
      renderDashboard();
    }
  }

  function renderDashboard() {
    if (!App.pins.length) {
      dom.dashboardGrid.innerHTML = '<div class="empty-state" style="grid-column:1/-1;">Pin charts from execution results</div>';
      return;
    }
    dom.dashboardGrid.innerHTML = App.pins.map((pin) => `
      <div class="dashboard-card"><img src="${chartUrl(pin.chart_path)}" alt="${esc(pin.label)}" loading="lazy">
        <div class="dashboard-card-body"><span class="dashboard-card-label" title="${esc(pin.label)}">${esc(pin.label)}</span><span class="dashboard-card-unit">#${pin.unit_id}</span><button class="btn-danger btn-sm" data-pin-id="${pin.pin_id}">Remove</button></div>
      </div>`).join("");
    dom.dashboardGrid.querySelectorAll(".btn-danger").forEach((button) => button.addEventListener("click", () => unpinChart(button.dataset.pinId)));
  }

  async function pinChart(unitId, chartPath, label) {
    try {
      await api("/dashboard/pins", { method: "POST", body: { unit_id: unitId, chart_path: chartPath, label } });
      await loadDashboard();
      await loadResults();
    } catch (error) { showError("panel-right", error.message); }
  }

  async function unpinChart(pinId) {
    try {
      await api(`/dashboard/pins/${pinId}`, { method: "DELETE" });
      await loadDashboard();
      await loadResults();
    } catch (error) { showError("panel-right", error.message); }
  }

  async function generateReport() {
    dom.btnGenReport.disabled = true;
    dom.btnGenReport.textContent = "Generating...";
    try {
      const data = await api("/report/generate", { method: "POST" });
      dom.reportOutput.classList.remove("hidden");
      dom.reportOutput.innerHTML = data.report ? markdownToHtml(data.report) : '<div class="empty-state">No report content</div>';
    } catch (error) { showError("panel-right", error.message); }
    finally {
      dom.btnGenReport.disabled = false;
      dom.btnGenReport.textContent = "Generate Report";
    }
  }

  function markdownToHtml(markdown) {
    let html = esc(markdown || "");
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, "<pre><code>$2</code></pre>");
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
    html = html.replace(/^#### (.+)$/gm, "<h4>$1</h4>");
    html = html.replace(/^### (.+)$/gm, "<h3>$1</h3>");
    html = html.replace(/^## (.+)$/gm, "<h2>$1</h2>");
    html = html.replace(/^# (.+)$/gm, "<h1>$1</h1>");
    html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/^\s*[-*] (.+)$/gm, "<li>$1</li>");
    html = html.replace(/((?:<li>.*<\/li>\n?)+)/g, "<ul>$1</ul>");
    html = html.replace(/^> (.+)$/gm, "<blockquote>$1</blockquote>");
    html = html.replace(/^---$/gm, "<hr>");
    html = html.replace(/^(?!<[a-z/])(.+)$/gm, "<p>$1</p>");
    return html.replace(/<p>\s*<\/p>/g, "");
  }

  function esc(value) {
    if (value == null) return "";
    return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function showError(containerId, message) {
    const container = document.getElementById(containerId);
    if (!container) return;
    const existing = container.querySelector(".inline-error");
    if (existing) existing.remove();
    const error = document.createElement("div");
    error.className = "inline-error";
    error.textContent = message;
    container.prepend(error);
    setTimeout(() => error.remove(), 8000);
  }

  function renderAll() {
    renderSources();
    renderColumns();
    renderWorkspace();
    renderDashboard();
    dom.resultsArea.classList.add("hidden");
    dom.reportOutput.classList.add("hidden");
    dom.executionSummary.textContent = "";
    setExecutionStatus("idle");
    dom.btnExecute.disabled = false;
  }

  async function init() {
    cacheDom();
    try {
      await initSession();
      initUpload();
      initDialogue();
      dom.btnNew.addEventListener("click", newSession);
      dom.btnAddUnit.addEventListener("click", addUnit);
      dom.btnGenPlan.addEventListener("click", generatePlan);
      dom.btnExecute.addEventListener("click", runExecution);
      dom.btnGenReport.addEventListener("click", generateReport);
      await Promise.all([refreshData(), loadWorkspace(), loadDashboard()]);
      const stateResponse = await fetch(`/api/sessions/${App.sessionId}`);
      if (stateResponse.ok) {
        const state = await stateResponse.json();
        if (state.has_results) await loadResults();
        if (state.has_report) {
          const report = await api("/report");
          if (report.report) {
            dom.reportOutput.innerHTML = markdownToHtml(report.report);
            dom.reportOutput.classList.remove("hidden");
          }
        }
        if (state.has_results) {
          const status = await api("/execution/status");
          if (status.status === "running") {
            setExecutionStatus("running");
            dom.btnExecute.disabled = true;
            startPolling();
          }
        }
      }
    } catch (error) {
      dom.sessionId.textContent = `error: ${error.message}`;
      dom.sessionDot.style.background = "var(--error)";
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
