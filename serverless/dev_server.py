#!/usr/bin/env python3
"""Local stdlib HTTP wrapper for the dynamic routing Lambda handler."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import routing

HOST = "127.0.0.1"
PORT = 8788


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path.rstrip("/") not in {"/api/flood-route", "/flood-route"}:
            self.send_error(404)
            return
        length = int(self.headers.get("content-length", "0"))
        result = routing.handler({"body": self.rfile.read(length).decode("utf-8")})
        body = result["body"].encode("utf-8")
        self.send_response(result["statusCode"])
        for key, value in result["headers"].items():
            self.send_header(key, value)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, message: str, *args: object) -> None:
        print(f"[routing] {message % args}")


if __name__ == "__main__":
    print(json.dumps({"service": "waterpark-routing", "url": f"http://{HOST}:{PORT}"}))
    try:
        ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        pass
