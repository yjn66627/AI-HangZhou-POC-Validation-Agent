"""Standard-library HTTP wrapper for the frozen V1.2C handler."""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import index


class RequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _dispatch(self):
        parsed = urlsplit(self.path)
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        raw_body = self.rfile.read(content_length) if content_length else b""
        query = parse_qs(parsed.query, keep_blank_values=True)
        event = {
            "path": parsed.path,
            "rawPath": parsed.path,
            "httpMethod": self.command,
            "headers": {key: value for key, value in self.headers.items()},
            "queryStringParameters": query,
            "rawQueryString": parsed.query,
            "body": raw_body.decode("utf-8") if raw_body else None,
        }
        response = index.main(event, None)
        payload = response.get("body", "")
        encoded = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
        self.send_response(int(response.get("statusCode", 500)))
        for key, value in response.get("headers", {}).items():
            self.send_header(str(key), str(value))
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        self._dispatch()

    def do_POST(self):
        self._dispatch()

    def do_PUT(self):
        self._dispatch()

    def do_DELETE(self):
        self._dispatch()

    def log_message(self, format_string, *args):
        return


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "9000"))
    ThreadingHTTPServer(("0.0.0.0", port), RequestHandler).serve_forever()
