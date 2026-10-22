"""Servidor MCP de literatura científica en acceso abierto.

Expone a Claude herramientas para buscar artículos, localizar versiones legales
de acceso abierto, descargar PDF, leer texto completo de PubMed Central y
generar referencias APA 7.

Ejecución (transporte stdio, el que usa Claude Desktop):
    python open_access_server.py

Variables de entorno:
    OA_EMAIL         Correo de contacto (obligatorio para Unpaywall; recomendado para OpenAlex).
    OA_DOWNLOAD_DIR  Carpeta donde se guardan los PDF (por defecto ~/articulos_oa).
"""

from __future__ import annotations

import functools
from typing import Any, Literal

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from oa_client import OAClient, OAError

INSTRUCCIONES = """\
Herramientas de literatura científica que usan solo fuentes legales de acceso abierto
(OpenAlex, Unpaywall, Europe PMC, arXiv y Crossref).
Flujo recomendado: buscar_articulos -> localizar_acceso_abierto -> descargar_pdf o
texto_completo_pmc -> referencia_apa. Para biomedicina, buscar_europe_pmc ofrece
mejor cobertura de texto completo. Si un artículo no tiene versión abierta, indique
las vías legales (biblioteca institucional, préstamo interbibliotecario, autor).
"""

mcp = MCPServer("acceso-abierto", instructions=INSTRUCCIONES, version="1.0.0")
_cliente: OAClient | None = None


def cliente() -> OAClient:
    global _cliente
    if _cliente is None:
        _cliente = OAClient()
    return _cliente


def herramienta(fn):
    """Registra una herramienta y convierte los errores esperados en mensajes para Claude."""

    @functools.wraps(fn)
    async def envoltura(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except OAError as exc:
            raise ToolError(str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            raise ToolError(
                f"El servicio respondió {exc.response.status_code} para {exc.request.url}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ToolError(f"Error de red al consultar {exc.request.url}: {exc}") from exc

    return mcp.tool()(envoltura)


@herramienta
async def buscar_articulos(
    consulta: str,
    max_resultados: int = 10,
    desde_anio: int | None = None,
    hasta_anio: int | None = None,
    solo_acceso_abierto: bool = False,
    orden: Literal["relevancia", "citas", "fecha"] = "relevancia",
) -> list[dict[str, Any]]:
    """Busca artículos en OpenAlex (más de 250 millones de obras, todas las disciplinas).

    Devuelve título, autores, año, revista, DOI, número de citas, estado de acceso
    abierto y resumen. Use 'orden' para priorizar relevancia, citas o fecha.
    """
    return await cliente().buscar_openalex(
        consulta, max_resultados, desde_anio, hasta_anio, solo_acceso_abierto, orden
    )


@herramienta
async def buscar_europe_pmc(
    consulta: str, max_resultados: int = 10, solo_acceso_abierto: bool = False
) -> list[dict[str, Any]]:
    """Busca literatura biomédica y de ciencias de la vida en Europe PMC.

    Admite la sintaxis de Europe PMC (p. ej. 'TITLE:"microbiota" AND PUB_YEAR:[2020 TO 2025]').
    Los resultados con PMCID y acceso abierto permiten leer el texto completo.
    """
    return await cliente().buscar_europepmc(consulta, max_resultados, solo_acceso_abierto)


@herramienta
async def buscar_arxiv(consulta: str, max_resultados: int = 10) -> list[dict[str, Any]]:
    """Busca preprints en arXiv (física, matemáticas, informática, estadística, etc.)."""
    return await cliente().buscar_arxiv(consulta, max_resultados)


@herramienta
async def obtener_metadatos(doi: str) -> dict[str, Any]:
    """Obtiene los metadatos completos de un artículo a partir de su DOI (OpenAlex)."""
    return await cliente().obra_openalex(doi)


@herramienta
async def localizar_acceso_abierto(doi: str) -> dict[str, Any]:
    """Localiza versiones legales de acceso abierto de un DOI.

    Consulta Unpaywall, Europe PMC y OpenAlex, y devuelve las URL de PDF con su
    versión (publicada, aceptada o enviada) y licencia.
    """
    return await cliente().localizar_acceso_abierto(doi)


@herramienta
async def descargar_pdf(doi: str) -> dict[str, Any]:
    """Descarga el PDF de acceso abierto de un DOI en la carpeta OA_DOWNLOAD_DIR.

    Solo descarga desde ubicaciones de acceso abierto registradas; si no existe
    ninguna, devuelve alternativas legales para obtener el artículo.
    """
    return await cliente().descargar_pdf(doi)


@herramienta
async def texto_completo_pmc(pmcid: str, max_caracteres: int = 40000) -> dict[str, Any]:
    """Recupera el texto completo (por secciones) de un artículo de PubMed Central.

    Útil para que Claude lea y analice métodos y resultados. Requiere un PMCID
    (p. ej. 'PMC7029158') obtenido con buscar_europe_pmc.
    """
    return await cliente().texto_completo_pmc(pmcid, max_caracteres)


@herramienta
async def referencia_apa(doi: str, idioma: Literal["es-ES", "en-US"] = "es-ES") -> dict[str, Any]:
    """Genera la referencia bibliográfica en formato APA 7 a partir de un DOI."""
    return await cliente().referencia_apa(doi, idioma)


@herramienta
async def procesar_lista_dois(dois: list[str], descargar: bool = False) -> list[dict[str, Any]]:
    """Comprueba (y opcionalmente descarga) el acceso abierto de una lista de DOI.

    Pensado para revisiones de literatura: admite hasta 100 DOI por llamada y
    devuelve un informe por artículo.
    """
    return await cliente().procesar_lote(dois[:100], descargar)


if __name__ == "__main__":
    mcp.run()
