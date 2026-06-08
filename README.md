# ENV Manager

Tableau de bord d'administration des secrets `.env` pour un VPS.

Un service **FastAPI** unique et autonome qui :

1. **Scanne** le dossier `deploy` toutes les 30 minutes (planificateur interne APScheduler) et collecte **tous les fichiers `.env`** de chaque projet.
2. **Stocke** l'instantané dans un simple fichier **JSON** (aucune base de données).
3. **Sert une interface web** (admin uniquement) pour **voir, modifier, ajouter et supprimer** les variables — chaque modification est **réécrite dans le vrai fichier `.env`** sur le disque.

---

## Architecture

```
deploy/                      <- monté en lecture/écriture dans le conteneur (/deploy)
├── Faet-Server/.env
├── GesPer-Server/.env
├── Tea-Server/.env, .env.staging
└── ...

env-manager (FastAPI)
├── APScheduler  --(toutes les 30 min)-->  data/envs.json
├── API REST     /api/login, /api/projects, /api/scan, /api/secrets/{update,delete}
└── Frontend     web/  (HTML + JS vanilla, servi en static, même origine = pas de CORS)
```

- **Pas de base de données.** L'état = l'instantané JSON + les fichiers `.env` réels.
- **Authentification :** un seul admin. Login mot de passe → **JWT** (Bearer, HS256).
- **Lecture/écriture `.env` :** `python-dotenv` (`dotenv_values` en lecture brute sans interpolation ; `set_key`/`unset_key` en écriture, ce qui **préserve les commentaires et l'ordre**).

---

## Configuration

Copier `.env.example` → `.env` et renseigner au minimum :

| Variable            | Description                                              | Défaut             |
|---------------------|----------------------------------------------------------|--------------------|
| `ADMIN_PASSWORD`    | **Obligatoire.** Mot de passe admin (choisissez-le fort) | —                  |
| `JWT_SECRET`        | **Obligatoire.** Clé de signature JWT (≥ 16 car.)        | —                  |
| `DEPLOY_HOST_PATH`  | Chemin du dossier `deploy` sur l'hôte (compose)          | `/home/kevine/deploy` |
| `ADMIN_USERNAME`    | Nom d'utilisateur admin                                  | `admin`            |
| `SCAN_INTERVAL_MINUTES` | Intervalle du scan                                   | `30`               |
| `JWT_EXPIRE_HOURS`  | Durée de validité du token                               | `12`               |

Générer un bon secret JWT :

```bash
openssl rand -hex 32
```

---

## Déploiement (Docker Compose, recommandé)

Le service se branche sur votre réseau Docker externe `web` et **ne publie aucun port** par défaut : il est destiné à passer derrière votre reverse proxy Nginx existant.

```bash
# 1. Configurer
cp .env.example .env
nano .env            # ADMIN_PASSWORD, JWT_SECRET, DEPLOY_HOST_PATH

# 2. Lancer
docker compose up -d --build

# 3. Vérifier
docker compose logs -f env-manager
```

Puis ajouter un vhost Nginx (sur le réseau `web`) pointant vers le conteneur :

```nginx
server {
    server_name env.votre-domaine.fr;

    location / {
        proxy_pass http://env-manager:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # TLS via votre certbot habituel
    # listen 443 ssl; ...
}
```

> Le mount `deploy` **doit** être en `rw` (lecture/écriture) — c'est ce qui permet la modification des `.env`.

---

## PWA (installation sur mobile / bureau)

L'interface est une **PWA installable** : une fois servie en **HTTPS**, le navigateur propose « Ajouter à l'écran d'accueil » / « Installer ». Elle s'ouvre alors en plein écran, avec sa propre icône.

- `manifest.json` — métadonnées + icônes (mode `standalone`, thème sombre).
- `sw.js` — service worker qui met en cache **uniquement la coquille statique** (HTML/CSS/JS/icônes). Les routes `/api/*` (qui transportent les secrets) **ne sont jamais mises en cache**.
- Icônes dans `web/icons/` (192/512 standard + maskable, apple-touch, favicons).

> ⚠️ L'installation PWA et le service worker nécessitent un **contexte sécurisé** (HTTPS, ou `localhost` en dev). Derrière votre Nginx + TLS, c'est automatique.
> Si vous modifiez les fichiers du front, incrémentez la constante `CACHE` dans `web/sw.js` pour forcer la mise à jour chez les clients.

---

## Déploiement alternatif (sans Docker)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DEPLOY_ROOT=/home/kevine/deploy ADMIN_PASSWORD=... JWT_SECRET=...
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Le planificateur interne tourne déjà. Si vous préférez un **vrai cron système** plutôt que le scheduler intégré, voir `crontab.example` et `scripts/run_scan.py`.

---

## API

| Méthode | Endpoint                | Auth   | Rôle                                   |
|---------|-------------------------|--------|----------------------------------------|
| POST    | `/api/login`            | —      | `{username,password}` → `{token}`      |
| GET     | `/api/health`           | —      | Santé du service                       |
| GET     | `/api/projects`         | admin  | Instantané JSON complet                |
| POST    | `/api/scan`             | admin  | Force un nouveau scan                  |
| POST    | `/api/secrets/update`   | admin  | `{project,file,key,value}` (créé/maj)  |
| POST    | `/api/secrets/delete`   | admin  | `{project,file,key}`                   |

---

## Sécurité

- Le fichier `data/envs.json` **contient les secrets en clair** → il est créé avec les permissions `0600` et **exclu de Git** (`.gitignore`). Le volume `envmgr_data` reste sur l'hôte.
- **Servez toujours l'interface en HTTPS** (votre Nginx + certbot). Vous pouvez aussi ajouter une couche `.htpasswd` au niveau du proxy comme pour vos autres services.
- Choisissez un `ADMIN_PASSWORD` fort et un `JWT_SECRET` aléatoire.
- Les écritures sont protégées contre le **path traversal** : le projet et le fichier sont validés, le chemin résolu doit rester sous `deploy`, et seuls les vrais fichiers `.env` (pas les `.example`/`.template`) sont modifiables.
