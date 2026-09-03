"""Prueba el Stare and Compare sin red, con dos paginas de fixture.

Lo que se verifica es que detecte los cuatro bugs tipicos de una migracion:
texto alterado, contenido perdido, referencias que quedaron apuntando al sitio
viejo, y daño de codificacion introducido al copiar.

    python tests/test_migration.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

import qa.checks.links as links
import qa.migration as migration
from qa.findings import Verdict
from qa.glossary import load_glossary

ORIGINAL = """
<html><head><title>Mojix Chevrolet | Las Vegas</title>
<meta name="description" content="New and used vehicles in Las Vegas">
</head><body>
  <h1>Welcome to Mojix Chevrolet</h1>
  <h2>Our Services</h2>
  <a href="/new-inventory/">New Inventory</a>
  <a href="/service/">Schedule Service</a>
  <a href="/parts/">Order Parts</a>
  <a href="/financing/">Finance Center</a>
  <p>Open Monday through Saturday, 9am to 7pm.</p>
  <p>Call us at 888-111-2222 for an appointment.</p>
  <img src="/img/showroom.jpg" alt="Our showroom">
  <span data-toggle="popover" data-title="Hours" data-content="Closed Sundays">Hours</span>
</body></html>
"""

# La copia con los bugs tipicos de una migracion
MIGRADA = """
<html><head><title>Mojix Chevrolet | Las Vegas</title>
<meta name="description" content="New and used vehicles in Las Vegas">
</head><body>
  <h1>Welcome to Mojix Chevrolet</h1>
  <h2>Our Service</h2>
  <a href="/new-inventory/">New Inventory</a>
  <a href="https://oldsite.example.com/service/">Schedule Service</a>
  <a href="/financing/">Finance Center</a>
  <p>Open Monday through Saturday, 9am to 7pm.</p>
  <p>Call us at 888-111-2222 for an appointment.</p>
  <img src="https://oldsite.example.com/img/showroom.jpg" alt="Our showroom">
</body></html>
"""

ORIGEN = "https://oldsite.example.com/"
COPIA = "https://new.cms.dealer.com/"


def revisar(nombre, condicion, detalle=""):
    marca = "OK  " if condicion else "FALLA"
    print(f"  [{marca}] {nombre}" + (f"  -> {detalle}" if detalle and not condicion else ""))
    return condicion


def main() -> int:
    glossary, _ = load_glossary()

    paginas = {ORIGEN: ORIGINAL, COPIA: MIGRADA}
    migration.fetch_html = lambda s, url: next(
        (html for base, html in paginas.items() if url.startswith(base)), None
    )
    migration.polite_pause = lambda: None

    resultado = migration.compare_sites(ORIGEN, COPIA, ["/"],
                                        char_rules=glossary.char_rules)
    hallazgos = resultado.findings
    por_tipo = {}
    for f in hallazgos:
        por_tipo.setdefault(f.verdict, []).append(f)

    ok = True
    print()
    print("STARE AND COMPARE")
    print("=" * 68)
    print(f"\n{len(hallazgos)} hallazgos: " +
          ", ".join(f"{v.value}={len(fs)}" for v, fs in sorted(por_tipo.items(), key=lambda kv: kv[0].value)))

    print("\n1. Referencias que quedaron apuntando al sitio viejo")
    fugas = por_tipo.get(Verdict.SOURCE_LEAK, [])
    ok &= revisar("encuentra las 2", len(fugas) == 2, f"encontro {len(fugas)}")
    urls = " ".join(f.found for f in fugas)
    ok &= revisar("el link de Schedule Service", "/service/" in urls)
    ok &= revisar("la imagen del showroom", "showroom.jpg" in urls)

    print("\n2. Texto alterado al copiar")
    cambios = por_tipo.get(Verdict.TEXT_CHANGED, [])
    ok &= revisar("detecta 'Our Service' vs 'Our Services'",
                  any(f.found == "Our Service" and f.expected == "Our Services" for f in cambios),
                  "; ".join(f"{f.found!r}->{f.expected!r}" for f in cambios))

    print("\n3. Contenido que no llego")
    faltantes = por_tipo.get(Verdict.CONTENT_MISSING, [])
    textos = [f.expected for f in faltantes]
    ok &= revisar("detecta que falta 'Order Parts'", "Order Parts" in textos, str(textos))

    print("\n4. Popups que no se migraron")
    popups = por_tipo.get(Verdict.POPUP_MISSING, [])
    ok &= revisar("detecta el popover de Hours", len(popups) >= 1, f"{len(popups)}")

    print("\n5. Lo identico no genera ruido")
    identicos = ["Welcome to Mojix Chevrolet", "New Inventory", "Finance Center",
                 "Open Monday through Saturday, 9am to 7pm.",
                 "Mojix Chevrolet | Las Vegas"]
    ruido = [t for t in identicos
             if any(f.found == t or f.expected == t for f in cambios + faltantes)]
    ok &= revisar("los textos iguales no se reportan", not ruido, f"se reportaron {ruido}")

    print("\n6. Una copia identica no reporta nada")
    paginas[COPIA] = ORIGINAL
    limpio = migration.compare_sites(ORIGEN, COPIA, ["/"], char_rules=glossary.char_rules)
    ok &= revisar("cero hallazgos", not limpio.findings,
                  "; ".join(f.verdict.value for f in limpio.findings))

    print("\n7. Verificacion de links (--links)")
    ORIGINAL_LINKS = """
    <html><head><title>Home</title></head><body>
      <a href="/used-vehicles/">Used Vehicles</a>
      <a href="/contact/">Contact Us</a>
    </body></html>
    """
    MIGRADA_LINKS = """
    <html><head><title>Home</title></head><body>
      <a href="/inventory/index.htm">Used Vehicles</a>
      <a href="/contact-bad/">Contact Us</a>
      <a href="/broken/">Old Specials</a>
    </body></html>
    """
    paginas[ORIGEN] = ORIGINAL_LINKS
    paginas[COPIA] = MIGRADA_LINKS

    RESPUESTAS = {
        # Mismo destino, titulo parecido aunque no identico -> no es bug
        "https://new.cms.dealer.com/inventory/index.htm":
            (200, "<title>Used Vehicles For Sale | Mojix</title>"),
        "https://oldsite.example.com/used-vehicles/":
            (200, "<title>Used Vehicles For Sale</title>"),
        # Mismo texto de link, pero el destino habla de otra cosa -> si es bug
        "https://new.cms.dealer.com/contact-bad/":
            (200, "<title>Wrong Section</title>"),
        "https://oldsite.example.com/contact/":
            (200, "<title>Contact Us - Schedule a Visit</title>"),
        # Link que no resuelve en la copia
        "https://new.cms.dealer.com/broken/": (404, ""),
    }

    class FakeResponse:
        def __init__(self, status_code, html):
            self.status_code = status_code
            self.text = html

        @property
        def ok(self):
            return self.status_code < 400

    def fake_get(self, url, timeout=None):
        status, html = RESPUESTAS.get(url, (404, ""))
        return FakeResponse(status, html)

    requests.Session.get = fake_get
    links.LINK_CHECK_DELAY_SECONDS = 0  # no pausar en la prueba

    con_links = migration.compare_sites(ORIGEN, COPIA, ["/"],
                                        char_rules=glossary.char_rules, verify_links=True)
    hallazgos_links = con_links.findings

    rotos = [f for f in hallazgos_links if f.verdict == Verdict.BROKEN_LINK]
    ok &= revisar("detecta el link roto (404)",
                  any("/broken/" in f.meta.get("url", "") for f in rotos),
                  "; ".join(f.meta.get("url", "") for f in rotos))

    mismatches = [f for f in hallazgos_links if f.verdict == Verdict.LINK_MISMATCH]
    ok &= revisar("detecta el link que lleva a otra seccion",
                  any(f.meta.get("copy_url", "").endswith("/contact-bad/") for f in mismatches),
                  "; ".join(f.meta.get("copy_url", "") for f in mismatches))
    ok &= revisar("no marca el link cuyo destino coincide (aunque el titulo no sea identico)",
                  not any(f.meta.get("copy_url", "").endswith("/inventory/index.htm")
                         for f in mismatches),
                  "; ".join(f.meta.get("copy_url", "") for f in mismatches))

    print("\n7b. Paths distintos entre el original y la copia (--copy-paths)")
    paginas["https://oldsite.example.com/service/"] = ORIGINAL
    paginas["https://new.cms.dealer.com/service.htm"] = MIGRADA
    con_pares = migration.compare_sites(
        ORIGEN, COPIA, ["/service/"], copy_paths=["/service.htm"],
        char_rules=glossary.char_rules,
    )
    ok &= revisar("compara el path del original contra el de la copia",
                  not con_pares.error, con_pares.error)
    ok &= revisar("el reporte identifica la pagina por el path de la copia",
                  con_pares.pages and con_pares.pages[0].path == "/service.htm",
                  con_pares.pages[0].path if con_pares.pages else "sin paginas")
    ok &= revisar("las URLs armadas usan el path de cada sitio",
                  con_pares.pages
                  and con_pares.pages[0].source_url == "https://oldsite.example.com/service/"
                  and con_pares.pages[0].copy_url == "https://new.cms.dealer.com/service.htm",
                  f"{con_pares.pages[0].source_url} / {con_pares.pages[0].copy_url}"
                  if con_pares.pages else "sin paginas")

    print("\n7c. --paths y --copy-paths de largo distinto es un error, no una corrida a medias")
    con_error = migration.compare_sites(ORIGEN, COPIA, ["/", "/service/"],
                                        copy_paths=["/index.htm"],
                                        char_rules=glossary.char_rules)
    ok &= revisar("informa el error en vez de comparar como pueda",
                  bool(con_error.error) and not con_error.pages, con_error.error)

    print("\n8. Sin --links no se pide nada de eso")
    sin_links = migration.compare_sites(ORIGEN, COPIA, ["/"], char_rules=glossary.char_rules)
    ok &= revisar("no aparecen hallazgos de link roto ni de destino",
                  not any(f.verdict in (Verdict.BROKEN_LINK, Verdict.LINK_MISMATCH)
                         for f in sin_links.findings),
                  "; ".join(f.verdict.value for f in sin_links.findings))

    print("\n" + "=" * 68)
    print("TODO OK" if ok else "HAY FALLAS")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
