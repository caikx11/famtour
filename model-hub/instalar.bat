@echo off
cd /d "%~dp0"
where python >nul 2>nul || (echo Instale o Python 3.11+ em python.org e marque "Add to PATH". & pause & exit /b)
where ollama >nul 2>nul || echo AVISO: Ollama nao encontrado. Instale em https://ollama.com
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
echo.
echo Pronto! Agora rode iniciar.bat
pause
