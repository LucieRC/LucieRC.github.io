@echo off
rem Double-cliquer (Windows) : ouvre le portail FiPu (Reperes, Veille, Donnees) dans le navigateur.
cd /d "%~dp0portail-fipu"
py -3 serve.py || python serve.py
pause
