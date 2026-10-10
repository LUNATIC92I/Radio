#!/usr/bin/env bash
# Lancement de LUNATIC RADIO LAB (interface graphique par défaut ; arguments transmis à la CLI)
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -f .venv/bin/activate ]; then . .venv/bin/activate; fi
exec python -m lunatic_radio_lab "$@"
