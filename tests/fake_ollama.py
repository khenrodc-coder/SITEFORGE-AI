"""A tiny fake Ollama server for tests, so no real model is needed."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeOllama:
    def __init__(self):
        self.models = ["llama3.1:8b"]
        self.chat_content = json.dumps({
            "site_name": "Kuya's Ramen",
            "tagline": "Slow-simmered ramen, open past midnight.",
            "category": "restaurant",
        })
        self.chat_status = 200
        self.chat_body_override = None   # send this raw text instead of the normal body
        self.responder = None            # function(request_body) -> text, overrides chat_content
        self.delay = 0
        self.requests = []

        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status, body):
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass   # client already gave up (timeout test)

            def do_GET(self):
                if self.path == "/api/tags":
                    self._send(200, {"models": [{"name": name} for name in owner.models]})
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                owner.requests.append(body)
                if owner.delay:
                    time.sleep(owner.delay)
                if owner.chat_status == 404:
                    self._send(404, {"error": f'model "{body.get("model")}" not found, try pulling it first'})
                elif owner.chat_status != 200:
                    self._send(owner.chat_status, {"error": "boom"})
                elif owner.chat_body_override is not None:
                    self._send(200, owner.chat_body_override.encode())
                else:
                    content = owner.responder(body) if owner.responder else owner.chat_content
                    self._send(200, {"message": {"role": "assistant", "content": content}, "done": True})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
