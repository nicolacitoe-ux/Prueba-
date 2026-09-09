"""Convierte un archivo a Markdown usando MarkItDown y guarda el resultado.

Uso:
    python convert.py <ruta_al_archivo> [directorio_salida]

Si no se indica directorio de salida, se usa ./converted/
"""

import sys
from pathlib import Path

from markitdown import MarkItDown


def convertir_a_markdown(ruta_archivo: str, dir_salida: str = "converted") -> Path:
    origen = Path(ruta_archivo)
    if not origen.exists():
        raise FileNotFoundError(f"No existe el archivo: {origen}")

    md = MarkItDown()
    resultado = md.convert(str(origen))

    destino_dir = Path(dir_salida)
    destino_dir.mkdir(parents=True, exist_ok=True)
    destino = destino_dir / f"{origen.stem}.md"
    destino.write_text(resultado.text_content, encoding="utf-8")
    return destino


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python convert.py <ruta_al_archivo> [directorio_salida]")
        sys.exit(1)

    dir_salida = sys.argv[2] if len(sys.argv) > 2 else "converted"
    destino = convertir_a_markdown(sys.argv[1], dir_salida)
    print(f"Archivo convertido guardado en: {destino}")
