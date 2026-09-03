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
    mostrar(`Guardado como ${nombre}`, "ok");
  } catch (err) {
    mostrar("Error: " + err.message, "error");
  } finally {
    boton.disabled = false;
  }
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

cargarPopups();
