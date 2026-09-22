@echo off
REM Instala Dossier Builder QA/QC en un entorno virtual local (Windows).
setlocal

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] No se encontro Python en el PATH. Instale Python 3.10 o superior desde https://www.python.org/downloads/
    exit /b 1
)

echo Creando entorno virtual en .venv ...
python -m venv .venv
if errorlevel 1 (
    echo [ERROR] No se pudo crear el entorno virtual.
    exit /b 1
)

echo Activando entorno virtual e instalando dependencias...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo Instalacion completa. Use run.bat para iniciar la aplicacion.
endlocal
