#!/usr/bin/env bash
# Restaure une sauvegarde faite par scripts/backup.sh.
#
#   ./scripts/restore.sh backups/20261118-120000/env-manager-data-20261118-120000.tar.gz
#
# Remplace le contenu de /app/data dans le conteneur. Les fichiers .env des
# projets ne sont pas touchés : le prochain scan les relira de toute façon.
set -euo pipefail

FICHIER="${1:?Usage : restore.sh <archive.tar.gz[.enc]>}"
CONTAINER="${ENVMGR_CONTAINER:-env-manager}"
[ -s "$FICHIER" ] || { echo "Archive introuvable ou vide : $FICHIER" >&2; exit 1; }

lire() {
  case "$FICHIER" in
    *.enc) openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_PASSPHRASE < "$FICHIER" ;;
    *) cat "$FICHIER" ;;
  esac
}

echo "Restauration de $FICHIER dans $CONTAINER:/app/data…" >&2
lire | docker exec -i "$CONTAINER" sh -c 'rm -rf /app/data/* && tar xzf - -C /app/data'
echo "✓ Restauré." >&2
