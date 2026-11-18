"""Les garde-fous d'écriture : jamais hors du dossier deploy, jamais un non-.env."""
from __future__ import annotations

import pytest

from app.env_io import EnvIOError, resolve_env_path, update_variable


@pytest.mark.parametrize(
    "projet, fichier, code",
    [
        ("Tea-Server", "../etc/passwd", 400),
        ("Tea-Server", "/etc/passwd", 400),
        ("..", "../.env", 400),
        ("Tea-Server", "Titi-App/.env.production", 400),
        ("Tea-Server", "Tea-Server/.env.example", 400),
        ("Tea-Server", "Tea-Server/composer.json", 400),
        ("Tea-Server", "Tea-Server/.env.absent", 404),
    ],
)
def test_chemins_refuses(deploy, projet, fichier, code):
    with pytest.raises(EnvIOError) as err:
        resolve_env_path(projet, fichier)
    assert err.value.status_code == code


def test_lien_symbolique_hors_deploy_refuse(deploy, tmp_path):
    dehors = tmp_path / "secret.env"
    dehors.write_text("X=1\n")
    (deploy / "Tea-Server" / ".env.lien").symlink_to(dehors)
    with pytest.raises(EnvIOError) as err:
        resolve_env_path("Tea-Server", "Tea-Server/.env.lien")
    assert err.value.status_code == 403


@pytest.mark.parametrize("cle", ["", "1ABC", "A-B", "A B", "A=B"])
def test_cles_invalides(deploy, cle):
    with pytest.raises(EnvIOError):
        update_variable("Tea-Server", "Tea-Server/.env", cle, "x")
