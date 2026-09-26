"""Dialogos secundarios: metadatos, configuracion, resultados de validacion,
nueva subseccion y vista previa de PDF.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.core.dossier_builder import PreviewRow
from app.core.section_suggester import suggest_sections_for_files
from app.core.validator import Severity, ValidationReport
from app.models.project_model import ProjectMetadata, ProjectSettings
from app.models.section_model import SectionNode
from app.services.settings import AppSettings

APP_VERSION = "0.1.0"
APP_AUTHOR_NAME = "Romao Israel Landázuri Balseca"
APP_AUTHOR_COUNTRY = "Ecuador"


class AboutDialog(QDialog):
    """Panel de informacion ('Acerca de'): quien elaboro el programa y version."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Acerca de Dossier Builder QA/QC")
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)

        title = QLabel("Dossier Builder QA/QC")
        title.setStyleSheet("font-weight: 700; font-size: 14pt;")
        layout.addWidget(title)
        layout.addWidget(QLabel(f"Version {APP_VERSION}"))

        layout.addWidget(QLabel(""))

        layout.addWidget(QLabel("Elaborado por:"))
        author_label = QLabel(APP_AUTHOR_NAME)
        author_label.setStyleSheet("font-weight: 600; font-size: 11pt;")
        layout.addWidget(author_label)
        layout.addWidget(QLabel(APP_AUTHOR_COUNTRY))

        layout.addWidget(QLabel(""))
        copyright_label = QLabel(f"© {datetime.now().year} {APP_AUTHOR_NAME}. Todos los derechos reservados.")
        copyright_label.setStyleSheet("color: palette(mid); font-size: 9pt;")
        copyright_label.setWordWrap(True)
        layout.addWidget(copyright_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


_USER_MANUAL_HTML = """
<h1>Manual de Usuario &mdash; Dossier Builder QA/QC</h1>
<p>Esta guia explica, paso a paso, para que sirve cada seccion, boton y menu del
programa. Esta pensada para leerse de una sola vez o consultarse por partes
mientras se trabaja.</p>

<h2>1. Flujo de trabajo general</h2>
<ol>
<li><b>Nuevo proyecto</b>: se crea el proyecto y se pide el nombre y luego la
plantilla PDF (el documento base sobre el que se va a armar el dossier).</li>
<li>Se revisan/editan las <b>secciones</b> detectadas en la plantilla (o se
agregan subsecciones propias).</li>
<li>Se <b>agregan los documentos</b> (PDF) a cada seccion, ya sea manualmente
o con <i>Distribuir documentos (auto)</i>.</li>
<li>Se define el <b>tratamiento de firma</b> de cada documento (conservar
original, aplanar, o automatico).</li>
<li>Se <b>valida</b> el dossier para detectar errores o advertencias antes de
generarlo.</li>
<li>Se <b>genera el dossier</b>: el programa arma un unico PDF final con todo
lo anterior, respetando la plantilla y agregando bookmarks/indice segun la
configuracion.</li>
</ol>
<p>El proyecto completo (secciones, documentos, configuracion, metadatos e
historial de cambios) se guarda en un archivo <code>.dossierproj</code>, que
se puede volver a abrir en cualquier momento con <i>Abrir proyecto</i>, en la
misma computadora o en otra.</p>

<h2>2. Barra de herramientas superior (fila &quot;Proyecto&quot;)</h2>
<ul>
<li><b>Nuevo proyecto</b>: crea un proyecto vacio. Pide el nombre del
proyecto y despues muestra el aviso &quot;Elegir plantilla&quot; antes de abrir
el explorador de archivos, para que se sepa que hay que seleccionar el PDF
base.</li>
<li><b>Abrir proyecto</b>: abre un archivo <code>.dossierproj</code> guardado
previamente (propio o de otra persona/computadora).</li>
<li><b>Guardar</b>: guarda los cambios en el mismo archivo del proyecto
actual. Si el proyecto es nuevo y nunca se guardo, se comporta como
&quot;Guardar como...&quot;.</li>
<li><b>Guardar como...</b>: guarda una copia del proyecto en una ubicacion o
con un nombre distinto.</li>
<li><b>Metadatos</b>: abre el formulario de datos del encabezado (Proyecto,
Pozo, WO, Codigo, Contrato, Bloque, Fecha, Revision, Tipo) y las propiedades
del PDF final (Titulo, Autor, Asunto, Palabras clave). Estos datos tambien
alimentan las variables disponibles para el nombre del archivo de salida
(ej. <code>{codigo}</code>, <code>{pozo}</code>).</li>
<li><b>Configuracion</b>: ajustes del proyecto actual &mdash; DPI y formato de
imagen para aplanar firmas, calidad JPEG, modo de tratamiento de firmas por
defecto, patron de nombre del archivo de salida, carpeta de salida por
defecto, y tres casillas: crear un bookmark por documento individual, generar
un indice automatico, e incluir documentos individuales en ese indice. Ver
la seccion 8 para el detalle de cada opcion.</li>
<li><b>Preferencias</b>: ajustes globales de la aplicacion, validos para
todos los proyectos (no solo el actual): tema claro/oscuro, DPI y calidad
JPEG por defecto, patron de nombre por defecto y carpeta de salida por
defecto para proyectos nuevos.</li>
<li><b>Historial de cambios</b>: abre la tabla con el registro de auditoria
del proyecto (quien hizo que y cuando). Ver seccion 9.</li>
<li><b>Acerca de</b>: muestra el nombre del programa, version, autor y el
aviso de derechos reservados. Junto a este boton esta tambien
<b>Manual de Usuario</b>, que abre esta misma guia.</li>
</ul>

<h2>3. Barra de herramientas inferior (fila &quot;Dossier&quot;)</h2>
<ul>
<li><b>Distribuir documentos (auto)</b>: analiza los nombres de archivo que
se seleccionen y sugiere, para cada uno, a que seccion del dossier
corresponde (comparando palabras clave del nombre contra el titulo de cada
seccion, con sinonimos como MTR/CERT &rarr; CERTIFICADO o RUN &rarr; PULL).
Muestra una tabla con la sugerencia de cada archivo en un menu desplegable
editable: se puede aceptar la sugerencia, cambiarla a otra seccion, o
marcar &quot;(No asignar)&quot; para dejarlo fuera. Nada se agrega hasta
confirmar el dialogo. Es un punto de partida rapido para lotes grandes de
documentos, no un reemplazo del criterio propio.</li>
<li><b>Vista previa del dossier</b>: muestra el indice/esquema final (orden
de secciones y documentos, con numeracion) sin generar el PDF, para revisar
la estructura antes de procesar.</li>
<li><b>Vista previa con miniaturas</b>: igual que la anterior, pero muestra
una miniatura de la primera pagina de cada documento, util para confirmar
visualmente que el archivo correcto esta en el lugar correcto.</li>
<li><b>Validar dossier</b>: revisa el proyecto completo (secciones vacias,
documentos faltantes, configuracion incompleta, etc.) y muestra una lista de
resultados marcados como <b>OK</b>, <b>ADVERTENCIA</b> o <b>ERROR</b>. Si hay
errores, no se puede generar el dossier hasta corregirlos. Las advertencias
si permiten continuar (el programa pregunta si se desea seguir de todas
formas).</li>
<li><b>Generar dossier</b>: corre la validacion automaticamente y, si esta
todo en orden, pide la carpeta de salida y arma el PDF final. Ver seccion 10
para el detalle paso a paso.</li>
</ul>

<h2>4. Panel izquierdo: arbol de secciones</h2>
<p>Muestra la estructura de secciones y subsecciones del dossier, tal como
se detectaron en la plantilla o se agregaron manualmente. Al hacer clic en
una seccion, el panel central muestra los documentos que contiene.</p>
<p><b>Clic derecho sobre una seccion</b> abre un menu con:</p>
<ul>
<li><b>Agregar subseccion</b>: crea una subseccion nueva dentro de la
seleccionada, pidiendo su nombre.</li>
<li><b>Renombrar seccion</b>: cambia el titulo de la seccion seleccionada.</li>
<li><b>Eliminar seccion</b>: borra la seccion (y todo lo que contenga:
subsecciones y documentos). Pide confirmacion.</li>
</ul>
<p>Con una seccion seleccionada, la tecla <b>Suprimir/Backspace</b> tambien
la elimina directamente (con confirmacion).</p>

<h2>5. Panel central: documentos de la seccion</h2>
<p>Lista los documentos PDF que pertenecen a la seccion seleccionada en el
arbol. Se pueden arrastrar y soltar archivos PDF directamente desde el
explorador de Windows sobre esta lista (o sobre una seccion del arbol) para
agregarlos sin usar los botones.</p>

<h3>5.1 Botones (fila 1)</h3>
<ul>
<li><b>+ Agregar documento(s)</b>: abre el explorador de archivos para
seleccionar uno o varios PDF y agregarlos a la seccion actual.</li>
<li><b>+ Agregar carpeta</b>: agrega de una sola vez todos los PDF que
encuentre dentro de una carpeta seleccionada.</li>
<li><b>+ Agregar subseccion</b>: igual que la opcion del menu de clic
derecho del arbol, pero accesible desde este panel.</li>
<li><b>Eliminar seccion</b>: elimina la seccion actualmente seleccionada.</li>
</ul>

<h3>5.2 Botones (fila 2)</h3>
<ul>
<li><b>Subir / Bajar</b>: mueve el/los documento(s) seleccionado(s) una
posicion hacia arriba o abajo dentro de la seccion, para cambiar el orden en
que apareceran en el dossier final.</li>
<li><b>Eliminar</b>: quita el/los documento(s) seleccionado(s) de la
seccion (no borra el archivo original del disco, solo lo saca del
proyecto).</li>
<li><b>Vista previa</b>: abre una vista previa rapida del documento
seleccionado dentro del programa.</li>
<li><b>Tratamiento de firma...</b>: abre un menu para elegir como se debe
tratar la firma del/los documento(s) seleccionado(s):
<ul>
<li><i>Conservar original</i>: el PDF se inserta tal cual, sin modificar.</li>
<li><i>Aplanar para dossier</i>: el documento se convierte en imagen (segun
el DPI/calidad configurados) para &quot;aplanar&quot; la firma y evitar que se
pueda editar o que capas digitales se descoloquen al combinar PDFs.</li>
<li><i>Automatico (segun deteccion de firma)</i>: el programa detecta si el
documento tiene firma y decide por si mismo si aplanarlo o no.</li>
</ul></li>
</ul>

<h3>5.3 Botones (fila 3)</h3>
<ul>
<li><b>Abrir documento</b>: abre el PDF seleccionado con el lector de PDF
predeterminado de Windows.</li>
<li><b>Abrir ubicacion</b>: abre el Explorador de Windows en la carpeta que
contiene el archivo seleccionado.</li>
</ul>

<h3>5.4 Menu de clic derecho sobre un documento</h3>
<p>Incluye todas las acciones anteriores (Vista previa, Abrir documento,
Abrir ubicacion, Tratamiento de firma, Subir, Bajar, Eliminar) y ademas:</p>
<ul>
<li><b>Mover a seccion...</b>: cambia el/los documento(s) seleccionado(s) de
seccion (se elimina de la seccion actual y se agrega a la elegida).</li>
<li><b>Copiar a seccion...</b>: agrega una copia del/los documento(s)
seleccionado(s) a otra seccion, sin quitarlo de la seccion actual.</li>
</ul>
<p>Con uno o varios documentos seleccionados, la tecla <b>Suprimir/Backspace</b>
tambien los elimina directamente de la seccion.</p>

<h2>6. Historial de cambios (auditoria)</h2>
<p>El boton <b>Historial de cambios</b> muestra una tabla con cada accion
importante realizada sobre el proyecto: agregar/mover/eliminar documentos o
secciones, cambiar tratamiento de firma, editar metadatos o configuracion,
guardar el proyecto y generar el dossier. Cada fila muestra fecha y hora,
el <b>usuario de Windows</b> que hizo la accion (se captura automaticamente,
no hay que escribirlo), la accion realizada y un detalle adicional (por
ejemplo, cuantos documentos se agregaron y en que seccion).</p>
<p>Este historial viaja dentro del propio archivo <code>.dossierproj</code>,
asi que si el proyecto se abre en otra computadora o lo edita otra persona,
sus acciones tambien quedan registradas aqui. Se guardan las ultimas 500
acciones; las mas antiguas se descartan automaticamente para no agrandar el
archivo indefinidamente.</p>

<h2>7. Metadatos del proyecto</h2>
<p>Formulario con los campos de encabezado del dossier: <i>Proyecto, Pozo,
WO, Codigo, Contrato, Bloque, Fecha, Revision, Tipo</i>, y las propiedades
que se graban dentro del PDF final: <i>Titulo, Autor, Asunto y Palabras
clave (PDF)</i>. Los primeros nueve campos tambien se pueden usar como
variables (<code>{codigo}</code>, <code>{pozo}</code>, <code>{wo}</code>,
<code>{tipo}</code>, <code>{revision}</code>, <code>{contrato}</code>,
<code>{bloque}</code>) dentro del patron de nombre del archivo de salida,
configurable en &quot;Configuracion&quot; o &quot;Preferencias&quot;.</p>

<h2>8. Configuracion del proyecto</h2>
<ul>
<li><b>DPI de aplanado</b> (150/200/300/450/600): resolucion con la que se
convierten a imagen los documentos marcados para aplanar. Mas alto = firmas
mas nitidas, pero archivo final mas pesado y aplanado mas lento. 450 DPI es
un buen punto de partida; para documentos muy largos puede convenir bajar a
300 DPI.</li>
<li><b>Formato de imagen</b> (jpeg/png): formato interno usado al aplanar.</li>
<li><b>Calidad JPEG (aplanado)</b>: 70% a 100%, solo aplica si el formato es
JPEG.</li>
<li><b>Tratamiento de firmas</b>: modo por defecto para documentos nuevos
(Automatico, Preguntar siempre, o Nunca aplanar). Se puede sobreescribir por
documento desde el panel central.</li>
<li><b>Patron de nombre de salida</b>: plantilla de texto para el nombre del
archivo final, usando las variables de metadatos, ej.
<code>{codigo}-{pozo}-{tipo}-{revision}</code>.</li>
<li><b>Carpeta de salida por defecto</b>: carpeta que se sugiere al generar
el dossier (se puede cambiar en el momento).</li>
<li><b>Crear un bookmark por cada documento insertado</b>: agrega, ademas de
los bookmarks de seccion, uno por cada documento individual, para poder
saltar directo a el desde el panel de marcadores del lector de PDF. No
agrega paginas nuevas.</li>
<li><b>Generar indice automatico</b>: inserta una pagina nueva al inicio del
dossier final con el indice de secciones/subsecciones y su numero de
pagina, ademas del indice que ya pueda tener la plantilla (que no se
modifica).</li>
<li><b>Incluir documentos individuales en el indice</b>: si el indice
automatico esta activado, tambien lista cada documento anidado bajo su
seccion con su pagina de inicio.</li>
</ul>

<h2>9. Preferencias (globales)</h2>
<p>Ajustes que aplican a toda la aplicacion, no a un proyecto en particular:
<b>Tema</b> (Claro/Oscuro), y los valores <b>por defecto</b> con los que
arrancara cada proyecto nuevo: DPI de aplanado, calidad JPEG, patron de
nombre y carpeta de salida. Cambiar estos valores no afecta proyectos ya
existentes, solo a los que se creen despues (o hasta que se cambien
manualmente en &quot;Configuracion&quot;).</p>

<h2>10. Generar el dossier, paso a paso</h2>
<ol>
<li>Se valida el proyecto automaticamente. Si hay <b>errores</b>, se
muestran y no se puede continuar hasta corregirlos. Si solo hay
<b>advertencias</b>, se pregunta si se desea continuar de todas formas.</li>
<li>Se pide la <b>carpeta de salida</b> donde se guardara el PDF final.</li>
<li>Se pide el <b>nombre del archivo</b>:
<ul>
<li>Si es la <b>primera vez</b> que se genera este proyecto, se sugiere un
nombre segun el patron configurado (editable antes de confirmar).</li>
<li>Si el proyecto <b>ya se genero antes</b>, se muestra el nombre usado la
ultima vez y el numero de generacion, y se pregunta si se desea
<b>mantener ese mismo nombre</b> o <b>cambiarlo</b> (en cuyo caso se abre el
mismo campo de texto editable que en la primera generacion).</li>
</ul></li>
<li>Se muestra una barra de progreso mientras se arma el PDF final (se puede
<b>cancelar</b> en cualquier momento).</li>
<li>Al terminar, el proyecto guarda el numero de generacion, el nombre de
archivo usado y la fecha, y todo queda tambien registrado en el
<b>Historial de cambios</b>, ademas de aparecer en el manifest.json y en el
Reporte de Generacion (PDF) que se guarda junto al dossier final.</li>
</ol>
<p>Los documentos originales que ya tenian firma (carpeta de Originales
firmados) y los documentos ya procesados no se renombran: conservan
exactamente su nombre original en todas las corridas, incluso en una
segunda o tercera generacion del mismo proyecto.</p>

<h2>11. Consejos y atajos</h2>
<ul>
<li><b>Suprimir/Backspace</b> elimina la seccion o los documentos
seleccionados (con confirmacion), sin necesidad de usar el menu ni los
botones.</li>
<li>Se puede <b>arrastrar y soltar</b> archivos PDF directamente desde el
Explorador de Windows sobre la lista de documentos o sobre una seccion del
arbol.</li>
<li>Usar <b>Vista previa del dossier</b> o <b>con miniaturas</b> antes de
generar, para revisar que el orden y contenido sean correctos y evitar
correr una generacion completa innecesariamente.</li>
<li>El <b>Historial de cambios</b> es la forma mas rapida de saber que hizo
cada persona que trabajo en el proyecto, especialmente cuando varias
personas lo editan desde distintas computadoras.</li>
</ul>
"""


class UserManualDialog(QDialog):
    """Manual de usuario paso a paso: que hace cada seccion, boton y menu."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manual de Usuario")
        self.resize(760, 640)

        layout = QVBoxLayout(self)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.setHtml(_USER_MANUAL_HTML)
        layout.addWidget(browser)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class AuditLogDialog(QDialog):
    """Historial de cambios del proyecto: quien (usuario del sistema
    operativo) hizo que accion y cuando. Util cuando varias personas, cada
    una desde su propia computadora, editan el mismo proyecto -- el
    historial viaja dentro del propio archivo .dossierproj.
    """

    def __init__(self, audit_log: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Historial de cambios")
        self.resize(720, 420)

        layout = QVBoxLayout(self)

        entries = list(reversed(audit_log))  # mas reciente primero
        layout.addWidget(QLabel(f"{len(entries)} accion(es) registradas (mas reciente primero)."))

        table = QTableWidget(len(entries), 4)
        table.setHorizontalHeaderLabels(["Fecha y hora", "Usuario", "Accion", "Detalle"])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.verticalHeader().setVisible(False)
        for row, entry in enumerate(entries):
            table.setItem(row, 0, QTableWidgetItem(self._format_timestamp(entry.get("timestamp", ""))))
            table.setItem(row, 1, QTableWidgetItem(entry.get("user", "")))
            table.setItem(row, 2, QTableWidgetItem(entry.get("action", "")))
            table.setItem(row, 3, QTableWidgetItem(entry.get("details", "")))
        table.horizontalHeader().setStretchLastSection(True)
        table.resizeColumnsToContents()
        layout.addWidget(table)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    @staticmethod
    def _format_timestamp(value: str) -> str:
        try:
            dt = datetime.fromisoformat(value)
            return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return value


class MetadataDialog(QDialog):
    """Edicion de los campos de encabezado del proyecto (Pozo, WO, Codigo, etc.)."""

    def __init__(self, metadata: ProjectMetadata, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Metadatos del proyecto")
        self.setMinimumWidth(420)

        self._fields: dict[str, QLineEdit] = {}
        form = QFormLayout()
        labels = {
            "proyecto": "Proyecto",
            "pozo": "Pozo",
            "wo": "WO",
            "codigo": "Codigo",
            "contrato": "Contrato",
            "bloque": "Bloque",
            "fecha": "Fecha",
            "revision": "Revision",
            "tipo": "Tipo",
            "titulo_pdf": "Titulo (PDF)",
            "autor_pdf": "Autor (PDF)",
            "asunto_pdf": "Asunto (PDF)",
            "keywords_pdf": "Palabras clave (PDF)",
        }
        for field_name, label in labels.items():
            edit = QLineEdit(getattr(metadata, field_name, ""))
            self._fields[field_name] = edit
            form.addRow(label, edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def result_metadata(self) -> ProjectMetadata:
        data = {name: edit.text() for name, edit in self._fields.items()}
        return ProjectMetadata(**data)


class SettingsDialog(QDialog):
    """Configuracion de procesamiento del proyecto (DPI, firmas, salida, nombre)."""

    def __init__(self, settings: ProjectSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuracion del proyecto")
        self.setMinimumWidth(420)

        form = QFormLayout()

        self.dpi_combo = QComboBox()
        self.dpi_combo.addItems(["150", "200", "300", "450", "600"])
        self.dpi_combo.setCurrentText(str(settings.flatten_dpi))
        form.addRow("DPI de aplanado", self.dpi_combo)

        self.format_combo = QComboBox()
        self.format_combo.addItems(["jpeg", "png"])
        self.format_combo.setCurrentText(settings.flatten_image_format)
        form.addRow("Formato de imagen", self.format_combo)

        self.jpeg_quality_spin = QSpinBox()
        self.jpeg_quality_spin.setRange(70, 100)
        self.jpeg_quality_spin.setValue(settings.flatten_jpeg_quality)
        self.jpeg_quality_spin.setSuffix(" %")
        form.addRow("Calidad JPEG (aplanado)", self.jpeg_quality_spin)

        self.signature_mode_combo = QComboBox()
        self.signature_mode_combo.addItem("Automatico (detectar firmas)", "auto")
        self.signature_mode_combo.addItem("Preguntar siempre", "ask")
        self.signature_mode_combo.addItem("Nunca aplanar", "never")
        index = self.signature_mode_combo.findData(settings.signature_mode)
        self.signature_mode_combo.setCurrentIndex(max(0, index))
        form.addRow("Tratamiento de firmas", self.signature_mode_combo)

        self.naming_edit = QLineEdit(settings.output_naming_pattern)
        form.addRow("Patron de nombre de salida", self.naming_edit)

        self.output_dir_edit = QLineEdit(settings.output_dir)
        form.addRow("Carpeta de salida por defecto", self.output_dir_edit)

        self.doc_bookmarks_checkbox = QCheckBox(
            "Crear un bookmark por cada documento insertado (ademas de los de seccion)"
        )
        self.doc_bookmarks_checkbox.setChecked(settings.create_bookmarks_for_individual_docs)
        form.addRow("", self.doc_bookmarks_checkbox)

        self.auto_index_checkbox = QCheckBox("Generar indice automatico (seccion/subseccion + pagina)")
        self.auto_index_checkbox.setChecked(settings.generate_automatic_index)
        form.addRow("", self.auto_index_checkbox)

        self.include_docs_checkbox = QCheckBox(
            "Incluir documentos individuales en el indice (nombre + pagina de inicio)"
        )
        self.include_docs_checkbox.setChecked(settings.include_documents_in_index)
        form.addRow("", self.include_docs_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel("Variables disponibles: {codigo} {pozo} {wo} {tipo} {revision} {contrato} {bloque}"))
        layout.addWidget(
            QLabel(
                "DPI y calidad JPEG mas altos hacen que las firmas e imagenes aplanadas se vean mas "
                "nitidas dentro del dossier final, a cambio de un archivo de salida mas pesado y un "
                "aplanado un poco mas lento. 450 DPI / 95% es un buen punto de partida para firmas; "
                "para documentos muy grandes (cientos de paginas escaneadas) puede convenir bajar a "
                "300 DPI si el tamano final del PDF es un problema."
            )
        )
        layout.addWidget(
            QLabel(
                "'Crear un bookmark por cada documento' agrega, al arbol de bookmarks del PDF final, "
                "una entrada por cada documento insertado (para poder saltar directo a el desde el "
                "panel de marcadores del lector de PDF), ademas de las de seccion. No crea ninguna "
                "pagina nueva ni modifica el indice de la plantilla.\n\n"
                "El indice automatico (mas abajo) es distinto y opcional: inserta una PAGINA nueva al "
                "comienzo del dossier final, ademas del indice ya existente en la plantilla (que "
                "siempre se respeta sin cambios). Con 'Incluir documentos individuales', esa pagina "
                "tambien lista cada documento anidado bajo su seccion, ej.:\n"
                "   1.1 DIAGRAMAS MECANICOS ........... 5\n"
                "       Diagrama_Final_Firmado.pdf ..... 7"
            )
        )
        layout.addWidget(buttons)

    def apply_to(self, settings: ProjectSettings) -> ProjectSettings:
        settings.flatten_dpi = int(self.dpi_combo.currentText())
        settings.flatten_image_format = self.format_combo.currentText()
        settings.flatten_jpeg_quality = self.jpeg_quality_spin.value()
        settings.signature_mode = self.signature_mode_combo.currentData()
        settings.output_naming_pattern = self.naming_edit.text() or settings.output_naming_pattern
        settings.output_dir = self.output_dir_edit.text()
        settings.create_bookmarks_for_individual_docs = self.doc_bookmarks_checkbox.isChecked()
        settings.generate_automatic_index = self.auto_index_checkbox.isChecked()
        settings.include_documents_in_index = self.include_docs_checkbox.isChecked()
        return settings


class PreferencesDialog(QDialog):
    """Preferencias globales de la aplicacion (tema, DPI por defecto, etc.),
    validas para todos los proyectos, no solo el actual.
    """

    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferencias")
        self.setMinimumWidth(420)

        form = QFormLayout()

        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Claro", "light")
        self.theme_combo.addItem("Oscuro", "dark")
        index = self.theme_combo.findData(settings.theme)
        self.theme_combo.setCurrentIndex(max(0, index))
        form.addRow("Tema", self.theme_combo)

        self.dpi_combo = QComboBox()
        self.dpi_combo.addItems(["150", "200", "300", "450", "600"])
        self.dpi_combo.setCurrentText(str(settings.default_flatten_dpi))
        form.addRow("DPI de aplanado por defecto", self.dpi_combo)

        self.jpeg_quality_spin = QSpinBox()
        self.jpeg_quality_spin.setRange(70, 100)
        self.jpeg_quality_spin.setValue(settings.default_flatten_jpeg_quality)
        self.jpeg_quality_spin.setSuffix(" %")
        form.addRow("Calidad JPEG por defecto", self.jpeg_quality_spin)

        self.naming_edit = QLineEdit(settings.default_naming_pattern)
        form.addRow("Patron de nombre por defecto", self.naming_edit)

        self.output_dir_edit = QLineEdit(settings.default_output_dir)
        form.addRow("Carpeta de salida por defecto", self.output_dir_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def apply_to(self, settings: AppSettings) -> AppSettings:
        settings.theme = self.theme_combo.currentData()
        settings.default_flatten_dpi = int(self.dpi_combo.currentText())
        settings.default_flatten_jpeg_quality = self.jpeg_quality_spin.value()
        settings.default_naming_pattern = self.naming_edit.text() or settings.default_naming_pattern
        settings.default_output_dir = self.output_dir_edit.text()
        return settings


_SEVERITY_PREFIX = {Severity.OK: "OK", Severity.WARNING: "ADVERTENCIA", Severity.ERROR: "ERROR"}
_SEVERITY_COLOR = {Severity.OK: Qt.darkGreen, Severity.WARNING: Qt.darkYellow, Severity.ERROR: Qt.red}


class ValidationResultsDialog(QDialog):
    """Muestra el resultado de 'Validar dossier': OK / Advertencia / Error por item."""

    def __init__(self, report: ValidationReport, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Resultado de validacion")
        self.resize(620, 480)

        layout = QVBoxLayout(self)

        summary = QLabel(
            f"{len(report.messages)} verificaciones - "
            f"{len(report.warnings)} advertencia(s) - {len(report.errors)} error(es)"
        )
        layout.addWidget(summary)

        listbox = QListWidget()
        for msg in report.messages:
            prefix = _SEVERITY_PREFIX[msg.severity]
            item = QListWidgetItem(f"[{prefix}] {msg.message}")
            item.setForeground(_SEVERITY_COLOR[msg.severity])
            listbox.addItem(item)
        layout.addWidget(listbox)

        if report.can_generate:
            footer = QLabel("Se puede generar el dossier (no hay errores criticos).")
        else:
            footer = QLabel("No se puede generar el dossier: corrija los errores marcados arriba.")
            footer.setStyleSheet("color: red; font-weight: bold;")
        layout.addWidget(footer)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class NewSectionDialog(QDialog):
    """Pide el nombre de una nueva (sub)seccion dinamica."""

    def __init__(self, parent=None, default_name: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Nueva subseccion")
        self.setMinimumWidth(360)

        self.name_edit = QLineEdit(default_name)

        form = QFormLayout()
        form.addRow("Nombre de la subseccion", self.name_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def section_name(self) -> str:
        return self.name_edit.text().strip()


class PdfPreviewDialog(QDialog):
    """Vista previa simple de un PDF: navegacion de paginas y zoom."""

    def __init__(self, pdf_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Vista previa - {pdf_path}")
        self.resize(720, 860)

        self._path = pdf_path
        self._doc: Optional[fitz.Document] = None
        self._page_index = 0
        self._zoom = 1.2

        self.image_label = QLabel("Cargando...")
        self.image_label.setAlignment(Qt.AlignCenter)

        self.page_label = QLabel("")

        prev_btn = QPushButton("< Anterior")
        next_btn = QPushButton("Siguiente >")
        zoom_in_btn = QPushButton("Zoom +")
        zoom_out_btn = QPushButton("Zoom -")
        prev_btn.clicked.connect(self._prev_page)
        next_btn.clicked.connect(self._next_page)
        zoom_in_btn.clicked.connect(self._zoom_in)
        zoom_out_btn.clicked.connect(self._zoom_out)

        nav = QHBoxLayout()
        nav.addWidget(prev_btn)
        nav.addWidget(self.page_label)
        nav.addWidget(next_btn)
        nav.addStretch()
        nav.addWidget(zoom_out_btn)
        nav.addWidget(zoom_in_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(nav)
        layout.addWidget(self.image_label, stretch=1)

        self._open_and_render()

    def _open_and_render(self) -> None:
        try:
            self._doc = fitz.open(self._path)
        except Exception as exc:  # noqa: BLE001
            self.image_label.setText(f"No se pudo abrir el PDF:\n{exc}")
            return
        self._render_current_page()

    def _render_current_page(self) -> None:
        if not self._doc:
            return
        page = self._doc[self._page_index]
        matrix = fitz.Matrix(self._zoom, self._zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
        self.image_label.setPixmap(QPixmap.fromImage(image))
        self.page_label.setText(f"Pagina {self._page_index + 1} / {self._doc.page_count}")

    def _prev_page(self) -> None:
        if self._doc and self._page_index > 0:
            self._page_index -= 1
            self._render_current_page()

    def _next_page(self) -> None:
        if self._doc and self._page_index < self._doc.page_count - 1:
            self._page_index += 1
            self._render_current_page()

    def _zoom_in(self) -> None:
        self._zoom = min(4.0, self._zoom + 0.2)
        self._render_current_page()

    def _zoom_out(self) -> None:
        self._zoom = max(0.4, self._zoom - 0.2)
        self._render_current_page()

    def closeEvent(self, event) -> None:  # noqa: N802 - nombre Qt
        if self._doc:
            self._doc.close()
        super().closeEvent(event)


def flatten_section_options(sections: list[SectionNode]) -> list[tuple[str, str]]:
    """Devuelve pares (etiqueta, section_id) en el mismo orden que el arbol.

    Se usa donde sea que la UI necesite mostrar una lista plana de todas las
    secciones/subsecciones para elegir una (distribucion automatica, mover
    o copiar un documento a otra seccion, etc.).
    """
    options: list[tuple[str, str]] = []
    for root in sections:
        for node in root.iter_all_sections():
            label = f"{node.numbering} {node.title}".strip()
            options.append((label, node.id))
    return options


class AutoDistributeDialog(QDialog):
    """Sugiere, por archivo, la seccion destino segun palabras clave del
    nombre (ver ``app/core/section_suggester.py``), y deja que el usuario
    confirme o corrija cada asignacion antes de agregar los documentos.
    """

    def __init__(self, file_paths: list[str], sections: list[SectionNode], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Distribuir documentos automaticamente")
        self.resize(720, 480)

        self._file_paths = file_paths
        self._section_options = flatten_section_options(sections)
        suggestions = suggest_sections_for_files([Path(p).name for p in file_paths], sections)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Se sugiere una seccion por archivo segun palabras clave en el nombre. "
                "Revise y corrija antes de confirmar; puede dejar 'No asignar' para omitir un archivo."
            )
        )

        self.table = QTableWidget(len(file_paths), 2)
        self.table.setHorizontalHeaderLabels(["Archivo", "Seccion sugerida"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)

        self._combos: list[QComboBox] = []
        for row, path in enumerate(file_paths):
            name_item = QTableWidgetItem(Path(path).name)
            self.table.setItem(row, 0, name_item)

            combo = QComboBox()
            combo.addItem("(No asignar)", None)
            for label, section_id in self._section_options:
                combo.addItem(label, section_id)

            suggestion = suggestions.get(Path(path).name)
            if suggestion is not None:
                index = combo.findData(suggestion.id)
                if index >= 0:
                    combo.setCurrentIndex(index)

            self.table.setCellWidget(row, 1, combo)
            self._combos.append(combo)

        layout.addWidget(self.table)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_assignments(self) -> dict[str, Optional[str]]:
        return {path: combo.currentData() for path, combo in zip(self._file_paths, self._combos)}


class DossierOutlinePreviewDialog(QDialog):
    """Vista previa estructural del dossier: el orden final de paginas de
    plantilla y documentos, calculado sin abrir ni aplanar ningun PDF (para
    poder revisar el orden incluso en dossiers de cientos de paginas antes
    de generar).
    """

    def __init__(self, rows: list[PreviewRow], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Vista previa del dossier (orden estructural)")
        self.resize(760, 560)

        layout = QVBoxLayout(self)

        display_rows = self._collapse_template_runs(rows)
        total_pages = sum(r.page_count or 1 for r in rows)
        layout.addWidget(QLabel(f"{len(rows)} elemento(s) - {total_pages} pagina(s) estimada(s) en total"))

        table = QTableWidget(len(display_rows), 4)
        table.setHorizontalHeaderLabels(["Pagina", "Tipo", "Seccion", "Documento"])
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)

        for row_index, (page_label, kind_label, section_label, doc_label) in enumerate(display_rows):
            table.setItem(row_index, 0, QTableWidgetItem(page_label))
            table.setItem(row_index, 1, QTableWidgetItem(kind_label))
            table.setItem(row_index, 2, QTableWidgetItem(section_label))
            table.setItem(row_index, 3, QTableWidgetItem(doc_label))

        layout.addWidget(table)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    @staticmethod
    def _collapse_template_runs(rows: list[PreviewRow]) -> list[tuple[str, str, str, str]]:
        """Agrupa paginas de plantilla consecutivas en una sola fila, para
        no listar una por una en plantillas de decenas de paginas.
        """
        display: list[tuple[str, str, str, str]] = []
        i = 0
        while i < len(rows):
            row = rows[i]
            if row.kind == "template":
                start = row.start_page
                j = i
                while j < len(rows) and rows[j].kind == "template":
                    j += 1
                end = rows[j - 1].start_page
                page_label = str(start) if start == end else f"{start}-{end}"
                display.append((page_label, "Plantilla", "", f"{j - i} pagina(s) de plantilla"))
                i = j
            else:
                page_count_label = str(row.page_count) if row.page_count is not None else "?"
                display.append((str(row.start_page), "Documento", row.section_label, f"{row.label} ({page_count_label} pag.)"))
                i += 1
        return display


class DossierThumbnailPreviewDialog(QDialog):
    """Vista previa con miniaturas reales: una imagen por cada pagina de la
    plantilla y por la primera pagina de cada documento, en el orden final
    del dossier. No renderiza el dossier completo pagina por pagina (seria
    demasiado lento en dossiers de cientos de paginas); cada documento se
    representa con su primera pagina, que basta para verificar visualmente
    el orden y que el archivo correcto quedo en cada seccion.
    """

    _THUMB_WIDTH = 120
    _THUMB_HEIGHT = 156
    _COLUMNS = 5

    def __init__(self, rows: list[PreviewRow], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Vista previa del dossier (miniaturas)")
        self.resize(820, 680)

        outer_layout = QVBoxLayout(self)
        outer_layout.addWidget(
            QLabel(f"{len(rows)} elemento(s) - se muestra la primera pagina de cada documento")
        )

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        grid = QGridLayout(container)
        grid.setSpacing(10)

        open_docs: dict[str, Optional[fitz.Document]] = {}

        def get_source_doc(path: str) -> Optional[fitz.Document]:
            if path not in open_docs:
                try:
                    open_docs[path] = fitz.open(path)
                except Exception:  # noqa: BLE001 - un archivo movido/danado no debe romper la vista previa
                    open_docs[path] = None
            return open_docs[path]

        for index, row in enumerate(rows):
            cell = QWidget()
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(2, 2, 2, 2)

            image_label = QLabel()
            image_label.setAlignment(Qt.AlignCenter)
            image_label.setFixedSize(self._THUMB_WIDTH, self._THUMB_HEIGHT)
            image_label.setStyleSheet("border: 1px solid #999999; background-color: white;")

            qpixmap = self._render_thumbnail(row, get_source_doc)
            if qpixmap is not None:
                image_label.setPixmap(
                    qpixmap.scaled(
                        self._THUMB_WIDTH,
                        self._THUMB_HEIGHT,
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    )
                )
            else:
                image_label.setText("(sin vista\nprevia)")

            caption_text = f"pag. {row.start_page}"
            if row.kind == "doc" and row.section_label:
                caption_text += f" - {row.section_label}"
            caption_text += f"\n{row.label}"
            caption = QLabel(caption_text)
            caption.setAlignment(Qt.AlignCenter)
            caption.setWordWrap(True)
            caption.setFixedWidth(self._THUMB_WIDTH)

            cell_layout.addWidget(image_label)
            cell_layout.addWidget(caption)
            grid.addWidget(cell, index // self._COLUMNS, index % self._COLUMNS)

        for doc in open_docs.values():
            if doc is not None:
                doc.close()

        scroll.setWidget(container)
        outer_layout.addWidget(scroll, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        outer_layout.addWidget(buttons)

    def _render_thumbnail(self, row: PreviewRow, get_source_doc) -> Optional[QPixmap]:
        if not row.source_path or not Path(row.source_path).exists():
            return None
        doc = get_source_doc(row.source_path)
        if doc is None or not (0 <= row.source_page_index < doc.page_count):
            return None
        try:
            page = doc[row.source_page_index]
            zoom = self._THUMB_WIDTH / max(page.rect.width, 1.0)
            matrix = fitz.Matrix(zoom, zoom)
            rendered = page.get_pixmap(matrix=matrix, alpha=False)
            image = QImage(rendered.samples, rendered.width, rendered.height, rendered.stride, QImage.Format_RGB888)
            return QPixmap.fromImage(image)
        except Exception:  # noqa: BLE001 - una pagina irrenderizable no debe romper la vista previa
            return None
