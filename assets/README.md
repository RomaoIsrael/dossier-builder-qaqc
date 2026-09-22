# assets

Carpeta reservada para recursos estaticos de la aplicacion (icono `.ico`
para el `.exe` generado con PyInstaller, iconos de la interfaz, etc.).

Actualmente vacia: `build_exe.bat` no pasa `--icon` todavia. Para agregar
un icono propio, coloque un archivo `icon.ico` aqui y agregue
`--icon assets\icon.ico` al comando de `pyinstaller` en `build_exe.bat`.
