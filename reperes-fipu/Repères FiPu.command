#!/bin/bash
# Double-cliquer (macOS) : ouvre la page Repères FiPu avec le bouton « Actualiser » actif.
cd "$(dirname "$0")" || exit 1
python3 serve.py
