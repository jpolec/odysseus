"use strict";

const state = {
  bootstrap: null, runs: [], projects: [], sessions: [], inbox: [], attention: [], epics: [], selectedId: null,
  selected: null, events: [], filter: "all", projectFilter: "all", view: "work",
  stream: null, refreshTimer: null, stats: null, searchResults: [], sessionScope: "attached", taskSection: "summary",
  projectOverview: null, projectSkills: null, projectKnowledge: null, taskSkillCatalog: null, taskSkillRecommendations: null,
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
function activeProject() { return state.projectFilter === "all" ? null : projectById(state.projectFilter); }
function discoveredSessionForRun(run) { return state.sessions.find((session) => session.adopted_run_id === run.id); }
function preferredProjectId() {
  const candidates = [state.selected?.project_id, state.projectFilter !== "all" ? state.projectFilter : "", state.runs[0]?.project_id, state.projects[0]?.id];
  return candidates.find((id) => id && projectById(id)) || "";
}
function syncCustomProject(select, container) {
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

function setView(view) {
  if (view === "projects" && !$("#projectsView")) view = "work";
  state.view = view;
  document.body.dataset.view = view;
  document.body.classList.toggle("task-open", view === "tasks");
  $$(".nav-button").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  $$(".view-panel").forEach((panel) => panel.classList.remove("active"));
  $(`#${view}View`)?.classList.add("active");
  const surfaceNames = {work: "Overview", attention: "Needs You", epics: "Plans", tasks: "Task", sessions: "Terminals", inbox: "Inbox", projects: "Project registry", insights: "Insights", github: "GitHub issues"};
  const project = activeProject();
  const scopedProject = ["work", "tasks", "epics", "github"].includes(view) ? project : null;
  $("#titleProject").textContent = scopedProject?.name || "Workspace";
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
  if (view === "github" && project && [...$("#githubProject").options].some((option) => option.value === project.id)) $("#githubProject").value = project.id;
  if (view === "insights") refreshInsights();
  if (view === "work") renderWork();
  updateGitHubLink();
}

function activateTab(name) {
  const selectedTab = $(`.tab[data-tab="${name}"]`);
  if (!selectedTab) return;
  if (["diff", "integration"].includes(name)) activateTaskSection("changes");
  if (["checks", "context", "review", "evaluation", "ci"].includes(name)) activateTaskSection("evidence");
  const inspector = selectedTab.closest(".inspector-panel");
  [...inspector.querySelectorAll(".tab")].forEach((item) => item.classList.toggle("active", item.dataset.tab === name));
  [...inspector.querySelectorAll(".tab-pane")].forEach((pane) => pane.classList.toggle("active", pane.id === `tab-${name}`));
}

function activateTaskSection(name) {
  state.taskSection = name;
  $$(".task-section-tab").forEach((item) => item.classList.toggle("active", item.dataset.section === name));
  $$(".task-section-pane").forEach((pane) => pane.classList.toggle("active", pane.id === `task-section-${name}`));
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
  $("#allWorkCount").textContent = state.runs.length;
  $("#sidebarAttentionCount").textContent = state.attention.length;
  $("#taskSectionTitle").textContent = activeProject()?.name?.toUpperCase() || "ALL TASKS";
  $("#projectTree").innerHTML = state.projects.length ? state.projects.map((project) => {
    const selected = project.id === state.projectFilter;
    const runs = runsForProject(project.id);
    const active = runs.filter((run) => activeStatuses.has(run.status)).length;
    const children = runs.slice(0, 5).map((run) => `<button class="${run.id === state.selectedId ? "selected" : ""}" data-project-run="${escapeHtml(run.id)}" type="button"><span>↳</span><span>${escapeHtml(run.title)}</span></button>`).join("");
    return `<div class="project-node ${selected ? "selected" : ""}"><button class="project-row ${selected ? "selected" : ""}" data-select-project="${escapeHtml(project.id)}" type="button"><span class="chevron">›</span><strong>${escapeHtml(project.name)}</strong><small>${active || runs.length}</small></button><div class="project-children"><button data-project-overview="${escapeHtml(project.id)}" type="button"><span>⌂</span><span>Overview</span></button>${children || `<button data-project-new="${escapeHtml(project.id)}" type="button"><span>＋</span><span>Start first task</span></button>`}</div></div>`;
  }).join("") : `<div class="empty-list">Add a repository to start.</div>`;
  $$('[data-select-project], [data-project-overview]').forEach((button) => button.addEventListener("click", () => selectProject(button.dataset.selectProject || button.dataset.projectOverview)));
  $$('[data-project-run]').forEach((button) => button.addEventListener("click", () => selectRun(button.dataset.projectRun)));
  $$('[data-project-new]').forEach((button) => button.addEventListener("click", () => { selectProject(button.dataset.projectNew); $("#newTaskButton").click(); }));
}

function selectProject(projectId = "all") {
  state.projectFilter = projectId && projectById(projectId) ? projectId : "all";
  state.selectedId = null;
  state.selected = null;
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
  container.innerHTML = skills.length ? skills.map((skill) => `<label class="task-skill-choice"><input type="checkbox" name="skills" value="${escapeHtml(skill.name)}" ${skill.mode === "required" ? "checked disabled" : ""}><span><strong>${escapeHtml(skill.name)}</strong><small>${escapeHtml(skill.description)}</small></span>${skill.mode === "required" ? `<em>required</em>` : ""}</label>`).join("") : `<div class="empty-list">Choose a registered project to see its skills.</div>`;
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
  container.innerHTML = selected.length ? `<small>AUTO WILL ATTACH</small>${selected.map((item) => `<div><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml((item.reasons || [])[0] || "project policy")}</span></div>`).join("")}` : "";
}

function renderProjectSkills() {
  const catalog = state.projectSkills;
  const skills = catalog?.skills || [];
  $("#projectSkillCount").textContent = `${skills.filter((skill) => skill.mode !== "disabled").length} enabled`;
  $("#projectSkillList").innerHTML = skills.length ? skills.map((skill) => { const stats = skill.effectiveness || {}; const outcome = stats.runs ? `${stats.runs} run${stats.runs === 1 ? "" : "s"}${stats.success_rate === null ? " · awaiting outcomes" : ` · ${Math.round(Number(stats.success_rate) * 100)}% successful`}` : "No project history yet"; return `<details class="project-skill" data-skill="${escapeHtml(skill.name)}"><summary><span><strong>${escapeHtml(skill.name)}</strong><small>${escapeHtml(skill.description)}</small><em class="skill-effectiveness">${escapeHtml(outcome)}</em></span><span class="skill-source">${escapeHtml(skill.scope)}</span><select class="skill-policy" data-skill-policy="${escapeHtml(skill.name)}" aria-label="Policy for ${escapeHtml(skill.name)}"><option value="auto" ${skill.mode === "auto" ? "selected" : ""}>Auto</option><option value="required" ${skill.mode === "required" ? "selected" : ""}>Required</option><option value="disabled" ${skill.mode === "disabled" ? "selected" : ""}>Disabled</option></select></summary><div class="skill-preview"><div>${(skill.triggers || []).map((trigger) => `<span>${escapeHtml(trigger)}</span>`).join("")}</div>${stats.runs ? `<p class="skill-stats">Average ${compactNumber(stats.avg_tokens)} tokens · $${Number(stats.avg_cost_usd || 0).toFixed(4)} · ${Number(stats.interventions || 0)} human interventions</p>` : ""}<pre>${escapeHtml(skill.preview || "No preview available.")}</pre></div></details>`; }).join("") : `<div class="empty-list">No valid SKILL.md files found.</div>`;
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
  $("#projectMemoryList").innerHTML = items.length ? items.map((item) => `<article class="memory-item ${item.enabled ? "" : "disabled"}"><div><strong>${escapeHtml(item.title)}</strong><p>${escapeHtml(item.content)}</p><span>${[...(item.triggers || []).map((value) => `trigger: ${value}`), ...(item.folders || []).map((value) => `folder: ${value}`)].map(escapeHtml).join(" · ") || "Always attach"}</span></div><label class="memory-toggle"><input type="checkbox" data-memory-toggle="${escapeHtml(item.id)}" ${item.enabled ? "checked" : ""}><span>${item.enabled ? "On" : "Off"}</span></label><button class="ghost compact" data-memory-edit="${escapeHtml(item.id)}" type="button">Edit</button></article>`).join("") : `<div class="empty-list">No project-specific memory yet. Add only facts that agents cannot infer reliably from the repository.</div>`;
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

function renderProjectKnowledge() {
  const project = activeProject();
  const overview = state.projectOverview;
  const home = $("#projectHome");
  home.classList.toggle("hidden", !project);
  if (!project) return;
  if (!overview || overview.project?.id !== project.id) {
    $("#projectAbout").textContent = "Loading README, instructions, commits, and project activity…";
    $("#projectAboutSource").textContent = "";
    $("#projectContextSources").innerHTML = `<div class="empty-list">Discovering repository context…</div>`;
    $("#projectSkillList").innerHTML = `<div class="empty-list">Loading project skills…</div>`;
    $("#projectMemoryList").innerHTML = `<div class="empty-list">Loading project memory…</div>`;
    $("#projectCommitList").innerHTML = `<div class="empty-list">Loading Git history…</div>`;
    $("#projectTimeline").innerHTML = `<div class="empty-list">Building project timeline…</div>`;
    return;
  }
  $("#projectAbout").textContent = overview.about;
  $("#projectAboutSource").textContent = overview.profile?.summary ? "Odysseus project brief" : overview.readme?.path ? `Read from ${overview.readme.path}` : "No README found";
  $("#projectNotes").textContent = overview.profile?.notes || "";
  $("#projectNotes").classList.toggle("hidden", !overview.profile?.notes);
  $("#projectStack").innerHTML = (overview.stack || []).map((item) => `<span>${escapeHtml(item)}</span>`).join("") || `<span>Stack not inferred</span>`;
  const sources = [...(overview.readme ? [{...overview.readme, kind: "README"}] : []), ...(overview.instructions || []).map((item) => ({...item, kind: "Instructions"}))];
  $("#projectContextCount").textContent = `${sources.length} source${sources.length === 1 ? "" : "s"}`;
  $("#projectContextSources").innerHTML = sources.length ? sources.map((source) => `<div class="context-source"><span>${escapeHtml(source.kind)}</span><div><strong>${escapeHtml(source.path)}</strong><small>${escapeHtml(source.summary || "Detected repository context")}</small></div><code>${escapeHtml(String(source.sha256 || "").slice(0, 8))}</code></div>`).join("") : `<div class="empty-list">No README or agent instruction files detected.</div>`;
  $("#projectCommitList").innerHTML = (overview.commits || []).length ? overview.commits.map((commit) => `<div class="project-commit"><code>${escapeHtml(commit.short_sha)}</code><div><strong>${escapeHtml(commit.subject)}</strong><small>${escapeHtml(commit.author)} · ${relativeTime(commit.ts)} ago</small></div></div>`).join("") : `<div class="empty-list">No Git commits found.</div>`;
  $("#projectTimeline").innerHTML = (overview.activity || []).length ? overview.activity.slice(0, 12).map((item) => `<button class="timeline-entry" data-timeline-run="${escapeHtml(item.run_id)}" type="button"><span class="timeline-dot"></span><div><small>${escapeHtml(statusLabel(item.type))} · ${relativeTime(item.ts)} ago</small><strong>${escapeHtml(item.run_title)}</strong><p>${escapeHtml(item.summary)}</p></div></button>`).join("") : `<div class="empty-list">Project activity will appear after its first task.</div>`;
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
    ? project.name
    : state.projects.length ? "Pick a Git repository" : "Add your first Git repository";
  $('[data-journey-step="2"] small').textContent = project
    ? `Say what “done” means in ${project.name}`
    : "One clear, finished outcome";
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
      else { selectProject("all"); toast("Choose a project first."); return; }
    } else setView("work");
    window.requestAnimationFrame(() => $("#quickTaskPrompt")?.focus());
  };
  buttons[2].onclick = () => {
    if (!project) { toast("Choose a project first."); return; }
    if (projectAttention.length) { setView("attention"); return; }
    if (projectRuns.length) { selectRun(projectRuns[0].id); return; }
    toast("Describe the first change before there is anything to follow.");
    window.requestAnimationFrame(() => $("#quickTaskPrompt")?.focus());
  };
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
        <span class="inline-step"><b>1</b><span>CHOOSE A PROJECT</span></span>
        <h2>Connect one repository.</h2>
        <p>Odysseus reads the existing README and agent instructions, then keeps every task on its own branch and worktree. Your source checkout is not modified by registration.</p>
        <form class="quick-project-form" id="quickProjectForm">
          <label for="quickProjectPath">Repository path</label>
          <div><input id="quickProjectPath" name="path" required placeholder="${escapeHtml(state.bootstrap?.working_directory || "/absolute/path/to/repository")}"><button class="primary" type="submit">Add repository</button></div>
        </form>
        <button class="text-button" id="copyDemoCommand" type="button">Not ready to run an agent? Copy the no-token demo command</button>
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
        toast(`${registered.name} is ready. Describe the first change.`);
      } catch (error) { toast(error.message, true); }
      finally { button.disabled = false; button.textContent = "Add repository"; }
    });
    $("#copyDemoCommand").addEventListener("click", () => copyCommand("odysseus demo"));
    return;
  }
  container.className = "quick-start quick-task-card";
  container.innerHTML = `
    <form id="quickTaskForm">
      <div class="quick-task-heading"><div><span class="inline-step"><b>2</b><span>DESCRIBE A CHANGE</span></span><h2>What should change in ${escapeHtml(project.name)}?</h2></div><span class="safety-note">Source checkout stays untouched</span></div>
      <textarea name="task" id="quickTaskPrompt" required rows="3" placeholder="Example: Make installation errors short and actionable, and add a regression test."></textarea>
      <p class="quick-task-promise">Odysseus creates an isolated branch, runs the agent and checks, then brings the result back for review.</p>
      <div class="quick-task-actions"><button class="primary" type="submit">Start task</button><button class="ghost" id="quickPlanTask" type="button">Plan larger work</button><button class="text-button" id="quickAdvancedTask" type="button">More options…</button></div>
    </form>`;
  $("#quickTaskForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.currentTarget.querySelector('button[type="submit"]');
    const task = String(new FormData(event.currentTarget).get("task") || "").trim();
    if (!task) return;
    try {
      button.disabled = true; button.textContent = "Queueing…";
      const run = await api("/api/runs", {method: "POST", body: JSON.stringify({task, project_path: project.path, lane: state.bootstrap.default_lane, skill_mode: "auto"})});
      event.currentTarget.reset();
      toast(`Task queued: ${run.title}`);
      await Promise.all([refreshRuns(), refreshProjects()]);
      await selectRun(run.id);
    } catch (error) { toast(error.message, true); }
    finally { button.disabled = false; button.textContent = "Start task"; }
  });
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
  $("#workBreadcrumb").textContent = project ? "PROJECT" : "WORKSPACE";
  $("#workTitle").textContent = project?.name || (state.projects.length ? "All work" : "Welcome to Odysseus");
  $("#workDescription").textContent = project ? "Describe a change. Odysseus runs the agent and checks; you review the result." : state.projects.length ? "Choose a project to start or continue work." : "Add a Git repository, describe a change, then review the result.";
  $("#workMeta").innerHTML = project ? `<span>${escapeHtml(project.path)}</span><span>${escapeHtml(project.branch || "Git repository")}</span>${(project.tags || []).map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}` : state.projects.length ? `<span>${state.projects.length} registered projects</span><span>${state.bootstrap?.max_parallel || 0} parallel slots</span><span>Local-first workspace</span>` : "";
  $("#workMeta").classList.toggle("hidden", !project && !state.projects.length);
  $("#workSummary").innerHTML = [
    [project ? runs.length : state.projects.length, project ? "Tasks" : "Projects", project ? "in this repository" : "registered repositories"],
    [active, "In progress", "running or queued"],
    [needs, "Needs you", needs ? "decisions waiting" : "nothing waiting"],
    [project ? terminals : complete, project ? "Terminals" : "Completed", project ? "agent panes" : "accepted changes"],
  ].map(([value, label, note]) => `<div class="work-stat"><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong><span>${escapeHtml(note)}</span></div>`).join("");
  $("#workSummary").classList.toggle("hidden", !state.projects.length);
  renderJourney();
  renderQuickStart();
  renderProjectKnowledge();
  $("#workPlanButton").classList.toggle("hidden", !project);
  $("#workNewTaskButton").classList.toggle("hidden", !state.projects.length);
  $("#newTaskButton").classList.toggle("hidden", !state.projects.length);
  $("#workListEyebrow").textContent = project ? "TASKS" : "PROJECTS";
  $("#workListTitle").textContent = project ? "Recent work" : "Your workspace";
  const secondary = $("#workSecondaryAction");
  secondary.textContent = project ? "View plans" : "Add project";
  secondary.onclick = () => project ? setView("epics") : $("#projectDialog").showModal();
  $("#workList").closest(".work-section").classList.toggle("hidden", !state.projects.length);
  if (!project) {
    $("#workList").innerHTML = state.projects.length ? state.projects.map((item) => {
      const itemRuns = runsForProject(item.id); const itemActive = itemRuns.filter((run) => activeStatuses.has(run.status)).length; const itemNeeds = attentionForProject(item.id).length;
      return `<button class="project-overview-card" data-work-project="${escapeHtml(item.id)}" type="button"><span class="project-glyph">${escapeHtml(item.name.slice(0, 1).toUpperCase())}</span><div><h3>${escapeHtml(item.name)}</h3><p>${escapeHtml(item.path)}</p></div><div class="project-card-signals"><span>${itemRuns.length} tasks</span><span>${itemActive} active</span>${itemNeeds ? `<span class="needs">${itemNeeds} need you</span>` : ""}</div></button>`;
    }).join("") : `<div class="empty-card"><strong>No projects yet.</strong><br>Add a repository, then describe the first task.</div>`;
    $$('[data-work-project]').forEach((button) => button.addEventListener("click", () => selectProject(button.dataset.workProject)));
  } else {
    $("#workList").innerHTML = runs.length ? runs.map((run) => `<button class="work-task-row" data-work-run="${escapeHtml(run.id)}" type="button"><div><h3>${escapeHtml(run.title)}</h3><p>${escapeHtml(run.task || run.workflow)}</p></div><span>${relativeTime(run.updated_at)} ago</span><span class="mini-status ${statusClass(run.status)}">${escapeHtml(statusLabel(run.status))}</span></button>`).join("") : `<div class="empty-card"><strong>No tasks in ${escapeHtml(project.name)}.</strong><br>Choose New task and describe one finished outcome.</div>`;
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
      <div class="task-card-meta"><span>${escapeHtml(run.lane)}${run.kind === "tmux" ? "" : ` · P${escapeHtml(run.priority ?? 50)}`}</span><span>${escapeHtml(projectById(run.project_id)?.name || run.kind || run.workflow)}</span></div>
      <div class="task-signals">${signals}</div>
    </button>`;
  }).join("") : `<div class="empty-list">No tasks in this view.</div>`;
  $$(".task-card[data-run-id]").forEach((button) => button.addEventListener("click", () => selectRun(button.dataset.runId)));
  renderProjectTree();
}

async function refreshRuns() {
  const data = await api("/api/runs");
  state.runs = data.runs;
  renderRuns();
  renderWork();
  if (!state.selectedId && state.runs.length && state.view === "tasks") await selectRun(state.runs[0].id);
  if (state.selectedId) {
    const current = state.runs.find((run) => run.id === state.selectedId);
    if (current && (!state.selected || current.updated_at !== state.selected.updated_at)) await refreshSelected();
  }
}

async function selectRun(runId) {
  const target = state.runs.find((run) => run.id === runId);
  if (target?.project_id) state.projectFilter = target.project_id;
  state.selectedId = runId;
  state.taskSection = "summary";
  location.hash = `task/${encodeURIComponent(runId)}`;
  setView("tasks");
  renderRuns();
  state.events = [];
  closeStream();
  await refreshSelected(true);
  activateTaskSection("summary");
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
  const interactive = run.kind === "tmux";
  $(".journey-context").classList.toggle("hidden", interactive);
  const discovered = interactive ? discoveredSessionForRun(run) : null;
  const status = $("#detailStatus");
  status.textContent = interactive ? "tracked tmux terminal" : statusLabel(run.status); status.className = `status-pill ${statusClass(run.status)}`;
  $("#detailId").textContent = run.id;
  const project = projectById(run.project_id);
  $("#detailProjectName").textContent = project?.name || "Project";
  $("#titleProject").textContent = project?.name || "Workspace";
  $("#titleSurface").textContent = run.title;
  $("#detailTitle").textContent = discovered?.title || discovered?.window_name || run.title;
  $("#detailTask").textContent = interactive ? `Existing ${run.lane} session in tmux ${discovered?.tmux_session || run.tmux_session || "—"}${(discovered?.tmux_target || run.tmux_target) ? `, pane ${discovered?.tmux_target || run.tmux_target}` : ""}.` : run.task;
  $("#observedSession").classList.toggle("hidden", !interactive);
  $("#runNarrative").classList.toggle("hidden", interactive);
  $("#metrics").classList.toggle("hidden", interactive);
  $("#detailGrid").classList.toggle("hidden", interactive);
  const metrics = run.metrics || {};
  $("#metrics").innerHTML = [
    ["Tokens", compactNumber(Number(metrics.input_tokens || 0) + Number(metrics.output_tokens || 0))],
    ["Cost", metrics.cost_usd ? `$${Number(metrics.cost_usd).toFixed(4)}` : "—"],
    ["Confidence", run.confidence === null || run.confidence === undefined ? "—" : `${Math.round(Number(run.confidence) * 100)}%`],
    ["GitHub CI", run.ci?.status || "not started"],
  ].map(([label, value]) => `<div class="metric"><small>${label}</small><strong>${escapeHtml(value)}</strong></div>`).join("");
  renderEnvironment(run);
  const metadata = interactive ? [
    ["Run ID", run.id], ["Agent", run.lane], ["Repository", projectById(run.project_id)?.name || run.project_path],
    ["tmux location", `${discovered?.tmux_session || run.tmux_session || "—"} · ${discovered?.tmux_target || run.tmux_target || "—"}`],
    ["Live pane state", discovered?.status || "not currently visible"], ["Tracking", "durable shortcut"], ["Control", "original terminal"],
  ] : [
    ["Run ID", run.id], ["Agent", run.lane], ["Environment", run.environment?.profile || "host"], ["Workflow", run.workflow], ["Project", projectById(run.project_id)?.name || run.project_path],
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
  if ($("#runDetail").dataset.runId !== run.id) { $("#runDetail").dataset.runId = run.id; activateTaskSection("summary"); }
  $("#workflowStrip").classList.toggle("hidden", interactive);
  renderActions(run); renderNarrative(run); renderWorkflow(run); renderEvents();
  $("#diffStat").textContent = diff.stat || "No changed files yet."; $("#diffPatch").textContent = diff.patch || "No diff yet.";
  renderIntegration(run); renderChecks(run.check_results || []); renderContextReceipt(run); $("#reviewSummary").textContent = run.review_summary || run.last_error || "Review has not run yet."; renderEvaluation(run.evaluation || {}); renderCI(run);
}

function renderEnvironment(run) {
  const node = $("#environmentCard");
  const environment = run.environment || {};
  if (run.kind === "tmux") { node.classList.add("hidden"); return; }
  node.classList.remove("hidden");
  const profile = environment.profile || "host";
  const profileLabel = profile === "project-default" ? "Project default" : profile;
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
    ${environment.preview_url ? `<a href="${escapeHtml(environment.preview_url)}" target="_blank" rel="noreferrer">Open preview ↗</a>` : ""}
    ${profile === "host" ? `<div class="environment-warning">Host mode is compatible, but it can access the same files, credentials, ports, and services as your user.</div>` : ""}`;
}

function renderNarrative(run) {
  const ciStatus = run.ci?.status;
  const values = {
    queued: ["IN QUEUE", "Waiting for an execution slot", "Odysseus will create an isolated worktree as soon as capacity is available.", "No action needed", "calm", "→"],
    blocked: ["DEPENDENCY GATE", "Waiting for predecessor work", "This task starts only after every required artifact has been accepted.", "Check Needs You", "warn", "⊘"],
    starting: ["ISOLATING", "Creating a safe workspace", "The source checkout stays untouched while Odysseus prepares a dedicated branch and worktree.", "No action needed", "active", "01"],
    running: ["IMPLEMENTING", "The agent is working", "Tool calls, messages, and usage appear in Activity while the implementation changes the isolated worktree.", "No action needed", "active", "02"],
    checking: ["VERIFYING", "Running deterministic checks", "Configured tests and project checks are evaluating the implementation independently of the agent.", "No action needed", "active", "03"],
    reviewing: ["REVIEWING", "Independent evidence review", "A separate reviewer is checking the diff and deterministic results before the human gate.", "No action needed", "active", "04"],
    review: ["DECISION READY", "The change is ready for you", "Inspect the diff, checks, evaluation, and merge risk. Accept it or resume the agent with precise feedback.", "Your decision", "attention", "!"],
    attention: ["QUESTION", "The agent needs one decision", "Answer in Needs You; Odysseus will continue the same agent thread and preserve the current worktree.", "Needs you", "attention", "?"],
    failed: ["STOPPED SAFELY", "The workflow could not continue", "The branch and worktree are preserved. Inspect the failure, then resume, switch agent, or continue in a terminal.", "Needs you", "danger", "×"],
    accepted: ["ACCEPTED", "A durable artifact is ready", "Downstream tasks can compose this exact Git artifact. Nothing was pushed or merged into the source checkout.", "Complete", "success", "✓"],
    publishing: ["PUBLISHING", "Preparing the draft pull request", "Odysseus is committing and pushing only this task branch before opening a draft PR.", "No action needed", "active", "↗"],
    pr_created: ["GITHUB FEEDBACK", ciStatus === "failed" ? "CI found a regression" : ciStatus === "passed" ? "CI is green" : "Draft PR is being checked", ciStatus === "failed" ? "Failure logs are captured and the bounded repair loop can resume the original agent." : "GitHub checks are tracked here until they pass or need your attention.", ciStatus === "failed" ? "Repair in progress" : ciStatus === "passed" ? "Complete" : "No action needed", ciStatus === "failed" ? "danger" : ciStatus === "passed" ? "success" : "active", ciStatus === "passed" ? "✓" : "↻"],
  };
  const environmentApproval = run.status === "attention" && run.environment?.trust_status === "pending";
  const [label, title, copy, tail, tone, mark] = environmentApproval ? ["TRUST GATE", "Review repository execution commands", "No agent or repository command has run. Approve the container profile, setup, checks, and evaluators in Needs You, or reject the task.", "Needs you", "attention", "!"] : values[run.status] || ["WORKFLOW", "Odysseus is tracking this task", "Open Activity for the latest normalized events.", "No action needed", "calm", "→"];
  $("#narrativeLabel").textContent = label; $("#narrativeTitle").textContent = title; $("#narrativeCopy").textContent = copy; $("#narrativeTail").textContent = tail; $("#narrativeMark").textContent = mark; $("#runNarrative").dataset.tone = tone;
}

function renderActions(run) {
  const actions = [];
  if (run.status === "review") actions.push(`<button class="action-button accept" data-action="accept" type="button">Approve</button>`);
  if (["attention", "review", "failed", "accepted", "pr_created"].includes(run.status)) actions.push(`<button class="action-button" data-action="resume" type="button">Give feedback</button>`);
  if (["review", "accepted"].includes(run.status)) actions.push(`<button class="action-button" data-action="draft-pr" type="button">Draft PR</button>`);
  if (run.tmux_session || run.agent_sessions?.agent || run.agent_session_id) actions.push(`<button class="action-button" data-action="takeover" type="button" title="Copies a command that opens this agent in your terminal">${run.kind === "tmux" ? "Copy tmux command" : "Continue in terminal"}</button>`);
  if (activeStatuses.has(run.status) && run.status !== "cancelling") actions.push(`<button class="action-button warn" data-action="cancel" type="button">Cancel</button>`);
  if (run.pull_request_url) actions.push(`<a class="action-button accept" href="${escapeHtml(run.pull_request_url)}" target="_blank" rel="noreferrer">Open PR</a>`);
  if (run.pull_request_url) actions.push(`<button class="action-button" data-action="ci-poll" type="button">Poll CI</button>`);
  $("#runActions").innerHTML = actions.join("");
  $$("#runActions [data-action]").forEach((button) => button.addEventListener("click", () => runAction(button.dataset.action)));
}

function renderWorkflow(run) {
  const status = run.status; let current = 0;
  if ((run.integration_sources || []).length) current = 2; else if (run.worktree_path || status === "running") current = 1;
  if (status === "running") current = 2;
  if (status === "checking") current = 3;
  if (["reviewing", "review", "accepted", "publishing"].includes(status)) current = 4;
  if (status === "pr_created") current = 5;
  ["stageWorktree", "stageIntegrate", "stageAgent", "stageCheck", "stageReview", "stageCI"].forEach((id, index) => {
    const node = $(`#${id}`); node.classList.toggle("done", index < current || (status === "pr_created" && index < 5) || run.ci?.status === "passed"); node.classList.toggle("current", index === current && (activeStatuses.has(status) || status === "pr_created"));
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
    const content = source.kind === "skill" ? String(snapshot?.content || "").slice(0, 16000) : String(snapshot?.content || "");
    return `<details class="receipt-source"><summary><span class="receipt-kind">${escapeHtml(source.kind)}</span><span><strong>${escapeHtml(source.title)}</strong><small>${escapeHtml(source.reason)}</small></span><code>${escapeHtml(String(source.sha256 || "").slice(0, 10))}</code></summary><div><span>${escapeHtml(source.path)}</span><span>${compactNumber(source.bytes)} bytes</span></div><pre>${escapeHtml(content || "Snapshot content is unavailable.")}</pre></details>`;
  }).join("");
  $("#contextReceipt").innerHTML = `<section class="receipt-head"><div><small>CONTEXT RECEIPT</small><strong>${escapeHtml(receipt.version)}</strong><p>These immutable snapshots are exactly what Odysseus attached when the task was queued.</p></div><code title="Complete bundle digest">${escapeHtml(receipt.bundle_sha256 || "")}</code></section><div class="receipt-source-list">${sourceRows || `<div class="empty-card">No project or skill context was attached.</div>`}</div>`;
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

function renderCI(run) {
  const ci = run.ci || {status: "not_started", checks: []};
  const checks = ci.checks || [];
  $("#ciResults").innerHTML = `
    <div class="ci-hero ci-${escapeHtml(ci.status || "not_started")}"><div><small>GITHUB CHECKS</small><strong>${escapeHtml(statusLabel(ci.status || "not_started"))}</strong></div><span>${escapeHtml(ci.summary || "Publish a draft PR to start the feedback loop.")}</span></div>
    ${checks.length ? checks.map((check) => `<div class="ci-check"><span>${escapeHtml(check.workflow || "workflow")}</span><strong>${escapeHtml(check.name || "check")}</strong><em>${escapeHtml(check.bucket || check.state || "unknown")}</em></div>`).join("") : `<div class="empty-card">No GitHub check runs recorded.</div>`}
    ${ci.logs ? `<details class="ci-logs"><summary>Failed log captured for agent resume</summary><pre>${escapeHtml(ci.logs)}</pre></details>` : ""}
    <div class="ci-foot"><span>Automatic repairs: ${escapeHtml(ci.attempt || 0)}</span><span>${ci.updated_at ? `Updated ${relativeTime(ci.updated_at)} ago` : "Not polled"}</span></div>`;
}

function openStream(runId) {
  if (state.view !== "tasks" || state.stream) return;
  const after = state.events.at(-1)?.seq || 0; const stream = new EventSource(`/api/runs/${encodeURIComponent(runId)}/stream?after=${after}`); state.stream = stream;
  stream.addEventListener("odysseus", (message) => {
    const event = JSON.parse(message.data); if (state.events.some((item) => item.seq === event.seq)) return;
    state.events.push(event); renderEvents(); window.clearTimeout(state.refreshTimer);
    state.refreshTimer = window.setTimeout(async () => { await refreshRuns(); if (["run.review_ready", "run.failed", "run.accepted", "pr.created", "artifact.created", "integration.completed", "integration.conflict", "ci.started", "ci.failed", "ci.passed", "ci.retry_pushed", "agent.usage", "agent.tool.started"].includes(event.type)) await refreshSelected(); }, 180);
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
    else toast(action === "draft-pr" ? "Draft pull request created." : action === "ci-poll" ? "GitHub checks refreshed." : `Action completed: ${action}`);
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
    const options = (item.options || []).map((option) => `<button class="${option.id === "takeover" ? "ghost" : "primary"}" data-attention-answer="${escapeHtml(item.id)}" data-answer="${escapeHtml(option.id)}" type="button">${escapeHtml(option.label)}</button>`).join("");
    return `<article class="stack-card attention-card priority-${escapeHtml(item.priority)}"><div class="card-row"><span class="mini-status status-${item.priority === "high" || item.priority === "critical" ? "failed" : "queued"}">${escapeHtml(item.priority)} · ${escapeHtml(statusLabel(item.type))}</span><span class="run-id">${relativeTime(item.created_at)}</span></div><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.message)}</p><div class="card-actions">${options}<button class="ghost" data-attention-custom="${escapeHtml(item.id)}" type="button">Answer…</button>${item.run_id ? `<button class="ghost" data-open-run="${escapeHtml(item.run_id)}" type="button">Open task</button>` : ""}<button class="ghost" data-attention-resolve="${escapeHtml(item.id)}" type="button">Resolve</button></div></article>`;
  }).join("") : `<div class="attention-zero"><span class="all-clear-mark">✓</span><p class="eyebrow">ALL CLEAR</p><strong>Nothing needs you right now.</strong><p>Agents can keep working. Questions, permission requests, failures, and review gates will appear here automatically.</p><div class="empty-actions"><button class="primary" data-attention-new type="button">Start a task</button><button class="ghost" data-attention-epic type="button">Plan multi-task work</button><button class="ghost" data-open-terminals type="button">View agent terminals</button></div></div>`;
  $$('[data-attention-answer]').forEach((button) => button.addEventListener("click", () => respondAttention(button.dataset.attentionAnswer, button.dataset.answer)));
  $$('[data-attention-custom]').forEach((button) => button.addEventListener("click", () => { const response = window.prompt("Answer the agent or add guidance:"); if (response) respondAttention(button.dataset.attentionCustom, response); }));
  $$('[data-attention-resolve]').forEach((button) => button.addEventListener("click", async () => { await api(`/api/attention/${encodeURIComponent(button.dataset.attentionResolve)}/resolve`, {method: "POST", body: "{}"}); await refreshAttention(); }));
  $$('[data-open-run]').forEach((button) => button.addEventListener("click", () => selectRun(button.dataset.openRun)));
  $('[data-attention-new]')?.addEventListener("click", () => $("#newTaskButton").click());
  $('[data-attention-epic]')?.addEventListener("click", () => $("#newEpicButton").click());
  $('[data-open-terminals]')?.addEventListener("click", () => setView("sessions"));
}

async function respondAttention(itemId, response) {
  try {
    const result = await api(`/api/attention/${encodeURIComponent(itemId)}/respond`, {method: "POST", body: JSON.stringify({response})});
    if (result.takeover?.command) await copyCommand(result.takeover.command);
    else if (result.run?.project_commands_approved) toast("Environment approved; the task is queued.");
    else if (result.run?.status === "cancelled") toast("Configuration rejected; the task was cancelled.");
    else toast("Response recorded; the same agent session was queued to continue.");
    await Promise.all([refreshAttention(), refreshRuns(), refreshEpics()]);
  } catch (error) { toast(error.message, true); }
}

async function refreshEpics() {
  state.epics = (await api("/api/epics")).epics;
  $("#epicNavCount").textContent = state.epics.filter((epic) => ["planning", "proposed", "active"].includes(epic.status)).length || "";
  const visibleEpics = activeProject() ? state.epics.filter((epic) => epic.project_id === state.projectFilter) : state.epics;
  $("#epicList").innerHTML = visibleEpics.length ? visibleEpics.map((epic) => {
    const tasks = epic.plan?.tasks || [];
    const graph = tasks.length ? `<div class="dag">${tasks.map((task) => `<div class="dag-node"><div><strong>${escapeHtml(task.title)}</strong><small>${escapeHtml(task.role || "implementer")} · ${escapeHtml(task.lane || "default")}</small></div><span>${task.depends_on?.length ? `after ${escapeHtml(task.depends_on.join(", "))}` : "ready"}</span></div>`).join("")}</div>` : "";
    return `<article class="stack-card epic-card"><div class="card-row"><span class="mini-status ${statusClass(epic.status)}">${escapeHtml(epic.status)}</span><span class="run-id">${escapeHtml(projectById(epic.project_id)?.name || "project")}</span></div><h3>${escapeHtml(epic.title)}</h3><p>${escapeHtml(epic.plan?.summary || epic.description || "Planning…")}</p>${graph}<div class="card-actions">${epic.status === "proposed" ? `<button class="primary" data-approve-epic="${escapeHtml(epic.id)}" type="button">Approve plan</button>` : ""}${(epic.run_ids || []).map((runId) => `<button class="ghost" data-open-run="${escapeHtml(runId)}" type="button">${escapeHtml(state.runs.find((run) => run.id === runId)?.task_key || "task")}</button>`).join("")}</div></article>`;
  }).join("") : `<div class="empty-card">No plans yet. Describe a larger feature; review the proposed tasks before anything starts.</div>`;
  $$('[data-approve-epic]').forEach((button) => button.addEventListener("click", async () => { if (!window.confirm("Approve this task graph and start every ready root task?")) return; try { await api(`/api/epics/${encodeURIComponent(button.dataset.approveEpic)}/approve`, {method: "POST", body: "{}"}); toast("Plan approved. Ready tasks are queued."); await Promise.all([refreshEpics(), refreshRuns()]); } catch (error) { toast(error.message, true); } }));
  $$('[data-open-run]').forEach((button) => button.addEventListener("click", () => selectRun(button.dataset.openRun)));
}

async function refreshProjects() {
  state.projects = (await api("/api/projects")).projects;
  const projectOptions = state.projects.map((project) => `<option value="${escapeHtml(project.id)}">${escapeHtml(project.name)}</option>`).join("");
  $("#projectFilter").innerHTML = `<option value="all">All projects</option>${projectOptions}`; $("#projectFilter").value = state.projectFilter;
  const preferred = preferredProjectId();
  $("#taskProjectSelect").innerHTML = `${projectOptions}<option value="">Other repository path…</option>`;
  $("#epicProjectSelect").innerHTML = `${projectOptions}<option value="">Other repository path…</option>`;
  if (preferred) { $("#taskProjectSelect").value = preferred; $("#epicProjectSelect").value = preferred; }
  syncCustomProject($("#taskProjectSelect"), $("#taskCustomProject"));
  syncCustomProject($("#epicProjectSelect"), $("#epicCustomProject"));
  $("#inboxProjectSelect").innerHTML = `<option value="">No project</option>${projectOptions}`;
  $("#githubProject").innerHTML = state.projects.filter((project) => project.github_url).map((project) => `<option value="${escapeHtml(project.id)}">${escapeHtml(project.name)}</option>`).join("") || `<option value="">No GitHub projects</option>`;
  renderProjects(); renderRuns(); renderProjectTree(); renderWork(); updateGitHubLink();
}

function renderProjects() {
  $("#projectList").innerHTML = state.projects.length ? state.projects.map((project) => `
    <article class="collection-card"><div class="card-row"><span class="mini-status status-accepted">registered</span><span class="run-id">${escapeHtml(project.branch || "git")}</span></div>
      <h3>${escapeHtml(project.name)}</h3><p>${escapeHtml(project.path)}</p><div class="card-meta">${(project.tags || []).map((tag) => `<span>${escapeHtml(tag)}</span>`).join("") || "<span>automatic</span>"}</div>
      <div class="card-actions"><button class="ghost" data-filter-project="${escapeHtml(project.id)}" type="button">View tasks</button>${project.github_url ? `<a class="action-button" href="${escapeHtml(project.github_url)}" target="_blank" rel="noreferrer">GitHub</a>` : ""}</div></article>`).join("") : `<div class="empty-card">No projects yet. Queue a task, launch a managed tmux session, or add one here.</div>`;
  $$('[data-filter-project]').forEach((button) => button.addEventListener("click", () => selectProject(button.dataset.filterProject)));
}

function updateGitHubLink() {
  const project = projectById(state.selected?.project_id || (state.projectFilter !== "all" ? state.projectFilter : "")); const link = $("#githubButton");
  const url = project?.github_url || state.bootstrap?.repository_url || "https://github.com/jpolec/odysseus";
  link.classList.remove("disabled"); link.href = url; link.title = project?.github_url ? `Open ${project.name} on GitHub` : "Open Odysseus on GitHub";
}

async function refreshSessions() {
  try { state.sessions = (await api("/api/tmux/sessions")).sessions; renderSessions(); $("#sessionNavCount").textContent = state.sessions.length || ""; renderProjectTree(); renderWork(); }
  catch (error) { $("#sessionList").innerHTML = `<div class="empty-card">${escapeHtml(error.message)}</div>`; }
}

function renderSessions() {
  const visibleSessions = state.sessionScope === "attached" ? state.sessions.filter((session) => session.attached) : state.sessions;
  const uniqueTmux = new Set(state.sessions.map((session) => session.tmux_session)).size;
  const waiting = state.sessions.filter((session) => session.status === "waiting").length;
  const working = state.sessions.filter((session) => session.status === "working").length;
  const tracked = state.sessions.filter((session) => session.adopted_run_id).length;
  $("#sessionSummary").innerHTML = [
    [state.sessions.length, "agent panes", `${uniqueTmux} tmux sessions`], [working, "working", "visible tmux activity"], [waiting, "need terminal input", "action required"], [tracked, "tracked", "durable Odysseus entries"],
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
  }).join("") : `<div class="empty-card"><strong>${state.sessionScope === "attached" && state.sessions.length ? "No panes in an attached tmux session." : "No agent terminals found."}</strong><br>${state.sessionScope === "attached" && state.sessions.length ? "Choose “All discovered sessions” to see detached tmux sessions." : "Start Codex or Claude inside tmux; it will appear here automatically within a few seconds. There is no import button."}</div>`;
  $$('[data-open-run]').forEach((button) => button.addEventListener("click", () => selectRun(button.dataset.openRun)));
  $$('[data-attach]').forEach((button) => button.addEventListener("click", () => copyCommand(button.dataset.paneTarget ? `tmux select-pane -t ${button.dataset.paneTarget} \\; attach-session -t ${button.dataset.attach}` : `tmux attach-session -t ${button.dataset.attach}`)));
  $$('[data-adopt]').forEach((button) => button.addEventListener("click", async () => { try { const run = await api(`/api/tmux/sessions/${encodeURIComponent(button.dataset.adopt)}/adopt`, {method: "POST", body: "{}"}); toast("Now tracking this pane. The original tmux session was not changed."); await Promise.all([refreshSessions(), refreshRuns(), refreshProjects()]); await selectRun(run.id); } catch (error) { toast(error.message, true); } }));
}

async function refreshInbox() { state.inbox = (await api("/api/inbox")).items; renderInbox(); $("#inboxNavCount").textContent = state.inbox.filter((item) => item.status === "open").length || ""; }
function renderInbox() {
  $("#inboxList").innerHTML = state.inbox.length ? state.inbox.map((item) => `<article class="stack-card"><div class="card-row"><span class="mini-status ${item.status === "open" ? "status-queued" : "status-accepted"}">${escapeHtml(item.status)}</span><span class="run-id">${relativeTime(item.updated_at)}</span></div><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.task)}</p><div class="card-meta"><span>${escapeHtml(item.source)}</span><span>${escapeHtml(projectById(item.project_id)?.name || "no project")}</span><span>${escapeHtml(item.priority)}</span></div><div class="card-actions">${item.status === "open" && item.project_path ? `<button class="primary" data-promote="${escapeHtml(item.id)}" type="button">Queue as agent task</button>` : ""}${item.status === "open" ? `<button class="ghost" data-resolve="${escapeHtml(item.id)}" type="button">Resolve</button>` : ""}</div></article>`).join("") : `<div class="empty-card"><strong>No parked follow-ups.</strong><br>Use “Add follow-up” to save work for later. Adding an item does not start an agent; “Queue as agent task” does.</div>`;
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
  $("#projectProfileForm").addEventListener("submit", async (event) => { if (event.submitter?.value === "cancel") return; event.preventDefault(); const project = activeProject(); if (!project) return; const submit = event.submitter; const data = new FormData(event.currentTarget); try { submit.disabled = true; await api(`/api/projects/${encodeURIComponent(project.id)}/profile`, {method: "POST", body: JSON.stringify({summary: data.get("summary"), notes: data.get("notes")})}); projectProfileDialog.close(); await refreshProjectOverview(); toast("Project brief saved."); } catch (error) { toast(error.message, true); } finally { submit.disabled = false; } });
  $("#addProjectMemory").addEventListener("click", () => openKnowledgeDialog());
  $("#knowledgeForm").addEventListener("submit", async (event) => { if (event.submitter?.value === "cancel") return; event.preventDefault(); const project = activeProject(); if (!project) return; const submit = event.submitter; const data = new FormData(event.currentTarget); const payload = {id: data.get("id"), source: data.get("source"), title: data.get("title"), content: data.get("content"), triggers: String(data.get("triggers") || "").split(",").map((value) => value.trim()).filter(Boolean), folders: String(data.get("folders") || "").split(",").map((value) => value.trim()).filter(Boolean), enabled: data.get("enabled") === "on"}; try { submit.disabled = true; state.projectKnowledge = await api(`/api/projects/${encodeURIComponent(project.id)}/knowledge`, {method: "POST", body: JSON.stringify(payload)}); $("#knowledgeDialog").close(); renderProjectMemory(); toast("Project memory saved."); } catch (error) { toast(error.message, true); } finally { submit.disabled = false; } });
  const taskDialog = $("#taskDialog");
  [$("#newTaskButton"), $("#emptyNewTask"), $("#workNewTaskButton")].forEach((button) => button?.addEventListener("click", () => { prepareProjectSelect($("#taskProjectSelect"), $("#taskCustomProject")); refreshTaskSkillChoices().catch((error) => toast(error.message, true)); taskDialog.showModal(); }));
  $("#taskProjectSelect").addEventListener("change", () => { syncCustomProject($("#taskProjectSelect"), $("#taskCustomProject")); refreshTaskSkillChoices().catch((error) => toast(error.message, true)); });
  $("#taskPrompt").addEventListener("input", scheduleTaskSkillRecommendations);
  $("#taskSkillMode").addEventListener("change", () => { renderTaskSkillChoices(); renderTaskSkillRecommendations(); scheduleTaskSkillRecommendations(); });
  $("#environmentProfile").addEventListener("change", (event) => $("#environmentOptions").classList.toggle("hidden", event.currentTarget.value !== "docker"));
  $("#untrustedProject").addEventListener("change", (event) => { if (!event.currentTarget.checked) return; const select = $("#environmentProfile"); const docker = select.querySelector('option[value="docker"]'); if (docker?.disabled) { event.currentTarget.checked = false; toast("Install Docker before running an untrusted repository.", true); return; } select.value = "docker"; select.dispatchEvent(new Event("change")); });
  $("#epicProjectSelect").addEventListener("change", () => syncCustomProject($("#epicProjectSelect"), $("#epicCustomProject")));
  $("#taskForm").addEventListener("submit", async (event) => { if (event.submitter?.value === "cancel") return; event.preventDefault(); const submit = event.submitter; const data = new FormData(event.currentTarget); const project = projectById(data.get("project_id")); let environment; try { environment = environmentFromForm(data); } catch (error) { toast(error.message, true); return; } const payload = {task: data.get("task"), title: data.get("title"), project_path: project?.path || data.get("project_path"), lane: data.get("lane"), skill_mode: data.get("skill_mode"), skills: data.getAll("skills"), environment, untrusted_project: data.get("untrusted_project") === "on", workflow: "agent-check-review", priority: Number(data.get("priority")), max_retries: Number(data.get("max_retries")), checks: String(data.get("checks") || "").split("\n").map((item) => item.trim()).filter(Boolean), budgets: {timeout_seconds: Number(data.get("timeout")), stall_seconds: Number(data.get("stall_timeout")), max_tokens: Number(data.get("max_tokens")), max_tool_calls: Number(data.get("max_tool_calls")), max_cost_usd: Number(data.get("max_cost"))}}; try { submit.disabled = true; submit.textContent = "Starting…"; const run = await api("/api/runs", {method: "POST", body: JSON.stringify(payload)}); taskDialog.close(); event.currentTarget.reset(); $("#environmentOptions").classList.add("hidden"); state.taskSkillCatalog = null; state.taskSkillRecommendations = null; renderTaskSkillChoices(); renderTaskSkillRecommendations(); toast(`Task queued: ${run.title}`); await Promise.all([refreshRuns(), refreshProjects()]); await selectRun(run.id); } catch (error) { toast(error.message, true); } finally { submit.disabled = false; submit.textContent = "Start task"; } });
  [$("#newEpicButton"), $("#workPlanButton")].forEach((button) => button?.addEventListener("click", () => { prepareProjectSelect($("#epicProjectSelect"), $("#epicCustomProject")); $("#epicDialog").showModal(); }));
  $("#epicForm").addEventListener("submit", async (event) => { if (event.submitter?.value === "cancel") return; event.preventDefault(); const submit = event.submitter; const data = new FormData(event.currentTarget); const project = projectById(data.get("project_id")); const payload = {requirement: data.get("requirement"), project_path: project?.path || data.get("project_path"), planner_lane: data.get("planner_lane"), lane: data.get("lane"), review_lane: data.get("review_lane"), checks: String(data.get("checks") || "").split("\n").map((item) => item.trim()).filter(Boolean)}; try { submit.disabled = true; submit.textContent = "Reading repository…"; await api("/api/epics/plan", {method: "POST", body: JSON.stringify(payload)}); $("#epicDialog").close(); event.currentTarget.reset(); toast("Task graph proposed. Review it before approving any work."); await refreshEpics(); setView("epics"); } catch (error) { toast(error.message, true); } finally { submit.disabled = false; submit.textContent = "Generate task plan"; } });
  $("#feedbackForm").addEventListener("submit", async (event) => { if (event.submitter?.value === "cancel") return; event.preventDefault(); const data = new FormData(event.currentTarget); const prompt = data.get("feedback"); const strategy = data.get("strategy"); try { await api(`/api/runs/${encodeURIComponent(state.selectedId)}/resume`, {method: "POST", body: JSON.stringify({prompt, strategy, lane: data.get("lane")})}); $("#feedbackDialog").close(); event.currentTarget.reset(); toast(strategy === "resume" ? "Existing agent session queued for continuation." : strategy === "switch" ? "Branch handed to the selected lane." : "Clean-context attempt queued on the same branch."); await refreshRuns(); await refreshSelected(); } catch (error) { toast(error.message, true); } });
  $("#newInboxButton").addEventListener("click", () => $("#inboxDialog").showModal());
  $("#inboxForm").addEventListener("submit", async (event) => { if (event.submitter?.value === "cancel") return; event.preventDefault(); const data = new FormData(event.currentTarget); const project = projectById(data.get("project_id")); await api("/api/inbox", {method: "POST", body: JSON.stringify({title: data.get("title"), task: data.get("task"), project_id: project?.id || "", project_path: project?.path || ""})}); $("#inboxDialog").close(); event.currentTarget.reset(); await refreshInbox(); });
  [$("#addProjectButton"), $("#manageAddProjectButton")].forEach((button) => button?.addEventListener("click", () => $("#projectDialog").showModal()));
  $("#projectForm").addEventListener("submit", async (event) => { if (event.submitter?.value === "cancel") return; event.preventDefault(); const data = new FormData(event.currentTarget); try { const registered = await api("/api/projects", {method: "POST", body: JSON.stringify({path: data.get("path"), name: data.get("name"), tags: String(data.get("tags") || "").split(",").map((tag) => tag.trim()).filter(Boolean)})}); $("#projectDialog").close(); event.currentTarget.reset(); await refreshProjects(); selectProject(registered.id); toast(`${registered.name} is ready.`); } catch (error) { toast(error.message, true); } });
}

async function init() {
  try {
    state.bootstrap = await api("/api/bootstrap"); $("#parallelLabel").textContent = `${state.bootstrap.max_parallel} slots`; const laneOptions = state.bootstrap.lanes.map((lane) => `<option value="${escapeHtml(lane)}">${escapeHtml(lane)}</option>`).join(""); $("#laneSelect").innerHTML = laneOptions; $("#plannerLaneSelect").innerHTML = laneOptions; $("#epicLaneSelect").innerHTML = laneOptions; $("#epicReviewLaneSelect").innerHTML = laneOptions; $("#resumeLaneSelect").innerHTML = laneOptions;
    [["docker", "Docker is not installed"], ["devcontainer", "Dev Container CLI is not installed"]].forEach(([profile, message]) => { const option = $("#environmentProfile").querySelector(`option[value="${profile}"]`); if (option && !state.bootstrap.capabilities?.[profile]) { option.disabled = true; option.textContent += ` — unavailable`; option.title = message; } });
    bindDialogs();
    $$(".nav-button").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view))); $$('[data-open-view]').forEach((button) => button.addEventListener("click", () => setView(button.dataset.openView)));
    $$(".filter").forEach((button) => button.addEventListener("click", () => { state.filter = button.dataset.filter; $$(".filter").forEach((item) => item.classList.toggle("active", item === button)); renderRuns(); }));
    $$(".tab").forEach((button) => button.addEventListener("click", () => activateTab(button.dataset.tab)));
    $$(".task-section-tab").forEach((button) => button.addEventListener("click", () => activateTaskSection(button.dataset.section)));
    $("#allWorkButton").addEventListener("click", () => selectProject("all")); $("#sidebarAttentionButton").addEventListener("click", () => setView("attention")); $("#backToProject").addEventListener("click", () => selectProject(state.selected?.project_id || state.projectFilter));
    $(".brand").addEventListener("click", (event) => { event.preventDefault(); selectProject("all"); });
    $("#projectFilter").addEventListener("change", (event) => selectProject(event.target.value)); $("#sessionScope").addEventListener("change", (event) => { state.sessionScope = event.target.value; renderSessions(); }); $("#refreshSessions").addEventListener("click", refreshSessions); $("#refreshAttention").addEventListener("click", refreshAttention); $("#refreshInsights").addEventListener("click", refreshInsights); $("#loadIssues").addEventListener("click", loadIssues); $("#runSearch").addEventListener("click", () => runSearch()); $("#insightSearch").addEventListener("keydown", (event) => { if (event.key === "Enter") runSearch(); }); $("#globalSearch").addEventListener("keydown", (event) => { if (event.key === "Enter") runSearch(event.currentTarget.value); });
    document.addEventListener("keydown", (event) => { if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); $("#globalSearch").focus(); } });
    await Promise.all([refreshProjects(), refreshSessions(), refreshInbox(), refreshAttention(), refreshEpics()]); await refreshRuns();
    const params = new URLSearchParams(location.search);
    const match = decodeURIComponent(location.hash.slice(1)).match(/^task\/(.+)$/); if (match && state.runs.some((run) => run.id === match[1])) await selectRun(match[1]);
    else { const projectMatch = decodeURIComponent(location.hash.slice(1)).match(/^project\/(.+)$/); if (projectMatch && projectById(projectMatch[1])) selectProject(projectMatch[1]); else { const requestedView = params.get("view"); if (["work", "attention", "epics", "tasks", "sessions", "inbox", "projects", "insights", "github"].includes(requestedView)) { if (requestedView === "tasks" && state.runs.length) await selectRun(state.runs[0].id); else setView(requestedView); } else setView("work"); } }
    const requestedTab = params.get("tab"); if (["diff", "integration", "checks", "context", "review", "evaluation", "ci"].includes(requestedTab)) activateTab(requestedTab);
    const requestedDialog = params.get("dialog"); if (requestedDialog === "task") { $("#taskPrompt").value = params.get("prompt") || ""; $("#newTaskButton").click(); scheduleTaskSkillRecommendations(); } else if (requestedDialog === "epic") $("#newEpicButton").click();
    setConnection(true);
    window.setInterval(() => refreshRuns().catch(() => setConnection(false)), 3000);
    window.setInterval(() => Promise.all([refreshSessions(), refreshInbox(), refreshAttention(), refreshEpics()]).catch(() => setConnection(false)), 6000);
  } catch (error) { setConnection(false); toast(error.message, true); }
}

window.addEventListener("beforeunload", closeStream);
init();
