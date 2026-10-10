#!/usr/bin/env bash
# Installation de LUNATIC RADIO LAB (Linux / macOS)
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
"$PY" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ requis (3.12 recommandé)"'
# --system-site-packages : permet d'utiliser SoapySDR / GNU Radio installés par le système
"$PY" -m venv --system-site-packages .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e . --no-deps
echo
echo "Vérification de l'installation :"
python -m lunatic_radio_lab devices || true
python -m lunatic_radio_lab selftest
echo
echo "Installation terminée. Lancement : scripts/run.sh"
echo "Pilotes SDR optionnels : voir docs/GUIDE_SDR.md"
