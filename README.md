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

Abre http://localhost:5000. **La interfaz está en inglés**, igual que los
mensajes de los hallazgos y el CSV, porque el contenido que se revisa y el
equipo que lo lee trabajan en inglés.

El escaneo corre en segundo plano con barra de progreso. El reporte trae
filtros por severidad y por tipo de hallazgo, buscador de texto, páginas
plegables y un enlace para descargar el CSV.

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

### Stare and Compare — sitio migrado contra el original

```bash
python compare.py --source oldsite.com --copy new.cms.dealer.com --paths / /service/
```

Programa **aparte**, con lógica contraria a la de `scan.py`: acá los dos textos
deben ser **iguales**, no se traduce nada. Cualquier diferencia es sospechosa.

| Opción | Para qué |
|---|---|
| `--source` | Dominio del sitio original, del que se copia |
| `--copy` | Dominio del sitio migrado, normalmente el del CMS |
| `--paths / /service/` | Los paths a comparar, los mismos en los dos sitios |
| `--paths-file paths.txt` | Un path por línea, para lotes grandes |
| `--csv` · `--json` | Exportar el reporte |

Qué detecta:

| Check | Qué encuentra |
|---|---|
| Referencias al sitio viejo | Links e imágenes que siguen apuntando al origen. **El bug clásico**: la página se ve perfecta hasta que apagan el sitio viejo |
| Texto alterado | El elemento existe en los dos pero el texto cambió |
| Contenido perdido | Está en el original y no llegó a la copia |
| Contenido de más | Está en la copia y no en el original |
| Diferencia de cantidad | Una sección entera que falta, aunque los hallazgos sueltos no lo dejen ver |
| Claves, caracteres, popups | Los mismos checks de `scan.py`, que aplican igual |

No usa el glosario para juzgar traducciones — solo aprovecha sus reglas de
caracteres para detectar mojibake introducido al copiar.

### El formato de bugs del equipo

Los dos programas pueden emitir los hallazgos en el formato del documento de
proceso, para pegarlos directo en el tracker:

```
Field 1 | Field 2 | Field 3 | Field 4
   D    | Critical|  Link   | External Link needed — "https://oldsite.com/service/"
```

| Opción | Para qué |
|---|---|
| `--bugs` | Imprimir los hallazgos en ese formato |
| `--html reporte.html` | Reporte con el formato de Test & Feedback: cabecera, tabla de contenido y un bug por hallazgo |
| `--shots` | Adjuntar al reporte una captura recortada de cada bug, con el elemento resaltado |
| `--mobile` | Pide las páginas como un teléfono y reporta el Field 1 como `M` |

**Un bug que sale en varias páginas se reporta una sola vez**, con la lista de
paths y la nota de consultar con quien trabajó el request — que es lo que pide
el documento de proceso. En un sitio real eso baja 62 hallazgos a 2 bugs.

El mapeo de veredicto a los campos 2 y 3 está en [qa/bugreport.py](qa/bugreport.py),
en una tabla de una línea por veredicto, fácil de corregir.

#### Las capturas

`--shots` abre un navegador, ubica el elemento de cada hallazgo, le dibuja un
contorno rojo y **recorta esa región** — no fotografía la página entera. Cuando
hay las dos versiones, captura ambas y quedan lado a lado.

El recorte es por espacio: un reporte de Test & Feedback pesa ~700 KB por
captura de página completa, y estas pesan **14 KB**.

Si el elemento está oculto dentro de un menú desplegable (submenús que solo
aparecen con hover o clic), primero se intenta destaparlo: se sube por los
ancestros hasta el contenedor colapsado y se acciona su disparador — clic si
usa `data-toggle`/`aria-haspopup` (Bootstrap), hover si es un menú por CSS.
Los elementos que ni así se pueden ubicar quedan sin captura — se prefiere
ninguna antes que una que no muestre el elemento.

**Un bug agrupado en varias páginas no repite la captura en cada una.** Cada
hallazgo se agrupa por su línea de bug (`Field 1 | Field 2 | Field 3 | Field 4`,
igual que el resto del reporte), y dentro de esa línea el reporte muestra, por
cada *lugar* donde se ilustró el bug: su path, sus dos enlaces (`source` y, si
aplica, el de referencia) y sus imágenes — todo junto en una tarjeta. Por
defecto se ilustran hasta 2 lugares por bug; el resto de las páginas afectadas
se sigue listando aparte, en `Pages`, sin capturas repetidas.

Para el lado de referencia (la otra página), el texto a buscar **no** es
siempre el mismo campo del hallazgo: para un `off_glossary`, `expected` es la
traducción canónica del glosario — lo que *debería* decir la página revisada —
no lo que dice de verdad la otra página. Buscar eso ahí casi siempre fallaba.
`TermChecker.check()` ahora guarda aparte, en `meta['source_text']`, el texto
real de la contraparte, y `screenshots.py` lo usa para localizar el elemento
del lado de referencia.

Requiere Playwright y agrega un par de minutos.

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
app.py                 interfaz web del QA de localizacion
scan.py                CLI del QA de localizacion  (EN -> ES, contra el glosario)
compare.py             CLI del Stare and Compare   (original -> copia, mismo idioma)
validate_glossary.py   validador del glosario
qa/
  glossary.py          carga y valida data/
  normalize.py         normalización de texto (conserva acentos a propósito)
  casing.py            clasificación de mayúsculas
  fetch.py             descarga con locale
  extract.py           extracción y emparejamiento ES↔EN
  engine.py            orquesta los checks
  findings.py          modelo de hallazgos
  export.py            CSV, comun a los dos programas
  browser.py           verificacion de popups con Playwright
  migration.py         motor del Stare and Compare
  checks/              los checks
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

## Código desconectado

`qa/llm.py` y `qa/advisor.py` son una capa opcional de sugerencias con un
modelo local (Ollama), construida y luego desconectada a pedido. Nada del flujo
los importa; solo su propio test, `tests/test_ai_no_perjudica.py`, que verifica
que la capa no puede alterar ni ocultar ningún hallazgo de QA.

Para reconectarla harían falta dos cambios: el flag en `scan.py` y la casilla
en `app.py` con su plantilla.
