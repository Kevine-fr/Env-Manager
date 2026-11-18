"""Réglages de test : un faux dossier `deploy` et des secrets jetables.

`app.config.settings` est lu une seule fois à l'import : les variables
doivent donc être posées AVANT tout `import app`.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_RACINE = Path(tempfile.mkdtemp(prefix="envmgr-tests-"))
_DEPLOY = _RACINE / "deploy"
_DATA = _RACINE / "data"
_DEPLOY.mkdir()
_DATA.mkdir()

os.environ.update(
    {
        "DEPLOY_ROOT": str(_DEPLOY),
        "DATA_DIR": str(_DATA),
        "ADMIN_USERNAME": "admin",
        "ADMIN_PASSWORD": "mot-de-passe-de-test",
        "JWT_SECRET": "cle-de-test-suffisamment-longue",
        "SCAN_ON_STARTUP": "false",
        "INFRA_ENABLED": "false",
    }
)


@pytest.fixture()
def deploy(tmp_path):
    """Un dossier deploy neuf pour chaque test, avec deux projets."""
    from app.config import settings

    racine = tmp_path / "deploy"
    (racine / "Tea-Server").mkdir(parents=True)
    (racine / "Tea-Server" / ".env").write_text("# commentaire\nAPP_KEY=abc\nDB_HOST=db\n")
    (racine / "Tea-Server" / ".env.example").write_text("APP_KEY=\n")
    (racine / "Titi-App" / "node_modules" / "x").mkdir(parents=True)
    (racine / "Titi-App" / "node_modules" / "x" / ".env").write_text("NE_PAS=lire\n")
    (racine / "Titi-App" / ".env.production").write_text("NEXTAUTH_SECRET=s3cr3t\n")

    anciens = settings.deploy_root, settings.data_dir
    settings.deploy_root = racine.resolve()
    settings.data_dir = (tmp_path / "data").resolve()
    yield racine
    settings.deploy_root, settings.data_dir = anciens


@pytest.fixture()
def client(deploy):
    from fastapi.testclient import TestClient

    from app.main import app, limiteur_connexion

    limiteur_connexion._echecs.clear()
    # Sans `with` : le cycle de vie (et son planificateur) ne démarre pas.
    return TestClient(app)


@pytest.fixture()
def jeton(client):
    rep = client.post("/api/login", json={"username": "admin", "password": "mot-de-passe-de-test"})
    assert rep.status_code == 200
    return {"Authorization": f"Bearer {rep.json()['access_token']}"}
