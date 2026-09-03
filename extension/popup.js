// Guarda el HTML ya renderizado de la pestaña activa a un archivo .html.
//
// El nombre del archivo sigue el mismo algoritmo que qa/migration.py usa
// para buscarlo (_local_filename): el path de la URL, sin barras al
// principio/final, con las barras internas cambiadas por "_". Si cambia uno,
// tiene que cambiar el otro, o el modo --source-dir no va a encontrar nada.
function nombreDeArchivo(pathname) {
  const limpio = (pathname || "/").replace(/^\/+|\/+$/g, "").replace(/\//g, "_");
  return (limpio || "home") + ".html";
}

const boton = document.getElementById("save");
const estado = document.getElementById("status");

function mostrar(texto, clase) {
  estado.textContent = texto;
  estado.className = clase || "";
}

boton.addEventListener("click", async () => {
  boton.disabled = true;
  mostrar("Guardando...");

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.id) {
      throw new Error("No se encontro la pestaña activa.");
    }

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
