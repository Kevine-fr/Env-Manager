"""Lecture / écriture sûre des fichiers .env.

Toutes les écritures (édition, suppression, ajout) modifient directement le
fichier .env d'origine dans le dossier `deploy` du VPS, en préservant les
commentaires et l'ordre des variables.

Sécurité : chaque chemin reçu du client est validé pour empêcher toute
sortie du dossier `deploy` (path traversal) et garantir qu'on ne touche
qu'à de vrais fichiers .env.
"""
from __future__ import annotations

import fnmatch
from pathlib import Path

from dotenv import dotenv_values, set_key, unset_key

from .config import settings


class EnvIOError(Exception):
    """Erreur métier renvoyée proprement à l'API (400/403/404)."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _is_env_filename(name: str) -> bool:
    """Le nom de fichier correspond-il à un .env (et pas à un template) ?"""
    for suffix in settings.env_exclude_suffixes:
        if name.endswith(suffix):
            return False
    return any(fnmatch.fnmatch(name, pattern) for pattern in settings.env_globs)


def resolve_env_path(project: str, relative_file: str) -> Path:
    """Valide (project, fichier) et renvoie un chemin absolu sûr.

    - `relative_file` est relatif à DEPLOY_ROOT (ex: "Tea-Server/.env").
    - On vérifie que le premier segment == project.
    - On vérifie que le chemin résolu reste DANS DEPLOY_ROOT.
    - On vérifie que c'est bien un fichier .env existant.
    """
    if not project or "/" in project or "\\" in project or project in {".", ".."}:
        raise EnvIOError("Nom de projet invalide.", 400)

    rel = Path(relative_file)
    if rel.is_absolute() or ".." in rel.parts:
        raise EnvIOError("Chemin de fichier invalide.", 400)

    parts = rel.parts
    if not parts or parts[0] != project:
        raise EnvIOError(
            "Le fichier ne correspond pas au projet indiqué.", 400
        )

    candidate = (settings.deploy_root / rel).resolve()

    # Garde-fou anti path-traversal : le fichier DOIT rester sous DEPLOY_ROOT.
    if not candidate.is_relative_to(settings.deploy_root):
        raise EnvIOError("Accès refusé : chemin hors du dossier deploy.", 403)

    if not _is_env_filename(candidate.name):
        raise EnvIOError("Ce fichier n'est pas un fichier .env.", 400)

    if not candidate.exists() or not candidate.is_file():
        raise EnvIOError("Fichier .env introuvable.", 404)

    return candidate


def read_variables(env_path: Path) -> list[dict[str, str]]:
    """Lit un .env et renvoie une liste ordonnée {key, value}.

    `interpolate=False` : on affiche les valeurs telles qu'elles sont écrites
    dans le fichier (sans expansion des ${VAR}).
    """
    values = dotenv_values(env_path, interpolate=False)
    return [
        {"key": key, "value": "" if val is None else val}
        for key, val in values.items()
    ]


def _validate_key(key: str) -> str:
    key = (key or "").strip()
    if not key:
        raise EnvIOError("La clé est vide.", 400)
    # Clés .env classiques : lettres/chiffres/underscore, ne commence pas par un chiffre.
    if not all(c.isalnum() or c == "_" for c in key) or key[0].isdigit():
        raise EnvIOError(
            "Clé invalide : utilisez uniquement lettres, chiffres et _ "
            "(sans commencer par un chiffre).",
            400,
        )
    return key


def update_variable(project: str, relative_file: str, key: str, value: str) -> dict:
    """Crée ou met à jour une variable dans le fichier .env d'origine."""
    env_path = resolve_env_path(project, relative_file)
    key = _validate_key(key)
    if value is None:
        value = ""
    success, _, _ = set_key(env_path, key, value, quote_mode="auto")
    if not success:
        raise EnvIOError("Échec de l'écriture de la variable.", 500)
    return {"key": key, "value": value}


def delete_variable(project: str, relative_file: str, key: str) -> None:
    """Supprime une variable du fichier .env d'origine."""
    env_path = resolve_env_path(project, relative_file)
    key = _validate_key(key)

    existing = dotenv_values(env_path, interpolate=False)
    if key not in existing:
        raise EnvIOError("Cette variable n'existe pas dans le fichier.", 404)

    success, _ = unset_key(env_path, key, quote_mode="auto")
    if not success:
        raise EnvIOError("Échec de la suppression de la variable.", 500)
