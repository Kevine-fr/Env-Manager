"""Les dépendances qui gardent l'accès admin ne redescendent pas sous leur correctif.

PyJWT 2.7.0 était épinglé depuis la création du projet : quinze avis de
sécurité publiés depuis (dont GHSA-pxh4-856f-4h89), corrigés entre 2.13.0 et
2.15.0. PyJWT vérifie chaque jeton de /api : une version vulnérable ici, c'est
la porte du tableau de bord — et de tous les secrets du VPS.
"""
from pathlib import Path

import jwt

MINIMUM = {"pyjwt": (2, 15, 0)}


def _version(texte: str) -> tuple[int, ...]:
    return tuple(int(p) for p in texte.split(".")[:3])


def test_requirements_epingle_une_version_corrigee():
    lignes = (Path(__file__).resolve().parent.parent / "requirements.txt").read_text().splitlines()
    epingles = {
        nom.strip().lower(): version.strip()
        for nom, _, version in (l.partition("==") for l in lignes if "==" in l and not l.startswith("#"))
    }
    for paquet, minimum in MINIMUM.items():
        assert paquet in epingles, f"{paquet} n'est plus épinglé"
        assert _version(epingles[paquet]) >= minimum, f"{paquet}=={epingles[paquet]} < {minimum}"


def test_la_version_installee_est_corrigee():
    assert _version(jwt.__version__) >= MINIMUM["pyjwt"]
