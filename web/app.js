"use strict";

const THEME_KEY = "odysseus-theme";
const SIDEBAR_WIDTH_KEY = "odysseus-sidebar-width";
const DEFAULT_SIDEBAR_WIDTH = 340;
const MIN_SIDEBAR_WIDTH = 280;
const MAX_SIDEBAR_WIDTH = 520;
let savedTheme = "";
try { savedTheme = window.localStorage.getItem(THEME_KEY) || ""; } catch { savedTheme = ""; }
document.documentElement.dataset.theme = savedTheme === "dark" ? "dark" : "light";

const state = {
  bootstrap: null, runs: [], projects: [], sessions: [], inbox: [], attention: [], epics: [], selectedId: null,
  selected: null, selectedDiff: null, selectedDiffRunId: "", selectedDiffLoadingRunId: "",
  events: [], eventsLoadedRunId: "", eventsLoadingRunId: "", eventVisibleLimit: 150,
  selectionGeneration: 0, filter: "active", projectFilter: "all", view: "work",
  stream: null, streamRunId: "", refreshTimer: null, stats: null, searchResults: [], sessionScope: "repositories", taskSection: "summary",
  projectOverview: null, projectSkills: null, projectKnowledge: null, taskSkillCatalog: null, taskSkillRecommendations: null,
  assistantConversations: {}, config: null, resources: null, decisionDiff: null, decisionDiffRunId: "",
  selectedDecisionPaths: [],
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[char]);
const activeStatuses = new Set(["queued", "starting", "running", "checking", "reviewing", "waiting_variants", "cancelling", "publishing"]);
const ciGreenStatuses = new Set(["passed", "success", "green"]);
const ciWaitingStatuses = new Set(["pending", "running", "queued", "in_progress", "waiting", "requested", "repairing"]);
const ciFailedStatuses = new Set(["failed", "failure", "fail", "error", "poll_error", "timed_out", "cancelled", "retry_exhausted"]);
const deliveredDeliveryStatuses = new Set(["applied", "pr_created", "integrated_applied", "integrated_pr_created"]);
const HEAVY_TEXT_LIMIT = 16000;
const UI_COPY = {
  noAction: "No action needed",
  needsYou: "Needs you",
  review: "Review result",
  deliver: "Choose delivery",
  unknown: "Unknown",
  notObserved: "Not observed",
  notApplied: "Saved artifact, not applied",
};

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
  const readable = message === null || message === undefined || !String(message).trim()
    ? (isError ? "Something went wrong. Open Activity for details." : "Done.")
    : String(message);
  node.textContent = readable;
  node.className = `toast visible${isError ? " error" : ""}`;
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => node.className = "toast", 4200);
}

function confirmChoice({eyebrow = "CONFIRM ACTION", title, lead, message, confirmLabel = "Continue"}) {
  const dialog = $("#confirmDialog");
  $("#confirmEyebrow").textContent = eyebrow;
  $("#confirmTitle").textContent = title;
  $("#confirmLead").textContent = lead;
  $("#confirmMessage").textContent = message;
  $("#confirmProceed").textContent = confirmLabel;
  dialog.returnValue = "cancel";
  dialog.showModal();
  return new Promise((resolve) => dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm"), {once: true}));
}

function setSidebarWidth(width, persist = true) {
  const value = Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, Math.round(Number(width) || DEFAULT_SIDEBAR_WIDTH)));
  document.documentElement.style.setProperty("--sidebar-width", `${value}px`);
  const handle = $("#sidebarResizer");
  if (handle) handle.setAttribute("aria-valuenow", String(value));
  if (persist) {
    try { window.localStorage.setItem(SIDEBAR_WIDTH_KEY, String(value)); } catch { /* Width remains active for this tab. */ }
  }
}

function resetSidebarWidth() {
  try { window.localStorage.removeItem(SIDEBAR_WIDTH_KEY); } catch { /* Ignore storage failures. */ }
  setSidebarWidth(DEFAULT_SIDEBAR_WIDTH, false);
  toast("Sidebar width reset.");
}

function initSidebarResize() {
  let saved = "";
  try { saved = window.localStorage.getItem(SIDEBAR_WIDTH_KEY) || ""; } catch { saved = ""; }
  setSidebarWidth(saved || DEFAULT_SIDEBAR_WIDTH, false);
  const handle = $("#sidebarResizer");
  if (!handle) return;
  let dragging = false;
  const updateFromClientX = (clientX) => {
    const benchLeft = $(".workbench")?.getBoundingClientRect().left || 0;
    const activityWidth = $(".activity-bar")?.getBoundingClientRect().width || 0;
    setSidebarWidth(clientX - benchLeft - activityWidth);
  };
  handle.addEventListener("pointerdown", (event) => {
    dragging = true;
    handle.setPointerCapture(event.pointerId);
    updateFromClientX(event.clientX);
  });
  handle.addEventListener("pointermove", (event) => { if (dragging) updateFromClientX(event.clientX); });
  handle.addEventListener("pointerup", (event) => {
    dragging = false;
    try { handle.releasePointerCapture(event.pointerId); } catch { /* Pointer capture may already be released. */ }
  });
  handle.addEventListener("keydown", (event) => {
    const current = Number(handle.getAttribute("aria-valuenow") || DEFAULT_SIDEBAR_WIDTH);
    if (event.key === "ArrowLeft") { event.preventDefault(); setSidebarWidth(current - (event.shiftKey ? 40 : 10)); }
    if (event.key === "ArrowRight") { event.preventDefault(); setSidebarWidth(current + (event.shiftKey ? 40 : 10)); }
    if (event.key === "Home") { event.preventDefault(); setSidebarWidth(MIN_SIDEBAR_WIDTH); }
    if (event.key === "End") { event.preventDefault(); setSidebarWidth(MAX_SIDEBAR_WIDTH); }
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); resetSidebarWidth(); }
  });
  $("#resetSidebarWidth")?.addEventListener("click", resetSidebarWidth);
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
function formatBytes(value) {
  let size = Number(value || 0);
  for (const unit of ["B", "KB", "MB", "GB"]) {
    if (size < 1024 || unit === "GB") return unit === "B" ? `${Math.round(size)} B` : `${size.toFixed(1)} ${unit}`;
    size /= 1024;
  }
  return `${size.toFixed(1)} GB`;
}
function statusClass(status) { return `status-${String(status || "unknown").replace(/[^a-z_]/g, "")}`; }
function statusLabel(status) {
  const labels = {queued: "waiting", waiting_variants: "running variants", review: "ready for review", decided: "decided", rejected: "rejected"};
  const key = String(status || "unknown");
  return labels[key] || key.replaceAll("_", " ");
}
function runActionLine(run) {
  const delivery = run?.delivery || {};
  if (run?.kind === "tmux") return "Open the terminal.";
  if (run?.status === "review") return "Review result.";
  if (run?.status === "pr_created") return ciActionLine(run);
  if (run?.status === "accepted" && delivery.status === "integrated_pr_created") return "Delivered in integration PR.";
  if (run?.status === "accepted" && deliveredDeliveryStatuses.has(delivery.status)) return "No action needed.";
  if (run?.status === "accepted" && delivery.status === "failed") return "Fix apply prerequisite.";
  if (run?.status === "accepted") return "Choose delivery.";
  if (run?.status === "decided") return "No action needed.";
  if (run?.status === "attention") return "Answer Needs You.";
  if (run?.status === "failed") return "Resume with feedback.";
  if (run?.status === "blocked") return "Accept predecessor.";
  if (run?.status === "queued") return "Wait for a slot.";
  if (run?.status === "waiting_variants") return "Wait for candidates.";
  if (activeStatuses.has(run?.status)) return "No action needed.";
  return UI_COPY.noAction;
}
function ciActionLine(run) {
  const ci = run?.ci || {};
  const status = String(ci.status || "not_started").toLowerCase();
  const failingChecks = (ci.checks || []).some((item) => ciFailedStatuses.has(String(item.bucket || item.state || "").toLowerCase()));
  const exhausted = status === "retry_exhausted" || (status === "failed" && Number(ci.max_attempts || 0) > 0 && Number(ci.attempt || 0) >= Number(ci.max_attempts || 0));
  if (ciGreenStatuses.has(status)) return "No action needed.";
  if (status === "not_started") return "Poll CI.";
  if (run?.ci_retry_active || ciWaitingStatuses.has(status)) return status === "repairing" || run?.ci_retry_active ? "Repair in progress." : "Wait for CI.";
  if (exhausted) return "Resume CI repair.";
  if (ciFailedStatuses.has(status) || failingChecks) return "Repair failed CI.";
  return "Check GitHub CI.";
}
function blockedPrerequisite(run) {
  const deps = run?.dependency_keys || run?.depends_on || [];
  return deps.length ? `Waiting for ${deps[0]}` : "Waiting for predecessor acceptance";
}
function truncateText(value, limit = HEAVY_TEXT_LIMIT) {
  const content = String(value || "");
  if (content.length <= limit) return content;
  return `${content.slice(0, limit)}\n\n[truncated in browser: ${compactNumber(content.length - limit)} more characters]`;
}
function isLoopbackHost(hostname) {
  const host = String(hostname || "").toLowerCase().replace(/^\[|\]$/g, "");
  return host === "localhost" || host === "::1" || host === "0:0:0:0:0:0:0:1" || host === "127.0.0.1" || host.startsWith("127.");
}
function reachablePreviewUrl(previewUrl) {
  if (!previewUrl) return "";
  try {
    const localUrl = new URL(previewUrl, window.location.href);
    if (!isLoopbackHost(localUrl.hostname) || isLoopbackHost(window.location.hostname)) return "";
    const remoteUrl = new URL(localUrl.href);
    remoteUrl.hostname = window.location.hostname;
    return remoteUrl.href;
  } catch {
    return "";
  }
}
function previewLinks(previewUrl) {
  if (!previewUrl) return "";
  const tailscaleUrl = reachablePreviewUrl(previewUrl);
  return `<div class="preview-actions"><a class="ghost button-link" href="${escapeHtml(previewUrl)}" target="_blank" rel="noreferrer">Open local preview</a>${tailscaleUrl ? `<a class="ghost button-link" href="${escapeHtml(tailscaleUrl)}" target="_blank" rel="noreferrer" title="Uses the current Odysseus host with the preview port">Open via Tailscale</a>` : ""}</div>`;
}
function projectById(id) { return state.projects.find((project) => project.id === id); }
function projectName(project) { return project?.display_name || project?.name || project?.folder_name || "Repository"; }
function projectRepository(project) { return project?.repository || project?.folder_name || "Local repository"; }
function projectHasDuplicateCheckout(project) { return Boolean(project?.repository) && state.projects.filter((item) => item.repository === project.repository).length > 1; }
function projectCheckoutLabel(project) {
  if (projectHasDuplicateCheckout(project)) return `Folder: ${project.folder_name || project.path}`;
  if (project?.repository && project.repository !== project.folder_name) return project.repository;
  return project?.folder_name || project?.path || "Local repository";
}
function runTitle(run, fallback = "task") {
  return String(run?.title || run?.task || fallback).split("\n")[0].trim() || fallback;
}
function projectOptionLabel(project) {
  const name = projectName(project);
  return projectHasDuplicateCheckout(project) ? `${name} — ${project.folder_name}` : name;
}
function activeProject() { return state.projectFilter === "all" ? null : projectById(state.projectFilter); }
function discoveredSessionForRun(run) { return state.sessions.find((session) => session.adopted_run_id === run.id); }
function preferredProjectId() {
  const candidates = [state.selected?.project_id, state.projectFilter !== "all" ? state.projectFilter : "", state.runs[0]?.project_id, state.projects[0]?.id];
  return candidates.find((id) => id && projectById(id)) || "";
}
function syncCustomProject(select, container) {
  if (!select || !container) return;
  const custom = !select.value;
  container.classList.toggle("hidden", !custom);
  const input = container.querySelector("input");
  input.required = custom;
  if (!custom) input.value = "";
}
function prepareProjectSelect(select, container) {
  const preferred = preferredProjectId();
  if (preferred && [...select.options].some((option) => option.value === preferred)) select.value = preferred;
  syncCustomProject(select, container);
}

function syncThemeButton() {
  const button = $("#themeToggle");
  if (!button) return;
  const isDark = document.documentElement.dataset.theme === "dark";
  button.setAttribute("aria-label", isDark ? "Switch to light theme" : "Switch to dark theme");
  button.title = isDark ? "Switch to light theme" : "Switch to dark theme";
  button.setAttribute("aria-pressed", String(isDark));
}

function toggleTheme() {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { window.localStorage.setItem(THEME_KEY, next); } catch { /* Theme remains active for this tab. */ }
  syncThemeButton();
}

function setFormSubmitting(form, submitting, activeButton, label) {
  form.setAttribute("aria-busy", submitting ? "true" : "false");
  [...form.elements].forEach((element) => {
    if (element.type !== "hidden") element.disabled = submitting;
  });
  if (activeButton && label) activeButton.textContent = label;
}

function setView(view) {
  if (view === "projects" && !$("#projectsView")) view = "work";
  state.view = view;
  document.body.dataset.view = view;
  document.body.classList.toggle("task-open", view === "tasks");
  $$(".nav-button").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  $$(".view-panel").forEach((panel) => panel.classList.remove("active"));
  $(`#${view}View`)?.classList.add("active");
  const surfaceNames = {work: "Repositories", attention: "Needs You", epics: "Plans", tasks: "Task", sessions: "Terminals", inbox: "Follow-ups", projects: "Manage repositories", insights: "Search & insights", github: "GitHub issues", settings: "Settings"};
  const project = activeProject();
  const scopedProject = ["work", "tasks", "epics", "github"].includes(view) ? project : null;
  $("#titleProject").textContent = scopedProject ? projectName(scopedProject) : "Odysseus";
  $("#titleSurface").textContent = surfaceNames[view] || "Overview";
  $("#allWorkButton").classList.toggle("selected", view === "work" && state.projectFilter === "all");
  $("#sidebarAttentionButton").classList.toggle("selected", view === "attention");
  if (view !== "tasks") closeStream();
  if (view === "tasks" && state.selectedId) openStream(state.selectedId);
  if (view === "tasks" && !state.selectedId && state.runs.length) selectRun(state.runs[0].id);
  if (view === "sessions") refreshSessions();
  if (view === "inbox") refreshInbox();
  if (view === "attention") refreshAttention();
  if (view === "epics") refreshEpics();
  if (view === "settings") refreshSettings();
  if (view === "github" && project && [...$("#githubProject").options].some((option) => option.value === project.id)) $("#githubProject").value = project.id;
  if (view === "insights") refreshInsights();
  if (view === "work") renderWork();
  updateGitHubLink();
}

function activateTab(name) {
  const selectedTab = $(`.tab[data-tab="${name}"]`);
  if (!selectedTab) return;
  const inspector = selectedTab.closest(".inspector-panel");
  [...inspector.querySelectorAll(".tab")].forEach((item) => item.classList.toggle("active", item.dataset.tab === name));
  [...inspector.querySelectorAll(".tab-pane")].forEach((pane) => pane.classList.toggle("active", pane.id === `tab-${name}`));
  const section = ["diff", "integration"].includes(name) ? "changes" : "evidence";
  activateTaskSection(section);
}

function activateTaskSection(name) {
  state.taskSection = name;
  $$(".task-section-tab").forEach((item) => item.classList.toggle("active", item.dataset.section === name));
  $$(".task-section-pane").forEach((pane) => pane.classList.toggle("active", pane.id === `task-section-${name}`));
  renderVisibleHeavyPanels().catch((error) => toast(error.message, true));
}

function filteredRuns() {
  let runs = state.runs;
  if (state.projectFilter !== "all") runs = runs.filter((run) => run.project_id === state.projectFilter);
  if (state.filter === "active") return runs.filter((run) => activeStatuses.has(run.status));
  if (state.filter === "review") return runs.filter((run) => ["attention", "blocked", "review", "failed", "accepted"].includes(run.status));
  return runs;
}

function runsForProject(projectId) { return state.runs.filter((run) => run.project_id === projectId); }
function attentionForProject(projectId) { return state.attention.filter((item) => item.project_id === projectId); }
function projectTerminalCount(project) { return state.sessions.filter((session) => session.project_path === project.path).length; }
function repositoryScopedSessions() {
  const project = activeProject();
  if (project) return state.sessions.filter((session) => session.project_path === project.path);
  const projectPaths = new Set(state.projects.map((project) => project.path));
  return state.sessions.filter((session) => projectPaths.has(session.project_path));
}
function updateSessionNavCount() {
  const count = repositoryScopedSessions().length;
  $("#sessionNavCount").textContent = count || "";
}

function environmentFromForm(data) {
  const profile = String(data.get("environment_profile") || "");
  const result = profile ? {profile} : {};
  if (profile !== "docker") return result;
  const image = String(data.get("environment_image") || "").trim();
  if (image) result.image = image;
  result.network = String(data.get("environment_network") || "bridge");
  const allowEnv = String(data.get("environment_allow_env") || "").split(",").map((value) => value.trim()).filter(Boolean);
  if (allowEnv.length) result.allow_env = allowEnv;
  const cpus = Number(data.get("environment_cpus") || 0);
  if (cpus) result.cpus = cpus;
  const memory = String(data.get("environment_memory") || "").trim();
  if (memory) result.memory = memory;
  const ports = {};
  String(data.get("environment_ports") || "").split("\n").map((value) => value.trim()).filter(Boolean).forEach((line) => {
    const [name, port] = line.split("=", 2);
    if (!name || !port || !Number(port)) throw new Error("Preview ports must use NAME=CONTAINER_PORT, one per line.");
    ports[name.trim()] = Number(port);
  });
  if (Object.keys(ports).length) result.ports = ports;
  return result;
}

function renderProjectTree() {
  $("#projectCount").textContent = state.projects.length;
  $("#allWorkCount").textContent = state.projects.length;
  $("#sidebarAttentionCount").textContent = state.attention.length;
  updateSessionNavCount();
  const currentProject = activeProject();
  $(".task-section").classList.toggle("hidden", !currentProject);
  $("#taskSectionTitle").textContent = "TASKS";
  $("#projectTree").innerHTML = state.projects.length ? state.projects.map((project) => {
    const selected = project.id === state.projectFilter;
    const runs = runsForProject(project.id);
    const active = runs.filter((run) => activeStatuses.has(run.status)).length;
    const count = active ? `${active} active` : `${runs.length} task${runs.length === 1 ? "" : "s"}`;
    return `<div class="project-node ${selected ? "selected" : ""}"><button class="project-row ${selected ? "selected" : ""}" data-select-project="${escapeHtml(project.id)}" type="button"><span class="repository-icon">R</span><span class="project-row-copy"><strong>${escapeHtml(projectName(project))}</strong><small>${escapeHtml(projectCheckoutLabel(project))}</small></span><span class="project-row-count">${escapeHtml(count)}</span></button></div>`;
  }).join("") : `<div class="empty-list">Add a repository to start.</div>`;
  $$('[data-select-project]').forEach((button) => button.addEventListener("click", () => selectProject(button.dataset.selectProject)));
}

function selectProject(projectId = "all") {
  state.selectionGeneration += 1;
  closeStream();
  state.projectFilter = projectId && projectById(projectId) ? projectId : "all";
  state.selectedId = null;
  state.selected = null;
  state.selectedDecisionPaths = [];
  resetHeavyTaskState();
  $("#projectFilter").value = state.projectFilter;
  location.hash = state.projectFilter === "all" ? "" : `project/${encodeURIComponent(state.projectFilter)}`;
  renderProjectTree();
  renderRuns();
  setView("work");
  refreshProjectOverview().catch((error) => toast(error.message, true));
}

async function refreshProjectOverview() {
  const project = activeProject();
  if (!project) { state.projectOverview = null; state.projectSkills = null; state.projectKnowledge = null; renderProjectKnowledge(); return; }
  const [overview, skills, knowledge] = await Promise.all([
    api(`/api/projects/${encodeURIComponent(project.id)}/overview`),
    api(`/api/projects/${encodeURIComponent(project.id)}/skills`),
    api(`/api/projects/${encodeURIComponent(project.id)}/knowledge`),
  ]);
  state.projectOverview = overview;
  state.projectSkills = skills;
  state.projectKnowledge = knowledge;
  if (activeProject()?.id === project.id) renderProjectKnowledge();
}

async function refreshTaskSkillChoices() {
  const projectId = $("#taskProjectSelect").value;
  state.taskSkillCatalog = projectId ? await api(`/api/projects/${encodeURIComponent(projectId)}/skills`) : null;
  renderTaskSkillChoices();
  scheduleTaskSkillRecommendations();
}

function renderTaskSkillChoices() {
  const container = $("#taskSkillChoices");
  const manual = $("#taskSkillMode").value === "manual";
  container.classList.toggle("hidden", !manual);
  if (!manual) return;
  const skills = (state.taskSkillCatalog?.skills || []).filter((skill) => skill.mode !== "disabled");
  container.innerHTML = skills.length ? skills.map((skill) => `<label class="task-skill-choice"><input type="checkbox" name="skills" value="${escapeHtml(skill.name)}" ${skill.mode === "required" ? "checked disabled" : ""}><span><strong>${escapeHtml(skill.name)}</strong><small>${escapeHtml(skill.description)}</small></span>${skill.mode === "required" ? `<em>required</em>` : ""}</label>`).join("") : `<div class="empty-list">Choose a registered repository to see its skills.</div>`;
}

function scheduleTaskSkillRecommendations() {
  window.clearTimeout(scheduleTaskSkillRecommendations.timer);
  scheduleTaskSkillRecommendations.timer = window.setTimeout(refreshTaskSkillRecommendations, 350);
}

async function refreshTaskSkillRecommendations() {
  const projectId = $("#taskProjectSelect").value;
  const task = $("#taskPrompt").value.trim();
  const automatic = $("#taskSkillMode").value === "auto";
  if (!projectId || !automatic || task.length < 4) {
    state.taskSkillRecommendations = null;
    renderTaskSkillRecommendations();
    return;
  }
  const expected = `${projectId}\n${task}`;
  const result = await api(`/api/projects/${encodeURIComponent(projectId)}/skills/recommend`, {method: "POST", body: JSON.stringify({task})});
  if (`${$("#taskProjectSelect").value}\n${$("#taskPrompt").value.trim()}` !== expected) return;
  state.taskSkillRecommendations = result;
  renderTaskSkillRecommendations();
}

function renderTaskSkillRecommendations() {
  const container = $("#taskSkillRecommendations");
  const selected = (state.taskSkillRecommendations?.recommendations || []).filter((item) => item.selected);
  container.classList.toggle("hidden", $("#taskSkillMode").value !== "auto" || !selected.length);
  container.innerHTML = selected.length ? `<small>AUTO WILL ATTACH</small>${selected.map((item) => `<div><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml((item.reasons || [])[0] || "repository policy")}</span></div>`).join("")}` : "";
}

function renderProjectSkills() {
  const catalog = state.projectSkills;
  const skills = catalog?.skills || [];
  $("#projectSkillCount").textContent = `${skills.filter((skill) => skill.mode !== "disabled").length} enabled`;
  $("#projectSkillList").innerHTML = skills.length ? skills.map((skill) => { const stats = skill.effectiveness || {}; const outcome = stats.runs ? `${stats.runs} run${stats.runs === 1 ? "" : "s"}${stats.success_rate === null ? " · awaiting outcomes" : ` · ${Math.round(Number(stats.success_rate) * 100)}% successful`}` : "No repository history yet"; return `<details class="project-skill" data-skill="${escapeHtml(skill.name)}"><summary><span><strong>${escapeHtml(skill.name)}</strong><small>${escapeHtml(skill.description)}</small><em class="skill-effectiveness">${escapeHtml(outcome)}</em></span><span class="skill-source">${escapeHtml(skill.scope)}</span><select class="skill-policy" data-skill-policy="${escapeHtml(skill.name)}" aria-label="Policy for ${escapeHtml(skill.name)}"><option value="auto" ${skill.mode === "auto" ? "selected" : ""}>Auto</option><option value="required" ${skill.mode === "required" ? "selected" : ""}>Required</option><option value="disabled" ${skill.mode === "disabled" ? "selected" : ""}>Disabled</option></select></summary><div class="skill-preview"><div>${(skill.triggers || []).map((trigger) => `<span>${escapeHtml(trigger)}</span>`).join("")}</div>${stats.runs ? `<p class="skill-stats">Average ${compactNumber(stats.avg_tokens)} tokens · $${Number(stats.avg_cost_usd || 0).toFixed(4)} · ${Number(stats.interventions || 0)} human interventions</p>` : ""}<pre>${escapeHtml(skill.preview || "No preview available.")}</pre></div></details>`; }).join("") : `<div class="empty-list">No valid SKILL.md files found.</div>`;
  $$('[data-skill-policy]').forEach((select) => {
    select.addEventListener("click", (event) => event.stopPropagation());
    select.addEventListener("change", async (event) => {
      const project = activeProject();
      if (!project) return;
      const name = event.currentTarget.dataset.skillPolicy;
      try {
        state.projectSkills = await api(`/api/projects/${encodeURIComponent(project.id)}/skills`, {method: "POST", body: JSON.stringify({policies: {[name]: event.currentTarget.value}})});
        renderProjectSkills();
        toast(`${name} policy updated.`);
      } catch (error) { toast(error.message, true); }
    });
  });
}

function openKnowledgeDialog(item = null) {
  const form = $("#knowledgeForm");
  form.reset();
  form.elements.id.value = item?.status === "suggested" ? "" : item?.id || "";
  form.elements.source.value = item?.source || "operator";
  form.elements.title.value = item?.title || "";
  form.elements.content.value = item?.content || "";
  form.elements.triggers.value = (item?.triggers || []).join(", ");
  form.elements.folders.value = (item?.folders || []).join(", ");
  form.elements.enabled.checked = item?.status === "suggested" ? true : item?.enabled !== false;
  $("#knowledgeDialog").showModal();
}

function renderProjectMemory() {
  const catalog = state.projectKnowledge;
  const items = catalog?.items || [];
  const active = items.filter((item) => item.enabled).length;
  $("#projectMemoryCount").textContent = `${active} active`;
  $("#projectMemoryList").innerHTML = items.length ? items.map((item) => `<article class="memory-item ${item.enabled ? "" : "disabled"}"><div><strong>${escapeHtml(item.title)}</strong><p>${escapeHtml(item.content)}</p><span>${[...(item.triggers || []).map((value) => `trigger: ${value}`), ...(item.folders || []).map((value) => `folder: ${value}`)].map(escapeHtml).join(" · ") || "Always attach"}</span></div><label class="memory-toggle"><input type="checkbox" data-memory-toggle="${escapeHtml(item.id)}" ${item.enabled ? "checked" : ""}><span>${item.enabled ? "On" : "Off"}</span></label><button class="ghost compact" data-memory-edit="${escapeHtml(item.id)}" type="button">Edit</button></article>`).join("") : `<div class="empty-list">No repository-specific memory yet. Add only facts that agents cannot infer reliably from the codebase.</div>`;
  const suggestions = catalog?.suggestions || [];
  $("#memorySuggestions").classList.toggle("hidden", !suggestions.length);
  $("#memorySuggestions").innerHTML = suggestions.length ? `<header><div><small>SUGGESTED FROM HISTORY</small><strong>Repeated guidance worth remembering</strong></div><span>${suggestions.length}</span></header>${suggestions.map((item, index) => `<article><div><strong>${escapeHtml(item.content)}</strong><small>Seen ${item.evidence_count} times · requires your approval</small></div><button class="ghost compact" data-memory-suggestion="${index}" type="button">Review & add</button></article>`).join("")}` : "";
  $$('[data-memory-edit]').forEach((button) => button.addEventListener("click", () => openKnowledgeDialog(items.find((item) => item.id === button.dataset.memoryEdit))));
  $$('[data-memory-suggestion]').forEach((button) => button.addEventListener("click", () => openKnowledgeDialog(suggestions[Number(button.dataset.memorySuggestion)])));
  $$('[data-memory-toggle]').forEach((input) => input.addEventListener("change", async () => {
    const project = activeProject();
    const item = items.find((value) => value.id === input.dataset.memoryToggle);
    if (!project || !item) return;
    try {
      state.projectKnowledge = await api(`/api/projects/${encodeURIComponent(project.id)}/knowledge`, {method: "POST", body: JSON.stringify({...item, enabled: input.checked})});
      renderProjectMemory();
      toast(`${item.title} ${input.checked ? "enabled" : "disabled"}.`);
    } catch (error) { toast(error.message, true); }
  }));
}

function decisionStateLabel(value) {
  return ({unplanned: "Not planned", proposed: "Plan ready", planned: "Planned", in_progress: "In progress", completed: "Completed", blocked: "Blocked"})[value] || statusLabel(value);
}

function renderProjectDecisions() {
  const decisions = state.projectOverview?.decisions || [];
  const catalog = state.projectOverview?.decision_summary || {};
  const knownPaths = new Set(decisions.map((item) => item.path));
  state.selectedDecisionPaths = state.selectedDecisionPaths.filter((path) => knownPaths.has(path));
  const completed = decisions.filter((item) => item.implementation?.state === "completed").length;
  const active = decisions.filter((item) => ["proposed", "planned", "in_progress"].includes(item.implementation?.state)).length;
  const unplanned = decisions.filter((item) => item.implementation?.state === "unplanned").length;
  const tokens = Number(catalog.tokens || 0);
  $("#projectDecisionCount").textContent = `${decisions.length} ADR${decisions.length === 1 ? "" : "s"}`;
  $("#projectDecisionSummary").innerHTML = [
    [completed, "completed"], [active, "active plans"], [unplanned, "not planned"], [compactNumber(tokens), "tokens"], [catalog.cost_usd === null || catalog.cost_usd === undefined ? "Unknown" : `$${Number(catalog.cost_usd).toFixed(2)}`, "reported cost"],
  ].map(([value, label]) => `<div><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span></div>`).join("");
  $("#projectDecisionList").innerHTML = decisions.length ? decisions.map((item) => {
    const implementation = item.implementation || {};
    const selected = state.selectedDecisionPaths.includes(item.path);
    const progress = implementation.tasks ? `${implementation.completed_tasks || 0}/${implementation.tasks} tasks` : "No task graph";
    const economics = implementation.tokens ? `${compactNumber(implementation.tokens)} tokens${implementation.cost_usd === null || implementation.cost_usd === undefined ? " · cost unknown" : ` · $${Number(implementation.cost_usd).toFixed(2)}`}` : "No usage yet";
    return `<article class="project-decision ${selected ? "selected" : ""}">
      <label class="project-decision-select"><input type="checkbox" data-decision-path="${escapeHtml(item.path)}" ${selected ? "checked" : ""}><span class="sr-only">Select ${escapeHtml(item.title)}</span></label>
      <div class="project-decision-copy"><div class="project-decision-title"><strong>${escapeHtml(item.title)}</strong><span class="decision-record-status decision-record-${escapeHtml(item.status)}">${escapeHtml(item.status)}</span></div><p>${escapeHtml(item.summary || "No decision summary found.")}</p><code>${escapeHtml(item.path)} · ${escapeHtml(String(item.sha256 || "").slice(0, 8))}</code></div>
      <div class="project-decision-progress"><strong class="decision-progress-${escapeHtml(implementation.state || "unplanned")}">${escapeHtml(decisionStateLabel(implementation.state))}</strong><span>${escapeHtml(progress)}</span><small>${escapeHtml(economics)}</small>${(item.epic_ids || []).length ? `<button class="text-button" data-open-decision-plan type="button">View plan history</button>` : ""}</div>
    </article>`;
  }).join("") : `<div class="decision-empty"><strong>No ADRs found.</strong><p>Add Markdown files such as <code>_ADR/0001-short-title.md</code>. Include <code>Status: Proposed</code> or <code>Status: Accepted</code>; Odysseus will discover them without changing the repository.</p></div>`;
  const button = $("#planSelectedDecisions");
  button.disabled = !state.selectedDecisionPaths.length;
  button.textContent = state.selectedDecisionPaths.length ? `Plan selected (${state.selectedDecisionPaths.length})` : "Plan selected";
  $$('[data-decision-path]').forEach((input) => input.addEventListener("change", () => {
    const paths = new Set(state.selectedDecisionPaths);
    if (input.checked) paths.add(input.dataset.decisionPath); else paths.delete(input.dataset.decisionPath);
    state.selectedDecisionPaths = [...paths];
    renderProjectDecisions();
  }));
  $$('[data-open-decision-plan]').forEach((button) => button.addEventListener("click", () => setView("epics")));
}

function openEpicDialog(sourcePaths = []) {
  const form = $("#epicForm");
  form.reset();
  prepareProjectSelect($("#epicProjectSelect"), $("#epicCustomProject"));
  state.selectedDecisionPaths = [...sourcePaths];
  const decisions = state.projectOverview?.decisions || [];
  const selected = decisions.filter((item) => state.selectedDecisionPaths.includes(item.path));
  $("#epicProjectSelect").disabled = Boolean(selected.length);
  const sourcePanel = $("#epicDecisionSources");
  sourcePanel.classList.toggle("hidden", !selected.length);
  sourcePanel.innerHTML = selected.length ? `<small>SELECTED DECISIONS</small><strong>${selected.length} ADR${selected.length === 1 ? "" : "s"} will be frozen into this plan</strong><div>${selected.map((item) => `<span>${escapeHtml(item.path)} <code>${escapeHtml(String(item.sha256 || "").slice(0, 8))}</code></span>`).join("")}</div>` : "";
  if (selected.length) form.elements.requirement.value = `Implement the selected architecture decision${selected.length === 1 ? "" : "s"} as one coherent, verified change. Preserve the recorded constraints and show any ambiguity before implementation.`;
  $("#epicDialog").showModal();
}

function renderProjectKnowledge() {
  const project = activeProject();
  const overview = state.projectOverview;
  const home = $("#projectHome");
  home.classList.toggle("hidden", !project);
  if (!project) return;
  if (!overview || overview.project?.id !== project.id) {
    $("#projectAbout").textContent = "Loading README, instructions, commits, and repository activity…";
    $("#projectAboutSource").textContent = "";
    $("#projectContextSources").innerHTML = `<div class="empty-list">Discovering repository context…</div>`;
    $("#projectSkillList").innerHTML = `<div class="empty-list">Loading repository skills…</div>`;
    $("#projectMemoryList").innerHTML = `<div class="empty-list">Loading repository memory…</div>`;
    $("#projectDecisionList").innerHTML = `<div class="empty-list">Discovering architecture decisions…</div>`;
    $("#projectCommitList").innerHTML = `<div class="empty-list">Loading Git history…</div>`;
    $("#projectTimeline").innerHTML = `<div class="empty-list">Building repository timeline…</div>`;
    return;
  }
  $("#projectAbout").textContent = overview.about;
  $("#projectAboutSource").textContent = overview.profile?.summary ? "Odysseus repository overview" : overview.readme?.path ? `Read from ${overview.readme.path}` : "No README found";
  $("#projectNotes").textContent = overview.profile?.notes || "";
  $("#projectNotes").classList.toggle("hidden", !overview.profile?.notes);
  $("#projectStack").innerHTML = (overview.stack || []).map((item) => `<span>${escapeHtml(item)}</span>`).join("") || `<span>Stack not inferred</span>`;
  const sources = [...(overview.readme ? [{...overview.readme, kind: "README"}] : []), ...(overview.instructions || []).map((item) => ({...item, kind: "Instructions"}))];
  $("#projectContextCount").textContent = `${sources.length} source${sources.length === 1 ? "" : "s"}`;
  $("#projectContextSources").innerHTML = sources.length ? sources.map((source) => `<div class="context-source"><span>${escapeHtml(source.kind)}</span><div><strong>${escapeHtml(source.path)}</strong><small>${escapeHtml(source.summary || "Detected repository context")}</small></div><code>${escapeHtml(String(source.sha256 || "").slice(0, 8))}</code></div>`).join("") : `<div class="empty-list">No README or agent instruction files detected.</div>`;
  $("#projectCommitList").innerHTML = (overview.commits || []).length ? overview.commits.map((commit) => `<div class="project-commit"><code>${escapeHtml(commit.short_sha)}</code><div><strong>${escapeHtml(commit.subject)}</strong><small>${escapeHtml(commit.author)} · ${relativeTime(commit.ts)} ago</small></div></div>`).join("") : `<div class="empty-list">No Git commits found.</div>`;
  $("#projectTimeline").innerHTML = (overview.activity || []).length ? overview.activity.slice(0, 12).map((item) => `<button class="timeline-entry" data-timeline-run="${escapeHtml(item.run_id)}" type="button"><span class="timeline-dot"></span><div><small>${escapeHtml(statusLabel(item.type))} · ${relativeTime(item.ts)} ago</small><strong>${escapeHtml(item.run_title)}</strong><p>${escapeHtml(item.summary)}</p></div></button>`).join("") : `<div class="empty-list">Activity appears after the first task.</div>`;
  renderProjectDecisions();
  renderProjectSkills();
  renderProjectMemory();
  $$('[data-timeline-run]').forEach((button) => button.addEventListener("click", () => selectRun(button.dataset.timelineRun)));
}

function renderJourney() {
  const project = activeProject();
  const projectRuns = project ? runsForProject(project.id) : [];
  const projectAttention = project ? attentionForProject(project.id) : [];
  const current = !project ? 1 : projectRuns.length ? 3 : 2;
  const buttons = $$('[data-journey-step]');
  buttons.forEach((button) => {
    const step = Number(button.dataset.journeyStep);
    button.classList.toggle("done", step < current);
    button.classList.toggle("current", step === current);
    button.classList.toggle("upcoming", step > current);
    if (step === current) button.setAttribute("aria-current", "step");
    else button.removeAttribute("aria-current");
  });
  $('[data-journey-step="1"] small').textContent = project
    ? `${projectName(project)} · ${project.folder_name || "local folder"}`
    : state.projects.length ? "Pick a Git repository" : "Add your first Git repository";
  $('[data-journey-step="2"] small').textContent = project
    ? `Describe what the agent should change in ${projectName(project)}`
    : "Choose a repository, then describe one outcome";
  $('[data-journey-step="3"] small').textContent = projectAttention.length
    ? `${projectAttention.length} decision${projectAttention.length === 1 ? "" : "s"} waiting for you`
    : projectRuns.length ? "Watch progress; act only when asked" : "Odysseus runs the agent and checks";
  buttons[0].onclick = () => {
    setView("work");
    if (!state.projects.length) { $("#projectDialog").showModal(); return; }
    selectProject("all");
    window.requestAnimationFrame(() => $('[data-work-project]')?.focus());
  };
  buttons[1].onclick = () => {
    if (!state.projects.length) { $("#projectDialog").showModal(); return; }
    if (!project) {
      if (state.projects.length === 1) selectProject(state.projects[0].id);
      else { selectProject("all"); toast("Choose a repository first."); return; }
    } else setView("work");
    window.requestAnimationFrame(() => $("#quickTaskPrompt")?.focus());
  };
  buttons[2].onclick = () => {
    if (!project) { toast("Choose a repository first."); return; }
    if (projectAttention.length) { setView("attention"); return; }
    if (projectRuns.length) { selectRun(projectRuns[0].id); return; }
    toast("Describe the first change before there is anything to follow.");
    window.requestAnimationFrame(() => $("#quickTaskPrompt")?.focus());
  };
}

function renderCurrentRepositoryHint() {
  const container = $("#currentRepositoryHint");
  const candidate = state.bootstrap?.current_repository;
  const registered = candidate?.path && state.projects.some((project) => project.path === candidate.path);
  const visible = state.projects.length > 0 && !activeProject() && candidate?.path && !registered;
  container.classList.toggle("hidden", !visible);
  if (!visible) { container.innerHTML = ""; return; }
  container.innerHTML = `<div><span class="inline-step"><b>1</b><span>CURRENT REPOSITORY</span></span><h2>Work on ${escapeHtml(projectName(candidate))}?</h2><p>${escapeHtml(projectRepository(candidate))}</p><small>${escapeHtml(candidate.path)}</small></div><button class="primary" id="addCurrentRepository" type="button">Use this repository</button>`;
  $("#addCurrentRepository").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    try {
      button.disabled = true; button.textContent = "Adding…";
      const registeredProject = await api("/api/projects", {method: "POST", body: JSON.stringify({path: candidate.path})});
      await refreshProjects();
      selectProject(registeredProject.id);
      toast(`${projectName(registeredProject)} is ready. Describe the first change.`);
    } catch (error) { toast(error.message, true); }
    finally { button.disabled = false; button.textContent = "Use this repository"; }
  });
}

function renderQuickStart() {
  const container = $("#quickStart");
  const project = activeProject();
  const mode = !state.projects.length ? "first-project" : project ? `task:${project.id}` : "hidden";
  if (container.dataset.mode === mode) return;
  container.dataset.mode = mode;
  if (mode === "hidden") {
    container.className = "quick-start hidden";
    container.innerHTML = "";
    return;
  }
  if (mode === "first-project") {
    const capabilities = state.bootstrap?.capabilities || {};
    const agentsReady = capabilities.codex || capabilities.claude;
    container.className = "quick-start first-run-card";
    container.innerHTML = `
      <div class="first-run-copy">
        <span class="inline-step"><b>1</b><span>CHOOSE A REPOSITORY</span></span>
        <h2>Add one repository.</h2>
        <p>Registration reads context only; your source checkout stays unchanged.</p>
        <form class="quick-project-form" id="quickProjectForm">
          <label for="quickProjectPath">Repository folder</label>
          <div><input id="quickProjectPath" name="path" required value="${escapeHtml(state.bootstrap?.current_repository?.path || "")}" placeholder="${escapeHtml(state.bootstrap?.working_directory || "/absolute/path/to/repository")}"><button class="primary" type="submit">Add repository</button></div>
        </form>
        <button class="text-button" id="copyDemoCommand" type="button">Copy demo command</button>
      </div>
      <div class="setup-checks" aria-label="Local setup status">
        <p>READY CHECK</p>
        <div class="done"><span>✓</span><div><strong>Odysseus is running</strong><small>Local service connected</small></div></div>
        <div class="${capabilities.git ? "done" : "missing"}"><span>${capabilities.git ? "✓" : "!"}</span><div><strong>${capabilities.git ? "Git is ready" : "Git is missing"}</strong><small>Branches and worktrees</small></div></div>
        <div class="${agentsReady ? "done" : "missing"}"><span>${agentsReady ? "✓" : "!"}</span><div><strong>${agentsReady ? "Agent CLI is ready" : "Install an agent CLI"}</strong><small>${capabilities.codex ? "Codex CLI detected" : capabilities.claude ? "Claude Code detected" : "Codex CLI or Claude Code is required"}</small></div></div>
      </div>`;
    $("#quickProjectForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = event.currentTarget.querySelector("button");
      const path = new FormData(event.currentTarget).get("path");
      try {
        button.disabled = true; button.textContent = "Adding…";
        const registered = await api("/api/projects", {method: "POST", body: JSON.stringify({path})});
        await refreshProjects();
        selectProject(registered.id);
        toast(`${projectName(registered)} is ready. Describe the first change.`);
      } catch (error) { toast(error.message, true); }
      finally { button.disabled = false; button.textContent = "Add repository"; }
    });
    $("#copyDemoCommand").addEventListener("click", () => copyCommand("odysseus demo"));
    return;
  }
  container.className = "quick-start quick-task-card";
  const laneOptions = state.bootstrap.lanes.map((lane) => `<option value="${escapeHtml(lane)}" ${lane === state.bootstrap.default_lane ? "selected" : ""}>${escapeHtml(lane)}</option>`).join("");
  container.innerHTML = `
    <form id="quickTaskForm">
      <div class="quick-task-heading"><div><span class="inline-step"><b>2</b><span>NEW TASK</span></span><h2>Describe the finished change.</h2></div><span class="safety-note">Source checkout untouched</span></div>
      <textarea name="task" id="quickTaskPrompt" required rows="3" placeholder="Example: Make installation errors short and actionable, and add a regression test."></textarea>
      <div class="quick-task-toolbar"><label><span>Agent</span><select name="lane" aria-label="Implementation agent">${laneOptions}</select></label><p><strong>${escapeHtml(state.bootstrap.max_parallel)} slots.</strong> Extra work waits. <button class="text-button" id="quickQueueSettings" type="button">Settings</button></p></div>
      <p class="task-submit-status hidden" id="quickTaskStatus" aria-live="polite"></p>
      <div class="quick-task-actions"><button class="primary" value="default" type="submit">Start task</button><button class="ghost" value="another" type="submit">Start &amp; add another</button><button class="text-button" id="quickPlanTask" type="button">Plan</button><button class="text-button" id="quickAdvancedTask" type="button">More options</button></div>
    </form>`;
  $("#quickTaskForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = event.submitter;
    const originalLabel = button.textContent;
    const data = new FormData(form);
    const task = String(data.get("task") || "").trim();
    const addAnother = button.value === "another";
    if (!task) return;
    const status = $("#quickTaskStatus");
    const lane = data.get("lane") || state.bootstrap.default_lane;
    try {
      form.elements.task.value = "";
      status.textContent = `Starting ${lane} on ${projectName(project)}...`;
      status.classList.remove("hidden");
      setFormSubmitting(form, true, button, "Starting...");
      const run = await api("/api/runs", {method: "POST", body: JSON.stringify({task, project_path: project.path, lane, skill_mode: "auto"})});
      status.textContent = addAnother ? "Task started. Add the next request." : "Task started. Opening the live task view...";
      toast(`Task started: ${runTitle(run)}`);
      await Promise.all([refreshRuns(), refreshProjects()]);
      if (addAnother) {
        window.requestAnimationFrame(() => $("#quickTaskPrompt")?.focus());
        window.setTimeout(() => status.classList.add("hidden"), 2200);
      }
      else await selectRun(run.id);
    } catch (error) {
      form.elements.task.value = task;
      status.classList.add("hidden");
      toast(error.message, true);
    }
    finally {
      setFormSubmitting(form, false, button, originalLabel);
      if (!addAnother && state.view === "tasks") status.classList.add("hidden");
    }
  });
  $("#quickQueueSettings").addEventListener("click", () => setView("settings"));
  $("#quickPlanTask").addEventListener("click", () => {
    const prompt = $("#quickTaskPrompt").value;
    prepareProjectSelect($("#epicProjectSelect"), $("#epicCustomProject"));
    $("#epicForm").elements.requirement.value = prompt;
    $("#epicDialog").showModal();
  });
  $("#quickAdvancedTask").addEventListener("click", () => {
    const prompt = $("#quickTaskPrompt").value;
    prepareProjectSelect($("#taskProjectSelect"), $("#taskCustomProject"));
    $("#taskPrompt").value = prompt;
    refreshTaskSkillChoices().catch((error) => toast(error.message, true));
    $("#taskDialog").showModal();
  });
}

function renderWork() {
  const project = activeProject();
  const runs = project ? runsForProject(project.id) : state.runs;
  const active = runs.filter((run) => activeStatuses.has(run.status)).length;
  const needs = project ? attentionForProject(project.id).length : state.attention.length;
  const complete = runs.filter((run) => ["accepted", "pr_created", "completed"].includes(run.status)).length;
  const terminals = project ? projectTerminalCount(project) : state.sessions.length;
  $("#workView").classList.toggle("repository-selected", !!project);
  $("#workBreadcrumb").textContent = project ? "GIT REPOSITORY" : "ODYSSEUS";
  $("#workTitle").textContent = project ? projectName(project) : (state.projects.length ? "Repositories" : "Welcome to Odysseus");
  $("#workDescription").textContent = project ? `${runs.length} task${runs.length === 1 ? "" : "s"} · ${needs ? `${needs} need you` : UI_COPY.noAction}.` : state.projects.length ? "Choose where the agent should work." : "Add one repository to start.";
  $("#workMeta").innerHTML = project ? `<span>${escapeHtml(projectRepository(project))}</span><span>Folder: ${escapeHtml(project.path)}</span><span>${escapeHtml(project.branch || "Git repository")}</span>${(project.tags || []).map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}` : "";
  $("#workMeta").classList.toggle("hidden", !project);
  $("#workSummary").innerHTML = [
    [project ? runs.length : state.projects.length, project ? "Tasks" : "Repositories", project ? "in this repository" : "registered repositories"],
    [active, "In progress", "running or waiting"],
    [needs, "Needs you", needs ? "decisions waiting" : "nothing waiting"],
    [project ? terminals : complete, project ? "Terminals" : "Completed", project ? "agent panes" : "accepted changes"],
  ].map(([value, label, note]) => `<div class="work-stat"><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong><span>${escapeHtml(note)}</span></div>`).join("");
  $("#workSummary").classList.toggle("hidden", !project);
  $("#journeyStepper").classList.toggle("hidden", !!project);
  renderJourney();
  renderCurrentRepositoryHint();
  renderQuickStart();
  renderProjectKnowledge();
  $("#workPlanButton").classList.toggle("hidden", !project);
  $("#workNewTaskButton").classList.toggle("hidden", !state.projects.length);
  $("#newTaskButton").classList.toggle("hidden", !state.projects.length);
  $("#workListEyebrow").textContent = project ? "TASKS" : "REPOSITORIES";
  $("#workListTitle").textContent = project ? "Recent work" : "Your repositories";
  $("#workListDescription").textContent = project ? "Latest tasks for this repository." : "Saved local checkouts.";
  const secondary = $("#workSecondaryAction");
  secondary.textContent = project ? "View plans" : "Add repository";
  secondary.onclick = () => project ? setView("epics") : $("#projectDialog").showModal();
  $("#workList").closest(".work-section").classList.toggle("hidden", !state.projects.length);
  if (!project) {
    $("#workList").innerHTML = state.projects.length ? state.projects.map((item) => {
      const itemRuns = runsForProject(item.id); const itemActive = itemRuns.filter((run) => activeStatuses.has(run.status)).length; const itemNeeds = attentionForProject(item.id).length;
      const checkoutNote = projectHasDuplicateCheckout(item) ? `Checkout · ${item.folder_name}` : item.path;
      return `<article class="project-overview-card"><button class="project-overview-main" data-work-project="${escapeHtml(item.id)}" type="button"><span class="project-glyph">${escapeHtml(projectName(item).slice(0, 1).toUpperCase())}</span><span class="project-overview-copy"><strong>${escapeHtml(projectName(item))}</strong><span class="repository-reference">${escapeHtml(projectRepository(item))}</span><small>${escapeHtml(checkoutNote)}</small></span></button><div class="project-overview-side"><div class="project-card-signals"><span>${itemRuns.length} tasks</span><span>${itemActive} active</span>${itemNeeds ? `<span class="needs">${itemNeeds} need you</span>` : ""}</div><button class="text-button danger-text" data-forget-project-inline="${escapeHtml(item.id)}" type="button">Remove</button></div></article>`;
    }).join("") : `<div class="empty-card"><strong>No repositories yet.</strong><br>Add one, then describe the first task.</div>`;
    $$('[data-work-project]').forEach((button) => button.addEventListener("click", () => selectProject(button.dataset.workProject)));
    $$('[data-forget-project-inline]').forEach((button) => button.addEventListener("click", () => forgetProject(button.dataset.forgetProjectInline)));
  } else {
    $("#workList").innerHTML = runs.length ? runs.map((run) => `<button class="work-task-row" data-work-run="${escapeHtml(run.id)}" type="button"><div><h3>${escapeHtml(run.title)}</h3><p>${escapeHtml(runActionLine(run))}</p></div><span>${relativeTime(run.updated_at)} ago</span><span class="mini-status ${statusClass(run.status)}">${escapeHtml(statusLabel(run.status))}</span></button>`).join("") : `<div class="empty-card"><strong>No tasks yet.</strong><br>Describe the first change above.</div>`;
    $$('[data-work-run]').forEach((button) => button.addEventListener("click", () => selectRun(button.dataset.workRun)));
  }
}

function renderRuns() {
  const runs = filteredRuns();
  $("#runCount").textContent = runs.length;
  $("#taskList").innerHTML = runs.length ? runs.map((run) => {
    const session = run.kind === "tmux" ? discoveredSessionForRun(run) : null;
    const title = session?.title || session?.window_name || run.title;
    const status = run.kind === "tmux" ? "tracked terminal" : statusLabel(run.status);
    const signals = run.kind === "tmux"
      ? `<span>tmux ${escapeHtml(session?.tmux_session || run.tmux_session || "session")} · ${escapeHtml(session?.tmux_target || run.tmux_target || "pane")}</span>`
      : `<span class="risk-${escapeHtml(run.merge_analysis?.risk || "none")}">${escapeHtml(run.merge_analysis?.risk || "none")} merge risk</span>${run.ci?.status && run.ci.status !== "not_started" ? `<span class="ci-${escapeHtml(run.ci.status)}">CI ${escapeHtml(run.ci.status)}</span>` : ""}`;
    return `<button class="task-card ${run.id === state.selectedId ? "selected" : ""}" data-run-id="${escapeHtml(run.id)}" type="button">
      <div class="task-card-top"><span class="mini-status ${statusClass(run.status)}">${escapeHtml(status)}</span><span class="run-id">${relativeTime(run.updated_at)}</span></div>
      <h3>${escapeHtml(title)}</h3>
      <div class="task-card-meta"><span>${escapeHtml(run.lane)}${run.kind === "tmux" ? "" : ` · P${escapeHtml(run.priority ?? 50)}`}</span><span>${escapeHtml(projectById(run.project_id) ? projectName(projectById(run.project_id)) : run.kind || run.workflow)}</span></div>
      <div class="task-signals">${signals}</div>
    </button>`;
  }).join("") : `<div class="empty-list">No tasks in this view.</div>`;
  $$(".task-card[data-run-id]").forEach((button) => button.addEventListener("click", () => selectRun(button.dataset.runId)));
  renderProjectTree();
}

async function refreshRuns() {
  const data = await api("/api/runs?summary=1");
  state.runs = data.runs;
  renderRuns();
  renderWork();
  if (!state.selectedId && state.runs.length && state.view === "tasks") await selectRun(state.runs[0].id);
  if (state.selectedId) {
    const current = state.runs.find((run) => run.id === state.selectedId);
    if (current && (!state.selected || current.updated_at !== state.selected.updated_at)) await refreshSelected();
  }
}

function resetHeavyTaskState() {
  state.selectedDiff = null;
  state.selectedDiffRunId = "";
  state.selectedDiffLoadingRunId = "";
  state.decisionDiff = null;
  state.decisionDiffRunId = "";
  state.events = [];
  state.eventsLoadedRunId = "";
  state.eventsLoadingRunId = "";
  state.eventVisibleLimit = 150;
}

async function selectRun(runId) {
  const target = state.runs.find((run) => run.id === runId);
  if (target?.project_id) state.projectFilter = target.project_id;
  const generation = state.selectionGeneration + 1;
  state.selectionGeneration = generation;
  closeStream();
  state.selectedId = runId;
  state.selected = null;
  state.taskSection = "summary";
  resetHeavyTaskState();
  location.hash = `task/${encodeURIComponent(runId)}`;
  setView("tasks");
  renderRuns();
  $("#emptyState").classList.add("hidden");
  $("#runDetail").classList.remove("hidden");
  $("#runDetail").setAttribute("aria-busy", "true");
  $("#detailStatus").textContent = "opening task";
  $("#detailStatus").className = "status-pill status-queued";
  $("#detailTitle").textContent = target?.title || "Opening task…";
  $("#detailTask").textContent = "Loading the task summary. Changes, activity, and evidence load only when you open them.";
  try {
    await refreshSelected(false, runId, generation);
    if (state.selectedId !== runId || state.selectionGeneration !== generation) return;
    activateTaskSection("summary");
    openStream(runId);
  } catch (error) {
    if (state.selectedId === runId && state.selectionGeneration === generation) {
      $("#runDetail").removeAttribute("aria-busy");
      toast(error.message, true);
    }
  }
}

async function refreshSelected(loadEvents = false, requestedId = state.selectedId, generation = state.selectionGeneration) {
  if (!requestedId) return;
  const run = await api(`/api/runs/${encodeURIComponent(requestedId)}`);
  if (state.selectedId !== requestedId || state.selectionGeneration !== generation) return;
  state.selected = run;
  renderDetail(run);
  if (loadEvents) await loadEvents(requestedId, generation);
  updateGitHubLink();
}

function activeInspectorTab(section) {
  return $(`#task-section-${section} .tab.active`)?.dataset.tab || "";
}

async function loadEvents(runId = state.selectedId, generation = state.selectionGeneration) {
  if (!runId || state.eventsLoadedRunId === runId || state.eventsLoadingRunId === runId) return;
  state.eventsLoadingRunId = runId;
  renderEvents();
  try {
    const loaded = (await api(`/api/runs/${encodeURIComponent(runId)}/events`)).events || [];
    if (state.selectedId !== runId || state.selectionGeneration !== generation) return;
    const bySequence = new Map([...loaded, ...state.events].map((event) => [event.seq, event]));
    state.events = [...bySequence.values()].sort((left, right) => Number(left.seq || 0) - Number(right.seq || 0));
    state.eventsLoadedRunId = runId;
  } finally {
    if (state.eventsLoadingRunId === runId) state.eventsLoadingRunId = "";
  }
  if (state.selectedId === runId && state.taskSection === "activity") renderEvents();
}

async function renderVisibleHeavyPanels() {
  if (!state.selected) return;
  if (state.taskSection === "changes") {
    const tab = activeInspectorTab("changes");
    if (tab === "diff") await renderDiff();
    if (tab === "integration") renderIntegration(state.selected);
  }
  if (state.taskSection === "activity") {
    await loadEvents();
    renderEvents();
  }
  if (state.taskSection === "evidence") {
    const tab = activeInspectorTab("evidence");
    if (tab === "checks") renderChecks(state.selected.check_results || []);
    if (tab === "context") renderContextReceipt(state.selected);
    if (tab === "review") $("#reviewSummary").textContent = truncateText(state.selected.review_summary || state.selected.last_error || "Review has not run yet.");
    if (tab === "evaluation") renderEvaluation(state.selected.evaluation || {});
    if (tab === "ci") renderCI(state.selected);
  }
}

function renderDetail(run) {
  $("#emptyState").classList.add("hidden");
  $("#runDetail").classList.remove("hidden");
  $("#runDetail").removeAttribute("aria-busy");
  const interactive = run.kind === "tmux";
  $(".journey-context").classList.toggle("hidden", interactive);
  const discovered = interactive ? discoveredSessionForRun(run) : null;
  const status = $("#detailStatus");
  const delivered = run.delivery?.status;
  const visibleStatus = run.status === "review" ? "ready for review"
    : run.status === "accepted" && delivered === "applied" ? "applied"
    : run.status === "accepted" && deliveredDeliveryStatuses.has(delivered) && delivered !== "applied" ? "delivered by integration"
    : run.status === "accepted" ? "accepted · not applied"
    : statusLabel(run.status);
  status.textContent = interactive ? "tracked tmux terminal" : visibleStatus; status.className = `status-pill ${statusClass(run.status)}`;
  $("#detailId").textContent = run.id;
  const project = projectById(run.project_id);
  $("#detailProjectName").textContent = projectName(project);
  $("#titleProject").textContent = projectName(project);
  $("#titleSurface").textContent = run.title;
  $("#detailTitle").textContent = discovered?.title || discovered?.window_name || run.title;
  $("#detailTask").textContent = interactive ? `Existing ${run.lane} session in tmux ${discovered?.tmux_session || run.tmux_session || "—"}${(discovered?.tmux_target || run.tmux_target) ? `, pane ${discovered?.tmux_target || run.tmux_target}` : ""}.` : run.task;
  $("#observedSession").classList.toggle("hidden", !interactive);
  const decisionVisible = !interactive && ["review", "accepted", "pr_created"].includes(run.status);
  $("#assistantPanel").classList.toggle("hidden", interactive);
  $("#summaryAssistant").classList.toggle("hidden", interactive || !canAssistantFollowUp(run));
  renderAssistantPanel(run);
  renderRecoveryCard(run);
  $("#runNarrative").classList.toggle("hidden", interactive || decisionVisible);
  $("#metrics").classList.toggle("hidden", interactive);
  $("#detailGrid").classList.toggle("hidden", interactive);
  const metrics = run.metrics || {};
  $("#metrics").innerHTML = [
    ["Tokens", compactNumber(Number(metrics.input_tokens || 0) + Number(metrics.output_tokens || 0))],
    ["Cost", metrics.cost_observed ? `$${Number(metrics.cost_usd || 0).toFixed(4)}` : UI_COPY.unknown],
    ["Confidence", run.confidence === null || run.confidence === undefined ? UI_COPY.unknown : `${Math.round(Number(run.confidence) * 100)}%`],
    ["GitHub CI", run.ci?.status || "not started"],
  ].map(([label, value]) => `<div class="metric"><small>${label}</small><strong>${escapeHtml(value)}</strong></div>`).join("");
  renderEnvironment(run);
  const metadata = interactive ? [
    ["Run ID", run.id], ["Agent", run.lane], ["Repository", projectById(run.project_id) ? projectName(projectById(run.project_id)) : run.project_path],
    ["tmux location", `${discovered?.tmux_session || run.tmux_session || "—"} · ${discovered?.tmux_target || run.tmux_target || "—"}`],
    ["Live pane state", discovered?.status || "not currently visible"], ["Tracking", "durable shortcut"], ["Control", "original terminal"],
  ] : [
    ["Run ID", run.id], ["Agent", run.lane], ["Environment", run.environment?.profile || "host"], ["Workflow", run.workflow], ["Repository", projectById(run.project_id) ? projectName(projectById(run.project_id)) : run.project_path],
    ["Branch", run.branch || "waiting"], ["Worktree", run.worktree_path || run.project_path],
    ["Agent session", run.agent_sessions?.agent || run.agent_session_id || "—"], ["tmux", run.tmux_target ? `${run.tmux_session} · ${run.tmux_target}` : run.tmux_session || "—"],
    ["Attempt", `${run.attempt || 0} / ${(run.max_retries || 0) + 1}`], ["Role", run.role || "implementer"],
    ["Plan", run.epic_id || "—"], ["Depends on", (run.dependency_keys || []).join(", ") || "—"],
    ["Skills", (run.skills_selected || []).map((skill) => skill.name || skill).join(", ") || "none"],
    ["Artifact", run.artifact_sha ? run.artifact_sha.slice(0, 12) : "—"], ["Priority", `P${run.priority ?? 50}`],
    ["Tool calls", compactNumber(metrics.tool_calls)], ["Cached tokens", compactNumber(metrics.cached_input_tokens)], ["Merge risk", run.merge_analysis?.risk || "none"],
    ["Stage", run.stage || statusLabel(run.status)], ["Heartbeat", run.last_heartbeat ? `${relativeTime(run.last_heartbeat)} ago` : "—"],
  ];
  $("#metadata").innerHTML = metadata.map(([label, value]) => `<div class="meta"><small>${escapeHtml(label)}</small><strong title="${escapeHtml(value)}">${escapeHtml(value)}</strong></div>`).join("");
  const technical = $("#technicalDetails");
  if (technical.dataset.runId !== run.id) { technical.dataset.runId = run.id; technical.open = interactive; }
  const changedRun = $("#runDetail").dataset.runId !== run.id;
  if (changedRun) { $("#runDetail").dataset.runId = run.id; activateTaskSection("summary"); }
  $("#workflowStrip").classList.toggle("hidden", interactive);
  renderActions(run); renderReviewDecision(run); renderNarrative(run); renderRecoveryCard(run); renderWorkflow(run);
  loadDecisionDiff(run);
  if (changedRun) {
    $("#diffStat").textContent = "Open Changes to load the diff.";
    $("#diffPatch").textContent = "Large diffs are loaded only when this tab is visible.";
    $("#eventLog").innerHTML = `<div class="event"><time>—</time><span class="event-type">on demand</span><span class="event-message">Open Activity to load the event history.</span></div>`;
    $("#integrationResults").innerHTML = `<div class="empty-card">Open Integration to inspect predecessor artifacts.</div>`;
    $("#checkResults").innerHTML = `<div class="empty-card">Open Evidence to inspect checks.</div>`;
    $("#contextReceipt").innerHTML = `<div class="empty-card">Open Context to inspect attached snapshots.</div>`;
    $("#reviewSummary").textContent = "Open Review to inspect reviewer output.";
    $("#evaluationResults").innerHTML = `<div class="empty-card">Open Evaluation to inspect confidence signals.</div>`;
    $("#ciResults").innerHTML = `<div class="empty-card">Open CI to inspect GitHub checks.</div>`;
  }
  renderVisibleHeavyPanels().catch((error) => toast(error.message, true));
}

function renderEnvironment(run) {
  const node = $("#environmentCard");
  const environment = run.environment || {};
  if (run.kind === "tmux") { node.classList.add("hidden"); return; }
  node.classList.remove("hidden");
  const profile = environment.profile || "host";
  const profileLabel = profile === "project-default" ? "Repository default" : profile;
  const isolated = profile === "docker";
  const ports = Object.entries(environment.ports || {});
  const details = [
    environment.image ? `image ${environment.image}` : "",
    environment.network ? `network ${environment.network}` : "",
    environment.cpus ? `${environment.cpus} CPU` : "",
    environment.memory ? `${environment.memory} memory` : "",
    (environment.credential_env_names || []).length ? `${environment.credential_env_names.length} scoped credential env` : "",
  ].filter(Boolean);
  node.innerHTML = `<div class="environment-card-head"><div><small>EXECUTION ENVIRONMENT</small><strong>${escapeHtml(profileLabel)}</strong></div><span class="environment-state ${isolated ? "isolated" : ""}">${escapeHtml(environment.status || "pending")}</span></div>
    <p>${escapeHtml(environment.isolation || "Environment will be resolved when the task starts.")}</p>
    ${details.length ? `<div class="environment-tags">${details.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>` : ""}
    ${ports.length ? `<div class="environment-ports">${ports.map(([name, value]) => `<span><strong>${escapeHtml(name)}</strong> ${profile === "docker" ? `127.0.0.1:${escapeHtml(value.host)} → ${escapeHtml(value.container)}` : `127.0.0.1:${escapeHtml(value.host)} allocated`}</span>`).join("")}</div>` : ""}
    ${previewLinks(environment.preview_url)}
    ${profile === "host" ? `<div class="environment-warning">Host mode is compatible, but it can access the same files, credentials, ports, and services as your user.</div>` : ""}`;
}

function renderNarrative(run) {
  const ciStatus = run.ci?.status;
  const values = {
    queued: ["WAITING", "Waiting for a slot", "Starts when capacity opens.", UI_COPY.noAction, "calm", "→"],
    blocked: ["BLOCKED", blockedPrerequisite(run), "Prerequisite must be accepted first.", "Review prerequisite", "warn", "⊘"],
    starting: ["STARTING", "Creating worktree", "Source checkout stays unchanged.", UI_COPY.noAction, "active", "01"],
    running: ["RUNNING", "Agent is working", "Progress appears in Activity.", UI_COPY.noAction, "active", "02"],
    checking: ["CHECKING", "Running checks", "Results appear in Evidence.", UI_COPY.noAction, "active", "03"],
    reviewing: ["REVIEWING", "Independent review", "Decision comes next.", UI_COPY.noAction, "active", "04"],
    review: ["REVIEW", "Ready for your decision", "Nothing has been applied.", UI_COPY.review, "attention", "!"],
    attention: ["NEEDS YOU", "One decision required", "Answer to continue this task.", UI_COPY.needsYou, "attention", "?"],
    failed: ["FAILED", "Stopped safely", "Resume or take over from the preserved worktree.", UI_COPY.needsYou, "danger", "×"],
    accepted: ["ACCEPTED", UI_COPY.notApplied, "Apply locally, create a PR, or keep the artifact.", UI_COPY.deliver, "attention", "✓"],
    publishing: ["PUBLISHING", "Creating draft PR", "Task branch is being pushed.", UI_COPY.noAction, "active", "↗"],
    pr_created: ["PR CREATED", ciStatus === "failed" ? "CI failed" : ciStatus === "passed" ? "CI passed" : "CI pending", ciStatus === "failed" ? "Failure logs are captured." : "GitHub checks are tracked here.", ciStatus === "failed" ? "Repair in progress" : ciStatus === "passed" ? "Complete" : UI_COPY.noAction, ciStatus === "failed" ? "danger" : ciStatus === "passed" ? "success" : "active", ciStatus === "passed" ? "✓" : "↻"],
  };
  const environmentApproval = run.status === "attention" && run.environment?.trust_status === "pending";
  let narrative = environmentApproval ? ["TRUST GATE", "Approve repository commands", "No repository command has run.", UI_COPY.needsYou, "attention", "!"] : values[run.status] || ["WORKFLOW", "Tracking task", "Open Activity for events.", UI_COPY.noAction, "calm", "→"];
  if (run.status === "accepted" && ["applied", "integrated_applied"].includes(run.delivery?.status)) narrative = ["APPLIED", `Applied to ${run.delivery.target_branch || run.base_ref}`, `HEAD ${String(run.delivery.target_after_sha || "").slice(0, 12) || UI_COPY.unknown}. Artifact remains auditable.`, run.delivery?.status === "integrated_applied" ? "Delivered by integration" : "Delivered locally", "success", "✓"];
  if (run.status === "accepted" && run.delivery?.status === "failed") narrative = ["APPLY BLOCKED", "Artifact saved; delivery failed", run.delivery.error || "Resolve repository state, then retry.", UI_COPY.needsYou, "danger", "!"];
  if (run.status === "accepted" && run.delivery?.status === "integration_queued") narrative = ["INTEGRATION QUEUED", "Artifact selected for integration", `Run ${run.delivery.integration_run_id || UI_COPY.unknown} will compose delivery.`, "Integration queued", "attention", "→"];
  const [label, title, copy, tail, tone, mark] = narrative;
  $("#narrativeLabel").textContent = label; $("#narrativeTitle").textContent = title; $("#narrativeCopy").textContent = copy; $("#narrativeTail").textContent = tail; $("#narrativeMark").textContent = mark; $("#runNarrative").dataset.tone = tone;
}

function renderActions(run) {
  const actions = [];
  if (run.status === "queued") actions.push(`<button class="action-button" data-action="settings" type="button">Queue settings</button>`);
  if (["accepted", "pr_created"].includes(run.status)) actions.push(`<button class="action-button" data-action="resume" type="button">Follow up</button>`);
  if ((run.tmux_session || run.agent_sessions?.agent || run.agent_session_id) && !canInlineResume(run)) actions.push(`<button class="action-button" data-action="takeover" type="button" title="Copies a command that opens this agent in your terminal">${run.kind === "tmux" ? "Copy tmux command" : "Continue in terminal"}</button>`);
  if (activeStatuses.has(run.status) && run.status !== "cancelling") actions.push(`<button class="action-button warn" data-action="cancel" type="button">Cancel</button>`);
  if (run.pull_request_url) actions.push(`<a class="action-button accept" href="${escapeHtml(run.pull_request_url)}" target="_blank" rel="noreferrer">Open PR</a>`);
  if (run.pull_request_url) actions.push(`<button class="action-button" data-action="ci-poll" type="button">Poll CI</button>`);
  $("#runActions").innerHTML = actions.join("");
  $$("#runActions [data-action]").forEach((button) => button.addEventListener("click", () => runAction(button.dataset.action)));
}

function parseDiffStat(stat) {
  const text = String(stat || "");
  const summary = text.split("\n").find((line) => /\d+\s+files? changed/.test(line)) || "";
  const files = Number((summary.match(/(\d+)\s+files? changed/) || [])[1] || 0);
  const insertions = Number((summary.match(/(\d+)\s+insertions?\(\+\)/) || [])[1] || 0);
  const deletions = Number((summary.match(/(\d+)\s+deletions?\(-\)/) || [])[1] || 0);
  return {files, insertions, deletions, observed: Boolean(summary)};
}

function highRiskPaths(paths) {
  const patterns = [/auth/i, /security/i, /migrations?\//i, /schema/i, /payment/i, /billing/i, /permissions?/i, /secrets?/i, /infra/i, /deploy/i, /Dockerfile/i, /package-lock\.json/i, /requirements/i];
  return (paths || []).filter((path) => patterns.some((pattern) => pattern.test(String(path)))).slice(0, 5);
}

function findingsBySeverity(run) {
  const findings = run.evaluation?.findings || [];
  const grouped = {critical: 0, high: 0, medium: 0, low: 0};
  for (const finding of findings) {
    const severity = String(finding.severity || finding.priority || "medium").toLowerCase();
    if (Object.prototype.hasOwnProperty.call(grouped, severity)) grouped[severity] += 1;
    else grouped.medium += 1;
  }
  return grouped;
}

function phaseUsage(run) {
  const usage = run.metrics?.session_usage || {};
  const parts = ["agent", "review", "retry"].map((phase) => {
    const item = usage[phase] || usage[phase === "agent" ? "implementation" : phase] || {};
    const tokens = Number(item.input_tokens || 0) + Number(item.output_tokens || 0);
    return `${phase}: ${tokens ? compactNumber(tokens) : "Not observed"}`;
  });
  return parts.join(" · ");
}

function decisionEvidence(run) {
  const checks = run.check_results || [];
  const passed = checks.filter((item) => Number(item.returncode) === 0 || item.skipped).length;
  const failed = checks.filter((item) => Number(item.returncode) !== 0 && !item.skipped);
  const ci = run.ci || {};
  const ciFailures = (ci.checks || []).filter((item) => ["fail", "failed", "failure"].includes(String(item.bucket || item.state || "").toLowerCase()));
  const files = run.artifact_files || run.merge_analysis?.files || [];
  const stat = state.decisionDiffRunId === run.id ? parseDiffStat(state.decisionDiff?.stat || "") : {observed: false};
  const riskPaths = highRiskPaths(files);
  const findings = findingsBySeverity(run);
  const unresolved = Object.entries(findings).filter(([, count]) => count).map(([severity, count]) => `${count} ${severity}`).join(", ");
  const verdict = run.evaluation?.decision || run.evaluation?.verdict || run.policy_decision || "";
  const ciObserved = ci.status && ci.status !== "not_started";
  const cost = run.metrics?.cost_observed
    ? `$${Number(run.metrics.cost_usd || 0).toFixed(4)}`
    : UI_COPY.unknown;
  const confidence = run.confidence === null || run.confidence === undefined ? UI_COPY.unknown : `${Math.round(Number(run.confidence) * 100)}%`;
  const title = (run.status === "review" && (!ciObserved || !["passed", "success"].includes(String(ci.status).toLowerCase())))
    ? "Ready for your decision"
    : run.status === "review" ? "Ready for your decision" : "Delivery decision";
  return {checks, passed, failed, ci, ciFailures, files, stat, riskPaths, unresolved, verdict, ciObserved, cost, confidence, title};
}

function renderDecisionSummary(run) {
  const evidence = decisionEvidence(run);
  const diffValue = evidence.stat.observed
    ? `+${compactNumber(evidence.stat.insertions)} / -${compactNumber(evidence.stat.deletions)}`
    : "Unknown";
  const fileValue = evidence.stat.observed && evidence.stat.files ? evidence.stat.files : (evidence.files.length || "Unknown");
  const riskValue = evidence.riskPaths.length ? evidence.riskPaths.join(", ") : UI_COPY.notObserved;
  const ciValue = evidence.ciObserved ? statusLabel(evidence.ci.status) : UI_COPY.notObserved;
  return `
    <section class="decision-summary" aria-label="Evidence summary for acceptance">
      <div><small>Checks</small><strong>${escapeHtml(evidence.passed)} / ${escapeHtml(evidence.checks.length)} passed</strong></div>
      <div><small>Failures</small><strong>${escapeHtml(evidence.failed.length + evidence.ciFailures.length)}</strong></div>
      <div><small>Diff</small><strong>${escapeHtml(diffValue)}</strong></div>
      <div><small>Files</small><strong>${escapeHtml(fileValue)}</strong></div>
      <div><small>Review</small><strong>${escapeHtml(evidence.verdict || UI_COPY.unknown)}</strong></div>
      <div><small>GitHub CI</small><strong>${escapeHtml(ciValue)}</strong></div>
      <div><small>Confidence</small><strong>${escapeHtml(evidence.confidence)}</strong></div>
      <div><small>Cost</small><strong>${escapeHtml(evidence.cost)}</strong></div>
    </section>
    <details class="decision-detail"><summary>More evidence</summary><pre>${escapeHtml([
      `Checks: ${evidence.passed}/${evidence.checks.length}`,
      `Failed checks: ${evidence.failed.map((item) => item.command || "check").join(", ") || "none observed"}`,
      `CI failures: ${evidence.ciFailures.map((item) => item.name || item.workflow || "check").join(", ") || "none observed"}`,
      `High-risk paths: ${riskValue}`,
      `Token usage by phase: ${phaseUsage(run)}`,
      `Unresolved findings: ${evidence.unresolved || UI_COPY.notObserved}`,
      `Changed files: ${evidence.files.join(", ") || "Unknown"}`,
      `Review summary: ${run.review_summary || "Not observed"}`,
    ].join("\n"))}</pre></details>`;
}

async function loadDecisionDiff(run) {
  if (!run?.id || !["review", "accepted", "pr_created"].includes(run.status)) return;
  if (state.decisionDiffRunId === run.id) return;
  try {
    state.decisionDiff = await api(`/api/runs/${encodeURIComponent(run.id)}/diff`);
    state.decisionDiffRunId = run.id;
    if (state.selectedId === run.id) renderReviewDecision(state.selected);
  } catch {
    state.decisionDiff = {stat: "", patch: ""};
    state.decisionDiffRunId = run.id;
  }
}

function renderReviewDecision(run) {
  const node = $("#reviewDecisionCard");
  const visible = ["review", "accepted", "pr_created", "decided"].includes(run.status);
  node.classList.toggle("hidden", !visible);
  if (!visible) { node.innerHTML = ""; return; }
  if (run.workflow === "variants") {
    renderVariantDecision(run, node);
    return;
  }
  const project = projectById(run.project_id);
  const delivery = run.delivery || {};
  const applied = ["applied", "integrated_applied"].includes(delivery.status);
  const integratedPr = delivery.status === "integrated_pr_created";
  const delivered = deliveredDeliveryStatuses.has(delivery.status);
  const failed = delivery.status === "failed";
  const previewUrl = run.environment?.preview_url || "";
  let deliveryCopy = "Accepting saves a durable artifact. It does not change your source checkout.";
  let deliveryActions = `<button class="primary" data-review-action="accept" type="button">Accept result</button>`;
  let alternateActions = `<button class="ghost" data-review-action="draft-pr" type="button">Create draft PR</button>`;
  let deliveryHelp = "";
  if (run.status === "accepted" && !delivered) {
    deliveryCopy = failed ? `Apply is blocked: ${delivery.error || "inspect the repository state and try again."}` : `Accepted, but not applied to ${run.base_ref || "the source branch"}. You may also keep it as an artifact and do nothing.`;
    const conflict = /conflict|merge was aborted/i.test(delivery.error || "");
    deliveryActions = conflict
      ? `<button class="primary" data-review-action="resolve-conflict" type="button">Ask integration agent</button>`
      : `<button class="primary" data-review-action="apply" type="button">${failed ? "Try apply again" : "Apply to repository"}</button>`;
    alternateActions = `<button class="ghost" data-review-action="integration" type="button">Prepare integration</button><button class="ghost" data-review-action="draft-pr" type="button">Create draft PR</button>`;
    if (failed) {
      const tracked = /tracked local changes/i.test(delivery.error || "");
      const explanation = tracked
        ? "Prerequisite: clean source checkout."
        : conflict
          ? "Prerequisite: resolve source/artifact conflict."
          : "Prerequisite: compatible source repository state.";
      deliveryHelp = `<div class="delivery-help"><strong>${escapeHtml(explanation)}</strong><div class="delivery-help-actions"><button class="ghost" data-review-action="copy-source-status" type="button">Copy status command</button>${tracked ? `<button class="ghost" data-review-action="copy-source-stash" type="button">Copy safe stash command</button>` : ""}</div></div>`;
    }
  }
  if (run.status === "accepted" && delivery.status === "integration_queued") {
    deliveryCopy = `Queued for integration${delivery.integration_run_id ? ` as ${delivery.integration_run_id}` : ""}.`;
    deliveryActions = `<span class="delivery-complete">Integration queued</span>`;
    alternateActions = "";
    deliveryHelp = "";
  }
  if (applied) {
    deliveryCopy = `${delivery.status === "integrated_applied" ? "Integrated and applied" : "Applied"} to ${delivery.target_branch || run.base_ref} at ${String(delivery.target_after_sha || "").slice(0, 12)}.`;
    deliveryActions = `<span class="delivery-complete">✓ ${delivery.status === "integrated_applied" ? "Delivered by integration" : "Applied to repository"}</span>`;
    alternateActions = "";
  }
  if (integratedPr) {
    deliveryCopy = `Delivered by integration PR${delivery.integration_run_id ? ` from ${delivery.integration_run_id}` : ""}.`;
    deliveryActions = delivery.url
      ? `<a class="primary button-link" href="${escapeHtml(delivery.url)}" target="_blank" rel="noreferrer">Open integration PR</a>`
      : `<span class="delivery-complete">✓ Delivered in integration PR</span>`;
    alternateActions = "";
  }
  if (run.status === "pr_created") {
    deliveryCopy = "A draft pull request contains this change. GitHub CI is tracked separately.";
    deliveryActions = run.pull_request_url ? `<a class="primary button-link" href="${escapeHtml(run.pull_request_url)}" target="_blank" rel="noreferrer">Open pull request</a>` : `<span class="delivery-complete">✓ Draft PR created</span>`;
    alternateActions = "";
  }
  const evidence = decisionEvidence(run);
  node.innerHTML = `
    <header class="review-decision-head"><div><small>${run.status === "review" ? "DECISION" : delivered ? "DELIVERED" : run.status === "pr_created" ? "PULL REQUEST" : "DELIVERY"}</small><strong>${escapeHtml(run.status === "review" ? "Review result" : integratedPr ? "Delivered in integration PR" : applied ? "Source updated" : run.status === "pr_created" ? "PR opened" : UI_COPY.notApplied)}</strong></div><span>${escapeHtml(runActionLine(run))}</span></header>
    ${renderDecisionSummary(run)}
    <section class="delivery-decision"><div><strong>${escapeHtml(deliveryCopy)}</strong>${deliveryHelp}</div><div class="delivery-actions">${deliveryActions}</div></section>
    <details class="review-secondary"><summary>Inspect or choose another action</summary><div class="secondary-action-grid"><button class="ghost" data-review-action="view-changes" type="button">View changes</button>${previewUrl ? previewLinks(previewUrl) : `<button class="ghost" data-review-action="view-evidence" type="button">View evidence</button>`}${alternateActions}</div></details>
    ${run.status === "review" ? `<details class="review-request"><summary>Request changes</summary><textarea id="reviewFeedback" rows="4" placeholder="What should the agent change before you accept this result?"></textarea><div><button class="primary" data-review-action="send-back" type="button">Send changes</button>${canTakeover(run) ? `<button class="ghost" data-review-action="takeover" type="button">Continue in terminal</button>` : ""}</div></details>` : ""}
    <footer class="delivery-target">Repository: <strong>${escapeHtml(projectName(project))}</strong> · Local branch: <code>${escapeHtml(run.base_ref || "unknown")}</code></footer>`;
  $$('[data-review-action]').forEach((button) => button.addEventListener("click", () => reviewAction(button.dataset.reviewAction, button)));
}

function renderVariantDecision(run, node) {
  const project = projectById(run.project_id);
  const comparison = run.variant_comparison || {};
  const candidates = comparison.candidates || [];
  const frontier = new Set(comparison.pareto_frontier || []);
  const decided = run.variant_decision || {};
  const rows = candidates.map((item) => {
    const tests = item.tests || {};
    const quality = item.code_quality || {};
    const cost = item.observed_cost || {};
    const size = item.unnecessary_change_size || {};
    const attention = item.human_attention || {};
    const artifact = item.artifact || {};
    const frontierMark = frontier.has(item.run_id) ? `<span class="variant-frontier">Frontier</span>` : "";
    return `<article class="variant-candidate">
      <header><div><strong>${escapeHtml(item.title || item.run_id)}</strong><small>${escapeHtml(item.run_id)} · ${escapeHtml(item.lane || "")}</small></div>${frontierMark}</header>
      <div class="variant-metrics">
        <span><small>Tests</small><strong>${escapeHtml(tests.passed || 0)}/${escapeHtml(tests.total || 0)}</strong></span>
        <span><small>Quality</small><strong>${escapeHtml(Math.round(Number(quality.confidence || 0) * 100))}%</strong></span>
        <span><small>Risk</small><strong>${escapeHtml((item.regression_merge_risk || {}).risk || "unknown")}</strong></span>
        <span><small>Cost</small><strong>$${escapeHtml(Number(cost.usd || 0).toFixed(2))}</strong></span>
        <span><small>Size</small><strong>${escapeHtml(size.files || 0)} files</strong></span>
        <span><small>Needs</small><strong>${escapeHtml(attention.count || 0)}</strong></span>
      </div>
      <footer><span>${escapeHtml(artifact.sha ? artifact.sha.slice(0, 12) : "no artifact")}</span>${run.status === "review" && artifact.sha ? `<button class="ghost compact" data-review-action="variant-select" data-candidate-id="${escapeHtml(item.run_id)}" type="button">Select</button>` : ""}</footer>
    </article>`;
  }).join("");
  const canCombine = run.status === "review" && (comparison.pareto_frontier || []).length >= 2;
  const decisionCopy = decided.decision
    ? `Decision recorded: ${decided.decision.replaceAll("_", " ")}${decided.integration_run_id ? ` · integration ${decided.integration_run_id}` : ""}.`
    : "Choose a candidate, queue a separate integration task, or reject all.";
  node.innerHTML = `
    <header class="review-decision-head"><div><small>VARIANTS</small><strong>Comparison ready</strong></div><span>${escapeHtml(runActionLine(run))}</span></header>
    <section class="variant-summary"><strong>${escapeHtml(decisionCopy)}</strong><p>${escapeHtml(comparison.summary || "Candidates are preserved for operator review.")}</p></section>
    <div class="variant-candidate-list">${rows || `<div class="empty-card">No variant candidates recorded.</div>`}</div>
    <section class="delivery-decision"><div><strong>Artifacts are preserved; nothing has been applied or merged.</strong></div><div class="delivery-actions">${canCombine ? `<button class="primary" data-review-action="variant-combine" type="button">Combine frontier</button>` : ""}${run.status === "review" ? `<button class="ghost" data-review-action="variant-reject" type="button">Reject all</button>` : ""}</div></section>
    <footer class="delivery-target">Repository: <strong>${escapeHtml(projectName(project))}</strong> · Local branch: <code>${escapeHtml(run.base_ref || "unknown")}</code></footer>`;
  $$('[data-review-action]').forEach((button) => button.addEventListener("click", () => reviewAction(button.dataset.reviewAction, button)));
}

async function reviewAction(action, button) {
  if (action === "view-changes") { activateTaskSection("changes"); return; }
  if (action === "view-evidence") { activateTaskSection("evidence"); activateTab("checks"); return; }
  if (action === "resolve-conflict") {
    const project = projectById(state.selected?.project_id);
    const form = $("#feedbackForm");
    form.elements.feedback.value = `Integrate this accepted task with the current ${state.selected?.base_ref || "source branch"}. Resolve the apply conflicts without discarding either the accepted behavior or newer source changes, then rerun the relevant checks.`;
    form.elements.strategy.value = "resume";
    $("#feedbackDialog").showModal();
    toast(`The integration request is ready${project ? ` for ${projectName(project)}` : ""}. Review it, then submit.`);
    return;
  }
  if (action === "copy-source-status" || action === "copy-source-stash") {
    const project = projectById(state.selected?.project_id);
    if (!project?.path) { toast("The source repository path is unavailable.", true); return; }
    const root = shellQuote(project.path);
    const command = action === "copy-source-status"
      ? `git -C ${root} status --short`
      : `git -C ${root} stash push --include-untracked -m 'Before Odysseus apply'`;
    await copyCommand(command);
    return;
  }
  if (action === "send-back") {
    const prompt = $("#reviewFeedback")?.value.trim() || "";
    if (!prompt) { toast("Describe what the agent should change.", true); return; }
    await submitReviewFeedback(prompt, button);
    return;
  }
  if (action === "integration") {
    await openIntegrationDialog(button);
    return;
  }
  if (action === "variant-select") {
    await submitVariantDecision("select", [button.dataset.candidateId], button);
    return;
  }
  if (action === "variant-combine") {
    await submitVariantDecision("combine", state.selected?.variant_comparison?.pareto_frontier || [], button);
    return;
  }
  if (action === "variant-reject") {
    await submitVariantDecision("reject_all", [], button);
    return;
  }
  await runAction(action);
}

async function submitVariantDecision(decision, selectedRunIds, button) {
  if (!state.selectedId) return;
  const originalLabel = button?.textContent;
  try {
    if (button) { button.disabled = true; button.textContent = "Saving..."; }
    const result = await api(`/api/runs/${encodeURIComponent(state.selectedId)}/variants`, {method: "POST", body: JSON.stringify({decision, selected_run_ids: selectedRunIds})});
    toast(decision === "combine" && result.integration_run ? "Integration run queued." : decision === "reject_all" ? "Variants rejected." : "Variant selected.");
    await refreshRuns(); await refreshSelected();
  } catch (error) { toast(error.message, true); }
  finally {
    if (button) { button.disabled = false; button.textContent = originalLabel; }
  }
}

async function openIntegrationDialog(button) {
  if (!state.selectedId) return;
  const originalLabel = button?.textContent;
  try {
    if (button) { button.disabled = true; button.textContent = "Loading..."; }
    const preview = await api(`/api/runs/${encodeURIComponent(state.selectedId)}/integration-candidates`);
    state.integrationPreview = preview;
    renderIntegrationCandidateDialog(preview);
    $("#integrationDialog").showModal();
  } catch (error) { toast(error.message, true); }
  finally {
    if (button) { button.disabled = false; button.textContent = originalLabel; }
  }
}

function renderIntegrationCandidateDialog(preview) {
  const candidates = preview.candidates || [];
  const excluded = preview.excluded || [];
  const list = $("#integrationCandidateList");
  if (!candidates.length) {
    list.innerHTML = `<div class="empty-list">No eligible accepted artifacts are available for this repository and branch.</div>${excluded.length ? `<p class="candidate-exclusions">${excluded.length} accepted artifact${excluded.length === 1 ? "" : "s"} excluded by delivery state, supersession, staleness, or base compatibility.</p>` : ""}`;
    return;
  }
  list.innerHTML = `
    <section class="integration-flow" aria-label="Integration delivery flow">
      <div><strong>1. Review evidence</strong><small>Changed files and checks remain visible before selection.</small></div>
      <div><strong>2. Choose each artifact</strong><small>Integrate now, keep for later, or supersede stale work.</small></div>
      <div><strong>3. One durable job</strong><small>Selected artifacts become one integration task and one delivery decision.</small></div>
    </section>
    ${candidates.map((item) => `
      <article class="integration-candidate" data-candidate-id="${escapeHtml(item.id)}">
        <header><div><strong>${escapeHtml(item.title || item.id)}</strong><small>${escapeHtml(item.id)} · ${escapeHtml(String(item.artifact_sha || "").slice(0, 12))}</small></div><span>${(item.artifact_files || []).length} file${(item.artifact_files || []).length === 1 ? "" : "s"}</span></header>
        <div class="candidate-disposition">
          <label><input type="radio" name="disposition-${escapeHtml(item.id)}" value="integrate_now" checked> <strong>Integrate now</strong><small>Include in this one integration job.</small></label>
          <label><input type="radio" name="disposition-${escapeHtml(item.id)}" value="keep_for_later"> <strong>Keep for later</strong><small>Leave accepted and unapplied.</small></label>
          <label><input type="radio" name="disposition-${escapeHtml(item.id)}" value="supersede"> <strong>Supersede</strong><small>Mark stale because newer work replaces it.</small></label>
        </div>
        <input name="reason-${escapeHtml(item.id)}" aria-label="Disposition reason for ${escapeHtml(item.title || item.id)}" placeholder="Reason or newer task id for Keep/Supersede, optional">
      </article>
    `).join("")}
    ${excluded.length ? `<p class="candidate-exclusions">${excluded.length} accepted artifact${excluded.length === 1 ? "" : "s"} excluded by construction.</p>` : ""}`;
}

async function submitIntegrationDisposition(event) {
  if (event.submitter?.value === "cancel") return;
  event.preventDefault();
  const preview = state.integrationPreview;
  const candidates = preview?.candidates || [];
  if (!state.selectedId || !candidates.length) { toast("There are no integration candidates.", true); return; }
  const form = event.currentTarget;
  const submit = event.submitter;
  const originalLabel = submit.textContent;
  const dispositions = {};
  let integrateCount = 0;
  for (const item of candidates) {
    const chosen = form.elements[`disposition-${item.id}`]?.value;
    if (!chosen) { toast(`Choose a disposition for ${item.id}.`, true); return; }
    if (chosen === "integrate_now") integrateCount += 1;
    dispositions[item.id] = {
      decision: chosen,
      reason: form.elements[`reason-${item.id}`]?.value || "",
    };
  }
  if (integrateCount === 1) { toast("Use direct Apply for a single artifact, or select at least two artifacts for integration.", true); return; }
  try {
    submit.disabled = true;
    submit.textContent = "Creating...";
    const result = await api(`/api/runs/${encodeURIComponent(state.selectedId)}/integration`, {method: "POST", body: JSON.stringify({dispositions})});
    $("#integrationDialog").close();
    toast(result.integration_run ? "Integration run queued." : "Artifact dispositions recorded.");
    await refreshRuns(); await refreshSelected();
  } catch (error) { toast(error.message, true); }
  finally {
    submit.disabled = false;
    submit.textContent = originalLabel;
  }
}

function renderWorkflow(run) {
  const status = run.status; let current = 0;
  if ((run.integration_sources || []).length) current = 2; else if (run.worktree_path || status === "running") current = 1;
  if (status === "running") current = 2;
  if (status === "checking") current = 3;
  if (["reviewing", "review", "accepted", "publishing"].includes(status)) current = 4;
  if (status === "pr_created") current = 5;
  ["stageWorktree", "stageIntegrate", "stageAgent", "stageCheck", "stageReview", "stageCI"].forEach((id, index) => {
    const reviewComplete = ["accepted", "publishing", "pr_created"].includes(status) && index === 4;
    const node = $(`#${id}`); node.classList.toggle("done", index < current || reviewComplete || (status === "pr_created" && index < 5) || run.ci?.status === "passed"); node.classList.toggle("current", index === current && (activeStatuses.has(status) || ["review", "pr_created"].includes(status)));
  });
}

function eventMessage(event) {
  const data = event.data || {};
  if (event.type === "agent.usage") return `in ${compactNumber(data.input_tokens)} · cached ${compactNumber(data.cached_input_tokens)} · out ${compactNumber(data.output_tokens)}`;
  if (event.type.startsWith("agent.tool")) return `${data.tool || data.kind || "tool"}${data.command ? ` · ${data.command}` : ""}${data.exit_code !== undefined ? ` → ${data.exit_code}` : ""}`;
  if (data.message) return truncateText(data.message, 2400); if (data.text) return truncateText(data.text, 2400);
  if (data.command) return `${data.command}${data.returncode !== undefined ? ` → ${data.returncode}` : ""}`;
  if (data.step) return `${data.step}${data.attempt ? ` · attempt ${data.attempt}` : ""}`;
  if (data.status) return data.status; if (data.url) return data.url;
  return Object.keys(data).length ? truncateText(JSON.stringify(data), 2400) : "";
}

function renderEvents() {
  const log = $("#eventLog");
  if (state.eventsLoadingRunId === state.selectedId && state.eventsLoadedRunId !== state.selectedId) {
    log.innerHTML = `<div class="event"><time>—</time><span class="event-type">loading</span><span class="event-message">Reading this task's activity history…</span></div>`;
    return;
  }
  if (state.eventsLoadedRunId !== state.selectedId) {
    log.innerHTML = `<div class="event"><time>—</time><span class="event-type">on demand</span><span class="event-message">Open Activity to load the event history.</span></div>`;
    return;
  }
  const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 80;
  const hiddenCount = Math.max(0, state.events.length - state.eventVisibleLimit);
  const eventRows = state.events.slice(-state.eventVisibleLimit).map((event) => {
    const kind = event.type.includes("failed") ? "failed" : event.type.includes("review") ? "review" : event.type.includes("usage") ? "usage" : "";
    const time = new Date(event.ts).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"});
    return `<div class="event ${kind}"><time>${escapeHtml(time)}</time><span class="event-type" title="${escapeHtml(event.type)}">${escapeHtml(event.type)}</span><span class="event-message">${escapeHtml(eventMessage(event))}</span></div>`;
  }).join("");
  log.innerHTML = `${hiddenCount ? `<button class="ghost activity-load-older" id="loadOlderEvents" type="button">Load ${Math.min(150, hiddenCount)} earlier events · ${hiddenCount} hidden</button>` : ""}${eventRows || `<div class="event"><time>—</time><span class="event-type">waiting</span><span class="event-message">No events yet.</span></div>`}`;
  $("#loadOlderEvents")?.addEventListener("click", () => { state.eventVisibleLimit += 150; renderEvents(); });
  if (atBottom) log.scrollTop = log.scrollHeight;
}

function renderChecks(checks) {
  $("#checkResults").innerHTML = checks.length ? checks.map((check) => { const pass = Number(check.returncode) === 0; return `<div class="check-card"><div class="check-head"><span>${escapeHtml(check.command || "No checks configured")}</span><strong class="${pass ? "check-pass" : "check-fail"}">${check.skipped ? "SKIPPED" : pass ? "PASS" : `FAIL ${check.returncode}`}</strong></div><pre class="check-output">${escapeHtml(truncateText(check.output || "No output."))}</pre></div>`; }).join("") : `<div class="check-output">Checks have not run yet.</div>`;
}

function renderContextReceipt(run) {
  const receipt = run.context_receipt || {};
  const sources = receipt.sources || [];
  if (!receipt.version) {
    $("#contextReceipt").innerHTML = `<div class="empty-card">This task predates context receipts.</div>`;
    return;
  }
  const sourceRows = sources.map((source) => {
    const snapshot = source.kind === "skill"
      ? (run.skill_context || []).find((item) => item.name === source.title)
      : (run.context_bundle || []).find((item) => item.path === source.path && item.kind === source.kind);
    const content = truncateText(snapshot?.content || "");
    return `<details class="receipt-source"><summary><span class="receipt-kind">${escapeHtml(source.kind)}</span><span><strong>${escapeHtml(source.title)}</strong><small>${escapeHtml(source.reason)}</small></span><code>${escapeHtml(String(source.sha256 || "").slice(0, 10))}</code></summary><div><span>${escapeHtml(source.path)}</span><span>${compactNumber(source.bytes)} bytes</span></div><pre>${escapeHtml(content || "Snapshot content is unavailable.")}</pre></details>`;
  }).join("");
  $("#contextReceipt").innerHTML = `<section class="receipt-head"><div><small>CONTEXT RECEIPT</small><strong>${escapeHtml(receipt.version)}</strong><p>These immutable snapshots are exactly what Odysseus attached when the task was queued.</p></div><code title="Complete bundle digest">${escapeHtml(receipt.bundle_sha256 || "")}</code></section><div class="receipt-source-list">${sourceRows || `<div class="empty-card">No repository or skill context was attached.</div>`}</div>`;
}

function renderEvaluation(evaluation) {
  const components = evaluation.components || [];
  $("#evaluationResults").innerHTML = evaluation.version ? `
    <div class="evaluation-head"><strong>${Math.round(Number(evaluation.confidence || 0) * 100)}% confidence</strong><span>${escapeHtml(evaluation.decision || "human_review")}</span></div>
    ${components.map((item) => `<div class="evaluation-row"><div><strong>${escapeHtml(item.id)}</strong><small>${escapeHtml(item.kind || "signal")}</small></div><span>${Math.round(Number(item.score || 0) * 100)}%</span><span class="${item.verdict === "fail" ? "check-fail" : "check-pass"}">${escapeHtml(item.verdict || "—")}</span></div>`).join("")}
  ` : `<div class="empty-card">Evaluation has not run yet.</div>`;
}

function renderIntegration(run) {
  const analysis = run.merge_analysis || {risk: "none", overlaps: [], files: []};
  const sources = run.integration_sources || [];
  const overlaps = analysis.overlaps || [];
  $("#integrationResults").innerHTML = `
    <div class="integration-hero risk-${escapeHtml(analysis.risk || "none")}"><div><small>MERGE RISK</small><strong>${escapeHtml(String(analysis.risk || "none").toUpperCase())}</strong></div><span>${sources.length} predecessor artifact${sources.length === 1 ? "" : "s"}</span></div>
    <div class="artifact-card"><small>DURABLE ARTIFACT</small><code>${escapeHtml(run.artifact_sha || "Created when this task is accepted or published")}</code></div>
    ${sources.length ? `<div class="source-list">${sources.map((source) => `<div><span>${escapeHtml(source.run_id)}</span><code>${escapeHtml(source.artifact_sha?.slice(0, 12) || "—")}</code></div>`).join("")}</div>` : `<div class="empty-card">This task has no predecessor artifacts to compose.</div>`}
    ${overlaps.length ? `<div class="overlap-list"><strong>Overlapping file surfaces</strong>${overlaps.map((item) => `<p>${escapeHtml(item.left)} ↔ ${escapeHtml(item.right)}<br><code>${escapeHtml((item.files || []).join(", "))}</code></p>`).join("")}</div>` : ""}
    ${(analysis.files || []).length ? `<details class="file-surface"><summary>${analysis.files.length} files in the integrated surface</summary><pre>${escapeHtml(analysis.files.join("\n"))}</pre></details>` : ""}`;
}

async function renderDiff() {
  if (!state.selectedId) return;
  const runId = state.selectedId;
  const generation = state.selectionGeneration;
  if (!state.selectedDiff || state.selectedDiffRunId !== runId) {
    $("#diffStat").textContent = "Loading diff…";
    $("#diffPatch").textContent = "Reading the isolated task worktree…";
    if (state.selectedDiffLoadingRunId === runId) return;
    state.selectedDiffLoadingRunId = runId;
    try {
      const diff = await api(`/api/runs/${encodeURIComponent(runId)}/diff`);
      if (state.selectedId !== runId || state.selectionGeneration !== generation) return;
      state.selectedDiff = diff;
      state.selectedDiffRunId = runId;
    } catch (error) {
      if (state.selectedId !== runId || state.selectionGeneration !== generation) return;
      $("#diffStat").textContent = "Diff unavailable.";
      $("#diffPatch").textContent = error.message;
      return;
    } finally {
      if (state.selectedDiffLoadingRunId === runId) state.selectedDiffLoadingRunId = "";
    }
  }
  $("#diffStat").textContent = truncateText(state.selectedDiff.stat || "No changed files yet.");
  $("#diffPatch").textContent = truncateText(state.selectedDiff.patch || "No diff yet.", 120000);
}

function renderCI(run) {
  const ci = run.ci || {status: "not_started", checks: []};
  const checks = ci.checks || [];
  $("#ciResults").innerHTML = `
    <div class="ci-hero ci-${escapeHtml(ci.status || "not_started")}"><div><small>GITHUB CHECKS</small><strong>${escapeHtml(statusLabel(ci.status || "not_started"))}</strong></div><span>${escapeHtml(ci.summary || "Publish a draft PR to start the feedback loop.")}</span></div>
    ${checks.length ? checks.map((check) => `<div class="ci-check"><span>${escapeHtml(check.workflow || "workflow")}</span><strong>${escapeHtml(check.name || "check")}</strong><em>${escapeHtml(check.bucket || check.state || "unknown")}</em></div>`).join("") : `<div class="empty-card">No GitHub check runs recorded.</div>`}
    ${ci.logs ? `<details class="ci-logs"><summary>Failed log captured for agent resume</summary><pre>${escapeHtml(truncateText(ci.logs, 120000))}</pre></details>` : ""}
    <div class="ci-foot"><span>Automatic repairs: ${escapeHtml(ci.attempt || 0)}</span><span>${ci.updated_at ? `Updated ${relativeTime(ci.updated_at)} ago` : "Not polled"}</span></div>`;
}

function openStream(runId) {
  if (state.view !== "tasks" || state.selectedId !== runId) return;
  if (state.stream && state.streamRunId === runId) return;
  closeStream();
  const after = state.eventsLoadedRunId === runId
    ? (state.events.at(-1)?.seq || 0)
    : Number(state.selected?.event_seq || 0);
  const stream = new EventSource(`/api/runs/${encodeURIComponent(runId)}/stream?after=${after}`);
  state.stream = stream;
  state.streamRunId = runId;
  stream.addEventListener("odysseus", (message) => {
    if (state.selectedId !== runId) return;
    const event = JSON.parse(message.data); if (state.events.some((item) => item.seq === event.seq)) return;
    state.events.push(event);
    if (state.taskSection === "activity" && state.eventsLoadedRunId === runId) renderEvents();
    if (["artifact.created", "run.review_ready", "run.accepted"].includes(event.type)) {
      state.selectedDiff = null;
      state.selectedDiffRunId = "";
    }
    window.clearTimeout(state.refreshTimer);
    state.refreshTimer = window.setTimeout(async () => { await refreshRuns(); if (["run.review_ready", "run.failed", "run.accepted", "pr.created", "artifact.created", "integration.completed", "integration.conflict", "ci.started", "ci.failed", "ci.passed", "ci.retry_pushed", "agent.usage", "agent.tool.started"].includes(event.type)) await refreshSelected(); }, 180);
  });
  stream.onopen = () => setConnection(true); stream.onerror = () => setConnection(false);
}
function closeStream() { if (state.stream) state.stream.close(); state.stream = null; state.streamRunId = ""; }
function setConnection(online) { $(".connection").classList.toggle("online", online); $("#connectionLabel").textContent = online ? "Live" : "Reconnecting"; }

async function copyCommand(command) {
  try { await navigator.clipboard.writeText(command); toast(`Copied: ${command}`); }
  catch {
    $("#commandDialogText").textContent = command;
    $("#commandDialog").showModal();
  }
}

function shellQuote(value) {
  return `'${String(value ?? "").replaceAll("'", `'"'"'`)}'`;
}

function assistantProviderLabel(provider) {
  return provider === "claude" ? "Claude Code CLI" : provider === "openai" ? "Direct API: ChatGPT" : provider === "anthropic" ? "Direct API: Claude" : "Codex CLI";
}

function assistantProviderValue() {
  return $("#assistantProvider")?.value || $("#summaryAssistantProvider")?.value || "codex";
}

function syncAssistantProvider(provider) {
  if ($("#assistantProvider")) $("#assistantProvider").value = provider;
  if ($("#summaryAssistantProvider")) $("#summaryAssistantProvider").value = provider;
}

function assistantConversation(runId = state.selectedId) {
  if (!runId) return [];
  if (!state.assistantConversations[runId]) {
    try { state.assistantConversations[runId] = JSON.parse(localStorage.getItem(`odysseus.assistant.${runId}`) || "[]"); }
    catch { state.assistantConversations[runId] = []; }
  }
  return state.assistantConversations[runId];
}

function saveAssistantConversation(runId = state.selectedId) {
  if (!runId) return;
  localStorage.setItem(`odysseus.assistant.${runId}`, JSON.stringify(assistantConversation(runId).slice(-30)));
}

function selectedAssistantScopes() {
  return $$("[data-assistant-scope]").filter((item) => item.checked).map((item) => item.value);
}

function selectedAssistantContextLabels() {
  const labels = selectedAssistantScopes().map((item) => item[0].toUpperCase() + item.slice(1));
  if ($("#assistantIncludeDiff")?.checked) labels.push("Diff/code");
  return labels;
}

function assistantShareSummary() {
  const scopes = selectedAssistantScopes().map((item) => item[0].toUpperCase() + item.slice(1));
  const includeDiff = $("#assistantIncludeDiff")?.checked;
  return `Shared: ${scopes.length ? scopes.join(", ") : "no task context"}. Diff/code ${includeDiff ? "on and redacted" : "off"}.`;
}

function assistantMessageAllowed(message) {
  const shared = Array.isArray(message.shared_context) ? message.shared_context : null;
  if (!shared) return message.role === "user";
  const allowed = new Set(selectedAssistantContextLabels());
  return shared.every((item) => allowed.has(item));
}

function assistantOutgoingMessages() {
  return assistantConversation().filter(assistantMessageAllowed);
}

function assistantOmittedCount() {
  return assistantConversation().length - assistantOutgoingMessages().length;
}

function renderAssistantStatus(message = "") {
  const provider = assistantProviderValue();
  const info = state.bootstrap?.assistant?.[provider] || {};
  const status = $("#assistantStatus");
  const defaultMessage = info.mode === "local_cli"
    ? (info.configured ? `${assistantProviderLabel(provider)} ready. Scratch workspace; selected context only.` : `${assistantProviderLabel(provider)} is not on PATH.`)
    : (info.configured ? `${assistantProviderLabel(provider)} ready via ${info.env}; model ${info.model}.` : `Direct API mode requires ${info.env || (provider === "anthropic" ? "ANTHROPIC_API_KEY" : "OPENAI_API_KEY")} in the server environment.`);
  if (status) {
    status.textContent = message || defaultMessage;
    status.classList.toggle("assistant-missing", !info.configured && !message);
  }
  const access = $("#summaryAssistantAccess");
  if (access) {
    access.textContent = message || (info.mode === "local_cli"
      ? "Scratch workspace; selected context only."
      : "Selected prompt context only.");
    access.classList.toggle("assistant-missing", !info.configured && !message);
  }
}

function renderAssistantMessages() {
  const messages = assistantConversation();
  $("#assistantMessages").innerHTML = messages.length ? messages.map((message) => `
    <article class="assistant-message ${escapeHtml(message.role)} ${assistantMessageAllowed(message) ? "" : "omitted"}">
      <small>${escapeHtml(message.role === "assistant" ? assistantProviderLabel(message.provider || $("#assistantProvider").value) : "You")}</small>
      <p>${escapeHtml(message.content)}</p>
      ${message.shared_context?.length ? `<em>Shared: ${escapeHtml(message.shared_context.join(", "))}</em>` : ""}
      ${assistantMessageAllowed(message) ? "" : `<em>Omitted from the next request because current context sharing is narrower.</em>`}
    </article>
  `).join("") : `<div class="assistant-empty">Ask a local Codex or Claude helper what feedback to send next. Only selected context chips are shared.</div>`;
  $("#assistantMessages").scrollTop = $("#assistantMessages").scrollHeight;
}

function renderAssistantPanel(run = state.selected) {
  if (!run || run.kind === "tmux") return;
  const omitted = assistantOmittedCount();
  const shareText = `${assistantShareSummary()}${omitted ? ` ${omitted} older message${omitted === 1 ? "" : "s"} will be omitted from the next request.` : ""}`;
  $("#assistantShareNotice").textContent = shareText;
  $("#summaryAssistantShareNotice").textContent = shareText;
  renderAssistantStatus();
  renderAssistantMessages();
  const hasAnswer = Boolean(lastAssistantAnswer());
  $("#assistantInsertFeedback").disabled = !hasAnswer;
  $("#assistantSubmitFeedback").disabled = !hasAnswer || !canAssistantFollowUp(run);
  $("#assistantCopy").disabled = !hasAnswer;
  $("#assistantQueueTask").disabled = !hasAnswer;
  $("#summaryAssistantInsertFeedback").disabled = !hasAnswer;
  $("#summaryAssistantSubmitFeedback").disabled = !hasAnswer || !canAssistantFollowUp(run);
}

function lastAssistantAnswer() {
  return [...assistantConversation()].reverse().find((message) => message.role === "assistant")?.content?.trim() || "";
}

function canInlineResume(run = state.selected) {
  return Boolean(run && ["failed", "attention"].includes(run.status));
}

function canAssistantFollowUp(run = state.selected) {
  return Boolean(run && ["review", "failed", "attention", "accepted", "pr_created"].includes(run.status));
}

function canTakeover(run = state.selected) {
  return Boolean(run && (run.tmux_session || run.agent_sessions?.agent || run.agent_session_id));
}

function renderRecoveryCard(run) {
  const visible = canInlineResume(run);
  $("#recoveryCard").classList.toggle("hidden", !visible);
  if (!visible) return;
  const attention = run.status === "attention";
  $("#recoveryLabel").textContent = attention ? "YOUR ANSWER" : "RECOVERY";
  $("#recoveryTitle").textContent = attention ? "Answer and continue this task" : "Resume this task with feedback";
  $("#recoveryCopy").textContent = attention ? "Your answer returns to the same agent thread and worktree." : "The branch and saved agent thread are preserved. Explain what to investigate or fix next.";
  $("#inlineTakeover").classList.toggle("hidden", !canTakeover(run));
}

async function submitReviewFeedback(prompt, button) {
  const originalLabel = button.textContent;
  try {
    button.disabled = true;
    button.textContent = "Sending...";
    await api(`/api/runs/${encodeURIComponent(state.selectedId)}/resume`, {method: "POST", body: JSON.stringify({prompt, strategy: "resume", lane: ""})});
    toast("Changes sent back to the same agent thread.");
    await refreshRuns();
    await refreshSelected();
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.textContent = originalLabel; }
}

async function sendAssistantMessage(source = "side") {
  if (!state.selectedId) return;
  const composer = source === "summary" ? $("#summaryAssistantComposer") : $("#assistantComposer");
  const mirrorComposer = source === "summary" ? $("#assistantComposer") : $("#summaryAssistantComposer");
  const sendButton = source === "summary" ? $("#summaryAssistantSend") : $("#assistantSend");
  const mirrorButton = source === "summary" ? $("#assistantSend") : $("#summaryAssistantSend");
  const instruction = composer.value.trim();
  if (!instruction) { toast("Ask the assistant first.", true); return; }
  const originalLabel = sendButton.textContent;
  const messages = assistantConversation();
  const userMessage = {role: "user", content: instruction, shared_context: selectedAssistantContextLabels()};
  messages.push(userMessage);
  composer.value = "";
  if (mirrorComposer?.value.trim() === instruction) mirrorComposer.value = "";
  renderAssistantMessages();
  try {
    sendButton.disabled = true;
    if (mirrorButton) mirrorButton.disabled = true;
    sendButton.textContent = "Sending...";
    const scopes = selectedAssistantScopes();
    const include_diff = Boolean($("#assistantIncludeDiff").checked);
    const provider = assistantProviderValue();
    renderAssistantStatus(`Sending to ${assistantProviderLabel(provider)}. ${assistantShareSummary()}`);
    const result = await api("/api/assist", {method: "POST", body: JSON.stringify({provider, run_id: state.selectedId, messages: assistantOutgoingMessages().slice(-12), scopes, include_diff})});
    messages.push({role: "assistant", content: result.prompt || "", provider: result.provider, shared_context: result.shared_context || []});
    saveAssistantConversation();
    renderAssistantMessages();
    renderAssistantStatus(`Answered with ${assistantProviderLabel(result.provider)}. ${assistantShareSummary()}`);
  } catch (error) {
    messages.pop();
    composer.value = instruction;
    renderAssistantStatus(error.message);
    renderAssistantMessages();
    toast(error.message, true);
  } finally {
    sendButton.disabled = false;
    if (mirrorButton) mirrorButton.disabled = false;
    sendButton.textContent = originalLabel;
    renderAssistantPanel();
  }
}

async function copyAssistantPrompt() {
  const prompt = lastAssistantAnswer();
  if (!prompt) { toast("There is no assistant answer to copy.", true); return; }
  await copyCommand(prompt);
}

function insertAssistantFeedback() {
  const prompt = lastAssistantAnswer();
  if (!prompt) { toast("There is no assistant answer to insert.", true); return; }
  if (state.selected?.status === "review" && $("#reviewFeedback")) {
    $("#reviewFeedback").value = prompt;
    $("#reviewFeedback").closest("details").open = true;
    toast("Inserted assistant answer into requested changes.");
    return;
  }
  if (canInlineResume()) {
    $("#inlineFeedback").value = prompt;
    toast("Inserted assistant answer into feedback.");
    return;
  }
  if (canAssistantFollowUp()) {
    $("#feedbackForm").elements.feedback.value = prompt;
    $("#feedbackDialog").showModal();
    toast("Inserted assistant answer into follow-up.");
    return;
  }
  toast("This task is not waiting for agent feedback.", true);
}

async function submitInlineFeedback(prompt = $("#inlineFeedback").value.trim(), button = $("#inlineResume")) {
  if (!state.selectedId || !prompt) { toast("Add feedback before resuming.", true); return; }
  if (!canInlineResume()) { toast("This task is not waiting for recovery feedback.", true); return; }
  const originalLabel = button.textContent;
  try {
    button.disabled = true;
    button.textContent = "Resuming...";
    await api(`/api/runs/${encodeURIComponent(state.selectedId)}/resume`, {method: "POST", body: JSON.stringify({prompt, strategy: "resume", lane: ""})});
    toast("Feedback submitted to resume this task.");
    $("#inlineFeedback").value = "";
    await refreshRuns();
    await refreshSelected();
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.textContent = originalLabel; }
}

async function submitAssistantFollowUp(prompt, button) {
  if (!state.selectedId || !prompt) { toast("There is no assistant answer to submit.", true); return; }
  if (!canAssistantFollowUp()) { toast("This task cannot be resumed with assistant feedback.", true); return; }
  const originalLabel = button.textContent;
  try {
    button.disabled = true;
    button.textContent = "Submitting...";
    await api(`/api/runs/${encodeURIComponent(state.selectedId)}/resume`, {method: "POST", body: JSON.stringify({prompt, strategy: "resume", lane: ""})});
    toast("Assistant answer submitted to the agent.");
    await refreshRuns();
    await refreshSelected();
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.textContent = originalLabel; }
}

async function submitAssistantFeedback() {
  const prompt = lastAssistantAnswer();
  if (!prompt) { toast("There is no assistant answer to submit.", true); return; }
  await submitAssistantFollowUp(prompt, $("#assistantSubmitFeedback"));
}

async function queueAssistantTask() {
  const prompt = lastAssistantAnswer();
  const run = state.selected;
  const project = projectById(run?.project_id);
  if (!run || !project || !prompt) { toast("There is no assistant answer to queue.", true); return; }
  const button = $("#assistantQueueTask");
  const originalLabel = button.textContent;
  try {
    button.disabled = true;
    button.textContent = "Queueing...";
    const created = await api("/api/runs", {method: "POST", body: JSON.stringify({task: prompt, project_path: project.path, lane: run.lane || state.bootstrap.default_lane, skill_mode: "auto"})});
    toast(`Queued new task: ${runTitle(created)}`);
    await Promise.all([refreshRuns(), refreshProjects()]);
    await selectRun(created.id);
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.textContent = originalLabel; }
}

async function runAction(action) {
  if (action === "settings") { setView("settings"); return; }
  if (!state.selectedId) return;
  if (action === "resume") { $("#feedbackDialog").showModal(); return; }
  if (action === "apply") {
    const run = state.selected;
    const approved = await confirmChoice({eyebrow: "APPLY LOCALLY", title: `Apply to ${run.base_ref || "the source branch"}?`, lead: "This changes your source checkout.", message: "Odysseus will proceed only if the checkout is clean, on the expected branch, and still descends from the task base. A conflicting merge is aborted automatically.", confirmLabel: "Apply to repository"});
    if (!approved) return;
  }
  if (action === "draft-pr") {
    const approved = await confirmChoice({eyebrow: "PUBLISH FOR REVIEW", title: "Create a draft pull request?", lead: "The task branch will be pushed to GitHub.", message: "Your local source checkout remains unchanged. GitHub CI will be watched after the pull request is created.", confirmLabel: "Create draft PR"});
    if (!approved) return;
  }
  try {
    const result = await api(`/api/runs/${encodeURIComponent(state.selectedId)}/${action}`, {method: "POST", body: "{}"});
    if (action === "takeover") await copyCommand(result.command);
    else toast(action === "accept" ? "Result accepted. It is saved, but not applied yet." : action === "apply" ? "Change applied to the source repository." : action === "draft-pr" ? "Draft pull request created." : action === "ci-poll" ? "GitHub checks refreshed." : `Action completed: ${action}`);
    await refreshRuns(); await refreshSelected();
  } catch (error) { toast(error.message, true); }
}

async function refreshAttention() {
  state.attention = (await api("/api/attention?status=open")).items;
  const counts = state.attention.reduce((value, item) => ({...value, [item.priority]: (value[item.priority] || 0) + 1}), {});
  $("#attentionNavCount").textContent = state.attention.length || "";
  renderProjectTree(); renderWork();
  $("#attentionSummary").innerHTML = ["critical", "high", "medium", "low"].map((priority) => `<div><strong>${counts[priority] || 0}</strong><span>${priority}</span></div>`).join("");
  $("#attentionList").innerHTML = state.attention.length ? state.attention.map((item) => {
    const options = (item.options || []);
    const primaryOption = options.find((option) => option.id !== "takeover") || options[0];
    const extraOptions = options.filter((option) => option !== primaryOption);
    const optionButton = primaryOption ? `<button class="primary" data-attention-answer="${escapeHtml(item.id)}" data-answer="${escapeHtml(primaryOption.id)}" type="button">${escapeHtml(primaryOption.label)}</button>` : "";
    const extraButtons = extraOptions.map((option) => `<button class="ghost" data-attention-answer="${escapeHtml(item.id)}" data-answer="${escapeHtml(option.id)}" type="button">${escapeHtml(option.label)}</button>`).join("");
    const detail = item.data || {};
    const conflicts = detail.conflicts || [];
    const preserved = detail.preserved_branches || detail.preserved || [];
    const conflictBody = item.type === "merge_conflict" ? `<div class="attention-conflict-list"><strong>Conflicting files</strong>${conflicts.length ? conflicts.map((file) => `<code>${escapeHtml(file)}</code>`).join("") : `<span>Unknown</span>`}<strong>Preserved branches</strong>${preserved.length ? preserved.map((branch) => `<code>${escapeHtml(branch)}</code>`).join("") : `<span>Source and integration branches are preserved.</span>`}</div>` : "";
    const classes = `stack-card attention-card priority-${escapeHtml(item.priority)}${item.type === "merge_conflict" ? " attention-conflict" : ""}`;
    const actionLabel = item.type === "merge_conflict" ? "Ask integration agent" : "Answer";
    const title = item.type === "merge_conflict" ? "Integration conflict" : item.title;
    return `<article class="${classes}"><div class="card-row"><span class="mini-status status-${item.priority === "high" || item.priority === "critical" ? "failed" : "queued"}">${escapeHtml(item.priority)} · ${escapeHtml(statusLabel(item.type))}</span><span class="run-id">${relativeTime(item.created_at)}</span></div><h3>${escapeHtml(title)}</h3><p>${escapeHtml(item.type === "merge_conflict" ? "Prerequisite: resolve listed files." : item.message)}</p>${conflictBody}<div class="card-actions">${optionButton || `<button class="primary" data-attention-custom="${escapeHtml(item.id)}" type="button">${escapeHtml(actionLabel)}</button>`}<details class="card-more-actions"><summary>More</summary><div>${extraButtons}<button class="ghost" data-attention-custom="${escapeHtml(item.id)}" type="button">${escapeHtml(actionLabel)}</button>${item.run_id ? `<button class="ghost" data-open-run="${escapeHtml(item.run_id)}" type="button">Open task</button>` : ""}<button class="ghost" data-attention-resolve="${escapeHtml(item.id)}" type="button">Resolve</button></div></details></div></article>`;
  }).join("") : `<div class="attention-zero"><span class="all-clear-mark">✓</span><p class="eyebrow">ALL CLEAR</p><strong>Nothing needs you.</strong><p>${escapeHtml(UI_COPY.noAction)}.</p><div class="empty-actions"><button class="primary" data-attention-new type="button">Start a task</button><button class="ghost" data-attention-epic type="button">Plan work</button><button class="ghost" data-open-terminals type="button">Terminals</button></div></div>`;
  $$('[data-attention-answer]').forEach((button) => button.addEventListener("click", () => respondAttention(button.dataset.attentionAnswer, button.dataset.answer)));
  $$('[data-attention-custom]').forEach((button) => button.addEventListener("click", () => openAttentionResponseDialog(button.dataset.attentionCustom)));
  $$('[data-attention-resolve]').forEach((button) => button.addEventListener("click", async () => { await api(`/api/attention/${encodeURIComponent(button.dataset.attentionResolve)}/resolve`, {method: "POST", body: "{}"}); await refreshAttention(); }));
  $$('[data-open-run]').forEach((button) => button.addEventListener("click", () => selectRun(button.dataset.openRun)));
  $('[data-attention-new]')?.addEventListener("click", () => $("#newTaskButton").click());
  $('[data-attention-epic]')?.addEventListener("click", () => $("#newEpicButton").click());
  $('[data-open-terminals]')?.addEventListener("click", () => setView("sessions"));
}

function openAttentionResponseDialog(itemId) {
  const item = state.attention.find((value) => value.id === itemId);
  if (!item) return;
  const form = $("#attentionResponseForm");
  form.reset();
  form.elements.attention_id.value = itemId;
  $("#attentionResponseTitle").textContent = item.type === "merge_conflict" ? "Resolve integration conflict" : item.title;
  $("#attentionResponseLead").textContent = item.type === "merge_conflict" ? "This resumes the same integration-agent context." : "Send one clear response.";
  $("#attentionResponseMessage").textContent = item.type === "merge_conflict"
    ? "Tell the integration agent how to preserve both sides. Do not retry Apply blindly."
    : item.message;
  const textarea = form.elements.response;
  textarea.value = item.type === "merge_conflict"
    ? "Resolve the listed integration conflicts in the existing integration worktree. Preserve the accepted artifacts and the current source branch behavior, then rerun the configured checks."
    : "";
  $("#attentionResponseDialog").showModal();
  window.requestAnimationFrame(() => textarea.focus());
}

async function respondAttention(itemId, response) {
  try {
    const result = await api(`/api/attention/${encodeURIComponent(itemId)}/respond`, {method: "POST", body: JSON.stringify({response})});
    if (result.takeover?.command) await copyCommand(result.takeover.command);
    else if (result.run?.project_commands_approved) toast("Environment approved; the task is waiting to start.");
    else if (result.run?.status === "cancelled") toast("Configuration rejected; the task was cancelled.");
    else toast("Response recorded; the same agent session is waiting to continue.");
    await Promise.all([refreshAttention(), refreshRuns(), refreshEpics()]);
  } catch (error) { toast(error.message, true); }
}

function epicNodeState(run, task) {
  const status = String(run?.status || task?.status || "queued");
  if (["running", "starting", "checking", "reviewing", "publishing"].includes(status)) return "Running";
  if (status === "attention") return "Needs You";
  if (status === "blocked") return "Blocked";
  if (status === "accepted" || status === "pr_created" || status === "completed") return "Accepted";
  if (status === "failed" || status === "cancelled") return "Failed";
  return "Ready";
}

function renderEpicGraph(epic) {
  const runByKey = new Map((epic.run_ids || []).map((runId) => {
    const run = state.runs.find((item) => item.id === runId);
    return [run?.task_key || runId, run];
  }));
  const planTasks = epic.plan?.tasks || [];
  const nodes = (epic.run_ids || []).length
    ? (epic.run_ids || []).map((runId) => {
        const run = state.runs.find((item) => item.id === runId) || {};
        return {key: run.task_key || run.id || runId, title: runTitle(run, runId), depends_on: run.dependency_keys || run.depends_on || [], run};
      })
    : planTasks.map((task) => ({key: task.task_key, title: task.title || task.task, depends_on: task.depends_on || [], task}));
  if (!nodes.length) return "";
  const keys = new Set(nodes.map((node) => node.key));
  const depthMemo = new Map();
  const depthOf = (node) => {
    if (depthMemo.has(node.key)) return depthMemo.get(node.key);
    const parents = (node.depends_on || []).filter((key) => keys.has(key));
    const depth = parents.length ? 1 + Math.max(...parents.map((parent) => depthOf(nodes.find((item) => item.key === parent)))) : 0;
    depthMemo.set(node.key, depth);
    return depth;
  };
  nodes.forEach(depthOf);
  const maxDepth = Math.max(...nodes.map((node) => depthMemo.get(node.key) || 0), 0);
  const edges = nodes.flatMap((node) => (node.depends_on || []).filter((parent) => keys.has(parent)).map((parent) => `${parent} -> ${node.key}`));
  return `<div class="dag-graph" style="--dag-columns:${maxDepth + 1}" role="img" aria-label="Task dependency graph with ${nodes.length} tasks and ${edges.length} dependencies">
    ${nodes.map((node) => {
      const stateLabel = epicNodeState(node.run, node.task);
      const parentRuns = (node.depends_on || []).map((key) => runByKey.get(key) || state.runs.find((run) => run.id === key)).filter(Boolean);
      const waiting = stateLabel === "Blocked" ? parentRuns.find((run) => !["accepted", "pr_created", "completed"].includes(run.status)) : null;
      return `<div class="dag-graph-node dag-state-${stateLabel.toLowerCase().replaceAll(" ", "-")}" style="grid-column:${(depthMemo.get(node.key) || 0) + 1}" tabindex="0">
        <span>${escapeHtml(stateLabel)}</span><strong>${escapeHtml(node.title || node.key)}</strong><small>${escapeHtml(node.depends_on?.length ? `after ${node.depends_on.join(", ")}` : "root task")}</small>${waiting ? `<em>Waiting for ${escapeHtml(runTitle(waiting, waiting.id))}</em>` : ""}</div>`;
    }).join("")}
    ${edges.length ? `<p class="dag-edge-list">Edges: ${escapeHtml(edges.join("; "))}</p>` : `<p class="dag-edge-list">No dependencies.</p>`}
  </div><ol class="dag-linear-fallback">${nodes.map((node) => `<li><strong>${escapeHtml(node.title || node.key)}</strong><span>${escapeHtml(epicNodeState(node.run, node.task))}</span><small>${escapeHtml(node.depends_on?.length ? `Depends on ${node.depends_on.join(", ")}` : "No dependencies")}</small></li>`).join("")}</ol>`;
}

async function refreshEpics() {
  state.epics = (await api("/api/epics")).epics;
  $("#epicNavCount").textContent = state.epics.filter((epic) => ["planning", "proposed", "active"].includes(epic.status)).length || "";
  const visibleEpics = activeProject() ? state.epics.filter((epic) => epic.project_id === state.projectFilter) : state.epics;
  $("#epicList").innerHTML = visibleEpics.length ? visibleEpics.map((epic) => {
    const graph = renderEpicGraph(epic);
    const epicProject = projectById(epic.project_id);
    const sources = epic.source_documents || [];
    const linkedRuns = (epic.run_ids || []).map((runId) => state.runs.find((run) => run.id === runId)).filter(Boolean);
    const sourceLine = sources.length ? `<div class="epic-source-line"><strong>Source decision${sources.length === 1 ? "" : "s"}</strong>${sources.map((source) => `<span title="${escapeHtml(source.sha256 || "")}">${escapeHtml(source.path)} <code>${escapeHtml(String(source.sha256 || "").slice(0, 8))}</code></span>`).join("")}</div>` : "";
    const runButtons = (epic.run_ids || []).map((runId) => `<button class="ghost" data-open-run="${escapeHtml(runId)}" type="button">${escapeHtml(state.runs.find((run) => run.id === runId)?.task_key || "task")}</button>`).join("");
    return `<article class="stack-card epic-card"><div class="card-row"><span class="mini-status ${statusClass(epic.status)}">${escapeHtml(epic.status)}</span><span class="run-id">${escapeHtml(epicProject ? projectName(epicProject) : "repository")}</span></div><h3>${escapeHtml(epic.title)}</h3><p>${escapeHtml(epic.status === "proposed" ? "Review graph, then approve." : epic.status === "active" ? "Tasks are running or waiting." : epic.plan?.summary || epic.description || "Planning...")}</p>${sourceLine}${graph}<div class="card-actions">${epic.status === "proposed" ? `<button class="primary" data-approve-epic="${escapeHtml(epic.id)}" type="button">Approve plan</button>` : ""}${runButtons ? `<details class="card-more-actions"><summary>${linkedRuns.length} task${linkedRuns.length === 1 ? "" : "s"}</summary><div>${runButtons}</div></details>` : ""}</div></article>`;
  }).join("") : `<div class="empty-card">No plans yet.</div>`;
  $$('[data-approve-epic]').forEach((button) => button.addEventListener("click", async () => {
    const approved = await confirmChoice({eyebrow: "START A TASK PLAN", title: "Approve this plan?", lead: "Every dependency-ready root task will start.", message: "Review the task graph first. Dependent tasks remain blocked until their predecessors produce accepted artifacts.", confirmLabel: "Approve and start"});
    if (!approved) return;
    try { await api(`/api/epics/${encodeURIComponent(button.dataset.approveEpic)}/approve`, {method: "POST", body: "{}"}); toast("Plan approved. Ready tasks are waiting to start."); await Promise.all([refreshEpics(), refreshRuns()]); } catch (error) { toast(error.message, true); }
  }));
  $$('[data-open-run]').forEach((button) => button.addEventListener("click", () => selectRun(button.dataset.openRun)));
}

async function refreshProjects() {
  state.projects = (await api("/api/projects")).projects.filter((project) => project.git_repository !== false);
  const projectOptions = state.projects.map((project) => `<option value="${escapeHtml(project.id)}">${escapeHtml(projectOptionLabel(project))}</option>`).join("");
  $("#projectFilter").innerHTML = `<option value="all">All repositories</option>${projectOptions}`; $("#projectFilter").value = state.projectFilter;
  const preferred = preferredProjectId();
  $("#taskProjectSelect").innerHTML = projectOptions || `<option value="">Add a repository first</option>`;
  $("#epicProjectSelect").innerHTML = projectOptions || `<option value="">Add a repository first</option>`;
  if (preferred) { $("#taskProjectSelect").value = preferred; $("#epicProjectSelect").value = preferred; }
  syncCustomProject($("#taskProjectSelect"), $("#taskCustomProject"));
  syncCustomProject($("#epicProjectSelect"), $("#epicCustomProject"));
  $("#inboxProjectSelect").innerHTML = `<option value="">No repository</option>${projectOptions}`;
  $("#githubProject").innerHTML = state.projects.filter((project) => project.github_url).map((project) => `<option value="${escapeHtml(project.id)}">${escapeHtml(projectOptionLabel(project))}</option>`).join("") || `<option value="">No GitHub repositories</option>`;
  renderProjects(); renderRuns(); renderProjectTree(); renderWork(); updateGitHubLink();
}

async function forgetProject(identifier) {
  const project = projectById(identifier);
  if (!project) return;
  const approved = await confirmChoice({eyebrow: "FORGET REPOSITORY", title: `Remove ${projectOptionLabel(project)}?`, lead: "Only the Odysseus shortcut will be removed.", message: `The repository and every file in ${project.path} stay untouched.`, confirmLabel: "Remove from Odysseus"});
  if (!approved) return;
  try {
    await api(`/api/projects/${encodeURIComponent(project.id)}`, {method: "DELETE"});
    if (state.projectFilter === project.id) state.projectFilter = "all";
    await refreshProjects();
    selectProject("all");
    toast(`${projectName(project)} was removed from Your repositories. Its files were not changed.`);
  } catch (error) { toast(error.message, true); }
}

function renderProjects() {
  $("#projectList").innerHTML = state.projects.length ? state.projects.map((project) => `
    <article class="collection-card"><div class="card-row"><span class="mini-status status-accepted">registered</span><span class="run-id">${escapeHtml(project.branch || "git")}</span></div>
      <h3>${escapeHtml(projectName(project))}</h3><p><strong>${escapeHtml(projectRepository(project))}</strong><br><span class="local-folder">${escapeHtml(project.path)}</span></p><div class="card-meta"><span>${escapeHtml(project.folder_name || "local checkout")}</span>${(project.tags || []).map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}</div>
      <div class="card-actions"><button class="ghost" data-filter-project="${escapeHtml(project.id)}" type="button">Open repository</button>${project.github_url ? `<a class="action-button" href="${escapeHtml(project.github_url)}" target="_blank" rel="noreferrer">GitHub</a>` : ""}<button class="text-button danger-text" data-forget-project="${escapeHtml(project.id)}" type="button">Forget</button></div></article>`).join("") : `<div class="empty-card">No repositories yet. Add one local Git repository to start.</div>`;
  $$('[data-filter-project]').forEach((button) => button.addEventListener("click", () => selectProject(button.dataset.filterProject)));
  $$('[data-forget-project]').forEach((button) => button.addEventListener("click", () => forgetProject(button.dataset.forgetProject)));
}

function renderSettings(config = state.config || {}) {
  if (!$("#settingsForm")) return;
  const lanes = state.bootstrap?.lanes || [];
  const laneOptions = (selected) => lanes.map((lane) => `<option value="${escapeHtml(lane)}" ${lane === selected ? "selected" : ""}>${escapeHtml(lane)}</option>`).join("");
  $("#settingsDefaultLane").innerHTML = laneOptions(config.default_lane || state.bootstrap?.default_lane);
  $("#settingsPlannerLane").innerHTML = laneOptions(config.planner_lane || config.default_lane || state.bootstrap?.planner_lane);
  $("#settingsReviewLane").innerHTML = laneOptions(config.review_lane || config.default_lane || state.bootstrap?.review_lane);
  const form = $("#settingsForm");
  const budgets = config.budgets || {};
  const ci = config.ci || {};
  form.elements.max_parallel.value = config.max_parallel || state.bootstrap?.max_parallel || 2;
  form.elements.max_retries.value = config.max_retries ?? 2;
  form.elements.timeout_seconds.value = budgets.timeout_seconds || 0;
  form.elements.stall_seconds.value = budgets.stall_seconds || 900;
  form.elements.max_tokens.value = budgets.max_tokens || 0;
  form.elements.max_tool_calls.value = budgets.max_tool_calls || 0;
  form.elements.max_cost_usd.value = budgets.max_cost_usd || 0;
  form.elements.ci_watch.checked = ci.watch !== false;
  form.elements.ci_auto_resume.checked = ci.auto_resume !== false;
  form.elements.ci_max_attempts.value = ci.max_attempts ?? 2;
  form.elements.ci_poll_seconds.value = ci.poll_seconds ?? 30;
  form.elements.resource_retention_days.value = config.resource_retention_days || 14;
  const configuredModels = config.assistant_models || {};
  const assistantForm = $("#assistantSettingsForm");
  assistantForm.elements.openai_model.value = configuredModels.openai || "";
  assistantForm.elements.anthropic_model.value = configuredModels.anthropic || "";
  const assistant = state.bootstrap?.assistant || {};
  $("#assistantSettings").innerHTML = Object.entries(assistant).map(([provider, info]) => {
    const configured = info.configured ? "Configured" : "Not configured";
    const mode = info.mode === "local_cli" ? "Local CLI authentication" : `Server environment: ${info.env}`;
    const model = info.model ? `<span>Model: ${escapeHtml(info.model)}</span>` : "";
    const modelEnv = info.model_env ? `<span>Model env: ${escapeHtml(info.model_env)}</span>` : "";
    return `<article class="settings-row"><div><strong>${escapeHtml(assistantProviderLabel(provider))}</strong><small>${escapeHtml(mode)}</small></div><em class="${info.configured ? "configured" : "missing"}">${configured}</em>${model}${modelEnv}</article>`;
  }).join("");
  renderResources();
}

async function refreshSettings() {
  const [config, bootstrap, resources] = await Promise.all([api("/api/config"), api("/api/bootstrap"), api("/api/resources")]);
  state.config = config;
  state.bootstrap = bootstrap;
  state.resources = resources;
  state.bootstrap.max_parallel = state.config.max_parallel;
  state.bootstrap.default_lane = state.config.default_lane;
  state.bootstrap.planner_lane = state.config.planner_lane || state.config.default_lane;
  state.bootstrap.review_lane = state.config.review_lane || state.config.default_lane;
  $("#parallelLabel").textContent = `${state.bootstrap.max_parallel} slots`;
  const options = (selected) => state.bootstrap.lanes.map((lane) => `<option value="${escapeHtml(lane)}" ${lane === selected ? "selected" : ""}>${escapeHtml(lane)}</option>`).join("");
  $("#laneSelect").innerHTML = options(state.bootstrap.default_lane);
  $("#plannerLaneSelect").innerHTML = options(state.bootstrap.planner_lane);
  $("#epicLaneSelect").innerHTML = options(state.bootstrap.default_lane);
  $("#epicReviewLaneSelect").innerHTML = options(state.bootstrap.review_lane);
  $("#resumeLaneSelect").innerHTML = options(state.bootstrap.default_lane);
  $("#quickStart").dataset.mode = "";
  renderSettings();
  renderWork();
}

function renderResources() {
  const container = $("#resourceSettings");
  if (!container) return;
  const resources = state.resources;
  if (!resources) {
    container.innerHTML = `<div class="empty-list">Loading retained resources...</div>`;
    return;
  }
  const totals = resources.totals || {};
  const recent = [...(resources.worktrees || []), ...(resources.runtime_directories || [])]
    .filter((item) => item.reclaimable || item.force_reclaimable)
    .slice(0, 6);
  container.innerHTML = `
    <div class="resource-summary">
      <div><strong>${escapeHtml(formatBytes(totals.worktree_bytes))}</strong><span>Worktrees</span></div>
      <div><strong>${escapeHtml(formatBytes(totals.runtime_bytes))}</strong><span>Runtime</span></div>
      <div><strong>${escapeHtml(formatBytes(totals.reclaimable_bytes))}</strong><span>Reclaimable</span></div>
    </div>
    <div class="resource-list">${recent.length ? recent.map((item) => `<article class="settings-row"><div><strong>${escapeHtml(item.title || item.run_id || "orphan runtime")}</strong><small>${escapeHtml(item.status)} · ${escapeHtml(item.reason)}</small></div><em>${escapeHtml(formatBytes(item.bytes))}</em><span>${escapeHtml(item.path)}${item.branch ? ` · branch preserved: ${escapeHtml(item.branch)}` : ""}</span></article>`).join("") : `<div class="empty-list">No resources are eligible for reclamation right now.</div>`}</div>`;
}

function updateGitHubLink() {
  const project = projectById(state.selected?.project_id || (state.projectFilter !== "all" ? state.projectFilter : "")); const link = $("#githubButton");
  const url = project?.github_url || state.bootstrap?.repository_url || "https://github.com/jpolec/odysseus";
  link.classList.remove("disabled"); link.href = url; link.title = project?.github_url ? `Open ${projectName(project)} on GitHub` : "Open Odysseus on GitHub";
}

async function refreshSessions() {
  try { state.sessions = (await api("/api/tmux/sessions")).sessions; renderSessions(); renderProjectTree(); renderWork(); }
  catch (error) { $("#sessionList").innerHTML = `<div class="empty-card">${escapeHtml(error.message)}</div>`; }
}

function renderSessions() {
  const scopeSelect = $("#sessionScope");
  const repositoryOption = scopeSelect?.querySelector('option[value="repositories"]');
  if (repositoryOption) repositoryOption.textContent = activeProject() ? "This repository" : "Your repositories";
  if (scopeSelect && scopeSelect.value !== state.sessionScope) scopeSelect.value = state.sessionScope;
  const visibleSessions = state.sessionScope === "repositories"
    ? repositoryScopedSessions()
    : state.sessionScope === "attached"
      ? state.sessions.filter((session) => session.attached)
      : state.sessions;
  const uniqueTmux = new Set(visibleSessions.map((session) => session.tmux_session)).size;
  const waiting = visibleSessions.filter((session) => session.status === "waiting").length;
  const working = visibleSessions.filter((session) => session.status === "working").length;
  const tracked = visibleSessions.filter((session) => session.adopted_run_id).length;
  $("#sessionSummary").innerHTML = [
    [visibleSessions.length, "shown", `${uniqueTmux} tmux sessions · ${state.sessions.length} discovered`], [working, "working", "visible tmux activity"], [waiting, "need terminal input", "action required"], [tracked, "tracked", "durable Odysseus entries"],
  ].map(([value, label, note]) => `<div><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span><small>${escapeHtml(note)}</small></div>`).join("");
  const groups = new Map();
  visibleSessions.forEach((session) => { const key = session.tmux_session || "unknown"; if (!groups.has(key)) groups.set(key, []); groups.get(key).push(session); });
  $("#sessionList").innerHTML = visibleSessions.length ? [...groups.entries()].map(([name, sessions]) => {
    const attached = sessions.some((session) => session.attached);
    const cards = sessions.map((session) => {
      const title = session.title && session.title !== "-" ? session.title : session.window_name || `${session.lane} agent`;
      const location = [session.window_name ? `window ${session.window_name}` : "", session.tmux_target ? `pane ${session.tmux_target}` : ""].filter(Boolean).join(" · ");
      const context = session.context_remaining && session.metadata_confidence === "exact" ? `<span>${escapeHtml(session.context_remaining)} context</span>` : "";
      return `<article class="collection-card session-card"><div class="session-card-head"><span class="agent-avatar agent-${escapeHtml(session.lane)}">${escapeHtml(String(session.lane || "?").slice(0, 1).toUpperCase())}</span><div><span class="mini-status ${statusClass(session.status)}">${escapeHtml(statusLabel(session.status))}</span><h3 title="${escapeHtml(title)}">${escapeHtml(title)}</h3></div><span class="run-id">${escapeHtml(location || session.id)}</span></div><p class="session-location" title="${escapeHtml(session.project_path || "")}">${escapeHtml(session.project_path || "Unknown repository")}</p>
        <div class="card-meta"><span>${escapeHtml(session.lane)}</span>${context}${session.managed ? "<span>Odysseus-managed</span>" : "<span>discovered automatically</span>"}</div>
        <div class="card-actions">${session.adopted_run_id ? `<button class="ghost" data-open-run="${escapeHtml(session.adopted_run_id)}" type="button">Open tracked entry</button>` : `<button class="primary" data-adopt="${escapeHtml(session.id)}" type="button" title="Adds this pane to Tasks without changing it">Track in Odysseus</button>`}<button class="ghost" data-attach="${escapeHtml(session.tmux_session)}" data-pane-target="${escapeHtml(session.tmux_target || "")}" type="button">Copy tmux command</button></div></article>`;
    }).join("");
    return `<section class="session-group"><div class="session-group-head"><h2>tmux session ${escapeHtml(name)}</h2><span>${sessions.length} agent pane${sessions.length === 1 ? "" : "s"} · ${attached ? "attached" : "detached"}</span></div><div class="session-group-grid">${cards}</div></section>`;
  }).join("") : `<div class="empty-card"><strong>${state.sessionScope === "repositories" && state.sessions.length ? activeProject() ? "No panes for this repository." : "No panes for your repositories." : state.sessionScope === "attached" && state.sessions.length ? "No panes in an attached tmux session." : "No agent terminals found."}</strong><br>${state.sessionScope === "repositories" && state.sessions.length ? "Choose All discovered sessions to see other Codex and Claude panes." : state.sessionScope === "attached" && state.sessions.length ? "Choose All discovered sessions to see detached tmux sessions." : "Start Codex or Claude inside tmux; it will appear here automatically within a few seconds. There is no import button."}</div>`;
  $$('[data-open-run]').forEach((button) => button.addEventListener("click", () => selectRun(button.dataset.openRun)));
  $$('[data-attach]').forEach((button) => button.addEventListener("click", () => copyCommand(button.dataset.paneTarget ? `tmux select-pane -t ${button.dataset.paneTarget} \\; attach-session -t ${button.dataset.attach}` : `tmux attach-session -t ${button.dataset.attach}`)));
  $$('[data-adopt]').forEach((button) => button.addEventListener("click", async () => { try { const run = await api(`/api/tmux/sessions/${encodeURIComponent(button.dataset.adopt)}/adopt`, {method: "POST", body: "{}"}); toast("Now tracking this pane. The original tmux session was not changed."); await Promise.all([refreshSessions(), refreshRuns(), refreshProjects()]); await selectRun(run.id); } catch (error) { toast(error.message, true); } }));
}

async function refreshInbox() { state.inbox = (await api("/api/inbox")).items; renderInbox(); $("#inboxNavCount").textContent = state.inbox.filter((item) => item.status === "open").length || ""; }
function renderInbox() {
  $("#inboxList").innerHTML = state.inbox.length ? state.inbox.map((item) => { const inboxProject = projectById(item.project_id); return `<article class="stack-card"><div class="card-row"><span class="mini-status ${item.status === "open" ? "status-queued" : "status-accepted"}">${escapeHtml(item.status)}</span><span class="run-id">${relativeTime(item.updated_at)}</span></div><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.task)}</p><div class="card-meta"><span>${escapeHtml(inboxProject ? projectName(inboxProject) : "no repository")}</span><span>${escapeHtml(item.priority)}</span></div><div class="card-actions">${item.status === "open" && item.project_path ? `<button class="primary" data-promote="${escapeHtml(item.id)}" type="button">Queue task</button>` : ""}${item.status === "open" ? `<button class="ghost" data-resolve="${escapeHtml(item.id)}" type="button">Resolve</button>` : ""}</div></article>`; }).join("") : `<div class="empty-card"><strong>No follow-ups.</strong><br>Adding one does not start an agent.</div>`;
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

async function refreshInsights() {
  try {
    state.stats = await api("/api/stats");
    const entries = [
      ["Successful changes", state.stats.successful_changes, `${Math.round(Number(state.stats.success_rate || 0) * 100)}% of tasks`],
      ["Human interventions", state.stats.human_interventions, state.stats.human_interventions_per_successful_change === null ? `${state.stats.open_attention} currently open` : `${state.stats.human_interventions_per_successful_change} / successful change`],
      ["Tokens observed", compactNumber(state.stats.tokens), `${compactNumber(state.stats.tool_calls)} tool calls`],
      ["Compute cost", `$${Number(state.stats.cost_usd || 0).toFixed(2)}`, state.stats.cost_per_successful_change === null ? "No accepted task yet" : `$${Number(state.stats.cost_per_successful_change).toFixed(2)} / success`],
      ["CI repair loops", state.stats.ci_failures, "published changes repaired"],
      ["High merge risk", state.stats.merge_risk_high, "tasks with overlap"],
    ];
    $("#insightStats").innerHTML = entries.map(([label, value, note]) => `<article class="insight-card"><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong><p>${escapeHtml(note)}</p></article>`).join("");
  } catch (error) { toast(error.message, true); }
}

async function runSearch(query = "") {
  const value = String(query || $("#insightSearch").value || $("#globalSearch").value || "").trim();
  if (!value) return;
  $("#insightSearch").value = value; $("#globalSearch").value = value; setView("insights");
  $("#searchResults").innerHTML = `<div class="empty-card">Searching local state…</div>`;
  try {
    state.searchResults = (await api(`/api/search?q=${encodeURIComponent(value)}`)).results;
    $("#searchResults").innerHTML = state.searchResults.length ? state.searchResults.map((item) => `<article class="search-result"><div><span>${escapeHtml(item.kind)}</span><span>${escapeHtml(item.status || "record")}</span></div><h3>${escapeHtml(item.title || item.id)}</h3><p>${escapeHtml(item.snippet || "No preview")}</p>${item.run_id ? `<button class="ghost" data-search-run="${escapeHtml(item.run_id)}" type="button">Open task</button>` : ""}</article>`).join("") : `<div class="empty-card">No local record matched “${escapeHtml(value)}”.</div>`;
    $$('[data-search-run]').forEach((button) => button.addEventListener("click", () => selectRun(button.dataset.searchRun)));
  } catch (error) { toast(error.message, true); }
}

function bindDialogs() {
  const projectProfileDialog = $("#projectProfileDialog");
  $("#editProjectBrief").addEventListener("click", () => { const form = $("#projectProfileForm"); form.elements.summary.value = state.projectOverview?.profile?.summary || ""; form.elements.notes.value = state.projectOverview?.profile?.notes || ""; projectProfileDialog.showModal(); });
  $("#projectProfileForm").addEventListener("submit", async (event) => { if (event.submitter?.value === "cancel") return; event.preventDefault(); const project = activeProject(); if (!project) return; const submit = event.submitter; const data = new FormData(event.currentTarget); try { submit.disabled = true; await api(`/api/projects/${encodeURIComponent(project.id)}/profile`, {method: "POST", body: JSON.stringify({summary: data.get("summary"), notes: data.get("notes")})}); projectProfileDialog.close(); await refreshProjectOverview(); toast("Repository overview saved."); } catch (error) { toast(error.message, true); } finally { submit.disabled = false; } });
  $("#addProjectMemory").addEventListener("click", () => openKnowledgeDialog());
  $("#knowledgeForm").addEventListener("submit", async (event) => { if (event.submitter?.value === "cancel") return; event.preventDefault(); const project = activeProject(); if (!project) return; const submit = event.submitter; const data = new FormData(event.currentTarget); const payload = {id: data.get("id"), source: data.get("source"), title: data.get("title"), content: data.get("content"), triggers: String(data.get("triggers") || "").split(",").map((value) => value.trim()).filter(Boolean), folders: String(data.get("folders") || "").split(",").map((value) => value.trim()).filter(Boolean), enabled: data.get("enabled") === "on"}; try { submit.disabled = true; state.projectKnowledge = await api(`/api/projects/${encodeURIComponent(project.id)}/knowledge`, {method: "POST", body: JSON.stringify(payload)}); $("#knowledgeDialog").close(); renderProjectMemory(); toast("Repository memory saved."); } catch (error) { toast(error.message, true); } finally { submit.disabled = false; } });
  const taskDialog = $("#taskDialog");
  [$("#newTaskButton"), $("#emptyNewTask"), $("#workNewTaskButton")].forEach((button) => button?.addEventListener("click", () => { prepareProjectSelect($("#taskProjectSelect"), $("#taskCustomProject")); refreshTaskSkillChoices().catch((error) => toast(error.message, true)); taskDialog.showModal(); }));
  $("#taskProjectSelect").addEventListener("change", () => { syncCustomProject($("#taskProjectSelect"), $("#taskCustomProject")); refreshTaskSkillChoices().catch((error) => toast(error.message, true)); });
  $("#taskPrompt").addEventListener("input", scheduleTaskSkillRecommendations);
  $("#taskSkillMode").addEventListener("change", () => { renderTaskSkillChoices(); renderTaskSkillRecommendations(); scheduleTaskSkillRecommendations(); });
  $("#environmentProfile").addEventListener("change", (event) => $("#environmentOptions").classList.toggle("hidden", event.currentTarget.value !== "docker"));
  $("#untrustedProject").addEventListener("change", (event) => { if (!event.currentTarget.checked) return; const select = $("#environmentProfile"); const docker = select.querySelector('option[value="docker"]'); if (docker?.disabled) { event.currentTarget.checked = false; toast("Install Docker before running an untrusted repository.", true); return; } select.value = "docker"; select.dispatchEvent(new Event("change")); });
  $("#variantsEnabled").addEventListener("change", (event) => $("#variantOptions").classList.toggle("hidden", !event.currentTarget.checked));
  $("#epicProjectSelect").addEventListener("change", () => syncCustomProject($("#epicProjectSelect"), $("#epicCustomProject")));
  $("#taskForm").addEventListener("submit", async (event) => {
    if (event.submitter?.value === "cancel") return;
    event.preventDefault();
    const submit = event.submitter;
    const originalLabel = submit.textContent;
    const addAnother = submit.value === "another";
    const form = event.currentTarget;
    const data = new FormData(form);
    const project = projectById(data.get("project_id"));
    if (!project) { toast("Add a repository first.", true); return; }
    let environment;
    try { environment = environmentFromForm(data); }
    catch (error) { toast(error.message, true); return; }
    const variantsEnabled = data.get("variants_enabled") === "on";
    const variantCount = Number(data.get("variant_count") || 2);
    const variantLanes = String(data.get("variant_lanes") || "").split(",").map((item) => item.trim()).filter(Boolean);
    const variantPrompts = String(data.get("variant_prompts") || "").split("\n").map((item) => item.trim()).filter(Boolean);
    const payload = {
      task: data.get("task"), title: data.get("title"), project_path: project.path, lane: data.get("lane"),
      skill_mode: data.get("skill_mode"), skills: data.getAll("skills"), environment,
      untrusted_project: data.get("untrusted_project") === "on", workflow: variantsEnabled ? "variants" : "agent-check-review",
      variants: variantsEnabled ? {enabled: true, count: variantCount, lanes: variantLanes, prompts: variantPrompts} : {enabled: false},
      priority: Number(data.get("priority")), max_retries: Number(data.get("max_retries")),
      checks: String(data.get("checks") || "").split("\n").map((item) => item.trim()).filter(Boolean),
      budgets: {timeout_seconds: Number(data.get("timeout")), stall_seconds: Number(data.get("stall_timeout")), max_tokens: Number(data.get("max_tokens")), max_tool_calls: Number(data.get("max_tool_calls")), max_cost_usd: Number(data.get("max_cost"))},
    };
    const taskDraft = String(form.elements.task.value || "");
    const titleDraft = String(form.elements.title.value || "");
    const status = $("#taskSubmitStatus");
    try {
      form.elements.task.value = "";
      form.elements.title.value = "";
      status.textContent = `Starting ${payload.lane} on ${projectName(project)}...`;
      status.classList.remove("hidden");
      setFormSubmitting(form, true, submit, "Starting...");
      const run = await api("/api/runs", {method: "POST", body: JSON.stringify(payload)});
      state.taskSkillRecommendations = null;
      renderTaskSkillRecommendations();
      status.textContent = addAnother ? "Task started. Add the next request." : "Task started. Opening the live task view...";
      toast(`Task started for ${data.get("lane")}: ${runTitle(run)}`);
      await Promise.all([refreshRuns(), refreshProjects()]);
      if (addAnother) {
        window.requestAnimationFrame(() => $("#taskPrompt").focus());
        window.setTimeout(() => status.classList.add("hidden"), 2200);
      }
      else {
        taskDialog.close();
        form.reset();
        $("#environmentOptions").classList.add("hidden");
        $("#variantOptions").classList.add("hidden");
        state.taskSkillCatalog = null;
        renderTaskSkillChoices();
        await selectRun(run.id);
      }
    } catch (error) {
      form.elements.task.value = taskDraft;
      form.elements.title.value = titleDraft;
      status.classList.add("hidden");
      toast(error.message, true);
    }
    finally {
      setFormSubmitting(form, false, submit, originalLabel);
      if (!addAnother || !taskDialog.open) status.classList.add("hidden");
    }
  });
  [$("#newEpicButton"), $("#workPlanButton")].forEach((button) => button?.addEventListener("click", () => openEpicDialog()));
  $("#planSelectedDecisions").addEventListener("click", () => openEpicDialog(state.selectedDecisionPaths));
  $("#epicForm").addEventListener("submit", async (event) => { if (event.submitter?.value === "cancel") return; event.preventDefault(); const submit = event.submitter; const data = new FormData(event.currentTarget); const project = projectById($("#epicProjectSelect").value); if (!project) { toast("Add a repository first.", true); return; } const payload = {requirement: data.get("requirement"), project_id: project.id, project_path: project.path, source_paths: [...state.selectedDecisionPaths], planner_lane: data.get("planner_lane"), lane: data.get("lane"), review_lane: data.get("review_lane"), checks: String(data.get("checks") || "").split("\n").map((item) => item.trim()).filter(Boolean)}; try { submit.disabled = true; submit.textContent = "Reading repository…"; await api("/api/epics/plan", {method: "POST", body: JSON.stringify(payload)}); $("#epicDialog").close(); event.currentTarget.reset(); state.selectedDecisionPaths = []; toast("Task graph proposed. Review it before approving any work."); await Promise.all([refreshEpics(), refreshProjectOverview()]); setView("epics"); } catch (error) { toast(error.message, true); } finally { submit.disabled = false; submit.textContent = "Generate task plan"; } });
  $("#feedbackForm").addEventListener("submit", async (event) => { if (event.submitter?.value === "cancel") return; event.preventDefault(); const data = new FormData(event.currentTarget); const prompt = data.get("feedback"); const strategy = data.get("strategy"); try { await api(`/api/runs/${encodeURIComponent(state.selectedId)}/resume`, {method: "POST", body: JSON.stringify({prompt, strategy, lane: data.get("lane")})}); $("#feedbackDialog").close(); event.currentTarget.reset(); toast(strategy === "resume" ? "Existing agent session is waiting to continue." : strategy === "switch" ? "Branch handed to the selected lane." : "Clean-context attempt is waiting on the same branch."); await refreshRuns(); await refreshSelected(); } catch (error) { toast(error.message, true); } });
  $("#integrationForm").addEventListener("submit", submitIntegrationDisposition);
  $("#attentionResponseForm").addEventListener("submit", async (event) => {
    if (event.submitter?.value === "cancel") return;
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const response = String(data.get("response") || "").trim();
    if (!response) { toast("Write a response first.", true); return; }
    try {
      await respondAttention(String(data.get("attention_id") || ""), response);
      $("#attentionResponseDialog").close();
      form.reset();
    } catch (error) { toast(error.message, true); }
  });
  $("#assistantProvider").addEventListener("change", (event) => { syncAssistantProvider(event.currentTarget.value); renderAssistantPanel(); });
  $("#summaryAssistantProvider").addEventListener("change", (event) => { syncAssistantProvider(event.currentTarget.value); renderAssistantPanel(); });
  $$("[data-assistant-scope]").forEach((item) => item.addEventListener("change", () => renderAssistantPanel()));
  $("#assistantIncludeDiff").addEventListener("change", () => renderAssistantPanel());
  $("#assistantSend").addEventListener("click", () => sendAssistantMessage());
  $("#summaryAssistantSend").addEventListener("click", () => sendAssistantMessage("summary"));
  $("#assistantComposer").addEventListener("keydown", (event) => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") sendAssistantMessage(); });
  $("#summaryAssistantComposer").addEventListener("keydown", (event) => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") sendAssistantMessage("summary"); });
  $("#assistantInsertFeedback").addEventListener("click", insertAssistantFeedback);
  $("#summaryAssistantInsertFeedback").addEventListener("click", insertAssistantFeedback);
  $("#assistantCopy").addEventListener("click", copyAssistantPrompt);
  $("#assistantSubmitFeedback").addEventListener("click", submitAssistantFeedback);
  $("#summaryAssistantSubmitFeedback").addEventListener("click", submitAssistantFeedback);
  $("#assistantQueueTask").addEventListener("click", queueAssistantTask);
  $("#inlineResume").addEventListener("click", () => submitInlineFeedback());
  $("#inlineTakeover").addEventListener("click", () => runAction("takeover"));
  $("#newInboxButton").addEventListener("click", () => $("#inboxDialog").showModal());
  $("#inboxForm").addEventListener("submit", async (event) => { if (event.submitter?.value === "cancel") return; event.preventDefault(); const data = new FormData(event.currentTarget); const project = projectById(data.get("project_id")); await api("/api/inbox", {method: "POST", body: JSON.stringify({title: data.get("title"), task: data.get("task"), project_id: project?.id || "", project_path: project?.path || ""})}); $("#inboxDialog").close(); event.currentTarget.reset(); await refreshInbox(); });
  [$("#addProjectButton"), $("#manageAddProjectButton")].forEach((button) => button?.addEventListener("click", () => $("#projectDialog").showModal()));
  $("#projectForm").addEventListener("submit", async (event) => { if (event.submitter?.value === "cancel") return; event.preventDefault(); const data = new FormData(event.currentTarget); try { const registered = await api("/api/projects", {method: "POST", body: JSON.stringify({path: data.get("path"), name: data.get("name"), tags: String(data.get("tags") || "").split(",").map((tag) => tag.trim()).filter(Boolean)})}); $("#projectDialog").close(); event.currentTarget.reset(); await refreshProjects(); selectProject(registered.id); toast(`${projectName(registered)} is ready.`); } catch (error) { toast(error.message, true); } });
  $("#refreshSettings").addEventListener("click", () => refreshSettings().catch((error) => toast(error.message, true)));
  $("#settingsForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const submit = event.submitter;
    const originalLabel = submit.textContent;
    const data = new FormData(form);
    const payload = {
      max_parallel: Number(data.get("max_parallel")),
      max_retries: Number(data.get("max_retries")),
      default_lane: data.get("default_lane"),
      planner_lane: data.get("planner_lane"),
      review_lane: data.get("review_lane"),
      budgets: {
        timeout_seconds: Number(data.get("timeout_seconds")),
        stall_seconds: Number(data.get("stall_seconds")),
        max_tokens: Number(data.get("max_tokens")),
        max_tool_calls: Number(data.get("max_tool_calls")),
        max_cost_usd: Number(data.get("max_cost_usd")),
      },
      ci: {
        watch: data.get("ci_watch") === "on",
        auto_resume: data.get("ci_auto_resume") === "on",
        max_attempts: Number(data.get("ci_max_attempts")),
        poll_seconds: Number(data.get("ci_poll_seconds")),
      },
      resource_retention_days: Number(data.get("resource_retention_days")),
    };
    try {
      setFormSubmitting(form, true, submit, "Saving...");
      state.config = await api("/api/config", {method: "POST", body: JSON.stringify(payload)});
      toast("Settings saved.");
      await refreshSettings();
    } catch (error) { toast(error.message, true); }
    finally { setFormSubmitting(form, false, submit, originalLabel); }
  });
  $$("[data-reclaim-resources]").forEach((button) => button.addEventListener("click", async () => {
    const force = button.dataset.reclaimResources === "force";
    const approved = await confirmChoice({
      eyebrow: "RECLAIM RESOURCES",
      title: force ? "Reclaim all eligible terminal resources?" : "Reclaim expired resources now?",
      lead: "Task branches are preserved.",
      message: force ? "Odysseus will remove worktree and runtime directories for delivered or cancelled runs even if the retention window has not expired." : "Odysseus will remove only resources already past the configured retention window.",
      confirmLabel: "Reclaim now",
    });
    if (!approved) return;
    const originalLabel = button.textContent;
    try {
      button.disabled = true;
      button.textContent = "Reclaiming...";
      const retention = Number($("#settingsForm").elements.resource_retention_days.value || 14);
      const result = await api("/api/resources/reclaim", {method: "POST", body: JSON.stringify({retention_days: retention, force})});
      toast(`Reclaimed ${formatBytes(result.reclaimed_bytes)}.`);
      state.resources = await api("/api/resources");
      renderResources();
    } catch (error) { toast(error.message, true); }
    finally { button.disabled = false; button.textContent = originalLabel; }
  }));
  $("#assistantSettingsForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const submit = event.submitter;
    const originalLabel = submit.textContent;
    const data = new FormData(form);
    try {
      setFormSubmitting(form, true, submit, "Saving...");
      await api("/api/config", {method: "POST", body: JSON.stringify({assistant_models: {
        openai: String(data.get("openai_model") || "").trim(),
        anthropic: String(data.get("anthropic_model") || "").trim(),
      }})});
      toast("Assistant models saved. API keys remain outside Odysseus.");
      await refreshSettings();
    } catch (error) { toast(error.message, true); }
    finally { setFormSubmitting(form, false, submit, originalLabel); }
  });
}

async function init() {
  try {
    state.bootstrap = await api("/api/bootstrap"); $("#parallelLabel").textContent = `${state.bootstrap.max_parallel} slots`; const laneOptions = state.bootstrap.lanes.map((lane) => `<option value="${escapeHtml(lane)}">${escapeHtml(lane)}</option>`).join(""); $("#laneSelect").innerHTML = laneOptions; $("#plannerLaneSelect").innerHTML = laneOptions; $("#epicLaneSelect").innerHTML = laneOptions; $("#epicReviewLaneSelect").innerHTML = laneOptions; $("#resumeLaneSelect").innerHTML = laneOptions; $("#settingsDefaultLane").innerHTML = laneOptions; $("#settingsPlannerLane").innerHTML = laneOptions; $("#settingsReviewLane").innerHTML = laneOptions;
    [["docker", "Docker is not installed"], ["devcontainer", "Dev Container CLI is not installed"]].forEach(([profile, message]) => { const option = $("#environmentProfile").querySelector(`option[value="${profile}"]`); if (option && !state.bootstrap.capabilities?.[profile]) { option.disabled = true; option.textContent += ` — unavailable`; option.title = message; } });
    bindDialogs();
    syncThemeButton();
    initSidebarResize();
    $("#themeToggle").addEventListener("click", toggleTheme);
    $$(".nav-button").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view))); $$('[data-open-view]').forEach((button) => button.addEventListener("click", () => setView(button.dataset.openView)));
    $$(".filter").forEach((button) => button.addEventListener("click", () => { state.filter = button.dataset.filter; $$(".filter").forEach((item) => item.classList.toggle("active", item === button)); renderRuns(); }));
    $$(".tab").forEach((button) => button.addEventListener("click", () => activateTab(button.dataset.tab)));
    $$(".task-section-tab").forEach((button) => button.addEventListener("click", () => activateTaskSection(button.dataset.section)));
    $("#allWorkButton").addEventListener("click", () => selectProject("all")); $("#sidebarAttentionButton").addEventListener("click", () => setView("attention")); $("#backToProject").addEventListener("click", () => selectProject(state.selected?.project_id || state.projectFilter));
    $("#parallelLabel").addEventListener("click", () => setView("settings"));
    $(".brand").addEventListener("click", (event) => { event.preventDefault(); selectProject("all"); });
    $("#projectFilter").addEventListener("change", (event) => selectProject(event.target.value)); $("#sessionScope").addEventListener("change", (event) => { state.sessionScope = event.target.value; renderSessions(); }); $("#refreshSessions").addEventListener("click", refreshSessions); $("#refreshAttention").addEventListener("click", refreshAttention); $("#refreshInsights").addEventListener("click", refreshInsights); $("#loadIssues").addEventListener("click", loadIssues); $("#runSearch").addEventListener("click", () => runSearch()); $("#insightSearch").addEventListener("keydown", (event) => { if (event.key === "Enter") runSearch(); }); $("#globalSearch").addEventListener("keydown", (event) => { if (event.key === "Enter") runSearch(event.currentTarget.value); });
    document.addEventListener("keydown", (event) => { if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); $("#globalSearch").focus(); } });
    await Promise.all([refreshProjects(), refreshSessions(), refreshInbox(), refreshAttention(), refreshEpics()]); await refreshRuns();
    const params = new URLSearchParams(location.search);
    const match = decodeURIComponent(location.hash.slice(1)).match(/^task\/(.+)$/); if (match && state.runs.some((run) => run.id === match[1])) await selectRun(match[1]);
    else { const projectMatch = decodeURIComponent(location.hash.slice(1)).match(/^project\/(.+)$/); if (projectMatch && projectById(projectMatch[1])) selectProject(projectMatch[1]); else { const requestedView = params.get("view"); if (["work", "attention", "epics", "tasks", "sessions", "inbox", "projects", "insights", "github", "settings"].includes(requestedView)) { if (requestedView === "tasks" && state.runs.length) await selectRun(state.runs[0].id); else setView(requestedView); } else setView("work"); } }
    const requestedSection = params.get("section"); if (["summary", "changes", "activity", "evidence"].includes(requestedSection)) activateTaskSection(requestedSection);
    const requestedTab = params.get("tab"); if (["diff", "integration", "checks", "context", "review", "evaluation", "ci"].includes(requestedTab)) activateTab(requestedTab);
    const requestedDialog = params.get("dialog"); if (requestedDialog === "task") { $("#taskPrompt").value = params.get("prompt") || ""; $("#newTaskButton").click(); scheduleTaskSkillRecommendations(); } else if (requestedDialog === "epic") $("#newEpicButton").click();
    setConnection(true);
    if (params.get("browser-regression") === "1" && state.bootstrap?.test_capabilities?.browser_regression === true) runBrowserRegression().catch((error) => {
      const node = document.createElement("pre");
      node.id = "browserRegressionResult";
      node.textContent = `FAIL ${error.message}`;
      document.body.appendChild(node);
      api("/api/inbox", {method: "POST", body: JSON.stringify({title: "FAIL browser regression", task: error.message})}).catch(() => {});
    });
    window.setInterval(() => refreshRuns().catch(() => setConnection(false)), 3000);
    window.setInterval(() => Promise.all([refreshSessions(), refreshInbox(), refreshAttention(), refreshEpics()]).catch(() => setConnection(false)), 6000);
  } catch (error) { setConnection(false); toast(error.message, true); }
}

async function runBrowserRegression() {
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const sleep = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));
  assert($("#workDescription").textContent.includes("Choose where") || $("#workDescription").textContent.includes("task"), "repository default summary is concise");
  assert($('[data-journey-step="3"] strong')?.textContent === "Review", "first-run journey uses short review label");
  assert($("#sidebarResizer")?.getAttribute("aria-label") === "Resize repository sidebar", "sidebar resize handle accessible name");
  setSidebarWidth(DEFAULT_SIDEBAR_WIDTH);
  assert(getComputedStyle(document.documentElement).getPropertyValue("--sidebar-width").trim() === `${DEFAULT_SIDEBAR_WIDTH}px`, "default sidebar width");
  setSidebarWidth(460);
  assert($("#sidebarResizer").getAttribute("aria-valuenow") === "460", "widened sidebar value");
  setSidebarWidth(430);
  assert(window.localStorage.getItem(SIDEBAR_WIDTH_KEY) === "430", "persisted sidebar width");
  resetSidebarWidth();
  assert($("#sidebarResizer").getAttribute("aria-valuenow") === String(DEFAULT_SIDEBAR_WIDTH), "reset sidebar width");
  const narrow = window.matchMedia("(max-width: 760px)").matches;
  assert(!narrow || getComputedStyle($("#sidebarResizer")).display === "none", "mobile resize handle hidden");

  const accepted = state.runs.filter((run) => run.status === "accepted");
  const acceptedNotApplied = accepted.find((run) => run.delivery?.status === "not_applied" || !run.delivery?.status);
  assert(accepted.length >= 3, "accepted artifacts available");
  const running = state.runs.find((run) => run.status === "running");
  assert(running, "running task available");
  await selectRun(running.id);
  assert($("#narrativeTitle").textContent === "Agent is working", "running task uses one-line progress");
  assert($("#narrativeCopy").textContent === "Progress appears in Activity.", "running task avoids essay");
  assert($("#summaryAssistant").classList.contains("hidden"), "assistant hidden when no decision is needed");
  const blocked = state.runs.find((run) => run.status === "blocked");
  assert(blocked, "blocked task available");
  await selectRun(blocked.id);
  assert($("#narrativeTitle").textContent.includes("backend") || $("#narrativeTitle").textContent.includes("predecessor"), "blocked prerequisite named");
  const review = state.runs.find((run) => run.status === "review");
  assert(review, "review task available");
  await selectRun(review.id);
  assert($("#reviewDecisionCard").textContent.includes("Review result"), "review decision leads task detail");
  assert($("#runNarrative").classList.contains("hidden"), "review avoids duplicate narrative status");
  assert($("#reviewDecisionCard").textContent.includes("Cost") && $("#reviewDecisionCard").textContent.includes("Unknown"), "unknown cost remains explicit");
  assert($$("#reviewDecisionCard .delivery-decision .primary").length === 1, "review exposes one visible primary action");
  assert(!$("#summaryAssistant").classList.contains("hidden"), "assistant available on decision states");
  assert(acceptedNotApplied, "accepted not-applied artifact available");
  await selectRun(acceptedNotApplied.id);
  assert($("#reviewDecisionCard").textContent.includes("Checks"), "decision evidence visible");
  assert($("#reviewDecisionCard").textContent.includes("Saved artifact, not applied"), "accepted-not-applied is plain");
  assert($("#runNarrative").classList.contains("hidden"), "accepted avoids duplicate narrative status");
  assert($$("#reviewDecisionCard .delivery-decision .primary").length <= 1, "accepted delivery has at most one primary CTA");
  for (const [title, action] of [
    ["CI not started", "Poll CI."],
    ["CI pending", "Wait for CI."],
    ["CI running", "Wait for CI."],
    ["CI failed", "Repair failed CI."],
    ["CI exhausted", "Resume CI repair."],
    ["CI passed", "No action needed."],
  ]) {
    const prRun = state.runs.find((run) => run.title === title);
    assert(prRun, `${title} task available`);
    await selectRun(prRun.id);
    const renderedAction = $("#reviewDecisionCard .review-decision-head span").textContent;
    assert(renderedAction === action, `${title} next action: ${renderedAction}`);
  }
  await selectRun(acceptedNotApplied.id);
  await openIntegrationDialog(document.createElement("button"));
  const form = $("#integrationForm");
  const cards = $$(".integration-candidate");
  assert(cards.length >= 3, "integration candidates visible");
  assert($("#integrationDialog").textContent.includes("Choose each artifact"), "integration dialog is concise");
  cards.forEach((card, index) => {
    const id = card.dataset.candidateId;
    const value = index === 0 ? "supersede" : index < 3 ? "integrate_now" : "keep_for_later";
    form.elements[`disposition-${id}`].value = value;
    form.elements[`reason-${id}`].value = value === "supersede" ? "browser regression stale artifact" : "";
  });
  await submitIntegrationDisposition({preventDefault() {}, currentTarget: form, submitter: form.querySelector('button[value="default"]')});
  assert(!$("#integrationDialog").open, "integration dialog closed");
  await sleep(50);
  await refreshRuns();
  const queued = state.runs.find((run) => run.task_key === "integration-delivery");
  assert(queued, "integration delivery queued");

  await refreshAttention();
  const conflict = state.attention.find((item) => item.type === "merge_conflict");
  if (conflict) {
    assert($("#attentionList").textContent.includes("Conflicting files"), "conflict card shows files");
    assert($("#attentionList").textContent.includes("Prerequisite: resolve listed files."), "conflict card names prerequisite");
    openAttentionResponseDialog(conflict.id);
    assert($("#attentionResponseDialog").open, "native attention dialog opens");
    $("#attentionResponseDialog").close();
  }
  setView("attention");
  assert($("#attentionView").textContent.includes("Answer these to continue work."), "Needs You concise header");
  setView("epics");
  assert($("#epicsView").textContent.includes("Approve a graph before agents start."), "Plans concise header");
  setView("inbox");
  assert($("#inboxView").textContent.includes("Park work; queue explicitly."), "Follow-ups concise header");
  setView("settings");
  assert($("#settingsView").textContent.includes("Capacity, agents, CI, resources, assistants."), "Settings concise header");
  assert($("#settingsView").textContent.includes("API keys are never saved."), "settings security detail preserved");
  assert($$("#settingsView .primary").length === 1, "Settings exposes one primary action");
  document.documentElement.dataset.theme = "dark";
  syncThemeButton();
  assert($("#themeToggle").getAttribute("aria-label") === "Switch to light theme", "dark theme toggle accessible state");
  document.documentElement.dataset.theme = "light";
  syncThemeButton();
  assert($("#themeToggle").getAttribute("aria-label") === "Switch to dark theme", "light theme toggle accessible state");

  const delivered = state.runs.find((run) => run.delivery?.status === "integrated_applied");
  if (delivered) {
    const fullDelivered = await api(`/api/runs/${encodeURIComponent(delivered.id)}`);
    assert(fullDelivered.delivery?.integration_run_id, "source delivery provenance fanout");
  }
  const deliveredPr = state.runs.find((run) => run.delivery?.status === "integrated_pr_created");
  assert(deliveredPr, "integrated PR delivery source available");
  await selectRun(deliveredPr.id);
  assert($("#reviewDecisionCard .review-decision-head strong").textContent === "Delivered in integration PR", "integrated PR delivery has explicit title");
  assert($("#reviewDecisionCard .review-decision-head span").textContent === "Delivered in integration PR.", "integrated PR delivery action is explicit");
  assert($("#reviewDecisionCard").textContent.includes("integration-pr-existing"), "integrated PR delivery provenance visible");
  assert($("#reviewDecisionCard").textContent.includes("Open integration PR"), "integrated PR link visible");
  assert(!$("#reviewDecisionCard").textContent.includes("Apply to repository"), "integrated PR delivery hides apply action");
  assert(!$("#reviewDecisionCard").textContent.includes("Create draft PR"), "integrated PR delivery hides duplicate PR action");
  selectProject(state.projectFilter);
  assert($("#workView").classList.contains("active"), "navigation back to repository overview");
  await api("/api/inbox", {method: "POST", body: JSON.stringify({title: "PASS browser regression", task: "Browser regression completed."})});
  const node = document.createElement("pre");
  node.id = "browserRegressionResult";
  node.textContent = "PASS browser regression";
  document.body.appendChild(node);
}

window.addEventListener("beforeunload", closeStream);
init();
