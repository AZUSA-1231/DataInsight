/* DataInsight Frontend — single-page BI workspace */
(function () {
  "use strict";

  // ── State ──────────────────────────────────────────────
  const App = {
    sessionId: null,
    columns: [],
    plan: null,
    results: null,
    pins: [],
    pollingTimer: null,
    pendingInstruction: null,
    pendingAction: null,
  };
  const SESSION_KEY = "datainsight.sessionId";

  // ── DOM refs ───────────────────────────────────────────
  const $ = (sel) => document.querySelector(sel);
  const dom = {};

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
    dom.columnList = $("#column-list");
    dom.workspaceArea = $("#workspace-area");
    dom.workspaceEmpty = $("#workspace-empty");
    dom.btnAddUnit = $("#btn-add-unit");
    dom.btnGenPlan = $("#btn-generate-plan");
    dom.btnExecute = $("#btn-execute");
    dom.execBadge = $("#exec-status-badge");
    dom.execSpinner = $("#exec-spinner");
    dom.resultsArea = $("#results-area");
    dom.resultsList = $("#results-list");
    dom.dialogueMessages = $("#dialogue-messages");
    dom.dialogueInput = $("#dialogue-input");
    dom.dialogueSend = $("#dialogue-send");
    dom.dashboardGrid = $("#dashboard-grid");
    dom.btnGenReport = $("#btn-generate-report");
    dom.reportOutput = $("#report-output");
  }

  // ── API helper ─────────────────────────────────────────
  async function api(path, opts = {}) {
    if (!App.sessionId && !path.startsWith("/api/sessions") && opts.method !== "POST") {
      throw new Error("No session");
    }
    const base = `/api/sessions/${App.sessionId}`;
    const url = path.startsWith("/api/sessions") ? path : `${base}${path}`;

    const config = { headers: {}, ...opts };
    if (config.body && typeof config.body === "object" && !(config.body instanceof FormData)) {
      config.headers["Content-Type"] = "application/json";
      config.body = JSON.stringify(config.body);
    }
    // FormData sets its own Content-Type

    const res = await fetch(url, config);
    if (!res.ok) {
      const detail = await res.json().then((d) => d.detail || "Unknown error").catch(() => res.statusText);
      throw new Error(detail);
    }
    return res.json();
  }

  // ── Session ────────────────────────────────────────────
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
    const res = await fetch("/api/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_requirement: "" }),
    });
    if (!res.ok) throw new Error("Unable to create session");
    const data = await res.json();
    activateSession(data.session_id);
  }

  async function initSession() {
    try {
      const urlSession = new URLSearchParams(window.location.search).get("session");
      const savedSession = urlSession || localStorage.getItem(SESSION_KEY);
      if (savedSession) {
        const res = await fetch(`/api/sessions/${encodeURIComponent(savedSession)}`);
        if (res.ok) {
          activateSession(savedSession);
          return;
        }
      }
      await createSession();
    } catch (err) {
      dom.sessionId.textContent = "error: " + err.message;
      dom.sessionDot.style.background = "var(--error)";
    }
  }

  async function newSession() {
    if (App.pollingTimer) clearInterval(App.pollingTimer);
    App.sessionId = null;
    App.columns = [];
    App.plan = null;
    App.results = null;
    App.pins = [];
    await createSession();
    renderAll();
  }

  // ── Data Upload ────────────────────────────────────────
  function initUpload() {
    const zone = dom.uploadZone;
    const input = dom.fileInput;

    zone.addEventListener("click", () => input.click());

    zone.addEventListener("dragover", (e) => {
      e.preventDefault();
      zone.classList.add("drag-over");
    });
    zone.addEventListener("dragleave", () => zone.classList.remove("drag-over"));
    zone.addEventListener("drop", (e) => {
      e.preventDefault();
      zone.classList.remove("drag-over");
      const file = e.dataTransfer.files[0];
      if (file) uploadFile(file);
    });

    input.addEventListener("change", () => {
      const file = input.files[0];
      if (file) uploadFile(file);
    });
  }

  async function uploadFile(file) {
    dom.uploadError.classList.add("hidden");
    const form = new FormData();
    form.append("file", file);

    try {
      const data = await api("/data/upload", { method: "POST", body: form });
      dom.uploadEmpty.classList.add("hidden");
      dom.uploadFile.classList.remove("hidden");
      dom.fileName.textContent = data.file_name;
      dom.fileShape.textContent = `${data.row_count} rows × ${data.col_count} cols`;
      dom.uploadZone.classList.add("has-file");
      App.columns = data.unified_columns;

      // Load full column info from profile
      try {
        const profile = await api("/data/profile");
        App.columns = (profile.columns || []).map((c) => ({
          name: c.name,
          dtype: c.dtype,
          null_pct: c.null_pct || 0,
        }));
      } catch (_) { /* columns from upload response are ok */ }

      renderColumns();
      renderWorkspace();
    } catch (err) {
      dom.uploadError.textContent = err.message;
      dom.uploadError.classList.remove("hidden");
    }
  }

  // ── Columns ────────────────────────────────────────────
  function renderColumns() {
    const list = dom.columnList;
    if (!App.columns.length) {
      list.innerHTML = '<div class="empty-state">Upload a file to see columns</div>';
      return;
    }
    list.innerHTML = App.columns
      .map(
        (c) => `
        <div class="column-item" draggable="true" data-column="${c.name}">
          <span class="column-dtype">${c.dtype || "?"}</span>
          <span class="column-name">${c.name}</span>
          <span class="column-null">${c.null_pct != null ? c.null_pct.toFixed(1) + "%" : ""}</span>
        </div>`
      )
      .join("");

    // Drag source
    list.querySelectorAll(".column-item").forEach((el) => {
      el.addEventListener("dragstart", (e) => {
        e.dataTransfer.setData("text/plain", el.dataset.column);
        e.dataTransfer.effectAllowed = "copy";
        el.classList.add("dragging");
      });
      el.addEventListener("dragend", () => el.classList.remove("dragging"));
    });
  }

  // ── Workspace ──────────────────────────────────────────
  async function loadWorkspace() {
    try {
      const data = await api("/workspace");
      App.plan = data.plan;
      renderWorkspace();
    } catch (_) { /* no workspace yet */ }
  }

  function renderWorkspace() {
    const area = dom.workspaceArea;
    const plan = App.plan;
    const hasUnits = plan && plan.units && plan.units.length > 0;

    dom.workspaceEmpty.classList.toggle("hidden", hasUnits);

    if (!hasUnits) {
      area.innerHTML =
        '<div class="empty-state" id="workspace-empty">No analysis units yet. Add one below or use AI to generate.</div>';
      return;
    }

    area.innerHTML = plan.units
      .map(
        (u) => `
      <div class="unit-card" data-unit-id="${u.unit_id}">
        <div class="unit-header">
          <span class="unit-id">#${u.unit_id}</span>
          <input class="unit-purpose" value="${esc(u.purpose)}" placeholder="Analysis purpose..."
                 data-unit-id="${u.unit_id}" data-field="purpose">
          <select class="unit-model" data-unit-id="${u.unit_id}" data-field="model">
            <option value="">no model</option>
            ${["linear_regression","random_forest","kmeans","descriptive","correlation","custom"]
              .map((m) => `<option value="${m}" ${u.model_hint === m ? "selected" : ""}>${m}</option>`)
              .join("")}
          </select>
          <button class="unit-delete" data-unit-id="${u.unit_id}" title="Delete unit">&times;</button>
        </div>
        <div class="unit-fields">
          <span class="unit-fields-label">Fields:</span>
          ${(u.related_fields || [])
            .map((f) => `<span class="field-chip">${esc(f)}<span class="remove" data-field="${esc(f)}" data-unit-id="${u.unit_id}">&times;</span></span>`)
            .join("")}
          <span class="unit-drop-hint">drop columns here</span>
        </div>
      </div>`
      )
      .join("");

    // Drag targets — unit cards accept column drops
    area.querySelectorAll(".unit-card").forEach((card) => {
      card.addEventListener("dragover", (e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = "copy";
        card.classList.add("drag-over");
      });
      card.addEventListener("dragleave", () => card.classList.remove("drag-over"));
      card.addEventListener("drop", async (e) => {
        e.preventDefault();
        card.classList.remove("drag-over");
        const colName = e.dataTransfer.getData("text/plain");
        if (!colName) return;
        const unitId = parseInt(card.dataset.unitId);
        const unit = App.plan.units.find((u) => u.unit_id === unitId);
        if (!unit) return;
        const fields = [...(unit.related_fields || [])];
        if (fields.includes(colName)) return;
        fields.push(colName);
        await updateUnitField(unitId, { related_fields: fields });
      });
    });

    // Editable purpose
    area.querySelectorAll(".unit-purpose").forEach((inp) => {
      inp.addEventListener("change", async () => {
        const unitId = parseInt(inp.dataset.unitId);
        await updateUnitField(unitId, { purpose: inp.value });
      });
    });

    // Model selector
    area.querySelectorAll(".unit-model").forEach((sel) => {
      sel.addEventListener("change", async () => {
        const unitId = parseInt(sel.dataset.unitId);
        await updateUnitField(unitId, { model: sel.value || null });
      });
    });

    // Delete unit
    area.querySelectorAll(".unit-delete").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await deleteUnit(parseInt(btn.dataset.unitId));
      });
    });

    // Remove field chip
    area.querySelectorAll(".field-chip .remove").forEach((chip) => {
      chip.addEventListener("click", async (e) => {
        e.stopPropagation();
        const unitId = parseInt(chip.dataset.unitId);
        const field = chip.dataset.field;
        const unit = App.plan.units.find((u) => u.unit_id === unitId);
        if (!unit) return;
        const fields = (unit.related_fields || []).filter((f) => f !== field);
        await updateUnitField(unitId, { related_fields: fields });
      });
    });
  }

  async function addUnit() {
    try {
      const data = await api("/workspace/units", {
        method: "POST",
        body: { purpose: "New analysis", model: null, cautious: "", related_fields: [] },
      });
      App.plan = data.plan;
      renderWorkspace();
    } catch (err) {
      showError("workspace-area", err.message);
    }
  }

  async function updateUnitField(unitId, patch) {
    try {
      const data = await api(`/workspace/units/${unitId}`, { method: "PUT", body: patch });
      App.plan = data.plan;
      renderWorkspace();
    } catch (err) {
      showError("workspace-area", err.message);
    }
  }

  async function deleteUnit(unitId) {
    try {
      const data = await api(`/workspace/units/${unitId}`, { method: "DELETE" });
      App.plan = data.plan;
      if (!App.plan || !App.plan.units || App.plan.units.length === 0) {
        App.plan = null;
      }
      renderWorkspace();
    } catch (err) {
      showError("workspace-area", err.message);
    }
  }

  async function generatePlan() {
    dom.btnGenPlan.disabled = true;
    dom.btnGenPlan.textContent = "Generating...";
    try {
      const data = await api("/plan/generate", { method: "POST" });
      App.plan = data.plan;
      renderWorkspace();
    } catch (err) {
      showError("workspace-area", err.message);
    } finally {
      dom.btnGenPlan.disabled = false;
      dom.btnGenPlan.textContent = "Generate Plan";
    }
  }

  // ── Dialogue ───────────────────────────────────────────
  function initDialogue() {
    const input = dom.dialogueInput;
    const send = dom.dialogueSend;

    send.addEventListener("click", () => sendMessage());
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });
  }

  function _parseSSEdata(rawData) {
    // Safely parse SSE data field (JSON-string-escaped by json.dumps on backend).
    // Returns the parsed value as-is (string, object, etc.), or null on failure.
    if (rawData == null || rawData === "") return null;
    try {
      return JSON.parse(rawData);
    } catch (_) {
      // Not valid JSON — use raw data directly (strip surrounding quotes if present)
      console.warn("[SSE] JSON.parse failed for data:", rawData.slice(0, 100));
      const trimmed = rawData.trim();
      if (trimmed.length > 1 && trimmed[0] === '"' && trimmed[trimmed.length - 1] === '"') {
        return trimmed.slice(1, -1);
      }
      return trimmed;
    }
  }

  async function sendMessage() {
    const input = dom.dialogueInput;
    const msg = input.value.trim();
    if (!msg) return;

    input.value = "";
    dom.dialogueSend.disabled = true;
    input.disabled = true;

    appendMessage("user", msg);

    // Use SSE streaming
    const msgs = dom.dialogueMessages;
    const streamMsg = document.createElement("div");
    streamMsg.className = "dialogue-msg assistant streaming";
    streamMsg.innerHTML = '<div class="sender">AI</div><div class="content"></div>';
    msgs.appendChild(streamMsg);
    msgs.scrollTop = msgs.scrollHeight;

    const contentEl = streamMsg.querySelector(".content");
    let fullText = "";

    const finish = (finalText) => {
      streamMsg.classList.remove("streaming");
      if (source) source.close();
      if (finalText) contentEl.textContent = finalText;
      dom.dialogueSend.disabled = false;
      input.disabled = false;
      input.focus();
    };

    let source = null;
    try {
      const url = `/api/sessions/${App.sessionId}/dialogue/stream?message=${encodeURIComponent(msg)}`;
      source = new EventSource(url);

      source.addEventListener("token", (e) => {
        const text = _parseSSEdata(e.data);
        if (text != null) {
          fullText += text;
          contentEl.textContent = fullText;
          msgs.scrollTop = msgs.scrollHeight;
        }
      });

      // Fallback: catch events without explicit event: field
      source.addEventListener("message", (e) => {
        if (e.data == null || e.data === "") return;
        console.warn("[SSE] Got 'message' event (not 'token'):", e.data.slice(0, 80));
        const text = _parseSSEdata(e.data);
        if (text != null) {
          fullText += text;
          contentEl.textContent = fullText;
          msgs.scrollTop = msgs.scrollHeight;
        }
      });

      // BT Agent tool_call: submit_planner_instruction → cache for confirmation
      source.addEventListener("tool_call", (e) => {
        try {
          const parsed = _parseSSEdata(e.data);
          if (parsed && parsed.name === "submit_planner_instruction") {
            App.pendingInstruction = parsed.args;
            console.log("[SSE] Received instruction:", App.pendingInstruction.core_question);
          }
        } catch (err) {
          console.warn("[SSE] Failed to parse tool_call:", err);
        }
      });

      source.addEventListener("done", (e) => {
        const parsed = _parseSSEdata(e.data);
        let finalText, action;
        if (typeof parsed === "object" && parsed !== null) {
          finalText = parsed.full_text || fullText;
          action = parsed.action || "chat";
          // Extract instruction from done event (backend includes it when action=confirm)
          if (parsed.instruction) {
            App.pendingInstruction = parsed.instruction;
          }
        } else {
          finalText = parsed || fullText;
          action = "chat";
        }
        App.pendingAction = action;
        finish(finalText);

        // Show confirmation button when BT submitted an instruction
        if (action === "confirm") {
          showConfirmation(streamMsg);
        }
      });

      source.addEventListener("sse_error", (e) => {
        const errMsg = _parseSSEdata(e.data) || "(unknown error)";
        finish("Error: " + errMsg);
      });

      source.addEventListener("error", () => {
        // Native EventSource error — connection failed or unexpected close
        if (!fullText) {
          finish("(connection error)");
        } else {
          finish(null); // keep whatever text we accumulated
        }
      });
    } catch (err) {
      finish("Error: " + (err.message || "unknown"));
    }
  }

  function appendMessage(role, text) {
    const msgs = dom.dialogueMessages;
    const div = document.createElement("div");
    div.className = `dialogue-msg ${role}`;
    div.innerHTML = `<div class="sender">${role === "user" ? "YOU" : "AI"}</div><div class="content">${esc(text)}</div>`;
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
  }

  function showConfirmation(afterMsgEl) {
    // Remove any existing confirmation row
    const existing = document.querySelector(".confirm-row");
    if (existing) existing.remove();

    const row = document.createElement("div");
    row.className = "confirm-row";

    const confirmBtn = document.createElement("button");
    confirmBtn.className = "btn-confirm";
    confirmBtn.textContent = "Generate Workspace";

    const cancelBtn = document.createElement("button");
    cancelBtn.className = "btn-cancel";
    cancelBtn.textContent = "Ignore";

    confirmBtn.addEventListener("click", async () => {
      row.remove();
      await executePendingAction();
    });

    cancelBtn.addEventListener("click", () => {
      App.pendingInstruction = null;
      App.pendingAction = null;
      row.remove();
    });

    row.appendChild(confirmBtn);
    row.appendChild(cancelBtn);

    if (afterMsgEl && afterMsgEl.parentNode) {
      afterMsgEl.parentNode.insertBefore(row, afterMsgEl.nextSibling);
    } else {
      dom.dialogueMessages.appendChild(row);
    }
    row.scrollIntoView({ behavior: "smooth" });
  }

  async function executePendingAction() {
    if (!App.pendingInstruction) {
      // No instruction — fall back to old generatePlan
      await generatePlan();
      return;
    }

    const inst = App.pendingInstruction;
    dom.btnGenPlan.disabled = true;
    dom.btnGenPlan.textContent = "Generating...";

    try {
      const body = { instruction: inst };
      const base = `/api/sessions/${App.sessionId}`;
      const res = await fetch(`${base}/plan/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const detail = await res.json().then((d) => d.detail || "Unknown error").catch(() => res.statusText);
        throw new Error(detail);
      }
      const data = await res.json();
      App.plan = data.plan;
      renderWorkspace();

      // Clear pending state
      App.pendingInstruction = null;
      App.pendingAction = null;
    } catch (err) {
      showError("workspace-area", err.message);
    } finally {
      dom.btnGenPlan.disabled = false;
      dom.btnGenPlan.textContent = "Generate Plan";
    }
  }

  // ── Execution ──────────────────────────────────────────
  async function runExecution() {
    try {
      await api("/execution/run", { method: "POST" });
      dom.execBadge.textContent = "running";
      dom.execBadge.className = "status-badge running";
      dom.execSpinner.classList.remove("hidden");
      dom.btnExecute.disabled = true;
      startPolling();
    } catch (err) {
      showError("panel-center", err.message);
    }
  }

  function startPolling() {
    if (App.pollingTimer) clearInterval(App.pollingTimer);
    App.pollingTimer = setInterval(pollStatus, 1000);
  }

  async function pollStatus() {
    try {
      const data = await api("/execution/status");
      dom.execBadge.textContent = data.status;
      dom.execBadge.className = `status-badge ${data.status}`;

      if (data.status === "completed") {
        clearInterval(App.pollingTimer);
        App.pollingTimer = null;
        dom.execSpinner.classList.add("hidden");
        dom.btnExecute.disabled = false;
        await loadResults();
      } else if (data.status === "failed") {
        clearInterval(App.pollingTimer);
        App.pollingTimer = null;
        dom.execSpinner.classList.add("hidden");
        dom.btnExecute.disabled = false;
        showError("results-list", data.error || "Execution failed");
      }
    } catch (err) {
      clearInterval(App.pollingTimer);
      App.pollingTimer = null;
      dom.execSpinner.classList.add("hidden");
      dom.btnExecute.disabled = false;
    }
  }

  async function loadResults() {
    try {
      const data = await api("/execution/results");
      App.results = data;
      renderResults(data);
    } catch (err) {
      showError("results-list", err.message);
    }
  }

  function renderResults(data) {
    dom.resultsArea.classList.remove("hidden");
    const list = dom.resultsList;
    const units = data.units || [];

    if (!units.length) {
      list.innerHTML = '<div class="empty-state">No results yet</div>';
      return;
    }

    list.innerHTML = units
      .map(
        (u) => `
      <div class="result-card">
        <div class="result-header">
          <span class="result-unit-id">Unit #${u.unit_id}</span>
          <span class="result-status" style="color:${u.status === "completed" ? "var(--success)" : "var(--error)"}">
            ${u.status}
          </span>
          ${u.status === "completed" ? renderPinBtns(u) : ""}
        </div>
        ${u.error ? `<div style="color:var(--error);font-size:12px;">${esc(u.error)}</div>` : ""}
        ${u.charts && u.charts.length ? renderChartGallery(u) : ""}
        ${u.insights && u.insights.length ? `<ul class="result-insights">${u.insights.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>` : ""}
      </div>`
      )
      .join("");

    // Pin button handlers
    list.querySelectorAll(".btn-pin").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const unitId = parseInt(btn.dataset.unitId);
        const chartPath = btn.dataset.chartPath;
        const label = btn.dataset.label;
        if (btn.classList.contains("pinned")) {
          // Find and unpin
          const pin = App.pins.find((p) => p.chart_path === chartPath);
          if (pin) await unpinChart(pin.pin_id);
        } else {
          await pinChart(unitId, chartPath, label);
        }
      });
    });
  }

  function renderPinBtns(unit) {
    return (unit.charts || [])
      .map(
        (chart) =>
          `<button class="btn-pin" data-unit-id="${unit.unit_id}" data-chart-path="${esc(chart)}" data-label="${esc(chart)}">Pin</button>`
      )
      .join("");
  }

  function renderChartGallery(unit) {
    return `
      <div class="result-charts">
        ${(unit.charts || [])
          .map((chart) => {
            const url = chartUrl(chart);
            return `<img class="result-chart-img" src="${url}" alt="${esc(chart)}" loading="lazy">`;
          })
          .join("")}
      </div>`;
  }

  function chartUrl(chartPath) {
    const encodedPath = String(chartPath)
      .replaceAll("\\", "/")
      .split("/")
      .filter(Boolean)
      .map(encodeURIComponent)
      .join("/");
    return `/api/sessions/${App.sessionId}/execution/charts/${encodedPath}`;
  }

  // ── Dashboard ──────────────────────────────────────────
  async function loadDashboard() {
    try {
      const data = await api("/dashboard");
      App.pins = data.pins || [];
      renderDashboard();
    } catch (_) { /* no pins yet */ }
  }

  function renderDashboard() {
    const grid = dom.dashboardGrid;
    if (!App.pins.length) {
      grid.innerHTML = '<div class="empty-state" style="grid-column:1/-1;">Pin charts from execution results</div>';
      return;
    }
    grid.innerHTML = App.pins
      .map(
        (p) => `
      <div class="dashboard-card">
        <img src="${chartUrl(p.chart_path)}"
             alt="${esc(p.label)}" loading="lazy">
        <div class="dashboard-card-body">
          <span class="dashboard-card-label" title="${esc(p.label)}">${esc(p.label)}</span>
          <span class="dashboard-card-unit">#${p.unit_id}</span>
          <button class="btn-danger btn-sm" data-pin-id="${p.pin_id}">Remove</button>
        </div>
      </div>`
      )
      .join("");

    grid.querySelectorAll(".btn-danger").forEach((btn) => {
      btn.addEventListener("click", () => unpinChart(btn.dataset.pinId));
    });
  }

  async function pinChart(unitId, chartPath, label) {
    try {
      await api("/dashboard/pins", {
        method: "POST",
        body: { unit_id: unitId, chart_path: chartPath, label: label },
      });
      await loadDashboard();
      await loadResults(); // refresh pin buttons
    } catch (err) {
      showError("panel-right", err.message);
    }
  }

  async function unpinChart(pinId) {
    try {
      await api(`/dashboard/pins/${pinId}`, { method: "DELETE" });
      await loadDashboard();
      await loadResults(); // refresh pin buttons
    } catch (err) {
      showError("panel-right", err.message);
    }
  }

  // ── Report ─────────────────────────────────────────────
  async function generateReport() {
    dom.btnGenReport.disabled = true;
    dom.btnGenReport.textContent = "Generating...";
    try {
      const data = await api("/report/generate", { method: "POST" });
      dom.reportOutput.classList.remove("hidden");
      if (data.report) {
        dom.reportOutput.innerHTML = markdownToHtml(data.report);
      } else {
        dom.reportOutput.innerHTML = '<div class="empty-state">No report content</div>';
      }
      dom.reportOutput.scrollIntoView({ behavior: "smooth" });
    } catch (err) {
      showError("panel-right", err.message);
    } finally {
      dom.btnGenReport.disabled = false;
      dom.btnGenReport.textContent = "Generate Report";
    }
  }

  // ── Simple Markdown → HTML ─────────────────────────────
  function markdownToHtml(md) {
    let html = md;

    // Code blocks (fenced)
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, "<pre><code>$2</code></pre>");

    // Inline code
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");

    // Headers
    html = html.replace(/^#### (.+)$/gm, "<h4>$1</h4>");
    html = html.replace(/^### (.+)$/gm, "<h3>$1</h3>");
    html = html.replace(/^## (.+)$/gm, "<h2>$1</h2>");
    html = html.replace(/^# (.+)$/gm, "<h1>$1</h1>");

    // Bold & italic
    html = html.replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>");
    html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");

    // Unordered lists
    html = html.replace(/^(\s*)[-*] (.+)$/gm, "$1<li>$2</li>");
    html = html.replace(/((?:<li>.*<\/li>\n?)+)/g, "<ul>$1</ul>");

    // Ordered lists
    html = html.replace(/^\d+\. (.+)$/gm, "<li>$1</li>");

    // Blockquotes
    html = html.replace(/^> (.+)$/gm, "<blockquote>$1</blockquote>");

    // Horizontal rules
    html = html.replace(/^---$/gm, "<hr>");

    // Paragraphs: wrap remaining lines
    html = html.replace(/^(?!<[a-z/])(.+)$/gm, "<p>$1</p>");

    // Clean up empty paragraphs
    html = html.replace(/<p>\s*<\/p>/g, "");

    return html;
  }

  // ── Helpers ────────────────────────────────────────────
  function esc(s) {
    if (!s) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function showError(containerId, msg) {
    const container = document.getElementById(containerId);
    if (!container) return;
    const existing = container.querySelector(".inline-error");
    if (existing) existing.remove();
    const div = document.createElement("div");
    div.className = "inline-error";
    div.textContent = msg;
    container.prepend(div);
    setTimeout(() => div.remove(), 6000);
  }

  // ── Render all ─────────────────────────────────────────
  function renderAll() {
    renderColumns();
    renderWorkspace();
    renderDashboard();
    dom.resultsArea.classList.add("hidden");
    dom.reportOutput.classList.add("hidden");
    dom.execBadge.textContent = "idle";
    dom.execBadge.className = "status-badge idle";
    dom.btnExecute.disabled = false;
  }

  // ── Init ───────────────────────────────────────────────
  async function init() {
    cacheDom();
    await initSession();
    initUpload();
    initDialogue();

    // Button handlers
    dom.btnNew.addEventListener("click", newSession);
    dom.btnAddUnit.addEventListener("click", addUnit);
    dom.btnGenPlan.addEventListener("click", generatePlan);
    dom.btnExecute.addEventListener("click", runExecution);
    dom.btnGenReport.addEventListener("click", generateReport);

    // Load initial state
    await loadWorkspace();
    await loadDashboard();

    // If session already has data (from prior upload), refresh columns
    try {
      const state = await fetch(`/api/sessions/${App.sessionId}`).then((r) => r.json());
      if (state.has_data) {
        const cols = await api("/data/columns");
        App.columns = cols.unified_columns || [];
        try {
          const profile = await api("/data/profile");
          App.columns = (profile.columns || []).map((c) => ({
            name: c.name,
            dtype: c.dtype,
            null_pct: c.null_pct || 0,
          }));
        } catch (_) { /* fallback to name list */ }
        renderColumns();
      }
      if (state.has_results) await loadResults();
      if (state.has_report) {
        const report = await api("/report");
        if (report.report) {
          dom.reportOutput.innerHTML = markdownToHtml(report.report);
          dom.reportOutput.classList.remove("hidden");
        }
      }
    } catch (_) { /* fresh session */ }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
