"""Ejemplo minimo de uso de MarkItDown para convertir archivos a Markdown."""

import sys

from markitdown import MarkItDown


def convertir_a_markdown(ruta_archivo: str) -> str:
    md = MarkItDown()
    resultado = md.convert(ruta_archivo)
    return resultado.text_content


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python example_usage.py <ruta_al_archivo>")
        sys.exit(1)

    print(convertir_a_markdown(sys.argv[1]))
