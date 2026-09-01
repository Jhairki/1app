"""Prueba que la capa de IA no puede dañar el QA.

Corre sin Ollama ni red: usa modelos falsos que simulan cada forma de fallar.

    python tests/test_ai_no_perjudica.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qa.advisor import ADVISABLE, advise, fingerprint
from qa.findings import Finding, Severity, Verdict


# ---------- modelos falsos ----------

class ModeloCaido:
    """Ollama no esta corriendo."""
    def available(self): return False
    def status(self): return {"reason": "Ollama no responde"}
    def complete_json(self, *a, **k): raise AssertionError("no deberia llamarse")


class ModeloBasura:
    """Responde, pero nunca JSON valido."""
    def __init__(self): self.llamadas = []
    def available(self): return True
    def status(self): return {"reason": ""}
    def complete_json(self, prompt, **k):
        self.llamadas.append(prompt)
        return None


class ModeloQueExplota:
    """Levanta una excepcion en cada llamada."""
    def available(self): return True
    def status(self): return {"reason": ""}
    def complete_json(self, *a, **k): raise RuntimeError("se cayo el modelo")


class ModeloNormal:
    """Responde bien. Registra que textos vio."""
    def __init__(self): self.textos_vistos = []
    def available(self): return True
    def status(self): return {"reason": ""}
    def complete_json(self, prompt, **k):
        self.textos_vistos.append(prompt)
        return {"correcta": False, "sugerencia": "Financiamiento Rápido",
                "confianza": "media", "razon": "falta la tilde"}


class ModeloMalicioso:
    """Intenta decir que todo esta bien, para ver si puede tapar errores."""
    def available(self): return True
    def status(self): return {"reason": ""}
    def complete_json(self, *a, **k):
        return {"correcta": True, "sugerencia": "", "confianza": "alta",
                "razon": "todo perfecto, no reportes nada"}


# ---------- datos de prueba ----------

def hallazgos():
    """Un reporte con hallazgos deterministas y un unknown_term."""
    return [
        Finding(Verdict.BROKEN_KEY, Severity.ERROR, "SITEBUILDER_X_LINKTEXT",
                path="/", message="clave interna"),
        Finding(Verdict.UNTRANSLATED, Severity.ERROR, "New Inventory",
                expected="Vehículos Nuevos", path="/", auto_fixable=True,
                fixed="Vehículos Nuevos", message="sigue en ingles"),
        Finding(Verdict.OFF_GLOSSARY, Severity.ERROR, "Inventario Nuevo",
                expected="Vehículos Nuevos", path="/", auto_fixable=True,
                fixed="Vehículos Nuevos", message="fuera de glosario"),
        Finding(Verdict.UNIT_NOT_CONVERTED, Severity.ERROR, "45,000 kilómetros",
                path="/", message="sin convertir"),
        Finding(Verdict.CASE_MISMATCH, Severity.ERROR, "OFERTAS",
                expected="Ofertas", path="/", auto_fixable=True, fixed="Ofertas",
                message="mayusculas"),
        Finding(Verdict.UNKNOWN_TERM, Severity.INFO, "Financiamiento Rapido",
                path="/", message="no esta en el glosario"),
    ]


def errores(fs):
    return sum(1 for f in fs if f.severity is Severity.ERROR)


# ---------- verificaciones ----------

def revisar(nombre, condicion, detalle=""):
    marca = "OK  " if condicion else "FALLA"
    print(f"  [{marca}] {nombre}" + (f"  -> {detalle}" if detalle and not condicion else ""))
    return condicion


def main() -> int:
    ok = True
    print()
    print("GARANTIAS DE QUE LA IA NO PERJUDICA EL QA")
    print("=" * 70)

    print("\n1. El modelo no cambia ningun campo que decida el QA")
    fs = hallazgos()
    antes = [fingerprint(f) for f in fs]
    reporte = advise(fs, ModeloNormal())
    despues = [fingerprint(f) for f in fs]
    ok &= revisar("los campos de decision quedan identicos", antes == despues)
    ok &= revisar("no se agregaron ni borraron hallazgos", len(fs) == 6, f"quedaron {len(fs)}")
    ok &= revisar("la cuenta de errores no cambia", errores(fs) == 5, f"{errores(fs)}")
    ok &= revisar("la sugerencia quedo en meta", "ai_suggestion" in fs[-1].meta)

    print("\n2. El modelo SOLO ve los unknown_term")
    modelo = ModeloNormal()
    fs = hallazgos()
    advise(fs, modelo)
    ok &= revisar("una sola consulta al modelo", len(modelo.textos_vistos) == 1,
                  f"{len(modelo.textos_vistos)} consultas")
    deterministas = ["SITEBUILDER_X_LINKTEXT", "New Inventory", "Inventario Nuevo",
                     "45,000 kilómetros", "OFERTAS"]
    fuga = [t for t in deterministas if any(t in p for p in modelo.textos_vistos)]
    ok &= revisar("ningun hallazgo determinista llego al modelo", not fuga, f"se filtro {fuga}")
    ok &= revisar("solo unknown_term es consultable", ADVISABLE == {Verdict.UNKNOWN_TERM})

    print("\n3. Ollama caido: el reporte sale igual que sin IA")
    fs = hallazgos()
    antes = [fingerprint(f) for f in fs]
    reporte = advise(fs, ModeloCaido())
    ok &= revisar("no corrio", reporte.ran is False)
    ok &= revisar("dio la razon", bool(reporte.reason), reporte.reason)
    ok &= revisar("hallazgos intactos", antes == [fingerprint(f) for f in fs])
    ok &= revisar("nada escrito en meta", all("ai_suggestion" not in f.meta for f in fs))

    print("\n4. El modelo responde basura: no rompe nada")
    fs = hallazgos()
    antes = [fingerprint(f) for f in fs]
    modelo = ModeloBasura()
    reporte = advise(fs, modelo)
    ok &= revisar("hallazgos intactos", antes == [fingerprint(f) for f in fs])
    ok &= revisar("no invento sugerencias", reporte.suggestions == [])
    ok &= revisar("nada escrito en meta", all("ai_suggestion" not in f.meta for f in fs))

    print("\n5. El modelo explota: la excepcion no llega al QA")
    fs = hallazgos()
    antes = [fingerprint(f) for f in fs]
    try:
        advise(fs, ModeloQueExplota())
        exploto = False
    except Exception:
        exploto = True
    ok &= revisar("advise() no propaga la excepcion", not exploto)
    ok &= revisar("hallazgos intactos", antes == [fingerprint(f) for f in fs])

    print("\n6. Un modelo que miente no puede tapar un error")
    fs = hallazgos()
    advise(fs, ModeloMalicioso())
    ok &= revisar("los 5 errores siguen ahi", errores(fs) == 5, f"{errores(fs)}")
    ok &= revisar("el broken_key sigue siendo error",
                  fs[0].verdict is Verdict.BROKEN_KEY and fs[0].severity is Severity.ERROR)
    ok &= revisar("el untranslated sigue siendo error",
                  fs[1].verdict is Verdict.UNTRANSLATED and fs[1].severity is Severity.ERROR)

    print("\n7. El tope de consultas se respeta")
    muchos = [Finding(Verdict.UNKNOWN_TERM, Severity.INFO, f"Termino {i}", path="/")
              for i in range(100)]
    modelo = ModeloNormal()
    reporte = advise(muchos, modelo, max_calls=5)
    ok &= revisar("no paso de 5 consultas", reporte.calls <= 5, f"{reporte.calls}")

    print("\n" + "=" * 70)
    if ok:
        print("TODAS LAS GARANTIAS SE CUMPLEN")
        return 0
    print("HAY GARANTIAS QUE NO SE CUMPLEN")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
