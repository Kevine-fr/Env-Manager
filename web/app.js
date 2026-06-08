/* =========================================================================
   ENV Manager — logique front (vanilla JS)
   ========================================================================= */
"use strict";

const TOKEN_KEY = "envmgr_token";

const state = {
  token: localStorage.getItem(TOKEN_KEY) || null,
  snapshot: null,
  selectedProject: null,
  search: "",
  edit: null,    // { project, file, key, value, isNew }
  remove: null,  // { project, file, key }
};

/* ---------------------------- Icônes SVG -------------------------------- */
const ICON = {
  eye: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>',
  eyeOff: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9.9 4.2A10.9 10.9 0 0 1 12 4c6.5 0 10 7 10 7a17.8 17.8 0 0 1-3.2 4M6.6 6.6A17.6 17.6 0 0 0 2 11s3.5 7 10 7a10.8 10.8 0 0 0 4.4-.9"/><path d="m2 2 20 20"/></svg>',
  copy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>',
  edit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>',
  trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>',
  plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/></svg>',
  file: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>',
  warn: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/></svg>',
};

/* ---------------------------- Helpers DOM ------------------------------- */
const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, html) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (html !== undefined) node.innerHTML = html;
  return node;
};
const escapeHtml = (s) =>
  String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );

/* ---------------------------- API client -------------------------------- */
async function api(path, { method = "GET", body } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (state.token) headers["Authorization"] = `Bearer ${state.token}`;

  const res = await fetch(path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (res.status === 401) {
    logout();
    throw new Error("Session expirée.");
  }
  let data = null;
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) {
    throw new Error((data && data.detail) || `Erreur ${res.status}`);
  }
  return data;
}

/* ---------------------------- Toasts ------------------------------------ */
function toast(message, type = "info") {
  const node = el("div", `toast ${type === "error" ? "error" : ""}`,
    `${type === "error" ? ICON.warn : ICON.check}<span>${escapeHtml(message)}</span>`);
  $("#toast-stack").appendChild(node);
  setTimeout(() => {
    node.style.transition = "opacity .25s, transform .25s";
    node.style.opacity = "0";
    node.style.transform = "translateX(16px)";
    setTimeout(() => node.remove(), 260);
  }, 2600);
}

/* ---------------------------- Auth -------------------------------------- */
async function login(ev) {
  ev.preventDefault();
  const btn = $("#login-btn");
  const errBox = $("#login-error");
  errBox.hidden = true;
  btn.disabled = true;
  btn.querySelector(".btn-label").textContent = "Connexion…";
  try {
    const data = await api("/api/login", {
      method: "POST",
      body: {
        username: $("#login-username").value.trim() || "admin",
        password: $("#login-password").value,
      },
    });
    state.token = data.access_token;
    localStorage.setItem(TOKEN_KEY, state.token);
    $("#login-password").value = "";
    await enterApp();
  } catch (e) {
    errBox.textContent = e.message || "Échec de la connexion.";
    errBox.hidden = false;
  } finally {
    btn.disabled = false;
    btn.querySelector(".btn-label").textContent = "Déverrouiller";
  }
}

function logout() {
  state.token = null;
  state.snapshot = null;
  state.selectedProject = null;
  localStorage.removeItem(TOKEN_KEY);
  $("#app-view").hidden = true;
  $("#login-view").hidden = false;
}

async function enterApp() {
  $("#login-view").hidden = true;
  $("#app-view").hidden = false;
  await loadProjects();
}

/* ---------------------------- Chargement -------------------------------- */
async function loadProjects(keepSelection = true) {
  const previous = keepSelection ? state.selectedProject : null;
  state.snapshot = await api("/api/projects");
  updateScanMeta();
  renderSidebar();

  const names = state.snapshot.projects.map((p) => p.name);
  if (previous && names.includes(previous)) {
    state.selectedProject = previous;
  } else if (!state.selectedProject && names.length) {
    state.selectedProject = null; // on laisse l'utilisateur choisir
  }
  renderContent();
}

function updateScanMeta() {
  const s = state.snapshot;
  const d = new Date(s.generated_at);
  const stamp = d.toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
  $("#scan-meta").textContent =
    `${s.project_count} projets · ${s.total_variables} variables · scan ${stamp}`;
}

/* ---------------------------- Recherche --------------------------------- */
function matchesSearch(project) {
  const q = state.search;
  if (!q) return true;
  if (project.name.toLowerCase().includes(q)) return true;
  return project.env_files.some((f) =>
    f.variables.some((v) => v.key.toLowerCase().includes(q))
  );
}

/* ---------------------------- Sidebar ----------------------------------- */
function renderSidebar() {
  const list = $("#project-list");
  list.innerHTML = "";
  const projects = state.snapshot.projects.filter(matchesSearch);
  $("#project-count").textContent = projects.length;

  projects.forEach((p) => {
    const item = el("button", "project-item" + (p.name === state.selectedProject ? " active" : ""));
    item.innerHTML = `
      <span class="project-dot ${p.variable_count ? "" : "empty"}"></span>
      <span class="project-meta">
        <span class="project-name">${escapeHtml(p.name)}</span>
        <span class="project-sub">${p.file_count} fichier${p.file_count > 1 ? "s" : ""} .env</span>
      </span>
      <span class="project-count-badge">${p.variable_count}</span>`;
    item.addEventListener("click", () => {
      state.selectedProject = p.name;
      renderSidebar();
      renderContent();
    });
    list.appendChild(item);
  });

  if (!projects.length) {
    list.appendChild(el("div", "no-vars", "Aucun projet ne correspond."));
  }
}

/* ---------------------------- Contenu ----------------------------------- */
function renderContent() {
  const content = $("#content");
  const project = state.snapshot.projects.find((p) => p.name === state.selectedProject);

  if (!project) {
    content.innerHTML = `
      <div class="empty-state">
        <div class="empty-glyph">${ICON.file}</div>
        <p>Sélectionnez un projet pour afficher ses variables.</p>
      </div>`;
    return;
  }

  content.innerHTML = "";

  const header = el("div", "project-header");
  header.innerHTML = `
    <h2>${escapeHtml(project.name)}</h2>
    <div class="crumbs">${escapeHtml(state.snapshot.deploy_root)}/${escapeHtml(project.name)}
      · ${project.variable_count} variable${project.variable_count > 1 ? "s" : ""}</div>`;
  content.appendChild(header);

  if (!project.env_files.length) {
    content.appendChild(el("div", "no-files", "Aucun fichier .env trouvé dans ce projet."));
    return;
  }

  const q = state.search;
  project.env_files.forEach((file) => {
    const vars = q ? file.variables.filter((v) => v.key.toLowerCase().includes(q)) : file.variables;
    if (q && vars.length === 0) return; // masque les fichiers sans correspondance

    const block = el("div", "envfile");

    const head = el("div", "envfile-head");
    head.innerHTML = `
      <div class="envfile-path">${ICON.file}<code>${escapeHtml(file.path)}</code></div>
      <span class="envfile-count">${file.variable_count} var.</span>`;
    block.appendChild(head);

    if (file.error) {
      block.appendChild(el("div", "file-error", `Fichier illisible : ${escapeHtml(file.error)}`));
      content.appendChild(block);
      return;
    }

    const table = el("div", "table");
    if (vars.length === 0) {
      table.appendChild(el("div", "no-vars", "Aucune variable."));
    } else {
      vars.forEach((v) => table.appendChild(renderRow(project.name, file.path, v)));
    }

    // Ligne "ajouter une variable"
    const addRow = el("div", "add-row");
    const addBtn = el("button", "btn btn-ghost", `${ICON.plus}<span>Ajouter une variable</span>`);
    addBtn.addEventListener("click", () => openEdit(project.name, file.path, null));
    addRow.appendChild(addBtn);
    table.appendChild(addRow);

    block.appendChild(table);
    content.appendChild(block);
  });
}

function renderRow(projectName, filePath, variable) {
  const row = el("div", "row");
  const isEmpty = variable.value === "";

  const k = el("div", "k", escapeHtml(variable.key));

  const vWrap = el("div", "v-wrap");
  const v = el("div", "v" + (isEmpty ? " empty-val" : ""));
  v.dataset.value = variable.value;
  v.textContent = isEmpty ? "(vide)" : "•".repeat(12);

  const revealBtn = el("button", "icon-btn", ICON.eye);
  revealBtn.title = "Afficher / masquer";
  let revealed = false;
  revealBtn.addEventListener("click", () => {
    revealed = !revealed;
    if (revealed) {
      v.classList.add("revealed");
      v.textContent = isEmpty ? "(vide)" : variable.value;
      revealBtn.innerHTML = ICON.eyeOff;
    } else {
      v.classList.remove("revealed");
      v.textContent = isEmpty ? "(vide)" : "•".repeat(12);
      revealBtn.innerHTML = ICON.eye;
    }
  });

  const copyBtn = el("button", "icon-btn", ICON.copy);
  copyBtn.title = "Copier la valeur";
  copyBtn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(variable.value);
      toast(`Valeur de ${variable.key} copiée.`);
    } catch (_) {
      toast("Copie impossible (clipboard).", "error");
    }
  });

  vWrap.append(v, revealBtn, copyBtn);

  const actions = el("div", "row-actions");
  const editBtn = el("button", "icon-btn", ICON.edit);
  editBtn.title = "Modifier";
  editBtn.addEventListener("click", () => openEdit(projectName, filePath, variable));
  const delBtn = el("button", "icon-btn danger", ICON.trash);
  delBtn.title = "Supprimer";
  delBtn.addEventListener("click", () => openDelete(projectName, filePath, variable.key));
  actions.append(editBtn, delBtn);

  row.append(k, vWrap, actions);
  return row;
}

/* ---------------------------- Modale édition ---------------------------- */
function openEdit(project, file, variable) {
  const isNew = !variable;
  state.edit = {
    project,
    file,
    key: isNew ? "" : variable.key,
    value: isNew ? "" : variable.value,
    isNew,
  };
  $("#edit-title").textContent = isNew ? "Ajouter une variable" : "Modifier la variable";
  $("#edit-subtitle").textContent = `${project} · ${file}`;
  const keyInput = $("#edit-key");
  keyInput.value = state.edit.key;
  keyInput.readOnly = !isNew; // on ne renomme pas une clé existante
  $("#edit-value").value = state.edit.value;
  $("#edit-modal").hidden = false;
  (isNew ? keyInput : $("#edit-value")).focus();
}

async function saveEdit() {
  const key = $("#edit-key").value.trim();
  const value = $("#edit-value").value;
  if (!key) { toast("La clé est obligatoire.", "error"); return; }

  const btn = $("#edit-save");
  btn.disabled = true;
  btn.textContent = "Enregistrement…";
  try {
    await api("/api/secrets/update", {
      method: "POST",
      body: { project: state.edit.project, file: state.edit.file, key, value },
    });
    closeModals();
    await loadProjects();
    toast(state.edit?.isNew ? `Variable ${key} ajoutée.` : `Variable ${key} mise à jour.`);
  } catch (e) {
    toast(e.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Enregistrer";
  }
}

/* ---------------------------- Modale suppression ------------------------ */
function openDelete(project, file, key) {
  state.remove = { project, file, key };
  $("#delete-key").textContent = key;
  $("#delete-file").textContent = file;
  $("#delete-modal").hidden = false;
}

async function confirmDelete() {
  const btn = $("#delete-confirm");
  btn.disabled = true;
  btn.textContent = "Suppression…";
  try {
    await api("/api/secrets/delete", { method: "POST", body: { ...state.remove } });
    const key = state.remove.key;
    closeModals();
    await loadProjects();
    toast(`Variable ${key} supprimée.`);
  } catch (e) {
    toast(e.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Supprimer définitivement";
  }
}

function closeModals() {
  $("#edit-modal").hidden = true;
  $("#delete-modal").hidden = true;
  state.edit = null;
  state.remove = null;
}

/* ---------------------------- Rescan ------------------------------------ */
async function rescan() {
  const btn = $("#rescan-btn");
  btn.disabled = true;
  try {
    state.snapshot = await api("/api/scan", { method: "POST" });
    updateScanMeta();
    renderSidebar();
    renderContent();
    toast("Scan terminé.");
  } catch (e) {
    toast(e.message, "error");
  } finally {
    btn.disabled = false;
  }
}

/* ---------------------------- Branchements ------------------------------ */
function bind() {
  $("#login-form").addEventListener("submit", login);
  $("#logout-btn").addEventListener("click", logout);
  $("#rescan-btn").addEventListener("click", rescan);
  $("#edit-save").addEventListener("click", saveEdit);
  $("#delete-confirm").addEventListener("click", confirmDelete);

  $("#search-input").addEventListener("input", (e) => {
    state.search = e.target.value.trim().toLowerCase();
    renderSidebar();
    renderContent();
  });

  document.querySelectorAll("[data-close]").forEach((node) =>
    node.addEventListener("click", closeModals)
  );
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeModals();
  });
}

async function boot() {
  bind();
  if (state.token) {
    try {
      await enterApp();
      return;
    } catch (_) {
      logout();
    }
  }
  $("#login-view").hidden = false;
}

boot();
