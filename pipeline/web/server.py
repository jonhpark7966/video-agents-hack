"""Review page for a loop run.

  python3 pipeline/web/server.py
  open http://127.0.0.1:8765

Serves the history in runs/*/manifest.json and saves ranks to runs/<clip>/ranks.json.
The loop reads that file at the start of the next iteration.
"""

import json
import mimetypes
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNS = os.path.join(ROOT, "runs")
SAMPLES = os.path.join(ROOT, "samples")
PAGE = os.path.join(os.path.dirname(__file__), "index.html")
PORT = int(os.environ.get("PORT", "8765"))


def run_names():
    if not os.path.isdir(RUNS):
        return []
    found = []
    for name in os.listdir(RUNS):
        manifest = os.path.join(RUNS, name, "manifest.json")
        if os.path.isfile(manifest):
            found.append((os.path.getmtime(manifest), name))
    found.sort(reverse=True)
    return [name for _, name in found]


def read_json(path):
    with open(path) as handle:
        return json.load(handle)


def manifest_for(name):
    path = os.path.join(RUNS, name, "manifest.json")
    data = read_json(path)
    ranks_path = os.path.join(RUNS, name, "ranks.json")
    if os.path.isfile(ranks_path):
        data["ranks"] = read_json(ranks_path)
    data["runs"] = run_names()
    data["run"] = name
    return data


def safe_file(root, rel):
    rel = rel.replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/"):
        return None
    path = os.path.realpath(os.path.join(root, rel))
    root = os.path.realpath(root)
    if path != root and not path.startswith(root + os.sep):
        return None
    if not os.path.isfile(path):
        return None
    return path


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("  web", fmt % args, flush=True)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send_bytes(200, "text/html; charset=utf-8", open(PAGE, "rb").read())
            return
        if path == "/api/manifest":
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            wanted = ""
            for part in query.split("&"):
                if part.startswith("run="):
                    wanted = part[4:]
            names = run_names()
            name = wanted if wanted in names else (names[0] if names else "")
            if not name:
                body = {"status": "idle", "phase": "no run yet", "runs": [], "iterations": []}
            else:
                body = manifest_for(name)
            self._send_bytes(200, "application/json", json.dumps(body).encode())
            return
        if path.startswith("/media/runs/"):
            self._file(safe_file(RUNS, path[len("/media/runs/"):]))
            return
        if path.startswith("/media/samples/"):
            self._file(safe_file(SAMPLES, path[len("/media/samples/"):]))
            return
        self.send_error(404)

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/api/ranks":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send_bytes(400, "application/json", b'{"error":"bad json"}')
            return
        name = str(body.get("run") or "")
        if not name or name not in run_names():
            self._send_bytes(404, "application/json", b'{"error":"unknown run"}')
            return
        items = []
        for item in body.get("items") or []:
            if not isinstance(item, dict):
                continue
            try:
                rank = int(item.get("rank"))
                iteration = int(item.get("iteration"))
            except (TypeError, ValueError):
                continue
            if not 1 <= rank <= 9:
                continue
            variant = str(item.get("variant") or "")
            if not variant or "/" in variant or ".." in variant:
                continue
            items.append({
                "iteration": iteration,
                "variant": variant,
                "style": str(item.get("style") or ""),
                "rank": rank,
            })
        payload = {
            "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "note": str(body.get("note") or "")[:2000],
            "items": items,
        }
        dest = os.path.join(RUNS, name, "ranks.json")
        tmp = dest + ".tmp"
        with open(tmp, "w") as handle:
            json.dump(payload, handle, indent=2)
        os.replace(tmp, dest)
        self._send_bytes(200, "application/json", json.dumps({"ok": True, "saved": len(items)}).encode())

    def _file(self, path):
        if path is None:
            self.send_error(404)
            return
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        size = os.path.getsize(path)
        range_header = self.headers.get("Range")
        if range_header and range_header.startswith("bytes="):
            spec = range_header[6:].split(",", 1)[0]
            start_s, _, end_s = spec.partition("-")
            try:
                start = int(start_s) if start_s else 0
                end = int(end_s) if end_s else size - 1
            except ValueError:
                self.send_error(416)
                return
            end = min(end, size - 1)
            if start > end or start < 0:
                self.send_error(416)
                return
            length = end - start + 1
            self.send_response(206)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self._stream(path, start, length)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self._stream(path, 0, size)

    def _stream(self, path, start, length):
        try:
            with open(path, "rb") as handle:
                handle.seek(start)
                left = length
                while left > 0:
                    chunk = handle.read(min(65536, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return

    def _send_bytes(self, code, ctype, data):
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return


class ReviewServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, request, client_address):
        err = sys.exception()
        if isinstance(err, (BrokenPipeError, ConnectionResetError, TimeoutError)):
            return
        super().handle_error(request, client_address)


if __name__ == "__main__":
    server = ReviewServer(("127.0.0.1", PORT), Handler)
    print(f"review page  http://127.0.0.1:{PORT}", flush=True)
    server.serve_forever()
