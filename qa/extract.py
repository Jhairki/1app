"""Extraccion de las unidades de texto de una pagina.

La app vieja solo miraba los <a> de la navegacion. Para verificar que el
contenido esta migrado completo hace falta mas: encabezados, botones, alt de
imagenes y metadatos. Cada unidad sale con una CLAVE que permite emparejarla
con su equivalente de la pagina en ingles.

La clave por tipo:
  link      -> el href normalizado (sin el parametro locale)
  image_alt -> el src
  meta      -> el nombre del metadato
  heading   -> el nivel + el orden de aparicion (h2 #3)
  button    -> el orden de aparicion

El href es la clave fuerte: dos paginas del mismo sitio enlazan a los mismos
destinos, cambie o no el idioma del label.
"""

from dataclasses import dataclass
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse

from bs4 import BeautifulSoup

from qa.fetch import strip_locale, to_relative_path

# Estas etiquetas no llevan texto para el usuario
NON_CONTENT_TAGS = ["script", "style", "noscript", "template", "svg"]

# Dos textos sobrantes que se parecen tanto son el mismo elemento con el nombre
# escrito distinto, no dos elementos diferentes
TEXT_PAIR_RATIO = 0.85

# Tipos cuya clave es la POSICION, no la identidad. Solo son confiables si
# ambos idiomas tienen la misma cantidad: la pagina española del sitio real
# trae encabezados de mas ('PM', 'PS', 'TEAM') que corren todo el resto y
# hacen que cada item se compare contra el anterior del ingles.
POSITIONAL_KINDS = {"heading", "button"}

# Tipos que describen un popup, para el check de inventario
POPUP_KINDS = {"popup_trigger", "popup_title", "popup_content"}

HEADING_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6"]

# Valores de data-toggle que abren algo flotante
POPUP_TOGGLES = {"popover", "tooltip", "modal"}


@dataclass(frozen=True)
class TextUnit:
    kind: str
    key: str
    text: str
    order: int
    tag: str = ""

    @property
    def pair_key(self) -> tuple[str, str]:
        return (self.kind, self.key)

    def describe(self) -> str:
        if self.kind == "link":
            return f"link -> {self.key}"
        if self.kind == "image_alt":
            return f"alt of {self.key}"
        if self.kind == "meta":
            return f"meta {self.key}"
        if self.kind in POPUP_KINDS:
            etiqueta = {"popup_trigger": "trigger", "popup_title": "title",
                        "popup_content": "content"}[self.kind]
            return f"popup {self.key} ({etiqueta})"
        return f"{self.kind} {self.key}"


def make_soup(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(NON_CONTENT_TAGS):
        tag.decompose()
    return soup


def visible_text(html: str) -> str:
    """Texto visible de la pagina, con las entidades ya decodificadas.

    Los checks de caracteres corren sobre ESTO, no sobre el HTML crudo: asi una
    entidad bien escrita en el fuente no genera falso positivo, y una que sigue
    visible aqui es el bug real.
    """
    return make_soup(html).get_text(separator=" ", strip=True)


def _link_key(base_url: str, href: str) -> str:
    """Clave de un link: el path MAS su query, sin el parametro locale.

    El query no se puede tirar: en un sitio real hay 55 links a
    /new-inventory/index.htm que solo se distinguen por ?model=Colorado,
    ?model=Silverado, etc. Sin el query colapsan todos en la misma clave.
    """
    relative = to_relative_path(base_url, href)
    if relative is None:
        return strip_locale(href)

    parsed = urlparse(urljoin(base_url, href))
    query = urlencode([
        (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k != "locale"
    ])
    return f"{relative}?{query}" if query else relative


def popup_identity(el, base_url: str, index: int) -> str:
    """Clave estable de un popup.

    Los dialogos tienen identidad real: el data-el al que apuntan o el data-href
    que cargan. Los popovers no tienen ninguna, asi que van por posicion.
    """
    toggle = (el.get("data-toggle") or "").lower()
    if toggle in POPUP_TOGGLES:
        target = el.get("data-target") or el.get("href")
        if target and target.startswith("#"):
            return f"{toggle}:{target}"
        return f"{toggle}#{index}"

    if el.get("data-el"):
        return f"dialog:{el['data-el']}"
    if el.get("data-href"):
        return f"dialog:{_link_key(base_url, el['data-href'])}"
    return f"dialog#{index}"


def find_popup_elements(soup):
    """Los elementos que disparan un popup.

    El discriminador importa: en la pagina de ejemplos hay siete <a class="btn">
    que parecen botones de popup y no tienen NINGUN atributo data-*. Esos no son
    popups y no deben entrar al reporte.
    """
    elements = []
    seen = set()

    for el in soup.find_all(attrs={"data-toggle": True}):
        if (el.get("data-toggle") or "").lower() in POPUP_TOGGLES and id(el) not in seen:
            seen.add(id(el))
            elements.append(el)

    for el in soup.find_all(class_="dialog"):
        if (el.get("data-el") or el.get("data-href")) and id(el) not in seen:
            seen.add(id(el))
            elements.append(el)

    return elements


def extract_units(html: str, base_url: str) -> list[TextUnit]:
    """Devuelve todas las unidades de texto emparejables de la pagina."""
    soup = make_soup(html)
    units: list[TextUnit] = []
    order = 0

    def add(kind: str, key: str, text: str, tag: str = "") -> None:
        nonlocal order
        cleaned = (text or "").strip()
        if cleaned:
            units.append(TextUnit(kind, key, cleaned, order, tag))
            order += 1

    if soup.title and soup.title.string:
        add("meta", "title", soup.title.string, "title")

    for meta in soup.find_all("meta"):
        name = (meta.get("name") or meta.get("property") or "").lower()
        if name in {"description", "og:title", "og:description", "keywords"}:
            add("meta", name, meta.get("content", ""), "meta")

    heading_counts: dict[str, int] = {}
    for heading in soup.find_all(HEADING_TAGS):
        tag = heading.name
        heading_counts[tag] = heading_counts.get(tag, 0) + 1
        add("heading", f"{tag}#{heading_counts[tag]}", heading.get_text(strip=True), tag)

    for anchor in soup.find_all("a", href=True):
        add("link", _link_key(base_url, anchor["href"]), anchor.get_text(strip=True), "a")

    button_index = 0
    for button in soup.find_all("button"):
        button_index += 1
        add("button", f"button#{button_index}", button.get_text(strip=True), "button")

    for field in soup.find_all("input", attrs={"type": ["submit", "button"]}):
        button_index += 1
        add("button", f"button#{button_index}", field.get("value", ""), "input")

    # --- Popups: el texto vive en atributos, no en el cuerpo de la pagina ---
    # Dos disparadores distintos pueden apuntar al mismo destino (dos links al
    # mismo /eprice-form.htm). Son dos popups: cada uno tiene su propio texto.
    vistas: dict[str, int] = {}
    for popup_index, el in enumerate(find_popup_elements(soup), 1):
        key = popup_identity(el, base_url, popup_index)
        repeticion = vistas.get(key, 0)
        vistas[key] = repeticion + 1
        if repeticion:
            key = f"{key}#{repeticion + 1}"
        add("popup_trigger", key, el.get_text(strip=True), el.name)
        add("popup_title", key, el.get("data-title") or el.get("title") or "", el.name)
        add("popup_content", key, el.get("data-content") or "", el.name)

        # Los dialogos inline apuntan a un div oculto con el contenido real
        target = el.get("data-el") or ""
        if target.startswith("#"):
            node = soup.find(id=target[1:])
            if node is not None:
                add("popup_content", key, node.get_text(" ", strip=True), node.name)

    for image in soup.find_all("img"):
        alt = (image.get("alt") or "").strip()
        if alt:
            add("image_alt", image.get("src", f"img#{order}"), alt, "img")

    return units


def find_navigation_paths(html: str, base_url: str) -> list[str]:
    """Paths del sitio sacados de la navegacion principal."""
    soup = make_soup(html)
    navigation = soup.find("div", class_="header-navigation") or soup.find("nav")
    if navigation is None:
        return []

    paths: list[str] = []
    seen: set[str] = set()
    for anchor in navigation.find_all("a", href=True):
        relative = to_relative_path(base_url, anchor["href"])
        if relative and relative not in seen:
            seen.add(relative)
            paths.append(relative)
    return paths


def index_units(units: list[TextUnit]) -> dict[tuple[str, str, int], TextUnit]:
    """Indexa por (tipo, clave, n-esima aparicion).

    El numero de aparicion es imprescindible: en la portada real hay 12 links
    de navegacion con href vacio, y 55 al mismo path. Sin el, "la primera gana"
    emparejaba 'Vehiculos Usados' con 'New Inventory' y disparaba hallazgos
    falsos. Ahora el n-esimo link de cada clave se empareja con el n-esimo del
    otro idioma, que es el orden en que el CMS los renderiza.
    """
    index: dict[tuple[str, str, int], TextUnit] = {}
    seen: dict[tuple[str, str], int] = {}
    for unit in units:
        n = seen.get(unit.pair_key, 0)
        seen[unit.pair_key] = n + 1
        index[(unit.kind, unit.key, n)] = unit
    return index


def _numbered(units: list[TextUnit]):
    """Devuelve [(clave_con_numero, unidad), ...] con la misma numeracion."""
    seen: dict[tuple[str, str], int] = {}
    result = []
    for unit in units:
        n = seen.get(unit.pair_key, 0)
        seen[unit.pair_key] = n + 1
        result.append(((unit.kind, unit.key, n), unit))
    return result


def _query_of(key: str) -> str:
    """El query de una clave de link, sin el path."""
    return key.split("?", 1)[1] if "?" in key else ""


def pair_units(spanish: list[TextUnit], english: list[TextUnit]):
    """Empareja las unidades ES con sus equivalentes EN.

    Devuelve (pares, huerfanas_es, faltantes_en_es).

    Tres pasadas, aprendidas de un sitio real:

    1. Clave exacta (tipo, href+query, n-esima aparicion).

    2. Solo el query, para los links que no matchearon. El sitio real usa
       rutas distintas por idioma para lo mismo:
         ES /new-inventory/index.htm?model=Corvette+E-Ray
         EN /new/index.htm?model=Corvette+E-Ray
       El query identifica el destino aunque el path cambie.

    3. Los links con href vacio (los que maneja JavaScript) solo se emparejan
       por posicion si ambos lados tienen la MISMA cantidad. Si difieren, la
       posicion ya no significa nada: emparejar igual hacia que 'Coupe' se
       comparara contra 'Truck'. En ese caso se juzga el texto español solo.
    """
    from collections import defaultdict

    def agrupar(units):
        grupos = defaultdict(list)
        for unit in units:
            grupos[unit.pair_key].append(unit)
        return grupos

    grupos_es = agrupar(spanish)
    grupos_en = agrupar(english)

    # Los tipos posicionales se descartan enteros si las cantidades no cuadran
    posicionales_rotos = {
        kind for kind in POSITIONAL_KINDS
        if sum(1 for u in spanish if u.kind == kind)
        != sum(1 for u in english if u.kind == kind)
    }

    pairs: list[tuple[TextUnit, TextUnit]] = []
    sin_par_es: list[TextUnit] = []
    sin_par_en: list[TextUnit] = []

    # --- Pasada 1 y 3: por clave, con el cuidado de las claves vacias ---
    for clave, unidades_es in grupos_es.items():
        unidades_en = grupos_en.get(clave, [])
        # Sin identidad real: href vacio, o un tipo posicional desfasado
        clave_vacia = not clave[1] or clave[0] in posicionales_rotos

        if clave_vacia and len(unidades_es) != len(unidades_en):
            # Listas de distinto largo: la posicion no es evidencia de nada
            sin_par_es.extend(unidades_es)
            continue
        if clave[0] in posicionales_rotos:
            sin_par_es.extend(unidades_es)
            continue

        n = min(len(unidades_es), len(unidades_en))
        pairs.extend(zip(unidades_es[:n], unidades_en[:n]))
        sin_par_es.extend(unidades_es[n:])

    for clave, unidades_en in grupos_en.items():
        unidades_es = grupos_es.get(clave, [])
        if clave[0] in posicionales_rotos:
            continue  # la posicion esta corrida: no se afirma que falte nada
        if not clave[1] and len(unidades_es) != len(unidades_en):
            continue  # ver arriba: sin evidencia, no se afirma que falte
        sin_par_en.extend(unidades_en[len(unidades_es):])

    # --- Pasada 2: por query, para los links de rutas distintas ---
    por_query = defaultdict(list)
    for unit in sin_par_en:
        query = _query_of(unit.key) if unit.kind == "link" else ""
        if query:
            por_query[query].append(unit)

    huerfanas: list[TextUnit] = []
    emparejadas_en = set()

    for unit in sin_par_es:
        query = _query_of(unit.key) if unit.kind == "link" else ""
        candidatos = por_query.get(query) if query else None
        if candidatos:
            pareja = candidatos.pop(0)
            pairs.append((unit, pareja))
            emparejadas_en.add(id(pareja))
        else:
            huerfanas.append(unit)

    restantes_en = [u for u in sin_par_en if id(u) not in emparejadas_en]

    # --- Pasada 4: por texto mas parecido entre los sobrantes ---
    # El carrusel de modelos no se puede emparejar por URL: el sitio usa otro
    # path por idioma Y otro año en el query ('year=2026' vs 'year=2027').
    # Lo que si queda estable es el nombre. 'Sierra 2500HD' encuentra a
    # 'Sierra 2500 HD', y lo que no encuentra a nadie si esta faltando.
    disponibles = defaultdict(list)
    for u in restantes_en:
        disponibles[u.kind].append(u)

    # 4a. Si de un tipo sobra la MISMA cantidad de cada lado, el orden del CMS
    # alcanza. Pasa cuando la URL lleva la traduccion adentro:
    #   ES /showroom/2027/Chevrolet/Bolt/VUD.htm
    #   EN /showroom/2027/Chevrolet/Bolt/SUV.htm
    # 53 de cada lado, misma grilla, mismo orden.
    sobrantes_es = defaultdict(list)
    for u in huerfanas:
        sobrantes_es[u.kind].append(u)

    tomadas = set()
    resueltas_es = set()
    for kind, lista_es in sobrantes_es.items():
        lista_en = disponibles.get(kind, [])
        if lista_en and len(lista_es) == len(lista_en):
            pairs.extend(zip(lista_es, lista_en))
            tomadas.update(id(u) for u in lista_en)
            resueltas_es.update(id(u) for u in lista_es)

    huerfanas = [u for u in huerfanas if id(u) not in resueltas_es]

    # 4b. El resto, por texto muy parecido
    huerfanas_finales = []

    for unidad in huerfanas:
        candidatos = disponibles.get(unidad.kind, [])
        mejor, mejor_ratio = None, 0.0
        for candidato in candidatos:
            if id(candidato) in tomadas:
                continue
            ratio = SequenceMatcher(None, unidad.text.lower(), candidato.text.lower()).ratio()
            if ratio > mejor_ratio:
                mejor, mejor_ratio = candidato, ratio

        if mejor is not None and mejor_ratio >= TEXT_PAIR_RATIO:
            pairs.append((unidad, mejor))
            tomadas.add(id(mejor))
        else:
            huerfanas_finales.append(unidad)

    huerfanas = huerfanas_finales
    missing = [u for u in restantes_en if id(u) not in tomadas]

    return pairs, huerfanas, missing
