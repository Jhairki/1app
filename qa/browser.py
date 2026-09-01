"""Check B: verificar que los popups ABREN de verdad, con un navegador real.

El check sin navegador (qa/checks/popups.py) ve si el popup existe en el HTML.
Este ve si funciona. Son cosas distintas: en la pagina de ejemplos de un sitio
real los 6 dialogos estan perfectamente definidos en el HTML y ninguno abre,
porque el codigo llama a .dialog('open') sobre un elemento que nunca se
inicializo como dialogo.

Por que hace falta un navegador de verdad: los popovers de Bootstrap no
responden a un click programatico, solo a un evento real del usuario. Con
requests + BeautifulSoup esto es indetectable.

Es un modo APARTE, no parte del escaneo normal: abrir un navegador por pagina
es lento y pesado comparado con una descarga.
"""

import logging

from qa.findings import Finding, Severity, Verdict

logger = logging.getLogger(__name__)

# Lo que aparece en el DOM cuando algo se abrio
SELECTORES_ABIERTO = (
    ".popover, .ui-dialog, [role=dialog], .modal.in, .modal.show, "
    ".modal[style*='display: block'], .fancybox-container, .mfp-wrap"
)

# Los que disparan un popup. Un <a class="btn"> sin data-* no es uno.
SELECTOR_DISPARADORES = (
    "[data-toggle='popover'], [data-toggle='tooltip'], [data-toggle='modal'], "
    "a.dialog[data-el], a.dialog[data-href], .dialog[data-el], .dialog[data-href]"
)

TIEMPO_CARGA = 25_000
# Cuanto esperar a que aparezca el popup. Se sondea en vez de dormir fijo,
# porque los que cargan un fragmento por AJAX tardan mucho mas que los inline.
TIEMPO_APERTURA = 4_000
INTERVALO_SONDEO = 150

# Un popup que falla se reintenta: la primera interaccion con la pagina suele
# fallar por scroll o por handlers que todavia se estan enlazando, y reportar
# eso como bug del sitio seria un falso positivo.
REINTENTOS = 3


def _identidad(info: dict) -> str:
    """Misma logica de clave que qa/extract.py, para poder cruzar resultados."""
    toggle = (info.get("toggle") or "").lower()
    if toggle:
        objetivo = info.get("target") or info.get("href") or ""
        if objetivo.startswith("#"):
            return f"{toggle}:{objetivo}"
        return f"{toggle}#{info['indice']}"
    if info.get("dataEl"):
        return f"dialog:{info['dataEl']}"
    if info.get("dataHref"):
        return f"dialog:{info['dataHref']}"
    return f"dialog#{info['indice']}"


JS_INVENTARIO = """
() => {
  const sel = %s;
  return [...document.querySelectorAll(sel)]
    .filter(el => !el.closest('nav, header, footer, .header-navigation'))
    .map((el, i) => ({
      indice: i + 1,
      toggle: el.getAttribute('data-toggle') || '',
      target: el.getAttribute('data-target') || '',
      href: el.getAttribute('href') || '',
      dataEl: el.getAttribute('data-el') || '',
      dataHref: el.getAttribute('data-href') || '',
      titulo: el.getAttribute('data-title') || el.getAttribute('title') || '',
      texto: (el.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 60)
    }));
}
""" % repr(SELECTOR_DISPARADORES)


def _abiertos(page) -> int:
    return page.evaluate(
        "sel => [...document.querySelectorAll(sel)]"
        ".filter(n => n.offsetParent !== null || getComputedStyle(n).display !== 'none').length",
        SELECTORES_ABIERTO,
    )


def _cerrar_todo(page) -> None:
    """Cierra todo lo abierto Y resetea el estado interno de los widgets.

    Lo segundo es imprescindible. Los popovers de Bootstrap ALTERNAN en cada
    clic: si se les borra el nodo del DOM sin avisarles, siguen creyendo que
    estan mostrados y el clic siguiente los oculta en vez de abrirlos. Eso hacia
    que un popover sano se reportara como roto.
    """
    page.evaluate(
        """sel => {
            const $ = window.jQuery;
            if ($ && $.fn && $.fn.popover) {
              try { $('[data-toggle="popover"], [data-toggle="tooltip"]').popover('hide'); } catch (e) {}
            }
            document.querySelectorAll(sel).forEach(n => {
              const c = n.querySelector('.ui-dialog-titlebar-close, .close, [data-dismiss], .mfp-close');
              if (c) c.click(); else n.remove();
            });
            document.querySelectorAll('.ui-widget-overlay, .modal-backdrop').forEach(n => n.remove());
        }""",
        SELECTORES_ABIERTO,
    )
    page.keyboard.press("Escape")


JS_CONTENIDO = """sel => {
    const n = [...document.querySelectorAll(sel)]
      .filter(x => x.offsetParent !== null).pop();
    return n ? (n.innerText || '').trim().replace(/\\s+/g,' ').slice(0,160) : '';
}"""


def _esperar_apertura(page, antes: int) -> bool:
    """Sondea hasta que aparezca el popup, en vez de dormir un tiempo fijo.

    Los que cargan un fragmento por AJAX tardan mucho mas que los inline.
    """
    esperado = 0
    while esperado < TIEMPO_APERTURA:
        if _abiertos(page) > antes:
            return True
        page.wait_for_timeout(INTERVALO_SONDEO)
        esperado += INTERVALO_SONDEO
    return _abiertos(page) > antes


def _intentar(page, disparadores, indice: int):
    """Un intento de abrir un popup. Devuelve (abrio, contenido, error)."""
    try:
        _cerrar_todo(page)
        page.wait_for_timeout(200)
        antes = _abiertos(page)

        elemento = disparadores.nth(indice)
        elemento.scroll_into_view_if_needed(timeout=5_000)
        page.wait_for_timeout(150)
        elemento.click(timeout=6_000, force=True)

        if not _esperar_apertura(page, antes):
            return False, "", ""

        return True, page.evaluate(JS_CONTENIDO, SELECTORES_ABIERTO), ""
    except Exception as exc:
        return False, "", str(exc).split("\n")[0][:120]


def probar_popups(page, url: str) -> list[dict]:
    """Abre la pagina, hace clic real en cada popup y anota si abrio."""
    page.goto(url, wait_until="domcontentloaded", timeout=TIEMPO_CARGA)
    try:
        page.wait_for_load_state("networkidle", timeout=8_000)
    except Exception:
        pass  # los sitios de dealer nunca quedan del todo quietos

    # Calentamiento. Sin esto el PRIMER popup de la lista sale inestable: en
    # dos corridas seguidas del mismo sitio daba roto una vez y bien la otra.
    # Un QA que reporta resultados flaky es peor que no tenerlo.
    page.wait_for_timeout(2_500)
    page.mouse.move(10, 10)
    page.mouse.click(5, 5)
    page.wait_for_timeout(500)

    inventario = page.evaluate(JS_INVENTARIO)
    disparadores = page.locator(SELECTOR_DISPARADORES)
    resultados = []

    for i, info in enumerate(inventario):
        abrio, contenido, error, intento = False, "", "", 0
        for intento in range(1, REINTENTOS + 1):
            abrio, contenido, error = _intentar(page, disparadores, i)
            if abrio:
                break
            page.wait_for_timeout(400)

        resultados.append({
            "clave": _identidad(info),
            "texto": info["texto"],
            "titulo": info["titulo"],
            "abrio": abrio,
            "contenido": contenido,
            "error": error,
            "intentos": intento,
        })

    _cerrar_todo(page)
    return resultados


def check_popups_live(spanish_url: str, english_url: str, path: str = "",
                      headless: bool = True) -> list[Finding]:
    """Compara si los popups abren en cada idioma.

    Distingue de quien es el problema, igual que con las claves del CMS:

      no abre en español pero si en ingles -> bug de localizacion
      no abre en ninguno                   -> bug del sitio, no de traduccion
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [
            Finding(
                verdict=Verdict.POPUP_UNVERIFIED,
                severity=Severity.INFO,
                found="",
                path=path,
                message=(
                    "Playwright no esta instalado, no se pudo verificar que los "
                    "popups abran. Instalalo con: pip install playwright && "
                    "playwright install chromium"
                ),
            )
        ]

    findings: list[Finding] = []

    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=headless)
        try:
            pagina = navegador.new_page(viewport={"width": 1280, "height": 900})
            ingles = {r["clave"]: r for r in probar_popups(pagina, english_url)}
            español = {r["clave"]: r for r in probar_popups(pagina, spanish_url)}
        finally:
            navegador.close()

    for clave, en in ingles.items():
        es = español.get(clave)
        etiqueta = en["texto"] or en["titulo"] or clave

        if not en["abrio"]:
            # No abre ni en ingles: no es problema de la traduccion
            findings.append(
                Finding(
                    verdict=Verdict.POPUP_BROKEN_SOURCE,
                    severity=Severity.WARNING,
                    found=etiqueta,
                    path=path,
                    auto_fixable=False,
                    message=(
                        f"Este popup no abre en INGLES tampoco ({clave}). Es un bug "
                        "del sitio, no de la localizacion."
                    ),
                    context=f"popup {clave}",
                    meta={"clave": clave, "en_abrio": False,
                          "es_abrio": bool(es and es["abrio"])},
                )
            )
            continue

        if es is None:
            continue  # la ausencia ya la reporta checks/popups.py

        if not es["abrio"]:
            findings.append(
                Finding(
                    verdict=Verdict.POPUP_BROKEN,
                    severity=Severity.ERROR,
                    found=es["texto"] or etiqueta,
                    expected=etiqueta,
                    path=path,
                    auto_fixable=False,
                    message=(
                        f"El popup abre en ingles pero NO en español ({clave})."
                        + (f" Error: {es['error']}" if es["error"] else "")
                    ),
                    context=f"popup {clave}",
                    meta={"clave": clave, "en_abrio": True, "es_abrio": False},
                )
            )

    return findings
