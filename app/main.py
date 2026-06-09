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
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import Depends, FastAPI, HTTPException
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


def _scheduled_scan() -> None:
    try:
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


app = FastAPI(title="ENV Manager", version="1.0.0", lifespan=lifespan)


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


@app.post("/api/login")
def login(body: LoginIn):
    if not verify_credentials(body.username, body.password):
        raise HTTPException(status_code=401, detail="Identifiants incorrects.")
    return create_token()


@app.get("/api/projects")
def get_projects(_: dict = Depends(require_admin)):
    return load_snapshot()


@app.post("/api/scan")
def trigger_scan(_: dict = Depends(require_admin)):
    return run_scan()


def _refresh_file_in_snapshot(project: str, relative_file: str) -> dict:
    """Recharge le fichier modifié et met à jour le JSON sans tout rescanner."""
    env_path = resolve_env_path(project, relative_file)
    variables = read_variables(env_path)

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
