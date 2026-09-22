@echo off
REM Compila Dossier Builder QA/QC como un unico .exe de Windows (no requiere Python instalado).
setlocal

if not exist .venv\Scripts\activate.bat (
    echo [ERROR] No se encontro el entorno virtual .venv. Ejecute primero install.bat
    exit /b 1
)

call .venv\Scripts\activate.bat

pip show pyinstaller >nul 2>nul
if errorlevel 1 (
    echo Instalando PyInstaller...
    pip install pyinstaller
)

echo Compilando DossierBuilderQAQC.exe ...
pyinstaller --noconfirm --clean --onefile --windowed ^
    --name DossierBuilderQAQC ^
    --collect-all PySide6 ^
    --collect-submodules fitz ^
    main.py

echo.
echo Listo. El ejecutable quedo en dist\DossierBuilderQAQC.exe
endlocal
