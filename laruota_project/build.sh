#!/usr/bin/env bash
# Exit on error
set -o errexit

# Installa le dipendenze
pip install -r requirements.txt

# Raccoglie i file statici (CSS, Immagini) in una cartella unica
python manage.py collectstatic --no-input

# Applica le migrazioni al database
python manage.py migrate