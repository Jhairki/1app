"""Prueba el Stare and Compare sin red, con dos paginas de fixture.

Lo que se verifica es que detecte los cuatro bugs tipicos de una migracion:
texto alterado, contenido perdido, referencias que quedaron apuntando al sitio
viejo, y daño de codificacion introducido al copiar.

    python tests/test_migration.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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

    print("\n" + "=" * 68)
    print("TODO OK" if ok else "HAY FALLAS")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
