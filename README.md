# Servidor MCP de literatura científica en acceso abierto

Servidor [MCP](https://modelcontextprotocol.io) que permite a Claude buscar artículos
científicos, localizar versiones **legales** de acceso abierto, descargar PDF, leer el
texto completo de PubMed Central y generar referencias en formato **APA 7**.

Solo consulta fuentes oficiales y documentadas:

| Fuente | Uso en el servidor |
|---|---|
| [OpenAlex](https://openalex.org) | Búsqueda multidisciplinar y metadatos (más de 250 M de obras) |
| [Unpaywall](https://unpaywall.org) | Localización de PDF de acceso abierto por DOI |
| [Europe PMC](https://europepmc.org) | Literatura biomédica y texto completo de PMC |
| [arXiv](https://arxiv.org) | Preprints de ciencias exactas, ingeniería e informática |
| [Crossref](https://crossref.org) / doi.org | Referencias APA y metadatos |

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
        "OA_DOWNLOAD_DIR": "/RUTA/ABSOLUTA/articulos"
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

### Claude Code

```bash
claude mcp add acceso-abierto -e OA_EMAIL=su_correo@institucion.edu \
  -- /RUTA/ABSOLUTA/Prueba-/.venv/bin/python /RUTA/ABSOLUTA/Prueba-/open_access_server.py
```

## Ejemplos de uso con Claude

- «Busca los 10 artículos más citados sobre *biochar y retención de nitrógeno* desde 2018
  y dime cuáles tienen acceso abierto.»
- «Descarga los PDF abiertos de estos DOI y genera sus referencias APA: …»
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
