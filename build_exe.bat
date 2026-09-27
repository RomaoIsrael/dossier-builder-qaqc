@echo off
REM Compila Dossier Builder QA/QC como un unico .exe de Windows (no requiere Python instalado).
setlocal

if not exist .venv\Scripts\activate.bat (
    echo [ERROR] No se encontro el entorno virtual .venv. Ejecute primero install.bat
    exit /b 1
)

if not exist assets\icon.ico (
    echo [ERROR] No se encontro assets\icon.ico. Verifique que descargo la version mas reciente del proyecto.
    exit /b 1
)

call .venv\Scripts\activate.bat

pip show pyinstaller >nul 2>nul
if errorlevel 1 (
    echo Instalando PyInstaller...
    pip install pyinstaller
    if errorlevel 1 (
        echo [ERROR] No se pudo instalar PyInstaller. Revise su conexion a internet y vuelva a intentar.
        exit /b 1
    )
)

echo Compilando DossierBuilderQAQC.exe ...
pyinstaller --noconfirm --clean --onefile --windowed ^
    --name DossierBuilderQAQC ^
    --icon assets\icon.ico ^
    --add-data "assets\icon.ico;assets" ^
    --collect-all PySide6 ^
    --collect-submodules fitz ^
    main.py

if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller fallo durante la compilacion. Revise el detalle del error mas arriba
    echo en esta misma ventana ^(suba para verlo^) y comparta ese texto para poder ayudarle.
    exit /b 1
)

if not exist dist\DossierBuilderQAQC.exe (
    echo.
    echo [ERROR] PyInstaller termino pero no se genero dist\DossierBuilderQAQC.exe. Revise el detalle
    echo del error mas arriba en esta misma ventana.
    exit /b 1
)

echo.
echo Listo. El ejecutable quedo en dist\DossierBuilderQAQC.exe
endlocal
