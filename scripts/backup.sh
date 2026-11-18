#!/usr/bin/env bash
# Sauvegarde des données d'ENV Manager (l'instantané data/envs.json).
#
#   ./scripts/backup.sh                    -> backups/<horodatage>/env-manager-data.tar.gz
#   BACKUP_DIR=/srv/sauvegardes ./scripts/backup.sh
#
# Contrat commun aux dépôts du VPS (le dépôt Infrastructure envoie les
# sauvegardes sur MinIO) : un seul fichier écrit, son chemin en DERNIÈRE
# ligne de la sortie standard, les messages sur la sortie d'erreur.
#
# L'instantané contient en clair tous les secrets des projets du VPS : si
# BACKUP_PASSPHRASE est posée, l'archive est chiffrée (AES-256, openssl), et
# c'est fortement conseillé avant tout envoi hors de la machine.
set -euo pipefail

CONTAINER="${ENVMGR_CONTAINER:-env-manager}"
STAMP="$(date +%Y%m%d-%H%M%S)"
RACINE="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${BACKUP_DIR:-$RACINE/backups/$STAMP}"
mkdir -p "$DEST"
FICHIER="$DEST/env-manager-data-$STAMP.tar.gz"

echo "Sauvegarde de /app/data depuis $CONTAINER…" >&2
if [ -n "${BACKUP_PASSPHRASE:-}" ]; then
  FICHIER="$FICHIER.enc"
  docker exec "$CONTAINER" tar czf - -C /app/data . \
    | openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:BACKUP_PASSPHRASE > "$FICHIER.part"
else
  echo "Attention : BACKUP_PASSPHRASE absente, archive NON chiffrée." >&2
  docker exec "$CONTAINER" tar czf - -C /app/data . > "$FICHIER.part"
fi

# Une archive vide veut dire que le conteneur n'a rien rendu : ne pas la
# faire passer pour une sauvegarde.
if [ ! -s "$FICHIER.part" ]; then
  rm -f "$FICHIER.part"
  echo "Échec : archive vide." >&2
  exit 1
fi
mv "$FICHIER.part" "$FICHIER"
echo "✓ $(du -h "$FICHIER" | cut -f1)" >&2
echo "$FICHIER"
