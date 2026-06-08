#!/usr/bin/env python3
"""Script autonome de scan, à appeler par un cron système si souhaité.

Exemple de crontab (toutes les 30 minutes) :
    */30 * * * * cd /chemin/env-manager && /usr/bin/python3 -m scripts.run_scan >> /var/log/env-manager-scan.log 2>&1

Note : l'application FastAPI lance déjà ce scan automatiquement toutes les
30 min via son scheduler interne. Ce script n'est utile que si vous préférez
piloter la planification avec le cron système plutôt qu'avec l'application.
"""
import sys
from pathlib import Path

# Permet d'exécuter le script depuis n'importe où.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.scanner import run_scan  # noqa: E402


def main() -> int:
    snapshot = run_scan()
    print(
        f"[scan] OK — {snapshot['project_count']} projets, "
        f"{snapshot['total_env_files']} fichiers .env, "
        f"{snapshot['total_variables']} variables -> {snapshot['generated_at']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
