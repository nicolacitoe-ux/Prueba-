"""Pruebas del cliente de acceso abierto con respuestas HTTP simuladas."""

import asyncio
import json

import httpx
import pytest

from oa_client import (
    OAClient,
    OAError,
    formatear_apa,
    nombre_archivo_seguro,
    normalizar_doi,
    reconstruir_resumen,
)

DOI = "10.1234/abc.5678"
PDF = b"%PDF-1.7\n contenido de prueba"

UNPAYWALL = {
    "doi": DOI,
    "title": "Un estudio de prueba",
    "is_oa": True,
    "oa_status": "gold",
    "best_oa_location": {"url_for_pdf": "https://repo.example.org/a.pdf",
                         "url_for_landing_page": "https://repo.example.org/a",
                         "version": "publishedVersion", "license": "cc-by",
                         "host_type": "repository"},
    "oa_locations": [{"url_for_pdf": "https://repo.example.org/a.pdf",
                      "url": "https://repo.example.org/a", "version": "publishedVersion",
                      "license": "cc-by", "host_type": "repository"}],
}

OPENALEX_WORK = {
    "id": "https://openalex.org/W1",
    "doi": f"https://doi.org/{DOI}",
    "display_name": "Un estudio de prueba",
    "publication_year": 2023,
    "type": "article",
    "cited_by_count": 12,
    "authorships": [{"author": {"display_name": "Ana Pérez"}}],
    "primary_location": {"source": {"display_name": "Revista de Pruebas"}},
    "open_access": {"is_oa": True, "oa_status": "gold", "oa_url": "https://oa.example.org/a.pdf"},
    "abstract_inverted_index": {"Resumen": [0], "breve": [1]},
}

ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <published>2024-01-01T00:00:00Z</published>
    <title>Redes  neuronales
      de prueba</title>
    <summary>Resumen arXiv.</summary>
    <author><name>Luis Gómez</name></author>
    <link title="pdf" href="http://arxiv.org/pdf/2401.00001v1"/>
    <arxiv:doi>10.9999/arx.1</arxiv:doi>
  </entry>
</feed>"""

JATS_XML = """<article><front><article-meta><title-group>
<article-title>Artículo PMC</article-title></title-group>
<abstract><p>Resumen PMC.</p></abstract></article-meta></front>
<body><sec><title>Métodos</title><p>Se midió X.</p></sec>
<sec><title>Resultados</title><p>X aumentó.</p></sec></body></article>"""


def crear_cliente(handler, tmp_path, email="investigador@example.org"):
    return OAClient(email=email, carpeta_descargas=tmp_path,
                    transport=httpx.MockTransport(handler))


def ejecutar(coro):
    return asyncio.run(coro)


def test_normalizar_doi():
    assert normalizar_doi("https://doi.org/10.1038/nature12373") == "10.1038/nature12373"
    assert normalizar_doi(" doi:10.1000/xyz.1. ") == "10.1000/xyz.1"
    with pytest.raises(OAError):
        normalizar_doi("no es un doi")


def test_nombre_archivo_seguro_no_permite_rutas():
    nombre = nombre_archivo_seguro("10.1000/../../etc/passwd")
    assert "/" not in nombre and not nombre.startswith(".")
    assert nombre.endswith(".pdf")


def test_reconstruir_resumen():
    assert reconstruir_resumen({"mundo": [1], "Hola": [0]}) == "Hola mundo"
    assert reconstruir_resumen(None) is None


def test_buscar_openalex_aplica_filtros(tmp_path):
    def handler(request):
        params = request.url.params
        assert params["search"] == "microbiota"
        assert params["per-page"] == "10"
        assert params["filter"] == "from_publication_date:2020-01-01,is_oa:true"
        assert params["sort"] == "cited_by_count:desc"
        assert params["mailto"] == "investigador@example.org"
        return httpx.Response(200, json={"results": [OPENALEX_WORK]})

    c = crear_cliente(handler, tmp_path)
    res = ejecutar(c.buscar_openalex("microbiota", desde_anio=2020,
                                     solo_acceso_abierto=True, orden="citas"))
    assert res[0]["doi"] == DOI
    assert res[0]["autores"] == ["Ana Pérez"]
    assert res[0]["resumen"] == "Resumen breve"


def test_buscar_arxiv(tmp_path):
    c = crear_cliente(lambda r: httpx.Response(200, text=ARXIV_XML), tmp_path)
    res = ejecutar(c.buscar_arxiv("redes"))
    assert res[0]["titulo"] == "Redes neuronales de prueba"
    assert res[0]["url_pdf"] == "http://arxiv.org/pdf/2401.00001v1"
    assert res[0]["anio"] == 2024 and res[0]["doi"] == "10.9999/arx.1"


def test_unpaywall_exige_correo(tmp_path, monkeypatch):
    monkeypatch.delenv("OA_EMAIL", raising=False)
    c = crear_cliente(lambda r: httpx.Response(200, json=UNPAYWALL), tmp_path, email=None)
    with pytest.raises(OAError, match="OA_EMAIL"):
        ejecutar(c.unpaywall(DOI))


def test_descargar_pdf_guarda_en_carpeta(tmp_path):
    def handler(request):
        host = request.url.host
        if host == "api.unpaywall.org":
            return httpx.Response(200, json=UNPAYWALL)
        if host == "www.ebi.ac.uk":
            return httpx.Response(200, json={"resultList": {"result": []}})
        if host == "repo.example.org":
            return httpx.Response(200, content=PDF)
        return httpx.Response(404)

    c = crear_cliente(handler, tmp_path)
    res = ejecutar(c.descargar_pdf(DOI))
    ruta = tmp_path / nombre_archivo_seguro(DOI)
    assert res["guardado_en"] == str(ruta)
    assert ruta.read_bytes() == PDF


def test_descargar_rechaza_html(tmp_path):
    def handler(request):
        if request.url.host == "api.unpaywall.org":
            return httpx.Response(200, json=UNPAYWALL)
        if request.url.host == "www.ebi.ac.uk":
            return httpx.Response(200, json={"resultList": {"result": []}})
        return httpx.Response(200, content=b"<html>login</html>")

    c = crear_cliente(handler, tmp_path)
    res = ejecutar(c.descargar_pdf(DOI))
    assert res["guardado_en"] is None
    assert "no devolvió un PDF" in res["errores"][0]
    assert not list(tmp_path.iterdir())


def test_sin_acceso_abierto_sugiere_vias_legales(tmp_path):
    def handler(request):
        host = request.url.host
        if host == "api.unpaywall.org":
            return httpx.Response(200, json={"is_oa": False, "oa_locations": []})
        if host == "www.ebi.ac.uk":
            return httpx.Response(200, json={"resultList": {"result": []}})
        if host == "api.openalex.org":
            obra = {**OPENALEX_WORK, "open_access": {"is_oa": False, "oa_url": None}}
            return httpx.Response(200, json=obra)
        return httpx.Response(404)

    c = crear_cliente(handler, tmp_path)
    res = ejecutar(c.localizar_acceso_abierto(DOI))
    assert res["acceso_abierto"] is False
    assert "préstamo interbibliotecario" in res["sugerencia"]


def test_europepmc_y_texto_completo(tmp_path):
    def handler(request):
        if request.url.path.endswith("/search"):
            assert "OPEN_ACCESS:Y" in request.url.params["query"]
            return httpx.Response(200, json={"resultList": {"result": [{
                "title": "Artículo PMC", "pmcid": "PMC123", "isOpenAccess": "Y",
                "doi": DOI, "pubYear": "2022",
                "journalInfo": {"journal": {"title": "Rev. Biomédica"}}}]}})
        assert request.url.path.endswith("/PMC123/fullTextXML")
        return httpx.Response(200, text=JATS_XML)

    c = crear_cliente(handler, tmp_path)
    res = ejecutar(c.buscar_europepmc("microbiota", solo_acceso_abierto=True))
    assert res[0]["url_pdf"] == "https://europepmc.org/articles/PMC123?pdf=render"
    assert res[0]["revista"] == "Rev. Biomédica"

    texto = ejecutar(c.texto_completo_pmc("123"))
    assert texto["pmcid"] == "PMC123"
    assert texto["secciones"] == ["Métodos", "Resultados"]
    assert "X aumentó." in texto["texto"]


def test_referencia_apa_desde_doi_org(tmp_path):
    def handler(request):
        assert "style=apa" in request.headers["Accept"]
        return httpx.Response(200, text="Pérez, A. (2023). Un estudio. https://doi.org/x\n")

    c = crear_cliente(handler, tmp_path)
    res = ejecutar(c.referencia_apa(DOI))
    assert res["referencia"].startswith("Pérez, A. (2023)")


def test_referencia_apa_respaldo_crossref(tmp_path):
    meta = {"author": [{"given": "Ana María", "family": "Pérez"},
                       {"given": "Luis", "family": "Gómez"}],
            "issued": {"date-parts": [[2023, 5]]}, "title": ["Un estudio de prueba"],
            "container-title": ["Revista de Pruebas"], "volume": "12", "issue": "3",
            "page": "45-67", "DOI": DOI}

    def handler(request):
        if request.url.host == "doi.org":
            return httpx.Response(503)
        return httpx.Response(200, json={"message": meta})

    c = crear_cliente(handler, tmp_path)
    res = ejecutar(c.referencia_apa(DOI))
    assert res["referencia"] == (
        "Pérez, A. M., y Gómez, L. (2023). Un estudio de prueba. "
        "*Revista de Pruebas*, *12*(3), 45–67. https://doi.org/10.1234/abc.5678"
    )


def test_formatear_apa_mas_de_20_autores():
    meta = {"author": [{"given": "A", "family": f"Autor{i}"} for i in range(25)],
            "issued": {"date-parts": [[2020]]}, "title": ["T"]}
    ref = formatear_apa(meta)
    assert "Autor18, A., ... Autor24, A." in ref
    assert "Autor19" not in ref


def test_procesar_lote_informa_errores(tmp_path):
    def handler(request):
        if request.url.host == "api.unpaywall.org":
            return httpx.Response(200, json=UNPAYWALL)
        return httpx.Response(200, json={"resultList": {"result": []}})

    c = crear_cliente(handler, tmp_path)
    res = ejecutar(c.procesar_lote([DOI, "texto inválido"]))
    assert res[0]["acceso_abierto"] is True
    assert res[0]["url_pdf"] == "https://repo.example.org/a.pdf"
    assert "DOI válido" in res[1]["error"]


def test_servidor_registra_herramientas():
    from open_access_server import mcp

    nombres = {t.name for t in ejecutar(mcp.list_tools())}
    assert nombres == {
        "buscar_articulos", "buscar_europe_pmc", "buscar_arxiv", "obtener_metadatos",
        "localizar_acceso_abierto", "descargar_pdf", "texto_completo_pmc",
        "referencia_apa", "procesar_lista_dois",
    }
    json.dumps([t.input_schema for t in ejecutar(mcp.list_tools())])
