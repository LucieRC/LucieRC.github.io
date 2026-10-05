@echo off
rem Double-cliquer (Windows) : ouvre la page Repères FiPu avec le bouton « Actualiser » actif.
cd /d "%~dp0"
py -3 serve.py || python serve.py
pause
