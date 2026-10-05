#!/bin/bash
# Double-cliquer (macOS) : ouvre le portail FiPu (Repères, Veille, Données) dans le navigateur.
cd "$(dirname "$0")/portail-fipu" || exit 1
python3 serve.py
