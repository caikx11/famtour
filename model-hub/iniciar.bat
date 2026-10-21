@echo off
if not exist "%~dp0.venv\Scripts\python.exe" (echo Rode primeiro o instalar.bat & pause & exit /b)
cd /d "%~dp0"
rem Contexto maior: o Claude Code precisa de bastante memoria de conversa
set OLLAMA_CONTEXT_LENGTH=32768
tasklist | find /i "ollama" >nul || start "" /min ollama serve
start "" http://localhost:4000
.venv\Scripts\python hub.py
