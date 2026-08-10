"""Petit CP HTTP pour le gate chaos P1, sans PostgreSQL."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Handler(BaseHTTPRequestHandler):
    desired_file: Path

    def do_GET(self) -> None:  # noqa: N802
        if self.path.endswith("/desired"):
            data = self.desired_file.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path.endswith("/report"):
            length = int(self.headers.get("Content-Length", "0"))
            if length:
                json.loads(self.rfile.read(length))
            self.send_response(204)
            self.end_headers()
            return
        self.send_error(404)

    def log_message(self, fmt: str, *args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--desired", type=Path, required=True)
    args = parser.parse_args()
    Handler.desired_file = args.desired
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
