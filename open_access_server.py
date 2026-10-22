"""Servidor MCP de literatura científica en acceso abierto.

Expone a Claude herramientas para buscar artículos, localizar versiones legales
de acceso abierto, descargar PDF, leer texto completo de PubMed Central y
generar referencias APA 7. Incluye fuentes de biotecnología (PubMed, UniProt,
KEGG) y organiza PDF y bibliografías por proyecto.

Ejecución (transporte stdio, el que usa Claude Desktop):
    python open_access_server.py

Variables de entorno:
    OA_EMAIL         Correo de contacto (obligatorio para Unpaywall; recomendado para OpenAlex).
    OA_DOWNLOAD_DIR  Carpeta donde se guardan los PDF (por defecto ~/articulos_oa).
    OA_PROYECTOS     Nombres de proyectos separados por ';' (cada uno tiene su carpeta).
    NCBI_API_KEY     Clave opcional de NCBI para aumentar el límite de consultas a PubMed.
"""

from __future__ import annotations

import functools
from typing import Any, Literal

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from oa_client import OAClient, OAError

INSTRUCCIONES = """\
Herramientas de investigación en biotecnología que usan solo fuentes legales de acceso
abierto (OpenAlex, PubMed, Europe PMC, Unpaywall, arXiv, Crossref, UniProt y KEGG).
Flujo recomendado: buscar_pubmed o buscar_articulos -> localizar_acceso_abierto ->
descargar_pdf o texto_completo_pmc -> agregar_a_bibliografia. Para enzimas, proteínas y
rutas metabólicas use buscar_proteinas_uniprot, buscar_kegg y detalle_kegg.
Cuando el usuario trabaje en un proyecto (consulte listar_proyectos), pase su nombre en
el parámetro 'proyecto' para guardar PDF y referencias en la carpeta correspondiente.
Si un artículo no tiene versión abierta, indique las vías legales (biblioteca
institucional, préstamo interbibliotecario, autor de correspondencia).
"""

mcp = MCPServer("acceso-abierto", instructions=INSTRUCCIONES, version="1.1.0")
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
async def descargar_pdf(doi: str, proyecto: str | None = None) -> dict[str, Any]:
    """Descarga el PDF de acceso abierto de un DOI.

    Si se indica 'proyecto', se guarda en la subcarpeta de ese proyecto dentro de
    OA_DOWNLOAD_DIR. Solo descarga desde ubicaciones de acceso abierto registradas;
    si no existe ninguna, devuelve alternativas legales para obtener el artículo.
    """
    return await cliente().descargar_pdf(doi, proyecto)


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
async def procesar_lista_dois(
    dois: list[str], descargar: bool = False, proyecto: str | None = None
) -> list[dict[str, Any]]:
    """Comprueba (y opcionalmente descarga) el acceso abierto de una lista de DOI.

    Pensado para revisiones de literatura: admite hasta 100 DOI por llamada y
    devuelve un informe por artículo. Con 'proyecto', los PDF se guardan en su carpeta.
    """
    return await cliente().procesar_lote(dois[:100], descargar, proyecto)


@herramienta
async def buscar_pubmed(
    consulta: str,
    max_resultados: int = 10,
    desde_anio: int | None = None,
    hasta_anio: int | None = None,
    orden: Literal["relevancia", "fecha"] = "relevancia",
) -> list[dict[str, Any]]:
    """Busca en PubMed (MEDLINE) con la sintaxis de NCBI.

    Admite términos MeSH y etiquetas de campo, p. ej.
    '"Bioreactors"[MeSH] AND lipase[tiab] AND review[pt]'. Devuelve PMID, DOI y PMCID
    (este último permite leer el texto completo con texto_completo_pmc).
    """
    return await cliente().buscar_pubmed(consulta, max_resultados, desde_anio, hasta_anio, orden)


@herramienta
async def buscar_proteinas_uniprot(
    consulta: str,
    organismo: str | None = None,
    solo_revisadas: bool = True,
    max_resultados: int = 10,
) -> list[dict[str, Any]]:
    """Busca proteínas y enzimas en UniProtKB.

    Devuelve accesión, nombre, genes, organismo, números EC, longitud y función.
    'solo_revisadas' limita a Swiss-Prot (anotación curada manualmente).
    Ejemplo: consulta='lipase', organismo='Candida antarctica'.
    """
    return await cliente().buscar_uniprot(consulta, organismo, solo_revisadas, max_resultados)


@herramienta
async def buscar_kegg(
    termino: str,
    base: Literal["enzyme", "pathway", "compound", "reaction", "module", "orthology"] = "enzyme",
    max_resultados: int = 20,
) -> list[dict[str, str]]:
    """Busca enzimas, rutas metabólicas, compuestos, reacciones o módulos en KEGG.

    Use detalle_kegg con el identificador devuelto (p. ej. 'ec:3.1.1.3' o 'map00010').
    """
    return await cliente().buscar_kegg(base, termino, max_resultados)


@herramienta
async def detalle_kegg(identificador: str) -> dict[str, Any]:
    """Obtiene la ficha de una entrada KEGG: nombre, reacción, sustratos, productos y rutas."""
    return await cliente().detalle_kegg(identificador)


@herramienta
async def listar_proyectos() -> list[str]:
    """Lista los proyectos configurados (OA_PROYECTOS) y los que ya tienen carpeta."""
    return cliente().listar_proyectos()


@herramienta
async def agregar_a_bibliografia(
    dois: list[str], proyecto: str, idioma: Literal["es-ES", "en-US"] = "es-ES"
) -> dict[str, Any]:
    """Añade referencias APA 7 a la bibliografía de un proyecto.

    Evita duplicados por DOI y regenera 'referencias_apa.md' en orden alfabético,
    listo para copiar en el documento del proyecto.
    """
    return await cliente().agregar_a_bibliografia(dois, proyecto, idioma)


@herramienta
async def ver_biblioteca(proyecto: str) -> dict[str, Any]:
    """Muestra los PDF descargados y las referencias guardadas de un proyecto."""
    return cliente().ver_biblioteca(proyecto)


if __name__ == "__main__":
    mcp.run()
