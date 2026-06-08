"""Configuration centrale de l'application.

Toutes les valeurs sont lues depuis les variables d'environnement, ce qui
permet de configurer l'application sans modifier le code (cf. .env.example).
"""
from __future__ import annotations

import os
from pathlib import Path


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if not raw:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


class Settings:
    """Réglages de l'application, instanciés une seule fois (singleton)."""

    def __init__(self) -> None:
        # Racine contenant les projets à scanner (chaque sous-dossier = 1 projet).
        # Sur le VPS : /home/kevine/deploy.  En Docker on monte ce dossier sur /deploy.
        self.deploy_root: Path = Path(
            os.getenv("DEPLOY_ROOT", "/deploy")
        ).expanduser().resolve()

        # Dossier où est écrit le JSON généré (ne doit PAS être public).
        self.data_dir: Path = Path(
            os.getenv("DATA_DIR", str(Path(__file__).resolve().parent.parent / "data"))
        ).expanduser().resolve()

        # Dossier des fichiers statiques (front).
        self.web_dir: Path = Path(
            os.getenv("WEB_DIR", str(Path(__file__).resolve().parent.parent / "web"))
        ).expanduser().resolve()

        # Authentification admin (obligatoire).
        self.admin_password: str = os.getenv("ADMIN_PASSWORD", "")
        self.admin_username: str = os.getenv("ADMIN_USERNAME", "admin")
        self.jwt_secret: str = os.getenv("JWT_SECRET", "")
        self.jwt_expire_hours: int = int(os.getenv("JWT_EXPIRE_HOURS", "12"))

        # Planification du scan.
        self.scan_interval_minutes: int = int(os.getenv("SCAN_INTERVAL_MINUTES", "30"))
        self.scan_on_startup: bool = _get_bool("SCAN_ON_STARTUP", True)

        # Quels fichiers considérer comme des ".env".
        self.env_globs: list[str] = _get_list("ENV_GLOBS", [".env", ".env.*"])
        # Suffixes ignorés (templates / exemples, qui ne contiennent pas de vrais secrets).
        self.env_exclude_suffixes: list[str] = _get_list(
            "ENV_EXCLUDE_SUFFIXES", [".example", ".sample", ".dist", ".template"]
        )
        # Dossiers ignorés lors du parcours récursif.
        self.exclude_dirs: set[str] = set(
            _get_list(
                "EXCLUDE_DIRS",
                [
                    "node_modules",
                    "vendor",
                    ".git",
                    ".svn",
                    "dist",
                    "build",
                    "__pycache__",
                    ".venv",
                    "venv",
                    ".idea",
                    "storage",
                ],
            )
        )

        self.port: int = int(os.getenv("PORT", "8000"))
        self.host: str = os.getenv("HOST", "0.0.0.0")

    @property
    def json_path(self) -> Path:
        return self.data_dir / "envs.json"

    def validate(self) -> None:
        """Vérifie la configuration minimale au démarrage."""
        errors: list[str] = []
        if not self.admin_password:
            errors.append("ADMIN_PASSWORD est requis (mot de passe admin).")
        if not self.jwt_secret or len(self.jwt_secret) < 16:
            errors.append("JWT_SECRET est requis et doit faire au moins 16 caractères.")
        if not self.deploy_root.exists():
            errors.append(
                f"DEPLOY_ROOT introuvable : {self.deploy_root} "
                "(vérifiez le chemin / le montage Docker)."
            )
        if errors:
            raise RuntimeError(
                "Configuration invalide :\n  - " + "\n  - ".join(errors)
            )


settings = Settings()
