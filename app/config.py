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

        # =====================================================================
        # Intégration "Infrastructure" (contrôle Docker, nginx, SSL, git push).
        # =====================================================================
        self.infra_enabled: bool = _get_bool("INFRA_ENABLED", True)

        # Domaine de base : les sous-domaines deviennent <sous-domaine>.<APP_DOMAIN>.
        self.app_domain: str = os.getenv("APP_DOMAIN", "wk-archi-o22a-15m-g1.fr")

        # Racine du dossier deploy côté HÔTE (= source du montage Docker).
        # Sert à traduire les chemins conteneur -> hôte pour les conteneurs frères
        # (certbot monte des chemins HÔTE, pas conteneur).
        self.deploy_host_root: str = os.getenv("DEPLOY_HOST_ROOT", "/home/kevine/deploy")

        # Chemin du dépôt Infrastructure tel que vu par env-manager (via /deploy).
        # Vide => auto-détection d'un sous-dossier de DEPLOY_ROOT contenant nginx/conf.d.
        self.infra_repo_path_raw: str = os.getenv("INFRA_REPO_PATH", "")

        self.nginx_container: str = os.getenv("NGINX_CONTAINER", "nginx")
        self.nginx_conf_subdir: str = os.getenv("NGINX_CONF_SUBDIR", "nginx/conf.d")
        self.certbot_www_subdir: str = os.getenv("CERTBOT_WWW_SUBDIR", "certbot/www")
        self.certbot_conf_subdir: str = os.getenv("CERTBOT_CONF_SUBDIR", "certbot/conf")
        self.certbot_image: str = os.getenv("CERTBOT_IMAGE", "certbot/certbot:latest")

        # Services dont on autorise le pilotage (start/stop/restart) depuis l'UI.
        self.infra_services: list[str] = _get_list("INFRA_SERVICES", ["sonarqube"])

        # --- Git (commit + push du dépôt Infrastructure) ---
        self.git_branch: str = os.getenv("GIT_BRANCH", "main")
        self.git_remote: str = os.getenv("GIT_REMOTE", "origin")
        self.git_author_name: str = os.getenv("GIT_AUTHOR_NAME", "ENV Manager")
        self.git_author_email: str = os.getenv("GIT_AUTHOR_EMAIL", "env-manager@vps.local")
        # Auth push : soit un token GitHub (HTTPS), soit une clé SSH montée.
        self.github_token: str = os.getenv("GIT_TOKEN", "")
        self.git_repo_slug: str = os.getenv("GIT_REPO_SLUG", "")  # ex: Kevine-fr/Infrastructure
        self.git_ssh_key_path: str = os.getenv("GIT_SSH_KEY_PATH", "")
        # Pousser automatiquement après chaque modif (.conf, SSL) ?
        self.infra_auto_push: bool = _get_bool("INFRA_AUTO_PUSH", True)

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
