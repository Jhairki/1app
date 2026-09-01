# QA de Localización — sitios de dealers EN → ES

Verifica que la versión en español de un sitio de concesionario esté bien
migrada, comparando cada página `?locale=es_US` contra su equivalente
`?locale=en_US`.

Todo es determinista: reglas, glosario y aritmética. No usa ningún modelo de
lenguaje, así que el mismo sitio da siempre el mismo reporte.

## Instalación

Requiere Python 3.11 o superior.

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

En Git Bash el activate es `source venv/Scripts/activate`.

## Uso

### Interfaz web

```bash
python app.py
```

Abre http://localhost:5000. El escaneo corre en segundo plano con barra de
progreso, y al terminar el reporte trae un enlace para descargar el CSV.

### Línea de comandos

```bash
python scan.py https://midealer.com
```

| Opción | Para qué |
|---|---|
| `--max-pages 5` | Limitar cuántas páginas escanear |
| `--paths /servicio/ /ofertas/` | Revisar paths específicos en vez de la navegación |
| `--csv reporte.csv` | Exportar a CSV para abrir en Excel |
| `--json reporte.json` | Exportar a JSON |
| `--unknown` | Incluir los términos que no están en el glosario (mucho ruido) |
| `--popups` | Verificar con un navegador real que los popups abren (lento) |
| `-v` | Ver el progreso página por página |

Sale con código 1 si hay errores, para encadenarlo en CI.

**En Git Bash**, si pasás `--paths /` solo, antepone `MSYS_NO_PATHCONV=1` — si no,
Git Bash convierte la barra en una ruta de Windows.

### Validar el glosario

```bash
python validate_glossary.py
```

Revisa `data/` antes de escanear: claves duplicadas, traducciones faltantes,
`policy` inválidas, mojibake dentro del propio glosario. Sale con código 1 si
hay errores. El escaneo lo corre solo y se niega a arrancar si el glosario
está mal.

## Qué verifica

| Check | Qué detecta |
|---|---|
| Labels rotos | Claves internas del CMS visibles (`SITEBUILDER_*`), placeholders sin resolver, `undefined`/`null` |
| Traducción | El término español contra el glosario oficial |
| Contenido migrado | Texto que sigue en inglés, y contenido que existe en EN pero no en ES |
| Mayúsculas | Que el patrón de capitalización siga al de la página inglesa |
| Caracteres | Mojibake, entidades HTML visibles, acentos perdidos |
| Unidades | Que millas y kilómetros no cambien de unidad sin convertir el valor |
| Duplicados | El mismo término dos veces en la página, una traducida y otra no |
| Popups | Que los popups del inglés existan en español, y con `--popups`, que abran |

Cuando una clave del CMS aparece **solo en español**, el reporte dice qué texto
tiene la página inglesa en ese mismo elemento. Si aparece en los dos idiomas,
baja a advertencia: el label nunca se llenó en el CMS y no es un bug de
traducción.

## Popups

Un popup es invisible para los demás checks: su texto vive en atributos
(`data-title`, `data-content`) o en un div oculto, y su ausencia no deja
ningún hueco visible en la página.

Se detectan por `data-toggle="popover"` o por `class="dialog"` con `data-el`
o `data-href`. Un `<a class="btn">` sin ningún atributo `data-*` **no** es un
popup y no entra al reporte.

El escaneo normal compara el inventario entre idiomas. Con `--popups` además
se abre un navegador real y se hace clic en cada uno, porque los popovers de
Bootstrap no responden a un clic programático. Ese modo distingue si el popup
no abre solo en español (bug de localización) o tampoco en inglés (bug del
sitio).

Requiere `pip install playwright` y `playwright install chromium`.

## Los datos

Tres archivos en `data/`, editables en Excel:

- **`glossary.csv`** — los términos. Columnas: `english`,
  `spanish_canonical` (la oficial), `spanish_accepted` (variantes válidas,
  separadas por `|`), `policy`, `context`, `notes`.

  `policy` puede ser `translate`, `do_not_translate` (marcas como CarFinder),
  `pattern` (con placeholders `{n}`, `{year}`) o `pending` (sin traducción
  todavía).

- **`char_rules.csv`** — mojibake, acentos perdidos, typos. Las filas de tipo
  `html_entity` y `unit` quedan como referencia: las cubre otro check.

- **`style_rules.csv`** — reglas de estilo, como no usar artículos antes de
  modelos de vehículos.

Se leen con `utf-8-sig` porque Excel escribe BOM.

## Estructura

```
app.py                 interfaz web
scan.py                CLI
validate_glossary.py   validador del glosario
qa/
  glossary.py          carga y valida data/
  normalize.py         normalización de texto (conserva acentos a propósito)
  casing.py            clasificación de mayúsculas
  fetch.py             descarga con locale
  extract.py           extracción y emparejamiento ES↔EN
  engine.py            orquesta los checks
  findings.py          modelo de hallazgos
  export.py            CSV
  checks/              los seis checks
tests/
data/
```

## Notas

- Se espera un segundo entre peticiones para no golpear el sitio.
- El emparejamiento ES↔EN usa cuatro pasadas: href+query exacto, solo el
  query, orden cuando las cantidades coinciden, y texto más parecido. Los
  sitios reales usan rutas distintas por idioma (`/new/` vs `/new-inventory/`),
  y a veces meten la traducción dentro de la URL (`/SUV.htm` vs `/VUD.htm`).
- Los términos que no están en el glosario se ocultan salvo `--unknown`: en una
  página real son el 76% del reporte y casi todos son nombres de modelo,
  direcciones y copy de marketing.

## Código heredado

`scraper.py`, `workflow.py`, `agents/`, `chains/`, `tools/` y
`translations.csv` son de la versión anterior. Ya están reemplazados y nada del
código actual los importa. Necesitan `langchain` y `langchain-google-genai`,
que no están en `requirements.txt`.

`qa/llm.py` y `qa/advisor.py` son una capa opcional de sugerencias con un
modelo local, construida y luego desconectada. No los importa nadie salvo su
propio test.
