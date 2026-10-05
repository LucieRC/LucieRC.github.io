@echo off
rem Double-cliquer (Windows) : collecte les dernieres donnees publiees.
cd /d "%~dp0"
py -3 update.py || python update.py
pause
