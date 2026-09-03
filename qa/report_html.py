"""Reporte HTML con el formato de Test & Feedback que ya usa el equipo.

Copia la estructura del export de la extension: cabecera con estadisticas,
tabla de contenido con anclas, y despues cada bug con su numero, la hora, el
titulo en los cuatro campos, la descripcion y el enlace a la pagina.

La idea es que el reporte que sale de la herramienta se vea y se lea igual que
el que hace una persona a mano, para que no haya que traducir de un formato al
otro antes de compartirlo.

Un bug que aparece en varias paginas se reporta UNA vez con la lista de paths,
que es lo que pide el documento de proceso.
"""

import html as html_mod
from datetime import datetime

from qa.bugreport import CRITICAL, ISSUE, QUESTION, classify, describe, group_repeated

COLOR = {
    CRITICAL: ("#c4314b", "#fdf2f4"),
    ISSUE: ("#c07800", "#fdf6e9"),
    QUESTION: ("#0078d4", "#eff6fc"),
}


def _e(texto) -> str:
    return html_mod.escape(str(texto or ""))


def _stat(nombre: str, valor: str) -> str:
    return (f'<div class="stat"><div class="statName">{_e(nombre)}</div>'
            f'<div class="statValue">{_e(valor)}</div></div>')


def _url_de(result, paths: list[str]) -> str:
    """La URL de la primera pagina donde aparece el bug."""
    for page in result.pages:
        if page.path in paths:
            return (getattr(page, "spanish_url", None)
                    or getattr(page, "copy_url", "") or "")
    return ""


def build(result, device: str = "D", title: str = "QA Report",
          started: datetime = None, shots: dict = None) -> str:
    """Arma el HTML completo del reporte."""
    grupos = group_repeated(result, device)
    shots = shots or {}
    ahora = datetime.now()
    started = started or ahora
    resumen = result.summary()

    site = getattr(result, "copy_site", None) or result.base_url
    source = getattr(result, "source_site", "")

    # --- tabla de contenido ---
    toc = []
    for i, g in enumerate(grupos, 1):
        importancia = g["bug"].split(" | ")[1]
        color, fondo = COLOR.get(importancia, ("#605e5c", "#f3f2f1"))
        toc.append(
            f'<a class="tocRow" href="#bug{i}">'
            f'<span class="tocId">Bug {i}</span>'
            f'<span class="tocBadge" style="color:{color};background:{fondo}">{_e(importancia)}</span>'
            f'<span class="tocTitle">{_e(g["bug"])}</span>'
            f'<span class="tocPages">{len(g["paths"])} page{"s" if len(g["paths"]) > 1 else ""}</span>'
            f'</a>'
        )

    # --- los bugs ---
    bugs = []
    for i, g in enumerate(grupos, 1):
        partes = g["bug"].split(" | ", 3)
        f1, f2, f3, f4 = (partes + ["", "", "", ""])[:4]
        color, fondo = COLOR.get(f2, ("#605e5c", "#f3f2f1"))
        url = _url_de(result, g["paths"])

        paths_html = "".join(
            f'<li><code>{_e(p)}</code></li>' for p in g["paths"][:25]
        )
        if len(g["paths"]) > 25:
            paths_html += f'<li class="muted">…and {len(g["paths"]) - 25} more</li>'

        imagenes = shots.get(g["bug"], [])
        shots_html = ""
        if imagenes:
            tarjetas = "".join(
                f'<figure class="shot">'
                f'<figcaption>{_e(img["label"])}</figcaption>'
                f'<img src="{img["src"]}" alt="{_e(img["label"])}" loading="lazy">'
                f'</figure>'
                for img in imagenes
            )
            shots_html = f'<div class="label">Screenshots</div><div class="shots">{tarjetas}</div>'

        repetido = ""
        if len(g["paths"]) > 1:
            repetido = (
                '<p class="repeated"><strong>Same bug on '
                f'{len(g["paths"])} pages.</strong> Per the QA process, check with '
                'whoever worked on the request instead of filing it once per page.</p>'
            )

        bugs.append(f'''
    <div class="bug" id="bug{i}">
      <div class="bugHead">
        <span class="bugId">Bug {i}</span>
        <span class="bugDate">{_e(ahora.strftime("%m/%d/%Y %I:%M %p"))}</span>
      </div>
      <h2 class="bugTitle">
        <span class="f f1">{_e(f1)}</span><span class="sep">|</span>
        <span class="f f2" style="color:{color};background:{fondo}">{_e(f2)}</span><span class="sep">|</span>
        <span class="f f3">{_e(f3)}</span><span class="sep">|</span>
        <span class="f4">{_e(f4)}</span>
      </h2>
      <div class="bugBody">
        {repetido}
        <div class="label">Pages</div>
        <ul class="paths">{paths_html}</ul>
        {shots_html}
        {f'<div class="label">Source</div><a class="src" href="{_e(url)}" target="_blank" rel="noopener">{_e(url)}</a>' if url else ''}
      </div>
    </div>''')

    filed = len(grupos)
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: #faf9f8; color: #201f1e;
    font: 14px/1.5 "Segoe UI", system-ui, -apple-system, sans-serif;
  }}
  .wrap {{ max-width: 1000px; margin: 0 auto; padding: 0 24px 80px; }}
  header {{ background: #fff; border-bottom: 1px solid #edebe9; }}
  header .wrap {{ padding: 26px 24px; }}
  h1 {{ font-size: 22px; font-weight: 600; margin: 0 0 4px; }}
  .sub {{ color: #605e5c; font-size: 13px; margin: 0; }}
  .sub code {{ font-size: 12.5px; }}

  .stats {{ display: flex; flex-wrap: wrap; gap: 34px; margin-top: 22px; }}
  .statName {{ color: #605e5c; font-size: 12px; margin-bottom: 2px; }}
  .statValue {{ font-size: 15px; font-weight: 600; }}

  h2.section {{
    font-size: 15px; font-weight: 600; margin: 34px 0 12px;
    padding-bottom: 8px; border-bottom: 1px solid #edebe9;
  }}

  .toc {{ background: #fff; border: 1px solid #edebe9; border-radius: 2px; }}
  .tocRow {{
    display: flex; gap: 12px; align-items: baseline; padding: 11px 16px;
    border-bottom: 1px solid #f3f2f1; text-decoration: none; color: inherit;
  }}
  .tocRow:last-child {{ border-bottom: 0; }}
  .tocRow:hover {{ background: #f3f2f1; }}
  .tocId {{ flex: 0 0 54px; color: #0078d4; font-weight: 600; font-size: 13px; }}
  .tocBadge {{
    flex: 0 0 auto; font-size: 11px; font-weight: 600; padding: 1px 8px;
    border-radius: 2px;
  }}
  .tocTitle {{
    flex: 1 1 auto; font-size: 13px; overflow: hidden;
    text-overflow: ellipsis; white-space: nowrap;
  }}
  .tocPages {{ flex: 0 0 auto; color: #605e5c; font-size: 12px; }}

  .bug {{
    background: #fff; border: 1px solid #edebe9; border-radius: 2px;
    margin-bottom: 14px; scroll-margin-top: 16px;
  }}
  .bugHead {{
    display: flex; gap: 14px; align-items: baseline;
    padding: 12px 18px 0;
  }}
  .bugId {{ color: #0078d4; font-weight: 600; font-size: 14px; }}
  .bugDate {{ color: #605e5c; font-size: 12px; }}
  .bugTitle {{
    font-size: 15px; font-weight: 600; margin: 6px 0 0; padding: 0 18px 14px;
    border-bottom: 1px solid #f3f2f1; line-height: 1.55;
  }}
  .f {{ font-weight: 600; }}
  .f2 {{ padding: 1px 8px; border-radius: 2px; }}
  .sep {{ color: #a19f9d; margin: 0 6px; font-weight: 400; }}
  .f4 {{ font-weight: 400; }}
  .bugBody {{ padding: 14px 18px 18px; }}
  .label {{
    font-size: 11px; text-transform: uppercase; letter-spacing: .04em;
    color: #605e5c; font-weight: 600; margin: 14px 0 6px;
  }}
  .bugBody .label:first-child {{ margin-top: 0; }}
  .paths {{ margin: 0; padding-left: 20px; }}
  .paths li {{ margin-bottom: 3px; }}
  code {{
    font-family: Consolas, ui-monospace, monospace; font-size: 12.5px;
    background: #f3f2f1; padding: 1px 5px; border-radius: 2px;
  }}
  .src {{ color: #0078d4; font-size: 13px; word-break: break-all; }}
  .repeated {{
    background: #fdf6e9; border-left: 3px solid #c07800;
    padding: 10px 14px; margin: 0 0 14px; font-size: 13px;
  }}
  .shots {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: 14px; margin-bottom: 4px;
  }}
  .shot {{ margin: 0; }}
  .shot figcaption {{
    font-size: 11px; text-transform: uppercase; letter-spacing: .04em;
    color: #605e5c; font-weight: 600; margin-bottom: 5px;
  }}
  .shot img {{
    max-width: 100%; border: 1px solid #edebe9; border-radius: 2px; display: block;
  }}
  .muted {{ color: #605e5c; }}
  footer {{ margin-top: 40px; color: #a19f9d; font-size: 12px; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #1b1a19; color: #f3f2f1; }}
    header, .toc, .bug {{ background: #252423; border-color: #3b3a39; }}
    .tocRow {{ border-color: #323130; }}
    .tocRow:hover {{ background: #323130; }}
    .bugTitle {{ border-color: #323130; }}
    code {{ background: #323130; }}
    h2.section {{ border-color: #3b3a39; }}
    .sub, .statName, .bugDate, .tocPages, .label, .muted {{ color: #a19f9d; }}
    .repeated {{ background: #2b2415; }}
    .shot img {{ border-color: #3b3a39; }}
    .shot figcaption {{ color: #a19f9d; }}
  }}
</style>
</head>
<body>
<header>
  <div class="wrap">
    <h1>{_e(title)}</h1>
    <p class="sub">
      {"Migrated site <code>" + _e(site) + "</code> against source <code>" + _e(source) + "</code>" if source else "Site <code>" + _e(site) + "</code>"}
    </p>
    <div class="stats">
      {_stat("Started On", started.strftime("%m/%d/%Y %I:%M %p"))}
      {_stat("Exported On", ahora.strftime("%m/%d/%Y %I:%M %p"))}
      {_stat("Bugs Filed", str(filed))}
      {_stat("Pages Checked", str(resumen["pages_scanned"]))}
      {_stat("Texts Checked", str(resumen["units_checked"]))}
      {_stat("Device", "Desktop" if device == "D" else "Mobile")}
    </div>
  </div>
</header>

<div class="wrap">
  <h2 class="section">Contents</h2>
  <div class="toc">
    {"".join(toc) if toc else '<div class="tocRow"><span class="muted">No bugs found.</span></div>'}
  </div>

  <h2 class="section">Bugs</h2>
  {"".join(bugs) if bugs else '<p class="muted">Nothing to report — the pages checked out clean.</p>'}

  <footer>
    Generated by the QA tool, in the Test &amp; Feedback report format used by the team.
  </footer>
</div>
</body>
</html>
'''


def write(result, path, device: str = "D", title: str = "QA Report",
          shots: dict = None) -> int:
    """Guarda el reporte y devuelve cuantos bugs quedaron."""
    contenido = build(result, device, title, shots=shots)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(contenido)
    return len(group_repeated(result, device))
