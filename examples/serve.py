# -*- coding: utf-8 -*-
"""最小可用后端：把 Checker 包成两个 HTTP 接口，给前端 update-check.js 用。

    python examples/serve.py --current 1.2.0 \
        --lanzou-folder https://example.lanzou?.com/bXXXXXXXX --lanzou-pwd ****

    GET  /                 → 演示页（web/update-check.js）
    GET  /api/update/check → 检查结果 JSON（服务端缓存，重启即失效）
    POST /api/open_url     → {"url": "..."} 用系统浏览器打开下载页（有域名白名单）

只依赖标准库。生产上换成你程序里已有的 HTTP 框架即可——接口形状不变。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nou import Checker                     # noqa: E402
from nou.sources import LanzouFolder, StaticJson  # noqa: E402

# 允许开浏览器的域名后缀。**必须**白名单，否则就是一个「任意 URL」后门。
OPEN_URL_ALLOW = (".github.com", ".lanzoue.com", ".lanzoup.com", ".lanzoux.com",
                  ".lanzoui.com", ".lanzoub.com")

STATIC = ROOT / "web"


def make_handler(checker: Checker):
    class H(BaseHTTPRequestHandler):
        server_version = "nou-demo"

        def log_message(self, fmt, *args):        # 安静点
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urllib.parse.urlsplit(self.path).path
            if path in ("/", "/index.html"):
                return self._file(STATIC / "demo.html", "text/html; charset=utf-8")
            if path == "/update-check.js":
                return self._file(STATIC / "update-check.js",
                                  "application/javascript; charset=utf-8")
            if path == "/api/update/check":
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                force = q.get("force", ["0"])[0] not in ("0", "", "false")
                return self._json(checker.check(force=force).to_dict())
            return self._json({"ok": False, "error": "not found"}, 404)

        def do_POST(self):
            if urllib.parse.urlsplit(self.path).path != "/api/open_url":
                return self._json({"ok": False, "error": "not found"}, 404)
            n = int(self.headers.get("Content-Length") or 0)
            try:
                data = json.loads(self.rfile.read(n) or b"{}")
            except Exception:                     # noqa: BLE001
                return self._json({"ok": False, "error": "bad json"}, 400)
            url = str(data.get("url") or "").strip()
            if not _allowed(url):
                return self._json({"ok": False, "error": "域名不在白名单"}, 400)
            try:
                webbrowser.open(url)
            except Exception as e:                # noqa: BLE001
                return self._json({"ok": False, "error": str(e)[:120]}, 500)
            return self._json({"ok": True})

        def _file(self, p: Path, ctype: str):
            if not p.exists():
                return self._json({"ok": False, "error": "missing " + p.name}, 404)
            body = p.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return H


def _allowed(url: str) -> bool:
    try:
        u = urllib.parse.urlsplit(url)
    except Exception:                             # noqa: BLE001
        return False
    if u.scheme not in ("https",):
        return False
    host = (u.hostname or "").lower()
    return any(host == a.lstrip(".") or host.endswith(a) for a in OPEN_URL_ALLOW)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--current", required=True)
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--lanzou-folder")
    ap.add_argument("--lanzou-pwd", default=os.environ.get("NOU_LANZOU_PWD", ""))
    ap.add_argument("--lanzou-dl-host", default="")
    ap.add_argument("--json-url")
    a = ap.parse_args(argv)

    srcs = []
    if a.lanzou_folder:
        srcs.append(LanzouFolder(a.lanzou_folder, password=a.lanzou_pwd,
                                 dl_host=a.lanzou_dl_host or
                                 urllib.parse.urlsplit(a.lanzou_folder).netloc))
    if a.json_url:
        srcs.append(StaticJson(a.json_url))
    if not srcs:
        ap.error("至少给一个源")

    ck = Checker(current=a.current, sources=srcs)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(ck))
    print("http://127.0.0.1:%d/  (Ctrl+C 退出)" % a.port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
