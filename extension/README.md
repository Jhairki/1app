# QA Page Exporter

Extensión de Chrome de un solo botón: guarda el HTML ya cargado de la
pestaña activa a un archivo. Sirve para el caso en que el sitio original de
un Stare and Compare bloquea pedidos automatizados (por ejemplo, un desafío
anti-bot de Cloudflare) y por eso `compare.py` no lo puede pedir en vivo.

La idea: **navegás cada página vos, como cualquier visitante** — así es como
se resuelve el desafío — y con un clic guardás el HTML que ya viste. Después
`compare.py --source-dir` compara esos archivos contra la copia, que sí se
puede pedir en vivo sin problema.

## Instalar

1. `chrome://extensions`
2. Activar "Modo de desarrollador" (arriba a la derecha)
3. "Cargar descomprimida" → elegir esta carpeta (`extension/`)

## Usar

1. Navegá a la página del sitio original que querés comparar.
2. Click en el ícono de la extensión → "Guardar HTML de esta página".
3. Se descarga un `.html` con el nombre derivado del path de la URL (por
   ejemplo, `/service/hours/` se guarda como `service_hours.html`; la
   portada, `/`, como `home.html`).
4. Repetí para cada página de la lista, y mové todos los `.html` descargados
   a una misma carpeta.

## Lista de paths guardados

Cada vez que guardás una página, la extensión recuerda su path (en orden,
sin duplicados) para toda esta sesión del navegador. "Copiar paths" copia
esa lista al portapapeles, un path por línea — lista para pegar directo en
"Paths on the source site" del formulario web, o en un archivo para
`--paths-file`. Así no hace falta reconstruir a mano qué paths se guardaron,
ni adivinarlos a partir del nombre del archivo (que es ambiguo: un `_` ahí
puede venir de una barra del path o de un guion bajo real).

"Reiniciar lista" la vacía, para arrancar una tanda nueva con otro sitio.

## Popups en la página

Al abrir el popup, la extensión también busca en la página los mismos
disparadores de popup que reconoce el resto de la herramienta
(`data-toggle="popover"/"tooltip"/"modal"`, o `class="dialog"` con
`data-el`/`data-href`) y los lista, con una sugerencia de cómo probarlos
(hover o click).

**Esto solo avisa dónde probar a mano — no confirma que abran.** No hay
forma automática de verificarlo aquí: eso necesitaría un navegador
automatizado pegándole al sitio bloqueado, que es exactamente lo que no se
puede hacer. Click en "Ubicar" hace scroll hasta el disparador y lo resalta
en rojo por un momento, para encontrarlo rápido en la página y probarlo con
tu propio mouse.

## Usar los archivos guardados

```bash
python compare.py --source https://oldsite.com --copy new.cms.dealer.com \
  --source-dir ./paginas-guardadas \
  --paths /service/hours/ / \
  --copy-paths /service-hours.htm /index.htm
```

`--source` sigue siendo obligatorio (identifica el dominio para los links
"Source" del reporte y para detectar si la copia sigue apuntando al sitio
viejo), pero con `--source-dir` el HTML de ese lado no se pide por red: se
lee del archivo que le corresponda a cada path, con el mismo nombre que
genera esta extensión. Si falta el archivo de algún path, `compare.py` lo
avisa en vez de fallar en silencio.
