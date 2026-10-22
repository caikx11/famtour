@echo off
cd /d "%~dp0"
rem "py" e o lancador oficial do Python; "python" pode ser so o atalho da Microsoft Store
set PY=py -3
py -3 --version >nul 2>nul || set PY=python
%PY% --version >nul 2>nul || (echo ERRO: Python nao encontrado. Instale em python.org e marque "Add to PATH". & pause & exit /b)
where ollama >nul 2>nul || echo AVISO: Ollama nao encontrado. Instale em https://ollama.com
%PY% -m venv .venv
if not exist ".venv\Scripts\python.exe" (echo ERRO: nao consegui criar o .venv. Veja a mensagem acima. & pause & exit /b)
.venv\Scripts\python -m pip install -r requirements.txt || (echo ERRO ao instalar dependencias. Veja a mensagem acima. & pause & exit /b)
rem Coloca esta pasta no PATH do usuario para o comando "claude-hub" funcionar em qualquer lugar
powershell -NoProfile -Command "$p=[Environment]::GetEnvironmentVariable('Path','User'); if(($p -split ';') -notcontains '%~dp0'.TrimEnd('\')){[Environment]::SetEnvironmentVariable('Path',($p.TrimEnd(';')+';'+'%~dp0'.TrimEnd('\')),'User')}"
rem Otimizacoes do Ollama para RTX 5070 Ti 16 GB + 64 GB RAM (valem tambem para o Ollama da bandeja)
setx OLLAMA_FLASH_ATTENTION 1 >nul
setx OLLAMA_KV_CACHE_TYPE q8_0 >nul
setx OLLAMA_CONTEXT_LENGTH 32768 >nul
setx OLLAMA_NUM_PARALLEL 1 >nul
setx OLLAMA_MAX_LOADED_MODELS 1 >nul
setx OLLAMA_KEEP_ALIVE 30m >nul
rem Variavel usada pela skill /local
setx MODEL_HUB "%~dp0." >nul
rem Instala a skill /local no Claude Code
xcopy /e /i /y "skill\local" "%USERPROFILE%\.claude\skills\local" >nul
xcopy /e /i /y "skill\imagem" "%USERPROFILE%\.claude\skills\imagem" >nul
echo.
echo Se o Ollama ja estava aberto, feche ele na bandeja para aplicar as otimizacoes.
echo Pronto! Feche e abra o terminal e digite:  claude-hub
echo Dentro do Claude Code use:  /local  e  /imagem
pause
