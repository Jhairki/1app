"""Capturas de pantalla del elemento donde esta el bug.

Recorta la region del elemento en vez de fotografiar la pagina entera, por dos
razones:

  Peso. El reporte de Test & Feedback del equipo pesa 7,5 MB con 9 capturas de
  pagina completa. Un recorte en JPEG pesa 40-80 KB, asi que 30 bugs entran en
  ~2 MB y el archivo se sigue pudiendo mandar por mail.

  Utilidad. Una captura de pagina completa no muestra DONDE esta el bug. El
  recorte con el elemento resaltado si.

Localizar el elemento se intenta por varias vias, de la mas precisa a la mas
general. Si ninguna funciona no hay captura -- por ahora se prefiere ninguna
antes que una que no muestre el elemento.
"""

import base64
import logging
import re

logger = logging.getLogger(__name__)

TIEMPO_CARGA = 25_000
MARGEN = 40          # pixeles alrededor del elemento, para dar contexto
ALTO_MAXIMO = 520    # un recorte mas alto que esto no ayuda a nadie
CALIDAD = 78

# Contorno del elemento, en el estilo de las capturas de QA
RESALTADO = """(el) => {
  const previo = el.getAttribute('style') || '';
  el.setAttribute('data-qa-style', previo);
  el.style.outline = '3px solid #e81123';
  el.style.outlineOffset = '2px';
  el.style.boxShadow = '0 0 0 4px rgba(232,17,35,.18)';
  el.scrollIntoView({block: 'center', inline: 'center'});
}"""

QUITAR_RESALTADO = """(el) => {
  el.setAttribute('style', el.getAttribute('data-qa-style') || '');
  el.removeAttribute('data-qa-style');
}"""


def _href_del_contexto(context: str):
    """El href de un contexto tipo 'link -> /parts/index.htm?x=1'."""
    m = re.match(r"link -> (\S+)", context or "")
    return m.group(1) if m else None


def _visible(loc) -> bool:
    try:
        return loc.count() > 0 and loc.first.is_visible()
    except Exception:
        return False


def _existe(loc) -> bool:
    """Esta en el DOM, este visible o no. Sirve para saber si vale la pena
    intentar destaparlo antes de darnos por vencidos."""
    try:
        return loc.count() > 0
    except Exception:
        return False


# Destapa el elemento si esta oculto dentro de un menu desplegable colapsado.
#
# Sube por los ancestros buscando el primero con display:none (el panel del
# menu -- un UL.dropdown-menu, un mega-menu, etc). El disparador de ese panel
# es el primer <a>/<button> del LI padre, o el hermano anterior. Si el
# disparador usa data-toggle o aria-haspopup (Bootstrap), se hace CLIC: ese
# patron no reacciona a un hover sintetico. Si no tiene ninguno de los dos, se
# asume que es un menu por CSS puro y se dispara mouseenter/mouseover.
#
# Encontrado en un sitio real: un link de "Service & Parts" y un heading de un
# mega-menu de "Pre-Owned Inventory" quedaban sin captura porque su contenedor
# tenia display:none hasta el hover/clic, y is_visible() los descartaba antes
# de intentar nada.
DESTAPAR_MENU = """(el) => {
  let n = el;
  let actuo = false;
  for (let i = 0; i < 6 && n; i++) {
    const cs = getComputedStyle(n);
    const oculto = cs.display === 'none' || cs.visibility === 'hidden'
                  || parseFloat(cs.opacity) === 0;
    if (oculto) {
      const padre = n.parentElement;
      let disparador = padre
        ? padre.querySelector(':scope > a[data-toggle], :scope > a[aria-haspopup],'
                              + ' :scope > button[data-toggle], :scope > a, :scope > button')
        : null;
      if (!disparador && n.previousElementSibling) {
        disparador = n.previousElementSibling;
      }
      if (disparador) {
        if (disparador.getAttribute('data-toggle') || disparador.getAttribute('aria-haspopup')) {
          disparador.click();
        } else {
          disparador.dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));
          disparador.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
        }
        actuo = true;
      }
    }
    n = n.parentElement;
  }
  return actuo;
}"""


def _destapar_si_hace_falta(page, loc) -> bool:
    """Si el candidato esta oculto por un menu, intenta abrirlo. Devuelve si
    quedo visible al final, se haya intentado algo o no."""
    if _visible(loc):
        return True
    try:
        if not loc.first.evaluate(DESTAPAR_MENU):
            return False
    except Exception:
        return False
    page.wait_for_timeout(300)
    return _visible(loc)


def find_element(page, finding, texto: str):
    """Busca el elemento del hallazgo. Devuelve un Locator o None.

    De lo mas preciso a lo mas general: la URL exacta que quedo apuntando al
    sitio viejo, el href del link, y por ultimo el texto. Un candidato que
    existe pero esta oculto se intenta destapar (menus desplegables) antes de
    descartarlo.
    """
    # 1. Fuga al sitio viejo: la URL esta en meta y es unica
    url = (finding.meta or {}).get("url")
    if url:
        for sel in (f'[href="{url}"]', f'[src="{url}"]', f'[data-href="{url}"]'):
            loc = page.locator(sel)
            if _existe(loc) and _destapar_si_hace_falta(page, loc):
                return loc.first

    # 2. Link: el href identifica el elemento sin ambiguedad
    href = _href_del_contexto(finding.context)
    if href and href not in ("", "#"):
        loc = page.locator(f'a[href="{href}"], a[href$="{href}"]')
        if _existe(loc) and _destapar_si_hace_falta(page, loc):
            return loc.first

    # 3. El texto, que es lo que funciona para encabezados y botones
    if texto and len(texto.strip()) > 2:
        try:
            loc = page.get_by_text(texto.strip(), exact=True)
            if _existe(loc) and _destapar_si_hace_falta(page, loc):
                return loc.first
            loc = page.get_by_text(texto.strip()[:60], exact=False)
            if _existe(loc) and _destapar_si_hace_falta(page, loc):
                return loc.first
        except Exception:
            pass

    return None


def capture(page, finding, texto: str):
    """Captura recortada del elemento. None si no se lo pudo ubicar."""
    elemento = find_element(page, finding, texto)
    if elemento is None:
        return None

    try:
        elemento.evaluate(RESALTADO)
        page.wait_for_timeout(220)

        caja = elemento.bounding_box()
        if not caja or caja["width"] < 2 or caja["height"] < 2:
            return None

        vista = page.viewport_size or {"width": 1280, "height": 900}
        x = max(0, caja["x"] - MARGEN)
        y = max(0, caja["y"] - MARGEN)
        ancho = min(vista["width"] - x, caja["width"] + MARGEN * 2)
        alto = min(vista["height"] - y, min(caja["height"] + MARGEN * 2, ALTO_MAXIMO))
        if ancho < 2 or alto < 2:
            return None

        datos = page.screenshot(
            type="jpeg", quality=CALIDAD,
            clip={"x": x, "y": y, "width": ancho, "height": alto},
        )
        return "data:image/jpeg;base64," + base64.b64encode(datos).decode()
    except Exception as exc:
        logger.info("No se pudo capturar %r: %s", texto[:40], exc)
        return None
    finally:
        try:
            elemento.evaluate(QUITAR_RESALTADO)
        except Exception:
            pass


def _urls_de(page_result):
    """(url_revisada, etiqueta) y (url_referencia, etiqueta) segun el programa."""
    if getattr(page_result, "copy_url", None):
        return (page_result.copy_url, "Migrated site"), (page_result.source_url, "Source site")
    return (page_result.spanish_url, "Spanish page"), (page_result.english_url, "English page")


def _texto_de(finding, campo: str) -> str:
    """El texto a buscar en la pantalla, para el lado 'found' o 'reference'.

    El lado de referencia NO usa finding.expected a ciegas: para un
    off_glossary, expected es la traduccion canonica del glosario (lo que
    DEBERIA decir la pagina revisada), no lo que dice de verdad la pagina de
    referencia. meta['source_text'], cuando existe, es el texto real de esa
    contraparte -- lo guarda TermChecker.check(). Sin esto, un heading sin
    link se quedaba sin captura del lado ingles: buscaba una traduccion que
    esa pagina nunca tuvo.
    """
    if campo == "found":
        return finding.found or ""
    return (finding.meta or {}).get("source_text") or finding.expected or ""


def _es_navegacion(finding) -> bool:
    """El hallazgo es de un termino del menu/nav, no de contenido de la pagina.

    El nav (y el footer) del sitio son el MISMO fragmento de HTML repetido en
    cada pagina -- no una coincidencia de texto, es literalmente el mismo
    elemento. Capturarlo desde dos paginas distintas da dos fotos casi
    identicas del mismo navbar: no es evidencia nueva, es el mismo bug
    fotografiado dos veces.

    La señal es la columna 'context' del glosario (nav/cta/form/...), que el
    equipo ya usa para categorizar cada termino al mantenerlo.
    """
    return "nav" in (finding.context or "").split(" | ")


def collect(result, device: str = "D", both_sides: bool = True,
            max_shots: int = 60, max_per_bug: int = 2, max_per_bug_nav: int = 1,
            headless: bool = True) -> dict:
    """Captura imagenes por hallazgo, agrupadas por lugar. Devuelve:

        {linea_de_bug: [{"path", "source", "reference", "shots": [...]}]}

    Cada entrada de la lista es UN LUGAR donde aparece el bug -- una pagina --
    con sus propias imagenes y sus propios enlaces de origen, en vez de una
    galeria plana sin saber que imagen viene de donde.

    both_sides captura tambien el lado de referencia, que en el Stare and
    Compare es lo que hace evidente la diferencia sin leer nada.

    max_per_bug limita cuantos LUGARES se capturan por cada bug agrupado. Un
    label del nav puede repetirse en las 30 paginas del sitio; capturarlo las
    30 veces es la misma imagen una y otra vez. La lista completa de paginas
    afectadas se sigue mostrando aparte (group_repeated ya la arma, sin tope):
    esto solo limita CUANTAS de esas paginas llevan captura.

    Los bugs de navegacion (ver _es_navegacion) usan max_per_bug_nav en vez de
    max_per_bug -- por defecto 1, porque ahi las paginas de mas no aportan
    nada: es literalmente el mismo elemento en todas.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("Playwright no esta instalado; el reporte va sin capturas.")
        return {}

    from qa.bugreport import to_bug

    capturas: dict[str, list] = {}
    conteo_por_bug: dict[str, int] = {}
    tomadas = 0

    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=headless)
        try:
            vista = {"width": 390, "height": 844} if device == "M" else {"width": 1280, "height": 900}
            pagina = navegador.new_page(viewport=vista)

            for page_result in result.pages:
                if page_result.error or not page_result.findings or tomadas >= max_shots:
                    continue

                # Un bug puede aparecer mas de una vez en la MISMA pagina (poco
                # comun, pero pasa); se toma solo la primera ocurrencia.
                por_bug: dict[str, object] = {}
                for finding in page_result.findings:
                    linea = to_bug(finding, device)
                    tope = max_per_bug_nav if _es_navegacion(finding) else max_per_bug
                    if conteo_por_bug.get(linea, 0) >= tope:
                        continue  # ya se capturaron suficientes lugares de este bug
                    por_bug.setdefault(linea, finding)
                if not por_bug:
                    continue

                (url_a, etiqueta_a), (url_b, etiqueta_b) = _urls_de(page_result)
                lados = [(url_a, etiqueta_a, "found")]
                if both_sides and url_b:
                    lados.append((url_b, etiqueta_b, "reference"))

                imagenes_por_bug: dict[str, list] = {linea: [] for linea in por_bug}

                for url, etiqueta, campo in lados:
                    if tomadas >= max_shots:
                        break
                    try:
                        pagina.goto(url, wait_until="domcontentloaded", timeout=TIEMPO_CARGA)
                        pagina.wait_for_timeout(1_200)
                    except Exception as exc:
                        logger.info("No se pudo abrir %s: %s", url, exc)
                        continue

                    for linea, finding in por_bug.items():
                        if tomadas >= max_shots:
                            break
                        texto = _texto_de(finding, campo)
                        if not texto:
                            continue
                        imagen = capture(pagina, finding, texto)
                        if imagen:
                            imagenes_por_bug[linea].append({"label": etiqueta, "src": imagen})
                            tomadas += 1

                for linea, shots in imagenes_por_bug.items():
                    if not shots:
                        continue
                    conteo_por_bug[linea] = conteo_por_bug.get(linea, 0) + 1
                    capturas.setdefault(linea, []).append({
                        "path": page_result.path,
                        "source": url_a,
                        "reference": url_b if both_sides else "",
                        "shots": shots,
                    })
        finally:
            navegador.close()

    logger.info("Capturas tomadas: %d", tomadas)
    return capturas
