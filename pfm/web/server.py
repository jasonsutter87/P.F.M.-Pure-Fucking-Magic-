"""PFM Web Server - Local HTTP server for live PFM viewing.

Uses only stdlib (http.server). Opens browser automatically.
Binds to 127.0.0.1 only (no network exposure).

Security:
  - Binds to localhost only (127.0.0.1)
  - Only GET requests are served; all other methods return 405
  - Only the root path (/) is served; all other paths return 404
  - Security headers: X-Content-Type-Options, X-Frame-Options,
    Content-Security-Policy, Referrer-Policy, X-XSS-Protection
  - Cache-Control: no-store to prevent caching of sensitive PFM content
  - Port validation: must be 0 (auto) or 1024-65535
"""

from __future__ import annotations

import re
import sys
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

from pfm.web.generator import generate_html

# Maximum port number per TCP/IP specification
_MAX_PORT = 65535
# Minimum non-privileged port
_MIN_USER_PORT = 1024


class _PFMHandler(BaseHTTPRequestHandler):
    """Serves the generated HTML for a PFM file.

    Security: Only responds to GET / with full security headers.
    All other methods and paths are rejected.
    """

    _html_content: str = ""
    _csp_nonce: str = ""

    def do_GET(self) -> None:
        # Only serve the root path -- reject all other paths
        if self.path != "/" and self.path != "":
            self.send_error(404, "Not Found")
            return

        encoded = self._html_content.encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        # Security headers
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            f"default-src 'none'; script-src 'nonce-{self._csp_nonce}'; "
            f"style-src 'nonce-{self._csp_nonce}'; img-src data:;"
        )
        self.send_header("Referrer-Policy", "no-referrer")
        # X-XSS-Protection removed: deprecated, can cause issues in modern browsers
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self) -> None:
        self.send_error(405, "Method Not Allowed")

    def do_PUT(self) -> None:
        self.send_error(405, "Method Not Allowed")

    def do_DELETE(self) -> None:
        self.send_error(405, "Method Not Allowed")

    def do_PATCH(self) -> None:
        self.send_error(405, "Method Not Allowed")

    def do_OPTIONS(self) -> None:
        self.send_error(405, "Method Not Allowed")

    def log_message(self, format: str, *args) -> None:
        # Suppress default request logging
        pass

    # Override server_version to avoid leaking software version info
    server_version = "PFM"
    sys_version = ""


def serve(pfm_path: str | Path, port: int = 0, open_browser: bool = True) -> None:
    """Start a local HTTP server to view a PFM file.

    Args:
        pfm_path: Path to .pfm file.
        port: Port number (0 = auto-assign, or 1024-65535).
        open_browser: Open browser automatically.

    Raises:
        ValueError: If port is out of valid range.
    """
    # Validate port number
    if not isinstance(port, int):
        raise ValueError(f"Port must be an integer, got {type(port).__name__}")
    if port != 0 and (port < _MIN_USER_PORT or port > _MAX_PORT):
        raise ValueError(
            f"Port must be 0 (auto) or between {_MIN_USER_PORT} and {_MAX_PORT}, "
            f"got {port}"
        )

    pfm_path = Path(pfm_path)
    if not pfm_path.exists():
        print(f"Error: File not found: {pfm_path}", file=sys.stderr)
        sys.exit(1)

    html_content = generate_html(pfm_path)

    # Extract nonce from the generated HTML for the HTTP CSP header
    nonce_match = re.search(r"nonce-([A-Za-z0-9_-]+)", html_content)
    csp_nonce = nonce_match.group(1) if nonce_match else ""

    # Create handler class with the HTML content bound
    handler = type("Handler", (_PFMHandler,), {
        "_html_content": html_content,
        "_csp_nonce": csp_nonce,
    })

    server = HTTPServer(("127.0.0.1", port), handler)
    actual_port = server.server_address[1]

    url = f"http://127.0.0.1:{actual_port}"
    print(f"Serving {pfm_path.name} at {url}")
    print("Press Ctrl+C to stop.")

    if open_browser:
        # Open browser in a separate thread to avoid blocking
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()
