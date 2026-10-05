#!/bin/bash
# Double-cliquer (macOS) : collecte les dernières données publiées.
cd "$(dirname "$0")" || exit 1
python3 update.py
