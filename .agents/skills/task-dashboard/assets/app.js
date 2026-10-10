const labels = { in_progress: "In progress", blocked: "Blocked", todo: "Todo", done: "Done" };
const symbols = { in_progress: "◕", blocked: "⊗", todo: "○", done: "✓" };
const order = ["in_progress", "blocked", "todo", "done"];
const state = { data: null, file: null, status: "all", priority: "all", tag: "all", search: "", selectedId: null, layout: localStorage.getItem("task-dashboard-layout") === "board" ? "board" : "list" };

function node(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined) item.textContent = text;
  return item;
}

function setView(file) {
  state.file = file;
  closeDetail();
  render();
}

function issueId(task) {
  const file = task.file.split("/").pop().replace(/\.md$/i, "");
  const prefix = file.match(/^\d+/)?.[0] || file.replace(/[^a-z0-9]/gi, "").slice(0, 3).toUpperCase() || "TASK";
  return `${prefix}-${task.line}`;
}

function renderNavigation() {
  const { project, files, tasks } = state.data;
  document.getElementById("project-name").textContent = project;
  document.getElementById("project-initial").textContent = project[0]?.toUpperCase() || "P";
  document.getElementById("breadcrumb-project").textContent = project;
  document.getElementById("all-count").textContent = tasks.length;
  document.getElementById("all-files").classList.toggle("active", state.file === null);
  const fileList = document.getElementById("file-list");
  fileList.replaceChildren();
  for (const file of files) {
    const button = node("button", `nav-item${state.file === file.path ? " active" : ""}`);
    button.type = "button";
    button.title = file.path;
    button.append(node("span", "nav-icon", "◧"), node("span", "", file.name), node("span", "nav-count", file.count));
    button.addEventListener("click", () => setView(file.path));
    fileList.append(button);
  }
}

function priorityMatch(task, priority = state.priority) {
  if (priority === "all") return true;
  if (priority === "none") return !task.priority;
  return task.priority === priority;
}

function tagMatch(task, tag = state.tag) {
  if (tag === "all") return true;
  if (tag === "none") return task.tag.length === 0;
  return task.tag.includes(tag);
}

function inScope(task, ignore) {
  if (state.file && task.file !== state.file) return false;
  if (ignore !== "status" && ! (state.status === "all" || task.status === state.status)) return false;
  if (ignore !== "priority" && !priorityMatch(task)) return false;
  if (ignore !== "tag" && !tagMatch(task)) return false;
  return true;
}

function addFilter(container, pressed, label, count, onClick) {
  const button = node("button", `filter${pressed ? " active" : ""}`);
  button.type = "button";
  button.setAttribute("aria-pressed", String(pressed));
  button.append(node("span", "", label), node("span", "filter-count", count));
  button.addEventListener("click", () => { onClick(); closeDetail(); render(); });
  container.append(button);
}

function renderFilters() {
  const filters = document.getElementById("filters");
  filters.replaceChildren();
  const statuses = state.data.tasks.filter(task => inScope(task, "status"));
  for (const status of ["all", ...order]) {
    addFilter(filters, state.status === status, status === "all" ? "All" : labels[status], status === "all" ? statuses.length : statuses.filter(task => task.status === status).length, () => { state.status = status; });
  }

  const priorityFilters = document.getElementById("priority-filters");
  priorityFilters.replaceChildren();
  const prioritySource = state.data.tasks.filter(task => inScope(task, "priority"));
  addFilter(priorityFilters, state.priority === "all", "All", prioritySource.length, () => { state.priority = "all"; });
  for (const priority of state.data.schema.priority) {
    addFilter(priorityFilters, state.priority === priority, priority, prioritySource.filter(task => task.priority === priority).length, () => { state.priority = priority; });
  }
  addFilter(priorityFilters, state.priority === "none", "None", prioritySource.filter(task => !task.priority).length, () => { state.priority = "none"; });

  const tagFilters = document.getElementById("tag-filters");
  tagFilters.replaceChildren();
  const tagSource = state.data.tasks.filter(task => inScope(task, "tag"));
  addFilter(tagFilters, state.tag === "all", "All", tagSource.length, () => { state.tag = "all"; });
  for (const tag of state.data.schema.tag) {
    addFilter(tagFilters, state.tag === tag, tag, tagSource.filter(task => task.tag.includes(tag)).length, () => { state.tag = tag; });
  }
  addFilter(tagFilters, state.tag === "none", "None", tagSource.filter(task => task.tag.length === 0).length, () => { state.tag = "none"; });
}

function taskTags(task) {
  if (!task.priority && !task.tag.length) return null;
  const tags = node("span", "task-tags");
  if (task.priority) tags.append(node("span", "tag priority", task.priority));
  for (const value of task.tag) tags.append(node("span", "tag task-tag", value));
  return tags;
}

function taskEntry(task, layout) {
  const entry = node("button", `task-entry ${layout === "board" ? "board-card" : "task-row"}${state.selectedId === task.id ? " selected" : ""}`);
  entry.type = "button";
  entry.setAttribute("aria-label", `${issueId(task)} ${task.title}`);
  const title = node("span", "task-title", task.title);
  title.title = task.title;
  const tags = taskTags(task);
  const section = node("span", "task-section", task.section);
  section.title = task.section;
  const location = node("span", "task-location", task.file.split("/").pop().replace(/\.md$/i, ""));
  location.title = `${task.file}:${task.line}`;
  if (layout === "board") {
    const header = node("span", "board-card-header");
    header.append(node("span", "task-id", issueId(task)), location);
    entry.append(header, title);
    if (tags) entry.append(tags);
    entry.append(section);
  } else {
    const main = node("span", "task-main");
    main.append(title);
    if (tags) main.append(tags);
    entry.append(node("span", `task-status ${task.status}`, symbols[task.status]), node("span", "task-id", issueId(task)), main, section, location);
  }
  entry.addEventListener("click", () => openDetail(task, entry));
  return entry;
}

function renderTasks() {
  const query = state.search.toLowerCase();
  const tasks = state.data.tasks.filter(task =>
    inScope(task) &&
    (!query || `${task.title} ${task.section} ${task.file} ${task.priority || ""} ${task.tag.join(" ")}`.toLowerCase().includes(query))
  );
  document.getElementById("visible-count").textContent = tasks.length;
  const list = document.getElementById("task-list");
  const horizontalScroll = list.scrollLeft;
  const columnScroll = Object.fromEntries([...list.querySelectorAll(".board-column")].map(column => [column.dataset.status, column.querySelector(".board-column-cards").scrollTop]));
  list.className = `task-list ${state.layout}-view`;
  list.replaceChildren();
  if (!tasks.length) {
    const empty = node("div", "empty");
    empty.append(node("div", "empty-icon", "◇"), node("strong", "", "No tasks found"), node("p", "", "Try another file, status, priority, tag, or search term."));
    list.append(empty);
    return;
  }
  if (state.layout === "board") {
    const statuses = state.status === "all" ? order.filter(status => tasks.some(task => task.status === status)) : [state.status];
    for (const status of statuses) {
      const group = tasks.filter(task => task.status === status);
      const column = node("section", "board-column");
      column.dataset.status = status;
      const heading = node("div", "board-column-header");
      heading.append(node("span", `status-symbol ${status}`, symbols[status]), node("span", "", labels[status]), node("span", "group-count", group.length));
      const cards = node("div", "board-column-cards");
      for (const task of group) cards.append(taskEntry(task, "board"));
      column.append(heading, cards);
      list.append(column);
      cards.scrollTop = columnScroll[status] || 0;
    }
    list.scrollLeft = horizontalScroll;
    return;
  }
  for (const status of order) {
    const group = tasks.filter(task => task.status === status);
    if (!group.length) continue;
    const heading = node("div", "group-heading");
    heading.append(node("span", "group-chevron", "⌄"), node("span", `status-symbol ${status}`, symbols[status]), node("span", "", labels[status]), node("span", "group-count", group.length));
    list.append(heading);
    for (const task of group) list.append(taskEntry(task, "list"));
  }
}

function setLayout(layout) {
  if (state.layout === layout) return;
  state.layout = layout;
  localStorage.setItem("task-dashboard-layout", layout);
  closeDetail();
  renderLayoutControls();
  renderTasks();
}

function renderLayoutControls() {
  for (const layout of ["list", "board"]) {
    document.getElementById(`${layout}-layout`).setAttribute("aria-pressed", String(state.layout === layout));
  }
}

function renderDetail() {
  const panel = document.getElementById("detail-panel");
  const task = state.data.tasks.find(item => item.id === state.selectedId);
  if (!task) {
    panel.hidden = true;
    state.selectedId = null;
    return;
  }
  panel.hidden = false;
  document.getElementById("detail-id").textContent = issueId(task);
  document.getElementById("detail-title").textContent = task.title;
  document.getElementById("detail-status").textContent = `${symbols[task.status]}  ${labels[task.status]}`;
  document.getElementById("detail-priority").textContent = task.priority || "None";
  document.getElementById("detail-tag").textContent = task.tag.length ? task.tag.join(", ") : "None";
  document.getElementById("detail-section").textContent = task.section;
  document.getElementById("detail-source").textContent = `${task.file}:${task.line}`;
}

function openDetail(task, row) {
  state.selectedId = task.id;
  document.querySelectorAll(".task-entry.selected").forEach(item => item.classList.remove("selected"));
  row.classList.add("selected");
  renderDetail();
}

function closeDetail() {
  state.selectedId = null;
  document.getElementById("detail-panel").hidden = true;
  document.querySelectorAll(".task-entry.selected").forEach(row => row.classList.remove("selected"));
}

function fileIsComplete(path) {
  const tasks = state.data.tasks.filter(task => task.file === path);
  return tasks.length > 0 && tasks.every(task => task.status === "done");
}

async function archiveCurrentFile() {
  const file = state.file;
  if (!file || !fileIsComplete(file)) return;
  if (!window.confirm(`Move ${file} to tasks/archive/? It leaves the current list.`)) return;
  try {
    const response = await fetch("/api/archive", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    state.file = null;
    state.selectedId = null;
    state.data = data;
    render();
    document.getElementById("sync").textContent = "Archived";
  } catch (error) {
    const sync = document.getElementById("sync");
    sync.classList.add("error");
    sync.textContent = `Archive failed: ${error.message}`;
  }
}

function render() {
  if (!state.data) return;
  if (state.file && !state.data.files.some(file => file.path === state.file)) state.file = null;
  if (state.priority !== "all" && state.priority !== "none" && !state.data.schema.priority.includes(state.priority)) state.priority = "all";
  if (state.tag !== "all" && state.tag !== "none" && !state.data.schema.tag.includes(state.tag)) state.tag = "all";
  document.getElementById("archive-file").hidden = !(state.file && fileIsComplete(state.file));
  const viewName = state.file ? state.data.files.find(file => file.path === state.file).name : "All tasks";
  document.getElementById("breadcrumb-view").textContent = viewName;
  document.getElementById("page-title").textContent = viewName;
  renderNavigation();
  renderFilters();
  renderLayoutControls();
  renderTasks();
  renderDetail();
}

async function refresh() {
  try {
    const response = await fetch("/api/tasks", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (state.data?.version !== data.version) {
      state.data = data;
      render();
    }
    const sync = document.getElementById("sync");
    sync.classList.remove("error");
    sync.textContent = "Up to date";
    document.querySelector(".live-dot").className = "live-dot online";
  } catch (error) {
    const sync = document.getElementById("sync");
    sync.classList.add("error");
    sync.textContent = `Update failed: ${error.message}`;
    document.querySelector(".live-dot").className = "live-dot error";
  }
}

document.getElementById("all-files").addEventListener("click", () => setView(null));
document.getElementById("archive-file").addEventListener("click", archiveCurrentFile);
document.getElementById("list-layout").addEventListener("click", () => setLayout("list"));
document.getElementById("board-layout").addEventListener("click", () => setLayout("board"));
document.getElementById("close-detail").addEventListener("click", closeDetail);
document.addEventListener("keydown", event => {
  if (event.key === "Escape") closeDetail();
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "b") {
    event.preventDefault();
    setLayout(state.layout === "list" ? "board" : "list");
  }
});
document.getElementById("search").addEventListener("input", event => {
  state.search = event.target.value.trim();
  closeDetail();
  renderTasks();
});
refresh();
setInterval(refresh, 1000);
