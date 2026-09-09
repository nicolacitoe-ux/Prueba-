# Prueba-

## MarkItDown

Este repositorio incluye [MarkItDown](https://github.com/microsoft/markitdown), la utilidad de Microsoft para convertir diversos formatos de archivo (PDF, Word, PowerPoint, Excel, imágenes, audio, HTML, CSV, JSON, XML, ZIP, entre otros) a Markdown.

### Instalación

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Uso

```bash
python example_usage.py ruta/al/archivo.pdf
```

O directamente en Python:

```python
from markitdown import MarkItDown

md = MarkItDown()
resultado = md.convert("archivo.docx")
print(resultado.text_content)
```
