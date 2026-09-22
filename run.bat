@echo off
REM Ejecuta Dossier Builder QA/QC usando el entorno virtual creado por install.bat.
setlocal

if not exist .venv\Scripts\activate.bat (
    echo [ERROR] No se encontro el entorno virtual .venv. Ejecute primero install.bat
    exit /b 1
)

call .venv\Scripts\activate.bat
python main.py
endlocal
