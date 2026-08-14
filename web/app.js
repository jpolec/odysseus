"use strict";

const state = {
  bootstrap: null, runs: [], projects: [], sessions: [], inbox: [], selectedId: null,
  selected: null, events: [], filter: "all", projectFilter: "all", view: "tasks",
  stream: null, refreshTimer: null,
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
  toast.timer = window.setTimeout(() => node.className = "toast", 4200);
}

function relativeTime(iso) {
  if (!iso) return "—";
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86400)}d`;
}

function compactNumber(value) { return new Intl.NumberFormat("en", {notation: "compact", maximumFractionDigits: 1}).format(Number(value || 0)); }
function statusClass(status) { return `status-${String(status || "unknown").replace(/[^a-z_]/g, "")}`; }
function statusLabel(status) { return String(status || "unknown").replaceAll("_", " "); }
function projectById(id) { return state.projects.find((project) => project.id === id); }

function setView(view) {
  state.view = view;
  document.body.dataset.view = view;
  $$(".nav-button").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  $$(".view-panel").forEach((panel) => panel.classList.remove("active"));
  $(`#${view}View`).classList.add("active");
  if (view !== "tasks") closeStream();
  if (view === "tasks" && state.selectedId) openStream(state.selectedId);
  if (view === "sessions") refreshSessions();
  if (view === "inbox") refreshInbox();
  updateGitHubLink();
}

function filteredRuns() {
  let runs = state.runs;
  if (state.projectFilter !== "all") runs = runs.filter((run) => run.project_id === state.projectFilter);
  if (state.filter === "active") return runs.filter((run) => activeStatuses.has(run.status));
  if (state.filter === "review") return runs.filter((run) => ["review", "failed", "accepted"].includes(run.status));
  return runs;
}

function renderRuns() {
  const runs = filteredRuns();
  $("#runCount").textContent = runs.length;
  $("#taskList").innerHTML = runs.length ? runs.map((run) => `
    <button class="task-card ${run.id === state.selectedId ? "selected" : ""}" data-run-id="${escapeHtml(run.id)}" type="button">
      <div class="task-card-top"><span class="mini-status ${statusClass(run.status)}">${escapeHtml(statusLabel(run.status))}</span><span class="run-id">${relativeTime(run.updated_at)}</span></div>
      <h3>${escapeHtml(run.title)}</h3>
      <div class="task-card-meta"><span>${escapeHtml(run.lane)}</span><span>${escapeHtml(projectById(run.project_id)?.name || run.kind || run.workflow)}</span></div>
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
  state.selectedId = runId;
  location.hash = `task/${encodeURIComponent(runId)}`;
  setView("tasks");
  renderRuns();
  state.events = [];
  closeStream();
  await refreshSelected(true);
  openStream(runId);
}

async function refreshSelected(loadEvents = false) {
  if (!state.selectedId) return;
  const [run, diff] = await Promise.all([api(`/api/runs/${encodeURIComponent(state.selectedId)}`), api(`/api/runs/${encodeURIComponent(state.selectedId)}/diff`)]);
  state.selected = run;
  if (loadEvents) state.events = (await api(`/api/runs/${encodeURIComponent(state.selectedId)}/events`)).events;
  renderDetail(run, diff);
  updateGitHubLink();
}

function renderDetail(run, diff) {
  $("#emptyState").classList.add("hidden");
  $("#runDetail").classList.remove("hidden");
  const status = $("#detailStatus");
  status.textContent = statusLabel(run.status); status.className = `status-pill ${statusClass(run.status)}`;
  $("#detailId").textContent = run.id; $("#detailTitle").textContent = run.title; $("#detailTask").textContent = run.task;
  const metrics = run.metrics || {};
  $("#metrics").innerHTML = [
    ["Input", compactNumber(metrics.input_tokens)], ["Cached", compactNumber(metrics.cached_input_tokens)],
    ["Output", compactNumber(metrics.output_tokens)], ["Tool calls", compactNumber(metrics.tool_calls)],
    ["Cost", metrics.cost_usd ? `$${Number(metrics.cost_usd).toFixed(4)}` : "—"],
  ].map(([label, value]) => `<div class="metric"><small>${label}</small><strong>${escapeHtml(value)}</strong></div>`).join("");
  $("#metadata").innerHTML = [
    ["Lane", run.lane], ["Workflow", run.workflow], ["Project", projectById(run.project_id)?.name || run.project_path],
    ["Branch", run.branch || (run.kind === "tmux" ? "interactive" : "waiting")], ["Worktree", run.worktree_path || run.project_path],
    ["Agent session", run.agent_sessions?.agent || run.agent_session_id || "—"], ["tmux", run.tmux_target ? `${run.tmux_session} · ${run.tmux_target}` : run.tmux_session || "—"],
    ["Attempt", run.kind === "tmux" ? "interactive" : `${run.attempt || 0} / ${(run.max_retries || 0) + 1}`],
  ].map(([label, value]) => `<div class="meta"><small>${escapeHtml(label)}</small><strong title="${escapeHtml(value)}">${escapeHtml(value)}</strong></div>`).join("");
  $("#workflowStrip").classList.toggle("hidden", run.kind === "tmux");
  renderActions(run); renderWorkflow(run); renderEvents();
  $("#diffStat").textContent = diff.stat || "No changed files yet."; $("#diffPatch").textContent = diff.patch || "No diff yet.";
  renderChecks(run.check_results || []); $("#reviewSummary").textContent = run.review_summary || run.last_error || "Review has not run yet.";
}

function renderActions(run) {
  const actions = [];
  if (run.status === "review") actions.push(`<button class="action-button accept" data-action="accept" type="button">Accept</button>`);
  if (["review", "failed", "accepted"].includes(run.status)) actions.push(`<button class="action-button" data-action="resume" type="button">Resume agent</button>`);
  if (["review", "accepted"].includes(run.status)) actions.push(`<button class="action-button" data-action="draft-pr" type="button">Draft PR</button>`);
  if (run.tmux_session || run.agent_sessions?.agent || run.agent_session_id) actions.push(`<button class="action-button" data-action="takeover" type="button">Take over in tmux</button>`);
  if (activeStatuses.has(run.status) && run.status !== "cancelling") actions.push(`<button class="action-button warn" data-action="cancel" type="button">Cancel</button>`);
  if (run.pull_request_url) actions.push(`<a class="action-button accept" href="${escapeHtml(run.pull_request_url)}" target="_blank" rel="noreferrer">Open PR</a>`);
  $("#runActions").innerHTML = actions.join("");
  $$("#runActions [data-action]").forEach((button) => button.addEventListener("click", () => runAction(button.dataset.action)));
}

function renderWorkflow(run) {
  const status = run.status; let current = 0;
  if (run.worktree_path || status === "running") current = 1;
  if (status === "checking") current = 2;
  if (["reviewing", "review", "accepted", "pr_created", "publishing"].includes(status)) current = 3;
  ["stageWorktree", "stageAgent", "stageCheck", "stageReview"].forEach((id, index) => {
    const node = $(`#${id}`); node.classList.toggle("done", index < current || ["review", "accepted", "pr_created"].includes(status)); node.classList.toggle("current", index === current && activeStatuses.has(status));
  });
}

function eventMessage(event) {
  const data = event.data || {};
  if (event.type === "agent.usage") return `in ${compactNumber(data.input_tokens)} · cached ${compactNumber(data.cached_input_tokens)} · out ${compactNumber(data.output_tokens)}`;
  if (event.type.startsWith("agent.tool")) return `${data.tool || data.kind || "tool"}${data.command ? ` · ${data.command}` : ""}${data.exit_code !== undefined ? ` → ${data.exit_code}` : ""}`;
  if (data.message) return data.message; if (data.text) return data.text;
  if (data.command) return `${data.command}${data.returncode !== undefined ? ` → ${data.returncode}` : ""}`;
  if (data.step) return `${data.step}${data.attempt ? ` · attempt ${data.attempt}` : ""}`;
  if (data.status) return data.status; if (data.url) return data.url;
  return Object.keys(data).length ? JSON.stringify(data) : "";
}

function renderEvents() {
  const log = $("#eventLog"); const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 80;
  log.innerHTML = state.events.slice(-500).map((event) => {
    const kind = event.type.includes("failed") ? "failed" : event.type.includes("review") ? "review" : event.type.includes("usage") ? "usage" : "";
    const time = new Date(event.ts).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"});
    return `<div class="event ${kind}"><time>${escapeHtml(time)}</time><span class="event-type" title="${escapeHtml(event.type)}">${escapeHtml(event.type)}</span><span class="event-message">${escapeHtml(eventMessage(event))}</span></div>`;
  }).join("") || `<div class="event"><time>—</time><span class="event-type">waiting</span><span class="event-message">No events yet.</span></div>`;
  if (atBottom) log.scrollTop = log.scrollHeight;
}

function renderChecks(checks) {
  $("#checkResults").innerHTML = checks.length ? checks.map((check) => { const pass = Number(check.returncode) === 0; return `<div class="check-card"><div class="check-head"><span>${escapeHtml(check.command || "No checks configured")}</span><strong class="${pass ? "check-pass" : "check-fail"}">${check.skipped ? "SKIPPED" : pass ? "PASS" : `FAIL ${check.returncode}`}</strong></div><pre class="check-output">${escapeHtml(check.output || "No output.")}</pre></div>`; }).join("") : `<div class="check-output">Checks have not run yet.</div>`;
}

function openStream(runId) {
  if (state.view !== "tasks" || state.stream) return;
  const after = state.events.at(-1)?.seq || 0; const stream = new EventSource(`/api/runs/${encodeURIComponent(runId)}/stream?after=${after}`); state.stream = stream;
  stream.addEventListener("odysseus", (message) => {
    const event = JSON.parse(message.data); if (state.events.some((item) => item.seq === event.seq)) return;
    state.events.push(event); renderEvents(); window.clearTimeout(state.refreshTimer);
    state.refreshTimer = window.setTimeout(async () => { await refreshRuns(); if (["run.review_ready", "run.failed", "run.accepted", "pr.created", "agent.usage", "agent.tool.started"].includes(event.type)) await refreshSelected(); }, 180);
  });
  stream.onopen = () => setConnection(true); stream.onerror = () => setConnection(false);
}
function closeStream() { if (state.stream) state.stream.close(); state.stream = null; }
function setConnection(online) { $(".connection").classList.toggle("online", online); $("#connectionLabel").textContent = online ? "Live" : "Reconnecting"; }

async function copyCommand(command) {
  try { await navigator.clipboard.writeText(command); toast(`Copied: ${command}`); }
  catch { window.prompt("Run this command in your terminal:", command); }
}

async function runAction(action) {
  if (!state.selectedId) return;
  if (action === "resume") { $("#feedbackDialog").showModal(); return; }
  if (action === "draft-pr" && !window.confirm("Commit all worktree changes, push the branch, and create a draft pull request?")) return;
  try {
    const result = await api(`/api/runs/${encodeURIComponent(state.selectedId)}/${action}`, {method: "POST", body: "{}"});
    if (action === "takeover") await copyCommand(result.command);
    else toast(action === "draft-pr" ? "Draft pull request created." : `Action completed: ${action}`);
    await refreshRuns(); await refreshSelected();
  } catch (error) { toast(error.message, true); }
}

async function refreshProjects() {
  state.projects = (await api("/api/projects")).projects;
  const projectOptions = state.projects.map((project) => `<option value="${escapeHtml(project.id)}">${escapeHtml(project.name)}</option>`).join("");
  $("#projectFilter").innerHTML = `<option value="all">All projects</option>${projectOptions}`; $("#projectFilter").value = state.projectFilter;
  $("#taskProjectSelect").innerHTML = `<option value="">Custom path</option>${projectOptions}`;
  $("#inboxProjectSelect").innerHTML = `<option value="">No project</option>${projectOptions}`;
  $("#githubProject").innerHTML = state.projects.filter((project) => project.github_url).map((project) => `<option value="${escapeHtml(project.id)}">${escapeHtml(project.name)}</option>`).join("") || `<option value="">No GitHub projects</option>`;
  renderProjects(); renderRuns(); updateGitHubLink();
}

function renderProjects() {
  $("#projectList").innerHTML = state.projects.length ? state.projects.map((project) => `
    <article class="collection-card"><div class="card-row"><span class="mini-status status-accepted">registered</span><span class="run-id">${escapeHtml(project.branch || "git")}</span></div>
      <h3>${escapeHtml(project.name)}</h3><p>${escapeHtml(project.path)}</p><div class="card-meta">${(project.tags || []).map((tag) => `<span>${escapeHtml(tag)}</span>`).join("") || "<span>automatic</span>"}</div>
      <div class="card-actions"><button class="ghost" data-filter-project="${escapeHtml(project.id)}" type="button">View tasks</button>${project.github_url ? `<a class="action-button" href="${escapeHtml(project.github_url)}" target="_blank" rel="noreferrer">GitHub</a>` : ""}</div></article>`).join("") : `<div class="empty-card">No projects yet. Queue a task, launch a managed tmux session, or add one here.</div>`;
  $$('[data-filter-project]').forEach((button) => button.addEventListener("click", () => { state.projectFilter = button.dataset.filterProject; $("#projectFilter").value = state.projectFilter; renderRuns(); setView("tasks"); }));
}

function updateGitHubLink() {
  const project = projectById(state.selected?.project_id || (state.projectFilter !== "all" ? state.projectFilter : "")); const link = $("#githubButton");
  const url = project?.github_url || state.bootstrap?.repository_url || "https://github.com/jpolec/odysseus";
  link.classList.remove("disabled"); link.href = url; link.title = project?.github_url ? `Open ${project.name} on GitHub` : "Open Odysseus on GitHub";
}

async function refreshSessions() {
  try { state.sessions = (await api("/api/tmux/sessions")).sessions; renderSessions(); $("#sessionNavCount").textContent = state.sessions.length || ""; }
  catch (error) { $("#sessionList").innerHTML = `<div class="empty-card">${escapeHtml(error.message)}</div>`; }
}

function renderSessions() {
  $("#sessionList").innerHTML = state.sessions.length ? state.sessions.map((session) => `
    <article class="collection-card"><div class="card-row"><span class="mini-status ${statusClass(session.status)}">${escapeHtml(session.status)}</span><span class="run-id">${session.attached ? "attached" : "detached"}</span></div>
      <h3>${escapeHtml(session.title && session.title !== "-" ? session.title : session.tmux_session)}</h3><p>${escapeHtml(session.project_path || "Unknown project")}</p>
      <div class="card-meta"><span>${escapeHtml(session.lane)}</span><span>${escapeHtml(session.id)}</span><span>${escapeHtml(session.context_remaining || "—")} context</span>${session.managed ? "<span>managed</span>" : "<span>existing pane</span>"}</div>
      <div class="card-actions">${session.adopted_run_id ? `<button class="ghost" data-open-run="${escapeHtml(session.adopted_run_id)}" type="button">Open task</button>` : `<button class="primary" data-adopt="${escapeHtml(session.id)}" type="button">Adopt</button>`}<button class="ghost" data-attach="${escapeHtml(session.tmux_session)}" data-pane-target="${escapeHtml(session.tmux_target || "")}" type="button">Copy attach command</button></div></article>`).join("") : `<div class="empty-card">No tmux server or sessions are visible. Sessions launched with prefix + y appear here automatically.</div>`;
  $$('[data-open-run]').forEach((button) => button.addEventListener("click", () => selectRun(button.dataset.openRun)));
  $$('[data-attach]').forEach((button) => button.addEventListener("click", () => copyCommand(button.dataset.paneTarget ? `tmux select-pane -t ${button.dataset.paneTarget} \\; attach-session -t ${button.dataset.attach}` : `tmux attach-session -t ${button.dataset.attach}`)));
  $$('[data-adopt]').forEach((button) => button.addEventListener("click", async () => { try { const run = await api(`/api/tmux/sessions/${encodeURIComponent(button.dataset.adopt)}/adopt`, {method: "POST", body: "{}"}); toast("Session adopted into durable history."); await Promise.all([refreshSessions(), refreshRuns(), refreshProjects()]); await selectRun(run.id); } catch (error) { toast(error.message, true); } }));
}

async function refreshInbox() { state.inbox = (await api("/api/inbox")).items; renderInbox(); $("#inboxNavCount").textContent = state.inbox.filter((item) => item.status === "open").length || ""; }
function renderInbox() {
  $("#inboxList").innerHTML = state.inbox.length ? state.inbox.map((item) => `<article class="stack-card"><div class="card-row"><span class="mini-status ${item.status === "open" ? "status-queued" : "status-accepted"}">${escapeHtml(item.status)}</span><span class="run-id">${relativeTime(item.updated_at)}</span></div><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.task)}</p><div class="card-meta"><span>${escapeHtml(item.source)}</span><span>${escapeHtml(projectById(item.project_id)?.name || "no project")}</span><span>${escapeHtml(item.priority)}</span></div><div class="card-actions">${item.status === "open" && item.project_path ? `<button class="primary" data-promote="${escapeHtml(item.id)}" type="button">Queue task</button>` : ""}${item.status === "open" ? `<button class="ghost" data-resolve="${escapeHtml(item.id)}" type="button">Resolve</button>` : ""}</div></article>`).join("") : `<div class="empty-card">Inbox zero. Agents can add follow-ups without changing the project diff.</div>`;
  $$('[data-resolve]').forEach((button) => button.addEventListener("click", async () => { await api(`/api/inbox/${encodeURIComponent(button.dataset.resolve)}/resolve`, {method: "POST", body: "{}"}); await refreshInbox(); }));
  $$('[data-promote]').forEach((button) => button.addEventListener("click", async () => { const run = await api(`/api/inbox/${encodeURIComponent(button.dataset.promote)}/promote`, {method: "POST", body: "{}"}); await Promise.all([refreshInbox(), refreshRuns()]); await selectRun(run.id); }));
}

async function loadIssues() {
  const projectId = $("#githubProject").value; if (!projectId) return;
  $("#issueList").innerHTML = `<div class="empty-card">Loading GitHub issues…</div>`;
  try { const data = await api(`/api/github/issues?project_id=${encodeURIComponent(projectId)}`); renderIssues(data.issues, projectId); }
  catch (error) { $("#issueList").innerHTML = `<div class="empty-card">${escapeHtml(error.message)}</div>`; }
}
function renderIssues(issues, projectId) {
  $("#issueList").innerHTML = issues.length ? issues.map((issue) => `<article class="stack-card"><div class="card-row"><span class="mini-status status-queued">issue #${issue.number}</span><a class="run-id" href="${escapeHtml(issue.url)}" target="_blank" rel="noreferrer">Open ↗</a></div><h3>${escapeHtml(issue.title)}</h3><p>${escapeHtml(issue.body || "No description.")}</p><div class="card-meta">${(issue.labels || []).map((label) => `<span>${escapeHtml(label.name)}</span>`).join("")}</div><div class="card-actions"><button class="primary" data-import-issue="${issue.number}" type="button">Queue task</button></div></article>`).join("") : `<div class="empty-card">No open issues.</div>`;
  $$('[data-import-issue]').forEach((button) => button.addEventListener("click", async () => { const issue = issues.find((item) => String(item.number) === button.dataset.importIssue); try { const run = await api("/api/github/import", {method: "POST", body: JSON.stringify({project_id: projectId, title: issue.title, body: issue.body, url: issue.url})}); await refreshRuns(); await selectRun(run.id); } catch (error) { toast(error.message, true); } }));
}

function bindDialogs() {
  const taskDialog = $("#taskDialog"); [$("#newTaskButton"), $("#emptyNewTask")].forEach((button) => button.addEventListener("click", () => taskDialog.showModal()));
  $("#taskForm").addEventListener("submit", async (event) => { if (event.submitter?.value === "cancel") return; event.preventDefault(); const data = new FormData(event.currentTarget); const project = projectById(data.get("project_id")); const payload = {task: data.get("task"), title: data.get("title"), project_path: project?.path || data.get("project_path"), lane: data.get("lane"), workflow: "agent-check-review", max_retries: Number(data.get("max_retries")), checks: String(data.get("checks") || "").split("\n").map((item) => item.trim()).filter(Boolean)}; try { const run = await api("/api/runs", {method: "POST", body: JSON.stringify(payload)}); taskDialog.close(); event.currentTarget.reset(); toast(`Queued ${run.id}`); await Promise.all([refreshRuns(), refreshProjects()]); await selectRun(run.id); } catch (error) { toast(error.message, true); } });
  $("#feedbackForm").addEventListener("submit", async (event) => { if (event.submitter?.value === "cancel") return; event.preventDefault(); const prompt = new FormData(event.currentTarget).get("feedback"); try { await api(`/api/runs/${encodeURIComponent(state.selectedId)}/resume`, {method: "POST", body: JSON.stringify({prompt})}); $("#feedbackDialog").close(); event.currentTarget.reset(); toast("Existing agent session queued for continuation."); await refreshRuns(); await refreshSelected(); } catch (error) { toast(error.message, true); } });
  $("#newInboxButton").addEventListener("click", () => $("#inboxDialog").showModal());
  $("#inboxForm").addEventListener("submit", async (event) => { if (event.submitter?.value === "cancel") return; event.preventDefault(); const data = new FormData(event.currentTarget); const project = projectById(data.get("project_id")); await api("/api/inbox", {method: "POST", body: JSON.stringify({title: data.get("title"), task: data.get("task"), project_id: project?.id || "", project_path: project?.path || ""})}); $("#inboxDialog").close(); event.currentTarget.reset(); await refreshInbox(); });
  $("#addProjectButton").addEventListener("click", () => $("#projectDialog").showModal());
  $("#projectForm").addEventListener("submit", async (event) => { if (event.submitter?.value === "cancel") return; event.preventDefault(); const data = new FormData(event.currentTarget); try { await api("/api/projects", {method: "POST", body: JSON.stringify({path: data.get("path"), name: data.get("name"), tags: String(data.get("tags") || "").split(",").map((tag) => tag.trim()).filter(Boolean)})}); $("#projectDialog").close(); event.currentTarget.reset(); await refreshProjects(); } catch (error) { toast(error.message, true); } });
}

async function init() {
  try {
    state.bootstrap = await api("/api/bootstrap"); $("#parallelLabel").textContent = `${state.bootstrap.max_parallel} slots`; $("#laneSelect").innerHTML = state.bootstrap.lanes.map((lane) => `<option value="${escapeHtml(lane)}">${escapeHtml(lane)}</option>`).join("");
    bindDialogs();
    $$(".nav-button").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view))); $$('[data-open-view]').forEach((button) => button.addEventListener("click", () => setView(button.dataset.openView)));
    $$(".filter").forEach((button) => button.addEventListener("click", () => { state.filter = button.dataset.filter; $$(".filter").forEach((item) => item.classList.toggle("active", item === button)); renderRuns(); }));
    $$(".tab").forEach((button) => button.addEventListener("click", () => { $$(".tab").forEach((item) => item.classList.toggle("active", item === button)); $$(".tab-pane").forEach((pane) => pane.classList.toggle("active", pane.id === `tab-${button.dataset.tab}`)); }));
    $("#projectFilter").addEventListener("change", (event) => { state.projectFilter = event.target.value; renderRuns(); updateGitHubLink(); }); $("#refreshSessions").addEventListener("click", refreshSessions); $("#loadIssues").addEventListener("click", loadIssues);
    await Promise.all([refreshProjects(), refreshSessions(), refreshInbox()]); await refreshRuns();
    const match = decodeURIComponent(location.hash.slice(1)).match(/^task\/(.+)$/); if (match && state.runs.some((run) => run.id === match[1])) await selectRun(match[1]);
    setConnection(true);
    window.setInterval(() => refreshRuns().catch(() => setConnection(false)), 3000);
    window.setInterval(() => Promise.all([refreshSessions(), refreshInbox()]).catch(() => setConnection(false)), 6000);
  } catch (error) { setConnection(false); toast(error.message, true); }
}

window.addEventListener("beforeunload", closeStream);
init();
