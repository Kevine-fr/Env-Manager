"""Le contrat des sauvegardes : un fichier, son chemin en dernière ligne.

`docker` est remplacé par un faux qui simule le conteneur avec un dossier
local : aucune vraie machine n'est nécessaire.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

FAUX_DOCKER = r"""#!/usr/bin/env bash
# faux docker : « exec [-i] <conteneur> cmd… » s'exécute dans $FAUX_CONTENEUR
shift  # exec
[ "$1" = "-i" ] && shift
shift  # conteneur
args=()
for a in "$@"; do args+=("${a//\/app\/data/$FAUX_CONTENEUR}"); done
exec "${args[@]}"
"""


def _env(tmp_path: Path, **extra) -> dict:
    binaires = tmp_path / "bin"
    binaires.mkdir(exist_ok=True)
    docker = binaires / "docker"
    docker.write_text(FAUX_DOCKER)
    docker.chmod(0o755)
    conteneur = tmp_path / "conteneur"
    conteneur.mkdir(exist_ok=True)
    env = dict(os.environ)
    env.update(
        PATH=f"{binaires}:{env['PATH']}",
        FAUX_CONTENEUR=str(conteneur),
        BACKUP_DIR=str(tmp_path / "sauvegardes"),
        **extra,
    )
    return env


def _sauver(env) -> Path:
    sortie = subprocess.run(
        ["bash", str(RACINE / "scripts/backup.sh")], env=env, capture_output=True, text=True, check=True
    )
    return Path(sortie.stdout.strip().splitlines()[-1])


def test_sauvegarde_puis_restauration(tmp_path):
    env = _env(tmp_path)
    conteneur = Path(env["FAUX_CONTENEUR"])
    (conteneur / "envs.json").write_text('{"projects": []}')

    archive = _sauver(env)
    assert archive.is_file() and archive.stat().st_size > 0

    (conteneur / "envs.json").write_text("abîmé")
    subprocess.run(["bash", str(RACINE / "scripts/restore.sh"), str(archive)], env=env, check=True)
    assert (conteneur / "envs.json").read_text() == '{"projects": []}'


def test_sauvegarde_chiffree(tmp_path):
    env = _env(tmp_path, BACKUP_PASSPHRASE="phrase-de-test")
    (Path(env["FAUX_CONTENEUR"]) / "envs.json").write_text('{"secret": "x"}')
    archive = _sauver(env)
    assert archive.suffix == ".enc"
    assert b"secret" not in archive.read_bytes()
