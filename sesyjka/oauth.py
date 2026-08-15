from __future__ import annotations

import base64
import hashlib
import html
import secrets
import urllib.parse
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer

OAUTH_CALLBACK_HOST = "127.0.0.1"
OAUTH_CALLBACK_PORT = 8765
OAUTH_CALLBACK_PATH = "/auth/callback"
OAUTH_TIMEOUT_SECONDS = 180
DISCORD_SCOPES = "identify email"


@dataclass(frozen=True)
class OAuthCallback:
    code: str = ""
    error: str = ""
    error_description: str = ""


def create_pkce_pair() -> tuple[str, str]:
    """Return a RFC 7636 verifier and an S256 base64url challenge."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def build_discord_authorize_url(
    supabase_url: str,
    redirect_uri: str,
    code_challenge: str,
) -> str:
    query = urllib.parse.urlencode(
        {
            "provider": "discord",
            "redirect_to": redirect_uri,
            "code_challenge": code_challenge,
            "code_challenge_method": "s256",
            "scopes": DISCORD_SCOPES,
        }
    )
    return f"{supabase_url.rstrip('/')}/auth/v1/authorize?{query}"


class LoopbackOAuthReceiver:
    """One-shot localhost callback receiver used by desktop OAuth.

    The server only binds the IPv4 loopback address. It never listens on the
    LAN and is closed as soon as the callback arrives or the timeout expires.
    """

    def __init__(
        self,
        host: str = OAUTH_CALLBACK_HOST,
        port: int = OAUTH_CALLBACK_PORT,
        path: str = OAUTH_CALLBACK_PATH,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.path = path
        self.callback: OAuthCallback | None = None
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path != receiver.path:
                    self.send_error(404)
                    return
                params = urllib.parse.parse_qs(parsed.query)
                receiver.callback = OAuthCallback(
                    code=(params.get("code") or [""])[0],
                    error=(params.get("error") or [""])[0],
                    error_description=(params.get("error_description") or [""])[0],
                )
                success = bool(receiver.callback.code and not receiver.callback.error)
                title = "Logowanie zakończone" if success else "Logowanie nie powiodło się"
                detail = (
                    "Możesz zamknąć tę kartę i wrócić do Sesyjki."
                    if success
                    else receiver.callback.error_description or receiver.callback.error or "Brak kodu autoryzacyjnego."
                )
                body = (
                    "<!doctype html><html lang='pl'><meta charset='utf-8'>"
                    f"<title>{html.escape(title)}</title>"
                    "<body style='font-family:sans-serif;max-width:46rem;margin:4rem auto;padding:0 1rem'>"
                    f"<h1>{html.escape(title)}</h1><p>{html.escape(detail)}</p>"
                    "</body></html>"
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        try:
            self.server = HTTPServer((self.host, self.port), Handler)
            self.port = int(self.server.server_address[1])
        except OSError as exc:
            raise OSError(
                f"Nie można uruchomić lokalnego callbacku OAuth na {self.host}:{self.port}. "
                "Sprawdź, czy port nie jest używany przez inny program."
            ) from exc
        self.server.timeout = 0.5

    @property
    def redirect_uri(self) -> str:
        return f"http://{self.host}:{self.port}{self.path}"

    def wait(self, timeout: float = OAUTH_TIMEOUT_SECONDS) -> OAuthCallback:
        import time

        deadline = time.monotonic() + max(1.0, float(timeout))
        while self.callback is None and time.monotonic() < deadline:
            self.server.handle_request()
        if self.callback is None:
            raise TimeoutError("Przekroczono czas oczekiwania na logowanie Discord.")
        return self.callback

    def close(self) -> None:
        self.server.server_close()

    def __enter__(self) -> "LoopbackOAuthReceiver":
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        self.close()
