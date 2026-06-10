"""Intégration "Infrastructure".

Ce module connecte ENV Manager au dépôt Infrastructure déployé sur le VPS et
expose, derrière l'authentification admin, quatre familles d'actions :

  1. Piloter des services Docker (ex. SonarQube : up / down / restart).
  2. Créer/supprimer un reverse-proxy nginx (.conf) à partir de
     (sous-domaine, conteneur, port).
  3. Obtenir/renouveler un certificat SSL via certbot (sous-domaine, email).
  4. Commiter + pousser les modifications du dépôt vers GitHub.

Choix de conception / sécurité :
  - Tout passe par le SDK Docker (pas de shell) ; les opérations git utilisent
    subprocess avec des listes d'arguments (jamais shell=True).
  - Les entrées utilisateur (sous-domaine, conteneur, port, email) sont
    strictement validées avant d'être écrites dans un .conf ou un message de commit.
  - Le pilotage de conteneurs est restreint à une liste blanche (INFRA_SERVICES).
  - Le token GitHub n'est jamais renvoyé ni journalisé.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path

from .config import settings

logger = logging.getLogger("env-manager.infra")

# Dépendances de démarrage connues (démarrées avant, arrêtées après le service).
SERVICE_DEPS: dict[str, list[str]] = {
    "sonarqube": ["sonarqube-db"],
}
SERVICE_LABELS: dict[str, str] = {
    "sonarqube": "SonarQube",
    "sonarqube-db": "SonarQube · PostgreSQL",
}

# Validation stricte.
_SUBDOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
_CONTAINER_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class InfraError(Exception):
    """Erreur métier côté infrastructure (mappée en réponse HTTP)."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# =============================================================================
# Validation des entrées
# =============================================================================
def validate_subdomain(value: str) -> str:
    v = (value or "").strip().lower()
    # Tolère que l'utilisateur saisisse déjà le domaine complet.
    if v.endswith("." + settings.app_domain):
        v = v[: -(len(settings.app_domain) + 1)]
    if not _SUBDOMAIN_RE.match(v):
        raise InfraError(
            "Sous-domaine invalide : lettres minuscules, chiffres et tirets uniquement."
        )
    return v


def validate_container(value: str) -> str:
    v = (value or "").strip()
    if not _CONTAINER_RE.match(v):
        raise InfraError("Nom de conteneur invalide.")
    return v


def validate_port(value: int) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise InfraError("Port invalide.")
    if not (1 <= port <= 65535):
        raise InfraError("Le port doit être compris entre 1 et 65535.")
    return port


def validate_email(value: str) -> str:
    v = (value or "").strip()
    if not _EMAIL_RE.match(v):
        raise InfraError("Adresse email invalide.")
    return v


def fqdn_for(subdomain: str) -> str:
    return f"{subdomain}.{settings.app_domain}"


# =============================================================================
# Résolution des chemins (conteneur <-> hôte)
# =============================================================================
def _autodetect_repo() -> Path | None:
    """Cherche, sous DEPLOY_ROOT, un dossier contenant nginx/conf.d (le dépôt infra)."""
    root = settings.deploy_root
    # 1) DEPLOY_ROOT lui-même est-il le dépôt ?
    if (root / settings.nginx_conf_subdir).is_dir():
        return root
    # 2) Sinon, un sous-dossier direct.
    try:
        for child in sorted(root.iterdir()):
            if child.is_dir() and (child / settings.nginx_conf_subdir).is_dir():
                return child
    except OSError:
        pass
    return None


def repo_path() -> Path:
    """Chemin (conteneur) du dépôt Infrastructure."""
    if settings.infra_repo_path_raw:
        p = Path(settings.infra_repo_path_raw).expanduser()
        if not p.is_absolute():
            p = settings.deploy_root / p
        return p.resolve()
    detected = _autodetect_repo()
    if detected:
        return detected.resolve()
    # Repli : convention par défaut.
    return (settings.deploy_root / "Infrastructure").resolve()


def host_path_of(container_path: Path) -> str:
    """Traduit un chemin conteneur (sous /deploy) en chemin HÔTE équivalent.

    Nécessaire car certbot tourne dans un conteneur frère qui monte des chemins
    de l'hôte, pas ceux d'env-manager.
    """
    container_path = container_path.resolve()
    try:
        rel = container_path.relative_to(settings.deploy_root)
    except ValueError:
        # Hors de /deploy : on renvoie tel quel (cas non standard).
        return str(container_path)
    return str(Path(settings.deploy_host_root) / rel)


def nginx_conf_dir() -> Path:
    return repo_path() / settings.nginx_conf_subdir


def conf_path(subdomain: str) -> Path:
    return nginx_conf_dir() / f"{subdomain}.conf"


# =============================================================================
# Client Docker (SDK, via la socket montée)
# =============================================================================
_docker_client = None
_docker_error: str | None = None


def get_docker():
    """Retourne un client Docker, ou lève InfraError avec une cause claire."""
    global _docker_client, _docker_error
    if _docker_client is not None:
        return _docker_client
    try:
        import docker  # type: ignore
    except ImportError:
        _docker_error = "Le SDK Python 'docker' n'est pas installé."
        raise InfraError(_docker_error, 500)
    try:
        client = docker.from_env()
        client.ping()
    except Exception as exc:  # noqa: BLE001
        _docker_error = (
            "Impossible de joindre le démon Docker. Vérifiez que "
            "/var/run/docker.sock est bien monté dans le conteneur. "
            f"({exc.__class__.__name__})"
        )
        raise InfraError(_docker_error, 503)
    _docker_client = client
    return client


def docker_available() -> tuple[bool, str | None]:
    try:
        get_docker()
        return True, None
    except InfraError as exc:
        return False, exc.message


# =============================================================================
# Pilotage des services
# =============================================================================
def _service_label(name: str) -> str:
    return SERVICE_LABELS.get(name, name)


def _container_state(client, name: str) -> dict:
    try:
        c = client.containers.get(name)
    except Exception:  # noqa: BLE001  (NotFound, etc.)
        return {"name": name, "label": _service_label(name), "exists": False,
                "status": "absent", "running": False}
    status = c.status  # running, exited, created, paused...
    started_at = None
    try:
        started_at = c.attrs.get("State", {}).get("StartedAt")
    except Exception:  # noqa: BLE001
        pass
    return {
        "name": name,
        "label": _service_label(name),
        "exists": True,
        "status": status,
        "running": status == "running",
        "started_at": started_at,
        "image": (c.image.tags[0] if c.image and c.image.tags else None),
    }


def list_services() -> list[dict]:
    client = get_docker()
    out = []
    for name in settings.infra_services:
        entry = _container_state(client, name)
        deps = SERVICE_DEPS.get(name, [])
        if deps:
            entry["deps"] = [_container_state(client, d) for d in deps]
        out.append(entry)
    return out


def service_action(name: str, action: str) -> dict:
    if name not in settings.infra_services:
        raise InfraError("Service non autorisé.", 403)
    if action not in {"start", "stop", "restart"}:
        raise InfraError("Action inconnue.", 400)

    client = get_docker()
    deps = SERVICE_DEPS.get(name, [])

    def _get(n):
        try:
            return client.containers.get(n)
        except Exception:  # noqa: BLE001
            raise InfraError(f"Conteneur introuvable : {n}.", 404)

    if action == "start":
        # Ne démarre que si le service est arrêté.
        svc = _get(name)
        if svc.status == "running":
            return {"ok": True, "name": name, "action": action, "skipped": True,
                    "message": f"{_service_label(name)} est déjà actif.",
                    "service": _container_state(client, name)}
        # Démarrer d'abord les dépendances, puis le service.
        for d in deps:
            _get(d).start()
        svc.start()
    elif action == "stop":
        # N'arrête que si le service tourne.
        svc = _get(name)
        if svc.status != "running":
            return {"ok": True, "name": name, "action": action, "skipped": True,
                    "message": f"{_service_label(name)} est déjà arrêté.",
                    "service": _container_state(client, name)}
        # Arrêter le service, puis ses dépendances.
        svc.stop()
        for d in deps:
            _get(d).stop()
    else:  # restart
        for d in deps:
            _get(d).restart()
        _get(name).restart()

    logger.info("Service %s -> %s", name, action)
    return {"ok": True, "name": name, "action": action, "service": _container_state(client, name)}


# =============================================================================
# nginx : reload + génération de .conf
# =============================================================================
def reload_nginx() -> None:
    """Teste puis recharge la configuration nginx (docker exec)."""
    client = get_docker()
    try:
        nginx = client.containers.get(settings.nginx_container)
    except Exception:  # noqa: BLE001
        raise InfraError(
            f"Conteneur nginx introuvable ({settings.nginx_container}).", 404
        )
    test = nginx.exec_run(["nginx", "-t"])
    if test.exit_code != 0:
        raise InfraError(
            "La configuration nginx est invalide (nginx -t) :\n"
            + test.output.decode(errors="replace"),
            400,
        )
    res = nginx.exec_run(["nginx", "-s", "reload"])
    if res.exit_code != 0:
        raise InfraError(
            "Échec du reload nginx :\n" + res.output.decode(errors="replace"), 500
        )


def _conf_http_only(fqdn: str, container: str, port: int) -> str:
    return f"""# Généré par ENV Manager — proxy HTTP (avant certificat SSL).
server {{
    listen 80;
    server_name {fqdn};

    location ^~ /.well-known/acme-challenge/ {{
        root /var/www/certbot;
        try_files $uri =404;
    }}

    resolver 127.0.0.11 valid=30s ipv6=off;
    set $upstream {container}:{port};

    location / {{
        proxy_pass http://$upstream;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}
"""


def _conf_ssl(fqdn: str, container: str, port: int) -> str:
    return f"""# Généré par ENV Manager — proxy HTTPS (certificat Let's Encrypt).
server {{
    listen 80;
    server_name {fqdn};

    location ^~ /.well-known/acme-challenge/ {{
        root /var/www/certbot;
        try_files $uri =404;
    }}

    location / {{
        return 301 https://$host$request_uri;
    }}
}}

server {{
    listen 443 ssl;
    http2 on;
    server_name {fqdn};

    ssl_certificate     /etc/letsencrypt/live/{fqdn}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{fqdn}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_tickets off;

    add_header Strict-Transport-Security "max-age=63072000" always;
    add_header X-Content-Type-Options "nosniff" always;

    client_max_body_size 50m;

    resolver 127.0.0.11 valid=30s ipv6=off;
    set $upstream {container}:{port};

    location / {{
        proxy_pass http://$upstream;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}
"""


def _write_conf(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def _parse_conf(text: str) -> dict:
    """Extraction best-effort : server_name, upstream, présence SSL, généré par nous."""
    server_name = None
    m = re.search(r"server_name\s+([^;]+);", text)
    if m:
        server_name = m.group(1).strip().split()[0]
    upstream = None
    m = re.search(r"set\s+\$upstream\s+([^;]+);", text)
    if m:
        upstream = m.group(1).strip()
    else:
        m = re.search(r"proxy_pass\s+https?://([^/;]+)", text)
        if m:
            upstream = m.group(1).strip()
    return {
        "server_name": server_name,
        "upstream": upstream,
        "ssl": "listen 443" in text,
        "managed": text.startswith("# Généré par ENV Manager"),
    }


def list_confs() -> list[dict]:
    d = nginx_conf_dir()
    out = []
    if not d.is_dir():
        return out
    for f in sorted(d.glob("*.conf")):
        try:
            info = _parse_conf(f.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            info = {"server_name": None, "upstream": None, "ssl": False, "managed": False}
        out.append({"file": f.name, **info})
    return out


def create_conf(subdomain: str, container: str, port: int) -> dict:
    """Crée un reverse-proxy nginx en HTTP (le SSL s'ajoute ensuite via certbot)."""
    sub = validate_subdomain(subdomain)
    cont = validate_container(container)
    prt = validate_port(port)
    fqdn = fqdn_for(sub)
    path = conf_path(sub)
    if path.exists():
        raise InfraError(f"Un fichier {sub}.conf existe déjà.", 409)

    _write_conf(path, _conf_http_only(fqdn, cont, prt))
    try:
        reload_nginx()
    except InfraError:
        # Reload raté -> on retire le fichier pour ne pas casser nginx.
        path.unlink(missing_ok=True)
        raise
    logger.info("Conf nginx créée : %s -> %s:%s", fqdn, cont, prt)
    return {"ok": True, "file": path.name, "fqdn": fqdn, "upstream": f"{cont}:{prt}", "ssl": False}


def delete_conf(file_name: str) -> dict:
    # On n'accepte qu'un nom de fichier simple, dans le dossier conf.d.
    name = os.path.basename((file_name or "").strip())
    if not name.endswith(".conf") or "/" in file_name or ".." in file_name:
        raise InfraError("Nom de fichier .conf invalide.", 400)
    path = nginx_conf_dir() / name
    if not path.exists():
        raise InfraError("Fichier .conf introuvable.", 404)
    path.unlink()
    try:
        reload_nginx()
    except InfraError:
        logger.warning("Conf %s supprimée mais reload nginx en échec.", name)
        raise
    logger.info("Conf nginx supprimée : %s", name)
    return {"ok": True, "file": name}


# =============================================================================
# SSL (certbot, en conteneur one-shot)
# =============================================================================
def list_certificates() -> list[dict]:
    live = repo_path() / settings.certbot_conf_subdir / "live"
    out = []
    if not live.is_dir():
        return out
    for d in sorted(live.iterdir()):
        if d.is_dir() and (d / "fullchain.pem").exists():
            out.append({"domain": d.name})
    return out


def _ensure_dns_resolves(fqdn: str) -> None:
    """Échoue tôt si le sous-domaine ne résout pas (A ou AAAA).

    Sans cela, le challenge HTTP-01 de Let's Encrypt renverrait un NXDOMAIN et
    certbot afficherait l'obscur « Some challenges have failed ».
    """
    try:
        socket.getaddrinfo(fqdn, None)
    except socket.gaierror:
        raise InfraError(
            f"{fqdn} ne résout pas en DNS (NXDOMAIN). Ajoutez un enregistrement "
            "A (ou un wildcard *) pointant vers l'IP publique du VPS, attendez la "
            "propagation, puis réessayez.",
            400,
        )


def obtain_certificate(subdomain: str, email: str) -> dict:
    """Lance certbot (webroot) puis bascule le .conf en HTTPS et recharge nginx."""
    sub = validate_subdomain(subdomain)
    mail = validate_email(email)
    fqdn = fqdn_for(sub)

    # Il faut un .conf existant (créé via "Créer le proxy") pour connaître l'upstream.
    path = conf_path(sub)
    if not path.exists():
        raise InfraError(
            f"Aucun proxy pour {fqdn}. Créez d'abord le reverse-proxy "
            "(sous-domaine, conteneur, port).",
            409,
        )
    parsed = _parse_conf(path.read_text(encoding="utf-8", errors="replace"))
    upstream = parsed.get("upstream")
    if not upstream or ":" not in upstream:
        raise InfraError("Impossible de déterminer l'upstream du .conf existant.", 400)
    container, _, port = upstream.partition(":")

    # Vérifie que le sous-domaine résout AVANT de lancer certbot : le challenge
    # HTTP-01 échouerait sinon avec un « Some challenges have failed » obscur.
    _ensure_dns_resolves(fqdn)

    client = get_docker()
    # Chemins HÔTE du webroot et de la conf certbot. On privilégie une surcharge
    # absolue (CERTBOT_*_HOST) — indispensable si le gateway nginx vit hors du
    # dépôt (ex. /opt/gateway) — sinon on dérive depuis le dépôt Infrastructure.
    host_www = settings.certbot_www_host or host_path_of(repo_path() / settings.certbot_www_subdir)
    host_conf = settings.certbot_conf_host or host_path_of(repo_path() / settings.certbot_conf_subdir)

    command = [
        "certonly", "--webroot", "-w", "/var/www/certbot",
        "-d", fqdn,
        "--email", mail,
        "--agree-tos", "--no-eff-email",
        "--non-interactive", "--keep-until-expiring",
        "-v",  # détaille la raison exacte d'un challenge échoué (DNS, port 80…)
    ]
    try:
        import docker  # type: ignore
        logs = client.containers.run(
            settings.certbot_image,
            command=command,
            volumes={
                host_www: {"bind": "/var/www/certbot", "mode": "rw"},
                host_conf: {"bind": "/etc/letsencrypt", "mode": "rw"},
            },
            remove=True,
            stdout=True,
            stderr=True,
        )
        output = logs.decode(errors="replace") if isinstance(logs, (bytes, bytearray)) else str(logs)
    except Exception as exc:  # noqa: BLE001
        # docker.errors.ContainerError porte stderr ; on l'expose pour le diagnostic.
        detail = getattr(exc, "stderr", None)
        if isinstance(detail, (bytes, bytearray)):
            detail = detail.decode(errors="replace")
        raise InfraError(
            "Échec de certbot :\n" + (detail or str(exc)),
            502,
        )

    # Cert OK -> on bascule le .conf en HTTPS et on recharge.
    _write_conf(path, _conf_ssl(fqdn, container, int(port)))
    reload_nginx()
    logger.info("Certificat obtenu + conf HTTPS pour %s", fqdn)
    return {"ok": True, "fqdn": fqdn, "ssl": True, "output": output[-4000:]}


# =============================================================================
# Git : statut, commit + push
# =============================================================================
def _run_git(args: list[str], cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    # Le dépôt appartient à l'utilisateur du VPS (ex. kevine), mais le conteneur
    # tourne en root : git refuserait sinon ("detected dubious ownership").
    # On déclare le dépôt comme sûr sur CHAQUE commande (persistant, suit le chemin).
    safe = ["-c", f"safe.directory={cwd}"]
    return subprocess.run(
        ["git", *safe, *args],
        cwd=str(cwd),
        env=full_env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def git_available() -> tuple[bool, str | None]:
    repo = repo_path()
    if not repo.exists():
        return False, f"Dépôt introuvable : {repo}"
    if not (repo / ".git").exists():
        return False, f"{repo} n'est pas un dépôt git (.git absent)."
    try:
        res = _run_git(["rev-parse", "--is-inside-work-tree"], repo)
    except FileNotFoundError:
        return False, "git n'est pas installé dans le conteneur."
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    if res.returncode != 0:
        return False, res.stderr.strip() or "Dépôt git invalide."
    return True, None


def git_status() -> dict:
    ok, err = git_available()
    if not ok:
        raise InfraError(err or "git indisponible.", 503)
    repo = repo_path()
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo).stdout.strip()
    last = _run_git(["log", "-1", "--pretty=%h — %s (%cr)"], repo).stdout.strip()
    porcelain = _run_git(["status", "--porcelain"], repo).stdout.strip()
    changes = [line for line in porcelain.splitlines() if line.strip()]
    return {
        "branch": branch,
        "last_commit": last,
        "dirty": bool(changes),
        "changes": changes[:50],
        "change_count": len(changes),
        "auto_push": settings.infra_auto_push,
        "push_method": _push_method(),
    }


def _push_method() -> str:
    if settings.github_token and settings.git_repo_slug:
        return "https-token"
    if settings.git_ssh_key_path:
        return "ssh-key"
    return "remote-default"


def _push(repo: Path) -> str:
    """Pousse HEAD vers la branche cible. Renvoie un message (sans secret)."""
    method = _push_method()
    branch = settings.git_branch

    key_copy: str | None = None
    try:
        if method == "https-token":
            url = (
                f"https://x-access-token:{settings.github_token}"
                f"@github.com/{settings.git_repo_slug}.git"
            )
            res = _run_git(["push", url, f"HEAD:{branch}"], repo)
        elif method == "ssh-key":
            # La clé est souvent montée :ro avec les permissions de l'hôte (ex.
            # 0755). SSH refuse toute clé privée accessible par d'autres et
            # l'ignore. On la recopie donc dans un fichier privé en 0600.
            key_copy = _private_key_copy(settings.git_ssh_key_path)
            env = {
                "GIT_SSH_COMMAND": (
                    f"ssh -i {key_copy} "
                    "-o StrictHostKeyChecking=accept-new -o IdentitiesOnly=yes"
                )
            }
            res = _run_git(["push", settings.git_remote, f"HEAD:{branch}"], repo, env=env)
        else:
            res = _run_git(["push", settings.git_remote, f"HEAD:{branch}"], repo)
    finally:
        if key_copy:
            try:
                os.unlink(key_copy)
            except OSError:
                pass

    if res.returncode != 0:
        # Ne jamais renvoyer l'URL (peut contenir le token).
        stderr = (res.stderr or "").replace(settings.github_token or "\0", "***")
        raise InfraError("Échec du git push :\n" + stderr.strip(), 502)
    return "Push effectué."


def _private_key_copy(src: str) -> str:
    """Copie la clé SSH dans un fichier temporaire lisible par le seul
    propriétaire (0600), exigé par OpenSSH. Renvoie le chemin de la copie."""
    if not src or not Path(src).is_file():
        raise InfraError(f"Clé SSH introuvable : {src}.", 500)
    fd, dst = tempfile.mkstemp(prefix="deploy_key_")
    try:
        os.close(fd)
        shutil.copyfile(src, dst)
        os.chmod(dst, 0o600)
    except OSError as e:
        try:
            os.unlink(dst)
        except OSError:
            pass
        raise InfraError(f"Impossible de préparer la clé SSH : {e}.", 500)
    return dst


def git_commit_and_push(message: str, paths: list[str] | None = None,
                        push: bool | None = None) -> dict:
    ok, err = git_available()
    if not ok:
        raise InfraError(err or "git indisponible.", 503)
    repo = repo_path()

    # Stage : fichiers précis si fournis, sinon tout le dossier conf nginx.
    if paths:
        _run_git(["add", "--", *paths], repo)
    else:
        _run_git(["add", "-A", settings.nginx_conf_subdir], repo)

    staged = _run_git(["diff", "--cached", "--name-only"], repo).stdout.strip()
    committed = False
    commit_hash = None
    if staged:
        res = _run_git(
            [
                "-c", f"user.name={settings.git_author_name}",
                "-c", f"user.email={settings.git_author_email}",
                "commit", "-m", message,
            ],
            repo,
        )
        if res.returncode != 0:
            raise InfraError("Échec du commit :\n" + (res.stderr or "").strip(), 500)
        committed = True
        commit_hash = _run_git(["rev-parse", "--short", "HEAD"], repo).stdout.strip()

    do_push = settings.infra_auto_push if push is None else push
    pushed = False
    push_msg = None
    if do_push and (committed or _ahead_of_remote(repo)):
        push_msg = _push(repo)
        pushed = True

    return {
        "ok": True,
        "committed": committed,
        "commit": commit_hash,
        "pushed": pushed,
        "message": push_msg or ("Aucune modification à commiter." if not committed else "Commit créé."),
    }


def _ahead_of_remote(repo: Path) -> bool:
    """Vrai s'il y a des commits locaux non encore poussés."""
    res = _run_git(
        ["rev-list", "--count", f"{settings.git_remote}/{settings.git_branch}..HEAD"],
        repo,
    )
    if res.returncode != 0:
        return True  # en cas de doute, on tente le push
    try:
        return int(res.stdout.strip() or "0") > 0
    except ValueError:
        return False


# =============================================================================
# Statut global (pour l'UI)
# =============================================================================
def infra_status() -> dict:
    repo = repo_path()
    d_ok, d_err = docker_available()
    g_ok, g_err = git_available()
    return {
        "enabled": settings.infra_enabled,
        "app_domain": settings.app_domain,
        "repo_path": str(repo),
        "repo_host_path": host_path_of(repo),
        "nginx_conf_dir_exists": nginx_conf_dir().is_dir(),
        "docker": {"available": d_ok, "error": d_err},
        "git": {"available": g_ok, "error": g_err, "push_method": _push_method(),
                "auto_push": settings.infra_auto_push},
        "managed_services": settings.infra_services,
    }
