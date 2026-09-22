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
    01_DOCUMENTOS_PROCESADOS/   Versiones aplanadas (rasterizadas) de esos PDF
    02_DOSSIER_FINAL/           El PDF final del dossier
    03_REPORTES/
        manifest.json            SHA-256 de cada archivo, totales, avisos
        Reporte_Generacion.pdf   Reporte legible de la generacion
```

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

## Roadmap / Fase 4

No implementado todavía, pendiente para una siguiente iteración:

- Soporte multi-idioma (actualmente solo español).
- Validación estructural avanzada de PDF con `pikepdf`/`qpdf` (reparación
  de PDF dañados, análisis más profundo de PAdES).
- Bookmarks individuales por documento configurables desde la UI (el motor
  ya lo soporta vía `settings.create_bookmarks_for_individual_docs`).
- Reconocimiento y validación de vigencia de certificados en firmas PAdES.
- Miniaturas de TODAS las páginas de cada documento (hoy solo la primera),
  con carga diferida (lazy) para no saturar la memoria en dossiers enormes.

## Limitaciones conocidas del MVP

- No hay seguimiento de "cambios sin guardar" (dirty state): cerrar la
  aplicación no pregunta si se quiere guardar el proyecto.
- La vista previa es por documento individual, no del dossier completo ya
  ensamblado.
- El reporte de generación en PDF es un resumen simple (texto), no incluye
  gráficos ni miniaturas.
