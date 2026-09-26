# Dossier Builder QA/QC

Generador de dossiers de calidad (QA/QC) en PDF: toma una **plantilla** con
portada, índice, páginas separadoras y bookmarks, permite insertar los
documentos de cada sección (agregarlos, reordenarlos, eliminarlos), aplana
de forma segura los documentos con firma digital/electrónica, y genera el
PDF final reconstruyendo automáticamente los bookmarks — sin tener que
imprimir manualmente los PDF firmados y volver a armar el dossier a mano.

100% offline: no se envía ningún documento a internet ni a servicios en la
nube. Todo el procesamiento ocurre en el equipo local.

## Estado del proyecto: MVP

Esta es la primera versión funcional (MVP), tal como se pidió: cargar
plantilla, ver secciones (árbol de bookmarks), agregar/reordenar/eliminar
documentos por sección, marcar tratamiento de firma, generar el dossier
final con bookmarks reconstruidos, guardar/abrir proyecto y validación
básica con barra de progreso. Ver [Roadmap](#roadmap--fase-2) para lo que
falta.

---

## Índice

- [Cómo funciona (resumen del flujo)](#cómo-funciona-resumen-del-flujo)
- [Firmas digitales: qué hace y qué NO hace esta herramienta](#firmas-digitales-qué-hace-y-qué-no-hace-esta-herramienta)
- [Arquitectura](#arquitectura)
- [Decisiones técnicas](#decisiones-técnicas)
- [Instalación (Windows)](#instalación-windows)
- [Ejecutar](#ejecutar)
- [Compilar a .exe](#compilar-a-exe)
- [Estructura de carpetas de salida](#estructura-de-carpetas-de-salida-al-generar-un-dossier)
- [Proyecto de ejemplo](#proyecto-de-ejemplo)
- [Tests](#tests)
- [Roadmap / Fase 2](#roadmap--fase-2)
- [Limitaciones conocidas del MVP](#limitaciones-conocidas-del-mvp)

---

## Cómo funciona (resumen del flujo)

1. **Cargar plantilla**: se selecciona el PDF de plantilla (portada + índice
   + páginas separadoras). La aplicación lee sus bookmarks existentes
   (`Document.get_toc()` de PyMuPDF) y construye el árbol de secciones y
   subsecciones a partir de ellos — **no asume una cantidad fija de
   páginas**, se adapta a cualquier plantilla que tenga bookmarks.
2. **Agregar documentos** a cada sección desde el árbol lateral: se
   detectan automáticamente páginas, tamaño y presencia de firma digital.
3. **Reordenar / eliminar** documentos dentro de cada sección (arrastrar
   con el mouse o botones Subir/Bajar).
4. **Marcar tratamiento de firma** por documento: Conservar original /
   Aplanar para dossier / Automático (según se haya detectado firma).
5. **Validar dossier**: revisa plantilla, archivos faltantes/dañados/con
   contraseña, secciones vacías, nombres duplicados, documentos firmados,
   etc. Clasifica cada hallazgo como OK / Advertencia / Error. Con errores
   críticos, no se puede generar.
6. **Generar dossier**: en un hilo aparte (no congela la interfaz),
   - aplana (rasteriza) los documentos marcados para aplanado, guardando
     antes una copia de respaldo del original firmado;
   - ensambla el PDF final insertando cada documento inmediatamente
     después de la página separadora de su sección;
   - reconstruye los bookmarks calculando la nueva página de cada sección
     tras las inserciones;
   - aplica metadatos (título, autor, código, pozo, etc.);
   - guarda el PDF final, un `manifest.json` con SHA-256 de cada archivo
     (trazabilidad) y un reporte de generación en PDF.

## Firmas digitales: qué hace y qué NO hace esta herramienta

Esto es importante y se pidió explícitamente que quedara claro:

- Una **firma digital criptográfica** (PAdES, PKCS#7 con `/ByteRange`,
  certificado, etc.) es válida solo mientras los bytes exactos del PDF
  firmado no cambien. Al combinar/insertar ese PDF dentro de otro documento,
  esa validez criptográfica **se pierde siempre**, la haga quien la haga y
  con la herramienta que sea. Esto no es una limitación de esta aplicación:
  es cómo funciona la firma digital en PDF.
- Lo que **sí** se puede preservar es la **apariencia visual** de la firma
  (el sello/imagen/texto que se ve en la página). Para eso, el "aplanado"
  (`app/core/flattener.py`) renderiza cada página del PDF firmado a una
  imagen de alta resolución (150/200/300/400 DPI configurable) y reconstruye
  un PDF nuevo, visualmente idéntico, ya sin objetos de firma ni texto
  editable. Esto reemplaza el paso manual de "imprimir a PDF" que se hacía
  antes, con el mismo resultado pero automático y con mejor trazabilidad.
- **El PDF original firmado nunca se modifica ni se sobrescribe.** Cuando
  un documento se marca para aplanar, la aplicación guarda una copia intacta
  del original en `00_ORIGINALES_FIRMADOS/` antes de generar la versión
  plana en `01_DOCUMENTOS_PROCESADOS/`. Si alguna vez se necesita verificar
  la firma criptográfica original, debe hacerse sobre ese archivo de
  respaldo, con una herramienta de validación de firmas PDF (Adobe Acrobat,
  DSS de la UE, etc.) — esta aplicación **no valida** la firma
  criptográficamente, solo **detecta su presencia** para decidir si conviene
  aplanar (`app/core/signature_detector.py`: busca widgets `/FT /Sig`,
  objetos con `/ByteRange`, etc.).
- Antes de aplanar, la interfaz muestra siempre el aviso: *"Este documento
  contiene una firma digital. Para incluirlo en el dossier se generará una
  representación plana. El archivo original firmado permanecerá sin
  modificaciones."*

## Arquitectura

```
app/
    main.py                 Punto de entrada (crea QApplication + MainWindow)

    ui/
        main_window.py       Ventana principal: arbol de secciones, lista de
                              documentos, toolbar, generacion en QThread
        dialogs.py            Metadatos, configuracion, preferencias, resultados
                              de validacion, nueva subseccion, vista previa PDF/
                              estructural/miniaturas, distribucion automatica
        widgets.py            SectionTreeWidget, DocumentListWidget (drag&drop)
        theme.py               Hoja de estilos QSS para el tema oscuro/claro

    core/
        project.py            Crear/guardar/abrir/duplicar proyectos (JSON)
        pdf_engine.py          Apertura de PDF, TOC/bookmarks, insercion de
                              paginas, guardado (envoltorio sobre PyMuPDF)
        bookmark_manager.py    Construccion del arbol desde bookmarks y
                              reconstruccion de la TOC del dossier final
        signature_detector.py  Deteccion de firmas (widgets /Sig, ByteRange)
        flattener.py           Aplanado/rasterizado de PDF firmados
        validator.py           Validacion previa (OK / Advertencia / Error)
        section_suggester.py    Sugerencia de seccion por nombre de archivo
        dossier_builder.py      Orquestador: ensambla, aplana, reconstruye
                              bookmarks, guarda, genera manifest y reporte;
                              tambien la vista previa estructural rapida

    models/
        project_model.py       Project, ProjectMetadata, ProjectSettings
        section_model.py        SectionNode (arbol de secciones)
        document_model.py       DocumentItem, SignatureTreatment, DocumentStatus

    services/
        database.py            Indice SQLite de proyectos recientes/generaciones
        settings.py             Configuracion global de la app (JSON en AppData)
        logger.py               Logging a archivo (dossierbuilder.log) + consola

    utils/
        paths.py                Rutas estandar (AppData, temporales)
        hashing.py               SHA-256 por bloques
        tempfiles.py             Carpeta temporal de una generacion
        naming.py                Renderizado del patron de nombre de salida

tests/                          Pruebas (pytest) de cada modulo de app/core
examples/
    build_example_project.py    Genera un proyecto de ejemplo end-to-end
    example_project/             (se crea al ejecutar el script anterior)
```

### Flujo de datos de una generación

```
Project (plantilla + arbol de secciones con documentos)
    -> validator.validate_project()            -> ValidationReport
    -> DossierBuilder.generate()
        -> flattener.flatten_pdf() por cada doc marcado para aplanar
        -> pdf_engine: copia plantilla + inserta cada documento en orden
        -> bookmark_manager.build_toc_for_document()  -> nueva TOC
        -> pdf_engine.set_toc() / set_metadata() / save_document()
        -> manifest.json + Reporte_Generacion.pdf (SHA-256, totales, avisos)
```

## Decisiones técnicas

- **PyMuPDF (fitz) como única librería de manipulación de PDF en el MVP.**
  Cubre todo lo necesario (lectura/escritura, TOC/bookmarks, inserción de
  páginas, render a imagen de alta resolución, metadatos, detección de
  widgets de firma) con una sola dependencia binaria, de instalación simple
  en Windows (wheel precompilado) y buen rendimiento con documentos grandes.
  `pikepdf`/`qpdf` quedan documentados como dependencia opcional de una fase
  posterior para reparación/validación estructural avanzada de PDF, que no
  es necesaria para el flujo del MVP.
- **Proyectos como archivo JSON portable (`.dossierproj`), no como blobs en
  SQLite.** Así el proyecto se puede copiar, versionar con git, revisar a
  mano o enviar por correo sin depender de la base de datos local. Nunca se
  guarda el contenido binario de los PDF, solo referencias (rutas) — tal
  como pide el requerimiento.
- **SQLite como índice local**, no como almacén principal: guarda la lista
  de proyectos recientes y el historial de generaciones (para trazabilidad:
  qué se generó, cuándo, con qué SHA-256), pero el archivo `.dossierproj` es
  siempre la fuente de verdad del proyecto.
- **PySide6** para la interfaz: bindings oficiales de Qt para Python,
  licencia LGPL (a diferencia de PyQt6, GPL/comercial), soporte activo y
  buen resultado en Windows con PyInstaller.
- **QThread** para la generación (no `threading` puro): se integra de forma
  nativa con las señales de Qt (`progress`, `finished_ok`, `failed`) sin
  necesidad de polling ni timers para actualizar la interfaz.
- **Sin dependencias comerciales ni servicios web**: todo el procesamiento
  es local, con librerías open source.

## Instalación (Windows)

Requisitos: Python 3.10 o superior ([python.org](https://www.python.org/downloads/)).

```bat
install.bat
```

Esto crea un entorno virtual en `.venv` e instala las dependencias de
`requirements.txt` (PySide6, PyMuPDF, pytest, pyinstaller).

## Ejecutar

```bat
run.bat
```

o, con el entorno virtual ya activado:

```bat
python main.py
```

## Compilar a .exe

```bat
build_exe.bat
```

Genera `dist\DossierBuilderQAQC.exe`, un único ejecutable que **no requiere
Python instalado** en el equipo destino. Usa PyInstaller con
`--collect-all PySide6` (para incluir los plugins de Qt, como las
plataformas de ventana) y `--collect-submodules fitz`.

## Estructura de carpetas de salida (al generar un dossier)

```
<carpeta de salida elegida>/<Nombre del proyecto>/
    00_ORIGINALES_FIRMADOS/     Copias intactas de los PDF firmados originales
                                 renombradas como "pag {N}_{nombre_original}.pdf"
                                 (N = pagina donde ese documento empieza en el
                                 dossier final; ver mas abajo)
    01_DOCUMENTOS_PROCESADOS/   Versiones aplanadas (rasterizadas) de esos PDF,
                                 con el MISMO nombre que el archivo original
                                 (sin prefijo ni sufijo: solo cambia el
                                 contenido, no el nombre del archivo)
    02_DOSSIER_FINAL/           El PDF final del dossier
    03_REPORTES/
        manifest.json            SHA-256 de cada archivo, totales, avisos,
                                 numero de generacion, pagina de inicio y
                                 rutas (backup/aplanado) de cada documento
        Reporte_Generacion.pdf   Reporte legible de la generacion, incluye
                                 el numero de generacion/revision y el
                                 listado "pag. N  NOMBRE_ARCHIVO.pdf" de
                                 todos los documentos originales
```

El prefijo `pag {N}_` solo puede calcularse **despues** de armar el dossier
completo (recien ahi se sabe en que pagina termino cada documento), asi que
el renombrado ocurre como ultimo paso de la generacion, no al aplanar. Solo
se aplica a la copia de respaldo de `00_ORIGINALES_FIRMADOS/`: la version
aplanada de `01_DOCUMENTOS_PROCESADOS/` siempre conserva el nombre original
tal cual.

## Proyecto de ejemplo

No se incluyen documentos reales del dossier de referencia del cliente (por
confidencialidad). En su lugar, hay un script que genera una plantilla y
documentos **sintéticos** con la misma estructura del caso descrito
(Conciliación de materiales, Certificados de calidad, Anexos):

```bat
python examples\build_example_project.py
```

Esto crea `examples/example_project/proyecto_ejemplo.dossierproj`, listo
para abrirse desde la aplicación (`Abrir proyecto`) y generar el dossier de
ejemplo.

## Tests

```bat
pytest
```

Cubren: extracción y reconstrucción de bookmarks, inserción de páginas,
aplanado (incluyendo páginas rotadas), detección de firma, validación
(archivos faltantes/dañados/con contraseña, secciones vacías, nombres
duplicados), guardado/apertura de proyectos, y una prueba de integración
completa de `DossierBuilder` que arma un dossier con secciones anidadas y
una subsección dinámica, y verifica que cada bookmark quede apuntando a la
página exacta tras las inserciones.

> **Nota sobre este repositorio**: el entorno en el que se generó este
> código no tenía salida a internet para instalar PyMuPDF/PySide6 (política
> de red de la organización), así que los tests no se pudieron ejecutar ahí.
> Están escritos para correr con `pytest` en cualquier máquina con las
> dependencias instaladas (por ejemplo, tras `install.bat`).

## Ya implementado (Fase 2, sobre el MVP inicial)

- **Carga de carpetas completas**: botón "+ Agregar carpeta" busca
  recursivamente todos los `*.pdf` dentro de la carpeta elegida y los agrega
  a la sección seleccionada (`MainWindow.add_documents_from_folder`).
- **Sugerencia automática de sección por nombre de archivo**
  (`app/core/section_suggester.py`): compara palabras clave del nombre del
  archivo contra el título de cada sección (con sinónimos de jerga QA/QC:
  MTR/CERT → certificado, GR/REMISION → guía, etc.). Acción de toolbar
  "Distribuir documentos (auto)": se eligen varios PDF sin preasignar
  sección, se muestra una tabla con la sección sugerida por archivo
  (editable con un combo), y solo al confirmar se agregan. La decisión
  final siempre es del usuario — nunca se asigna nada automáticamente sin
  confirmación.
- **Vista previa estructural del dossier** (`DossierBuilder.build_preview_outline`
  + acción de toolbar "Vista previa del dossier"): antes de generar, muestra
  el orden final de páginas de plantilla y documentos con la página
  estimada de inicio de cada uno, **sin abrir ni aplanar ningún PDF** (usa
  el número de páginas ya detectado al agregar cada documento), por lo que
  es instantánea incluso en dossiers de cientos de páginas.

## Ya implementado (Fase 3)

- **Índice automático con paginación** (`DossierBuilder._insert_automatic_index`,
  opción "Generar índice automático" en Configuración del proyecto): genera
  una página de índice (sección/subsección + número de página) y la inserta
  al comienzo del dossier final, **además** del índice existente de la
  plantilla (que no se toca). Resuelve la referencia circular
  "el índice necesita los números de página finales, pero insertarlo cambia
  esos números" calculando primero cuántas páginas de índice se necesitan
  (depende solo de la cantidad de entradas, no de los números en sí),
  desplazando las posiciones ya calculadas por esa cantidad, y recién ahí
  dibujando el índice con los números definitivos — con una salvaguarda que
  re-renderiza si la estimación llegara a no coincidir con el resultado real.
- **Vista previa con miniaturas reales** (acción de toolbar "Vista previa con
  miniaturas", `DossierThumbnailPreviewDialog`): renderiza una imagen por
  cada página de la plantilla y por la primera página de cada documento, en
  el orden final del dossier — sin ensamblar ni renderizar el dossier
  completo página por página (inviable en dossiers de cientos de páginas).
- **Tema oscuro / claro** (`app/ui/theme.py`, acción de toolbar
  "Preferencias"): se guarda en la configuración global de la aplicación y
  se aplica de inmediato al cambiarlo, sin reiniciar.

## Ya implementado (mejoras posteriores)

- **Interfaz modernizada**: `app/ui/theme.py` se reescribió con una hoja de
  estilos completa para ambos temas (claro y oscuro) — paleta de colores
  consistente, bordes redondeados, estados hover/focus/pressed, cabeceras de
  tabla diferenciadas, scrollbars finos, y toolbar con íconos nativos de Qt
  (sin depender de archivos de imagen externos).
- **Eliminar secciones y subsecciones**: botón "Eliminar sección" junto al
  árbol de secciones (`MainWindow.remove_section`). Al eliminar una
  subsección dinámica (creada por el usuario) se quita por completo, junto
  con sus documentos. Al eliminar una sección derivada de un bookmark de la
  plantilla, se muestra una advertencia explicando que su página separadora
  física seguirá apareciendo en el dossier final (la app nunca modifica el
  PDF de la plantilla), pero se elimina su marcador y sus documentos del
  proyecto.
- **Arrastrar y soltar archivos PDF** desde el Explorador de Windows: se
  pueden soltar directamente sobre la lista de documentos (se agregan a la
  sección seleccionada) o sobre cualquier sección del árbol (sin necesidad
  de seleccionarla primero). El reordenamiento interno de documentos
  arrastrándolos dentro de la lista se sigue comportando igual que antes.
- **Menú de clic derecho**: en la lista de documentos (vista previa, abrir,
  abrir ubicación, tratamiento de firma, subir/bajar, eliminar) y en el
  árbol de secciones (agregar subsección, **renombrar sección** — nuevo,
  eliminar sección).
- **Fix**: error `source object number out of range` de PyMuPDF al generar
  el dossier. Causa raíz confirmada con traceback real: PyMuPDF puede
  degradar su estado interno (cache de objetos/"graft map") después de
  **muchas llamadas seguidas a `insert_pdf()` sobre el mismo documento de
  destino** que va creciendo (típico en dossiers con varias decenas de
  documentos). Fix: el documento en construcción se guarda y reabre
  automáticamente cada 15 inserciones (`_FLUSH_EVERY_N_INSERTS` en
  `dossier_builder.py`), lo que resetea ese estado interno sin alterar el
  resultado final. Además, cualquier error de bajo nivel de PyMuPDF al
  insertar un documento ahora queda envuelto en un mensaje claro que nombra
  el archivo exacto que falló, en vez de un "Error inesperado" genérico.
  Con ese mensaje se identificó que, en un caso real, el fallo persistía
  para un archivo específico incluso con el flush activo — apuntando a que
  ese PDF en particular tiene una estructura interna dañada (típico en
  PDF escaneados o que ya pasaron por otras herramientas de combinación).
  Fix adicional: `insert_pdf_pages()` ahora reintenta automáticamente tras
  **reparar** (reescribir desde cero) una copia temporal del PDF de origen
  cuando la inserción directa falla, antes de darse por vencido — esto
  suele resolver estructuras xref/objetos rotos sin intervención manual.
- **Trazabilidad de página de inicio por documento**: cada documento
  original queda registrado con la página donde empieza en el dossier
  final:
  - En `manifest.json`, campo `start_page` por documento.
  - En `Reporte_Generacion.pdf`, una sección "Documentos originales (página
    de inicio en el dossier final)" con líneas `pág. 185  NOMBRE_ARCHIVO.pdf`.
  - Opcionalmente **dentro del dossier mismo**: con "Incluir documentos
    individuales en el índice" (en Configuración, junto a "Generar índice
    automático"), el índice automático lista cada documento anidado bajo su
    sección, con su página de inicio.
  - **Archivos originales firmados renombrados**: la copia de respaldo en
    `00_ORIGINALES_FIRMADOS/` queda como `pag {N}_{nombre_original}.pdf`
    (ej. `pag 56_Certificado_API.pdf`), calculado después de armar el
    dossier completo (`DossierBuilder._rename_signed_originals_with_page_numbers`).
    La versión aplanada en `01_DOCUMENTOS_PROCESADOS/` **no** se renombra:
    conserva exactamente el mismo nombre que el archivo original.
    `manifest.json` refleja ambas rutas en `backup_path` y `flattened_path`.
- **Fix: no inventar numeración para bookmarks sin número** (ej. "CONTENIDO",
  típicamente la raíz/matriz del índice de la plantilla, sin numeración
  propia). Antes, `renumber_sections()` — que corre cada vez que se agrega,
  renombra o elimina una sección — renumeraba **todas** las secciones sin
  distinción, pisando el título de nodos como "CONTENIDO" con un número que
  nunca tuvieron. Ahora `renumber_sections()` solo numera las secciones
  **dinámicas** (creadas por el usuario con "+ Agregar subsección"); las que
  vienen de un bookmark de la plantilla —tengan número o no— nunca se
  tocan. `build_section_tree_from_toc()` tampoco sintetiza numeración al
  leer la plantilla por primera vez: se respeta el índice/bookmarks tal
  como están, sin inventar nada.
- **Bookmarks por documento individual, ahora con checkbox**: en
  Configuración, "Crear un bookmark por cada documento insertado" (motor ya
  existente vía `settings.create_bookmarks_for_individual_docs`, nunca
  antes expuesto en la interfaz). Es independiente del índice automático:
  no crea ninguna página nueva, solo agrega una entrada de bookmark por
  documento (anidada bajo su sección) para poder saltar directo a él desde
  el panel de marcadores del lector de PDF.
- **Barra de herramientas en dos filas**: `MainWindow._build_toolbar()` ahora
  usa dos `QToolBar` (una fila para "Proyecto": nuevo/abrir/guardar/guardar
  como/metadatos/configuración/preferencias, y otra para "Dossier":
  distribuir/vista previa/miniaturas/validar/generar) en vez de una sola
  barra larga. Al achicar la ventana, cada fila se ajusta de forma
  independiente y es mucho menos probable que aparezca el botón de
  desborde "»". Cuando sí aparece (ventanas muy angostas), ahora tiene
  fondo y borde propios en `theme.py` (`QToolButton#qt_toolbar_ext_button`)
  para que se vea con claridad también en tema oscuro, en vez de la flecha
  casi invisible de antes.
- **Nombre/código del dossier al generar**: `generate_dossier()` ahora
  pregunta, justo antes de iniciar la generación, con qué nombre o código
  guardar el PDF final (prellenado con el nombre calculado según el patrón
  de nomenclatura configurado, pero editable). `DossierBuilder.generate()`
  acepta un nuevo parámetro opcional `output_filename` que, si se indica,
  reemplaza el nombre calculado automáticamente.
- **Mover o copiar documentos entre secciones**: en el menú de clic derecho
  de la lista de documentos, "Mover a sección..." y "Copiar a sección..."
  permiten reubicar uno o varios documentos seleccionados en cualquier otra
  sección del árbol sin tener que eliminarlos y volver a agregarlos desde
  cero. "Copiar" crea una copia independiente del documento (nuevo id) en
  la sección destino; "Mover" lo reubica conservando su configuración
  (tratamiento de firma, bookmarks, etc.).
- **Tecla Suprimir/Backspace para eliminar**: tanto la lista de documentos
  como el árbol de secciones responden ahora a la tecla Supr (o Retroceso)
  con la selección activa, sin necesidad de usar el botón o el menú
  contextual.
- **Mayor calidad de aplanado de firmas**: DPI por defecto subido de 300 a
  450 (50% mas de resolucion lineal) y calidad JPEG de 90% a 95%, tanto en
  `Configuracion` del proyecto como en `Preferencias` globales (con
  opciones de hasta 600 DPI para casos exigentes). Ahora tambien se puede
  ajustar la calidad JPEG desde la interfaz (antes estaba fija en el
  codigo). Un DPI mas alto produce firmas e imagenes visiblemente mas
  nitidas dentro del dossier final, a cambio de un PDF de salida algo mas
  pesado.
- **Panel "Acerca de"**: nuevo boton con icono de informacion (i) en la
  barra de herramientas que muestra el nombre de quien elaboro el programa
  y la version de la aplicacion (`AboutDialog` en `app/ui/dialogs.py`).
- **Confirmar guardado al cerrar**: la aplicacion ahora recuerda si hay
  cambios sin guardar en el proyecto actual (crear/editar secciones,
  agregar o mover documentos, cambiar configuracion, etc.). Al cerrar la
  ventana con cambios pendientes, pregunta si se desean guardar, descartar
  o cancelar el cierre, en vez de perderlos silenciosamente como antes.
- **Documentos procesados con su nombre original**: la version aplanada en
  `01_DOCUMENTOS_PROCESADOS/` ya no se renombra (antes quedaba como
  `nombre__flat.pdf` y luego `pag {N}_nombre__flat.pdf`); ahora conserva
  exactamente el mismo nombre de archivo que el documento original. Solo la
  copia de respaldo en `00_ORIGINALES_FIRMADOS/` sigue llevando el prefijo
  `pag {N}_`.
- **Fix: renombrado de originales firmados que fallaba en la 2da corrida**
  (y siguientes) sobre la misma carpeta de salida. En Windows,
  `Path.rename()` falla si el archivo destino ya existe (a diferencia de
  Linux/Mac); como el archivo `pag {N}_...` de una corrida anterior ya
  ocupaba ese nombre, el renombrado de la nueva corrida fallaba
  silenciosamente y el backup quedaba sin el prefijo de pagina. Cambiado a
  `Path.replace()`, que sobrescribe el destino de forma segura en
  cualquier sistema operativo.
- **Control de versiones/generaciones del dossier**: el proyecto ahora
  recuerda cuantas veces se genero (`generation_count`) y con que nombre
  se guardo la ultima vez (`last_output_filename`). Al generar un dossier
  que ya se genero antes, la aplicacion pregunta si se desea **mantener el
  mismo nombre** de la ultima generacion o **cambiarlo** (en vez de
  ofrecer directamente un campo de texto en blanco, como en la primera
  generacion). El numero de generacion/revision queda registrado en
  `manifest.json` (`generation_number`) y en `Reporte_Generacion.pdf`
  ("Generacion / revision N.° X de este proyecto"), ademas del historial
  ya existente en el indice SQLite local (`DatabaseService.list_generations`).
- **Copyright en "Acerca de"**: el dialogo de informacion (`AboutDialog`)
  ahora tambien muestra una linea de copyright con el nombre del autor y
  el año actual (calculado automaticamente).
- **Aviso "Elegir plantilla" al crear un proyecto**: despues de escribir el
  nombre del proyecto nuevo, antes de abrir el explorador de archivos, se
  muestra un aviso explicando que el PDF que hay que elegir es la
  *plantilla* del dossier (caratula + indice + paginas separadoras con
  bookmarks), no un documento cualquiera. Antes se abria el explorador
  directamente sin explicar que se esperaba seleccionar ahi.
- **Historial de cambios (quien modifico que)**: el proyecto ahora lleva
  un registro (`audit_log`, dentro del propio `.dossierproj`, asi que viaja
  con el proyecto a cualquier computadora) de cada accion que lo modifica:
  guardar, agregar/eliminar/mover/copiar/reordenar documentos, agregar/
  renombrar/eliminar secciones, cambiar tratamiento de firma, editar
  metadatos o configuracion, y generar el dossier. Cada entrada guarda
  fecha/hora, el **usuario de Windows** de quien hizo el cambio
  (`getpass.getuser()`, automatico, sin que la persona escriba nada) y un
  detalle especifico (ej. "2 documento(s) en '1.1 Certificados'"). Se
  revisa desde el nuevo boton **"Historial de cambios"** en la barra de
  herramientas (`AuditLogDialog`), como una tabla con la entrada mas
  reciente primero. Asi, si dos personas comparten el mismo proyecto desde
  computadoras distintas, cada una queda identificada por sus propios
  cambios, no solo la fecha de la ultima modificacion.
- **Manual de Usuario integrado**: nuevo boton **"Manual de Usuario"** en la
  barra de herramientas, junto a "Acerca de" (`UserManualDialog`). Abre una
  guia paso a paso, dentro de la misma aplicacion, que explica que hace cada
  boton, cada menu de clic derecho y cada dialogo (barra de herramientas,
  panel de secciones, panel de documentos, metadatos, configuracion,
  preferencias, historial de cambios y el flujo completo de generacion del
  dossier), sin necesidad de salir del programa ni leer este README.
- **Panel de miniaturas del dossier completo, por hoja**: nuevo panel fijo a
  la derecha del panel de documentos (`ThumbnailRailWidget`), con una
  miniatura de **cada hoja (pagina)** de cada documento de **todas** las
  secciones, en el orden final del dossier, con barra de desplazamiento
  vertical (un documento de varias paginas aparece como varias miniaturas
  seguidas, "Hoja 1 de 5", "Hoja 2 de 5", etc.). Un control deslizante
  "Tamano" agranda o achica las miniaturas segun la necesidad de la
  pantalla o la preferencia de quien lo usa, y esa preferencia se recuerda
  entre sesiones (`AppSettings.thumbnail_rail_zoom`); las miniaturas se
  renderizan una sola vez a buena resolucion y solo se reescalan al hacer
  zoom, sin volver a abrir los PDF. Al seleccionar una miniatura se
  sincroniza automaticamente la seccion (en el arbol) y el documento (en la
  lista central) correspondientes, y viceversa (seleccion en cascada entre
  los tres paneles).
- **Excluir hojas puntuales de un documento**: en un documento de varias
  paginas, desde el panel de miniaturas se puede excluir (o restaurar) una
  hoja especifica del dossier final sin modificar el archivo original ni
  usar otra herramienta (`DocumentItem.excluded_pages`, nuevo campo del
  modelo). Las hojas excluidas se muestran en gris en el panel y el
  documento en la lista central se marca con "N HOJA(S) EXCLUIDA(S)". Al
  generar, `pdf_engine.insert_pdf_pages` omite esas paginas (y las vistas
  previas del dossier tambien reflejan el conteo real de paginas
  resultante). Si un documento queda con una sola hoja, en su lugar se
  ofrece eliminar el documento completo. Desde el menu de clic derecho de
  una miniatura (o con la tecla Suprimir) tambien se puede eliminar el
  documento completo o agregar otro en la misma seccion.
- **Fix: excluir una hoja ya no borra el documento completo por error**: el
  calculo de "cuantas paginas tiene este documento" para decidir si se
  puede excluir una hoja (o si hay que eliminar el documento entero) ahora
  se toma del panel de miniaturas, que ya abrio el PDF real
  (`_rail_page_count_for_document`), en vez de `doc.page_count`, que podia
  no estar actualizado en documentos agregados de ciertas formas (por
  ejemplo, copiados a otra seccion) y hacia que se confundiera un documento
  de varias paginas con uno de una sola. Ademas, excluir una hoja ahora
  siempre pide confirmacion antes de hacerlo (restaurarla no, porque no
  quita nada del dossier).
- **Indicador de posicion "Hoja N de M"**: arriba del panel de miniaturas,
  igual que en Adobe Acrobat o Foxit, se muestra la posicion de la
  miniatura seleccionada sobre el total de hojas de todo el dossier,
  actualizandose con cada seleccion.
- **Pantalla de bienvenida al iniciar**: al abrir el programa aparece una
  breve pantalla de bienvenida (dibujada en el momento, sin depender de
  ningun archivo de imagen) mientras se prepara la interfaz, y el programa
  se abre automaticamente apenas termina (`app/main.py`, `_show_splash`).

## Roadmap / Fase 4

No implementado todavía, pendiente para una siguiente iteración:

- Soporte multi-idioma (actualmente solo español).
- Validación estructural avanzada de PDF con `pikepdf`/`qpdf` (reparación
  de PDF dañados, análisis más profundo de PAdES).
- Reconocimiento y validación de vigencia de certificados en firmas PAdES.
- Miniaturas de TODAS las páginas de cada documento (hoy solo la primera),
  con carga diferida (lazy) para no saturar la memoria en dossiers enormes.

## Limitaciones conocidas del MVP

- La vista previa es por documento individual, no del dossier completo ya
  ensamblado.
- El reporte de generación en PDF es un resumen simple (texto), no incluye
  gráficos ni miniaturas.
