"""Portail FiPu : une seule adresse pour Repères, Veille et Données.

    python3 serve.py            # ouvre http://127.0.0.1:8760 dans le navigateur
    python3 serve.py --no-open

Chaque outil garde son dossier, sa page et son propre serve.py ; le portail se contente de
servir leurs pages (avec une barre de navigation commune), de lancer leurs collectes dans
un processus séparé et de répondre aux requêtes de la page Données.
Le serveur n'écoute que sur la machine locale (127.0.0.1).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import threading
import traceback
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

HERE = Path(__file__).parent
BERCY = HERE.parent

TOOLS = {
    "reperes": {"label": "Repères", "dir": BERCY / "reperes-fipu", "page": "dist/reperes-fipu.html", "build": "build.py",
                "desc": "Qui est en poste, gouvernement, Journal officiel, chiffres clés, historique, cadre et calendrier."},
    "veille": {"label": "Veille", "dir": BERCY / "veille-fipu", "page": "dist/veille-fipu.html", "build": "build.py",
               "desc": "Publications des institutions, organisations internationales, think tanks et presse, classées par mots-clés."},
    "donnees": {"label": "Données", "dir": BERCY / "donnees-fipu", "page": "page.html", "build": None,
                "desc": "Séries Eurostat et Insee : recherche, graphiques, comparaisons, révisions, export Excel."},
}

# La page Données est servie par ce processus : ses modules sont importés ici. Les autres outils
# ne sont jamais importés (noms de modules identiques d'un outil à l'autre) : ils tournent en sous-processus.
sys.path.insert(0, str(TOOLS["donnees"]["dir"]))
try:
    import web as donnees_web
except Exception:  # noqa: BLE001 — le portail reste utilisable sans la page Données
    donnees_web = None
    traceback.print_exc()

jobs = {k: {"running": False, "log": [], "started": None, "finished": None, "ok": None, "error": None} for k in TOOLS}
lock = threading.Lock()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_tool(tool, script="update.py"):
    """Lance `script` dans le dossier de l'outil ; la sortie alimente le journal affiché par la page."""
    t = TOOLS[tool]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    try:
        p = subprocess.Popen([sys.executable, script], cwd=t["dir"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace", env=env)
        for line in p.stdout:
            line = line.rstrip()
            print(f"[{tool}] {line}", flush=True)
            with lock:
                jobs[tool]["log"] = (jobs[tool]["log"] + [line])[-300:]
        code = p.wait()
        ok, err = code == 0, (None if code == 0 else f"{script} s'est terminé avec le code {code} (voir le journal)")
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        ok, err = False, f"{type(e).__name__}: {e}"
    with lock:
        jobs[tool].update(running=False, ok=ok, error=err, finished=now())


def start(tool, script="update.py"):
    with lock:
        if jobs[tool]["running"]:
            return False
        jobs[tool].update(running=True, log=[], ok=None, error=None, started=now(), finished=None)
    threading.Thread(target=run_tool, args=(tool, script), daemon=True).start()
    return True


NAV_CSS = """<style>
.fipu-portal{display:flex;align-items:center;gap:4px;flex-wrap:wrap;padding:6px max(16px,3vw);border-bottom:1px solid var(--line,#e2e0da);
background:var(--surface-2,#f0efeb);font:13px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif}
.fipu-portal b{font-weight:650;margin-right:10px;color:var(--ink,#16150f)}
.fipu-portal a{color:var(--ink-2,#52514e);padding:3px 9px;border-radius:6px;text-decoration:none}
.fipu-portal a:hover{background:var(--surface,#fcfcfb)}
.fipu-portal a[aria-current]{background:var(--surface,#fcfcfb);color:var(--ink,#16150f);font-weight:600;box-shadow:inset 0 0 0 1px var(--line,#e2e0da)}
.fipu-portal .home{margin-right:6px;color:var(--ink-3,#7c7a74)}
</style>"""


def nav(current, base="/", title="FiPu", home=None):
    """Barre commune ; `base`, `title` et `home` (lien de retour) servent à la version publiée (site/build.py)."""
    links = [("", "Accueil")] + [(k, t["label"]) for k, t in TOOLS.items()]
    items = "".join(f'<a href="{base}{k + "/" if k else ""}"{" aria-current=page" if k == current else ""}>{label}</a>' for k, label in links)
    back = f'<a class="home" href="{home[0]}">← {home[1]}</a>' if home else ""
    return f'{NAV_CSS}<nav class="fipu-portal" aria-label="Outils FiPu">{back}<b>{title}</b>{items}</nav>'


BODY_RE = re.compile(r"<body[^>]*>", re.I)
# Les pages de Repères et Veille appellent /api/… (adresse absolue, prévue pour leur propre serveur) :
# servies sous /reperes/ et /veille/, ces appels deviennent relatifs à leur dossier.
API_RE = re.compile(r"""(fetch\(\s*["'])/api/""")
# Liens d'un outil vers le serveur autonome d'un autre (ex. Veille → Repères) : redirigés vers le portail.
STANDALONE = {"http://127.0.0.1:8765/": "/reperes/", "http://127.0.0.1:8766/": "/veille/"}


def page_html(tool, **bar_opts):
    html = (HERE / "accueil.html" if not tool else TOOLS[tool]["dir"] / TOOLS[tool]["page"]).read_text(encoding="utf-8")
    html = API_RE.sub(r"\1api/", html)
    base = bar_opts.get("base", "/")
    for old, new in STANDALONE.items():
        html = html.replace(old, base + new.lstrip("/"))
    m = BODY_RE.search(html)
    bar = nav(tool or "", **bar_opts)
    return html[:m.end()] + bar + html[m.end():] if m else bar + html


def overview():
    out = {"tools": []}
    for k, t in TOOLS.items():
        page = t["dir"] / t["page"]
        with lock:
            job = {x: jobs[k][x] for x in ("running", "ok", "error", "finished")}
        mtime = None
        if t["build"] and page.exists():
            mtime = datetime.fromtimestamp(page.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
        out["tools"].append({"id": k, "label": t["label"], "desc": t["desc"], "installed": t["dir"].exists(),
                             "page": page.exists(), "generated": mtime, "job": job})
    if donnees_web:
        try:
            out["figures"] = donnees_web.resume({})["figures"]
            etat = donnees_web.etat({})
            runs = etat["runs"]
            out["donnees"] = {"n_series": etat["n_series"], "last": max((r["dernière collecte"] for r in runs), default=None),
                              "failed": [r["source"] for r in runs if not r["ok"]]}
        except Exception as e:  # noqa: BLE001
            out["donnees_error"] = f"{type(e).__name__}: {e}"
    return out


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        elif not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _route(self):
        u = urlsplit(self.path)
        parts = [p for p in u.path.split("/") if p]
        return u, parts

    def do_GET(self):
        u, parts = self._route()
        try:
            if not parts or parts == ["index.html"]:
                return self._send(200, page_html(None), "text/html; charset=utf-8")
            if parts == ["api", "overview"]:
                return self._send(200, overview())
            tool = parts[0]
            if tool not in TOOLS:
                return self._send(404, {"error": "introuvable"})
            if len(parts) == 1 and not u.path.endswith("/"):
                return self._send(301, b"", "text/plain", {"Location": f"/{tool}/" + (f"?{u.query}" if u.query else "")})
            if len(parts) == 1 or parts[1:] == ["index.html"]:
                t = TOOLS[tool]
                if not (t["dir"] / t["page"]).exists():
                    if t["build"] and t["dir"].exists():
                        start(tool, t["build"])  # page vide avec le bouton « Actualiser »
                        return self._send(503, "Page en cours de génération : recharger dans quelques secondes.", "text/plain; charset=utf-8", {"Refresh": "3"})
                    return self._send(404, f"{t['dir'].name} introuvable à côté du portail.", "text/plain; charset=utf-8")
                return self._send(200, page_html(tool), "text/html; charset=utf-8")
            if parts[1:] == ["api", "status"]:
                with lock:
                    return self._send(200, dict(jobs[tool]))
            if tool == "donnees" and len(parts) == 3 and parts[1] == "api":
                return self._donnees(parts[2], parse_qs(u.query))
            return self._send(404, {"error": "introuvable"})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def _donnees(self, route, q):
        if donnees_web is None:
            return self._send(503, {"error": "module Données non chargé (voir la console du portail)"})
        try:
            if route == "export":
                data, name = donnees_web.export(q)
                return self._send(200, data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                  {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})
            fn = donnees_web.ROUTES.get(route)
            if not fn:
                return self._send(404, {"error": "introuvable"})
            return self._send(200, fn(q))
        except (KeyError, ValueError) as e:
            return self._send(400, {"error": e.args[0] if e.args else str(e)})

    def do_POST(self):
        _, parts = self._route()
        if parts == ["api", "refresh-all"]:
            started = [k for k, t in TOOLS.items() if t["dir"].exists() and start(k)]
            return self._send(202, {"started": started})
        if len(parts) == 3 and parts[0] in TOOLS and parts[1:] == ["api", "refresh"]:
            if not start(parts[0]):
                return self._send(409, {"error": "actualisation déjà en cours"})
            return self._send(202, {"started": True})
        self._send(404, {"error": "introuvable"})

    def log_message(self, fmt, *args):
        pass  # silencieux : la progression des collectes est déjà affichée


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8760)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Portail FiPu : {url}  (Ctrl+C pour arrêter)")
    if not args.no_open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
