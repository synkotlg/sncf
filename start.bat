@echo off
REM Lancement de RailFine Analytics sous Windows (après installation, voir README.md)
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (
  echo Environnement Python absent : suivez la section Installation du README.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
if not exist frontend\dist\index.html (
  echo Interface non compilee : cd frontend ^&^& npm install ^&^& npm run build
  pause
  exit /b 1
)
start "" http://127.0.0.1:8000
railfine serve
