"""Scanner : parcourt le dossier `deploy`, collecte tous les .env et écrit
le résultat dans data/envs.json.

Ce module est utilisé à la fois par le scheduler interne (toutes les 30 min)
et par le script autonome scripts/run_scan.py (pour un vrai cron système).
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .config import settings
from .env_io import _is_env_filename, read_variables


def _find_env_files(project_dir: Path) -> list[Path]:
    """Trouve récursivement les fichiers .env d'un projet (hors dossiers exclus)."""
    found: list[Path] = []
    for root, dirs, files in os.walk(project_dir):
        # On élague les dossiers exclus pour ne pas y descendre.
        dirs[:] = [d for d in dirs if d not in settings.exclude_dirs]
        for name in files:
            if _is_env_filename(name):
                found.append(Path(root) / name)
    return sorted(found, key=lambda p: p.as_posix())


def build_snapshot() -> dict:
    """Construit la structure de données complète (sans l'écrire)."""
    deploy_root = settings.deploy_root
    projects: list[dict] = []

    if deploy_root.exists():
        for entry in sorted(deploy_root.iterdir(), key=lambda p: p.name.lower()):
            if not entry.is_dir() or entry.name in settings.exclude_dirs:
                continue

            env_files: list[dict] = []
            for env_path in _find_env_files(entry):
                try:
                    variables = read_variables(env_path)
                except Exception as exc:  # fichier illisible : on le signale sans planter
                    variables = []
                    error = str(exc)
                else:
                    error = None

                env_files.append(
                    {
                        "path": env_path.relative_to(deploy_root).as_posix(),
                        "name": env_path.name,
                        "variable_count": len(variables),
                        "variables": variables,
                        "error": error,
                    }
                )

            projects.append(
                {
                    "name": entry.name,
                    "file_count": len(env_files),
                    "variable_count": sum(f["variable_count"] for f in env_files),
                    "env_files": env_files,
                }
            )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "deploy_root": str(deploy_root),
        "project_count": len(projects),
        "total_env_files": sum(p["file_count"] for p in projects),
        "total_variables": sum(p["variable_count"] for p in projects),
        "projects": projects,
    }


def write_snapshot(snapshot: dict) -> Path:
    """Écrit le JSON de façon atomique avec des permissions restrictives (0600)."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    target = settings.json_path

    fd, tmp_path = tempfile.mkstemp(dir=settings.data_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, ensure_ascii=False, indent=2)
        os.chmod(tmp_path, 0o600)  # secrets : lisible par le propriétaire seulement
        os.replace(tmp_path, target)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
    return target


def run_scan() -> dict:
    """Scanne et écrit le JSON. Renvoie le snapshot généré."""
    snapshot = build_snapshot()
    write_snapshot(snapshot)
    return snapshot


def load_snapshot() -> dict:
    """Charge le dernier JSON généré (ou en génère un si absent)."""
    if not settings.json_path.exists():
        return run_scan()
    with open(settings.json_path, "r", encoding="utf-8") as fh:
        return json.load(fh)
