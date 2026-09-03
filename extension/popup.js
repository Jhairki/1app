// Guarda el HTML ya renderizado de la pestaña activa a un archivo .html, y
// avisa qué popups tiene la página para probarlos a mano mientras estás ahí.

// El nombre del archivo sigue el mismo algoritmo que qa/migration.py usa
// para buscarlo (local_filename): el path de la URL, sin barras al
// principio/final, con las barras internas cambiadas por "_". Si cambia uno,
// tiene que cambiar el otro, o el modo --source-dir no va a encontrar nada.
function nombreDeArchivo(pathname) {
  const limpio = (pathname || "/").replace(/^\/+|\/+$/g, "").replace(/\//g, "_");
  return (limpio || "home") + ".html";
}

// Se inyecta en la pestaña con chrome.scripting.executeScript -- corre en el
// contexto de la pagina, no en el de este popup. Mismos criterios que
// qa/extract.py::find_popup_elements y POPUP_TOGGLES: si uno cambia, el otro
// se desalinea de lo que scan.py/compare.py consideran un popup.
function _detectarPopupsEnLaPagina() {
  const POPUP_TOGGLES = ["popover", "tooltip", "modal"];
  const vistos = new Set();
  const encontrados = [];

  document.querySelectorAll("[data-toggle]").forEach((el) => {
    const toggle = (el.getAttribute("data-toggle") || "").toLowerCase();
    if (POPUP_TOGGLES.includes(toggle) && !vistos.has(el)) {
      vistos.add(el);
      encontrados.push({
        texto: el.textContent.trim().slice(0, 60)
          || el.getAttribute("data-title") || el.getAttribute("title") || "(sin texto)",
        tipo: toggle,
        // Solo un indicio -- el disparador real puede estar configurado
        // distinto (ver qa/browser.py, que lo lee del propio widget en vez
        // de asumirlo).
        sugerencia: toggle === "modal" ? "click" : "hover",
      });
    }
  });

  document.querySelectorAll(".dialog").forEach((el) => {
    if ((el.getAttribute("data-el") || el.getAttribute("data-href")) && !vistos.has(el)) {
      vistos.add(el);
      encontrados.push({
        texto: el.textContent.trim().slice(0, 60) || "(sin texto)",
        tipo: "dialog",
        sugerencia: "click",
      });
    }
  });

  return encontrados;
}

// Mismo criterio que _detectarPopupsEnLaPagina, para ubicar el elemento
// n-esimo en el mismo orden en que se listo.
function _resaltarPopupEnLaPagina(indice) {
  const POPUP_TOGGLES = ["popover", "tooltip", "modal"];
  const vistos = new Set();
  const elementos = [];

  document.querySelectorAll("[data-toggle]").forEach((el) => {
    const toggle = (el.getAttribute("data-toggle") || "").toLowerCase();
    if (POPUP_TOGGLES.includes(toggle) && !vistos.has(el)) {
      vistos.add(el);
      elementos.push(el);
    }
  });
  document.querySelectorAll(".dialog").forEach((el) => {
    if ((el.getAttribute("data-el") || el.getAttribute("data-href")) && !vistos.has(el)) {
      vistos.add(el);
      elementos.push(el);
    }
  });

  const el = elementos[indice];
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  const previoOutline = el.style.outline;
  const previoOffset = el.style.outlineOffset;
  el.style.outline = "3px solid #e53935";
  el.style.outlineOffset = "2px";
  setTimeout(() => {
    el.style.outline = previoOutline;
    el.style.outlineOffset = previoOffset;
  }, 2500);
}

const boton = document.getElementById("save");
const estado = document.getElementById("status");
const listaPopups = document.getElementById("popups");
const cargandoPopups = document.getElementById("popups-loading");
const sinPopups = document.getElementById("popups-empty");
const listaPaths = document.getElementById("lista-paths");
const contador = document.getElementById("contador");
const botonCopiar = document.getElementById("copiar");
const botonReiniciar = document.getElementById("reiniciar");

function mostrar(texto, clase) {
  estado.textContent = texto;
  estado.className = clase || "";
}

async function pestañaActiva() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.id) {
    throw new Error("No se encontro la pestaña activa.");
  }
  return tab;
}

// Recuerda, en orden, cada path guardado -- asi despues se puede copiar la
// lista entera y pegarla en "Paths on the source site" del formulario web,
// sin tener que reconstruirla a mano ni adivinarla a partir del nombre del
// archivo (que es ambiguo: un "_" en el nombre puede venir de una barra o de
// un guion bajo real del path).
const CLAVE_GUARDADOS = "guardados";

async function obtenerGuardados() {
  const datos = await chrome.storage.local.get({ [CLAVE_GUARDADOS]: [] });
  return datos[CLAVE_GUARDADOS];
}

async function agregarGuardado(path, filename) {
  const guardados = (await obtenerGuardados()).filter((g) => g.path !== path);
  guardados.push({ path, filename });
  await chrome.storage.local.set({ [CLAVE_GUARDADOS]: guardados });
  return guardados;
}

function pintarGuardados(guardados) {
  contador.textContent = guardados.length;
  listaPaths.innerHTML = "";
  for (const g of guardados) {
    const li = document.createElement("li");
    li.textContent = g.path;
    li.title = `${g.path} -> ${g.filename}`;
    listaPaths.appendChild(li);
  }
}

boton.addEventListener("click", async () => {
  boton.disabled = true;
  mostrar("Guardando...");

  try {
    const tab = await pestañaActiva();
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => ({ html: document.documentElement.outerHTML, path: location.pathname }),
    });

    const nombre = nombreDeArchivo(result.path);
    const blob = new Blob([result.html], { type: "text/html" });
    const url = URL.createObjectURL(blob);

    await chrome.downloads.download({ url, filename: nombre, saveAs: false });
    pintarGuardados(await agregarGuardado(result.path, nombre));
    mostrar(`Guardado como ${nombre}`, "ok");
  } catch (err) {
    mostrar("Error: " + err.message, "error");
  } finally {
    boton.disabled = false;
  }
});

botonCopiar.addEventListener("click", async () => {
  const guardados = await obtenerGuardados();
  if (!guardados.length) {
    mostrar("Todavía no guardaste ninguna página.", "error");
    return;
  }
  const texto = guardados.map((g) => g.path).join("\n");
  try {
    await navigator.clipboard.writeText(texto);
    mostrar(`Copiados ${guardados.length} path(s) al portapapeles`, "ok");
  } catch (err) {
    mostrar("No se pudo copiar: " + err.message, "error");
  }
});

botonReiniciar.addEventListener("click", async () => {
  await chrome.storage.local.set({ [CLAVE_GUARDADOS]: [] });
  pintarGuardados([]);
  mostrar("Lista reiniciada.");
});

async function resaltar(tabId, indice) {
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      func: _resaltarPopupEnLaPagina,
      args: [indice],
    });
  } catch (err) {
    // Nada critico -- a lo sumo no se ve el resaltado.
  }
}

async function cargarPopups() {
  try {
    const tab = await pestañaActiva();
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: _detectarPopupsEnLaPagina,
    });

    cargandoPopups.hidden = true;
    if (!result.length) {
      sinPopups.hidden = false;
      return;
    }

    result.forEach((popup, indice) => {
      const li = document.createElement("li");

      const info = document.createElement("div");
      info.className = "info";
      const texto = document.createElement("div");
      texto.className = "texto";
      texto.textContent = popup.texto;
      const detalle = document.createElement("div");
      detalle.className = "detalle";
      detalle.textContent = `${popup.tipo} · probar con ${popup.sugerencia}`;
      info.append(texto, detalle);

      const ubicar = document.createElement("button");
      ubicar.type = "button";
      ubicar.textContent = "Ubicar";
      ubicar.addEventListener("click", () => resaltar(tab.id, indice));

      li.append(info, ubicar);
      listaPopups.appendChild(li);
    });
  } catch (err) {
    cargandoPopups.hidden = true;
    sinPopups.hidden = false;
    sinPopups.textContent = "No se pudo revisar esta página: " + err.message;
  }
}

obtenerGuardados().then(pintarGuardados);
cargarPopups();
