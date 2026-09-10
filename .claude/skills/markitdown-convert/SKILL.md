---
name: markitdown-convert
description: Convert any document to clean Markdown using Microsoft's MarkItDown library — PDF, DOCX, PPTX, XLSX, HTML, CSV, JSON, XML, ZIP, images (with OCR/EXIF), and audio (with transcription). Use this skill whenever the user attaches a file and asks to "convert it to markdown", "pasarlo a markdown", "usa markitdown", wants a `.md` version of a document, or needs to extract clean text/structure from a PDF, Word, PowerPoint, or Excel file for further analysis (e.g. feeding it into a research workflow, an LLM prompt, or a git-friendly text format). Trigger this even if the user only says "conviértelo" or "extrae el texto" right after attaching a document — that request almost always means run it through MarkItDown, not just read it manually.
---

# MarkItDown Convert

Convierte archivos a Markdown usando la librería `markitdown` de Microsoft, y entrega el resultado como archivo `.md` descargable.

## Por qué usar esta skill en vez de leer el archivo directamente

Leer un PDF o DOCX manualmente (con Read) te da el contenido para razonar sobre él en la conversación, pero **no produce un artefacto reutilizable**. Esta skill guarda una versión `.md` real en disco que el usuario puede versionar en git, pegar en otro sistema, o usar como insumo de un pipeline de investigación. Cuando el usuario pide explícitamente el archivo convertido (no solo un resumen), usa el script — no transcribas el contenido a mano.

## Requisito: entorno con `markitdown` instalado

El proyecto ya trae un entorno virtual en `.venv/` en la raíz del repo con `markitdown[all]` instalado. Antes de convertir, verifica que exista y si no, créalo:

```bash
# Desde la raíz del repo
if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
python -c "import markitdown" 2>/dev/null || pip install -q 'markitdown[all]'
```

Si estás fuera de este repo (otra sesión, otro proyecto) y no hay `.venv`, instala directamente: `pip install 'markitdown[all]'`.

## Uso

Con el entorno activado, ejecuta el script incluido en esta skill:

```bash
python .claude/skills/markitdown-convert/scripts/convert.py <ruta_al_archivo> [directorio_salida]
```

- `directorio_salida` es opcional; por defecto guarda en `./converted/`.
- El script crea `<directorio_salida>/<nombre_original>.md` con el contenido convertido.
- Para varios archivos, invoca el script una vez por archivo (no hace falta un modo batch: la conversión es rápida y así cada resultado se puede inspeccionar antes de entregarlo).

Después de convertir, entrega el `.md` resultante al usuario (con la herramienta de envío de archivos disponible en la sesión) en vez de solo describir el contenido — ese es el punto de la skill.

## Limitaciones conocidas

- **PDFs sin espacios codificados**: algunos PDFs (sobre todo de bases de datos académicas antiguas) no codifican espacios entre palabras como caracteres explícitos, y el extractor subyacente (pdfminer) los infiere por posición de cada glifo. En esos casos el `.md` puede salir con palabras pegadas (`"ScienceoftheTotalEnvironment"`). Esto no es un bug del script: avísale al usuario si lo notas, no intentes "arreglarlo" reescribiendo el texto a mano salvo que te lo pida.
- **Audio**: la transcripción de audio requiere `ffmpeg` instalado en el sistema (no solo el paquete Python). Si no está disponible, la conversión de archivos de audio fallará o dará una advertencia (`pydub` la emite igual al importar markitdown, es inofensiva para el resto de formatos).
- **Archivos muy grandes o escaneados como imagen**: si un PDF es en realidad un escaneo (sin capa de texto), MarkItDown no hace OCR completo por sí solo; el resultado puede venir vacío o casi vacío. En ese caso, considera la skill `pdf` (con OCR) en vez de esta.
