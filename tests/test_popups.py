"""Prueba el check de popups sin red.

Lo critico es el discriminador: en la pagina real de ejemplos hay siete
<a class="btn"> que parecen botones de popup y no lo son. Si entran al
reporte, el check no sirve.

    python tests/test_popups.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qa.checks.popups import check_popups, inventory
from qa.extract import extract_units, find_popup_elements, make_soup
from qa.findings import Verdict

BASE = "https://sitio.example.com/"

# Reproduce la estructura real de la pagina de ejemplos
CON_POPUPS = """
<html><body>
  <span data-toggle="popover" data-title="This is the title for desktop"
        data-content="This is the content">Pop on over. Button</span>
  <span data-toggle="popover" data-title="Title with no button"
        data-content="This is the content">Pop on over. NO Button</span>

  <a class="dialog" href="#" data-el="#content1"
     data-title="Title of the pop up">Pop up, click for a demostration.</a>
  <div id="content1" style="display:none">This is the content that was hidden</div>

  <a class="dialog" href="#" data-href="/eprice-form.htm"
     data-title="Eprice Form">Load content from fragment page.</a>
  <a class="dialog" href="#" data-href="/eprice-form.htm"
     data-title="Eprice Form">Load from a text.</a>

  <!-- Estos NO son popups: no tienen ningun atributo data-* -->
  <a class="btn btn-default" href="#">BUTTON 1</a>
  <a class="btn btn-primary" href="#">BUTTON 2</a>
  <a class="btn btn-default" href="#">BUTTON 3</a>
</body></html>
"""

SIN_POPUPS = """
<html><body>
  <a class="btn btn-default" href="#">BOTON 1</a>
  <a class="btn btn-primary" href="#">BOTON 2</a>
  <p>Contenido normal sin ningun popup.</p>
</body></html>
"""

TRADUCIDO = """
<html><body>
  <span data-toggle="popover" data-title="Este es el titulo"
        data-content="Este es el contenido">Pasa por aca. Boton</span>
  <span data-toggle="popover" data-title="Titulo sin boton"
        data-content="Este es el contenido">Pasa por aca. SIN Boton</span>

  <a class="dialog" href="#" data-el="#content1"
     data-title="Titulo del pop up">Ventana, haz clic para una demostracion.</a>
  <div id="content1" style="display:none">Este es el contenido que estaba oculto</div>

  <a class="dialog" href="#" data-href="/eprice-form.htm"
     data-title="Formulario de Precio">Cargar contenido de la pagina.</a>
  <a class="dialog" href="#" data-href="/eprice-form.htm"
     data-title="Formulario de Precio">Cargar desde un texto.</a>

  <a class="btn btn-default" href="#">BOTON 1</a>
</body></html>
"""


def revisar(nombre, condicion, detalle=""):
    marca = "OK  " if condicion else "FALLA"
    print(f"  [{marca}] {nombre}" + (f"  -> {detalle}" if detalle and not condicion else ""))
    return condicion


def main() -> int:
    ok = True
    print()
    print("CHECK DE POPUPS")
    print("=" * 66)

    print("\n1. El discriminador: que es popup y que no")
    soup = make_soup(CON_POPUPS)
    elementos = find_popup_elements(soup)
    ok &= revisar("encuentra los 5 popups", len(elementos) == 5, f"encontro {len(elementos)}")
    textos = [e.get_text(strip=True) for e in elementos]
    colados = [t for t in textos if t.startswith("BUTTON")]
    ok &= revisar("ningun <a class=btn> se colo", not colados, f"se colaron {colados}")

    print("\n2. Cada popup sale con su texto de los atributos")
    units = extract_units(CON_POPUPS, BASE)
    inv = inventory(units)
    ok &= revisar("5 popups en el inventario", len(inv) == 5, f"{len(inv)}")
    titulos = {d["titulo"] for d in inv.values()}
    ok &= revisar("captura data-title", "This is the title for desktop" in titulos)
    contenidos = {d["contenido"] for d in inv.values()}
    ok &= revisar("captura data-content", "This is the content" in contenidos)
    ok &= revisar("captura el div oculto del data-el",
                  "This is the content that was hidden" in contenidos)

    print("\n3. Dos disparadores al mismo destino son dos popups")
    fragmentos = [k for k in inv if "eprice-form" in k]
    ok &= revisar("no colapsan en una sola clave", len(fragmentos) == 2, f"{fragmentos}")

    print("\n4. El caso real: ingles con popups, español sin ninguno")
    es = extract_units(SIN_POPUPS, BASE)
    en = extract_units(CON_POPUPS, BASE)
    hallazgos = check_popups(es, en, "/ejemplos")
    ok &= revisar("un solo hallazgo, no uno por atributo", len(hallazgos) == 1, f"{len(hallazgos)}")
    if hallazgos:
        f = hallazgos[0]
        ok &= revisar("es popup_missing", f.verdict is Verdict.POPUP_MISSING)
        ok &= revisar("cuenta los 5", "5 popups" in f.message, f.message)

    print("\n5. Si estan en los dos idiomas, no hay hallazgo de inventario")
    es = extract_units(TRADUCIDO, BASE)
    en = extract_units(CON_POPUPS, BASE)
    hallazgos = check_popups(es, en, "/ejemplos")
    ok &= revisar("sin popup_missing", not hallazgos,
                  "; ".join(h.message[:60] for h in hallazgos))

    print("\n6. Una pagina sin popups en ningun idioma no reporta nada")
    hallazgos = check_popups(extract_units(SIN_POPUPS, BASE),
                             extract_units(SIN_POPUPS, BASE), "/x")
    ok &= revisar("sin hallazgos", not hallazgos)

    print("\n" + "=" * 66)
    print("TODO OK" if ok else "HAY FALLAS")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
