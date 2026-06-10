/* =========================================================================
   ENV Manager — Module Infrastructure (vanilla JS)
   Réutilise les helpers globaux définis dans app.js :
     $, el, api, toast, escapeHtml
   ========================================================================= */
"use strict";

/* ---------------------------- Icônes ------------------------------------ */
const IIC = {
  refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v5h-5"/></svg>',
  push: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5"/><path d="m5 12 7-7 7 7"/></svg>',
  play: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="6 4 20 12 6 20 6 4"/></svg>',
  stop: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>',
  restart: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 9-9 9 9 0 0 0-6.36 2.64L3 8"/><path d="M3 3v5h5"/></svg>',
  server: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="8" rx="2"/><rect x="3" y="13" width="18" height="8" rx="2"/><path d="M7 7h.01M7 17h.01"/></svg>',
  globe: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a15 15 0 0 1 0 18M12 3a15 15 0 0 0 0 18"/></svg>',
  lock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>',
  git: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="9" r="3"/><path d="M18 12a9 9 0 0 1-9 9M6 9v6"/></svg>',
  trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>',
  plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/></svg>',
  spin: '<svg class="spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-6.22-8.56"/></svg>',
};

const infraState = { loaded: false, domain: "" };

/* ---------------------------- Bascule de vue ---------------------------- */
function switchView(view) {
  const app = $("#app-view");
  if (!app) return;
  const isInfra = view === "infra";
  app.classList.toggle("view-infra", isInfra);
  document.querySelectorAll("#view-switch button").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === view)
  );
  if (isInfra && !infraState.loaded) {
    infraState.loaded = true;
    loadInfra();
  }
}

// Réinitialise sur Secrets à chaque connexion (hook appelé par app.js).
window.__onEnterApp = () => {
  infraState.loaded = false;
  switchView("secrets");
};

/* ---------------------------- Utilitaires ------------------------------- */
function setBusy(btn, on, label) {
  if (!btn) return;
  if (on) {
    if (btn.dataset.html === undefined) btn.dataset.html = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `${IIC.spin}<span>${escapeHtml(label || "…")}</span>`;
  } else {
    btn.disabled = false;
    if (btn.dataset.html !== undefined) {
      btn.innerHTML = btn.dataset.html;
      delete btn.dataset.html;
    }
  }
}

function gitToast(prefix, git) {
  if (!git) return toast(prefix);
  if (git.ok === false) {
    toast(`${prefix} (git non synchronisé : ${git.error})`, "error");
  } else if (git.pushed) {
    toast(`${prefix} · poussé sur GitHub${git.commit ? " (" + git.commit + ")" : ""}.`);
  } else if (git.committed) {
    toast(`${prefix} · commit ${git.commit || ""} (push désactivé).`);
  } else {
    toast(prefix);
  }
}

function confirmAction(title, message, onConfirm) {
  $("#confirm-title").textContent = title;
  $("#confirm-message").textContent = message;
  const modal = $("#confirm-modal");
  modal.hidden = false;
  const ok = $("#confirm-ok");
  const fresh = ok.cloneNode(true); // purge les anciens listeners
  ok.parentNode.replaceChild(fresh, ok);
  fresh.addEventListener("click", async () => {
    fresh.disabled = true;
    try {
      await onConfirm();
      modal.hidden = true;
    } finally {
      fresh.disabled = false;
    }
  });
}

/* ---------------------------- Squelette --------------------------------- */
function loadInfra() {
  const wrap = $("#infra-wrap");
  wrap.innerHTML = `
    <div class="card">
      <div class="card-head">
        <div class="ch-title"><span class="ch-ic">${IIC.git}</span><h3>Dépôt Infrastructure</h3></div>
        <div class="ch-actions">
          <button class="btn btn-ghost" id="infra-refresh">${IIC.refresh}<span>Rafraîchir</span></button>
          <button class="btn btn-primary" id="git-push">${IIC.push}<span>Pousser vers GitHub</span></button>
        </div>
      </div>
      <div class="card-body" id="repo-body"><div class="note">Chargement…</div></div>
    </div>

    <div class="card">
      <div class="card-head"><div class="ch-title"><span class="ch-ic">${IIC.server}</span><h3>Services</h3></div></div>
      <div class="card-body" id="svc-body"><div class="note">Chargement…</div></div>
    </div>

    <div class="card">
      <div class="card-head"><div class="ch-title"><span class="ch-ic">${IIC.globe}</span><h3>Reverse-proxy nginx</h3></div></div>
      <div class="card-body">
        <div class="form-row">
          <label class="field"><span>Sous-domaine</span>
            <div class="suffix-input">
              <input id="nx-sub" class="mono" placeholder="ex: sonarqube" autocomplete="off" spellcheck="false" />
              <span class="suffix infra-suffix">.${escapeHtml(infraState.domain || "domaine")}</span>
            </div>
          </label>
          <label class="field"><span>Conteneur</span>
            <input id="nx-cont" class="mono" placeholder="ex: sonarqube" autocomplete="off" spellcheck="false" />
          </label>
          <label class="field"><span>Port</span>
            <input id="nx-port" class="mono" type="number" min="1" max="65535" placeholder="9000" />
          </label>
        </div>
        <div class="form-actions">
          <button class="btn btn-primary" id="nx-create">${IIC.plus}<span>Créer le proxy</span></button>
        </div>
        <div class="section-label">Fichiers .conf existants</div>
        <div class="conf-list" id="conf-list"><div class="note">Chargement…</div></div>
      </div>
    </div>

    <div class="card">
      <div class="card-head"><div class="ch-title"><span class="ch-ic">${IIC.lock}</span><h3>Certificats SSL</h3></div></div>
      <div class="card-body">
        <div class="note">Le reverse-proxy doit déjà exister (créez-le ci-dessus). L'obtention via certbot peut prendre 20 à 40 s.</div>
        <div class="form-row">
          <label class="field"><span>Sous-domaine</span>
            <div class="suffix-input">
              <input id="ssl-sub" class="mono" placeholder="ex: sonarqube" autocomplete="off" spellcheck="false" />
              <span class="suffix infra-suffix">.${escapeHtml(infraState.domain || "domaine")}</span>
            </div>
          </label>
          <label class="field"><span>Email (Let's Encrypt)</span>
            <input id="ssl-mail" type="email" placeholder="vous@exemple.fr" autocomplete="off" />
          </label>
        </div>
        <div class="form-actions">
          <button class="btn btn-primary" id="ssl-go">${IIC.lock}<span>Obtenir / renouveler</span></button>
        </div>
        <div class="section-label">Certificats émis</div>
        <div class="cert-list" id="cert-list"><div class="note">Chargement…</div></div>
      </div>
    </div>`;

  $("#infra-refresh").addEventListener("click", refreshAll);
  $("#git-push").addEventListener("click", doPush);
  $("#nx-create").addEventListener("click", createProxy);
  $("#ssl-go").addEventListener("click", obtainSsl);

  refreshAll();
}

function refreshAll() {
  refreshStatus();
  refreshServices();
  refreshConfs();
  refreshCerts();
}

function setSuffix(domain) {
  infraState.domain = domain;
  document.querySelectorAll(".infra-suffix").forEach((s) => (s.textContent = "." + domain));
}

/* ---------------------------- Dépôt / statut ---------------------------- */
async function refreshStatus() {
  const body = $("#repo-body");
  try {
    const s = await api("/api/infra/status");
    if (s.app_domain) setSuffix(s.app_domain);

    let gitLine = "—";
    let dirtyBadge = "";
    if (s.git.available) {
      try {
        const g = await api("/api/infra/git");
        gitLine = `${escapeHtml(g.branch)} · ${escapeHtml(g.last_commit || "—")}`;
        dirtyBadge = g.dirty
          ? `<span class="badge warn"><span class="dot"></span>${g.change_count} modif. en attente</span>`
          : `<span class="badge ok"><span class="dot"></span>à jour</span>`;
      } catch (_) {}
    }

    const dockerPill = s.docker.available
      ? `<span class="badge ok"><span class="dot"></span>Docker OK</span>`
      : `<span class="badge err"><span class="dot"></span>Docker indisponible</span>`;
    const gitPill = s.git.available
      ? `<span class="badge ok"><span class="dot"></span>git OK</span>`
      : `<span class="badge err"><span class="dot"></span>git indisponible</span>`;

    body.innerHTML = `
      <div style="display:flex;gap:8px;flex-wrap:wrap;">${dockerPill}${gitPill}${dirtyBadge}</div>
      <dl class="kv">
        <dt>Domaine</dt><dd class="mono">${escapeHtml(s.app_domain)}</dd>
        <dt>Dépôt (conteneur)</dt><dd class="mono">${escapeHtml(s.repo_path)}</dd>
        <dt>Dépôt (hôte)</dt><dd class="mono">${escapeHtml(s.repo_host_path)}</dd>
        <dt>Git</dt><dd>${gitLine}</dd>
        <dt>Push</dt><dd>${escapeHtml(s.git.push_method)} · auto : ${s.git.auto_push ? "oui" : "non"}</dd>
      </dl>
      ${s.docker.available ? "" : `<div class="note err">${escapeHtml(s.docker.error || "")}</div>`}
      ${s.git.available ? "" : `<div class="note err">${escapeHtml(s.git.error || "")}</div>`}`;

    const pushBtn = $("#git-push");
    if (pushBtn) pushBtn.disabled = !s.git.available;
  } catch (e) {
    body.innerHTML = `<div class="note err">${escapeHtml(e.message)}</div>`;
  }
}

async function doPush() {
  const btn = $("#git-push");
  setBusy(btn, true, "Push…");
  try {
    const r = await api("/api/infra/git/push", { method: "POST" });
    if (r.pushed) toast(`Poussé sur GitHub${r.commit ? " (" + r.commit + ")" : ""}.`);
    else toast(r.message || "Rien à pousser.");
    await refreshStatus();
  } catch (e) {
    toast(e.message, "error");
  } finally {
    setBusy(btn, false);
  }
}

/* ---------------------------- Services ---------------------------------- */
async function refreshServices() {
  const body = $("#svc-body");
  try {
    const { services } = await api("/api/infra/services");
    if (!services.length) {
      body.innerHTML = `<div class="note">Aucun service configuré (INFRA_SERVICES).</div>`;
      return;
    }
    body.innerHTML = "";
    services.forEach((svc) => body.appendChild(renderService(svc)));
  } catch (e) {
    body.innerHTML = `<div class="note err">${escapeHtml(e.message)}</div>`;
  }
}

function statusBadge(svc) {
  if (!svc.exists) return `<span class="badge err"><span class="dot"></span>absent</span>`;
  if (svc.running) return `<span class="badge ok"><span class="dot"></span>actif</span>`;
  return `<span class="badge stop"><span class="dot"></span>${escapeHtml(svc.status)}</span>`;
}

function renderService(svc) {
  const row = el("div", "svc");
  const depsLine = (svc.deps || [])
    .map((d) => `${escapeHtml(d.label)} : ${d.running ? "actif" : escapeHtml(d.status)}`)
    .join(" · ");

  // Démarrer seulement si le service est arrêté ; Arrêter/Redémarrer seulement
  // s'il tourne. Si le conteneur n'existe pas, tout est désactivé.
  const up = svc.running;
  const absent = !svc.exists;
  const dis = { start: absent || up, restart: absent || !up, stop: absent || !up };
  const off = (k) => (dis[k] ? "disabled" : "");

  row.innerHTML = `
    <div class="svc-info">
      <div class="svc-name"><strong>${escapeHtml(svc.label)}</strong>${statusBadge(svc)}</div>
      <span class="svc-sub">${escapeHtml(svc.image || svc.name)}${depsLine ? " — " + depsLine : ""}</span>
    </div>
    <div class="svc-actions">
      <button class="btn btn-ghost" data-act="start" title="Démarrer" ${off("start")}>${IIC.play}<span>Démarrer</span></button>
      <button class="btn btn-ghost" data-act="restart" title="Redémarrer" ${off("restart")}>${IIC.restart}</button>
      <button class="btn btn-danger" data-act="stop" title="Arrêter" ${off("stop")}>${IIC.stop}<span>Arrêter</span></button>
    </div>`;

  row.querySelectorAll("button[data-act]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled) return;
      serviceAction(svc.name, btn.dataset.act, btn);
    });
  });
  return row;
}

async function serviceAction(name, action, btn) {
  const labels = { start: "Démarrage…", stop: "Arrêt…", restart: "Redémarrage…" };
  setBusy(btn, true, labels[action] || "…");
  try {
    const r = await api("/api/infra/services/action", { method: "POST", body: { name, action } });
    toast(r && r.message ? r.message : `${name} : ${action} OK.`);
    await refreshServices();
  } catch (e) {
    toast(e.message, "error");
    setBusy(btn, false);
  }
}

/* ---------------------------- nginx .conf ------------------------------- */
async function refreshConfs() {
  const list = $("#conf-list");
  try {
    const { confs } = await api("/api/infra/nginx");
    if (!confs.length) {
      list.innerHTML = `<div class="note">Aucun fichier .conf.</div>`;
      return;
    }
    list.innerHTML = "";
    confs.forEach((c) => list.appendChild(renderConf(c)));
  } catch (e) {
    list.innerHTML = `<div class="note err">${escapeHtml(e.message)}</div>`;
  }
}

function renderConf(c) {
  const item = el("div", "conf-item");
  const sslBadge = c.ssl
    ? `<span class="badge ok"><span class="dot"></span>HTTPS</span>`
    : `<span class="badge warn"><span class="dot"></span>HTTP</span>`;
  const mgr = c.managed ? `<span class="badge accent">ENV Manager</span>` : "";
  item.innerHTML = `
    <div class="conf-meta">
      <div class="conf-name"><code>${escapeHtml(c.file)}</code>${sslBadge}${mgr}</div>
      <span class="conf-up">${escapeHtml(c.server_name || "?")}${c.upstream ? " → " + escapeHtml(c.upstream) : ""}</span>
    </div>
    <div class="conf-actions">
      <button class="icon-btn danger" title="Supprimer">${IIC.trash}</button>
    </div>`;
  item.querySelector("button").addEventListener("click", () => {
    confirmAction(
      "Supprimer le .conf",
      `Supprimer ${c.file} puis recharger nginx et pousser le dépôt ? Cette action est définitive.`,
      async () => {
        try {
          const r = await api("/api/infra/nginx/delete", { method: "POST", body: { file: c.file } });
          gitToast(`${c.file} supprimé`, r.git);
          await refreshConfs();
          await refreshStatus();
        } catch (e) {
          toast(e.message, "error");
        }
      }
    );
  });
  return item;
}

async function createProxy() {
  const sub = $("#nx-sub").value.trim();
  const cont = $("#nx-cont").value.trim();
  const port = parseInt($("#nx-port").value, 10);
  if (!sub || !cont || !port) {
    toast("Renseignez sous-domaine, conteneur et port.", "error");
    return;
  }
  const btn = $("#nx-create");
  setBusy(btn, true, "Création…");
  try {
    const r = await api("/api/infra/nginx", { method: "POST", body: { subdomain: sub, container: cont, port } });
    gitToast(`Proxy ${r.fqdn} créé`, r.git);
    $("#nx-sub").value = "";
    $("#nx-cont").value = "";
    $("#nx-port").value = "";
    await refreshConfs();
    await refreshStatus();
  } catch (e) {
    toast(e.message, "error");
  } finally {
    setBusy(btn, false);
  }
}

/* ---------------------------- SSL --------------------------------------- */
async function refreshCerts() {
  const list = $("#cert-list");
  try {
    const { certificates } = await api("/api/infra/ssl");
    if (!certificates.length) {
      list.innerHTML = `<div class="note">Aucun certificat émis.</div>`;
      return;
    }
    list.innerHTML = "";
    certificates.forEach((c) => {
      const item = el("div", "cert-item");
      item.innerHTML = `
        <div class="conf-meta"><div class="conf-name"><code>${escapeHtml(c.domain)}</code></div></div>
        <span class="badge ok"><span class="dot"></span>actif</span>`;
      list.appendChild(item);
    });
  } catch (e) {
    list.innerHTML = `<div class="note err">${escapeHtml(e.message)}</div>`;
  }
}

async function obtainSsl() {
  const sub = $("#ssl-sub").value.trim();
  const mail = $("#ssl-mail").value.trim();
  if (!sub || !mail) {
    toast("Renseignez le sous-domaine et l'email.", "error");
    return;
  }
  const btn = $("#ssl-go");
  setBusy(btn, true, "certbot… (~30 s)");
  toast("Demande de certificat en cours, patientez…");
  try {
    const r = await api("/api/infra/ssl", { method: "POST", body: { subdomain: sub, email: mail } });
    gitToast(`Certificat ${r.fqdn} obtenu (HTTPS activé)`, r.git);
    $("#ssl-mail").value = "";
    await refreshCerts();
    await refreshConfs();
    await refreshStatus();
  } catch (e) {
    toast(e.message, "error");
  } finally {
    setBusy(btn, false);
  }
}

/* ---------------------------- Initialisation ---------------------------- */
document.querySelectorAll("#view-switch button").forEach((b) =>
  b.addEventListener("click", () => switchView(b.dataset.view))
);
