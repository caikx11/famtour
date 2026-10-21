@echo off
if not exist "%~dp0.venv\Scripts\python.exe" (echo Rode primeiro o instalar.bat & pause & exit /b)
cd /d "%~dp0"
rem Contexto maior: o Claude Code precisa de bastante memoria de conversa
set OLLAMA_CONTEXT_LENGTH=32768
tasklist | find /i "ollama" >nul || start "" /min ollama serve
start "" http://localhost:4000
rem Se o hub ja estiver rodando (ex: aberto pelo claude-hub), so abre o painel
curl -s -o nul http://localhost:4000/api/estado && exit /b
.venv\Scripts\python hub.py
pause
