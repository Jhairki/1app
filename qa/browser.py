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
      trigger: (() => {
        const $ = window.jQuery;
        const d = $ ? $(el).data('bs.popover') || $(el).data('bs.tooltip') : null;
        if (d && d.options && d.options.trigger) return d.options.trigger;
        return el.getAttribute('data-trigger') || '';
      })(),
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
    """Cierra lo abierto usando la API de cada widget. NUNCA borra nodos.

    Dos razones, las dos descubiertas rompiendo cosas:

    1. jQuery UI MUEVE el div de contenido adentro del .ui-dialog al abrirlo.
       Borrar ese wrapper se lleva puesto el contenido, y los popups que se
       prueban despues quedan sin nada que mostrar. Asi es como diálogos sanos
       se reportaban rotos, pero solo los ultimos de cada columna.

    2. Los popovers de Bootstrap ALTERNAN en cada interaccion. Si se les quita
       el nodo sin avisarles, siguen creyendo que estan mostrados y la
       interaccion siguiente los oculta en vez de abrirlos.
    """
    page.evaluate(
        """() => {
            const $ = window.jQuery;
            if (!$) return;
            try { $('[data-toggle="popover"], [data-toggle="tooltip"]').popover('hide'); } catch (e) {}
            try { $('[data-toggle="tooltip"]').tooltip('hide'); } catch (e) {}
            if ($.fn.dialog) {
              $('.ui-dialog-content').each(function () {
                try { $(this).dialog('close'); } catch (e) {}
              });
            }
            if ($.fn.modal) { try { $('.modal').modal('hide'); } catch (e) {} }
            document.querySelectorAll('.ui-widget-overlay, .modal-backdrop').forEach(n => n.remove());
        }"""
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


def _intentar(page, disparadores, indice: int, por_hover: bool):
    """Un intento de abrir un popup. Devuelve (abrio, contenido, error).

    La interaccion tiene que ser la correcta: los popovers de la primera
    columna del sitio real estan configurados con trigger 'hover', no 'click'.
    Probarlos con clic da un resultado que no representa lo que hace un usuario.
    """
    try:
        _cerrar_todo(page)
        page.wait_for_timeout(200)
        antes = _abiertos(page)

        elemento = disparadores.nth(indice)
        elemento.scroll_into_view_if_needed(timeout=5_000)
        page.wait_for_timeout(150)

        if por_hover:
            elemento.hover(timeout=6_000)
        else:
            elemento.click(timeout=6_000, force=True)

        if not _esperar_apertura(page, antes):
            # Si el hover no alcanzo, se prueba el clic: algunos popovers
            # aceptan las dos, y lo que importa es si el usuario puede abrirlo.
            if por_hover:
                elemento.click(timeout=6_000, force=True)
                if not _esperar_apertura(page, antes):
                    return False, "", ""
            else:
                return False, "", ""

        return True, page.evaluate(JS_CONTENIDO, SELECTORES_ABIERTO), ""
    except Exception as exc:
        return False, "", str(exc).split("\n")[0][:120]


def _cargar(page, url: str) -> None:
    """Carga la pagina y la deja asentada, lista para interactuar."""
    page.goto(url, wait_until="domcontentloaded", timeout=TIEMPO_CARGA)
    try:
        page.wait_for_load_state("networkidle", timeout=8_000)
    except Exception:
        pass  # los sitios de dealer nunca quedan del todo quietos

    # Sin esta espera el primer popup sale inestable: los handlers todavia se
    # estan enlazando cuando llega el primer clic.
    page.wait_for_timeout(2_000)
    page.mouse.move(10, 10)


def probar_popups(page, url: str) -> list[dict]:
    """Prueba cada popup con la interaccion que le corresponde.

    Recarga la pagina antes de CADA popup. Es lento, pero es la unica forma de
    que el resultado sea el que ve un usuario que llega y hace un solo clic:
    probandolos en secuencia sobre la misma pagina, las interacciones previas
    contaminan a las siguientes y dialogos perfectamente sanos salian rotos.
    Verificado a mano: con la pagina fresca, #content3 abre bien; probado en
    tercer lugar sobre la misma pagina, no.
    """
    _cargar(page, url)
    inventario = page.evaluate(JS_INVENTARIO)
    resultados = []

    for i, info in enumerate(inventario):
        por_hover = "hover" in (info.get("trigger") or "").lower()

        abrio, contenido, error, intento = False, "", "", 0
        for intento in range(1, REINTENTOS + 1):
            if i > 0 or intento > 1:
                _cargar(page, url)
            disparadores = page.locator(SELECTOR_DISPARADORES)
            abrio, contenido, error = _intentar(page, disparadores, i, por_hover)
            if abrio:
                break

        resultados.append({
            "clave": _identidad(info),
            "texto": info["texto"],
            "titulo": info["titulo"],
            "abrio": abrio,
            "contenido": contenido,
            "error": error,
            "intentos": intento,
            "interaccion": "hover" if por_hover else "clic",
        })

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
                    "Playwright is not installed, so popup behavior could not be "
                    "verified. Install it with: pip install playwright && "
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
                        f"This popup does not open in ENGLISH either ({clave}). It is a "
                        "site bug, not a localization one."
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
                        f"The popup opens in English but NOT in Spanish ({clave})."
                        + (f" Error: {es['error']}" if es["error"] else "")
                    ),
                    context=f"popup {clave}",
                    meta={"clave": clave, "en_abrio": True, "es_abrio": False},
                )
            )

    return findings
