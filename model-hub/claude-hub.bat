@echo off
if not exist "%~dp0.venv\Scripts\python.exe" (echo Rode primeiro o instalar.bat & pause & exit /b)
rem Comando global: digite "claude-hub" em qualquer terminal.
rem Liga Ollama + hub se precisar e abre o Claude Code passando pelo hub.
set "HUB=%~dp0"
set OLLAMA_CONTEXT_LENGTH=32768
tasklist | find /i "ollama" >nul || start "" /min ollama serve
curl -s -o nul http://localhost:4000/api/estado || (
  start "Model Hub" /min "%HUB%.venv\Scripts\python.exe" "%HUB%hub.py"
  timeout /t 4 /nobreak >nul
)
set ANTHROPIC_BASE_URL=http://localhost:4000
claude %*
