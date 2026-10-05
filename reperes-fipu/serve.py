"""Sert la page en local et permet de l'actualiser depuis le bouton « Actualiser ».

    python3 serve.py            # ouvre http://127.0.0.1:8765 dans le navigateur
    python3 serve.py --no-open

Le serveur n'écoute que sur la machine locale (127.0.0.1).
"""
import argparse
import json
import threading
import traceback
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import update

ROOT = Path(__file__).parent
PAGE = ROOT / "dist" / "reperes-fipu.html"

state = {"running": False, "log": [], "started": None, "finished": None, "ok": None, "error": None}
lock = threading.Lock()


def _refresh():
    def progress(msg):
        with lock:
            state["log"].append(msg)
        print(msg, flush=True)
    try:
        update.run(progress=progress)
        ok, err = True, None
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        ok, err = False, f"{type(e).__name__}: {e}"
    with lock:
        state.update(running=False, ok=ok, error=err,
                     finished=datetime.now(timezone.utc).isoformat(timespec="seconds"))


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.split("?")[0] in ("/", "/index.html", "/reperes-fipu.html"):
            if not PAGE.exists():
                return self._send(503, "Page pas encore générée : cliquer sur Actualiser ou lancer update.py".encode(), "text/plain; charset=utf-8")
            return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/status":
            with lock:
                return self._send(200, dict(state))
        self._send(404, {"error": "introuvable"})

    def do_POST(self):
        if self.path != "/api/refresh":
            return self._send(404, {"error": "introuvable"})
        with lock:
            if state["running"]:
                return self._send(409, {"error": "actualisation déjà en cours"})
            state.update(running=True, log=[], ok=None, error=None,
                         started=datetime.now(timezone.utc).isoformat(timespec="seconds"), finished=None)
        threading.Thread(target=_refresh, daemon=True).start()
        self._send(202, {"started": True})

    def log_message(self, fmt, *args):
        pass  # silencieux : la progression est déjà affichée


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Repères FiPu : {url}  (Ctrl+C pour arrêter)")
    if not args.no_open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
