"""Cliente de fuentes académicas de acceso abierto.

Consulta únicamente servicios legales y documentados:

- OpenAlex (https://openalex.org): búsqueda y metadatos bibliográficos.
- Unpaywall (https://unpaywall.org): localización de versiones de acceso abierto por DOI.
- Europe PMC (https://europepmc.org): literatura biomédica y texto completo de PMC.
- arXiv (https://arxiv.org): preprints de física, matemáticas, informática, etc.
- Crossref / doi.org: metadatos y citas formateadas (APA) por negociación de contenido.
- PubMed (NCBI E-utilities): literatura biomédica y biotecnológica indexada en MEDLINE.
- UniProt (https://www.uniprot.org): secuencias, función y números EC de proteínas.
- KEGG (https://www.kegg.jp): enzimas, rutas metabólicas, compuestos y reacciones.

La lógica está separada del servidor MCP para poder probarla de forma aislada.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

OPENALEX_URL = "https://api.openalex.org"
UNPAYWALL_URL = "https://api.unpaywall.org/v2"
EUROPEPMC_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"
ARXIV_URL = "https://export.arxiv.org/api/query"
CROSSREF_URL = "https://api.crossref.org/works"
DOI_URL = "https://doi.org"
EUTILS_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
UNIPROT_URL = "https://rest.uniprot.org/uniprotkb/search"
KEGG_URL = "https://rest.kegg.jp"

# Campos de las fichas KEGG que se devuelven; el resto (GENES, REFERENCE...) es muy extenso.
KEGG_CAMPOS = {
    "ENTRY", "NAME", "DEFINITION", "DESCRIPTION", "CLASS", "SYSNAME", "REACTION",
    "ALL_REAC", "SUBSTRATE", "PRODUCT", "COMMENT", "PATHWAY", "MODULE", "ORTHOLOGY",
    "ENZYME", "FORMULA", "EXACT_MASS", "MOL_WEIGHT", "EQUATION", "RCLASS", "DBLINKS",
}

ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

MAX_PDF_BYTES = 60 * 1024 * 1024
DOI_PATTERN = re.compile(r"10\.\d{4,9}/\S+", re.IGNORECASE)


class OAError(Exception):
    """Error controlado que se devuelve al usuario como mensaje legible."""


def normalizar_doi(doi: str) -> str:
    """Extrae el DOI canónico de una cadena (URL, prefijo 'doi:' o DOI simple)."""
    match = DOI_PATTERN.search(doi.strip())
    if not match:
        raise OAError(f"No se reconoce un DOI válido en: {doi!r}")
    return match.group(0).rstrip(".,;")


def nombre_archivo_seguro(doi: str) -> str:
    """Convierte un DOI en un nombre de archivo sin separadores de ruta."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", doi).strip("._") + ".pdf"


def nombre_proyecto_seguro(proyecto: str) -> str:
    """Valida el nombre de un proyecto para usarlo como carpeta (sin rutas ni '..')."""
    limpio = " ".join(re.sub(r"[^\w\s-]", "", proyecto, flags=re.UNICODE).split())
    if not limpio:
        raise OAError(f"Nombre de proyecto no válido: {proyecto!r}")
    return limpio


def _clave_orden_apa(referencia: str) -> str:
    """Clave de ordenación alfabética de referencias APA (sin tildes ni marcas)."""
    sin_tildes = unicodedata.normalize("NFKD", referencia).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", sin_tildes.lower())


def reconstruir_resumen(indice_invertido: dict[str, list[int]] | None) -> str | None:
    """Reconstruye el resumen de OpenAlex a partir de su índice invertido."""
    if not indice_invertido:
        return None
    posiciones: dict[int, str] = {}
    for palabra, indices in indice_invertido.items():
        for i in indices:
            posiciones[i] = palabra
    return " ".join(posiciones[i] for i in sorted(posiciones))


def _resumir_obra_openalex(obra: dict[str, Any]) -> dict[str, Any]:
    oa = obra.get("open_access") or {}
    fuente = ((obra.get("primary_location") or {}).get("source") or {})
    doi = obra.get("doi")
    return {
        "titulo": obra.get("display_name") or obra.get("title"),
        "doi": normalizar_doi(doi) if doi else None,
        "anio": obra.get("publication_year"),
        "autores": [
            a["author"]["display_name"]
            for a in obra.get("authorships", [])
            if a.get("author", {}).get("display_name")
        ],
        "revista": fuente.get("display_name"),
        "tipo": obra.get("type"),
        "citas": obra.get("cited_by_count"),
        "acceso_abierto": oa.get("is_oa"),
        "estado_oa": oa.get("oa_status"),
        "url_oa": oa.get("oa_url"),
        "openalex_id": obra.get("id"),
        "resumen": reconstruir_resumen(obra.get("abstract_inverted_index")),
    }


def _resumir_europepmc(r: dict[str, Any]) -> dict[str, Any]:
    urls = (r.get("fullTextUrlList") or {}).get("fullTextUrl", [])
    revista = ((r.get("journalInfo") or {}).get("journal") or {}).get("title")
    pmcid = r.get("pmcid")
    return {
        "titulo": r.get("title"),
        "autores": r.get("authorString"),
        "revista": revista or r.get("journalTitle"),
        "anio": r.get("pubYear"),
        "doi": r.get("doi"),
        "pmid": r.get("pmid"),
        "pmcid": pmcid,
        "acceso_abierto": r.get("isOpenAccess") == "Y",
        "citas": r.get("citedByCount"),
        "resumen": r.get("abstractText"),
        "url_pdf": (
            f"https://europepmc.org/articles/{pmcid}?pdf=render"
            if pmcid and r.get("isOpenAccess") == "Y"
            else None
        ),
        "enlaces_texto_completo": [
            {"url": u.get("url"), "formato": u.get("documentStyle"), "acceso": u.get("availability")}
            for u in urls
        ],
    }


def _parsear_arxiv(xml_text: str) -> list[dict[str, Any]]:
    raiz = ET.fromstring(xml_text)
    resultados = []
    for entrada in raiz.findall("atom:entry", ATOM_NS):
        def texto(etiqueta: str) -> str | None:
            nodo = entrada.find(etiqueta, ATOM_NS)
            return " ".join(nodo.text.split()) if nodo is not None and nodo.text else None

        url_pdf = None
        for enlace in entrada.findall("atom:link", ATOM_NS):
            if enlace.get("title") == "pdf":
                url_pdf = enlace.get("href")
        publicado = texto("atom:published")
        resultados.append({
            "titulo": texto("atom:title"),
            "autores": [
                " ".join(a.text.split())
                for a in entrada.findall("atom:author/atom:name", ATOM_NS)
                if a.text
            ],
            "anio": int(publicado[:4]) if publicado else None,
            "arxiv_id": texto("atom:id"),
            "doi": texto("arxiv:doi"),
            "resumen": texto("atom:summary"),
            "url_pdf": url_pdf,
        })
    return resultados


def _resumir_pubmed(doc: dict[str, Any]) -> dict[str, Any]:
    ids = {a.get("idtype"): a.get("value") for a in doc.get("articleids", [])}
    pmcid = ids.get("pmc")
    return {
        "titulo": doc.get("title"),
        "autores": [a["name"] for a in doc.get("authors", []) if a.get("name")],
        "revista": doc.get("fulljournalname") or doc.get("source"),
        "fecha": doc.get("pubdate"),
        "tipo": doc.get("pubtype", []),
        "pmid": doc.get("uid"),
        "doi": ids.get("doi"),
        "pmcid": pmcid,
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{doc.get('uid')}/",
    }


def _resumir_uniprot(e: dict[str, Any]) -> dict[str, Any]:
    desc = e.get("proteinDescription") or {}
    nombre = ((desc.get("recommendedName") or {}).get("fullName") or {}).get("value")
    if not nombre:
        alternativos = desc.get("submissionNames") or [{}]
        nombre = (alternativos[0].get("fullName") or {}).get("value")
    ec = [x.get("value") for x in (desc.get("recommendedName") or {}).get("ecNumbers", [])]
    funcion = [
        t.get("value")
        for c in e.get("comments", [])
        if c.get("commentType") == "FUNCTION"
        for t in c.get("texts", [])
    ]
    acceso = e.get("primaryAccession")
    return {
        "accesion": acceso,
        "proteina": nombre,
        "genes": [
            g["geneName"]["value"] for g in e.get("genes", []) if g.get("geneName")
        ],
        "organismo": (e.get("organism") or {}).get("scientificName"),
        "numeros_ec": ec,
        "longitud": (e.get("sequence") or {}).get("length"),
        "revisada": "reviewed" in (e.get("entryType") or "").lower()
        and "unreviewed" not in (e.get("entryType") or "").lower(),
        "funcion": " ".join(funcion) or None,
        "url": f"https://www.uniprot.org/uniprotkb/{acceso}/entry" if acceso else None,
    }


def _parsear_ficha_kegg(texto: str, max_lineas_campo: int = 25) -> dict[str, Any]:
    """Convierte una ficha KEGG (formato plano de columnas fijas) en un diccionario."""
    campos: dict[str, list[str]] = {}
    actual = None
    for linea in texto.splitlines():
        if linea.startswith("///"):
            break
        clave = linea[:12].strip()
        if clave and not linea.startswith(" "):
            actual = clave
            campos.setdefault(actual, [])
        if actual in KEGG_CAMPOS and linea[12:].strip():
            campos[actual].append(linea[12:].strip())
    resultado: dict[str, Any] = {}
    for clave, lineas in campos.items():
        if clave not in KEGG_CAMPOS:
            continue
        resultado[clave.lower()] = lineas[:max_lineas_campo]
        if len(lineas) > max_lineas_campo:
            resultado[clave.lower()].append(f"... ({len(lineas) - max_lineas_campo} líneas más)")
    return resultado


def _texto_xml_jats(xml_text: str, max_caracteres: int) -> dict[str, Any]:
    """Extrae título, resumen y secciones del cuerpo de un XML JATS de PMC."""
    raiz = ET.fromstring(xml_text)

    def plano(nodo: ET.Element | None) -> str:
        return " ".join("".join(nodo.itertext()).split()) if nodo is not None else ""

    secciones = []
    for sec in raiz.findall(".//body/sec"):
        titulo = plano(sec.find("title"))
        parrafos = [plano(p) for p in sec.iter("p")]
        secciones.append({"seccion": titulo, "texto": "\n".join(p for p in parrafos if p)})

    texto = "\n\n".join(f"## {s['seccion']}\n{s['texto']}" for s in secciones)
    return {
        "titulo": plano(raiz.find(".//article-title")),
        "resumen": plano(raiz.find(".//abstract")),
        "texto": texto[:max_caracteres],
        "truncado": len(texto) > max_caracteres,
        "secciones": [s["seccion"] for s in secciones],
    }


def _autor_apa(autor: dict[str, Any]) -> str | None:
    apellido = autor.get("family")
    if not apellido:
        return autor.get("name")
    iniciales = " ".join(
        f"{parte[0]}." for parte in re.split(r"[\s]+", autor.get("given", "")) if parte
    )
    return f"{apellido}, {iniciales}" if iniciales else apellido


def formatear_apa(meta: dict[str, Any], conjuncion: str = "y") -> str:
    """Formatea metadatos de Crossref en una referencia APA 7 (artículo de revista).

    Se usa como respaldo cuando doi.org no devuelve la cita ya formateada.
    """
    autores = [a for a in (_autor_apa(x) for x in meta.get("author", [])) if a]
    if len(autores) > 20:
        lista = ", ".join(autores[:19]) + ", ... " + autores[-1]
    elif len(autores) > 1:
        lista = ", ".join(autores[:-1]) + f", {conjuncion} " + autores[-1]
    else:
        lista = autores[0] if autores else ""

    fecha = (meta.get("issued") or {}).get("date-parts") or [[None]]
    anio = fecha[0][0] if fecha and fecha[0] else None
    titulo = (meta.get("title") or [""])[0].rstrip(".")
    revista = (meta.get("container-title") or [""])[0]

    partes = [f"{lista} ({anio or 's. f.'}). {titulo}."]
    if revista:
        fuente = f"*{revista}*"
        if meta.get("volume"):
            fuente += f", *{meta['volume']}*"
        if meta.get("issue"):
            fuente += f"({meta['issue']})"
        if meta.get("page"):
            fuente += f", {meta['page'].replace('-', '–')}"
        partes.append(fuente + ".")
    if meta.get("DOI"):
        partes.append(f"https://doi.org/{meta['DOI']}")
    return " ".join(p for p in partes if p).strip()


class OAClient:
    """Cliente asíncrono para las fuentes de acceso abierto."""

    def __init__(
        self,
        email: str | None = None,
        carpeta_descargas: str | Path | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.email = email or os.environ.get("OA_EMAIL")
        self.carpeta_descargas = Path(
            carpeta_descargas
            or os.environ.get("OA_DOWNLOAD_DIR")
            or Path.home() / "articulos_oa"
        ).expanduser()
        self.ncbi_api_key = os.environ.get("NCBI_API_KEY")
        agente = "oa-research-mcp/1.0"
        if self.email:
            agente += f" (mailto:{self.email})"
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
            headers={"User-Agent": agente},
            transport=transport,
        )

    async def cerrar(self) -> None:
        await self._http.aclose()

    async def _get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = await self._http.get(url, params=params)
        if resp.status_code == 404:
            raise OAError(f"Recurso no encontrado: {url}")
        resp.raise_for_status()
        return resp.json()

    def _params_openalex(self, **params: Any) -> dict[str, Any]:
        if self.email:
            params["mailto"] = self.email
        return params

    # --- Búsqueda -----------------------------------------------------------

    async def buscar_openalex(
        self,
        consulta: str,
        max_resultados: int = 10,
        desde_anio: int | None = None,
        hasta_anio: int | None = None,
        solo_acceso_abierto: bool = False,
        orden: str = "relevancia",
    ) -> list[dict[str, Any]]:
        filtros = []
        if desde_anio:
            filtros.append(f"from_publication_date:{desde_anio}-01-01")
        if hasta_anio:
            filtros.append(f"to_publication_date:{hasta_anio}-12-31")
        if solo_acceso_abierto:
            filtros.append("is_oa:true")
        params = self._params_openalex(**{"search": consulta, "per-page": min(max_resultados, 50)})
        if filtros:
            params["filter"] = ",".join(filtros)
        if orden == "citas":
            params["sort"] = "cited_by_count:desc"
        elif orden == "fecha":
            params["sort"] = "publication_date:desc"
        datos = await self._get_json(f"{OPENALEX_URL}/works", params)
        return [_resumir_obra_openalex(o) for o in datos.get("results", [])]

    async def buscar_europepmc(
        self, consulta: str, max_resultados: int = 10, solo_acceso_abierto: bool = False
    ) -> list[dict[str, Any]]:
        if solo_acceso_abierto:
            consulta = f"({consulta}) AND OPEN_ACCESS:Y"
        datos = await self._get_json(
            f"{EUROPEPMC_URL}/search",
            {"query": consulta, "format": "json", "resultType": "core",
             "pageSize": min(max_resultados, 100)},
        )
        return [_resumir_europepmc(r) for r in datos.get("resultList", {}).get("result", [])]

    async def buscar_arxiv(self, consulta: str, max_resultados: int = 10) -> list[dict[str, Any]]:
        resp = await self._http.get(
            ARXIV_URL,
            params={"search_query": f"all:{consulta}", "start": 0,
                    "max_results": min(max_resultados, 50)},
        )
        resp.raise_for_status()
        return _parsear_arxiv(resp.text)

    async def buscar_pubmed(
        self,
        consulta: str,
        max_resultados: int = 10,
        desde_anio: int | None = None,
        hasta_anio: int | None = None,
        orden: str = "relevancia",
    ) -> list[dict[str, Any]]:
        base = {"db": "pubmed", "retmode": "json", "tool": "oa-research-mcp"}
        if self.email:
            base["email"] = self.email
        if self.ncbi_api_key:
            base["api_key"] = self.ncbi_api_key
        params = {**base, "term": consulta, "retmax": min(max_resultados, 100),
                  "sort": "pub_date" if orden == "fecha" else "relevance"}
        if desde_anio or hasta_anio:
            params.update(datetype="pdat", mindate=str(desde_anio or 1800),
                          maxdate=str(hasta_anio or 3000))
        busqueda = await self._get_json(f"{EUTILS_URL}/esearch.fcgi", params)
        ids = busqueda.get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
        resumen = await self._get_json(f"{EUTILS_URL}/esummary.fcgi", {**base, "id": ",".join(ids)})
        docs = resumen.get("result", {})
        return [_resumir_pubmed(docs[i]) for i in ids if i in docs]

    async def buscar_uniprot(
        self,
        consulta: str,
        organismo: str | None = None,
        solo_revisadas: bool = True,
        max_resultados: int = 10,
    ) -> list[dict[str, Any]]:
        partes = [f"({consulta})"]
        if organismo:
            partes.append(f'(organism_name:"{organismo}")')
        if solo_revisadas:
            partes.append("(reviewed:true)")
        datos = await self._get_json(UNIPROT_URL, {
            "query": " AND ".join(partes), "format": "json", "size": min(max_resultados, 50),
            "fields": "accession,protein_name,gene_names,organism_name,ec,length,cc_function",
        })
        return [_resumir_uniprot(e) for e in datos.get("results", [])]

    async def buscar_kegg(self, base: str, termino: str, max_resultados: int = 20) -> list[dict[str, str]]:
        resp = await self._http.get(f"{KEGG_URL}/find/{base}/{quote(termino)}")
        resp.raise_for_status()
        resultados = []
        for linea in resp.text.splitlines():
            if "\t" in linea:
                ident, descripcion = linea.split("\t", 1)
                resultados.append({"id": ident, "descripcion": descripcion})
        return resultados[:max_resultados]

    async def detalle_kegg(self, identificador: str) -> dict[str, Any]:
        identificador = identificador.strip()
        if not re.fullmatch(r"[A-Za-z0-9_.:+-]+", identificador):
            raise OAError(f"Identificador KEGG no válido: {identificador!r}")
        resp = await self._http.get(f"{KEGG_URL}/get/{identificador}")
        if resp.status_code == 404 or not resp.text.strip():
            raise OAError(f"KEGG no tiene la entrada {identificador}.")
        resp.raise_for_status()
        return {"id": identificador, **_parsear_ficha_kegg(resp.text),
                "url": f"https://www.kegg.jp/entry/{identificador}"}

    # --- Proyectos ------------------------------------------------------------

    def carpeta_proyecto(self, proyecto: str | None) -> Path:
        if not proyecto:
            return self.carpeta_descargas
        return self.carpeta_descargas / nombre_proyecto_seguro(proyecto)

    def listar_proyectos(self) -> list[str]:
        configurados = [p.strip() for p in os.environ.get("OA_PROYECTOS", "").split(";") if p.strip()]
        existentes = (
            [d.name for d in self.carpeta_descargas.iterdir() if d.is_dir()]
            if self.carpeta_descargas.is_dir() else []
        )
        nombres = {nombre_proyecto_seguro(p) for p in configurados} | set(existentes)
        return sorted(nombres, key=_clave_orden_apa)

    async def agregar_a_bibliografia(
        self, dois: list[str], proyecto: str, idioma: str = "es-ES"
    ) -> dict[str, Any]:
        """Añade referencias APA a la bibliografía del proyecto, sin duplicar DOI."""
        carpeta = self.carpeta_proyecto(proyecto)
        carpeta.mkdir(parents=True, exist_ok=True)
        ruta_json = carpeta / "bibliografia.json"
        bibliografia: dict[str, str] = (
            json.loads(ruta_json.read_text(encoding="utf-8")) if ruta_json.exists() else {}
        )

        pendientes = []
        for doi in dois:
            try:
                normalizado = normalizar_doi(doi)
            except OAError as exc:
                pendientes.append(exc)
                continue
            if normalizado.lower() not in {d.lower() for d in bibliografia}:
                pendientes.append(normalizado)

        async def referencia(doi: str) -> dict[str, Any]:
            try:
                return await self.referencia_apa(doi, idioma)
            except (OAError, httpx.HTTPError) as exc:
                return {"doi": doi, "error": str(exc)}

        resultados = await asyncio.gather(
            *(referencia(d) for d in pendientes if isinstance(d, str))
        )
        agregadas = [r for r in resultados if "referencia" in r]
        errores = [r for r in resultados if "error" in r]
        errores += [{"error": str(e)} for e in pendientes if isinstance(e, OAError)]

        for r in agregadas:
            bibliografia[r["doi"]] = r["referencia"]
        ruta_json.write_text(json.dumps(bibliografia, ensure_ascii=False, indent=2), encoding="utf-8")
        ruta_md = carpeta / "referencias_apa.md"
        ordenadas = sorted(bibliografia.values(), key=_clave_orden_apa)
        ruta_md.write_text(
            f"# Referencias — {carpeta.name}\n\n" + "\n\n".join(ordenadas) + "\n",
            encoding="utf-8",
        )
        return {
            "proyecto": carpeta.name,
            "agregadas": [r["doi"] for r in agregadas],
            "ya_existian": len(dois) - len(pendientes),
            "errores": errores,
            "total_referencias": len(bibliografia),
            "archivo": str(ruta_md),
        }

    def ver_biblioteca(self, proyecto: str) -> dict[str, Any]:
        carpeta = self.carpeta_proyecto(proyecto)
        if not carpeta.is_dir():
            return {"proyecto": nombre_proyecto_seguro(proyecto), "pdfs": [], "referencias": [],
                    "aviso": "El proyecto aún no tiene archivos."}
        ruta_json = carpeta / "bibliografia.json"
        bibliografia = (
            json.loads(ruta_json.read_text(encoding="utf-8")) if ruta_json.exists() else {}
        )
        return {
            "proyecto": carpeta.name,
            "carpeta": str(carpeta),
            "pdfs": sorted(p.name for p in carpeta.glob("*.pdf")),
            "referencias": sorted(bibliografia.values(), key=_clave_orden_apa),
        }

    # --- Metadatos y localización de acceso abierto ---------------------------

    async def obra_openalex(self, doi: str) -> dict[str, Any]:
        doi = normalizar_doi(doi)
        datos = await self._get_json(
            f"{OPENALEX_URL}/works/doi:{quote(doi, safe='/')}", self._params_openalex()
        )
        return _resumir_obra_openalex(datos)

    async def unpaywall(self, doi: str) -> dict[str, Any]:
        if not self.email:
            raise OAError(
                "Unpaywall exige un correo de contacto. Defina la variable de entorno "
                "OA_EMAIL en la configuración del servidor MCP."
            )
        doi = normalizar_doi(doi)
        datos = await self._get_json(f"{UNPAYWALL_URL}/{quote(doi, safe='/')}", {"email": self.email})
        mejor = datos.get("best_oa_location") or {}
        return {
            "doi": doi,
            "titulo": datos.get("title"),
            "acceso_abierto": datos.get("is_oa", False),
            "estado_oa": datos.get("oa_status"),
            "url_pdf": mejor.get("url_for_pdf"),
            "url_pagina": mejor.get("url_for_landing_page") or mejor.get("url"),
            "version": mejor.get("version"),
            "licencia": mejor.get("license"),
            "alojamiento": mejor.get("host_type"),
            "ubicaciones": [
                {"url_pdf": u.get("url_for_pdf"), "url": u.get("url"),
                 "version": u.get("version"), "licencia": u.get("license"),
                 "alojamiento": u.get("host_type")}
                for u in datos.get("oa_locations", [])
            ],
        }

    async def localizar_acceso_abierto(self, doi: str) -> dict[str, Any]:
        """Combina Unpaywall, Europe PMC y OpenAlex para encontrar una versión legal."""
        doi = normalizar_doi(doi)
        candidatos: list[dict[str, Any]] = []
        avisos: list[str] = []
        titulo = None
        estado = None

        try:
            up = await self.unpaywall(doi)
            titulo, estado = up["titulo"], up["estado_oa"]
            for u in up["ubicaciones"]:
                if u["url_pdf"]:
                    candidatos.append({"fuente": "Unpaywall", **u})
        except (OAError, httpx.HTTPError) as exc:
            avisos.append(f"Unpaywall: {exc}")

        try:
            epmc = await self.buscar_europepmc(f'DOI:"{doi}"', max_resultados=1)
            if epmc and epmc[0]["url_pdf"]:
                titulo = titulo or epmc[0]["titulo"]
                candidatos.append({"fuente": "Europe PMC", "url_pdf": epmc[0]["url_pdf"],
                                   "pmcid": epmc[0]["pmcid"]})
        except (OAError, httpx.HTTPError) as exc:
            avisos.append(f"Europe PMC: {exc}")

        if not candidatos:
            try:
                oa = await self.obra_openalex(doi)
                titulo = titulo or oa["titulo"]
                estado = estado or oa["estado_oa"]
                if oa["url_oa"]:
                    candidatos.append({"fuente": "OpenAlex", "url_pdf": oa["url_oa"]})
            except (OAError, httpx.HTTPError) as exc:
                avisos.append(f"OpenAlex: {exc}")

        return {
            "doi": doi,
            "titulo": titulo,
            "acceso_abierto": bool(candidatos),
            "estado_oa": estado,
            "candidatos": candidatos,
            "avisos": avisos,
            "sugerencia": None if candidatos else (
                "No hay versión de acceso abierto registrada. Opciones legales: acceso "
                "institucional de su biblioteca, préstamo interbibliotecario o solicitar "
                "el PDF al autor de correspondencia."
            ),
        }

    # --- Descarga -------------------------------------------------------------

    async def descargar_pdf(self, doi: str, proyecto: str | None = None) -> dict[str, Any]:
        carpeta = self.carpeta_proyecto(proyecto)
        info = await self.localizar_acceso_abierto(doi)
        if not info["candidatos"]:
            return {**info, "guardado_en": None}

        carpeta.mkdir(parents=True, exist_ok=True)
        destino = carpeta / nombre_archivo_seguro(info["doi"])
        errores = []
        for cand in info["candidatos"]:
            url = cand["url_pdf"]
            try:
                contenido = await self._descargar_bytes(url)
            except (OAError, httpx.HTTPError) as exc:
                errores.append(f"{url}: {exc}")
                continue
            destino.write_bytes(contenido)
            return {"doi": info["doi"], "titulo": info["titulo"], "guardado_en": str(destino),
                    "fuente": cand["fuente"], "url": url, "bytes": len(contenido)}
        return {"doi": info["doi"], "titulo": info["titulo"], "guardado_en": None,
                "errores": errores,
                "sugerencia": "Las URLs encontradas no devolvieron un PDF directo; "
                              "ábralas en el navegador desde la página del repositorio."}

    async def _descargar_bytes(self, url: str) -> bytes:
        async with self._http.stream("GET", url) as resp:
            resp.raise_for_status()
            datos = bytearray()
            async for bloque in resp.aiter_bytes():
                datos.extend(bloque)
                if len(datos) > MAX_PDF_BYTES:
                    raise OAError("El archivo supera el tamaño máximo permitido (60 MB).")
        if not datos.startswith(b"%PDF"):
            raise OAError("La URL no devolvió un PDF (posiblemente una página HTML).")
        return bytes(datos)

    # --- Texto completo y citas ----------------------------------------------

    async def texto_completo_pmc(self, pmcid: str, max_caracteres: int = 40000) -> dict[str, Any]:
        pmcid = pmcid.strip().upper()
        if not pmcid.startswith("PMC"):
            pmcid = f"PMC{pmcid}"
        resp = await self._http.get(f"{EUROPEPMC_URL}/{pmcid}/fullTextXML")
        if resp.status_code == 404:
            raise OAError(f"{pmcid} no tiene texto completo en acceso abierto en Europe PMC.")
        resp.raise_for_status()
        return {"pmcid": pmcid, **_texto_xml_jats(resp.text, max_caracteres)}

    async def referencia_apa(self, doi: str, idioma: str = "es-ES") -> dict[str, Any]:
        doi = normalizar_doi(doi)
        try:
            resp = await self._http.get(
                f"{DOI_URL}/{quote(doi, safe='/')}",
                headers={"Accept": f"text/x-bibliography; style=apa; locale={idioma}"},
            )
            if resp.status_code == 200 and resp.text.strip():
                return {"doi": doi, "referencia": resp.text.strip(), "fuente": "doi.org (CSL APA)"}
        except httpx.HTTPError:
            pass
        datos = await self._get_json(f"{CROSSREF_URL}/{quote(doi, safe='/')}")
        conjuncion = "y" if idioma.lower().startswith("es") else "&"
        return {"doi": doi, "referencia": formatear_apa(datos["message"], conjuncion),
                "fuente": "Crossref (formato local)"}

    # --- Lotes ---------------------------------------------------------------

    async def procesar_lote(self, dois: list[str], descargar: bool = False,
                            proyecto: str | None = None,
                            concurrencia: int = 4) -> list[dict[str, Any]]:
        semaforo = asyncio.Semaphore(concurrencia)
        self.carpeta_proyecto(proyecto)  # valida el nombre antes de lanzar las consultas

        async def uno(doi: str) -> dict[str, Any]:
            async with semaforo:
                try:
                    if descargar:
                        return await self.descargar_pdf(doi, proyecto)
                    info = await self.localizar_acceso_abierto(doi)
                    return {"doi": info["doi"], "titulo": info["titulo"],
                            "acceso_abierto": info["acceso_abierto"],
                            "url_pdf": info["candidatos"][0]["url_pdf"] if info["candidatos"] else None}
                except (OAError, httpx.HTTPError) as exc:
                    return {"doi": doi, "error": str(exc)}

        return await asyncio.gather(*(uno(d) for d in dois))
