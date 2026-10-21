@echo off
cd /d "%~dp0"
where python >nul 2>nul || (echo Instale o Python 3.11+ em python.org e marque "Add to PATH". & pause & exit /b)
where ollama >nul 2>nul || echo AVISO: Ollama nao encontrado. Instale em https://ollama.com
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
rem Coloca esta pasta no PATH do usuario para o comando "claude-hub" funcionar em qualquer lugar
powershell -NoProfile -Command "$p=[Environment]::GetEnvironmentVariable('Path','User'); if(($p -split ';') -notcontains '%~dp0'.TrimEnd('\')){[Environment]::SetEnvironmentVariable('Path',($p.TrimEnd(';')+';'+'%~dp0'.TrimEnd('\')),'User')}"
rem Variavel usada pela skill /local
setx MODEL_HUB "%~dp0." >nul
rem Instala a skill /local no Claude Code
xcopy /e /i /y "skill\local" "%USERPROFILE%\.claude\skills\local" >nul
echo.
echo Pronto! Feche e abra o terminal e digite:  claude-hub
echo Dentro do Claude Code use:  /local
pause
