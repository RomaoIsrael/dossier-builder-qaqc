# assets

Recursos estaticos de la aplicacion.

- `icon.ico`: icono de la aplicacion (16/32/48/256 px), elegido por el
  autor del proyecto, usado por `build_exe.bat` (`--icon` + `--add-data`,
  para el .exe generado con PyInstaller) y por `app/main.py`
  (`app.setWindowIcon(...)`, para que tambien aparezca en la barra de
  tareas y la barra de titulo al correr desde el codigo fuente, no solo en
  el .exe compilado).
- `icon_256.png`: la misma imagen suelta en PNG, por si se necesita en
  otro contexto (ej. una pagina web).

Para reemplazar el icono por uno propio, basta con sobreescribir
`icon.ico` (multi-resolucion: 16, 32, 48 y 256 px) con el propio.
