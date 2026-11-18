"""L'API : authentification, lecture et écriture des .env, métriques."""
from __future__ import annotations


def test_sante_publique(client):
    rep = client.get("/api/health")
    assert rep.status_code == 200
    assert rep.json()["status"] == "ok"


def test_version_publique(client):
    assert "version" in client.get("/api/version").json()


def test_les_secrets_exigent_un_jeton(client):
    assert client.get("/api/projects").status_code == 401
    rep = client.get("/api/projects", headers={"Authorization": "Bearer faux"})
    assert rep.status_code == 401


def test_mauvais_mot_de_passe(client):
    rep = client.post("/api/login", json={"username": "admin", "password": "non"})
    assert rep.status_code == 401


def test_connexion_limitee_apres_dix_echecs(client):
    # Bug évité : /api/login se laissait essayer sans limite, alors qu'un
    # seul mot de passe protège tous les secrets du VPS.
    entetes = {"X-Real-IP": "203.0.113.7"}
    for _ in range(10):
        rep = client.post("/api/login", json={"password": "non"}, headers=entetes)
        assert rep.status_code == 401
    rep = client.post(
        "/api/login",
        json={"username": "admin", "password": "mot-de-passe-de-test"},
        headers=entetes,
    )
    assert rep.status_code == 429
    # Une autre adresse n'est pas pénalisée.
    rep = client.post(
        "/api/login",
        json={"username": "admin", "password": "mot-de-passe-de-test"},
        headers={"X-Real-IP": "198.51.100.1"},
    )
    assert rep.status_code == 200


def test_le_limiteur_oublie_les_vieux_echecs():
    from app.main import LimiteurConnexion

    lim = LimiteurConnexion(max_echecs=2, fenetre_s=60)
    lim.echec("ip", maintenant=0)
    lim.echec("ip", maintenant=1)
    assert lim.bloque("ip", maintenant=2)
    assert not lim.bloque("ip", maintenant=100)


def test_scan_ignore_exemples_et_dossiers_exclus(client, jeton):
    snap = client.post("/api/scan", headers=jeton).json()
    chemins = [f["path"] for p in snap["projects"] for f in p["env_files"]]
    assert chemins == ["Tea-Server/.env", "Titi-App/.env.production"]
    assert snap["total_variables"] == 3


def test_modifier_puis_supprimer_une_variable(client, jeton, deploy):
    client.post("/api/scan", headers=jeton)
    rep = client.post(
        "/api/secrets/update",
        headers=jeton,
        json={"project": "Tea-Server", "file": "Tea-Server/.env", "key": "NOUVELLE", "value": "a b"},
    )
    assert rep.status_code == 200
    contenu = (deploy / "Tea-Server" / ".env").read_text()
    assert "# commentaire" in contenu  # les commentaires survivent
    assert "NOUVELLE='a b'" in contenu

    projets = client.get("/api/projects", headers=jeton).json()
    tea = next(p for p in projets["projects"] if p["name"] == "Tea-Server")
    assert tea["variable_count"] == 3

    rep = client.post(
        "/api/secrets/delete",
        headers=jeton,
        json={"project": "Tea-Server", "file": "Tea-Server/.env", "key": "NOUVELLE"},
    )
    assert rep.status_code == 200
    assert "NOUVELLE" not in (deploy / "Tea-Server" / ".env").read_text()


def test_suppression_variable_absente(client, jeton):
    rep = client.post(
        "/api/secrets/delete",
        headers=jeton,
        json={"project": "Tea-Server", "file": "Tea-Server/.env", "key": "ABSENTE"},
    )
    assert rep.status_code == 404


def test_metriques_prometheus(client):
    client.get("/api/health")
    rep = client.get("/metrics")
    assert rep.status_code == 200
    assert "http_requests_total" in rep.text
    assert "http_request_duration_seconds" in rep.text
