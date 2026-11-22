"""Connection to the local Ollama server.

Uses only the Python standard library. Every failure is turned into one of the
OllamaError classes below, each carrying a message that is safe to show to the user.
"""
import http.client
import json
import urllib.error
import urllib.request
from urllib.parse import urlparse

MAX_RESPONSE_BYTES = 4 * 1024 * 1024   # refuse absurdly large replies
STATUS_TIMEOUT = 5                     # seconds for the quick "is it running?" check


class OllamaError(Exception):
    """Base class. `code` and `http_status` are used by the API layer."""

    code = "ollama_error"
    http_status = 502

    def __init__(self, message):
        super().__init__(message)
        self.message = message


class OllamaUnavailableError(OllamaError):
    code = "ollama_unavailable"
    http_status = 503


class OllamaModelMissingError(OllamaError):
    code = "model_not_installed"
    http_status = 503


class OllamaTimeoutError(OllamaError):
    code = "ollama_timeout"
    http_status = 504


class OllamaResponseError(OllamaError):
    code = "ollama_bad_response"
    http_status = 502


class OllamaClient:
    def __init__(self, base_url, model, timeout=300):
        parsed = urlparse(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("OLLAMA_BASE_URL must start with http:// or https://")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        # An empty ProxyHandler stops Windows/system proxy settings from
        # intercepting requests to the local Ollama server.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    # ------------------------------------------------------------ low level
    def _missing_model_message(self):
        return f'The model "{self.model}" is not installed. Run: ollama pull {self.model}'

    def _request(self, method, path, payload=None, timeout=None):
        headers = {"Accept": "application/json"}
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)

        try:
            with self._opener.open(request, timeout=timeout or self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read(2048).decode("utf-8", errors="replace")
            except OSError:
                pass
            if exc.code == 404 and "not found" in detail.lower():
                raise OllamaModelMissingError(self._missing_model_message()) from exc
            raise OllamaResponseError(f"Ollama returned an error (HTTP {exc.code}).") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise self._timeout_error() from exc
            raise self._unavailable_error() from exc
        except TimeoutError as exc:
            raise self._timeout_error() from exc
        except http.client.HTTPException as exc:
            raise OllamaResponseError("Ollama sent an incomplete answer.") from exc
        except OSError as exc:
            raise self._unavailable_error() from exc

        if len(raw) > MAX_RESPONSE_BYTES:
            raise OllamaResponseError("Ollama sent an answer that was too large.")
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise OllamaResponseError("Ollama sent an answer that could not be read.") from exc

    def _unavailable_error(self):
        return OllamaUnavailableError(
            f"SiteForge could not reach Ollama at {self.base_url}. Start Ollama, then try again."
        )

    def _timeout_error(self):
        return OllamaTimeoutError(
            "The model took too long to answer. Try a shorter description, "
            "a smaller model, or raise OLLAMA_TIMEOUT in your .env file."
        )

    # ------------------------------------------------------------ public API
    def list_models(self):
        """Names of the models installed in Ollama."""
        data = self._request("GET", "/api/tags", timeout=STATUS_TIMEOUT)
        models = data.get("models") if isinstance(data, dict) else None
        if not isinstance(models, list):
            raise OllamaResponseError("Ollama sent an unexpected model list.")
        return [item["name"] for item in models if isinstance(item, dict) and isinstance(item.get("name"), str)]

    def status(self):
        """Describe the connection without ever raising an error."""
        info = {
            "reachable": False,
            "model": self.model,
            "model_installed": False,
            "installed_models": [],
            "message": "",
        }
        try:
            models = self.list_models()
        except OllamaError as exc:
            info["message"] = exc.message
            return info

        info["reachable"] = True
        info["installed_models"] = models[:20]
        wanted = {self.model, f"{self.model}:latest"} if ":" not in self.model else {self.model}
        info["model_installed"] = any(name in wanted for name in models)
        info["message"] = "Ready." if info["model_installed"] else self._missing_model_message()
        return info

    def chat_json(self, system_prompt, user_prompt, temperature=0.7, max_tokens=400):
        """Ask the model for a JSON object and return it as a Python dict."""
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "keep_alive": "10m",
            "options": {"temperature": temperature, "num_predict": max_tokens},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        data = self._request("POST", "/api/chat", payload)

        message = data.get("message") if isinstance(data, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise OllamaResponseError("The model returned an empty answer. Please try again.")
        try:
            result = json.loads(content)
        except ValueError as exc:
            raise OllamaResponseError("The model did not return valid JSON. Please try again.") from exc
        if not isinstance(result, dict):
            raise OllamaResponseError("The model returned an unexpected answer. Please try again.")
        return result


def client_from_config(config):
    """Build an OllamaClient from the Flask config."""
    try:
        return OllamaClient(config["OLLAMA_BASE_URL"], config["OLLAMA_MODEL"], config["OLLAMA_TIMEOUT"])
    except ValueError as exc:
        raise OllamaUnavailableError(str(exc)) from exc
