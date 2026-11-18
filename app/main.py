"""Application FastAPI : API REST + planificateur (toutes les 30 min) + front.

Endpoints :
  POST /api/login                 -> {access_token}
  GET  /api/health                -> état du service (public)
  GET  /api/projects              -> snapshot complet (admin)        [protégé]
  POST /api/scan                  -> relance un scan immédiat (admin) [protégé]
  POST /api/secrets/update        -> crée/modifie une variable (admin)[protégé]
  POST /api/secrets/delete        -> supprime une variable (admin)    [protégé]
Le front (web/) est servi sur /.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import create_token, require_admin, verify_credentials
from .config import settings
from .env_io import (
    EnvIOError,
    delete_variable,
    read_variables,
    resolve_env_path,
    update_variable,
)
from . import infra
from .infra import InfraError
from .scanner import build_snapshot, load_snapshot, run_scan, write_snapshot

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("env-manager")

scheduler = BackgroundScheduler(timezone="UTC")

# Le scan planifié (thread APScheduler) et une édition depuis l'UI écrivent
# tous deux envs.json : sans verrou, l'édition relit l'ancien instantané
# pendant que le scan écrit le nouveau, et le dernier qui écrit efface
# l'autre. Un seul écrivain à la fois.
_snapshot_lock = threading.Lock()


class LimiteurConnexion:
    """Limite les échecs de connexion par adresse IP (fenêtre glissante).

    Un seul mot de passe protège tous les secrets du VPS : sans limite,
    /api/login se laisse essayer à la vitesse du réseau. Après
    `max_echecs` échecs en `fenetre_s` secondes, l'adresse reçoit 429
    jusqu'à ce que les plus anciens échecs sortent de la fenêtre.
    """

    def __init__(self, max_echecs: int = 10, fenetre_s: int = 900) -> None:
        self.max_echecs = max_echecs
        self.fenetre_s = fenetre_s
        self._echecs: dict[str, deque[float]] = defaultdict(deque)
        self._verrou = threading.Lock()

    def _purger(self, ip: str, maintenant: float) -> deque[float]:
        file = self._echecs[ip]
        while file and maintenant - file[0] > self.fenetre_s:
            file.popleft()
        return file

    def bloque(self, ip: str, maintenant: float | None = None) -> bool:
        maintenant = time.monotonic() if maintenant is None else maintenant
        with self._verrou:
            return len(self._purger(ip, maintenant)) >= self.max_echecs

    def echec(self, ip: str, maintenant: float | None = None) -> None:
        maintenant = time.monotonic() if maintenant is None else maintenant
        with self._verrou:
            self._purger(ip, maintenant).append(maintenant)

    def reussite(self, ip: str) -> None:
        with self._verrou:
            self._echecs.pop(ip, None)


limiteur_connexion = LimiteurConnexion()


def _ip_client(request: Request) -> str:
    # Derrière le nginx du VPS, l'adresse du client est dans X-Real-IP /
    # X-Forwarded-For ; sans eux, tous les clients auraient l'IP de nginx et
    # un seul attaquant bloquerait tout le monde.
    reel = request.headers.get("x-real-ip")
    if reel:
        return reel.strip()
    transmis = request.headers.get("x-forwarded-for")
    if transmis:
        return transmis.split(",")[0].strip()
    return request.client.host if request.client else "inconnu"


def _scheduled_scan() -> None:
    try:
        with _snapshot_lock:
            snap = run_scan()
        logger.info(
            "Scan planifié OK : %d projets, %d variables.",
            snap["project_count"],
            snap["total_variables"],
        )
    except Exception:
        logger.exception("Le scan planifié a échoué.")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.validate()
    logger.info("Dossier deploy surveillé : %s", settings.deploy_root)
    if settings.scan_on_startup:
        _scheduled_scan()
    scheduler.add_job(
        _scheduled_scan,
        trigger=IntervalTrigger(minutes=settings.scan_interval_minutes),
        id="scan-envs",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info("Scheduler démarré (toutes les %d min).", settings.scan_interval_minutes)
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(title="ENV Manager", version=settings.app_version, lifespan=lifespan)


# ------------------------- Métriques Prometheus ------------------------------
# Expose `GET /metrics` (requêtes, latences par route, CPU/RSS du process) pour
# le Prometheus du VPS, qui scrute `env-manager:8000` via le réseau Docker.
# L'import est volontairement tolérant : si la dépendance venait à manquer dans
# une image, l'application doit démarrer quand même — la supervision n'est pas
# une raison de mettre le gestionnaire d'environnements à terre.
try:
    from prometheus_fastapi_instrumentator import Instrumentator

    Instrumentator(
        # Codes HTTP exacts plutôt que « 2xx » : sinon impossible de distinguer
        # un 401 d'un 404 dans les dashboards.
        should_group_status_codes=False,
        excluded_handlers=["/metrics"],
    ).instrument(app).expose(app, include_in_schema=False)
except ImportError:  # pragma: no cover
    logger.warning(
        "prometheus-fastapi-instrumentator absent : endpoint /metrics désactivé"
    )


# ----------------------------- Schémas (entrées) -----------------------------
class LoginIn(BaseModel):
    username: str = Field(default="admin")
    password: str


class UpdateIn(BaseModel):
    project: str
    file: str
    key: str
    value: str = ""


class DeleteIn(BaseModel):
    project: str
    file: str
    key: str


class ServiceActionIn(BaseModel):
    name: str
    action: str  # start | stop | restart


class NginxCreateIn(BaseModel):
    subdomain: str
    container: str
    port: int


class NginxDeleteIn(BaseModel):
    file: str


class SSLIn(BaseModel):
    subdomain: str
    email: str


# ------------------------ Gestion des erreurs métier -------------------------
@app.exception_handler(EnvIOError)
async def _env_io_handler(_, exc: EnvIOError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.exception_handler(InfraError)
async def _infra_handler(_, exc: InfraError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


# --------------------------------- Routes ------------------------------------
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "deploy_root": str(settings.deploy_root),
        "scan_interval_minutes": settings.scan_interval_minutes,
    }


@app.get("/api/version")
def version():
    """Version déployée (public) : affichée dans l'UI pour vérifier ce qui tourne."""
    return {"version": settings.app_version, "commit": settings.app_commit}


@app.post("/api/login")
def login(body: LoginIn, request: Request):
    ip = _ip_client(request)
    if limiteur_connexion.bloque(ip):
        logger.warning("Connexion refusée (trop d'échecs) depuis %s", ip)
        raise HTTPException(
            status_code=429,
            detail="Trop de tentatives. Réessayez dans quelques minutes.",
        )
    if not verify_credentials(body.username, body.password):
        limiteur_connexion.echec(ip)
        raise HTTPException(status_code=401, detail="Identifiants incorrects.")
    limiteur_connexion.reussite(ip)
    return create_token()


@app.get("/api/projects")
def get_projects(_: dict = Depends(require_admin)):
    # load_snapshot() lance un scan si le JSON manque : même verrou.
    with _snapshot_lock:
        return load_snapshot()


@app.post("/api/scan")
def trigger_scan(_: dict = Depends(require_admin)):
    with _snapshot_lock:
        return run_scan()


def _refresh_file_in_snapshot(project: str, relative_file: str) -> dict:
    """Recharge le fichier modifié et met à jour le JSON sans tout rescanner."""
    env_path = resolve_env_path(project, relative_file)
    variables = read_variables(env_path)

    with _snapshot_lock:
        return _maj_snapshot(project, relative_file, variables)


def _maj_snapshot(project: str, relative_file: str, variables: list[dict]) -> dict:
    snapshot = load_snapshot()
    for proj in snapshot.get("projects", []):
        if proj["name"] != project:
            continue
        for env_file in proj["env_files"]:
            if env_file["path"] == relative_file:
                env_file["variables"] = variables
                env_file["variable_count"] = len(variables)
        proj["variable_count"] = sum(
            f["variable_count"] for f in proj["env_files"]
        )
    snapshot["total_variables"] = sum(
        p["variable_count"] for p in snapshot.get("projects", [])
    )
    write_snapshot(snapshot)
    return {"variables": variables}


@app.post("/api/secrets/update")
def secrets_update(body: UpdateIn, _: dict = Depends(require_admin)):
    result = update_variable(body.project, body.file, body.key, body.value)
    refreshed = _refresh_file_in_snapshot(body.project, body.file)
    logger.info("Variable mise à jour : %s/%s :: %s", body.project, body.file, body.key)
    return {"ok": True, **result, **refreshed}


@app.post("/api/secrets/delete")
def secrets_delete(body: DeleteIn, _: dict = Depends(require_admin)):
    delete_variable(body.project, body.file, body.key)
    refreshed = _refresh_file_in_snapshot(body.project, body.file)
    logger.info("Variable supprimée : %s/%s :: %s", body.project, body.file, body.key)
    return {"ok": True, "key": body.key, **refreshed}


# ============================= Infrastructure ================================
def require_infra(_: dict = Depends(require_admin)) -> None:
    """Admin + module infra activé."""
    if not settings.infra_enabled:
        raise HTTPException(status_code=404, detail="Module Infrastructure désactivé.")


def _sync_repo(message: str, rel_paths: list[str] | None) -> dict:
    """Commite + pousse, sans faire échouer l'action infra si git échoue."""
    try:
        return infra.git_commit_and_push(message, rel_paths)
    except InfraError as exc:
        logger.warning("Sync git échouée : %s", exc.message)
        return {"ok": False, "error": exc.message}


@app.get("/api/infra/status")
def infra_status(_: None = Depends(require_infra)):
    return infra.infra_status()


@app.get("/api/infra/services")
def infra_services(_: None = Depends(require_infra)):
    return {"services": infra.list_services()}


@app.post("/api/infra/services/action")
def infra_service_action(body: ServiceActionIn, _: None = Depends(require_infra)):
    return infra.service_action(body.name, body.action)


@app.get("/api/infra/nginx")
def infra_nginx_list(_: None = Depends(require_infra)):
    return {"confs": infra.list_confs()}


@app.post("/api/infra/nginx")
def infra_nginx_create(body: NginxCreateIn, _: None = Depends(require_infra)):
    result = infra.create_conf(body.subdomain, body.container, body.port)
    rel = f"{settings.nginx_conf_subdir}/{result['file']}"
    git = _sync_repo(f"nginx: ajoute le proxy {result['fqdn']} -> {result['upstream']}", [rel])
    return {**result, "git": git}


@app.post("/api/infra/nginx/delete")
def infra_nginx_delete(body: NginxDeleteIn, _: None = Depends(require_infra)):
    result = infra.delete_conf(body.file)
    rel = f"{settings.nginx_conf_subdir}/{result['file']}"
    git = _sync_repo(f"nginx: supprime {result['file']}", [rel])
    return {**result, "git": git}


@app.get("/api/infra/ssl")
def infra_ssl_list(_: None = Depends(require_infra)):
    return {"certificates": infra.list_certificates()}


@app.post("/api/infra/ssl")
def infra_ssl_obtain(body: SSLIn, _: None = Depends(require_infra)):
    result = infra.obtain_certificate(body.subdomain, body.email)
    sub = infra.validate_subdomain(body.subdomain)
    rel = f"{settings.nginx_conf_subdir}/{sub}.conf"
    git = _sync_repo(f"nginx: active le SSL pour {result['fqdn']}", [rel])
    return {**result, "git": git}


@app.get("/api/infra/git")
def infra_git_status(_: None = Depends(require_infra)):
    return infra.git_status()


@app.post("/api/infra/git/push")
def infra_git_push(_: None = Depends(require_infra)):
    return infra.git_commit_and_push(
        "infra: synchronisation manuelle depuis ENV Manager", paths=None, push=True
    )


# ------------------------ Front statique (servi sur /) -----------------------
# Doit être monté APRÈS les routes /api/*.
app.mount("/", StaticFiles(directory=str(settings.web_dir), html=True), name="web")
