"""Cliente de un modelo local via Ollama.

Regla de oro de este modulo: NUNCA levanta una excepcion hacia arriba y NUNCA
bloquea indefinidamente. Si el modelo no esta, tarda, o responde basura,
devuelve None y el QA sigue su curso sin enterarse.

Se usa requests directo en vez de langchain-ollama: la llamada es un POST a
/api/generate y no vale la pena arrastrar una dependencia para eso.
"""

import json
import logging
import os
import re

import requests

logger = logging.getLogger(__name__)

DEFAULT_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")

# Un modelo local no puede frenar un escaneo. Si tarda mas que esto, se descarta.
HEALTH_TIMEOUT = 2
GENERATE_TIMEOUT = 45

JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


class LocalModel:
    """Envoltorio a prueba de fallos sobre Ollama."""

    def __init__(self, host: str = DEFAULT_HOST, model: str = DEFAULT_MODEL,
                 timeout: int = GENERATE_TIMEOUT):
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._available = None
        self._installed_models: list[str] = []

    # ---------- disponibilidad ----------

    def available(self) -> bool:
        """True si Ollama responde y el modelo pedido esta descargado."""
        if self._available is not None:
            return self._available

        try:
            response = requests.get(f"{self.host}/api/tags", timeout=HEALTH_TIMEOUT)
            response.raise_for_status()
            tags = response.json().get("models", [])
            self._installed_models = [m.get("name", "") for m in tags]
        except Exception as exc:
            logger.info("Ollama no responde en %s (%s). El QA sigue sin IA.", self.host, exc)
            self._available = False
            return False

        # Ollama nombra los modelos 'qwen2.5:7b'; aceptamos tambien 'qwen2.5'
        base = self.model.split(":")[0]
        self._available = any(
            name == self.model or name.split(":")[0] == base
            for name in self._installed_models
        )
        if not self._available:
            logger.warning(
                "Ollama esta arriba pero no tiene %s. Modelos disponibles: %s",
                self.model, ", ".join(self._installed_models) or "ninguno",
            )
        return self._available

    def status(self) -> dict:
        """Estado legible, para mostrarlo en la web."""
        ok = self.available()
        return {
            "available": ok,
            "host": self.host,
            "model": self.model,
            "installed": self._installed_models,
            "reason": (
                "" if ok
                else ("Ollama no responde" if not self._installed_models
                      else f"El modelo {self.model} no esta descargado")
            ),
        }

    # ---------- generacion ----------

    def complete(self, prompt: str, system: str = "", temperature: float = 0.1):
        """Devuelve el texto generado, o None ante cualquier problema."""
        if not self.available():
            return None

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": 400},
        }
        if system:
            payload["system"] = system

        try:
            response = requests.post(
                f"{self.host}/api/generate", json=payload, timeout=self.timeout
            )
            response.raise_for_status()
            return response.json().get("response", "").strip()
        except Exception as exc:
            logger.warning("La llamada al modelo local fallo: %s", exc)
            return None

    def complete_json(self, prompt: str, system: str = "", temperature: float = 0.1):
        """Igual que complete() pero parsea JSON. None si no sale JSON valido."""
        raw = self.complete(prompt, system, temperature)
        if not raw:
            return None

        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        match = JSON_BLOCK.search(text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        logger.warning("El modelo no devolvio JSON valido: %r", raw[:200])
        return None
