# Servidor MCP de literatura científica en acceso abierto

Servidor [MCP](https://modelcontextprotocol.io) que permite a Claude buscar artículos
científicos, localizar versiones **legales** de acceso abierto, descargar PDF, leer el
texto completo de PubMed Central y generar referencias en formato **APA 7**.
Está orientado a **biotecnología** (PubMed, UniProt, KEGG) y organiza los PDF y la
bibliografía **por proyecto**.

Solo consulta fuentes oficiales y documentadas:

| Fuente | Uso en el servidor |
|---|---|
| [OpenAlex](https://openalex.org) | Búsqueda multidisciplinar y metadatos (más de 250 M de obras) |
| [Unpaywall](https://unpaywall.org) | Localización de PDF de acceso abierto por DOI |
| [Europe PMC](https://europepmc.org) | Literatura biomédica y texto completo de PMC |
| [arXiv](https://arxiv.org) | Preprints de ciencias exactas, ingeniería e informática |
| [Crossref](https://crossref.org) / doi.org | Referencias APA y metadatos |
| [PubMed](https://pubmed.ncbi.nlm.nih.gov) (NCBI E-utilities) | Literatura biomédica y biotecnológica con términos MeSH |
| [UniProt](https://www.uniprot.org) | Proteínas y enzimas: función, organismo, números EC |
| [KEGG](https://www.kegg.jp) | Enzimas, rutas metabólicas, compuestos y reacciones |

## Herramientas

| Herramienta | Descripción |
|---|---|
| `buscar_articulos` | Búsqueda en OpenAlex con filtros por año, acceso abierto y orden (relevancia, citas, fecha) |
| `buscar_europe_pmc` | Búsqueda biomédica con la sintaxis de Europe PMC |
| `buscar_arxiv` | Búsqueda de preprints en arXiv |
| `obtener_metadatos` | Metadatos completos de un DOI |
| `localizar_acceso_abierto` | Versiones legales disponibles (versión y licencia) |
| `descargar_pdf` | Descarga el PDF abierto en la carpeta configurada |
| `texto_completo_pmc` | Texto completo por secciones de un artículo de PMC |
| `referencia_apa` | Referencia APA 7 (español o inglés) |
| `procesar_lista_dois` | Informe y descarga en lote (hasta 100 DOI) |
| `buscar_pubmed` | Búsqueda en PubMed con sintaxis NCBI (MeSH, `[tiab]`, `[pt]`) |
| `buscar_proteinas_uniprot` | Proteínas y enzimas por nombre, organismo y estado de revisión |
| `buscar_kegg` / `detalle_kegg` | Búsqueda y ficha de enzimas (EC), rutas, compuestos y reacciones |
| `listar_proyectos` | Proyectos configurados y existentes |
| `agregar_a_bibliografia` | Añade referencias APA al proyecto, sin duplicados y en orden alfabético |
| `ver_biblioteca` | PDF y referencias guardadas de un proyecto |

`descargar_pdf` y `procesar_lista_dois` aceptan el parámetro `proyecto` para guardar los
PDF en la carpeta de ese proyecto.

## Instalación

Requiere Python 3.10 o superior.

```bash
git clone https://github.com/nicolacitoe-ux/Prueba-.git
cd Prueba-
python -m venv .venv
# Windows: .venv\Scripts\activate    |    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

## Configuración en Claude Desktop

Edite el archivo de configuración de Claude Desktop:

- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`

Añada el servidor con las rutas absolutas al intérprete del entorno virtual y al script:

```json
{
  "mcpServers": {
    "acceso-abierto": {
      "command": "/RUTA/ABSOLUTA/Prueba-/.venv/bin/python",
      "args": ["/RUTA/ABSOLUTA/Prueba-/open_access_server.py"],
      "env": {
        "OA_EMAIL": "su_correo@institucion.edu",
        "OA_DOWNLOAD_DIR": "/RUTA/ABSOLUTA/articulos",
        "OA_PROYECTOS": "Proyecto de titulación NV;Biotecnología industrial NV"
      }
    }
  }
}
```

En Windows, `command` debe apuntar a `C:\\ruta\\Prueba-\\.venv\\Scripts\\python.exe`.
Reinicie Claude Desktop; las herramientas aparecerán en el menú de conectores.

| Variable | Obligatoria | Descripción |
|---|---|---|
| `OA_EMAIL` | Sí (para Unpaywall) | Correo de contacto exigido por Unpaywall; da acceso al *polite pool* de OpenAlex |
| `OA_DOWNLOAD_DIR` | No | Carpeta de descarga de PDF (por defecto `~/articulos_oa`) |
| `OA_PROYECTOS` | No | Nombres de proyectos separados por `;`; cada uno tiene su subcarpeta |
| `NCBI_API_KEY` | No | [Clave gratuita de NCBI](https://www.ncbi.nlm.nih.gov/account/) para más consultas por segundo a PubMed |

### Claude Code

```bash
claude mcp add acceso-abierto -e OA_EMAIL=su_correo@institucion.edu \
  -- /RUTA/ABSOLUTA/Prueba-/.venv/bin/python /RUTA/ABSOLUTA/Prueba-/open_access_server.py
```

## Uso en los Proyectos de Claude

Los servidores MCP locales están disponibles en **todas** las conversaciones de la
aplicación **Claude Desktop**, incluidas las que se abren dentro de un Proyecto. No están
disponibles en claude.ai desde el navegador ni desde el móvil, porque el servidor se
ejecuta en su ordenador.

1. Configure el servidor como se indica arriba y reinicie Claude Desktop.
2. Abra el Proyecto («Proyecto de titulación NV» o «Biotecnología industrial NV»).
3. En **Instrucciones del proyecto**, pegue el texto correspondiente de
   [`docs/instrucciones_proyectos.md`](docs/instrucciones_proyectos.md).
4. Cada proyecto tendrá su carpeta dentro de `OA_DOWNLOAD_DIR`:

```
articulos/
├── Proyecto de titulación NV/
│   ├── 10.1016_j.biotechadv.2021.107xxx.pdf
│   ├── bibliografia.json
│   └── referencias_apa.md
└── Biotecnología industrial NV/
    └── ...
```

`referencias_apa.md` puede subirse al conocimiento del Proyecto para que Claude lo
tenga presente en todas las conversaciones.

## Ejemplos de uso con Claude

- «Busca los 10 artículos más citados sobre *biochar y retención de nitrógeno* desde 2018
  y dime cuáles tienen acceso abierto.»
- «Descarga los PDF abiertos de estos DOI y genera sus referencias APA: …»
- «Busca en PubMed revisiones desde 2020 sobre inmovilización de lipasas para biodiésel,
  descarga las abiertas en *Biotecnología industrial NV* y añade sus referencias.»
- «Dame la ficha KEGG de la enzima EC 3.2.1.4 y las celulasas revisadas de
  *Trichoderma reesei* en UniProt.»
- «Busca en Europe PMC ensayos sobre probióticos en síndrome de intestino irritable,
  lee el texto completo del más reciente y resume su diseño metodológico.»

## Artículos sin versión abierta

Cuando no existe una versión de acceso abierto, el servidor lo indica y sugiere vías
legales: acceso mediante la biblioteca institucional (VPN o proxy), préstamo
interbibliotecario o solicitud directa del PDF al autor de correspondencia.

## Desarrollo y pruebas

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

Las pruebas simulan las respuestas HTTP, por lo que no requieren conexión a Internet.

## Estructura

```
oa_client.py            Lógica de consulta a las APIs (independiente de MCP)
open_access_server.py   Servidor MCP y definición de herramientas
tests/                  Pruebas unitarias con respuestas simuladas
```
