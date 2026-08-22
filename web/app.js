"use strict";

const THEME_KEY = "odysseus-theme";
const SIDEBAR_WIDTH_KEY = "odysseus-sidebar-width-v3";
const DEFAULT_SIDEBAR_WIDTH = 320;
const MIN_SIDEBAR_WIDTH = 280;
const MAX_SIDEBAR_WIDTH = 520;
let savedTheme = "";
try { savedTheme = window.localStorage.getItem(THEME_KEY) || ""; } catch { savedTheme = ""; }
document.documentElement.dataset.theme = savedTheme === "dark" ? "dark" : "light";

const state = {
  bootstrap: null, runs: [], projects: [], sessions: [], inbox: [], attention: [], epics: [], portfolio: null, selectedId: null,
  selected: null, selectedDiff: null, selectedDiffRunId: "", selectedDiffLoadingRunId: "",
  events: [], eventsLoadedRunId: "", eventsLoadingRunId: "", eventVisibleLimit: 150,
  selectionGeneration: 0, filter: "active", projectFilter: "all", view: "portfolio",
  stream: null, streamRunId: "", refreshTimer: null, stats: null, searchResults: [], sessionScope: "repositories", taskSection: "summary",
  projectOverview: null, projectSkills: null, projectKnowledge: null, taskSkillCatalog: null, taskSkillRecommendations: null,
  taskAgentRecommendation: null, taskAgentTimer: null,
  skillsProjectId: "", skillsCatalog: null,
  assistantConversations: {}, config: null, resources: null, decisionDiff: null, decisionDiffRunId: "",
  assistantOpen: false, helpOpen: false, activityFocus: false, activityWide: true,
  selectedDecisionPaths: [],
  planSelectedSourcePaths: [], planRepositorySources: [], planUploadedSources: [], planGithubCatalog: [], planSelectedGithub: [], planUrlSources: [], planForcedSourcePaths: [],
  planSourceLoading: false, planGithubLoading: false, planSourceGeneration: 0, planSourceTab: "all", planFilter: "all", taskSourceFilter: "",
  planStudio: null, planStudioTaskKey: "", planStudioDirty: false, planStudioSourceFilter: "all", planStudioTaskSort: "plan",
  workListScope: "", workListExpanded: true, portfolioLoading: false,
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
  notApplied: "Approved change · not applied",
};

async function api(path, options = {}) {
  const headers = {"Content-Type": "application/json", ...(options.headers || {})};
  if (options.method && options.method !== "GET") {
    headers["X-Odysseus-Token"] = state.bootstrap.token;
    headers["Idempotency-Key"] ||= options.idempotencyKey || (globalThis.crypto?.randomUUID?.() || `web-${Date.now()}-${Math.random()}`);
    if (options.expectedVersion !== undefined && options.expectedVersion !== null) {
      headers["X-Odysseus-Expected-Version"] = String(options.expectedVersion);
    }
  }
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
function unknownNumber(value, formatter = (item) => String(item)) {
  return value === null || value === undefined || value === "" ? UI_COPY.unknown : formatter(value);
}
function money(value) { return unknownNumber(value, (item) => `$${Number(item).toFixed(4)}`); }
function compactMoney(value) {
  const amount = Number(value || 0);
  if (amount > 0 && amount < 0.01) return `$${amount.toFixed(4)}`;
  return `$${amount.toFixed(2)}`;
}
function formatDuration(seconds) {
  const value = Number(seconds);
  if (!Number.isFinite(value) || value < 0) return "—";
  if (value < 60) return `${Math.round(value)}s`;
  const minutes = Math.floor(value / 60);
  const remainingSeconds = Math.round(value % 60);
  if (minutes < 60) return remainingSeconds ? `${minutes}m ${remainingSeconds}s` : `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return remainingMinutes ? `${hours}h ${remainingMinutes}m` : `${hours}h`;
}
function runElapsedSeconds(run) {
  const start = new Date(run?.started_at || "").getTime();
  if (!Number.isFinite(start)) return null;
  const terminal = !activeStatuses.has(run?.status);
  const endValue = run?.finished_at || run?.artifact_created_at || (terminal ? run?.updated_at : "");
  const end = endValue ? new Date(endValue).getTime() : Date.now();
  return Number.isFinite(end) ? Math.max(0, (end - start) / 1000) : null;
}
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
  const labels = {queued: "waiting", waiting_variants: "running variants", review: "ready for review", accepted: "approved", decided: "decided", rejected: "rejected"};
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
  if (run?.status === "accepted" && delivery.status === "failed") return "Resolve the apply conflict.";
  if (run?.status === "accepted") return "Apply it to the repository or keep it for later.";
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
  const raw = String(run?.title || run?.task || fallback).replace(/\s+/g, " ").trim();
  if (!raw) return fallback;
  const withoutLead = raw
    .replace(/^(?:please|could you|can you|prosz[eę]|czy mo[zż]esz|jeszcze|zobacz)\s*[:,—-]?\s*/i, "")
    .replace(/^[-*#\s]+/, "")
    .trim();
  const sentence = withoutLead.split(/[.!?](?:\s|$)/)[0] || withoutLead;
  if (sentence.length <= 82) return sentence;
  const clipped = sentence.slice(0, 82).replace(/\s+\S*$/, "").replace(/[,:;\-–—\s]+$/, "");
  return `${clipped || sentence.slice(0, 78)}…`;
}

function evidenceStrength(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return {label: UI_COPY.unknown, tone: "unknown"};
  const score = Number(value);
  if (score >= 0.85) return {label: "Strong", tone: "strong"};
  if (score >= 0.65) return {label: "Moderate", tone: "moderate"};
  return {label: "Limited", tone: "limited"};
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
  if (view !== "tasks" && state.activityFocus) setActivityFocus(false, false);
  state.view = view;
  if (view !== "epics") $("#planSourceNav")?.classList.add("hidden");
  document.body.dataset.view = view;
  document.body.classList.toggle("task-open", view === "tasks");
  $$(".nav-button, .sidebar-primary-link, .explorer-tools [data-open-view]").forEach((button) => button.classList.toggle("active", button.dataset.view === view || button.dataset.openView === view));
  if (["inbox", "github", "projects", "settings"].includes(view)) $("#sidebarMore").open = true;
  $$(".view-panel").forEach((panel) => panel.classList.remove("active"));
  $(`#${view}View`)?.classList.add("active");
  const surfaceNames = {portfolio: "Home", work: "Repositories", attention: "Needs You", skills: "Skills", epics: "Plans", tasks: "Task", sessions: "Terminals", inbox: "Follow-ups", projects: "Manage repositories", insights: "Outcomes", github: "GitHub issues", settings: "Settings"};
  const project = activeProject();
  const scopedProject = ["work", "tasks", "epics", "github"].includes(view) ? project : null;
  $("#titleProject").textContent = scopedProject ? projectName(scopedProject) : "Odysseus";
  $("#titleSurface").textContent = surfaceNames[view] || "Overview";
  $("#allWorkButton").classList.toggle("selected", view === "work" && state.projectFilter === "all");
  if (view !== "tasks") closeStream();
  if (view === "tasks" && state.selectedId) openStream(state.selectedId);
  if (view === "tasks" && !state.selectedId && state.runs.length) selectRun(state.runs[0].id);
  if (view === "sessions") refreshSessions();
  if (view === "inbox") refreshInbox();
  if (view === "attention") refreshAttention();
  if (view === "skills") refreshSkillsPage();
  if (view === "epics") refreshEpics();
  if (view === "settings") refreshSettings();
  if (view === "github" && project && [...$("#githubProject").options].some((option) => option.value === project.id)) $("#githubProject").value = project.id;
  if (view === "insights") { renderPortfolioPreview(); refreshPortfolio(); refreshInsights(); }
  if (view === "portfolio") renderHome();
  if (view === "work") renderWork();
  updateGitHubLink();
  if (state.helpOpen) renderHelpPanel();
}

function helpForCurrentView() {
  const project = activeProject();
  const run = state.selected;
  const general = {
    portfolio: {
      title: "Start here",
      intro: "Create one clear piece of engineering work. Odysseus chooses the agent, isolates the repository, runs checks, and brings the result back for review.",
      next: "Write what should change, choose a repository, then press Start task.",
      steps: [["1", "Describe the outcome", "Say what must change and what must stay unchanged.", "blue"], ["2", "Choose the repository", "Odysseus already knows its folder on this machine.", "violet"], ["3", "Review only when asked", "Needs You collects decisions that require a person.", "green"]],
    },
    work: {
      title: project ? `Repository: ${projectName(project)}` : "Your repositories",
      intro: project ? "This is the repository overview: what the codebase is, what has been done, and which tasks are active." : "Repositories are local Git folders registered with Odysseus. Adding one does not move or upload its code.",
      next: project ? "Start a task here, or open a task in the left sidebar to inspect its state." : "Choose a repository on the left, or add a local Git folder with +.",
      steps: [["R", "Repository", "The source checkout Odysseus protects.", "blue"], ["●", "Tasks", "Each task runs in its own branch and worktree.", "violet"], ["✓", "Delivery", "Approved work is still separate until you apply it or create a PR.", "green"]],
    },
    attention: {
      title: "Needs You",
      intro: "This is the human decision queue. Events from the same task are grouped so you can resolve work, not notifications.",
      next: "Open the highest-priority task, read the requested decision, and answer or review it.",
      steps: [["!", "High", "A blocked or risky task needs a decision now.", "red"], ["?", "Question", "The agent needs one clear answer to continue.", "amber"], ["✓", "Review", "Changes and evidence are ready for your decision.", "green"]],
    },
    epics: {
      title: "Plans",
      intro: "Plans turn a larger outcome into a dependency-aware task graph. Agents do not start until you approve the proposed graph.",
      next: "Open a proposed plan, verify its tasks and dependencies, then approve it.",
      steps: [["1", "Requirement", "Describe the finished outcome and constraints.", "blue"], ["2", "Task graph", "The planner separates parallel work and dependencies.", "violet"], ["3", "Approval", "You decide whether execution may begin.", "green"]],
    },
    insights: {
      title: "Outcomes",
      intro: "This page measures delivered engineering work—not agent activity. Unknown cost remains unknown, and percentages include their sample size.",
      next: "Start with delivered changes, human interventions, and failure attribution. Open a row only when you need the evidence behind it.",
      steps: [["✓", "Delivered", "The change reached its recorded delivery target.", "green"], ["$", "Economics", "Tokens, observed cost, retries, and human attention.", "blue"], ["!", "Failures", "Where work stopped and whether it recovered.", "red"]],
    },
    skills: {title: "Skills", intro: "Skills are reusable engineering procedures, such as security review or database migration guidance. They are not project-specific memory.", next: "Inspect a skill, then enable it for repositories where that procedure should be available.", steps: [["◆", "Procedure", "Instructions and evidence requirements for an agent.", "violet"], ["A", "Auto selection", "Odysseus can attach relevant skills to a task.", "blue"], ["N", "Evidence", "Performance is meaningful only together with sample size.", "green"]]},
    sessions: {title: "Agent terminals", intro: "Odysseus discovers Codex and Claude panes already running in tmux. Discovery does not take control of them.", next: "Track a terminal if you want a durable shortcut; use the copied tmux command to continue in your terminal.", steps: [["1", "See", "Detected panes appear automatically.", "blue"], ["2", "Track", "Create a durable task entry without moving the session.", "violet"], ["3", "Open", "Continue in the original terminal.", "green"]]},
    inbox: {title: "Follow-ups", intro: "Inbox holds ideas that should not start yet. It is a parking place, not the execution queue.", next: "Add a follow-up, then explicitly turn it into a task when you are ready.", steps: [["+", "Capture", "Save the idea without starting an agent.", "blue"], ["→", "Queue", "Convert it into executable work deliberately.", "green"]]},
    projects: {title: "Manage repositories", intro: "These are local Git checkouts known to Odysseus. Removing one from the list never deletes its folder or files.", next: "Add a repository by entering its absolute local folder path.", steps: [["+", "Add", "Register an existing local Git checkout.", "blue"], ["×", "Remove", "Forget the registration; leave source files untouched.", "amber"]]},
    settings: {title: "Settings", intro: "Global defaults control capacity, agents, CI, retained resources, and the optional Decision Assistant. Advanced controls stay folded until needed.", next: "Change only the setting you need, then save that section.", steps: [["A", "Execution", "Default agent, concurrent running tasks, retries, and budgets.", "blue"], ["⌁", "Resources", "Retention and cleanup for worktrees and runtimes.", "violet"], ["?", "Assistant", "Optional models; API keys are read from the server environment and are not saved here.", "green"]]},
    github: {title: "GitHub issues", intro: "Turn an open GitHub issue into a proposed plan. This screen does not start implementation immediately.", next: "Choose a repository, load issues, then select one to create a plan proposal.", steps: [["#", "Issue", "The original requirement from GitHub.", "blue"], ["◇", "Plan", "A proposed task graph for your approval.", "violet"], ["✓", "Run", "Agents start only after approval.", "green"]]},
  };
  if (state.view !== "tasks") return general[state.view] || general.portfolio;
  const sectionCopy = {
    summary: "Overview answers whether you need to act and what happens next.",
    changes: "Changes shows the exact diff from the isolated task worktree.",
    activity: "Activity is the detailed event stream for debugging and progress.",
    evidence: "Evidence contains checks, context, independent review, evaluation, and CI.",
  };
  const hasQuestion = run && relevantAttentionItems(state.attention).some((item) => item.run_id === run.id && item.type === "question");
  const statusCopy = !run ? ["Choose a task", "Select a task from the repository sidebar.", "blue"]
    : hasQuestion ? ["Answer the question", "The agent needs one clear answer before it can continue.", "blue"]
    : ["review", "attention"].includes(run.status) ? ["Review the decision", "Inspect Changes and Evidence, then approve or send precise feedback.", "red"]
    : ["failed", "blocked"].includes(run.status) ? ["Resolve the blocker", "Read the reason shown at the top. Resume with guidance or continue in the preserved terminal.", "red"]
    : ["accepted", "pr_created"].includes(run.status) ? ["Choose delivery", "Approval preserves the result. Apply it to the repository or deliver it through a PR.", "green"]
    : activeStatuses.has(run.status) ? ["No action needed", "The agent is working. Return when this task appears in Needs You.", "amber"]
    : ["Inspect the current state", "Use the primary action at the top of the task.", "violet"];
  return {
    title: run ? `Task: ${run.title}` : "Task",
    intro: sectionCopy[state.taskSection] || sectionCopy.summary,
    next: statusCopy[1],
    steps: [["1", "Overview", "Decision and next action.", statusCopy[2]], ["2", "Changes", "Files and exact diff.", "violet"], ["3", "Evidence", "Checks, review, and CI proof.", "green"]],
    current: statusCopy[0],
  };
}

function renderHelpPanel() {
  const help = helpForCurrentView();
  $("#helpTitle").textContent = help.title;
  $("#helpContent").innerHTML = `
    <section class="help-callout"><strong><span aria-hidden="true">ⓘ</span> What is this?</strong><p>${escapeHtml(help.intro)}</p></section>
    <section class="help-next"><small>${help.current ? "CURRENT STATE" : "WHAT TO DO NOW"}</small><strong>${escapeHtml(help.current || "Next step")}</strong><p>${escapeHtml(help.next)}</p></section>
    <section class="help-guide"><small>HOW TO READ THIS SCREEN</small>${help.steps.map(([mark, title, copy, tone]) => `<div class="help-step tone-${tone}"><span>${escapeHtml(mark)}</span><div><strong>${escapeHtml(title)}</strong><p>${escapeHtml(copy)}</p></div></div>`).join("")}</section>
    <section class="help-status-legend" aria-label="Task status colors"><small>TASK COLORS</small><span><i class="status-done"></i>Done</span><span><i class="status-in-progress"></i>Working</span><span><i class="status-question"></i>Question</span><span><i class="status-needs-action"></i>Needs you</span></section>
    <p class="help-foot">Help follows the screen you are viewing. It never starts, changes, or approves work.</p>`;
}

function toggleHelp(force) {
  state.helpOpen = typeof force === "boolean" ? force : !state.helpOpen;
  document.body.classList.toggle("help-open", state.helpOpen);
  $("#helpPanel").setAttribute("aria-hidden", String(!state.helpOpen));
  $("#helpToggle").setAttribute("aria-expanded", String(state.helpOpen));
  $("#helpToggle").classList.toggle("active", state.helpOpen);
  if (state.helpOpen) renderHelpPanel();
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
  if (name === "activity") setActivityFocus(state.activityWide, false);
  else if (state.activityFocus) setActivityFocus(false, false);
  $$(".task-section-tab").forEach((item) => item.classList.toggle("active", item.dataset.section === name));
  $$(".task-section-pane").forEach((pane) => pane.classList.toggle("active", pane.id === `task-section-${name}`));
  renderVisibleHeavyPanels().catch((error) => toast(error.message, true));
  if (state.helpOpen) renderHelpPanel();
}

function setActivityFocus(enabled, remember = true) {
  if (remember) state.activityWide = Boolean(enabled);
  state.activityFocus = Boolean(enabled && state.view === "tasks" && state.taskSection === "activity");
  document.body.classList.toggle("activity-focus", state.activityFocus);
  const button = $("#activityFocusToggle");
  if (!button) return;
  button.setAttribute("aria-pressed", String(state.activityFocus));
  button.setAttribute("aria-label", state.activityFocus ? "Narrow Activity" : "Expand Activity to the full workspace width");
  button.title = state.activityFocus ? "Narrow Activity (Esc)" : "Expand Activity to the full workspace width";
  button.innerHTML = state.activityFocus ? 'Narrow <span aria-hidden="true">⤡</span>' : 'Expand <span aria-hidden="true">⤢</span>';
}

function filteredRuns() {
  let runs = state.runs;
  if (state.projectFilter !== "all") runs = runs.filter((run) => run.project_id === state.projectFilter);
  if (state.taskSourceFilter) runs = runs.filter((run) => (run.source_paths || []).includes(state.taskSourceFilter));
  return runs.filter((run) => runMatchesFilter(run, state.filter));
}

function runMatchesFilter(run, filter = state.filter) {
  if (filter === "all") return true;
  if (filter === "active") return activeStatuses.has(run.status);
  if (filter === "review") return ["attention", "blocked", "review", "failed", "accepted"].includes(run.status);
  const tone = taskDotTone(run);
  if (filter === "working") return tone === "status-in-progress";
  if (filter === "question") return tone === "status-question";
  if (filter === "needs") return tone === "status-needs-action";
  if (filter === "done") return tone === "status-done";
  return true;
}

function runsForProject(projectId) { return state.runs.filter((run) => run.project_id === projectId); }
function attentionForProject(projectId) { return state.attention.filter((item) => item.project_id === projectId); }
function groupAttention(items = state.attention) {
  const groups = new Map();
  const priorityRank = {critical: 4, high: 3, medium: 2, low: 1};
  items.forEach((item) => {
    const key = item.run_id ? `run:${item.run_id}` : `item:${item.id}`;
    if (!groups.has(key)) groups.set(key, {key, run_id: item.run_id || "", project_id: item.project_id || "", priority: item.priority || "medium", items: []});
    const group = groups.get(key);
    group.items.push(item);
    if ((priorityRank[item.priority] || 0) > (priorityRank[group.priority] || 0)) group.priority = item.priority;
  });
  return [...groups.values()].sort((left, right) => {
    const priority = (priorityRank[right.priority] || 0) - (priorityRank[left.priority] || 0);
    if (priority) return priority;
    return String(right.items[0]?.created_at || "").localeCompare(String(left.items[0]?.created_at || ""));
  });
}
function attentionTaskCount(items = state.attention) { return groupAttention(items).length; }
function relevantAttentionItems(items) {
  const staleAtReview = new Set(["question", "permission_request", "blocked", "decision_required", "stalled", "budget"]);
  const finished = new Set(["accepted", "pr_created", "completed", "cancelled", "rejected"]);
  return items.filter((item) => {
    const run = item.run_id ? state.runs.find((candidate) => candidate.id === item.run_id) : null;
    if (!run) return true;
    if (finished.has(run.status)) return false;
    if (run.status === "review" && staleAtReview.has(item.type)) return false;
    return true;
  });
}
function agentLaneOptions(selected = "", includeAuto = false) {
  const automatic = includeAuto ? `<option value="auto" ${selected === "auto" ? "selected" : ""}>Auto — recommended</option>` : "";
  const manual = (state.bootstrap?.lanes || []).map((lane) => `<option value="${escapeHtml(lane)}" ${lane === selected ? "selected" : ""}>${escapeHtml(lane)}</option>`).join("");
  return automatic + manual;
}
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
  $("#sidebarSessionCount").textContent = count || "";
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
  $("#sidebarPrimaryAttentionCount").textContent = attentionTaskCount() || "";
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
  const nextProject = projectId && projectById(projectId) ? projectId : "all";
  if (nextProject !== state.projectFilter) { state.planFilter = "all"; state.taskSourceFilter = ""; }
  state.projectFilter = nextProject;
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

function renderTaskAgentRecommendation() {
  const node = $("#taskAgentReason");
  if (!node) return;
  const choice = $("#laneSelect").value;
  if (choice !== "auto") {
    node.innerHTML = `<strong>${escapeHtml(choice)}</strong> is manually selected. Auto routing is off for this task.`;
    return;
  }
  const recommendation = state.taskAgentRecommendation;
  const fallback = state.bootstrap?.default_lane || "codex";
  if (!recommendation) {
    node.innerHTML = `<strong>Auto is recommended.</strong> Sparse history falls back to ${escapeHtml(fallback)}.`;
    return;
  }
  const lane = recommendation.recommended_lane || fallback;
  const evidence = (recommendation.evidence || []).find((item) => item.agent === lane);
  const samples = Number(evidence?.samples || 0);
  const eligible = !["disabled", "insufficient_samples"].includes(recommendation.reason);
  node.innerHTML = eligible
    ? `<strong>${escapeHtml(lane)} selected.</strong> Best historical fit from ${escapeHtml(samples)} comparable outcome${samples === 1 ? "" : "s"}; the routing decision will be recorded.`
    : `<strong>${escapeHtml(fallback)} fallback.</strong> Not enough comparable outcomes yet; Odysseus records this choice and learns from delivery.`;
}

function scheduleTaskAgentRecommendation() {
  window.clearTimeout(state.taskAgentTimer);
  state.taskAgentTimer = window.setTimeout(() => refreshTaskAgentRecommendation().catch((error) => {
    state.taskAgentRecommendation = null;
    renderTaskAgentRecommendation();
    toast(error.message, true);
  }), 300);
}

async function refreshTaskAgentRecommendation() {
  const projectId = $("#taskProjectSelect").value;
  const task = $("#taskPrompt").value.trim();
  if ($("#laneSelect").value !== "auto" || !projectId || task.length < 4) {
    state.taskAgentRecommendation = null;
    renderTaskAgentRecommendation();
    return;
  }
  const expected = `${projectId}\n${task}`;
  const recommendation = await api(`/api/projects/${encodeURIComponent(projectId)}/router/recommend`, {
    method: "POST",
    body: JSON.stringify({task, operator_default: state.bootstrap.default_lane, role: "implementer", origin: "web"}),
  });
  if (`${$("#taskProjectSelect").value}\n${$("#taskPrompt").value.trim()}` !== expected || $("#laneSelect").value !== "auto") return;
  state.taskAgentRecommendation = recommendation;
  renderTaskAgentRecommendation();
}

function renderSkillCatalog(catalog, listSelector, countSelector) {
  const skills = catalog?.skills || [];
  const projectId = catalog?.project_id || "";
  $(countSelector).textContent = `${skills.filter((skill) => skill.mode !== "disabled").length} enabled`;
  $(listSelector).innerHTML = skills.length ? skills.map((skill) => { const stats = skill.effectiveness || {}; const runs = Number(stats.runs || 0); const terminalRuns = Number(stats.terminal_runs || 0); const successes = stats.success_rate === null || stats.success_rate === undefined ? null : Math.round(Number(stats.success_rate) * terminalRuns); const outcome = runs ? `N=${runs}${successes === null ? " · awaiting terminal outcomes" : runs < 20 ? ` · ${successes}/${terminalRuns} observed successes · low sample` : ` · ${Math.round(Number(stats.success_rate) * 100)}% observed success`}` : "No repository history yet"; const averageCost = stats.avg_cost_usd === null || stats.avg_cost_usd === undefined ? "cost Unknown" : `$${Number(stats.avg_cost_usd).toFixed(4)} avg cost · coverage ${Number(stats.cost_coverage || 0)}/${runs}`; return `<details class="project-skill" data-skill="${escapeHtml(skill.name)}"><summary><span><strong>${escapeHtml(skill.name)}</strong><small>${escapeHtml(skill.description)}</small><em class="skill-effectiveness ${runs > 0 && runs < 20 ? "low-sample" : ""}">${escapeHtml(outcome)}</em></span><span class="skill-source">${escapeHtml(skill.scope)}</span><select class="skill-policy" data-skill-policy="${escapeHtml(skill.name)}" data-skill-project="${escapeHtml(projectId)}" aria-label="Policy for ${escapeHtml(skill.name)}"><option value="auto" ${skill.mode === "auto" ? "selected" : ""}>Auto</option><option value="required" ${skill.mode === "required" ? "selected" : ""}>Required</option><option value="disabled" ${skill.mode === "disabled" ? "selected" : ""}>Disabled</option></select></summary><div class="skill-preview"><div>${(skill.triggers || []).map((trigger) => `<span>${escapeHtml(trigger)}</span>`).join("")}</div>${stats.runs ? `<p class="skill-stats">Average ${compactNumber(stats.avg_tokens)} tokens · ${escapeHtml(averageCost)} · ${Number(stats.interventions || 0)} human interventions</p>` : ""}<pre>${escapeHtml(skill.preview || "No preview available.")}</pre></div></details>`; }).join("") : `<div class="empty-list">No valid SKILL.md files found.</div>`;
  $$(`${listSelector} [data-skill-policy]`).forEach((select) => {
    select.addEventListener("click", (event) => event.stopPropagation());
    select.addEventListener("change", async (event) => {
      const name = event.currentTarget.dataset.skillPolicy;
      const targetProjectId = event.currentTarget.dataset.skillProject;
      if (!targetProjectId) return;
      try {
        const nextCatalog = await api(`/api/projects/${encodeURIComponent(targetProjectId)}/skills`, {method: "POST", body: JSON.stringify({policies: {[name]: event.currentTarget.value}})});
        if (activeProject()?.id === targetProjectId) state.projectSkills = nextCatalog;
        if (state.skillsProjectId === targetProjectId) state.skillsCatalog = nextCatalog;
        renderProjectSkills();
        renderSkillsPage();
        toast(`${name} policy updated.`);
      } catch (error) { toast(error.message, true); }
    });
  });
}

function renderProjectSkills() {
  renderSkillCatalog(state.projectSkills, "#projectSkillList", "#projectSkillCount");
}

function renderSkillsPage() {
  const selected = state.skillsProjectId && projectById(state.skillsProjectId) ? state.skillsProjectId : preferredProjectId();
  state.skillsProjectId = selected || "";
  if ([...$("#skillsProjectSelect").options].some((option) => option.value === state.skillsProjectId)) $("#skillsProjectSelect").value = state.skillsProjectId;
  $("#addSkillButton").disabled = !state.skillsProjectId;
  if (!state.skillsProjectId) {
    $("#skillsPageCount").textContent = "0 enabled";
    $("#skillsPageList").innerHTML = `<div class="empty-card">Add a repository to manage skills.</div>`;
    return;
  }
  if (!state.skillsCatalog || state.skillsCatalog.project_id !== state.skillsProjectId) {
    $("#skillsPageCount").textContent = "Loading";
    $("#skillsPageList").innerHTML = `<div class="empty-card">Loading repository skills…</div>`;
    return;
  }
  renderSkillCatalog(state.skillsCatalog, "#skillsPageList", "#skillsPageCount");
}

async function refreshSkillsPage(projectId = "") {
  const selected = projectId || $("#skillsProjectSelect")?.value || state.skillsProjectId || preferredProjectId();
  state.skillsProjectId = selected && projectById(selected) ? selected : "";
  renderSkillsPage();
  if (!state.skillsProjectId) return;
  state.skillsCatalog = await api(`/api/projects/${encodeURIComponent(state.skillsProjectId)}/skills`);
  if (activeProject()?.id === state.skillsProjectId) state.projectSkills = state.skillsCatalog;
  renderSkillsPage();
  if (activeProject()?.id === state.skillsProjectId) renderProjectSkills();
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

const PLAN_SOURCE_KIND_LABELS = {
  adr: "ADR", specification: "Specification", github_issue: "GitHub issue", pull_request: "GitHub PR",
  security_finding: "Security", incident: "Incident", milestone: "Milestone", repository_document: "Repository document",
  document_set: "Document set", user_request: "User request", url: "Web document",
};

function planSourceKindLabel(kind) { return PLAN_SOURCE_KIND_LABELS[kind] || String(kind || "Source").replaceAll("_", " "); }
function planSourceGroup(kind) {
  if (kind === "adr") return "adr";
  if (["github_issue", "pull_request"].includes(kind)) return "github";
  if (kind === "specification") return "specification";
  if (["incident", "security_finding"].includes(kind)) return "incident";
  return "other";
}
function selectedEpicRepositorySources() {
  const selected = new Set(state.planSelectedSourcePaths);
  return state.planRepositorySources.filter((item) => selected.has(item.path));
}
function selectedEpicGithubSources() {
  const selected = new Set(state.planSelectedGithub);
  return state.planGithubCatalog.filter((item) => selected.has(`${item.kind}:${item.number}`));
}
function epicSourceCount(extra = 0) {
  return state.planSelectedSourcePaths.length + state.planUploadedSources.length + state.planSelectedGithub.length + state.planUrlSources.length + extra;
}
function epicSourceBytes(extra = []) {
  return [...selectedEpicRepositorySources(), ...state.planUploadedSources, ...state.planUrlSources, ...extra]
    .reduce((total, item) => total + Number(item.bytes || 0), 0);
}
async function sourceDigest(content) {
  if (!globalThis.crypto?.subtle) return `fallback:${content.length}:${content.slice(0, 64)}`;
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(content));
  return [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, "0")).join("");
}
function possibleSourceSecret(content) {
  return /(?:bearer\s+[A-Za-z0-9._~+\/-]{16,}|\b(?:sk|ghp|github_pat|xox[baprs])[-_A-Za-z0-9]{12,}\b|(?:api[_-]?key|token|secret)\s*[:=]\s*[^\s]{12,})/i.test(content);
}
function inferredUploadedKind(name) {
  const value = String(name || "").toLowerCase();
  if (value.includes("adr") || value.includes("decision")) return "adr";
  if (value.includes("incident") || value.includes("postmortem")) return "incident";
  if (value.includes("security") || value.includes("threat")) return "security_finding";
  if (value.includes("milestone") || value.includes("roadmap")) return "milestone";
  if (value.includes("prd") || value.includes("spec") || value.includes("requirement") || value.includes("rfc")) return "specification";
  return String($("#epicForm")?.elements.source_kind?.value || "repository_document");
}
function sourceKindOptions(selected) {
  return ["user_request", "adr", "specification", "security_finding", "incident", "milestone", "repository_document", "document_set"]
    .map((kind) => `<option value="${kind}" ${kind === selected ? "selected" : ""}>${escapeHtml(planSourceKindLabel(kind))}</option>`).join("");
}

function renderEpicSourcePicker() {
  const repositoryPanel = $("#epicRepositorySources");
  const selectedRepository = selectedEpicRepositorySources();
  const visibleRepository = state.planRepositorySources.filter((item) => state.planSourceTab === "all" || state.planSourceTab === planSourceGroup(item.kind) || state.planSourceTab === "repository" && planSourceGroup(item.kind) === "other");
  if (state.planSourceLoading) {
    repositoryPanel.innerHTML = `<p>Discovering ADRs, specifications and planning documents…</p>`;
  } else if (visibleRepository.length) {
    repositoryPanel.innerHTML = `<div class="epic-source-picker-heading"><strong>Repository documents</strong><small>${visibleRepository.length} shown · ${state.planRepositorySources.length} discovered</small></div><div class="epic-source-options">${visibleRepository.map((item) => {
      const completed = item.implementation?.state === "completed";
      const forced = state.planForcedSourcePaths.includes(item.path);
      const checked = state.planSelectedSourcePaths.includes(item.path);
      return `<article class="epic-source-option ${completed ? "implemented" : ""}"><label><input type="checkbox" data-epic-source-path="${escapeHtml(item.path)}" ${checked ? "checked" : ""} ${completed && !forced ? "disabled" : ""}><span><span class="source-kind-badge">${escapeHtml(planSourceKindLabel(item.kind))}</span><strong>${escapeHtml(item.title || item.path)}</strong><small>${escapeHtml(item.path)} · ${escapeHtml(String(item.sha256 || "").slice(0, 8))}</small><em>${escapeHtml(item.summary || "No preview available.")}</em></span></label><div class="epic-source-option-actions">${completed ? `<b>Implemented</b><button class="text-button" data-force-source="${escapeHtml(item.path)}" type="button">${forced ? "Cancel repeat" : "Force again"}</button>` : ""}<details><summary>Preview</summary><pre>${escapeHtml(item.preview || item.summary || "")}</pre></details></div></article>`;
    }).join("")}</div>`;
  } else {
    repositoryPanel.innerHTML = `<p>No repository documents match this category. Upload a file, choose GitHub, or add a public HTTPS source.</p>`;
  }

  const githubPanel = $("#epicGithubSources");
  const showGithub = ["all", "github"].includes(state.planSourceTab);
  githubPanel.classList.toggle("hidden", !showGithub);
  githubPanel.innerHTML = showGithub ? (state.planGithubLoading
    ? `<p>Loading GitHub issues and pull requests…</p>`
    : state.planGithubCatalog.length ? `<div class="epic-source-picker-heading"><strong>GitHub</strong><small>${state.planGithubCatalog.length} open sources</small></div><div class="epic-source-options">${state.planGithubCatalog.map((item) => { const key = `${item.kind}:${item.number}`; return `<label><input type="checkbox" data-epic-github-key="${escapeHtml(key)}" ${state.planSelectedGithub.includes(key) ? "checked" : ""}><span><span class="source-kind-badge">${escapeHtml(planSourceKindLabel(item.kind))}</span><strong>#${escapeHtml(item.number)} ${escapeHtml(item.title)}</strong><small>${escapeHtml(item.url || "GitHub")}</small></span></label>`; }).join("")}</div>`
    : `<p>Load open issues and pull requests from the repository's GitHub remote.</p>`) : "";

  const localPanel = $("#epicUploadedSources");
  const localSources = [...state.planUploadedSources.map((item, index) => ({...item, type: "upload", index})), ...state.planUrlSources.map((item, index) => ({...item, type: "url", index}))];
  localPanel.classList.toggle("hidden", !localSources.length);
  localPanel.innerHTML = localSources.map((item) => `<div><span><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(formatBytes(item.bytes))} · ${escapeHtml(item.type === "url" ? "public URL" : "uploaded")}</small><details><summary>Preview</summary><pre>${escapeHtml(item.preview || item.content?.slice(0, 2000) || "")}</pre></details></span>${item.type === "upload" ? `<select data-upload-source-kind="${item.index}" aria-label="Source type for ${escapeHtml(item.title)}">${sourceKindOptions(item.kind)}</select>` : `<span class="source-kind-badge">Web</span>`}<button class="icon-button" data-remove-epic-${item.type}="${item.index}" type="button" aria-label="Remove ${escapeHtml(item.title)}">×</button></div>`).join("");

  const selectedSources = [
    ...selectedRepository.map((item) => ({title: item.title || item.path, detail: `${planSourceKindLabel(item.kind)} · ${item.path}${state.planForcedSourcePaths.includes(item.path) ? " · forced repeat" : ""}`})),
    ...selectedEpicGithubSources().map((item) => ({title: `#${item.number} ${item.title}`, detail: planSourceKindLabel(item.kind)})),
    ...state.planUploadedSources.map((item) => ({title: item.title, detail: `${planSourceKindLabel(item.kind)} · uploaded`})),
    ...state.planUrlSources.map((item) => ({title: item.title, detail: "public HTTPS source"})),
  ];
  const sourcePanel = $("#epicDecisionSources");
  sourcePanel.classList.toggle("hidden", !selectedSources.length);
  sourcePanel.innerHTML = selectedSources.length ? `<small>SELECTED SOURCES</small><strong>${selectedSources.length} document${selectedSources.length === 1 ? "" : "s"} will be frozen into this plan version</strong><div>${selectedSources.map((item) => `<span>${escapeHtml(item.title)} <code>${escapeHtml(item.detail)}</code></span>`).join("")}</div>` : "";

  $$("[data-plan-source-tab]").forEach((button) => button.classList.toggle("active", button.dataset.planSourceTab === state.planSourceTab));
  $$('[data-epic-source-path]').forEach((input) => input.addEventListener("change", () => {
    const paths = new Set(state.planSelectedSourcePaths);
    if (input.checked) {
      if (epicSourceCount() >= 20) { input.checked = false; toast("Choose at most 20 planning documents.", true); return; }
      paths.add(input.dataset.epicSourcePath);
    } else paths.delete(input.dataset.epicSourcePath);
    state.planSelectedSourcePaths = [...paths]; renderEpicSourcePicker();
  }));
  $$('[data-force-source]').forEach((button) => button.addEventListener("click", () => {
    const path = button.dataset.forceSource; const forced = new Set(state.planForcedSourcePaths); const selected = new Set(state.planSelectedSourcePaths);
    if (forced.has(path)) { forced.delete(path); selected.delete(path); }
    else { if (epicSourceCount() >= 20) { toast("Choose at most 20 planning documents.", true); return; } forced.add(path); selected.add(path); }
    state.planForcedSourcePaths = [...forced]; state.planSelectedSourcePaths = [...selected]; renderEpicSourcePicker();
  }));
  $$('[data-epic-github-key]').forEach((input) => input.addEventListener("change", () => {
    const selected = new Set(state.planSelectedGithub);
    if (input.checked) { if (epicSourceCount() >= 20) { input.checked = false; toast("Choose at most 20 planning documents.", true); return; } selected.add(input.dataset.epicGithubKey); }
    else selected.delete(input.dataset.epicGithubKey);
    state.planSelectedGithub = [...selected]; renderEpicSourcePicker();
  }));
  $$('[data-upload-source-kind]').forEach((select) => select.addEventListener("change", () => { state.planUploadedSources[Number(select.dataset.uploadSourceKind)].kind = select.value; renderEpicSourcePicker(); }));
  $$('[data-remove-epic-upload]').forEach((button) => button.addEventListener("click", () => { state.planUploadedSources.splice(Number(button.dataset.removeEpicUpload), 1); renderEpicSourcePicker(); }));
  $$('[data-remove-epic-url]').forEach((button) => button.addEventListener("click", () => { state.planUrlSources.splice(Number(button.dataset.removeEpicUrl), 1); renderEpicSourcePicker(); }));
}

async function refreshEpicSourceChoices(projectId, {preserveSelection = false} = {}) {
  const generation = ++state.planSourceGeneration;
  if (!preserveSelection) { state.planSelectedSourcePaths = []; state.planForcedSourcePaths = []; }
  state.planRepositorySources = [];
  state.planGithubCatalog = []; state.planSelectedGithub = [];
  if (!projectId || !projectById(projectId)) { state.planSourceLoading = false; renderEpicSourcePicker(); return; }
  state.planSourceLoading = true; renderEpicSourcePicker();
  try {
    const payload = await api(`/api/projects/${encodeURIComponent(projectId)}/planning-sources`);
    if (generation !== state.planSourceGeneration) return;
    state.planRepositorySources = payload.sources || [];
    const known = new Set(state.planRepositorySources.map((item) => item.path));
    state.planSelectedSourcePaths = state.planSelectedSourcePaths.filter((path) => known.has(path));
    state.planForcedSourcePaths = state.planForcedSourcePaths.filter((path) => known.has(path));
  } catch (error) {
    if (generation === state.planSourceGeneration) toast(`Could not list planning documents: ${error.message}`, true);
  } finally {
    if (generation === state.planSourceGeneration) { state.planSourceLoading = false; renderEpicSourcePicker(); }
  }
}

async function loadEpicGithubSources() {
  const projectId = $("#epicProjectSelect").value;
  if (!projectId) { toast("Choose a repository first.", true); return; }
  state.planGithubLoading = true; state.planSourceTab = "github"; renderEpicSourcePicker();
  try {
    const [issues, pulls] = await Promise.all([api(`/api/github/issues?project_id=${encodeURIComponent(projectId)}`), api(`/api/github/pulls?project_id=${encodeURIComponent(projectId)}`)]);
    state.planGithubCatalog = [
      ...(issues.issues || []).map((item) => ({...item, kind: "github_issue"})),
      ...(pulls.pulls || []).map((item) => ({...item, kind: "pull_request"})),
    ];
  } catch (error) { toast(`Could not load GitHub sources: ${error.message}`, true); }
  finally { state.planGithubLoading = false; renderEpicSourcePicker(); }
}

async function addEpicUrlSource() {
  const input = $("#epicSourceUrl"); const url = String(input.value || "").trim();
  if (!url) return;
  if (epicSourceCount() >= 20) { toast("Choose at most 20 planning documents.", true); return; }
  try {
    const source = await api("/api/planning-sources/preview-url", {method: "POST", body: JSON.stringify({url})});
    if ([...selectedEpicRepositorySources(), ...state.planUploadedSources, ...state.planUrlSources].some((item) => item.sha256 && item.sha256 === source.sha256)) { toast("That document is already selected.", true); return; }
    if (epicSourceBytes([source]) > 320000) { toast("Selected documents exceed the 320 KB planning limit.", true); return; }
    state.planUrlSources.push(source); input.value = ""; renderEpicSourcePicker();
  } catch (error) { toast(error.message, true); }
}

async function addEpicUploadedSources(files) {
  const candidates = [...files];
  if (!candidates.length) return;
  if (epicSourceCount(candidates.length) > 20) { toast("Choose at most 20 planning documents.", true); return; }
  const allowed = /\.(md|markdown|txt|rst|adoc|json|ya?ml)$/i; const additions = [];
  for (const file of candidates) {
    if (!allowed.test(file.name)) { toast(`${file.name} is not a supported text document.`, true); return; }
    if (file.size > 80000) { toast(`${file.name} exceeds the 80 KB document limit.`, true); return; }
    const content = await file.text(); const bytes = new TextEncoder().encode(content).length;
    if (!content.trim()) { toast(`${file.name} is empty.`, true); return; }
    if (bytes > 80000) { toast(`${file.name} exceeds the 80 KB document limit.`, true); return; }
    if (possibleSourceSecret(content)) { toast(`${file.name} may contain a token or secret. Sanitize it before planning.`, true); return; }
    const sha256 = await sourceDigest(content);
    const existing = [...selectedEpicRepositorySources(), ...state.planUploadedSources, ...state.planUrlSources, ...additions];
    if (existing.some((item) => item.sha256 === sha256)) { toast(`${file.name} duplicates an already selected document.`, true); return; }
    additions.push({title: file.name, path: `upload://${file.name}`, kind: inferredUploadedKind(file.name), bytes, content, sha256, preview: content.slice(0, 2000)});
  }
  if (epicSourceBytes(additions) > 320000) { toast("Selected documents exceed the 320 KB planning limit.", true); return; }
  state.planUploadedSources.push(...additions); renderEpicSourcePicker();
}

function openEpicDialog(sourcePaths = []) {
  const form = $("#epicForm"); form.reset(); prepareProjectSelect($("#epicProjectSelect"), $("#epicCustomProject"));
  state.planSelectedSourcePaths = [...sourcePaths]; state.planUploadedSources = []; state.planUrlSources = []; state.planSelectedGithub = []; state.planForcedSourcePaths = []; state.planSourceTab = sourcePaths.length ? "adr" : "all";
  const decisions = state.projectOverview?.decisions || []; const selected = decisions.filter((item) => state.planSelectedSourcePaths.includes(item.path));
  $("#epicProjectSelect").disabled = false; state.planRepositorySources = selected.length ? decisions : [];
  if (selected.length) { form.elements.source_kind.value = "adr"; form.elements.requirement.value = `Implement the selected architecture decision${selected.length === 1 ? "" : "s"} as one coherent, verified change. Preserve the recorded constraints and show any ambiguity before implementation.`; }
  renderEpicSourcePicker(); $("#epicDialog").showModal();
  refreshEpicSourceChoices($("#epicProjectSelect").value, {preserveSelection: Boolean(selected.length)}).catch((error) => toast(error.message, true));
}

function repositoryStatusLabel(run) {
  const deliveryStatus = String(run?.delivery?.status || "");
  if (run?.status === "pr_created" || deliveredDeliveryStatuses.has(deliveryStatus)) return "Delivered";
  if (["accepted", "completed"].includes(run?.status)) return "Accepted";
  if (activeStatuses.has(run?.status)) return "Running";
  if (["blocked", "attention", "failed", "cancelled"].includes(run?.status)) return "Blocked";
  if (run?.status === "review") return "Review";
  return "Planned";
}

function repositoryStatusNodes(project, runs) {
  const runNodes = runs.map((run) => ({
    key: run.task_key || run.id,
    id: run.id,
    title: runTitle(run, run.id),
    status: repositoryStatusLabel(run),
    created_at: run.created_at,
    started_at: run.started_at,
    finished_at: run.finished_at,
    artifact_created_at: run.artifact_created_at,
    updated_at: run.updated_at,
    cost_usd: run.navigation?.cost_observed ? Number(run.navigation.cost_usd) : null,
    cost_kind: run.navigation?.cost_observed ? "observed" : "",
    raw_dependencies: [...(run.dependency_keys || []), ...(run.depends_on || [])],
  }));
  const aliases = new Map(runNodes.flatMap((node) => [[node.key, node.key], [node.id, node.key]].filter(([key]) => key)));
  runNodes.forEach((node) => {
    node.depends_on = [...new Set(node.raw_dependencies.map((key) => aliases.get(key) || key))].filter((key) => key && key !== node.key);
    delete node.raw_dependencies;
  });
  const existing = new Set(runNodes.flatMap((node) => [node.key, node.id].filter(Boolean)));
  const planned = state.epics
    .filter((epic) => epic.project_id === project.id && !(epic.run_ids || []).length)
    .flatMap((epic) => (epic.plan?.tasks || []).map((task) => {
      const estimate = [task.estimated_cost_usd, task.estimate?.cost_usd, task.estimated_cost?.usd].find((value) => value !== null && value !== undefined && Number.isFinite(Number(value)));
      const cap = [task.budgets?.max_cost_usd, task.budget?.max_cost_usd, task.budget?.usd].find((value) => value !== null && value !== undefined && Number(value) > 0 && Number.isFinite(Number(value)));
      return {
        key: task.task_key,
        id: "",
        title: task.title || task.task || task.task_key,
        status: "Planned",
        created_at: epic.created_at,
        updated_at: epic.updated_at,
        cost_usd: estimate !== undefined ? Number(estimate) : cap !== undefined ? Number(cap) : null,
        cost_kind: estimate !== undefined ? "estimated" : cap !== undefined ? "cap" : "",
        depends_on: [...new Set(task.depends_on || [])],
      };
    }))
    .filter((node) => node.key && !existing.has(node.key));
  return [...runNodes, ...planned];
}

function repositoryNodeCost(node) {
  if (node.cost_usd === null || node.cost_usd === undefined || !Number.isFinite(Number(node.cost_usd))) return "";
  const prefix = node.cost_kind === "estimated" ? "est. " : node.cost_kind === "cap" ? "cap " : "";
  return `${prefix}${compactMoney(node.cost_usd)}`;
}

function repositoryStatusDepths(nodes) {
  const byKey = new Map(nodes.flatMap((node) => [[node.key, node], [node.id, node]].filter(([key]) => key)));
  const visiting = new Set();
  const memo = new Map();
  const depthOf = (node) => {
    if (!node) return 0;
    if (memo.has(node.key)) return memo.get(node.key);
    if (visiting.has(node.key)) return 0;
    visiting.add(node.key);
    const parents = (node.depends_on || []).map((key) => byKey.get(key)).filter(Boolean);
    const depth = parents.length ? 1 + Math.max(...parents.map(depthOf)) : 0;
    visiting.delete(node.key);
    memo.set(node.key, depth);
    return depth;
  };
  nodes.forEach(depthOf);
  return memo;
}

function timestampMs(value) {
  const valueMs = new Date(value || "").getTime();
  return Number.isFinite(valueMs) ? valueMs : null;
}

function renderRepositoryStatus() {
  const project = activeProject();
  if (!project) return;
  const runs = runsForProject(project.id);
  const nodes = repositoryStatusNodes(project, runs);
  const counts = nodes.reduce((result, node) => ({...result, [node.status]: (result[node.status] || 0) + 1}), {});
  const delivered = counts.Delivered || 0;
  const accepted = counts.Accepted || 0;
  const finished = delivered + accepted;
  const latestMs = Math.max(...runs.map((run) => timestampMs(run.updated_at) || 0), 0);
  const observedCosts = runs.filter((run) => run.navigation?.cost_observed && Number.isFinite(Number(run.navigation.cost_usd)));
  const totalObservedCost = observedCosts.reduce((total, run) => total + Number(run.navigation.cost_usd), 0);
  $("#repositoryStatusUpdated").textContent = latestMs ? `Updated ${relativeTime(new Date(latestMs).toISOString())} ago` : "No tasks";
  $("#repositoryDeliveryMetrics").innerHTML = [
    [delivered, "Delivered", "in the source or PR"],
    [accepted, "Accepted", "artifact only"],
    [counts.Running || 0, "Running", "agent or checks"],
    [(counts.Blocked || 0) + (counts.Review || 0), "Needs you", "review or recovery"],
    [counts.Planned || 0, "Planned", "not started"],
    [runs.length ? `${Math.round((finished / runs.length) * 100)}%` : "0%", "Success", "accepted or delivered"],
    [observedCosts.length ? compactMoney(totalObservedCost) : "—", "Observed cost", observedCosts.length ? `coverage ${observedCosts.length}/${runs.length}` : "provider cost unavailable"],
  ].map(([value, label, note]) => `<div><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong><span>${escapeHtml(note)}</span></div>`).join("");

  const depths = repositoryStatusDepths(nodes);
  const maxDepth = Math.max(...nodes.map((node) => depths.get(node.key) || 0), 0);
  const known = new Set(nodes.flatMap((node) => [node.key, node.id].filter(Boolean)));
  const edgeCount = nodes.reduce((total, node) => total + (node.depends_on || []).filter((key) => known.has(key)).length, 0);
  $("#repositoryGraphCount").textContent = `${nodes.length} task${nodes.length === 1 ? "" : "s"} · ${edgeCount} edge${edgeCount === 1 ? "" : "s"}`;
  $("#repositoryDependencyGraph").innerHTML = nodes.length ? Array.from({length: maxDepth + 1}, (_, depth) => `
    <div class="repository-graph-column" aria-label="Dependency level ${depth + 1}">
      ${nodes.filter((node) => (depths.get(node.key) || 0) === depth).map((node) => `
        <button class="repository-graph-node repo-status-${node.status.toLowerCase()}" ${node.id ? `data-status-run="${escapeHtml(node.id)}"` : "disabled"} type="button">
          <span>${escapeHtml(node.status)}${repositoryNodeCost(node) ? ` · ${escapeHtml(repositoryNodeCost(node))}` : ""}</span><strong>${escapeHtml(node.title)}</strong><small>${escapeHtml((node.depends_on || []).length ? `after ${node.depends_on.join(", ")}` : "root task")}</small>
        </button>`).join("")}
    </div>`).join("") : `<div class="empty-list">A task graph appears after you create a plan.</div>`;

  const now = Date.now();
  const timeline = nodes.map((node) => {
    const start = timestampMs(node.started_at) || timestampMs(node.created_at) || timestampMs(node.updated_at) || now;
    const end = node.status === "Running"
      ? now
      : timestampMs(node.finished_at) || timestampMs(node.artifact_created_at) || timestampMs(node.updated_at) || start;
    return {...node, start, end: Math.max(start, end)};
  });
  const points = timeline.flatMap((node) => [node.start, node.end]);
  const min = points.length ? Math.min(...points) : now;
  const maxObserved = points.length ? Math.max(...points) : min;
  const max = Math.max(maxObserved, min + 3_600_000);
  const range = Math.max(1, max - min);
  $("#repositoryTimelineCount").textContent = `${nodes.length} task${nodes.length === 1 ? "" : "s"}`;
  $("#repositoryGantt").innerHTML = timeline.slice(0, 18).map((node) => {
    const left = Math.max(0, Math.min(96, ((node.start - min) / range) * 100));
    const width = Math.max(4, Math.min(100 - left, ((node.end - node.start) / range) * 100));
    const cost = repositoryNodeCost(node);
    const costTitle = node.cost_kind === "observed" ? "Observed provider cost" : node.cost_kind === "estimated" ? "Estimated cost" : node.cost_kind === "cap" ? "Maximum cost budget" : "Cost not observed";
    return `<button class="gantt-row" ${node.id ? `data-status-run="${escapeHtml(node.id)}"` : "disabled"} type="button"><span title="${escapeHtml(node.title)}">${escapeHtml(node.title)}</span><svg class="gantt-track" viewBox="0 0 100 10" preserveAspectRatio="none" aria-hidden="true"><rect class="repo-status-${node.status.toLowerCase()}" x="${left.toFixed(2)}" y="0" width="${width.toFixed(2)}" height="10" rx="5"></rect></svg><em>${escapeHtml(node.status)}</em><b class="gantt-cost ${cost ? "" : "unknown"}" title="${escapeHtml(costTitle)}">${escapeHtml(cost || "—")}</b></button>`;
  }).join("") || `<div class="empty-list">The timeline appears after the first task.</div>`;
  $$('[data-status-run]').forEach((button) => button.addEventListener("click", () => selectRun(button.dataset.statusRun)));
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
    renderRepositoryStatus();
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
  renderRepositoryStatus();
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
  container.innerHTML = `
    <form id="quickTaskForm">
      <div class="quick-task-heading"><div><span class="inline-step"><b>2</b><span>NEW TASK</span></span><h2>What should the agent change?</h2></div><span class="safety-note">Source checkout untouched</span></div>
      <textarea name="task" id="quickTaskPrompt" required rows="3" placeholder="Example: Make installation errors short and actionable, add a regression test, and run the existing tests."></textarea>
      <div class="quick-task-toolbar"><span class="home-agent-note">Agent <strong>Auto</strong> · recommended</span><button class="text-button" id="quickAdvancedTask" type="button">Advanced options</button></div>
      <p class="task-submit-status hidden" id="quickTaskStatus" aria-live="polite"></p>
      <div class="quick-task-actions"><button class="primary" value="default" type="submit">Start task</button></div>
    </form>`;
  $("#quickTaskForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = event.submitter;
    const originalLabel = button.textContent;
    const data = new FormData(form);
    const task = String(data.get("task") || "").trim();
    if (!task) return;
    const status = $("#quickTaskStatus");
    try {
      form.elements.task.value = "";
      status.textContent = `Starting the task in ${projectName(project)}...`;
      status.classList.remove("hidden");
      setFormSubmitting(form, true, button, "Starting...");
      const run = await api("/api/runs", {method: "POST", body: JSON.stringify({task, project_path: project.path, lane: state.bootstrap.default_lane, auto_route: true, origin: "web", skill_mode: "auto"})});
      status.textContent = "Task started. Opening it now...";
      toast(`Task started: ${runTitle(run)}`);
      await Promise.all([refreshRuns(), refreshProjects()]);
      await selectRun(run.id);
    } catch (error) {
      form.elements.task.value = task;
      status.classList.add("hidden");
      toast(error.message, true);
    }
    finally {
      setFormSubmitting(form, false, button, originalLabel);
      if (state.view === "tasks") status.classList.add("hidden");
    }
  });
  $("#quickAdvancedTask").addEventListener("click", () => {
    const prompt = $("#quickTaskPrompt").value;
    openTaskDialog({prompt, projectId: project.id});
  });
}

function setWorkListExpanded(expanded) {
  state.workListExpanded = !!expanded;
  const panel = $("#workListPanel");
  const button = $("#workListToggle");
  if (!panel || !button) return;
  panel.classList.toggle("hidden", !state.workListExpanded);
  button.setAttribute("aria-expanded", String(state.workListExpanded));
  const noun = activeProject() ? "tasks" : "repositories";
  button.textContent = state.workListExpanded ? `Hide ${noun}` : `Show ${noun}`;
}

function renderWork() {
  const project = activeProject();
  const runs = project ? runsForProject(project.id) : state.runs;
  const active = runs.filter((run) => activeStatuses.has(run.status)).length;
  const needs = project ? attentionTaskCount(attentionForProject(project.id)) : attentionTaskCount();
  const complete = runs.filter((run) => ["accepted", "pr_created", "completed"].includes(run.status)).length;
  const terminals = project ? projectTerminalCount(project) : state.sessions.length;
  const delivered = runs.filter((run) => run.status === "pr_created" || deliveredDeliveryStatuses.has(run.delivery?.status)).length;
  const acceptedOnly = runs.filter((run) => run.status === "accepted" && !deliveredDeliveryStatuses.has(run.delivery?.status)).length;
  const deliveryBlocked = runs.filter((run) => run.status === "accepted" && run.delivery?.status === "failed").length;
  $("#workView").classList.toggle("repository-selected", !!project);
  $("#workBreadcrumb").textContent = project ? "GIT REPOSITORY" : "";
  $("#workBreadcrumb").classList.toggle("hidden", !project);
  $("#workTitle").textContent = project ? projectName(project) : (state.projects.length ? "Repositories" : "Welcome to Odysseus");
  $("#workDescription").textContent = project ? `${runs.length} task${runs.length === 1 ? "" : "s"} · ${needs ? `${needs} need you` : UI_COPY.noAction}.` : "Add or choose a local Git folder. Odysseus never moves your code.";
  $("#workStatusStrip").innerHTML = project ? [
    ["status-running", "Running", active],
    [needs || deliveryBlocked ? "status-attention" : "status-accepted", "Needs you", needs + deliveryBlocked],
    ["status-accepted", "Delivered", delivered],
    [acceptedOnly ? "status-attention" : "status-queued", "Artifacts", acceptedOnly],
  ].map(([tone, label, value]) => `<span class="repository-status-item ${escapeHtml(tone)}"><b>${escapeHtml(value)}</b>${escapeHtml(label)}</span>`).join("") + `<button class="repository-plan-cta" data-status-focus="dashboard" type="button"><span aria-hidden="true">↘</span><strong>Open delivery plan</strong><small>Dependencies, timeline &amp; cost</small></button>` : "";
  $("#workStatusStrip").classList.toggle("hidden", !project);
  $("#workMeta").innerHTML = project ? `<span>${escapeHtml(projectRepository(project))}</span><span>Folder: ${escapeHtml(project.path)}</span><span>${escapeHtml(project.branch || "Git repository")}</span>${(project.tags || []).map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}` : "";
  $("#workMeta").classList.toggle("hidden", !project);
  $("#workSummary").innerHTML = [
    [project ? runs.length : state.projects.length, project ? "Tasks" : "Repositories", project ? "in this repository" : "registered repositories"],
    [active, "In progress", "running or waiting"],
    [needs, "Needs you", needs ? "decisions waiting" : "nothing waiting"],
    [project ? terminals : complete, project ? "Terminals" : "Completed", project ? "agent panes" : "accepted changes"],
  ].map(([value, label, note]) => `<div class="work-stat"><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong><span>${escapeHtml(note)}</span></div>`).join("");
  $("#workSummary").classList.add("hidden");
  $("#journeyStepper").classList.add("hidden");
  renderJourney();
  renderCurrentRepositoryHint();
  renderQuickStart();
  renderProjectKnowledge();
  $("#workPlanButton").classList.toggle("hidden", !project);
  $("#workNewTaskButton").classList.remove("hidden");
  $("#workNewTaskButton").textContent = project ? "＋ New task" : "＋ Add repository";
  $("#newTaskButton").classList.toggle("hidden", !state.projects.length);
  $$('[data-new-task]').forEach((button) => button.classList.toggle("hidden", !state.projects.length));
  $("#workListEyebrow").textContent = project ? "TASKS" : "REPOSITORIES";
  $("#workListTitle").textContent = project ? "Recent work" : "Repository folders";
  $("#workListDescription").textContent = project ? "Latest tasks for this repository." : "Local Git checkouts known to Odysseus.";
  const workListScope = project?.id || "all-repositories";
  if (state.workListScope !== workListScope) {
    state.workListScope = workListScope;
    state.workListExpanded = !project;
  }
  setWorkListExpanded(state.workListExpanded);
  const secondary = $("#workSecondaryAction");
  secondary.textContent = project ? "View plans" : "Add repository";
  secondary.classList.toggle("hidden", !project);
  secondary.onclick = () => project ? setView("epics") : $("#projectDialog").showModal();
  $("#workList").closest(".work-section").classList.toggle("hidden", !state.projects.length);
  if (!project) {
    $("#workList").innerHTML = state.projects.length ? state.projects.map((item) => {
      const itemRuns = runsForProject(item.id); const itemActive = itemRuns.filter((run) => activeStatuses.has(run.status)).length; const itemNeeds = attentionTaskCount(attentionForProject(item.id));
      const checkoutNote = projectHasDuplicateCheckout(item) ? `Checkout · ${item.folder_name}` : item.path;
      return `<article class="project-overview-card"><button class="project-overview-main" data-work-project="${escapeHtml(item.id)}" type="button"><span class="project-glyph">${escapeHtml(projectName(item).slice(0, 1).toUpperCase())}</span><span class="project-overview-copy"><strong>${escapeHtml(projectName(item))}</strong><span class="repository-reference">${escapeHtml(projectRepository(item))}</span><small>${escapeHtml(checkoutNote)}</small></span></button><div class="project-overview-side"><div class="project-card-signals"><span>${itemRuns.length} tasks</span><span>${itemActive} active</span>${itemNeeds ? `<span class="needs">${itemNeeds} need you</span>` : ""}</div><button class="text-button danger-text" data-forget-project-inline="${escapeHtml(item.id)}" type="button">Remove</button></div></article>`;
    }).join("") : `<div class="empty-card"><strong>No repositories yet.</strong><br>Add one, then describe the first task.</div>`;
    $$('[data-work-project]').forEach((button) => button.addEventListener("click", () => selectProject(button.dataset.workProject)));
    $$('[data-forget-project-inline]').forEach((button) => button.addEventListener("click", () => forgetProject(button.dataset.forgetProjectInline)));
  } else {
    $("#workList").innerHTML = runs.length ? runs.map((run) => { const deliveryState = run.status === "accepted" && deliveredDeliveryStatuses.has(run.delivery?.status) ? "Delivered" : run.status === "accepted" && run.delivery?.status === "failed" ? "Apply blocked" : run.status === "accepted" ? "Approved · not applied" : statusLabel(run.status); const tone = run.status === "accepted" && run.delivery?.status === "failed" ? "status-failed" : statusClass(run.status); return `<button class="work-task-row" data-work-run="${escapeHtml(run.id)}" type="button" title="${escapeHtml(runActionLine(run))}"><span class="mini-status ${tone}">${escapeHtml(deliveryState)}</span><time class="work-task-time">${escapeHtml(relativeTime(run.updated_at))}</time><h3>${escapeHtml(runTitle(run))}</h3></button>`; }).join("") : `<div class="empty-card"><strong>No tasks yet.</strong><br>Describe the first change above.</div>`;
    $$('[data-work-run]').forEach((button) => button.addEventListener("click", () => selectRun(button.dataset.workRun)));
  }
  $("#workStatusStrip [data-status-focus]")?.addEventListener("click", () => $("#repositoryStatusView")?.scrollIntoView({behavior: "smooth", block: "start"}));
}

function taskDotTone(run) {
  if (run.status === "accepted" && run.delivery?.status === "failed") return "status-needs-action";
  const openItems = relevantAttentionItems(state.attention).filter((item) => item.run_id === run.id);
  if (openItems.some((item) => item.type === "question")) return "status-question";
  if (["review", "attention", "blocked", "failed", "cancelled"].includes(run.status)) return "status-needs-action";
  if (activeStatuses.has(run.status)) return "status-in-progress";
  if (["accepted", "completed", "pr_created", "decided"].includes(run.status)) return "status-done";
  return statusClass(run.status);
}

function renderRuns() {
  const runs = filteredRuns();
  $("#runCount").textContent = runs.length;
  const sourceChip = $("#taskSourceFilterChip");
  sourceChip.classList.toggle("hidden", !state.taskSourceFilter);
  sourceChip.innerHTML = state.taskSourceFilter ? `<span>Source: ${escapeHtml(state.taskSourceFilter)}</span><button type="button" aria-label="Clear source filter">×</button>` : "";
  sourceChip.querySelector("button")?.addEventListener("click", () => { state.taskSourceFilter = ""; state.planFilter = "all"; renderRuns(); });
  $("#taskList").innerHTML = runs.length ? runs.map((run) => {
    const session = run.kind === "tmux" ? discoveredSessionForRun(run) : null;
    const title = session?.title || session?.window_name || runTitle(run);
    const status = run.kind === "tmux" ? "tracked terminal" : run.status === "accepted" && deliveredDeliveryStatuses.has(run.delivery?.status) ? "delivered" : run.status === "accepted" && run.delivery?.status === "failed" ? "apply blocked" : run.status === "accepted" ? "approved · not applied" : statusLabel(run.status);
    const statusTone = taskDotTone(run);
    const navigation = run.navigation || {};
    const filesChanged = Number(navigation.files_changed || 0);
    const checksTotal = Number(navigation.checks_total || 0);
    const costSignal = navigation.cost_observed
      ? `<span class="task-row-cost" title="Observed task cost">${escapeHtml(compactMoney(navigation.cost_usd))}</span>`
      : `<span class="task-row-cost unknown" title="Task cost is not reported by this provider">—</span>`;
    const outcomeSignal = filesChanged
      ? `<span class="task-row-stat" title="${filesChanged} changed file${filesChanged === 1 ? "" : "s"}">${filesChanged}f</span>`
      : checksTotal ? `<span class="task-row-stat" title="${checksTotal} recorded check${checksTotal === 1 ? "" : "s"}">✓${checksTotal}</span>` : "";
    const signals = run.kind === "tmux"
      ? `<span>tmux ${escapeHtml(session?.tmux_session || run.tmux_session || "session")} · ${escapeHtml(session?.tmux_target || run.tmux_target || "pane")}</span>`
      : `<span class="risk-${escapeHtml(run.merge_analysis?.risk || "none")}">${escapeHtml(run.merge_analysis?.risk || "none")} merge risk</span>${run.ci?.status && run.ci.status !== "not_started" ? `<span class="ci-${escapeHtml(run.ci.status)}">CI ${escapeHtml(run.ci.status)}</span>` : ""}`;
    return `<button class="task-card ${run.id === state.selectedId ? "selected" : ""}" data-run-id="${escapeHtml(run.id)}" type="button" aria-label="${escapeHtml(`${title}. ${status}. Updated ${relativeTime(run.updated_at)} ago.`)}">
      <span class="task-state-dot ${statusTone}" aria-hidden="true"></span>
      <h3>${escapeHtml(title)}</h3>
      <span class="task-row-meta">${costSignal}<i aria-hidden="true">·</i>${outcomeSignal}${outcomeSignal ? `<i aria-hidden="true">·</i>` : ""}<time>${relativeTime(run.updated_at)}</time></span>
      <div class="task-card-top"><span class="mini-status ${statusTone}">${escapeHtml(status)}</span><span class="run-id">${relativeTime(run.updated_at)}</span></div>
      <div class="task-card-meta"><span>${escapeHtml(run.lane)}${run.kind === "tmux" ? "" : ` · P${escapeHtml(run.priority ?? 50)}`}</span><span>${escapeHtml(projectById(run.project_id) ? projectName(projectById(run.project_id)) : run.kind || run.workflow)}</span></div>
      <div class="task-signals">${signals}</div>
    </button>`;
  }).join("") : `<div class="empty-list">No tasks in this view.</div>`;
  $$(".task-card[data-run-id]").forEach((button) => {
    button.addEventListener("click", () => selectRun(button.dataset.runId));
    button.addEventListener("pointerenter", () => showTaskHover(button));
    button.addEventListener("pointerleave", hideTaskHover);
    button.addEventListener("focus", () => showTaskHover(button));
    button.addEventListener("blur", hideTaskHover);
  });
  renderProjectTree();
  renderHome();
}

function taskHoverMarkup(run) {
  const navigation = run.navigation || {};
  const project = projectById(run.project_id);
  const title = runTitle(run, run.id);
  const status = run.kind === "tmux"
    ? "Tracked terminal"
    : run.status === "accepted" && deliveredDeliveryStatuses.has(run.delivery?.status)
      ? "Delivered"
      : run.status === "accepted" && run.delivery?.status === "failed"
        ? "Integration blocked"
      : run.status === "accepted" ? "Approved · not applied" : statusLabel(run.status);
  const statusTone = taskDotTone(run);
  const files = Number(navigation.files_changed || 0);
  const checks = Number(navigation.checks_total || 0);
  const passed = Number(navigation.checks_passed || 0);
  const tools = Number(navigation.tool_calls || 0);
  const tokens = Number(navigation.total_tokens || 0);
  const cost = navigation.cost_observed ? `${compactMoney(navigation.cost_usd)} cost` : "Cost unknown";
  const environment = run.kind === "tmux"
    ? "Existing terminal session"
    : navigation.isolated ? "Runs in an isolated git worktree" : `Execution: ${navigation.environment || "host"}`;
  const metrics = [
    files ? `${files} file${files === 1 ? "" : "s"}` : "No artifact yet",
    checks ? `${passed}/${checks} checks` : "Checks pending",
    tools ? `${compactNumber(tools)} tools` : "No tools yet",
    tokens ? `${compactNumber(tokens)} tokens` : "Tokens pending",
    cost,
  ];
  return `<header><strong>${escapeHtml(title)}</strong><time>${escapeHtml(relativeTime(run.updated_at))}</time></header>
    <p><span aria-hidden="true">□</span>${escapeHtml(project ? projectName(project) : "Repository")}</p>
    <p><span class="task-state-dot ${statusTone}" aria-hidden="true"></span>${escapeHtml(status)} · ${escapeHtml(run.lane || "agent")}</p>
    <p><span aria-hidden="true">▱</span>${escapeHtml(environment)}</p>
    <footer>${metrics.map((value) => `<span>${escapeHtml(value)}</span>`).join("")}</footer>`;
}

function showTaskHover(button) {
  if (window.matchMedia("(max-width: 900px)").matches) return;
  const run = state.runs.find((item) => item.id === button.dataset.runId);
  const card = $("#taskHoverCard");
  if (!run || !card) return;
  card.innerHTML = taskHoverMarkup(run);
  card.hidden = false;
  card.dataset.tone = run.status === "accepted" && run.delivery?.status === "failed" ? "status-failed" : statusClass(run.status);
  window.requestAnimationFrame(() => {
    const row = button.getBoundingClientRect();
    const bounds = card.getBoundingClientRect();
    const left = Math.min(row.right + 10, window.innerWidth - bounds.width - 12);
    const top = Math.max(12, Math.min(row.top - 7, window.innerHeight - bounds.height - 12));
    document.documentElement.style.setProperty("--task-hover-left", `${Math.max(12, left)}px`);
    document.documentElement.style.setProperty("--task-hover-top", `${top}px`);
  });
}

function hideTaskHover() {
  const card = $("#taskHoverCard");
  if (card) card.hidden = true;
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
  if (target?.project_id) {
    state.projectFilter = target.project_id;
    const visibleInCurrentFilter = runMatchesFilter(target, state.filter);
    if (!visibleInCurrentFilter) {
      state.filter = ["attention", "blocked", "review", "failed", "accepted"].includes(target.status) ? "review" : "all";
      $$(".filter").forEach((button) => button.classList.toggle("active", button.dataset.filter === state.filter));
    }
  }
  const generation = state.selectionGeneration + 1;
  state.selectionGeneration = generation;
  closeStream();
  state.selectedId = runId;
  state.selected = null;
  state.assistantOpen = false;
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
  $("#detailTitle").textContent = target ? runTitle(target) : "Opening task…";
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
  const discovered = interactive ? discoveredSessionForRun(run) : null;
  const status = $("#detailStatus");
  const delivered = run.delivery?.status;
  const visibleStatus = run.status === "review" ? "ready for review"
    : run.status === "accepted" && delivered === "applied" ? "applied"
    : run.status === "accepted" && deliveredDeliveryStatuses.has(delivered) && delivered !== "applied" ? "delivered by integration"
    : run.status === "accepted" ? "approved · not applied"
    : statusLabel(run.status);
  status.textContent = interactive ? "tracked tmux terminal" : visibleStatus; status.className = `status-pill ${statusClass(run.status)}`;
  $("#detailId").textContent = run.id;
  const project = projectById(run.project_id);
  $("#detailProjectName").textContent = projectName(project);
  $("#titleProject").textContent = projectName(project);
  $("#titleSurface").textContent = runTitle(run);
  $("#detailTitle").textContent = discovered?.title || discovered?.window_name || runTitle(run);
  $("#detailAgent").textContent = `Agent ${run.lane || "—"}`;
  $("#detailStage").textContent = `Stage ${statusLabel(run.stage || run.status)}`;
  $("#detailElapsed").textContent = `Wall ${formatDuration(runElapsedSeconds(run))}`;
  $("#detailElapsed").title = run.started_at ? "Wall-clock time from execution start; queue time excluded" : "Execution has not started; queue time is excluded";
  $("#detailCost").textContent = `Cost ${run.metrics?.cost_observed ? compactMoney(run.metrics.cost_usd) : "—"}`;
  $("#detailCost").title = run.metrics?.cost_observed ? "Total observed provider cost" : "Total provider cost not observed";
  $("#detailTask").textContent = interactive ? `Existing ${run.lane} session in tmux ${discovered?.tmux_session || run.tmux_session || "—"}${(discovered?.tmux_target || run.tmux_target) ? `, pane ${discovered?.tmux_target || run.tmux_target}` : ""}.` : run.task;
  $("#observedSession").classList.toggle("hidden", !interactive);
  const decisionVisible = !interactive && ["review", "accepted", "pr_created"].includes(run.status);
  const assistantVisible = !interactive && state.assistantOpen;
  $("#assistantPanel").classList.toggle("hidden", !assistantVisible);
  $(".detail-body").classList.toggle("assistant-closed", !assistantVisible);
  $("#summaryAssistant").classList.add("hidden");
  renderAssistantPanel(run);
  renderRecoveryCard(run);
  $("#runNarrative").classList.toggle("hidden", interactive || decisionVisible);
  $("#metrics").classList.toggle("hidden", interactive);
  $("#detailGrid").classList.toggle("hidden", interactive);
  const metrics = run.metrics || {};
  const modelTokens = Number(metrics.input_tokens || 0) + Number(metrics.output_tokens || 0);
  const cacheReadTokens = Number(metrics.cached_input_tokens || 0);
  const billableObserved = metrics.billable_tokens_observed === true || metrics.billable_tokens !== undefined;
  const billableTokens = billableObserved ? Number(metrics.billable_tokens || 0) : null;
  const tokenLimit = Number(run.budgets?.max_tokens || 0);
  const tokenLabel = tokenLimit ? `${compactNumber(modelTokens)} / ${compactNumber(tokenLimit)}` : compactNumber(modelTokens);
  const strength = evidenceStrength(run.confidence);
  $("#metrics").innerHTML = [
    ["Model tokens", tokenLabel, tokenLimit && modelTokens >= tokenLimit * .8 ? "budget-warning" : ""],
    ["Cache read", cacheReadTokens ? compactNumber(cacheReadTokens) : UI_COPY.notObserved],
    ["Billable tokens", billableTokens === null ? UI_COPY.unknown : compactNumber(billableTokens)],
    ["Actual cost", metrics.cost_observed ? `$${Number(metrics.cost_usd || 0).toFixed(4)}` : UI_COPY.unknown],
    ["Evidence strength", strength.label, `evidence-${strength.tone}`],
    ["GitHub CI", run.ci?.status || "not started"],
  ].map(([label, value, tone = ""]) => `<div class="metric ${tone}"><small>${label}</small><strong>${escapeHtml(value)}</strong></div>`).join("");
  const executionDetails = $("#executionDetails");
  if (executionDetails.dataset.runId !== run.id) {
    executionDetails.dataset.runId = run.id;
    executionDetails.open = false;
  }
  const executionFacts = [
    statusLabel(run.stage || run.status),
    `Model tokens ${modelTokens ? compactNumber(modelTokens) : UI_COPY.notObserved}`,
    `Cache ${cacheReadTokens ? compactNumber(cacheReadTokens) : UI_COPY.notObserved}`,
    `Actual cost ${metrics.cost_observed ? `$${Number(metrics.cost_usd || 0).toFixed(4)}` : UI_COPY.unknown}`,
    `CI ${statusLabel(run.ci?.status || "not started")}`,
  ];
  $("#executionDetailsSummary").textContent = executionFacts.join(" · ");
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
  renderActions(run); renderReviewDecision(run); renderNarrative(run); renderRecoveryCard(run); renderWorkflow(run); renderDeliveryLifecycle(run);
  loadDecisionDiff(run);
  if (changedRun) {
    $("#diffStat").textContent = "Open Changes to load the diff.";
    $("#diffPatch").textContent = "Large diffs are loaded only when this tab is visible.";
    $("#eventLog").innerHTML = eventPlaceholder("on demand", "Open Activity to load the event history.");
    $("#integrationResults").innerHTML = `<div class="empty-card">Open Integration to inspect predecessor artifacts.</div>`;
    $("#checkResults").innerHTML = `<div class="empty-card">Open Evidence to inspect checks.</div>`;
    $("#contextReceipt").innerHTML = `<div class="empty-card">Open Context to inspect attached snapshots.</div>`;
    $("#reviewSummary").textContent = "Open Review to inspect reviewer output.";
    $("#evaluationResults").innerHTML = `<div class="empty-card">Open Evaluation to inspect evidence signals.</div>`;
    $("#ciResults").innerHTML = `<div class="empty-card">Open CI to inspect GitHub checks.</div>`;
  }
  renderVisibleHeavyPanels().catch((error) => toast(error.message, true));
  if (state.helpOpen) renderHelpPanel();
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
    accepted: ["APPROVED", UI_COPY.notApplied, "Apply it to the repository, create a PR, or keep it for later.", UI_COPY.deliver, "attention", "✓"],
    publishing: ["PUBLISHING", "Creating draft PR", "Task branch is being pushed.", UI_COPY.noAction, "active", "↗"],
    pr_created: ["PR CREATED", ciStatus === "failed" ? "CI failed" : ciStatus === "passed" ? "CI passed" : "CI pending", ciStatus === "failed" ? "Failure logs are captured." : "GitHub checks are tracked here.", ciStatus === "failed" ? "Repair in progress" : ciStatus === "passed" ? "Complete" : UI_COPY.noAction, ciStatus === "failed" ? "danger" : ciStatus === "passed" ? "success" : "active", ciStatus === "passed" ? "✓" : "↻"],
  };
  const environmentApproval = run.status === "attention" && run.environment?.trust_status === "pending";
  let narrative = environmentApproval ? ["TRUST GATE", "Approve repository commands", "No repository command has run.", UI_COPY.needsYou, "attention", "!"] : values[run.status] || ["WORKFLOW", "Tracking task", "Open Activity for events.", UI_COPY.noAction, "calm", "→"];
  if (run.status === "accepted" && ["applied", "integrated_applied"].includes(run.delivery?.status)) narrative = ["APPLIED", `Applied to ${run.delivery.target_branch || run.base_ref}`, `HEAD ${String(run.delivery.target_after_sha || "").slice(0, 12) || UI_COPY.unknown}. Artifact remains auditable.`, run.delivery?.status === "integrated_applied" ? "Delivered by integration" : "Delivered locally", "success", "✓"];
  if (run.status === "accepted" && run.delivery?.status === "failed") narrative = ["APPLY BLOCKED", "Approved change saved; repository unchanged", run.delivery.error || "Resolve the repository conflict.", UI_COPY.needsYou, "danger", "!"];
  if (run.status === "accepted" && run.delivery?.status === "integration_queued") narrative = ["INTEGRATION QUEUED", "Artifact selected for integration", `Run ${run.delivery.integration_run_id || UI_COPY.unknown} will compose delivery.`, "Integration queued", "attention", "→"];
  const [label, title, copy, tail, tone, mark] = narrative;
  $("#narrativeLabel").textContent = label; $("#narrativeTitle").textContent = title; $("#narrativeCopy").textContent = copy; $("#narrativeTail").textContent = tail; $("#narrativeMark").textContent = mark; $("#runNarrative").dataset.tone = tone;
}

function lifecycleModel(run) {
  const checks = run.check_results || [];
  const verified = checks.length > 0 && checks.every((item) => item.skipped || Number(item.returncode) === 0);
  const accepted = ["accepted", "pr_created"].includes(run.status);
  const published = Boolean(run.pull_request_url) || ["pr_created", "integrated_pr_created"].includes(run.delivery?.status);
  const integrated = ["applied", "integrated_applied", "integrated_pr_created"].includes(run.delivery?.status);
  const deployment = String(run.deployment?.status || "").toLowerCase();
  const observation = String(run.observation?.status || run.outcome?.observation_status || "").toLowerCase();
  const outcome = String(run.outcome?.final_outcome || run.outcome?.status || "").toLowerCase();
  const executed = Boolean(run.artifact_sha) || ["review", "accepted", "publishing", "pr_created"].includes(run.status);
  const steps = [
    ["Executed", executed, "Immutable artifact produced"],
    ["Verified", verified, checks.length ? `${checks.filter((item) => item.skipped || Number(item.returncode) === 0).length}/${checks.length} checks passed` : "Required evidence not observed"],
    ["Accepted", accepted, "Human or policy accepted this artifact"],
    ["Published", published, "Branch or pull request published"],
    ["Integrated", integrated, "Change reached the target branch"],
    ["Deployed", ["deployed", "healthy", "success"].includes(deployment), deployment ? `Deployment ${deployment}` : "Deployment not observed"],
    ["Observed", Boolean(observation) && !["unknown", "pending", "not_observed"].includes(observation), observation ? `Observation ${observation}` : "Post-merge observation not recorded"],
    [outcome === "regressed" ? "Regressed" : "Healthy", outcome === "healthy" || outcome === "regressed", outcome ? `Outcome ${outcome}` : "Final outcome unknown"],
  ];
  let next = {label: "Continue execution", actor: "Odysseus", detail: runActionLine(run)};
  if (["failed", "attention"].includes(run.status)) next = {label: run.status === "failed" ? "Recover task" : "Answer decision", actor: "You", detail: runActionLine(run)};
  else if (run.status === "review") next = {label: "Accept or request changes", actor: "You", detail: "Review hard gates and unknown evidence"};
  else if (accepted && !integrated && !published) next = {label: "Apply locally or create a PR", actor: "You", detail: "Acceptance preserved the artifact; source is unchanged"};
  else if (published && !integrated) next = {label: "Reach green, then integrate", actor: "You or policy", detail: ciActionLine(run)};
  else if (integrated && !steps[5][1]) next = {label: "Record deployment", actor: "Deployment integration", detail: "No deployment receipt observed"};
  else if (steps[5][1] && !steps[6][1]) next = {label: "Observe health", actor: "Odysseus", detail: "Waiting for post-deployment signals"};
  else if (steps[7][1]) next = {label: "Outcome recorded", actor: "Complete", detail: steps[7][2]};
  const firstIncomplete = steps.findIndex((item) => !item[1]);
  return {steps, firstIncomplete, next};
}

function renderDeliveryLifecycle(run) {
  const node = $("#deliveryLifecycle");
  if (!node || run.kind === "tmux") { node?.classList.add("hidden"); return; }
  node.classList.remove("hidden");
  const model = lifecycleModel(run);
  node.innerHTML = `<div class="lifecycle-track">${model.steps.map(([label, done, detail], index) => `<span class="lifecycle-step ${done ? "done" : index === model.firstIncomplete ? "next" : "pending"}" title="${escapeHtml(detail)}"><i>${done ? "✓" : index + 1}</i><strong>${escapeHtml(label)}</strong></span>`).join("")}</div><div class="lifecycle-next"><small>NEXT</small><strong>${escapeHtml(model.next.label)}</strong><span>${escapeHtml(model.next.detail)} · Owner: ${escapeHtml(model.next.actor)}</span></div>`;
}

function renderActions(run) {
  const actions = [];
  if (run.status === "queued") actions.push(`<button class="action-button" data-action="settings" type="button">Queue settings</button>`);
  if (run.status === "accepted" && run.artifact_sha && !deliveredDeliveryStatuses.has(run.delivery?.status)) {
    const conflict = run.delivery?.status === "failed" && /conflict|merge was aborted/i.test(run.delivery?.error || "");
    actions.push(conflict
      ? `<button class="action-button accept" data-review-action="resolve-conflict" type="button">Resolve integration</button>`
      : `<button class="action-button accept" data-action="apply" type="button">Apply to repository</button>`);
  }
  if (["accepted", "pr_created"].includes(run.status)) actions.push(`<button class="action-button" data-action="resume" type="button">Follow up</button>`);
  if ((run.tmux_session || run.agent_sessions?.agent || run.agent_session_id) && !canInlineResume(run)) actions.push(`<button class="action-button" data-action="takeover" type="button" title="Copies a command that opens this agent in your terminal">${run.kind === "tmux" ? "Copy tmux command" : "Continue in terminal"}</button>`);
  if (activeStatuses.has(run.status) && run.status !== "cancelling") actions.push(`<button class="action-button warn" data-action="cancel" type="button">Cancel</button>`);
  if (run.pull_request_url) actions.push(`<a class="action-button accept" href="${escapeHtml(run.pull_request_url)}" target="_blank" rel="noreferrer">Open PR</a>`);
  if (run.pull_request_url) actions.push(`<button class="action-button" data-action="ci-poll" type="button">Poll CI</button>`);
  if (run.kind !== "tmux") actions.push(`<button class="action-button" data-action="assistant" type="button">${state.assistantOpen ? "Close assistant" : "Ask assistant"}</button>`);
  $("#runActions").innerHTML = actions.join("");
  $$("#runActions [data-action]").forEach((button) => button.addEventListener("click", () => runAction(button.dataset.action)));
  $$("#runActions [data-review-action]").forEach((button) => button.addEventListener("click", () => reviewAction(button.dataset.reviewAction, button)));
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
  const strength = evidenceStrength(run.confidence);
  const unknowns = [
    !checks.length ? "checks" : "",
    !verdict ? "independent review" : "",
    !ciObserved ? "GitHub CI" : "",
    !run.metrics?.cost_observed ? "cost" : "",
    !stat.observed ? "diff statistics" : "",
  ].filter(Boolean);
  const title = (run.status === "review" && (!ciObserved || !["passed", "success"].includes(String(ci.status).toLowerCase())))
    ? "Ready for your decision"
    : run.status === "review" ? "Ready for your decision" : "Delivery decision";
  return {checks, passed, failed, ci, ciFailures, files, stat, riskPaths, unresolved, verdict, ciObserved, cost, strength, unknowns, title};
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
      <div><small>Hard gates</small><strong>${escapeHtml(evidence.passed)} / ${escapeHtml(evidence.checks.length)} checks</strong></div>
      <div><small>Gate failures</small><strong>${escapeHtml(evidence.failed.length + evidence.ciFailures.length)}</strong></div>
      <div><small>Diff</small><strong>${escapeHtml(diffValue)}</strong></div>
      <div><small>Files</small><strong>${escapeHtml(fileValue)}</strong></div>
      <div><small>Independent review</small><strong>${escapeHtml(evidence.verdict || UI_COPY.unknown)}</strong></div>
      <div><small>GitHub CI</small><strong>${escapeHtml(ciValue)}</strong></div>
      <div><small>Soft evidence</small><strong class="evidence-${escapeHtml(evidence.strength.tone)}">${escapeHtml(evidence.strength.label)}</strong></div>
      <div><small>Unknowns</small><strong>${escapeHtml(evidence.unknowns.length ? evidence.unknowns.length : "None")}</strong></div>
      <div><small>Cost</small><strong>${escapeHtml(evidence.cost)}</strong></div>
    </section>
    <details class="decision-detail"><summary>More evidence</summary><pre>${escapeHtml([
      `Checks: ${evidence.passed}/${evidence.checks.length}`,
      `Failed checks: ${evidence.failed.map((item) => item.command || "check").join(", ") || "none observed"}`,
      `CI failures: ${evidence.ciFailures.map((item) => item.name || item.workflow || "check").join(", ") || "none observed"}`,
      `High-risk paths: ${riskValue}`,
      `Unknown evidence: ${evidence.unknowns.join(", ") || "none"}`,
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
  let deliveryCopy = "Approving records this exact change and its evidence. It does not change your source repository yet.";
  let deliveryActions = `<button class="primary" data-review-action="accept" type="button">Approve change</button>`;
  let alternateActions = `<button class="ghost" data-review-action="draft-pr" type="button">Create draft PR</button>`;
  let deliveryHelp = "";
  if (run.status === "accepted" && !delivered) {
    deliveryCopy = failed ? `Applying the change is blocked: ${delivery.error || "inspect the repository state and resolve the conflict."}` : `Approved and ready to apply to ${run.base_ref || "the source branch"}.`;
    const conflict = /conflict|merge was aborted/i.test(delivery.error || "");
    deliveryActions = conflict
      ? `<button class="primary" data-review-action="resolve-conflict" type="button">Resolve integration</button>`
      : `<button class="primary" data-review-action="apply" type="button">${failed ? "Retry apply" : "Apply to repository"}</button>`;
    alternateActions = `<button class="ghost" data-review-action="integration" type="button">Combine approved changes</button><button class="ghost" data-review-action="draft-pr" type="button">Create draft PR</button>`;
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
    ${run.status === "review" ? `<details class="review-request"><summary>Request changes</summary><textarea id="reviewFeedback" rows="4" placeholder="Tell the agent exactly what must change before approval."></textarea><div><button class="primary" data-review-action="send-back" type="button">Send feedback</button>${canTakeover(run) ? `<button class="ghost" data-review-action="takeover" type="button">Continue in terminal</button>` : ""}</div></details>` : ""}
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
    const evidence = evidenceStrength(quality.confidence);
    const frontierMark = frontier.has(item.run_id) ? `<span class="variant-frontier">Frontier</span>` : "";
    return `<article class="variant-candidate">
      <header><div><strong>${escapeHtml(item.title || item.run_id)}</strong><small>${escapeHtml(item.run_id)} · ${escapeHtml(item.lane || "")}</small></div>${frontierMark}</header>
      <div class="variant-metrics">
        <span><small>Tests</small><strong>${escapeHtml(tests.passed || 0)}/${escapeHtml(tests.total || 0)}</strong></span>
        <span><small>Soft evidence</small><strong class="evidence-${escapeHtml(evidence.tone)}">${escapeHtml(evidence.label)}</strong></span>
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
  if (event.type.startsWith("agent.tool")) {
    const heading = `${data.tool || data.kind || "tool"}${data.command ? ` · ${data.command}` : ""}${data.exit_code !== undefined ? ` → ${data.exit_code}` : ""}`;
    const output = data.aggregated_output || data.output || data.result || "";
    return output ? `${heading}\n${truncateText(output, 2400)}` : heading;
  }
  if (data.message) return truncateText(data.message, 2400); if (data.text) return truncateText(data.text, 2400);
  if (data.answer) return truncateText(data.answer, 2400); if (data.feedback) return truncateText(data.feedback, 2400);
  if (data.task) return truncateText(data.task, 2400); if (data.reason) return truncateText(data.reason, 2400);
  if (data.command) return `${data.command}${data.returncode !== undefined ? ` → ${data.returncode}` : ""}`;
  if (data.step) return `${data.step}${data.attempt ? ` · attempt ${data.attempt}` : ""}`;
  if (data.status) return data.status; if (data.url) return data.url;
  return Object.keys(data).length ? truncateText(JSON.stringify(data), 2400) : "";
}

function eventPresentation(event) {
  const type = String(event.type || "event");
  const source = String(event.source || "odysseus");
  if (["user", "operator", "human"].includes(source) || /^(?:attention\.answered|review\.accepted|run\.feedback|variants\.decision)/.test(type)) {
    return {kind: "you", actor: "You", detail: type};
  }
  if (type === "agent.question") return {kind: "question", actor: "Agent asks", detail: `${source} · ${type}`};
  if (type.startsWith("agent.tool") || /^(?:check|ci)\./.test(type)) return {kind: "tool", actor: "Tool", detail: `${source} · ${type}`};
  if (/^(?:review|evaluation)\./.test(type) || ["reviewer", "evaluator"].includes(source)) return {kind: "reviewer", actor: "Reviewer", detail: `${source} · ${type}`};
  if (type.startsWith("agent.") || !["odysseus", "system", "git", "github", "shell"].includes(source)) return {kind: "agent", actor: "Agent", detail: `${source} · ${type}`};
  if (source === "git" || type.startsWith("worktree.") || type.startsWith("artifact.") || type.startsWith("integration.")) return {kind: "git", actor: "Git", detail: type};
  return {kind: type.includes("failed") ? "failed" : "system", actor: "System", detail: type};
}

function eventPlaceholder(type, message) {
  return `<div class="event event-system"><span class="event-avatar" aria-hidden="true">S</span><div class="event-content"><header><strong>System</strong><span>${escapeHtml(type)}</span><time>—</time></header><div class="event-message">${escapeHtml(message)}</div></div></div>`;
}

function activityPhaseDurations(events) {
  const totals = {agent: 0, check: 0, review: 0};
  const observed = {agent: false, check: false, review: false};
  const active = {agent: [], check: [], review: []};
  const phaseFor = (value) => {
    const phase = String(value || "").toLowerCase();
    if (["agent", "implement", "implementation"].includes(phase)) return "agent";
    if (["check", "checks", "ci", "verify", "verification"].includes(phase)) return "check";
    if (["review", "reviewer", "evaluation", "evaluator"].includes(phase)) return "review";
    return "";
  };
  for (const event of events) {
    if (!["step.started", "step.completed"].includes(event.type)) continue;
    const phase = phaseFor(event.data?.step || event.data?.phase);
    const timestamp = new Date(event.ts || "").getTime();
    if (!phase || !Number.isFinite(timestamp)) continue;
    if (event.type === "step.started") active[phase].push(timestamp);
    else if (active[phase].length) {
      const started = active[phase].pop();
      totals[phase] += Math.max(0, (timestamp - started) / 1000);
      observed[phase] = true;
    }
  }
  return {totals, observed};
}

function renderActivitySummary() {
  const run = state.selected || {};
  const phases = activityPhaseDurations(state.eventsLoadedRunId === state.selectedId ? state.events : []);
  const metrics = run.metrics || {};
  const activeCompute = Object.entries(phases.totals).reduce((sum, [phase, seconds]) => sum + (phases.observed[phase] ? seconds : 0), 0);
  const hasActiveCompute = Object.values(phases.observed).some(Boolean);
  const modelTokens = Number(metrics.input_tokens || 0) + Number(metrics.output_tokens || 0);
  const cacheTokens = Number(metrics.cached_input_tokens || 0);
  const billableObserved = metrics.billable_tokens_observed === true || metrics.billable_tokens !== undefined;
  const items = [
    ["Wall clock", formatDuration(runElapsedSeconds(run)), "Execution start to finish; queue time excluded"],
    ["Active compute", hasActiveCompute ? formatDuration(activeCompute) : "—", "Observed agent, checks, and review phases"],
    ["Agent", phases.observed.agent ? formatDuration(phases.totals.agent) : "—", "Observed worker execution"],
    ["Checks", phases.observed.check ? formatDuration(phases.totals.check) : "—", "Observed verification"],
    ["Review", phases.observed.review ? formatDuration(phases.totals.review) : "—", "Observed independent review"],
    ["Model tokens", modelTokens ? compactNumber(modelTokens) : "—", "Provider input plus output tokens"],
    ["Cache read", cacheTokens ? compactNumber(cacheTokens) : "—", "Provider-reported cached input tokens"],
    ["Billable", billableObserved ? compactNumber(metrics.billable_tokens || 0) : "—", "Only shown when the provider reports billable tokens"],
    ["Total cost", run.metrics?.cost_observed ? compactMoney(run.metrics.cost_usd) : "—", run.metrics?.cost_observed ? "Observed provider cost" : "Provider cost not observed"],
  ];
  $("#activitySummary").innerHTML = items.map(([label, value, title]) => `<span title="${escapeHtml(title)}"><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong></span>`).join("");
}

function eventTiming(event, baseline) {
  const timestamp = new Date(event.ts || "").getTime();
  const clock = Number.isFinite(timestamp) ? new Date(timestamp).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"}) : "—";
  const parts = [clock];
  if (Number.isFinite(timestamp) && Number.isFinite(baseline)) parts.push(`T+${formatDuration(Math.max(0, (timestamp - baseline) / 1000))}`);
  const elapsed = Number(event.data?.duration_seconds ?? event.data?.elapsed_seconds);
  if (Number.isFinite(elapsed) && elapsed >= 0) parts.push(`${formatDuration(elapsed)} elapsed`);
  const cost = Number(event.data?.cost_usd);
  if (event.data?.cost_usd !== undefined && Number.isFinite(cost) && cost >= 0) parts.push(`${compactMoney(cost)} cost`);
  return parts.join(" · ");
}

function renderEvents() {
  const log = $("#eventLog");
  renderActivitySummary();
  if (state.eventsLoadingRunId === state.selectedId && state.eventsLoadedRunId !== state.selectedId) {
    log.innerHTML = eventPlaceholder("loading", "Reading this task's activity history…");
    return;
  }
  if (state.eventsLoadedRunId !== state.selectedId) {
    log.innerHTML = eventPlaceholder("on demand", "Open Activity to load the event history.");
    return;
  }
  const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 80;
  const hiddenCount = Math.max(0, state.events.length - state.eventVisibleLimit);
  const firstEvent = new Date(state.events[0]?.ts || "").getTime();
  const runStart = new Date(state.selected?.started_at || state.selected?.created_at || "").getTime();
  const runDuration = runElapsedSeconds(state.selected);
  const baseline = Number.isFinite(runStart) && Number.isFinite(firstEvent) && firstEvent >= runStart && firstEvent - runStart <= Math.max(86_400_000, Number(runDuration || 0) * 1000 + 3_600_000) ? runStart : firstEvent;
  const eventRows = state.events.slice(-state.eventVisibleLimit).map((event) => {
    const presentation = eventPresentation(event);
    const timing = eventTiming(event, baseline);
    const mark = {you: "Y", agent: "A", question: "?", tool: "›_", reviewer: "R", git: "G", failed: "!", system: "S"}[presentation.kind] || "S";
    return `<div class="event event-${presentation.kind}"><span class="event-avatar" aria-hidden="true">${escapeHtml(mark)}</span><div class="event-content"><header><strong>${escapeHtml(presentation.actor)}</strong><span title="${escapeHtml(event.type)}">${escapeHtml(presentation.detail)}</span><time>${escapeHtml(timing)}</time></header><div class="event-message">${escapeHtml(eventMessage(event))}</div></div></div>`;
  }).join("");
  log.innerHTML = `${hiddenCount ? `<button class="ghost activity-load-older" id="loadOlderEvents" type="button">Load ${Math.min(150, hiddenCount)} earlier events · ${hiddenCount} hidden</button>` : ""}${eventRows || eventPlaceholder("waiting", "No events yet.")}`;
  $("#loadOlderEvents")?.addEventListener("click", () => { state.eventVisibleLimit += 150; renderEvents(); });
  if (atBottom) log.scrollTop = log.scrollHeight;
}

function lineMarkup(value, classify) {
  return String(value ?? "").split("\n").map((line) => `<span class="${classify(line)}">${escapeHtml(line) || " "}</span>`).join("");
}

function terminalMarkup(output) {
  return lineMarkup(output, (line) => {
    if (/^(?:\$|❯|>)\s/.test(line)) return "terminal-line terminal-command";
    if (/\b(?:FAIL(?:ED)?|ERROR|Traceback|fatal)\b/i.test(line)) return "terminal-line terminal-fail";
    if (/\b(?:PASS(?:ED)?|OK|SUCCESS)\b/i.test(line)) return "terminal-line terminal-pass";
    if (/\b(?:WARN(?:ING)?|SKIP(?:PED)?|deprecated)\b/i.test(line)) return "terminal-line terminal-warn";
    if (/(?:^|\s)[\w./-]+:\d+(?::\d+)?/.test(line)) return "terminal-line terminal-path";
    return "terminal-line";
  });
}

function diffMarkup(patch) {
  return lineMarkup(patch, (line) => {
    if (/^(?:diff --git|index |--- |\+\+\+ )/.test(line)) return "diff-line diff-file";
    if (/^@@/.test(line)) return "diff-line diff-hunk";
    if (/^\+/.test(line)) return "diff-line diff-add";
    if (/^-/.test(line)) return "diff-line diff-delete";
    if (/^\\ No newline/.test(line)) return "diff-line diff-note";
    return "diff-line diff-context";
  });
}

function renderChecks(checks) {
  $("#checkResults").innerHTML = checks.length ? checks.map((check) => { const pass = Number(check.returncode) === 0; return `<div class="check-card"><div class="check-head"><span>${escapeHtml(check.command || "No checks configured")}</span><strong class="${pass ? "check-pass" : "check-fail"}">${check.skipped ? "SKIPPED" : pass ? "PASS" : `FAIL ${check.returncode}`}</strong></div><pre class="check-output">${terminalMarkup(truncateText(check.output || "No output."))}</pre></div>`; }).join("") : `<div class="check-output"><span class="terminal-line">Checks have not run yet.</span></div>`;
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
  const strength = evidenceStrength(evaluation.confidence);
  $("#evaluationResults").innerHTML = evaluation.version ? `
    <div class="evaluation-head"><strong>Evidence strength: ${escapeHtml(strength.label)}</strong><span>${escapeHtml(evaluation.decision || "human_review")}</span></div>
    <p class="evaluation-note">Heuristic synthesis of observed signals. It is not a delivery probability; hard gates and unknowns remain separate.</p>
    ${components.map((item) => { const signal = evidenceStrength(item.score); return `<div class="evaluation-row"><div><strong>${escapeHtml(item.id)}</strong><small>${escapeHtml(item.kind || "signal")}</small></div><span class="evidence-${escapeHtml(signal.tone)}">${escapeHtml(signal.label)}</span><span class="${item.verdict === "fail" ? "check-fail" : "check-pass"}">${escapeHtml(item.verdict || "—")}</span></div>`; }).join("")}
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
  $("#diffPatch").innerHTML = diffMarkup(truncateText(state.selectedDiff.patch || "No diff yet.", 120000));
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
function setConnection(online) {
  $(".connection")?.classList.toggle("online", online);
  if ($("#connectionLabel")) $("#connectionLabel").textContent = online ? "Live" : "Reconnecting";
}

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
  const destination = state.selected?.lane || "the task agent";
  const actionHint = ` “Use as feedback” only drafts text. “Send & resume” sends it to ${destination} in the saved task session.`;
  const defaultMessage = (info.mode === "local_cli"
    ? (info.configured ? `${assistantProviderLabel(provider)} ready. Scratch workspace; selected context only.` : `${assistantProviderLabel(provider)} is not on PATH.`)
    : (info.configured ? `${assistantProviderLabel(provider)} ready via ${info.env}; model ${info.model}.` : `Direct API mode requires ${info.env || (provider === "anthropic" ? "ANTHROPIC_API_KEY" : "OPENAI_API_KEY")} in the server environment.`)) + actionHint;
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
  `).join("") : `<div class="assistant-empty"><strong>Draft only.</strong> Nothing reaches the task agent until you choose “Send &amp; resume”.</div>`;
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

function controlledRecovery(run) {
  const error = String(run?.last_error || run?.delivery?.error || "");
  if (run?.failure?.class === "agent_version_incompatible") {
    return {label: "AGENT VERSION", title: run.failure.title, copy: `${run.failure.message} ${run.failure.action}`, prompt: "Retry this preserved task with a model supported by the installed agent CLI. Do not redo completed work.", action: "Retry compatibly"};
  }
  if (run?.failure?.class === "mcp_authentication") {
    return {label: "MCP AUTHENTICATION", title: run.failure.title, copy: `${run.failure.message} ${run.failure.action}`, prompt: "Continue the preserved task without the unavailable MCP integration if it is optional; otherwise state the exact authentication step required.", action: "Retry after reconnect"};
  }
  if (/(?:\.git\/worktrees|index\.lock|gitdir|outside the writable sandbox).*(?:operation not permitted|permission denied)|(?:operation not permitted|permission denied).*(?:\.git\/worktrees|index\.lock|gitdir)/i.test(error)) {
    return {
      label: "GIT WORKTREE ACCESS",
      title: "Retry with scoped Git metadata access",
      copy: "The artifact branch is preserved. Odysseus will let Codex write only the linked repository's Git metadata; this is not full filesystem elevation. If host policy still blocks it, continue in the terminal.",
      prompt: "Continue the interrupted Git operation in this existing worktree. Verify the current rebase or merge state, resolve only the recorded conflict, stage the intended files, finish the Git operation, and rerun the relevant checks.",
      action: "Retry with Git access",
    };
  }
  if (/budget exceeded|token budget|tool-call budget|cost budget/i.test(error)) {
    return {label: "BUDGET REACHED", title: "Choose a smaller recovery", copy: "The run stopped at its configured guardrail. Increase the limit in Settings or give the agent a narrower instruction; unknown cost is never treated as zero.", prompt: "Inspect the preserved work and finish only the smallest remaining change. Avoid re-reading or rewriting completed areas.", action: "Resume narrowly"};
  }
  if (/requires approval|permission request/i.test(error)) {
    return {label: "PERMISSION REQUIRED", title: "Approve or replace the blocked command", copy: "No command was silently elevated. Explain the safe alternative below, or continue in the terminal if you intentionally want to run the exact command yourself.", prompt: "Continue without broad permission escalation. Use the narrowest safe command that completes the task, and ask again if a privileged action is still required.", action: "Retry safely"};
  }
  return null;
}

function renderRecoveryCard(run) {
  const visible = canInlineResume(run);
  $("#recoveryCard").classList.toggle("hidden", !visible);
  if (!visible) return;
  const attention = run.status === "attention";
  const recovery = attention ? null : controlledRecovery(run);
  $("#recoveryLabel").textContent = attention ? "YOUR ANSWER" : recovery?.label || "RECOVERY";
  $("#recoveryTitle").textContent = attention ? "Answer and continue this task" : recovery?.title || "Resume this task with feedback";
  $("#recoveryCopy").textContent = attention ? "Your answer returns to the same agent thread and worktree." : recovery?.copy || "The branch and saved agent thread are preserved. Explain what to investigate or fix next.";
  $("#inlineResume").textContent = recovery?.action || (attention ? "Send answer & resume" : "Resume with feedback");
  if (recovery && $("#inlineFeedback").dataset.recoveryRun !== run.id) {
    $("#inlineFeedback").value = recovery.prompt;
    $("#inlineFeedback").dataset.recoveryRun = run.id;
  }
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
  if (action === "assistant") {
    state.assistantOpen = !state.assistantOpen;
    $("#assistantPanel").classList.toggle("hidden", !state.assistantOpen);
    $(".detail-body").classList.toggle("assistant-closed", !state.assistantOpen);
    renderActions(state.selected);
    if (state.assistantOpen) window.requestAnimationFrame(() => $("#assistantComposer")?.focus());
    return;
  }
  if (action === "resume") { $("#feedbackDialog").showModal(); return; }
  if (action === "apply") {
    const run = state.selected;
    const approved = await confirmChoice({eyebrow: "APPLY LOCALLY", title: `Apply this change to ${run.base_ref || "the source branch"}?`, lead: "This updates your source checkout.", message: "Odysseus proceeds only if the checkout is clean and compatible. A conflicting merge is aborted automatically and the approved change remains safe.", confirmLabel: "Apply to repository"});
    if (!approved) return;
  }
  if (action === "draft-pr") {
    const approved = await confirmChoice({eyebrow: "PUBLISH FOR REVIEW", title: "Create a draft pull request?", lead: "The task branch will be pushed to GitHub.", message: "Your local source checkout remains unchanged. GitHub CI will be watched after the pull request is created.", confirmLabel: "Create draft PR"});
    if (!approved) return;
  }
  try {
    const result = await api(`/api/runs/${encodeURIComponent(state.selectedId)}/${action}`, {method: "POST", body: "{}"});
    if (action === "takeover") await copyCommand(result.command);
    else toast(action === "accept" ? "Artifact accepted. Integrate it to change the source repository." : action === "apply" ? "Artifact integrated into the source repository." : action === "draft-pr" ? "Draft pull request created." : action === "ci-poll" ? "GitHub checks refreshed." : `Action completed: ${action}`);
    await refreshRuns(); await refreshSelected();
  } catch (error) { toast(error.message, true); }
}

function attentionItemLabel(item) {
  if (item.type === "evaluation_review") return "Evaluation needs review";
  if (item.type === "evaluation_failed" && /requires operator review|inconclusive|needs review/i.test(String(item.message || ""))) return "Evaluation needs review";
  if (item.type === "evaluation_failed") return "Evaluation failed";
  if (item.type === "review_ready") return "Artifact ready for review";
  if (item.type === "merge_conflict") return "Integration conflict";
  return statusLabel(item.type);
}

function renderAttentionEvent(item) {
  const options = item.options || [];
  const primaryOption = item.type === "permission_request" ? null : (options.find((option) => option.id !== "takeover") || options[0]);
  const extraOptions = item.type === "permission_request" ? [] : options.filter((option) => option !== primaryOption && option.id !== "takeover");
  const handledByGroup = ["review", "review_ready", "evaluation_failed", "evaluation_review", "permission_request"].includes(item.type) && item.run_id && !primaryOption;
  const actionLabel = item.type === "merge_conflict" ? "Resolve integration" : item.type === "question" ? "Answer" : "Give guidance";
  const primary = handledByGroup
    ? ""
    : primaryOption
    ? `<button class="primary" data-attention-answer="${escapeHtml(item.id)}" data-answer="${escapeHtml(primaryOption.id)}" type="button">${escapeHtml(primaryOption.label)}</button>`
    : `<button class="primary" data-attention-custom="${escapeHtml(item.id)}" type="button">${escapeHtml(actionLabel)}</button>`;
  const extras = extraOptions.map((option) => `<button class="ghost" data-attention-answer="${escapeHtml(item.id)}" data-answer="${escapeHtml(option.id)}" type="button">${escapeHtml(option.label)}</button>`).join("");
  const detail = item.data || {};
  const conflicts = detail.conflicts || [];
  const preserved = detail.preserved_branches || detail.preserved || [];
  const conflictBody = item.type === "merge_conflict" ? `<div class="attention-conflict-list"><strong>Conflicting files</strong>${conflicts.length ? conflicts.map((file) => `<code>${escapeHtml(file)}</code>`).join("") : `<span>Unknown</span>`}<strong>Preserved branches</strong>${preserved.length ? preserved.map((branch) => `<code>${escapeHtml(branch)}</code>`).join("") : `<span>Source and integration branches are preserved.</span>`}</div>` : "";
  const message = item.type === "merge_conflict" ? "Prerequisite: resolve listed files." : item.message;
  return `<section class="attention-group-event"><div class="attention-event-copy"><div class="attention-event-head"><strong>${escapeHtml(attentionItemLabel(item))}</strong><span>${escapeHtml(relativeTime(item.created_at))} ago</span></div><p title="${escapeHtml(message)}">${escapeHtml(message)}</p>${conflictBody}</div><div class="attention-event-actions">${primary}<details class="card-more-actions"><summary>More</summary><div>${extras}<button class="ghost" data-attention-custom="${escapeHtml(item.id)}" type="button">${escapeHtml(actionLabel)}</button><button class="ghost" data-attention-resolve="${escapeHtml(item.id)}" type="button">Resolve decision</button></div></details></div></section>`;
}

async function refreshAttention() {
  state.attention = relevantAttentionItems((await api("/api/attention?status=open")).items);
  const groups = groupAttention();
  const highPriority = groups.filter((group) => ["critical", "high"].includes(group.priority)).length;
  const multiple = groups.filter((group) => group.items.length > 1).length;
  $("#attentionNavCount").textContent = groups.length || "";
  $("#sidebarPrimaryAttentionCount").textContent = groups.length || "";
  renderProjectTree(); renderWork(); renderHome();
  $("#attentionSummary").innerHTML = [
    [groups.length, "tasks need you"],
    [state.attention.length, "open decisions"],
    [highPriority, "high priority"],
    [multiple, "multi-decision tasks"],
  ].map(([count, label]) => `<div><strong>${escapeHtml(count)}</strong><span>${escapeHtml(label)}</span></div>`).join("");
  $("#attentionList").innerHTML = groups.length ? groups.map((group) => {
    const run = group.run_id ? state.runs.find((item) => item.id === group.run_id) : null;
    const first = group.items[0];
    const title = run ? runTitle(run) : (first.title || "Decision required");
    const classes = `stack-card attention-card attention-group priority-${escapeHtml(group.priority)}${group.items.some((item) => item.type === "merge_conflict") ? " attention-conflict" : ""}`;
    return `<article class="${classes}"><header class="attention-group-head"><span class="mini-status status-${group.priority === "high" || group.priority === "critical" ? "failed" : "queued"}">${escapeHtml(group.priority)}</span><h3 title="${escapeHtml(title)}">${escapeHtml(title)}</h3><span class="run-id">${group.items.length} decision${group.items.length === 1 ? "" : "s"}</span>${group.run_id ? `<button class="ghost compact" data-open-run="${escapeHtml(group.run_id)}" type="button">Open task</button>` : ""}</header><div class="attention-group-events">${group.items.map(renderAttentionEvent).join("")}</div></article>`;
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
  return `<div class="dag-graph" role="img" aria-label="Task dependency graph with ${nodes.length} tasks and ${edges.length} dependencies">
    ${Array.from({length: maxDepth + 1}, (_, depth) => `<div class="dag-column" aria-label="Dependency level ${depth + 1}">
      ${nodes.filter((node) => (depthMemo.get(node.key) || 0) === depth).map((node) => {
        const stateLabel = epicNodeState(node.run, node.task);
        const parentRuns = (node.depends_on || []).map((key) => runByKey.get(key) || state.runs.find((run) => run.id === key)).filter(Boolean);
        const waiting = stateLabel === "Blocked" ? parentRuns.find((run) => !["accepted", "pr_created", "completed"].includes(run.status)) : null;
        return `<div class="dag-graph-node dag-state-${stateLabel.toLowerCase().replaceAll(" ", "-")}" tabindex="0">
          <span>${escapeHtml(stateLabel)}</span><strong>${escapeHtml(node.title || node.key)}</strong><small>${escapeHtml(node.depends_on?.length ? `after ${node.depends_on.join(", ")}` : "root task")}</small>${waiting ? `<em>Waiting for ${escapeHtml(runTitle(waiting, waiting.id))}</em>` : ""}</div>`;
      }).join("")}
    </div>`).join("")}
  </div>${edges.length ? `<p class="dag-edge-list">Edges: ${escapeHtml(edges.join("; "))}</p>` : `<p class="dag-edge-list">No dependencies.</p>`}<ol class="dag-linear-fallback">${nodes.map((node) => `<li><strong>${escapeHtml(node.title || node.key)}</strong><span>${escapeHtml(epicNodeState(node.run, node.task))}</span><small>${escapeHtml(node.depends_on?.length ? `Depends on ${node.depends_on.join(", ")}` : "No dependencies")}</small></li>`).join("")}</ol>`;
}

function planGraphIntelligence(epic, linkedRuns, plannedTasks) {
  const items = linkedRuns.length ? linkedRuns : plannedTasks;
  const keyOf = (item, index) => String(item.task_key || item.id || `task-${index + 1}`);
  const keys = new Set(items.map(keyOf));
  const depthMemo = new Map();
  const depthOf = (item, index, visiting = new Set()) => {
    const key = keyOf(item, index);
    if (depthMemo.has(key)) return depthMemo.get(key);
    if (visiting.has(key)) return 0;
    const nextVisiting = new Set(visiting).add(key);
    const dependencies = (item.dependency_keys || item.depends_on || []).filter((dependency) => keys.has(String(dependency)));
    const depth = dependencies.length ? 1 + Math.max(...dependencies.map((dependency) => {
      const parentIndex = items.findIndex((candidate, candidateIndex) => keyOf(candidate, candidateIndex) === String(dependency));
      return parentIndex < 0 ? 0 : depthOf(items[parentIndex], parentIndex, nextVisiting);
    })) : 0;
    depthMemo.set(key, depth);
    return depth;
  };
  const depths = items.map((item, index) => depthOf(item, index));
  const criticalStages = depths.length ? Math.max(...depths) + 1 : 0;
  const breadth = depths.reduce((counts, depth) => counts.set(depth, (counts.get(depth) || 0) + 1), new Map());
  const peakParallel = breadth.size ? Math.max(...breadth.values()) : 0;
  const humanGates = items.filter((item) => ["reviewer", "human_gate"].includes(String(item.role || item.kind || ""))).length;
  const conflictRisks = linkedRuns.filter((run) => ["medium", "high"].includes(String(run.merge_analysis?.risk || "").toLowerCase())).length;
  const budgetTokens = items.reduce((total, item) => total + Number(item.budgets?.max_tokens || item.budget?.tokens || 0), 0);
  const budgetCost = items.reduce((total, item) => total + Number(item.budgets?.max_cost_usd || item.budget?.usd || 0), 0);
  return {criticalStages, peakParallel, humanGates, conflictRisks, budgetTokens, budgetCost};
}

function planEstimateLabel(task) {
  const estimate = task?.estimate || {};
  const min = Number(estimate.cost_usd_min);
  const max = Number(estimate.cost_usd_max);
  const hasMin = estimate.cost_usd_min !== null && estimate.cost_usd_min !== undefined && Number.isFinite(min);
  const hasMax = estimate.cost_usd_max !== null && estimate.cost_usd_max !== undefined && Number.isFinite(max);
  if (!hasMin && !hasMax) return "Cost not estimated";
  const range = hasMin && hasMax ? `$${min.toFixed(2)}–$${max.toFixed(2)}` : hasMax ? `up to $${max.toFixed(2)}` : `from $${min.toFixed(2)}`;
  return `${range} · ${escapeHtml(estimate.confidence || "unknown")} confidence`;
}

function planStudioTask() {
  return state.planStudio?.plan?.tasks?.find((task) => task.task_key === state.planStudioTaskKey) || null;
}

function planStudioTaskSources(task, sources) {
  const refs = new Set(task?.source_refs || []);
  return sources.filter((source) => (source.sections || []).some((section) => refs.has(section.ref)));
}

function planStudioVisibleTasks(tasks, sources) {
  const originalOrder = new Map(tasks.map((task, index) => [task.task_key, index]));
  let visible = state.planStudioSourceFilter === "all"
    ? [...tasks]
    : tasks.filter((task) => planStudioTaskSources(task, sources).some((source) => source.path === state.planStudioSourceFilter));
  if (state.planStudioTaskSort === "source") {
    const sourceOrder = new Map(sources.map((source, index) => [source.path, index]));
    visible.sort((left, right) => {
      const leftIndex = Math.min(...planStudioTaskSources(left, sources).map((source) => sourceOrder.get(source.path) ?? 9999), 9999);
      const rightIndex = Math.min(...planStudioTaskSources(right, sources).map((source) => sourceOrder.get(source.path) ?? 9999), 9999);
      return leftIndex - rightIndex || originalOrder.get(left.task_key) - originalOrder.get(right.task_key);
    });
  } else if (state.planStudioTaskSort === "dependency") {
    visible.sort((left, right) => (left.depends_on || []).length - (right.depends_on || []).length || originalOrder.get(left.task_key) - originalOrder.get(right.task_key));
  }
  return visible;
}

function planStudioNumber(value) {
  return value === "" || value === null || value === undefined ? null : Number(value);
}

function updatePlanStudioTaskFromEditor() {
  const task = planStudioTask();
  const form = $("#planStudioEditor");
  if (!task || !form) return;
  const data = new FormData(form);
  task.title = String(data.get("title") || "").trim();
  task.outcome = String(data.get("outcome") || "").trim();
  task.task = String(data.get("task") || "").trim();
  task.acceptance_criteria = String(data.get("acceptance_criteria") || "").split("\n").map((item) => item.trim()).filter(Boolean);
  task.required_evidence = String(data.get("required_evidence") || "").split("\n").map((item) => item.trim()).filter(Boolean);
  task.depends_on = [...form.elements.depends_on.selectedOptions].map((option) => option.value);
  task.execution_profile = {
    ...(task.execution_profile || {}), version: "execution-profile-v1",
    mode: String(data.get("profile_mode") || "auto"), harness: String(data.get("harness") || "auto"),
    model: String(data.get("model") || "").trim(),
    environment: String(data.get("environment") || "isolated_worktree"),
    policy: String(data.get("policy") || "standard").trim(),
    skills: String(data.get("skills") || "").split(",").map((item) => item.trim()).filter(Boolean),
    review_lane: String(data.get("review_lane") || "auto"),
    review_model: String(data.get("review_model") || "").trim(),
    reason: String(data.get("profile_reason") || "").trim(),
  };
  task.estimate = {
    ...(task.estimate || {}), version: "task-estimate-v1",
    cost_usd_min: planStudioNumber(data.get("cost_min")), cost_usd_max: planStudioNumber(data.get("cost_max")),
    duration_minutes_min: planStudioNumber(data.get("duration_min")), duration_minutes_max: planStudioNumber(data.get("duration_max")),
    confidence: String(data.get("estimate_confidence") || "unknown"), basis: String(data.get("estimate_basis") || "").trim(),
  };
  state.planStudioDirty = true;
  $("#planStudioSave").textContent = "Save draft · unsaved";
}

function renderPlanStudio() {
  const epic = state.planStudio;
  if (!epic) return;
  const tasks = epic.plan?.tasks || [];
  const sources = epic.source_documents || [];
  if (state.planStudioSourceFilter !== "all" && !sources.some((source) => source.path === state.planStudioSourceFilter)) state.planStudioSourceFilter = "all";
  const visibleTasks = planStudioVisibleTasks(tasks, sources);
  if (!visibleTasks.some((task) => task.task_key === state.planStudioTaskKey)) state.planStudioTaskKey = visibleTasks[0]?.task_key || "";
  const selected = planStudioTask();
  const sourceIndex = Math.min(Number(epic._sourceIndex || 0), Math.max(0, (epic.source_documents || []).length - 1));
  const source = (epic.source_documents || [])[sourceIndex];
  const version = epic.plan_version || {};
  const locked = Boolean(epic.approved);
  $("#planStudioTitle").textContent = epic.title || "Review plan";
  $("#planStudioSummary").textContent = epic.plan?.summary || "Review requirements, task contracts, evidence and execution profiles.";
  $("#planStudioVersion").textContent = version.id ? `v${version.number} · ${String(version.sha256 || "").slice(0, 8)}` : locked ? "Legacy approved plan" : "Unsaved draft";
  $("#planStudioSave").classList.toggle("hidden", locked);
  $("#planStudioApprove").classList.toggle("hidden", locked);
  $("#planStudioSourceCount").textContent = `${(epic.source_documents || []).length} source${(epic.source_documents || []).length === 1 ? "" : "s"}`;
  const estimated = tasks.filter((task) => task.estimate?.cost_usd_min !== null && task.estimate?.cost_usd_min !== undefined && task.estimate?.cost_usd_max !== null && task.estimate?.cost_usd_max !== undefined);
  const totalMin = estimated.reduce((sum, task) => sum + Number(task.estimate.cost_usd_min), 0);
  const totalMax = estimated.reduce((sum, task) => sum + Number(task.estimate.cost_usd_max), 0);
  $("#planStudioEstimate").textContent = estimated.length ? `$${totalMin.toFixed(2)}–$${totalMax.toFixed(2)} · ${estimated.length}/${tasks.length} tasks estimated` : "Cost unknown · no calibrated history";
  const impact = epic.source_impact || {status: "current", affected_task_keys: []};
  $("#planStudioImpact").classList.toggle("hidden", impact.status !== "changed");
  $("#planStudioImpact").innerHTML = impact.status === "changed" ? `<strong>Source changed</strong><span>${impact.affected_task_keys?.length ? `${escapeHtml(impact.affected_task_keys.join(", "))} require review.` : "No linked task contract is affected."}</span>${locked ? "" : `<button class="ghost" id="planStudioRefreshSources" type="button">Freeze current source</button>`}` : "";
  $("#planStudioSourceTabs").innerHTML = (epic.source_documents || []).map((item, index) => `<button class="${index === sourceIndex ? "active" : ""}" data-plan-source="${index}" type="button"><span>${escapeHtml(item.kind || "source")}</span><strong>${escapeHtml(item.title || item.path)}</strong></button>`).join("");
  const linkedRefs = new Set(selected?.source_refs || []);
  $("#planStudioSourceSections").innerHTML = source ? (source.sections || []).map((section) => `<button class="plan-source-section ${linkedRefs.has(section.ref) ? "linked" : ""}" data-source-ref="${escapeHtml(section.ref)}" type="button" ${locked ? "disabled" : ""}><span>${escapeHtml(section.ref)}</span><p>${escapeHtml(section.text)}</p>${linkedRefs.has(section.ref) ? `<em>Used by ${escapeHtml(selected.task_key)}</em>` : ""}</button>`).join("") : `<div class="empty-list">No frozen source content.</div>`;
  $("#planStudioSourceFilter").innerHTML = `<option value="all">All sources</option>${sources.map((item) => `<option value="${escapeHtml(item.path)}" ${state.planStudioSourceFilter === item.path ? "selected" : ""}>${escapeHtml(planSourceKindLabel(item.kind))}: ${escapeHtml(item.title || item.path)}</option>`).join("")}`;
  $("#planStudioTaskSort").value = state.planStudioTaskSort;
  const originalOrder = new Map(tasks.map((task, index) => [task.task_key, index + 1]));
  $("#planStudioTaskList").innerHTML = visibleTasks.length ? visibleTasks.map((task) => { const linkedSources = planStudioTaskSources(task, sources); return `<button class="plan-task-card ${task.task_key === state.planStudioTaskKey ? "active" : ""}" data-plan-task="${escapeHtml(task.task_key)}" type="button"><span>T${originalOrder.get(task.task_key)}</span><div><strong>${escapeHtml(task.title || task.task_key)}</strong><small>${escapeHtml(task.outcome || "Finished outcome not specified")}</small><em>${escapeHtml(task.execution_profile?.mode === "override" ? `${task.execution_profile.harness || "manual"} override` : `Auto · ${task.execution_profile?.reason || "routing at execution"}`)} · ${linkedSources.length ? linkedSources.map((item) => item.title || item.path).join(", ") : "no source linked"}</em></div><b>${planEstimateLabel(task)}</b></button>`; }).join("") : `<div class="empty-list">No tasks are linked to this source yet. Select a task under All sources, then link source paragraphs.</div>`;

  const form = $("#planStudioEditor");
  form.classList.toggle("hidden", !selected);
  if (selected) {
    form.elements.title.value = selected.title || "";
    form.elements.task_key.value = selected.task_key || "";
    form.elements.outcome.value = selected.outcome || "";
    form.elements.task.value = selected.task || "";
    form.elements.acceptance_criteria.value = (selected.acceptance_criteria || []).join("\n");
    form.elements.required_evidence.value = (selected.required_evidence || []).join("\n");
    form.elements.profile_mode.value = selected.execution_profile?.mode || "auto";
    form.elements.harness.value = ["auto", "codex", "claude"].includes(selected.execution_profile?.harness) ? selected.execution_profile.harness : "auto";
    form.elements.model.value = selected.execution_profile?.model || "";
    form.elements.environment.value = ["isolated_worktree", "host", "docker", "devcontainer"].includes(selected.execution_profile?.environment) ? selected.execution_profile.environment : "isolated_worktree";
    form.elements.policy.value = selected.execution_profile?.policy || "standard";
    form.elements.skills.value = (selected.execution_profile?.skills || []).join(", ");
    form.elements.review_lane.value = ["auto", "codex", "claude"].includes(selected.execution_profile?.review_lane) ? selected.execution_profile.review_lane : "auto";
    form.elements.review_model.value = selected.execution_profile?.review_model || "";
    form.elements.profile_reason.value = selected.execution_profile?.reason || "Auto will select from repository evidence";
    form.elements.depends_on.innerHTML = tasks.filter((task) => task.task_key !== selected.task_key).map((task) => `<option value="${escapeHtml(task.task_key)}" ${(selected.depends_on || []).includes(task.task_key) ? "selected" : ""}>${escapeHtml(task.title || task.task_key)}</option>`).join("");
    form.elements.cost_min.value = selected.estimate?.cost_usd_min ?? ""; form.elements.cost_max.value = selected.estimate?.cost_usd_max ?? "";
    form.elements.duration_min.value = selected.estimate?.duration_minutes_min ?? ""; form.elements.duration_max.value = selected.estimate?.duration_minutes_max ?? "";
    form.elements.estimate_confidence.value = selected.estimate?.confidence || "unknown"; form.elements.estimate_basis.value = selected.estimate?.basis || "No calibrated repository estimate yet";
    [...form.elements].forEach((control) => { control.disabled = locked; });
  }
  $("#planStudioGraph").innerHTML = renderEpicGraph(epic);
  const dependencies = tasks.reduce((sum, task) => sum + (task.depends_on || []).length, 0);
  $("#planStudioGraphMeta").textContent = `${tasks.length} tasks · ${dependencies} dependencies`;
  $$('[data-plan-source]').forEach((button) => button.addEventListener("click", () => { epic._sourceIndex = Number(button.dataset.planSource); state.planStudioSourceFilter = sources[epic._sourceIndex]?.path || "all"; renderPlanStudio(); }));
  $$('[data-plan-task]').forEach((button) => button.addEventListener("click", () => { state.planStudioTaskKey = button.dataset.planTask; renderPlanStudio(); }));
  $$('[data-source-ref]').forEach((button) => button.addEventListener("click", () => {
    if (!selected || locked) return;
    const refs = new Set(selected.source_refs || []); const ref = button.dataset.sourceRef;
    if (refs.has(ref)) refs.delete(ref); else refs.add(ref);
    selected.source_refs = [...refs]; state.planStudioDirty = true; renderPlanStudio();
  }));
  $("#planStudioRefreshSources")?.addEventListener("click", async () => {
    try {
      state.planStudio = await api(`/api/epics/${encodeURIComponent(epic.id)}/refresh-sources`, {method: "POST", body: "{}"});
      state.planStudioDirty = true; $("#planStudioSave").textContent = "Save draft · source updated"; renderPlanStudio();
    } catch (error) { toast(error.message, true); }
  });
}

async function openPlanStudio(epicId) {
  state.planStudio = await api(`/api/epics/${encodeURIComponent(epicId)}`);
  state.planStudioTaskKey = state.planStudio.plan?.tasks?.[0]?.task_key || "";
  state.planStudioDirty = false; state.planStudioSourceFilter = "all"; state.planStudioTaskSort = "plan";
  $("#planStudioSave").textContent = "Save draft";
  renderPlanStudio();
  $("#planStudioDialog").showModal();
}

async function savePlanStudio() {
  if (!state.planStudio) return;
  updatePlanStudioTaskFromEditor();
  const saved = await api(`/api/epics/${encodeURIComponent(state.planStudio.id)}/plan`, {method: "POST", body: JSON.stringify({plan: state.planStudio.plan})});
  state.planStudio = saved;
  state.planStudioDirty = false; $("#planStudioSave").textContent = "Save draft"; renderPlanStudio();
  toast("Plan draft saved as a new immutable version.");
}

function epicSourceGroups(epic) { return new Set((epic.source_documents || []).map((source) => planSourceGroup(source.kind))); }
function epicMatchesPlanFilter(epic) {
  if (state.planFilter === "all") return true;
  if (state.planFilter.startsWith("source:")) return (epic.source_documents || []).some((source) => source.path === state.planFilter.slice(7));
  return epicSourceGroups(epic).has(state.planFilter);
}
function primaryEpicSourceGroup(epic) {
  const order = ["adr", "github", "specification", "incident", "other"];
  const groups = epicSourceGroups(epic);
  return order.find((group) => groups.has(group)) || "other";
}
function planGroupRank(epic) {
  return ["adr", "github", "specification", "incident", "other"].indexOf(primaryEpicSourceGroup(epic));
}
function planGroupLabel(group) {
  return ({adr: "Architecture decisions", github: "GitHub", specification: "Specifications", incident: "Incidents & security", other: "Other plans"})[group] || "Plans";
}
function setPlanFilter(filter) {
  state.planFilter = filter || "all";
  state.taskSourceFilter = state.planFilter.startsWith("source:") ? state.planFilter.slice(7) : "";
  setView("epics");
}
function renderPlanFilters(epics) {
  const groups = ["adr", "github", "specification", "incident", "other"];
  const counts = Object.fromEntries(groups.map((group) => [group, epics.filter((epic) => epicSourceGroups(epic).has(group)).length]));
  const exactSource = state.planFilter.startsWith("source:") ? state.planFilter.slice(7) : "";
  const exactLabel = epics.flatMap((epic) => epic.source_documents || []).find((source) => source.path === exactSource)?.title || exactSource;
  $("#planFilters").innerHTML = `<button class="${state.planFilter === "all" ? "active" : ""}" data-plan-filter="all" type="button">All <span>${epics.length}</span></button>${groups.map((group) => `<button class="${state.planFilter === group ? "active" : ""}" data-plan-filter="${group}" type="button">${escapeHtml(planGroupLabel(group))} <span>${counts[group]}</span></button>`).join("")}${exactSource ? `<span class="plan-exact-filter">Source: <strong>${escapeHtml(exactLabel)}</strong><button data-show-source-tasks type="button">Show linked tasks</button></span>` : ""}`;

  const sources = [...new Map(epics.flatMap((epic) => epic.source_documents || []).filter((source) => source.path).map((source) => [source.path, source])).values()];
  const nav = $("#planSourceNav");
  nav.classList.toggle("hidden", state.view !== "epics" || !sources.length);
  nav.innerHTML = sources.length ? `<div class="sidebar-plan-groups">${groups.filter((group) => counts[group]).map((group) => `<button class="${state.planFilter === group ? "active" : ""}" data-plan-filter="${group}" type="button"><span>${escapeHtml(planGroupLabel(group))}</span><small>${counts[group]}</small></button>`).join("")}</div><div class="sidebar-plan-source-list">${sources.slice(0, 16).map((source) => `<button class="${exactSource === source.path ? "active" : ""}" data-plan-filter="source:${escapeHtml(source.path)}" type="button" title="${escapeHtml(source.path)}"><i>${escapeHtml(planSourceKindLabel(source.kind))}</i><span>${escapeHtml(source.title || source.path)}</span></button>`).join("")}</div>` : "";
  $$('[data-plan-filter]').forEach((button) => button.addEventListener("click", () => setPlanFilter(button.dataset.planFilter)));
  $("[data-show-source-tasks]")?.addEventListener("click", () => { state.filter = "all"; renderRuns(); setView("work"); });
}

async function refreshEpics() {
  state.epics = (await api("/api/epics")).epics;
  $("#epicNavCount").textContent = state.epics.filter((epic) => ["planning", "proposed", "active"].includes(epic.status)).length || "";
  const projectEpics = activeProject() ? state.epics.filter((epic) => epic.project_id === state.projectFilter) : state.epics;
  renderPlanFilters(projectEpics);
  const visibleEpics = projectEpics.filter(epicMatchesPlanFilter);
  const orderedEpics = state.planFilter === "all" ? [...visibleEpics].sort((left, right) => planGroupRank(left) - planGroupRank(right) || String(right.created_at || "").localeCompare(String(left.created_at || ""))) : visibleEpics;
  let previousGroup = "";
  $("#epicList").innerHTML = orderedEpics.length ? orderedEpics.map((epic) => {
    const group = primaryEpicSourceGroup(epic); const groupHeading = state.planFilter === "all" && group !== previousGroup ? `<header class="plan-group-heading"><h2>${escapeHtml(planGroupLabel(group))}</h2><span>${orderedEpics.filter((item) => primaryEpicSourceGroup(item) === group).length} plan${orderedEpics.filter((item) => primaryEpicSourceGroup(item) === group).length === 1 ? "" : "s"}</span></header>` : ""; previousGroup = group;
    const graph = renderEpicGraph(epic);
    const epicProject = projectById(epic.project_id);
    const sources = epic.source_documents || [];
    const linkedRuns = (epic.run_ids || []).map((runId) => state.runs.find((run) => run.id === runId)).filter(Boolean);
    const plannedTasks = epic.plan?.tasks || [];
    const taskCount = linkedRuns.length || plannedTasks.length;
    const nodeStates = linkedRuns.length
      ? linkedRuns.map((run) => epicNodeState(run))
      : plannedTasks.map((task) => epicNodeState(null, task));
    const activeNodes = nodeStates.filter((value) => value === "Running").length;
    const readyNodes = nodeStates.filter((value) => value === "Ready").length;
    const attentionNodes = nodeStates.filter((value) => value === "Needs You" || value === "Blocked" || value === "Failed").length;
    const acceptedNodes = nodeStates.filter((value) => value === "Accepted").length;
    const intelligence = planGraphIntelligence(epic, linkedRuns, plannedTasks);
    const dependencyCount = (linkedRuns.length ? linkedRuns : plannedTasks).reduce((total, item) => total + (item.dependency_keys || item.depends_on || []).length, 0);
    const sourceLine = sources.length ? `<div class="epic-source-line"><strong>Sources</strong>${sources.map((source) => `<button data-plan-filter="source:${escapeHtml(source.path)}" type="button" title="Filter plans and tasks by this source"><b>${escapeHtml(planSourceKindLabel(source.kind))}</b>${escapeHtml(source.title || source.path)} <code>${escapeHtml(String(source.sha256 || "").slice(0, 8))}</code>${source.repeat_authorized ? `<em>forced repeat</em>` : ""}</button>`).join("")}</div>` : "";
    const runButtons = (epic.run_ids || []).map((runId) => `<button class="ghost" data-open-run="${escapeHtml(runId)}" type="button">${escapeHtml(state.runs.find((run) => run.id === runId)?.task_key || "task")}</button>`).join("");
    return `${groupHeading}<article class="stack-card epic-card">
      <div class="card-row"><span class="mini-status ${statusClass(epic.status)}">${escapeHtml(epic.status)}</span><span class="run-id">${escapeHtml(epicProject ? projectName(epicProject) : "repository")}</span></div>
      <h3>${escapeHtml(epic.title)}</h3>
      <p>${escapeHtml(epic.status === "proposed" ? "Review the dependency graph, then approve execution." : epic.status === "active" ? "Odysseus is scheduling dependency-ready tasks." : epic.plan?.summary || epic.description || "Planning...")}</p>
      <div class="epic-progress" aria-label="Plan progress"><span><strong>${taskCount}</strong> tasks</span><span><strong>${intelligence.criticalStages || "—"}</strong> critical-path stages</span><span><strong>${intelligence.peakParallel || "—"}</strong> peak parallel</span><span><strong>${epic.status === "proposed" ? readyNodes : activeNodes}</strong> ${epic.status === "proposed" ? "ready after approval" : "active"}</span><span class="${attentionNodes ? "needs" : ""}"><strong>${attentionNodes}</strong> need you</span><span><strong>${acceptedNodes}</strong> accepted</span>${intelligence.conflictRisks ? `<span class="needs"><strong>${intelligence.conflictRisks}</strong> merge risks</span>` : ""}${intelligence.humanGates ? `<span><strong>${intelligence.humanGates}</strong> human gates</span>` : ""}${intelligence.budgetTokens ? `<span><strong>${compactNumber(intelligence.budgetTokens)}</strong> token ceiling</span>` : ""}${intelligence.budgetCost ? `<span><strong>$${intelligence.budgetCost.toFixed(2)}</strong> cost ceiling</span>` : ""}</div>
      <details class="epic-graph-details" ${epic.status === "proposed" ? "open" : ""}>
        <summary><span><strong>${epic.status === "proposed" ? "Review execution graph" : "Execution graph"}</strong><small>${dependencyCount} dependenc${dependencyCount === 1 ? "y" : "ies"} · ${intelligence.criticalStages || "—"} critical-path stages · up to ${intelligence.peakParallel || "—"} parallel</small></span><span>${epic.status === "proposed" ? "Approval required" : "Open graph"}</span></summary>
        <div class="epic-graph-content">${sourceLine}${graph}</div>
      </details>
      <div class="card-actions"><button class="${epic.status === "proposed" ? "primary" : "ghost"}" data-open-plan-studio="${escapeHtml(epic.id)}" type="button">${epic.status === "proposed" ? "Review plan contract" : "Open plan contract"}</button>${runButtons ? `<details class="card-more-actions"><summary>Open task${linkedRuns.length === 1 ? "" : "s"}</summary><div>${runButtons}</div></details>` : ""}</div>
    </article>`;
  }).join("") : `<div class="empty-card">No plans yet.</div>`;
  $$('[data-open-plan-studio]').forEach((button) => button.addEventListener("click", () => openPlanStudio(button.dataset.openPlanStudio).catch((error) => toast(error.message, true))));
  $$('[data-open-run]').forEach((button) => button.addEventListener("click", () => selectRun(button.dataset.openRun)));
  $$('#epicList [data-plan-filter]').forEach((button) => button.addEventListener("click", () => setPlanFilter(button.dataset.planFilter)));
}

async function refreshProjects() {
  state.projects = (await api("/api/projects")).projects.filter((project) => project.git_repository !== false);
  const projectOptions = state.projects.map((project) => `<option value="${escapeHtml(project.id)}">${escapeHtml(projectOptionLabel(project))}</option>`).join("");
  $("#projectFilter").innerHTML = `<option value="all">All repositories</option>${projectOptions}`; $("#projectFilter").value = state.projectFilter;
  const preferred = preferredProjectId();
  $("#taskProjectSelect").innerHTML = projectOptions || `<option value="">Add a repository first</option>`;
  $("#epicProjectSelect").innerHTML = projectOptions || `<option value="">Add a repository first</option>`;
  $("#skillsProjectSelect").innerHTML = projectOptions || `<option value="">Add a repository first</option>`;
  $("#homeProjectSelect").innerHTML = projectOptions || `<option value="">Add a repository first</option>`;
  if (preferred) { $("#taskProjectSelect").value = preferred; $("#epicProjectSelect").value = preferred; $("#skillsProjectSelect").value = preferred; $("#homeProjectSelect").value = preferred; }
  syncCustomProject($("#taskProjectSelect"), $("#taskCustomProject"));
  syncCustomProject($("#epicProjectSelect"), $("#epicCustomProject"));
  $("#inboxProjectSelect").innerHTML = `<option value="">No repository</option>${projectOptions}`;
  $("#githubProject").innerHTML = state.projects.filter((project) => project.github_url).map((project) => `<option value="${escapeHtml(project.id)}">${escapeHtml(projectOptionLabel(project))}</option>`).join("") || `<option value="">No GitHub repositories</option>`;
  renderProjects(); renderRuns(); renderProjectTree(); renderWork(); renderHome(); updateGitHubLink();
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
  $("#parallelLabel").textContent = `${state.bootstrap.max_parallel} running max`;
  const options = (selected) => agentLaneOptions(selected);
  $("#laneSelect").innerHTML = agentLaneOptions("auto", true);
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
  $("#issueList").innerHTML = issues.length ? issues.map((issue) => `<article class="stack-card"><div class="card-row"><span class="mini-status status-queued">issue #${issue.number}</span><a class="run-id" href="${escapeHtml(issue.url)}" target="_blank" rel="noreferrer">Open ↗</a></div><h3>${escapeHtml(issue.title)}</h3><p>${escapeHtml(issue.body || "No description.")}</p><div class="card-meta">${(issue.labels || []).map((label) => `<span>${escapeHtml(label.name)}</span>`).join("")}</div><div class="card-actions"><button class="primary" data-import-issue="${issue.number}" type="button">Propose plan</button></div></article>`).join("") : `<div class="empty-card">No open issues.</div>`;
  $$('[data-import-issue]').forEach((button) => button.addEventListener("click", async () => { const issue = issues.find((item) => String(item.number) === button.dataset.importIssue); try { button.disabled = true; button.textContent = "Reading issue…"; const epic = await api("/api/github/import", {method: "POST", body: JSON.stringify({project_id: projectId, number: issue.number})}); toast(epic.duplicate ? "Existing plan refreshed from GitHub." : "Plan proposed. Review it before agents start."); await Promise.all([refreshEpics(), refreshRuns()]); setView("epics"); } catch (error) { toast(error.message, true); } finally { button.disabled = false; button.textContent = "Propose plan"; } }));
}

function portfolioPercent(value) {
  return value === null || value === undefined ? "—" : `${Math.round(Number(value) * 100)}%`;
}

function portfolioMoney(value) {
  return value === null || value === undefined ? "—" : `$${Number(value).toFixed(2)}`;
}

function portfolioMetric(label, value, note, tone = "") {
  return `<article class="portfolio-kpi ${escapeHtml(tone)}" title="${escapeHtml(`${label}: ${note}`)}"><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong><p>${escapeHtml(note)}</p></article>`;
}

function renderHome() {
  const attention = groupAttention().slice(0, 4);
  const workingStatuses = new Set(["queued", "starting", "running", "checking", "reviewing", "planning"]);
  const working = state.runs
    .filter((run) => run.kind !== "tmux" && workingStatuses.has(run.status))
    .sort((left, right) => new Date(right.updated_at || 0) - new Date(left.updated_at || 0))
    .slice(0, 6);
  $("#homeAttentionList").innerHTML = attention.length ? attention.map((group) => {
    const first = group.items[0] || {};
    const project = projectById(group.project_id);
    return `<button class="home-row needs-action" data-home-run="${escapeHtml(group.run_id)}" type="button"><span class="home-row-state">${escapeHtml(String(group.items.length))}</span><span><small>${escapeHtml(projectName(project))} · ${escapeHtml(attentionItemLabel(first))}</small><strong>${escapeHtml(first.run_title || first.title || "Decision required")}</strong><em>${escapeHtml(first.message || first.task || "Open the task to continue.")}</em></span><b>${group.items.length > 1 ? `${group.items.length} decisions` : "Review"} →</b></button>`;
  }).join("") : `<div class="home-empty"><strong>Nothing needs you.</strong><span>Odysseus will surface a decision here instead of making you watch logs.</span></div>`;
  $("#homeWorkingList").innerHTML = working.length ? working.map((run) => `<button class="home-row" data-home-run="${escapeHtml(run.id)}" type="button"><span class="home-row-state is-running"></span><span><small>${escapeHtml(projectName(projectById(run.project_id)))} · ${escapeHtml(statusLabel(run.status))}</small><strong>${escapeHtml(runTitle(run))}</strong><em>${escapeHtml(runActionLine(run))}</em></span><b>${escapeHtml(relativeTime(run.updated_at))} →</b></button>`).join("") : `<div class="home-empty"><strong>No agents are running.</strong><span>Describe one finished change above to start.</span></div>`;
  $$('[data-home-run]').forEach((button) => button.addEventListener("click", () => button.dataset.homeRun ? selectRun(button.dataset.homeRun) : setView("attention")));
}

function openTaskDialog({prompt = "", projectId = ""} = {}) {
  prepareProjectSelect($("#taskProjectSelect"), $("#taskCustomProject"));
  if (projectId && projectById(projectId)) {
    $("#taskProjectSelect").value = projectId;
    $("#taskProjectSelect").dispatchEvent(new Event("change"));
  }
  state.taskAgentRecommendation = null;
  renderTaskAgentRecommendation();
  $("#taskPrompt").value = prompt;
  $("#taskPrompt").dispatchEvent(new Event("input"));
  refreshTaskSkillChoices().catch((error) => toast(error.message, true));
  scheduleTaskAgentRecommendation();
  $("#taskDialog").showModal();
  window.requestAnimationFrame(() => $("#taskPrompt").focus());
}

function focusTaskComposer(projectId = "") {
  if (!state.projects.length) { $("#projectDialog").showModal(); return; }
  setView("portfolio");
  if (projectId && projectById(projectId)) $("#homeProjectSelect").value = projectId;
  window.requestAnimationFrame(() => $("#homeTaskPrompt").focus());
}

async function continueHomeTask() {
  if (!state.projects.length) { $("#projectDialog").showModal(); return; }
  const prompt = $("#homeTaskPrompt").value.trim();
  if (!prompt) { $("#homeTaskPrompt").focus(); toast("Tell the agent what to change first.", true); return; }
  const projectId = $("#homeProjectSelect").value || preferredProjectId();
  const project = projectById(projectId);
  if (!project) { toast("Choose a repository first.", true); return; }
  const button = $("#homeStartTask");
  const status = $("#homeTaskStatus");
  try {
    $("#homeTaskPrompt").value = "";
    status.textContent = `Starting the task in ${projectName(project)}...`;
    status.classList.remove("hidden");
    button.disabled = true;
    button.textContent = "Starting...";
    const run = await api("/api/runs", {method: "POST", body: JSON.stringify({task: prompt, project_path: project.path, lane: state.bootstrap.default_lane, auto_route: true, origin: "web", skill_mode: "auto"})});
    status.textContent = "Task started. Opening it now...";
    toast(`Task started: ${runTitle(run)}`);
    await Promise.all([refreshRuns(), refreshProjects()]);
    await selectRun(run.id);
  } catch (error) {
    $("#homeTaskPrompt").value = prompt;
    status.classList.add("hidden");
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "Start task";
    if (state.view === "tasks") status.classList.add("hidden");
  }
}

function renderPortfolioPreview() {
  const days = Number($("#portfolioWindow")?.value || 7);
  const cutoff = Date.now() - days * 86400000;
  const runs = state.runs.filter((run) => run.kind !== "tmux" && new Date(run.created_at || 0).getTime() >= cutoff);
  const started = runs.filter((run) => run.started_at);
  const delivered = started.filter((run) => run.status === "pr_created" || deliveredDeliveryStatuses.has(run.delivery?.status));
  const blocked = state.runs.filter((run) => ["blocked", "failed", "attention"].includes(run.status));
  const agentBuckets = new Map();
  started.forEach((run) => {
    const lane = run.lane || "unknown";
    const bucket = agentBuckets.get(lane) || {agent: lane, started: 0, delivered: 0};
    bucket.started += 1;
    if (run.status === "pr_created" || deliveredDeliveryStatuses.has(run.delivery?.status)) bucket.delivered += 1;
    agentBuckets.set(lane, bucket);
  });
  const agents = [...agentBuckets.values()].sort((left, right) => right.delivered - left.delivered);
  $("#portfolioKpis").innerHTML = [
    portfolioMetric("Tasks started", compactNumber(started.length), `${days}-day snapshot`),
    portfolioMetric("Delivered", compactNumber(delivered.length), "integrated or PR delivered", "positive"),
    portfolioMetric("Autonomous deliveries", "Calculating…", "share of delivered changes"),
    portfolioMetric("First-pass deliveries", "Calculating…", "share of delivered changes"),
    portfolioMetric("Human interventions", "Calculating…", "reading operator actions"),
    portfolioMetric("Median delivery time", "Calculating…", "reading completed runs"),
    portfolioMetric("Median cost / delivery", "Calculating…", "unknown cost stays unknown"),
    portfolioMetric("Engineer-hours saved", "—", "requires configured baseline"),
    portfolioMetric("Active repositories", compactNumber(new Set(started.map((run) => run.project_id).filter(Boolean)).size), "with started work in window"),
    portfolioMetric("Currently blocked", compactNumber(blocked.length), "open across all repositories", blocked.length ? "danger" : "positive"),
  ].join("");
  $("#portfolioAgentCount").textContent = `${agents.length} agent${agents.length === 1 ? "" : "s"}`;
  $("#portfolioAgentTable").innerHTML = agents.length ? `<thead><tr><th>Worker</th><th>Delivered</th><th>Observed runs</th><th>Outcome detail</th></tr></thead><tbody>${agents.map((row) => `<tr><td><strong>${escapeHtml(row.agent)}</strong></td><td>${escapeHtml(row.delivered)}</td><td><span class="sample-badge ${row.started < 5 ? "low" : ""}">N=${escapeHtml(row.started)}${row.started < 5 ? " · low" : ""}</span></td><td>Calculating…</td></tr>`).join("")}</tbody>` : `<tbody><tr><td>No started agent runs in this window.</td></tr></tbody>`;
  $("#portfolioFailureCount").textContent = "Loading attribution…";
  $("#portfolioFailures").innerHTML = `<div class="portfolio-empty">Reading failure evidence…</div>`;
  $("#portfolioBlockers").innerHTML = blocked.length ? blocked.slice(0, 20).map((run) => `<button class="portfolio-blocker" data-portfolio-run="${escapeHtml(run.id)}" type="button"><span class="mini-status status-${escapeHtml(run.status)}">${escapeHtml(run.status)}</span><strong>${escapeHtml(runTitle(run))}</strong><small>${escapeHtml(run.last_error || run.blocked_reason || "Operator action required")}</small><em>Open →</em></button>`).join("") : `<div class="portfolio-empty"><strong>Nothing is blocked.</strong><span>Odysseus will surface the next decision here.</span></div>`;
  $$('[data-portfolio-run]').forEach((button) => button.addEventListener("click", () => selectRun(button.dataset.portfolioRun)));
  $("#portfolioMethod").textContent = "Snapshot ready. Audited outcome metrics are still loading…";
}

function renderPortfolio(payload) {
  state.portfolio = payload;
  const metrics = payload.metrics || {};
  const agents = payload.agents || [];
  const failures = payload.failures || [];
  const blocked = payload.blocked || [];
  const delivered = Number(metrics.delivered || 0);
  $("#portfolioKpis").innerHTML = [
    portfolioMetric("Tasks started", compactNumber(metrics.tasks_started || 0), `${payload.window?.days || 7}-day cohort`),
    portfolioMetric("Delivered", compactNumber(delivered), "integrated or PR delivered", "positive"),
    portfolioMetric("Autonomous deliveries", portfolioPercent(metrics.autonomous_delivery_rate), `of ${delivered} delivered · no corrective intervention`),
    portfolioMetric("First-pass deliveries", portfolioPercent(metrics.first_pass_success_rate), `of ${delivered} delivered · no retry or repair`),
    portfolioMetric("Human interventions", compactNumber(metrics.human_interventions || 0), "corrective operator actions"),
    portfolioMetric("Median delivery time", metrics.median_minutes_per_delivery === null ? "—" : `${metrics.median_minutes_per_delivery} min`, `N=${delivered}`),
    portfolioMetric("Median cost / delivery", portfolioMoney(metrics.median_cost_per_delivery_usd), `observed ${metrics.cost_coverage_deliveries || 0}/${delivered}`),
    portfolioMetric("Engineer-hours saved", metrics.engineer_hours_saved === null ? "—" : `${metrics.engineer_hours_saved} h`, metrics.engineer_hours_method || "not estimated"),
    portfolioMetric("Active repositories", compactNumber(metrics.active_repositories || 0), "with started work in window"),
    portfolioMetric("Currently blocked", compactNumber(metrics.currently_blocked || 0), "open across all repositories", Number(metrics.currently_blocked || 0) ? "danger" : "positive"),
  ].join("");
  $("#portfolioAgentCount").textContent = `${agents.length} agent${agents.length === 1 ? "" : "s"}`;
  $("#portfolioAgentTable").innerHTML = agents.length ? `<thead><tr><th>Worker</th><th>Delivered</th><th>Delivery</th><th>First pass</th><th>Median time</th><th>Median cost</th><th>Human</th><th>Evidence</th></tr></thead><tbody>${agents.map((row) => `<tr><td><strong>${escapeHtml(row.agent)}</strong></td><td>${escapeHtml(row.delivered)}</td><td>${escapeHtml(portfolioPercent(row.delivery_rate))}</td><td>${escapeHtml(portfolioPercent(row.first_pass_rate))}</td><td>${escapeHtml(row.median_minutes === null ? "—" : `${row.median_minutes} min`)}</td><td>${escapeHtml(portfolioMoney(row.median_cost_usd))}</td><td>${escapeHtml(row.interventions)}</td><td><span class="sample-badge ${Number(row.started) < 5 ? "low" : ""}">N=${escapeHtml(row.started)}${Number(row.started) < 5 ? " · low" : ""}</span></td></tr>`).join("")}</tbody>` : `<tbody><tr><td>No agent outcomes in this window.</td></tr></tbody>`;
  const failureTotal = failures.reduce((sum, row) => sum + Number(row.count || 0), 0);
  const failureMax = Math.max(1, ...failures.map((row) => Number(row.count || 0)));
  $("#portfolioFailureCount").textContent = `${failureTotal} failure${failureTotal === 1 ? "" : "s"}`;
  $("#portfolioFailures").innerHTML = failures.length ? failures.map((row) => `<div class="failure-row"><div><strong>${escapeHtml(row.reason)}</strong><span>${escapeHtml(row.count)}</span></div><progress class="failure-meter" max="100" value="${Math.round(Number(row.count || 0) / failureMax * 100)}">${Math.round(Number(row.count || 0) / failureMax * 100)}%</progress></div>`).join("") : `<div class="portfolio-empty">No attributed failures in this window.</div>`;
  $("#portfolioBlockers").innerHTML = blocked.length ? blocked.map((item) => `<button class="portfolio-blocker" data-portfolio-run="${escapeHtml(item.run_id)}" type="button"><span class="mini-status status-${escapeHtml(item.status)}">${escapeHtml(item.status)}</span><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.reason)} · ${escapeHtml(projectName(projectById(item.project_id)) || "Repository")}</small><em>Open →</em></button>`).join("") : `<div class="portfolio-empty"><strong>Nothing is blocked.</strong><span>Odysseus will surface the next decision here.</span></div>`;
  $$('[data-portfolio-run]').forEach((button) => button.addEventListener("click", () => selectRun(button.dataset.portfolioRun)));
  $("#portfolioMethod").textContent = `Window starts ${new Date(payload.window?.starts_at).toLocaleString()}. ${payload.definitions?.autonomous_delivery_rate || ""} Cost: ${payload.definitions?.cost || "missing remains unknown"}.`;
}

async function refreshPortfolio() {
  if (state.portfolioLoading) return;
  state.portfolioLoading = true;
  const days = Number($("#portfolioWindow")?.value || 7);
  try { renderPortfolio(await api(`/api/portfolio?days=${days}`)); }
  catch (error) { $("#portfolioMethod").textContent = `Detailed outcome analysis unavailable: ${error.message}. Snapshot metrics remain visible.`; }
  finally { state.portfolioLoading = false; }
}

async function refreshInsights() {
  try {
    state.stats = await api("/api/stats");
    const economics = await api("/api/economics?privacy=full");
    const totals = economics.totals || {};
    const entries = [
      ["Accepted changes", totals.accepted_changes ?? state.stats.successful_changes, unknownNumber(totals.acceptance_rate ?? state.stats.success_rate, (value) => `${Math.round(Number(value) * 100)}% acceptance`)],
      ["Delivered changes", totals.delivered_changes ?? 0, unknownNumber(totals.delivery_rate, (value) => `${Math.round(Number(value) * 100)}% of accepted`)],
      ["Human interventions", state.stats.human_interventions, state.stats.human_interventions_per_successful_change === null ? `${state.stats.open_attention} currently open` : `${state.stats.human_interventions_per_successful_change} / successful change`],
      ["Tokens observed", compactNumber(state.stats.tokens), `${compactNumber(state.stats.tool_calls)} tool calls`],
      ["Observed cost", money(totals.observed_model_cost_usd), totals.cost_per_accepted_change_usd === null ? "Unknown / accepted" : `${money(totals.cost_per_accepted_change_usd)} / accepted`],
      ["Expected success cost", money(economics.expected_cost_per_successful_change_usd), `${economics.sample?.sample_size || 0}/${economics.sample?.minimum_runs || 0} sample`],
      ["Retry rate", unknownNumber(totals.retry_rate, (value) => `${Math.round(Number(value) * 100)}%`), `${state.stats.ci_failures} CI repair loops`],
    ];
    $("#insightStats").innerHTML = entries.map(([label, value, note]) => `<article class="insight-card"><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong><p>${escapeHtml(note)}</p></article>`).join("");
    renderEconomics(economics);
  } catch (error) { toast(error.message, true); }
}

function renderEconomicsTable(selector, rows, columns) {
  const table = $(selector);
  if (!table) return;
  table.innerHTML = rows.length ? `<thead><tr>${columns.map(([key, label]) => `<th>${escapeHtml(label || key)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${columns.map(([key]) => {
    let value = row[key];
    if (key === "observed_cost_usd") value = money(value);
    if (key === "eta") value = unknownNumber(value);
    if (key === "run_id") return `<td><button class="link-button" data-economics-run="${escapeHtml(row.run_id)}" type="button">${escapeHtml(String(value || "").slice(0, 12))}</button></td>`;
    return `<td title="${escapeHtml(value ?? UI_COPY.unknown)}">${escapeHtml(value ?? UI_COPY.unknown)}</td>`;
  }).join("")}</tr>`).join("")}</tbody>` : `<tbody><tr><td>No task outcomes observed yet.</td></tr></tbody>`;
  $$('[data-economics-run]').forEach((button) => button.addEventListener("click", () => selectRun(button.dataset.economicsRun)));
}

function renderEconomics(economics) {
  const sample = economics.sample || {};
  const formula = economics.formula || {};
  $("#economicsFormula").textContent = `Expected cost: ${formula.expected_cost_per_successful_change_usd || "formula unavailable."} Sample ${sample.sample_size || 0}/${sample.minimum_runs || 0}${sample.sufficient ? "" : " below threshold"}. Missing prices and costs stay Unknown.`;
  renderEconomicsTable("#economicsLeadTable", economics.lead_view || [], [
    ["task", "Task"], ["state", "State"], ["risk", "Risk"], ["observed_cost_usd", "Observed cost"], ["eta", "ETA"], ["receipt_id", "Receipt"], ["run_id", "Open"],
  ]);
  renderEconomicsTable("#economicsOperatorTable", economics.operator_view || [], [
    ["task", "Task"], ["lane", "Agent"], ["review_lane", "Review"], ["attempt", "Attempt"], ["ci_status", "CI"], ["checks", "Checks"], ["human_interventions", "Human"], ["event_count", "Events"], ["receipt_id", "Receipt"], ["run_id", "Open"],
  ]);
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
  const skillDialog = $("#skillDialog");
  $("#addSkillButton").addEventListener("click", () => { $("#skillForm").reset(); skillDialog.showModal(); });
  $("#skillsProjectSelect").addEventListener("change", (event) => refreshSkillsPage(event.currentTarget.value).catch((error) => toast(error.message, true)));
  $("#skillForm").addEventListener("submit", async (event) => {
    if (event.submitter?.value === "cancel") return;
    event.preventDefault();
    const projectId = state.skillsProjectId;
    if (!projectId) { toast("Choose a repository first.", true); return; }
    const submit = event.submitter;
    const data = new FormData(event.currentTarget);
    const payload = {
      name: data.get("name"),
      description: data.get("description"),
      triggers: String(data.get("triggers") || "").split(",").map((value) => value.trim()).filter(Boolean),
      content: data.get("content"),
    };
    try {
      submit.disabled = true;
      state.skillsCatalog = await api(`/api/projects/${encodeURIComponent(projectId)}/skills/local`, {method: "POST", body: JSON.stringify(payload)});
      if (activeProject()?.id === projectId) state.projectSkills = state.skillsCatalog;
      skillDialog.close();
      renderSkillsPage();
      if (activeProject()?.id === projectId) renderProjectSkills();
      toast(`${payload.name} skill added.`);
    } catch (error) { toast(error.message, true); }
    finally { submit.disabled = false; }
  });
  const taskDialog = $("#taskDialog");
  [$("#newTaskButton"), $("#emptyNewTask"), ...$$('[data-new-task]')].forEach((button) => button?.addEventListener("click", () => focusTaskComposer(activeProject()?.id || "")));
  $("#workNewTaskButton")?.addEventListener("click", () => {
    const project = activeProject();
    if (!project) { $("#projectDialog").showModal(); return; }
    setView("work");
    window.requestAnimationFrame(() => $("#quickTaskPrompt")?.focus());
  });
  $("#taskProjectSelect").addEventListener("change", () => { syncCustomProject($("#taskProjectSelect"), $("#taskCustomProject")); refreshTaskSkillChoices().catch((error) => toast(error.message, true)); scheduleTaskAgentRecommendation(); });
  $("#taskPrompt").addEventListener("input", () => { scheduleTaskSkillRecommendations(); scheduleTaskAgentRecommendation(); });
  $("#laneSelect").addEventListener("change", scheduleTaskAgentRecommendation);
  $("#taskSkillMode").addEventListener("change", () => { renderTaskSkillChoices(); renderTaskSkillRecommendations(); scheduleTaskSkillRecommendations(); });
  $("#environmentProfile").addEventListener("change", (event) => $("#environmentOptions").classList.toggle("hidden", event.currentTarget.value !== "docker"));
  $("#untrustedProject").addEventListener("change", (event) => { if (!event.currentTarget.checked) return; const select = $("#environmentProfile"); const docker = select.querySelector('option[value="docker"]'); if (docker?.disabled) { event.currentTarget.checked = false; toast("Install Docker before running an untrusted repository.", true); return; } select.value = "docker"; select.dispatchEvent(new Event("change")); });
  $("#variantsEnabled").addEventListener("change", (event) => $("#variantOptions").classList.toggle("hidden", !event.currentTarget.checked));
  $("#epicProjectSelect").addEventListener("change", () => {
    syncCustomProject($("#epicProjectSelect"), $("#epicCustomProject"));
    refreshEpicSourceChoices($("#epicProjectSelect").value).catch((error) => toast(error.message, true));
  });
  $$('[data-plan-source-tab]').forEach((button) => button.addEventListener("click", () => {
    state.planSourceTab = button.dataset.planSourceTab;
    if (state.planSourceTab === "github" && !state.planGithubCatalog.length && !state.planGithubLoading) loadEpicGithubSources();
    else renderEpicSourcePicker();
  }));
  $("#epicLoadGithub").addEventListener("click", loadEpicGithubSources);
  $("#epicAddSourceUrl").addEventListener("click", addEpicUrlSource);
  $("#epicSourceUrl").addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); addEpicUrlSource(); } });
  const sourceDropzone = $("#epicSourceDropzone");
  ["dragenter", "dragover"].forEach((type) => sourceDropzone.addEventListener(type, (event) => { event.preventDefault(); sourceDropzone.classList.add("dragging"); }));
  ["dragleave", "drop"].forEach((type) => sourceDropzone.addEventListener(type, (event) => { event.preventDefault(); sourceDropzone.classList.remove("dragging"); }));
  sourceDropzone.addEventListener("drop", (event) => addEpicUploadedSources(event.dataTransfer?.files || []).catch((error) => toast(`Could not read document: ${error.message}`, true)));
  $("#epicSourceUpload").addEventListener("change", async (event) => {
    try { await addEpicUploadedSources(event.currentTarget.files || []); }
    catch (error) { toast(`Could not read document: ${error.message}`, true); }
    finally { event.currentTarget.value = ""; }
  });
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
    const laneChoice = String(data.get("lane") || "auto");
    const autoRoute = laneChoice === "auto";
    const payload = {
      task: data.get("task"), title: data.get("title"), project_path: project.path, lane: autoRoute ? state.bootstrap.default_lane : laneChoice, auto_route: autoRoute, origin: "web",
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
      status.textContent = autoRoute ? `Routing and starting on ${projectName(project)}...` : `Starting ${payload.lane} on ${projectName(project)}...`;
      status.classList.remove("hidden");
      setFormSubmitting(form, true, submit, "Starting...");
      const run = await api("/api/runs", {method: "POST", body: JSON.stringify(payload)});
      state.taskSkillRecommendations = null;
      state.taskAgentRecommendation = null;
      renderTaskSkillRecommendations();
      renderTaskAgentRecommendation();
      status.textContent = addAnother ? "Task started. Add the next request." : "Task started. Opening the live task view...";
      toast(`${autoRoute ? `Task routed to ${run.lane}` : `Task started for ${run.lane}`}: ${runTitle(run)}`);
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
  $("#epicForm").addEventListener("submit", async (event) => {
    if (event.submitter?.value === "cancel") return;
    event.preventDefault();
    const submit = event.submitter;
    const data = new FormData(event.currentTarget);
    const project = projectById($("#epicProjectSelect").value);
    if (!project) { toast("Add a repository first.", true); return; }
    const sourceKind = String(data.get("source_kind") || "user_request");
    const repositorySources = selectedEpicRepositorySources();
    const requirementParts = [`Outcome:\n${String(data.get("requirement") || "").trim()}`];
    if (String(data.get("required_behavior") || "").trim()) requirementParts.push(`Must work:\n${String(data.get("required_behavior")).trim()}`);
    if (String(data.get("forbidden_regressions") || "").trim()) requirementParts.push(`Must not break:\n${String(data.get("forbidden_regressions")).trim()}`);
    if (String(data.get("required_evidence") || "").trim()) requirementParts.push(`Proof required:\n${String(data.get("required_evidence")).trim()}`);
    const payload = {
      requirement: requirementParts.join("\n\n"), source_kind: sourceKind, project_id: project.id,
      source_paths: repositorySources.filter((item) => item.kind === "adr").map((item) => item.path),
      repository_source_paths: repositorySources.filter((item) => item.kind !== "adr").map((item) => item.path),
      source_documents: state.planUploadedSources.map((item) => ({kind: item.kind || sourceKind, title: item.title, path: item.path, content: item.content})),
      github_sources: selectedEpicGithubSources().map((item) => ({kind: item.kind, number: item.number})),
      url_sources: state.planUrlSources.map((item) => item.source_url || item.path),
      force_source_paths: [...state.planForcedSourcePaths],
      planner_lane: data.get("planner_lane"), lane: data.get("lane"), review_lane: data.get("review_lane"),
      checks: String(data.get("checks") || "").split("\n").map((item) => item.trim()).filter(Boolean),
    };
    try {
      submit.disabled = true;
      submit.textContent = "Freezing sources…";
      await api("/api/epics/plan", {method: "POST", body: JSON.stringify(payload)});
      $("#epicDialog").close();
      event.currentTarget.reset();
      state.planSelectedSourcePaths = []; state.planRepositorySources = []; state.planUploadedSources = []; state.planGithubCatalog = []; state.planSelectedGithub = []; state.planUrlSources = []; state.planForcedSourcePaths = [];
      toast("Task graph proposed. Review the frozen sources and tasks before approving any work.");
      await Promise.all([refreshEpics(), refreshProjectOverview()]);
      setView("epics");
    } catch (error) { toast(error.message, true); }
    finally { submit.disabled = false; submit.textContent = "Generate task plan"; }
  });
  $("#planStudioClose").addEventListener("click", () => $("#planStudioDialog").close());
  $("#planStudioSourceFilter").addEventListener("change", (event) => {
    state.planStudioSourceFilter = event.currentTarget.value;
    const sourceIndex = (state.planStudio?.source_documents || []).findIndex((source) => source.path === state.planStudioSourceFilter);
    if (sourceIndex >= 0) state.planStudio._sourceIndex = sourceIndex;
    renderPlanStudio();
  });
  $("#planStudioTaskSort").addEventListener("change", (event) => { state.planStudioTaskSort = event.currentTarget.value; renderPlanStudio(); });
  $("#planStudioEditor").addEventListener("input", updatePlanStudioTaskFromEditor);
  $("#planStudioEditor").addEventListener("change", updatePlanStudioTaskFromEditor);
  $("#planStudioSave").addEventListener("click", async () => {
    try { $("#planStudioSave").disabled = true; await savePlanStudio(); await refreshEpics(); }
    catch (error) { toast(error.message, true); }
    finally { $("#planStudioSave").disabled = false; }
  });
  $("#planStudioApprove").addEventListener("click", async () => {
    if (!state.planStudio) return;
    const approved = await confirmChoice({eyebrow: "FREEZE EXECUTION CONTRACT", title: "Approve this exact plan version?", lead: "Dependency-ready root tasks will start.", message: "The source links, prompts, profiles, criteria and required evidence are frozen for this version. Push, PR and integration still use their existing safety gates.", confirmLabel: "Approve & start"});
    if (!approved) return;
    try {
      $("#planStudioApprove").disabled = true;
      if (state.planStudioDirty) await savePlanStudio();
      await api(`/api/epics/${encodeURIComponent(state.planStudio.id)}/approve`, {method: "POST", body: "{}"});
      $("#planStudioDialog").close(); toast("Execution contract approved. Ready tasks are queued.");
      await Promise.all([refreshEpics(), refreshRuns()]);
    } catch (error) { toast(error.message, true); }
    finally { $("#planStudioApprove").disabled = false; }
  });
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
  [$("#addProjectButton"), $("#manageAddProjectButton")].forEach((button) => button?.addEventListener("click", () => {
    $("#projectPathStatus").textContent = "Odysseus will verify that this is a readable Git repository.";
    $("#projectDialog").showModal();
  }));
  $("#useCurrentFolder").addEventListener("click", () => {
    const current = state.bootstrap?.working_directory || "";
    $("#projectPathInput").value = current;
    const detected = state.bootstrap?.current_repository;
    $("#projectPathStatus").textContent = detected?.git_repository
      ? `Detected Git repository: ${projectName(detected)}. No files will be moved.`
      : "The current server folder is not a Git repository. Choose another absolute path.";
    $("#projectPathInput").focus();
  });
  $("#projectPathInput").addEventListener("input", () => {
    $("#projectPathStatus").textContent = "Path will be checked before it is saved. The folder is never uploaded or moved.";
  });
  $("#projectForm").addEventListener("submit", async (event) => { if (event.submitter?.value === "cancel") return; event.preventDefault(); const data = new FormData(event.currentTarget); const status = $("#projectPathStatus"); try { status.textContent = "Checking folder and Git access…"; const registered = await api("/api/projects", {method: "POST", body: JSON.stringify({path: data.get("path"), name: data.get("name"), tags: String(data.get("tags") || "").split(",").map((tag) => tag.trim()).filter(Boolean)})}); $("#projectDialog").close(); event.currentTarget.reset(); await refreshProjects(); selectProject(registered.id); toast(`${projectName(registered)} is ready.`); } catch (error) { status.textContent = error.message; toast(error.message, true); } });
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
    state.bootstrap = await api("/api/bootstrap"); $("#parallelLabel").textContent = `${state.bootstrap.max_parallel} running max`; const laneOptions = agentLaneOptions(); $("#laneSelect").innerHTML = agentLaneOptions("auto", true); $("#plannerLaneSelect").innerHTML = laneOptions; $("#epicLaneSelect").innerHTML = laneOptions; $("#epicReviewLaneSelect").innerHTML = laneOptions; $("#resumeLaneSelect").innerHTML = laneOptions; $("#settingsDefaultLane").innerHTML = laneOptions; $("#settingsPlannerLane").innerHTML = laneOptions; $("#settingsReviewLane").innerHTML = laneOptions;
    [["docker", "Docker is not installed"], ["devcontainer", "Dev Container CLI is not installed"]].forEach(([profile, message]) => { const option = $("#environmentProfile").querySelector(`option[value="${profile}"]`); if (option && !state.bootstrap.capabilities?.[profile]) { option.disabled = true; option.textContent += ` — unavailable`; option.title = message; } });
    bindDialogs();
    syncThemeButton();
    initSidebarResize();
    $("#themeToggle").addEventListener("click", toggleTheme);
    $$(".nav-button, .sidebar-primary-link").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view))); $$('[data-open-view]').forEach((button) => button.addEventListener("click", () => setView(button.dataset.openView)));
    $$(".filter").forEach((button) => button.addEventListener("click", () => { state.filter = button.dataset.filter; $$(".filter").forEach((item) => item.classList.toggle("active", item === button)); renderRuns(); }));
    $$(".tab").forEach((button) => button.addEventListener("click", () => activateTab(button.dataset.tab)));
    $$(".task-section-tab").forEach((button) => button.addEventListener("click", () => activateTaskSection(button.dataset.section)));
    $("#allWorkButton").addEventListener("click", () => selectProject("all")); $("#backToProject").addEventListener("click", () => selectProject(state.selected?.project_id || state.projectFilter));
    $("#parallelLabel").addEventListener("click", () => setView("settings"));
    $("#helpToggle").addEventListener("click", () => toggleHelp());
    $("#helpClose").addEventListener("click", () => toggleHelp(false));
    $("#homeStartTask").addEventListener("click", () => continueHomeTask());
    $("#homeAdvancedTask").addEventListener("click", () => openTaskDialog({prompt: $("#homeTaskPrompt").value.trim(), projectId: $("#homeProjectSelect").value || preferredProjectId()}));
    $("#homeOpenRepositories").addEventListener("click", () => selectProject("all"));
    $("#homeTaskPrompt").addEventListener("keydown", (event) => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") { event.preventDefault(); continueHomeTask(); } });
    $("#workListToggle").addEventListener("click", () => setWorkListExpanded(!state.workListExpanded));
    $(".sidebar-brand").addEventListener("click", (event) => { event.preventDefault(); setView("portfolio"); });
    $("#sidebarSearchButton").addEventListener("click", () => {
      $("#globalSearch").focus();
      $("#globalSearch").select();
    });
    $("#taskList").addEventListener("scroll", hideTaskHover, {passive: true});
    window.addEventListener("resize", hideTaskHover, {passive: true});
    $("#activityFocusToggle").addEventListener("click", () => setActivityFocus(!state.activityFocus));
    $("#projectFilter").addEventListener("change", (event) => selectProject(event.target.value)); $("#sessionScope").addEventListener("change", (event) => { state.sessionScope = event.target.value; renderSessions(); }); $("#refreshSessions").addEventListener("click", refreshSessions); $("#refreshAttention").addEventListener("click", refreshAttention); $("#refreshInsights").addEventListener("click", refreshInsights); $("#refreshPortfolio").addEventListener("click", refreshPortfolio); $("#portfolioWindow").addEventListener("change", refreshPortfolio); $("#loadIssues").addEventListener("click", loadIssues); $("#runSearch").addEventListener("click", () => runSearch()); $("#insightSearch").addEventListener("keydown", (event) => { if (event.key === "Enter") runSearch(); }); $("#globalSearch").addEventListener("keydown", (event) => {
      if (event.key === "Enter") { event.preventDefault(); runSearch(event.currentTarget.value); }
      if (event.key === "Escape") { event.currentTarget.value = ""; event.currentTarget.blur(); }
    });
    document.addEventListener("keydown", (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); $("#globalSearch").focus(); return; }
      if (event.key === "Escape" && state.activityFocus) { event.preventDefault(); setActivityFocus(false); return; }
      if (event.key === "Escape" && state.helpOpen) { event.preventDefault(); toggleHelp(false); return; }
      if (!event.metaKey && !event.ctrlKey && !event.altKey && event.key.toLowerCase() === "n" && !/input|textarea|select/i.test(event.target.tagName) && !$("dialog[open]")) { event.preventDefault(); $("[data-new-task]").click(); }
    });
    await Promise.all([refreshProjects(), refreshSessions(), refreshInbox(), refreshAttention(), refreshEpics()]); await refreshRuns(); await refreshAttention();
    const params = new URLSearchParams(location.search);
    const match = decodeURIComponent(location.hash.slice(1)).match(/^task\/(.+)$/); if (match && state.runs.some((run) => run.id === match[1])) await selectRun(match[1]);
    else { const projectMatch = decodeURIComponent(location.hash.slice(1)).match(/^project\/(.+)$/); if (projectMatch && projectById(projectMatch[1])) selectProject(projectMatch[1]); else { const requestedView = params.get("view"); if (["portfolio", "work", "attention", "epics", "tasks", "sessions", "inbox", "projects", "insights", "github", "settings"].includes(requestedView)) { if (requestedView === "tasks" && state.runs.length) await selectRun(state.runs[0].id); else setView(requestedView); } else setView(state.runs.length ? "portfolio" : "work"); } }
    const requestedSection = params.get("section"); if (["summary", "changes", "activity", "evidence"].includes(requestedSection)) activateTaskSection(requestedSection);
    if (requestedSection === "activity" && params.get("focus") === "0") setActivityFocus(false);
    const requestedTab = params.get("tab"); if (["diff", "integration", "checks", "context", "review", "evaluation", "ci"].includes(requestedTab)) activateTab(requestedTab);
    const requestedDialog = params.get("dialog"); if (requestedDialog === "task") openTaskDialog({prompt: params.get("prompt") || "", projectId: preferredProjectId()}); else if (requestedDialog === "epic") $("#newEpicButton").click();
    const requestedPlan = params.get("plan"); if (requestedPlan && state.epics.some((epic) => epic.id === requestedPlan)) await openPlanStudio(requestedPlan);
    if (params.get("help") === "1") toggleHelp(true);
    setConnection(true);
    if (params.get("browser-regression") === "1" && state.bootstrap?.test_capabilities?.browser_regression === true) runBrowserRegression().catch((error) => {
      const node = document.createElement("pre");
      node.id = "browserRegressionResult";
      node.textContent = `FAIL ${error.message}`;
      document.body.appendChild(node);
      api("/api/inbox", {method: "POST", body: JSON.stringify({title: "FAIL browser regression", task: error.message})}).catch(() => {});
    });
    window.setInterval(() => refreshRuns().catch(() => setConnection(false)), 3000);
    window.setInterval(() => Promise.all([refreshSessions(), refreshInbox(), refreshAttention(), refreshEpics(), state.view === "insights" ? refreshPortfolio() : Promise.resolve()]).catch(() => setConnection(false)), 6000);
  } catch (error) { setConnection(false); toast(error.message, true); }
}

async function runBrowserRegression() {
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const sleep = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));
  setView("portfolio");
  assert($("#portfolioView").textContent.includes("What should the agent change?"), "Home asks for a direct instruction");
  assert($("#homeStartTask").textContent === "Start task", "Home has one direct primary task action");
  assert(!$("#homePlanTask"), "Home does not ask the user to choose the execution mechanism");
  assert(!$("#portfolioView").querySelector("#portfolioKpis"), "Home does not duplicate the Outcomes portfolio");
  assert($("#workDescription").textContent.includes("local Git folder"), "repository view focuses on local folders");
  assert($("#journeyStepper").classList.contains("hidden") && $("#workSummary").classList.contains("hidden"), "repository picker does not duplicate task onboarding or delivery metrics");
  assert($('[data-journey-step="3"] strong')?.textContent === "Review", "first-run journey uses short review label");
  assert($("#sidebarResizer")?.getAttribute("aria-label") === "Resize repository sidebar", "sidebar resize handle accessible name");
  assert($(".sidebar-brand") && !$(".titlebar .brand"), "product identity lives in the sidebar, not duplicate navigation");
  assert(!$('.sidebar-primary-link[data-view="portfolio"]'), "New task replaces the redundant Home navigation item");
  assert(!$("#sidebarMore").open, "secondary sidebar tools start collapsed");
  assert($$('.explorer-tools > button[data-open-view]').length === 2, "only Skills and Terminals stay visible above More");
  assert(!$(".titlebar .connection"), "top bar does not repeat a live connection label");
  $("#sidebarSearchButton").click();
  assert(document.activeElement === $("#globalSearch"), "sidebar search focuses the global search field");
  $("#globalSearch").value = "temporary query";
  $("#globalSearch").dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
  assert($("#globalSearch").value === "", "Escape clears global search");
  $("#helpToggle").click();
  assert(state.helpOpen && document.body.classList.contains("help-open"), "context help opens as a right column");
  assert($("#helpContent").textContent.includes("Write what should change"), "Home help gives the next action");
  setView("attention");
  assert($("#helpTitle").textContent === "Needs You", "help follows navigation context");
  if (window.innerWidth > 900) assert(getComputedStyle($("#attentionView")).maxWidth === "none", "Needs You fills the workspace");
  $("#helpClose").click();
  assert(!state.helpOpen && $("#helpPanel").getAttribute("aria-hidden") === "true", "context help closes without changing work");
  setView("portfolio");
  assert(getComputedStyle($(".activity-bar")).display === "none", "sidebar is the only global navigation surface");
  assert($("#taskHoverCard").getAttribute("role") === "tooltip", "task hover preview is exposed as a tooltip");
  setSidebarWidth(DEFAULT_SIDEBAR_WIDTH);
  assert(getComputedStyle(document.documentElement).getPropertyValue("--sidebar-width").trim() === `${DEFAULT_SIDEBAR_WIDTH}px`, "default sidebar width");
  setSidebarWidth(460);
  assert($("#sidebarResizer").getAttribute("aria-valuenow") === "460", "widened sidebar value");
  setSidebarWidth(430);
  assert(window.localStorage.getItem(SIDEBAR_WIDTH_KEY) === "430", "persisted sidebar width");
  resetSidebarWidth();
  assert($("#sidebarResizer").getAttribute("aria-valuenow") === String(DEFAULT_SIDEBAR_WIDTH), "reset sidebar width");
  assert(!$("#resetSidebarWidth"), "sidebar has no redundant reset-width button");
  const narrow = window.matchMedia("(max-width: 760px)").matches;
  assert(!narrow || getComputedStyle($("#sidebarResizer")).display === "none", "mobile resize handle hidden");

  if (state.projects.length) {
    selectProject(state.projects[0].id);
    await sleep(80);
    assert($("#workSummary").classList.contains("hidden"), "repository page does not repeat delivery metrics");
    assert($("#workListPanel").classList.contains("hidden"), "recent work starts folded for a repository");
    assert($("#workListToggle").getAttribute("aria-expanded") === "false", "recent work exposes collapsed state");
    $("#workListToggle").click();
    assert(!$("#workListPanel").classList.contains("hidden"), "recent work can be expanded");
    const sidebarTask = $(".task-card[data-run-id]");
    if (sidebarTask) {
      assert(sidebarTask.querySelector(":scope > .task-state-dot") && sidebarTask.querySelector(":scope > h3") && sidebarTask.querySelector(":scope > .task-row-meta"), "sidebar task is one scannable row");
      assert(getComputedStyle(sidebarTask.querySelector(".task-card-top")).display === "none", "sidebar task hides the old multi-line metadata");
      assert(narrow || sidebarTask.getBoundingClientRect().height <= 36, "sidebar task stays on one line");
      if (!window.matchMedia("(max-width: 900px)").matches) {
        showTaskHover(sidebarTask);
        await sleep(30);
        assert(!$("#taskHoverCard").hidden && $("#taskHoverCard").textContent.includes("checks"), "sidebar task exposes an outcome preview on hover");
        hideTaskHover();
      }
    }
    for (const [filter, tone] of [["working", "status-in-progress"], ["question", "status-question"], ["needs", "status-needs-action"], ["done", "status-done"]]) {
      const button = $(`.filter[data-filter="${filter}"]`);
      assert(button && button.getAttribute("aria-label"), `${filter} dot filter has an accessible label`);
      button.click();
      const visible = $$(".task-card[data-run-id]");
      assert(visible.length > 0 && visible.every((item) => item.querySelector(`.task-state-dot.${tone}`)), `${filter} dot filters tasks by status color`);
      assert(getComputedStyle(button.querySelector(".task-state-dot")).boxShadow === "none", `${filter} status dot has no halo`);
    }
    assert($$(".task-card .task-row-cost").some((item) => item.textContent === "$0.25"), "sidebar shows observed task cost");
    $('.filter[data-filter="active"]').click();
    const recentRow = $(".work-task-row");
    if (recentRow) {
      assert(recentRow.querySelector(":scope > .mini-status") && recentRow.querySelector(":scope > time") && recentRow.querySelector(":scope > h3"), "recent work is a status-time-title row");
      assert(narrow || recentRow.getBoundingClientRect().height <= 44, "recent work remains one line on desktop");
    }
    if (!narrow) {
      const columns = getComputedStyle($(".repository-status-grid")).gridTemplateColumns.split(" ").map(Number.parseFloat);
      assert(columns.length >= 2 && columns[0] > columns[1], "dependency graph is wider than the Gantt timeline");
    }
    assert($("#workStatusStrip [data-status-focus]").textContent.includes("Open delivery plan") && $("#workStatusStrip [data-status-focus]").textContent.includes("cost"), "repository status exposes a clear delivery-plan action");
    assert($("#repositoryDeliveryMetrics").textContent.includes("Observed cost"), "repository metrics disclose observed cost coverage");
    assert($$("#repositoryGantt .gantt-cost").some((item) => item.textContent.includes("$")), "repository timeline shows observed task cost where available");
    assert(!$("#repositoryDependencyGraph [style]"), "repository graph does not depend on CSP-blocked inline styles");
    assert($("#repositoryGantt .gantt-track"), "repository timeline uses CSP-safe SVG geometry");
  }

  setView("epics");
  const proposedContract = state.epics.find((epic) => epic.status === "proposed");
  if (proposedContract) {
    await openPlanStudio(proposedContract.id);
    assert($("#planStudioDialog").open, "versioned execution contract opens from Plans");
    assert($$("#planStudioSourceSections .plan-source-section").length >= 1, "Plan Studio shows frozen source requirements");
    assert($("#planStudioTaskList .plan-task-card"), "Plan Studio shows editable task contracts");
    assert($("#planStudioEditor").textContent.includes("Acceptance criteria") && $("#planStudioEditor").textContent.includes("Execution profile"), "task contract exposes evidence and execution profile");
    assert($("#planStudioEstimate").textContent.includes("Cost") || $("#planStudioEstimate").textContent.includes("$"), "Plan Studio states estimate coverage honestly");
    assert($$("#planStudioGraph .dag-graph-node").length >= 1, "Plan Studio keeps the dependency graph visible");
    $("#planStudioDialog").close();
  }

  $("#newTaskButton").click();
  await sleep(50);
  assert($("#portfolioView").classList.contains("active"), "new task opens the shared home composer");
  assert(document.activeElement === $("#homeTaskPrompt"), "new task focuses the direct instruction field");
  openTaskDialog({projectId: preferredProjectId()});
  await sleep(50);
  assert($("#taskDialog").open, "advanced task dialog opens on demand");
  assert($("#laneSelect").value === "auto", "new task defaults to Agent Auto");
  assert($("#taskDialog").textContent.includes("Advanced execution settings"), "execution settings are collapsed behind one disclosure");
  const advanced = $("#taskDialog > form > details.advanced");
  advanced.open = true;
  const checkbox = $("#untrustedProject");
  const checkboxLabel = checkbox.closest("label");
  assert(checkbox.getBoundingClientRect().width <= 20, "advanced checkbox retains compact width");
  assert(checkboxLabel.scrollWidth <= checkboxLabel.clientWidth + 1, "advanced checkbox label does not overflow");
  $("#taskDialog").close();

  const accepted = state.runs.filter((run) => run.status === "accepted");
  const acceptedNotApplied = accepted.find((run) => run.delivery?.status === "not_applied" || !run.delivery?.status);
  assert(accepted.length >= 3, "accepted artifacts available");
  const running = state.runs.find((run) => run.status === "running");
  assert(running, "running task available");
  await selectRun(running.id);
  assert(!$(".detail-breadcrumb") && $(".task-context-bar"), "task context is one compact metadata row");
  assert($("#narrativeTitle").textContent === "Agent is working", "running task uses one-line progress");
  assert($("#narrativeCopy").textContent === "Progress appears in Activity.", "running task avoids essay");
  assert($("#detailElapsed").textContent.startsWith("Wall ") && $("#detailCost").textContent.startsWith("Cost "), "task heading separates wall time and cost");
  assert(!$("#executionDetails").open, "execution telemetry starts folded");
  assert($("#executionDetails").textContent.includes("Forensic details") && $("#executionDetailsSummary").textContent.includes("Model tokens") && $("#executionDetailsSummary").textContent.includes("CI"), "folded forensic summary remains informative");
  assert($("#summaryAssistant").classList.contains("hidden"), "assistant hidden when no decision is needed");
  state.assistantOpen = true;
  renderDetail(running);
  assert(!$(".assistant-more-actions") && !$("#assistantCopy").closest("details") && !$("#assistantQueueTask").closest("details"), "Decision Assistant exposes copy and separate-task actions directly");
  assert($("#assistantMessages").textContent.includes("Draft only"), "empty Decision Assistant uses one compact explanation");
  state.assistantOpen = false;
  renderDetail(running);
  activateTaskSection("activity");
  await sleep(160);
  assert($("#eventLog").textContent.includes("Tool") && $("#eventLog").textContent.includes("python -m unittest"), "Activity separates tool execution from agent messages");
  assert($("#eventLog .event-tool .event-avatar"), "tool execution has a distinct visual actor");
  assert($("#activitySummary").textContent.includes("Total") && $("#activitySummary").textContent.includes("Agent") && $("#activitySummary").textContent.includes("Total cost"), "Activity summarizes total and phase economics");
  assert($("#eventLog time").textContent.includes("T+"), "each Activity entry shows relative task timing");
  assert(state.activityFocus && document.body.classList.contains("activity-focus"), "Activity uses the full workspace width by default");
  if (window.innerWidth > 900) assert(getComputedStyle($("#runDetail")).maxWidth === "none", "every task tab owns the full workspace");
  assert($("#activityFocusToggle").textContent.includes("Narrow"), "wide Activity exposes a diagonal narrow action");
  $("#activityFocusToggle").click();
  assert(!state.activityFocus && !document.body.classList.contains("activity-focus"), "diagonal control narrows Activity");
  assert($("#activityFocusToggle").textContent.includes("Expand"), "narrow Activity exposes a diagonal expand action");
  $("#activityFocusToggle").click();
  assert(state.activityFocus && (window.innerWidth <= 900 || getComputedStyle($(".project-explorer")).display !== "none"), "expanded Activity keeps repository navigation visible on desktop");
  document.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
  assert(!state.activityFocus && !document.body.classList.contains("activity-focus"), "Escape restores the task view");
  activateTaskSection("summary");
  const blocked = state.runs.find((run) => run.status === "blocked");
  assert(blocked, "blocked task available");
  await selectRun(blocked.id);
  assert($("#narrativeTitle").textContent.includes("backend") || $("#narrativeTitle").textContent.includes("predecessor"), "blocked prerequisite named");
  const review = state.runs.find((run) => run.status === "review");
  assert(review, "review task available");
  await selectRun(review.id);
  assert($("#reviewDecisionCard").textContent.includes("Review result"), "review decision leads task detail");
  assert($("#reviewDecisionCard").textContent.includes("Soft evidence"), "heuristic signal is separated from hard gates");
  assert(!$("#reviewDecisionCard").textContent.match(/Evidence score\s+\d+/i), "uncalibrated evidence is not rendered as a precise score");
  assert(!$("#reviewDecisionCard").textContent.includes("Confidence"), "uncalibrated confidence label is hidden");
  assert($("#deliveryLifecycle").textContent.includes("Executed") && $("#deliveryLifecycle").textContent.includes("Healthy"), "canonical delivery lifecycle is visible");
  assert($("#reviewDecisionCard .delivery-decision .primary").textContent === "Approve change", "review CTA uses direct user language");
  assert($("#reviewDecisionCard").textContent.includes("does not change your source repository yet"), "approval and repository application remain distinct");
  $("#helpToggle").click();
  assert($("#helpTitle").textContent.includes(review.title), "task help identifies the selected task");
  assert($("#helpContent").textContent.includes("Review the decision"), "task help explains the current decision");
  $("#helpClose").click();
  activateTaskSection("changes");
  await sleep(160);
  assert($("#diffPatch .diff-line"), "Changes renders escaped syntax-colored diff lines");
  activateTaskSection("evidence");
  await renderVisibleHeavyPanels();
  assert($("#checkResults .terminal-line"), "Evidence renders escaped syntax-colored terminal lines");
  activateTaskSection("summary");
  assert($("#runNarrative").classList.contains("hidden"), "review avoids duplicate narrative status");
  assert($("#reviewDecisionCard").textContent.includes("Cost") && $("#reviewDecisionCard").textContent.includes("Unknown"), "unknown cost remains explicit");
  assert($$("#reviewDecisionCard .delivery-decision .primary").length === 1, "review exposes one visible primary action");
  assert($("#summaryAssistant").classList.contains("hidden"), "duplicate summary assistant remains hidden");
  assert($("#assistantPanel").classList.contains("hidden"), "assistant does not compete with the primary review decision");
  const assistantButton = $('#runActions [data-action="assistant"]');
  assert(assistantButton?.textContent === "Ask assistant", "assistant remains available on demand");
  assistantButton.click();
  assert(!$("#assistantPanel").classList.contains("hidden"), "assistant opens on demand");
  assert(narrow || $("#assistantPanel").getBoundingClientRect().width >= 340, "assistant has enough width for a useful conversation");
  $('#runActions [data-action="assistant"]').click();
  assert(acceptedNotApplied, "accepted not-applied artifact available");
  await selectRun(acceptedNotApplied.id);
  assert($("#reviewDecisionCard").textContent.includes("Checks"), "decision evidence visible");
  assert($("#reviewDecisionCard").textContent.includes("Approved change · not applied"), "approved-not-applied is plain");
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
  assert(!state.attention.some((item) => item.type === "permission_request" && state.runs.find((run) => run.id === item.run_id)?.status === "review"), "review hides superseded runtime permissions");
  const conflict = state.attention.find((item) => item.type === "merge_conflict");
  if (conflict) {
    assert($("#attentionList").textContent.includes("Conflicting files"), "conflict card shows files");
    assert($("#attentionList").textContent.includes("Prerequisite: resolve listed files."), "conflict card names prerequisite");
    const group = conflict.run_id ? $(`[data-open-run="${CSS.escape(conflict.run_id)}"]`)?.closest(".attention-group") : null;
    assert(group && group.querySelectorAll(".attention-group-event").length === 2, "multiple decisions for one task are grouped");
    assert($("#attentionSummary").textContent.includes("tasks need you") && $("#attentionSummary").textContent.includes("open decisions"), "Needs You separates task and decision counts");
    openAttentionResponseDialog(conflict.id);
    assert($("#attentionResponseDialog").open, "native attention dialog opens");
    $("#attentionResponseDialog").close();
  }
  setView("attention");
  assert($("#attentionView").textContent.includes("Answer these to continue work."), "Needs You concise header");
  setView("epics");
  assert($("#epicsView").textContent.includes("Approve a graph before agents start."), "Plans concise header");
  assert($$("#epicList .epic-card").every((card) => card.querySelector(".epic-progress") && card.querySelector(".epic-graph-details")), "Plans expose compact progress and a drill-down graph");
  assert(!$("#epicList [style]"), "Plan graphs do not depend on CSP-blocked inline styles");
  const proposedPlan = $$("#epicList .epic-card").find((card) => card.querySelector(".mini-status")?.textContent.trim() === "proposed");
  if (proposedPlan) assert(proposedPlan.querySelector(".epic-graph-details").open, "proposed plan opens the graph required for approval");
  setView("inbox");
  assert($("#inboxView").textContent.includes("Park work; queue explicitly."), "Follow-ups concise header");
  setView("insights");
  await refreshInsights();
  assert($("#insightsView").querySelector("#portfolioKpis"), "Outcomes owns the engineering portfolio");
  assert($("#insightsView").textContent.includes("Delivery, not activity."), "Outcomes leads with delivered work");
  assert(!$("#portfolioFailures [style]"), "failure attribution does not depend on CSP-blocked inline styles");
  assert($("#economicsFormula").textContent.includes("Expected cost"), "economics formula visible");
  assert($("#economicsFormula").textContent.includes("Sample"), "economics sample size visible");
  assert($("#economicsLeadTable").textContent.includes("Observed cost"), "lead economics table visible");
  assert($("#economicsLeadTable").textContent.includes("Unknown"), "unknown economics cost visible");
  assert($("#economicsOperatorTable").textContent.includes("Events"), "operator economics table retains evidence detail");
  assert(document.querySelector('a[href="/api/economics?format=csv&view=lead"]'), "lead CSV export link");
  assert(document.querySelector('a[href="/api/economics?format=ndjson&view=operator"]'), "operator NDJSON export link");
  setView("settings");
  assert($("#sidebarMore").open, "secondary navigation opens when its current screen is active");
  assert($("#settingsView").textContent.includes("Capacity, agents, CI, resources, assistants."), "Settings concise header");
  assert($("#settingsView").textContent.includes("API keys are never saved."), "settings security detail preserved");
  assert($$("#settingsView .primary").length === 1, "Settings exposes one primary action");
  assert($$("#settingsView .settings-disclosure").length === 3, "Settings groups advanced controls into three sections");
  assert($("#settingsForm .settings-disclosure").open, "execution defaults open first");
  assert(!$("#assistantSettingsForm .settings-disclosure").open, "optional assistant settings start folded");
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
