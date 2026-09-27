@echo off
REM Compila Dossier Builder QA/QC como un unico .exe de Windows (no requiere Python instalado).
REM "enabledelayedexpansion" evita un problema clasico de los .bat: la ruta de
REM Inno Setup contiene un parentesis ("Program Files (x86)"), que rompe un
REM bloque if(...)else(...) si se usa %VAR% en vez de !VAR! para expandirla.
setlocal enabledelayedexpansion

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

REM -- Instalador (opcional): si Inno Setup ya esta instalado, se compila --
REM    automaticamente un DossierBuilderQAQC_Setup.exe a partir del .exe
REM    recien generado. Si no esta instalado, no es un error: el .exe
REM    portable de arriba ya sirve por si solo, el instalador es un extra.
set ISCC=
where ISCC >nul 2>nul
if not errorlevel 1 set ISCC=ISCC
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"

if defined ISCC (
    echo.
    echo Generando instalador con Inno Setup...
    "!ISCC!" installer.iss
    if errorlevel 1 (
        echo [ERROR] Inno Setup fallo al generar el instalador. Revise el detalle mas arriba.
    ) else (
        echo.
        echo Listo. El instalador quedo en installer_output\DossierBuilderQAQC_Setup.exe
    )
) else (
    echo.
    echo (Opcional^) Para generar tambien un instalador (Setup.exe con acceso directo
    echo y desinstalador^), instale Inno Setup ^(gratis^) desde:
    echo     https://jrsoftware.org/isdl.php
    echo y despues abra installer.iss con Inno Setup Compiler y presione Compilar,
    echo o vuelva a correr este mismo build_exe.bat.
)

endlocal
