"use strict";

const state = {
  bootstrap: null,
  runs: [],
  selectedId: null,
  selected: null,
  events: [],
  filter: "all",
  stream: null,
  refreshTimer: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[char]);
const activeStatuses = new Set(["queued", "starting", "running", "checking", "reviewing", "cancelling", "publishing"]);

async function api(path, options = {}) {
  const headers = {"Content-Type": "application/json", ...(options.headers || {})};
  if (options.method && options.method !== "GET") headers["X-Odysseus-Token"] = state.bootstrap.token;
  const response = await fetch(path, {...options, headers});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

function toast(message, isError = false) {
  const node = $("#toast");
  node.textContent = message;
  node.className = `toast visible${isError ? " error" : ""}`;
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => node.className = "toast", 3200);
}

function relativeTime(iso) {
  if (!iso) return "—";
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86400)}d`;
}

function statusClass(status) { return `status-${String(status || "unknown").replace(/[^a-z_]/g, "")}`; }
function statusLabel(status) { return String(status || "unknown").replaceAll("_", " "); }

function filteredRuns() {
  if (state.filter === "active") return state.runs.filter((run) => activeStatuses.has(run.status));
  if (state.filter === "review") return state.runs.filter((run) => ["review", "failed", "accepted"].includes(run.status));
  return state.runs;
}

function renderRuns() {
  const runs = filteredRuns();
  $("#runCount").textContent = state.runs.length;
  $("#taskList").innerHTML = runs.length ? runs.map((run) => `
    <button class="task-card ${run.id === state.selectedId ? "selected" : ""}" data-run-id="${escapeHtml(run.id)}" type="button">
      <div class="task-card-top"><span class="mini-status ${statusClass(run.status)}">${escapeHtml(statusLabel(run.status))}</span><span class="run-id">${relativeTime(run.updated_at)}</span></div>
      <h3>${escapeHtml(run.title)}</h3>
      <div class="task-card-meta"><span>${escapeHtml(run.lane)}</span><span>${escapeHtml(run.workflow)}</span></div>
    </button>`).join("") : `<div class="empty-list">No tasks in this view.</div>`;
  $$(".task-card[data-run-id]").forEach((button) => button.addEventListener("click", () => selectRun(button.dataset.runId)));
}

async function refreshRuns() {
  const data = await api("/api/runs");
  state.runs = data.runs;
  renderRuns();
  if (!state.selectedId && state.runs.length) await selectRun(state.runs[0].id);
  if (state.selectedId) {
    const current = state.runs.find((run) => run.id === state.selectedId);
    if (current && (!state.selected || current.updated_at !== state.selected.updated_at)) await refreshSelected();
  }
}

async function selectRun(runId) {
  if (state.selectedId === runId && state.selected) return;
  state.selectedId = runId;
  location.hash = encodeURIComponent(runId);
  renderRuns();
  state.events = [];
  closeStream();
  await refreshSelected(true);
  openStream(runId);
}

async function refreshSelected(loadEvents = false) {
  if (!state.selectedId) return;
  const [run, diff] = await Promise.all([
    api(`/api/runs/${encodeURIComponent(state.selectedId)}`),
    api(`/api/runs/${encodeURIComponent(state.selectedId)}/diff`),
  ]);
  state.selected = run;
  if (loadEvents) {
    const payload = await api(`/api/runs/${encodeURIComponent(state.selectedId)}/events`);
    state.events = payload.events;
  }
  renderDetail(run, diff);
}

function renderDetail(run, diff) {
  $("#emptyState").classList.add("hidden");
  $("#runDetail").classList.remove("hidden");
  const status = $("#detailStatus");
  status.textContent = statusLabel(run.status);
  status.className = `status-pill ${statusClass(run.status)}`;
  $("#detailId").textContent = run.id;
  $("#detailTitle").textContent = run.title;
  $("#detailTask").textContent = run.task;
  $("#metadata").innerHTML = [
    ["Lane", run.lane], ["Workflow", run.workflow], ["Branch", run.branch || "waiting for worktree"],
    ["Project", run.project_path], ["Worktree", run.worktree_path || "—"], ["Attempt", `${run.attempt || 0} / ${(run.max_retries || 0) + 1}`],
    ["Created", new Date(run.created_at).toLocaleString()], ["Base", run.base_ref || "current HEAD"],
  ].map(([label, value]) => `<div class="meta"><small>${escapeHtml(label)}</small><strong title="${escapeHtml(value)}">${escapeHtml(value)}</strong></div>`).join("");
  renderActions(run);
  renderWorkflow(run);
  renderEvents();
  $("#diffStat").textContent = diff.stat || "No changed files yet.";
  $("#diffPatch").textContent = diff.patch || "No diff yet.";
  renderChecks(run.check_results || []);
  $("#reviewSummary").textContent = run.review_summary || run.last_error || "Review has not run yet.";
}

function renderActions(run) {
  const actions = [];
  if (run.status === "review") actions.push(`<button class="action-button accept" data-action="accept" type="button">Accept</button>`);
  if (["review", "failed"].includes(run.status)) actions.push(`<button class="action-button warn" data-action="send-back" type="button">Send back</button>`);
  if (["review", "accepted"].includes(run.status)) actions.push(`<button class="action-button" data-action="draft-pr" type="button">Draft PR</button>`);
  if (activeStatuses.has(run.status) && run.status !== "cancelling") actions.push(`<button class="action-button warn" data-action="cancel" type="button">Cancel</button>`);
  if (run.pull_request_url) actions.push(`<a class="action-button accept" href="${escapeHtml(run.pull_request_url)}" target="_blank" rel="noreferrer">Open PR</a>`);
  $("#runActions").innerHTML = actions.join("");
  $$("#runActions [data-action]").forEach((button) => button.addEventListener("click", () => runAction(button.dataset.action)));
}

function renderWorkflow(run) {
  const status = run.status;
  let current = 0;
  if (run.worktree_path) current = 1;
  if (["running"].includes(status)) current = 1;
  if (["checking"].includes(status)) current = 2;
  if (["reviewing", "review", "accepted", "pr_created", "publishing"].includes(status)) current = 3;
  ["stageWorktree", "stageAgent", "stageCheck", "stageReview"].forEach((id, index) => {
    const node = $(`#${id}`);
    node.classList.toggle("done", index < current || ["review", "accepted", "pr_created"].includes(status));
    node.classList.toggle("current", index === current && activeStatuses.has(status));
  });
}

function eventMessage(event) {
  const data = event.data || {};
  if (data.message) return data.message;
  if (data.text) return data.text;
  if (data.command) return `${data.command}${data.returncode !== undefined ? ` → ${data.returncode}` : ""}`;
  if (data.step) return `${data.step}${data.attempt ? ` · attempt ${data.attempt}` : ""}`;
  if (data.status) return data.status;
  if (data.url) return data.url;
  return Object.keys(data).length ? JSON.stringify(data) : "";
}

function renderEvents() {
  const log = $("#eventLog");
  const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 80;
  log.innerHTML = state.events.slice(-400).map((event) => {
    const kind = event.type.includes("failed") ? "failed" : event.type.includes("review") ? "review" : "";
    const time = new Date(event.ts).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"});
    return `<div class="event ${kind}"><time>${escapeHtml(time)}</time><span class="event-type" title="${escapeHtml(event.type)}">${escapeHtml(event.type)}</span><span class="event-message">${escapeHtml(eventMessage(event))}</span></div>`;
  }).join("") || `<div class="event"><time>—</time><span class="event-type">waiting</span><span class="event-message">No events yet.</span></div>`;
  if (atBottom) log.scrollTop = log.scrollHeight;
}

function renderChecks(checks) {
  $("#checkResults").innerHTML = checks.length ? checks.map((check) => {
    const pass = Number(check.returncode) === 0;
    return `<div class="check-card"><div class="check-head"><span>${escapeHtml(check.command || "No checks configured")}</span><strong class="${pass ? "check-pass" : "check-fail"}">${check.skipped ? "SKIPPED" : pass ? "PASS" : `FAIL ${check.returncode}`}</strong></div><pre class="check-output">${escapeHtml(check.output || "No output.")}</pre></div>`;
  }).join("") : `<div class="check-output">Checks have not run yet.</div>`;
}

function openStream(runId) {
  const after = state.events.at(-1)?.seq || 0;
  const stream = new EventSource(`/api/runs/${encodeURIComponent(runId)}/stream?after=${after}`);
  state.stream = stream;
  stream.addEventListener("odysseus", (message) => {
    const event = JSON.parse(message.data);
    if (state.events.some((item) => item.seq === event.seq)) return;
    state.events.push(event);
    renderEvents();
    window.clearTimeout(state.refreshTimer);
    state.refreshTimer = window.setTimeout(async () => {
      await refreshRuns();
      if (["run.review_ready", "run.failed", "run.accepted", "pr.created"].includes(event.type)) await refreshSelected();
    }, 180);
  });
  stream.onopen = () => setConnection(true);
  stream.onerror = () => setConnection(false);
}

function closeStream() {
  if (state.stream) state.stream.close();
  state.stream = null;
}

function setConnection(online) {
  const node = $(".connection");
  node.classList.toggle("online", online);
  $("#connectionLabel").textContent = online ? "Live" : "Reconnecting";
}

async function runAction(action) {
  if (!state.selectedId) return;
  if (action === "send-back") { $("#feedbackDialog").showModal(); return; }
  if (action === "draft-pr" && !window.confirm("Commit all worktree changes, push the branch, and create a draft pull request?")) return;
  try {
    await api(`/api/runs/${encodeURIComponent(state.selectedId)}/${action}`, {method: "POST", body: "{}"});
    toast(action === "draft-pr" ? "Draft pull request created." : `Action completed: ${action}`);
    await refreshRuns();
    await refreshSelected();
  } catch (error) { toast(error.message, true); }
}

function bindDialogs() {
  const taskDialog = $("#taskDialog");
  [$("#newTaskButton"), $("#emptyNewTask")].forEach((button) => button.addEventListener("click", () => taskDialog.showModal()));
  $("#taskForm").addEventListener("submit", async (event) => {
    if (event.submitter?.value === "cancel") return;
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const payload = {
      task: data.get("task"), title: data.get("title"), project_path: data.get("project_path"),
      lane: data.get("lane"), workflow: "agent-check-review", max_retries: Number(data.get("max_retries")),
      checks: String(data.get("checks") || "").split("\n").map((item) => item.trim()).filter(Boolean),
    };
    try {
      const run = await api("/api/runs", {method: "POST", body: JSON.stringify(payload)});
      taskDialog.close();
      event.currentTarget.reset();
      toast(`Queued ${run.id}`);
      await refreshRuns();
      await selectRun(run.id);
    } catch (error) { toast(error.message, true); }
  });
  $("#feedbackForm").addEventListener("submit", async (event) => {
    if (event.submitter?.value === "cancel") return;
    event.preventDefault();
    const feedback = new FormData(event.currentTarget).get("feedback");
    try {
      await api(`/api/runs/${encodeURIComponent(state.selectedId)}/send-back`, {method: "POST", body: JSON.stringify({feedback})});
      $("#feedbackDialog").close();
      event.currentTarget.reset();
      toast("Feedback queued for the next agent cycle.");
      await refreshRuns();
      await refreshSelected();
    } catch (error) { toast(error.message, true); }
  });
}

async function init() {
  try {
    state.bootstrap = await api("/api/bootstrap");
    $("#parallelLabel").textContent = `${state.bootstrap.max_parallel} slots`;
    $("#laneSelect").innerHTML = state.bootstrap.lanes.map((lane) => `<option value="${escapeHtml(lane)}">${escapeHtml(lane)}</option>`).join("");
    bindDialogs();
    $$(".filter").forEach((button) => button.addEventListener("click", () => {
      state.filter = button.dataset.filter;
      $$(".filter").forEach((item) => item.classList.toggle("active", item === button));
      renderRuns();
    }));
    $$(".tab").forEach((button) => button.addEventListener("click", () => {
      $$(".tab").forEach((item) => item.classList.toggle("active", item === button));
      $$(".tab-pane").forEach((pane) => pane.classList.toggle("active", pane.id === `tab-${button.dataset.tab}`));
    }));
    const hash = decodeURIComponent(location.hash.slice(1));
    await refreshRuns();
    if (hash && state.runs.some((run) => run.id === hash)) await selectRun(hash);
    setConnection(true);
    window.setInterval(() => refreshRuns().catch(() => setConnection(false)), 3000);
  } catch (error) {
    setConnection(false);
    toast(error.message, true);
  }
}

window.addEventListener("beforeunload", closeStream);
init();
