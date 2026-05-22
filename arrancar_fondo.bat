@echo off
title REPOSITORIO ANTIGRAVITY - CONTROL CENTRAL
cd /d "%~dp0"

echo Iniciando motores de la Firma Cuantitativa...
echo -----------------------------------------------------

:: 1. Arranca el supervisor unico de agentes
echo Desplegando worker agentic unificado...
start "ANTIGRAVITY WORKER" cmd /k python -m antigravity.worker

:: 2. Arranca tu Interfaz Web (Dashboard)
echo Levantando Sede Central Web...
start "INTERFAZ WEB" cmd /k python -m streamlit run app.py

echo -----------------------------------------------------
echo Worker y dashboard activos.
echo Dashboard: http://localhost:8501
pause
