from __future__ import annotations

import base64
import hashlib
import threading
import urllib.parse
import urllib.request
import unittest
from unittest import mock

from sesyjka.cloud import CloudService, CloudSession, SessionTokenStore
from sesyjka.database_manager import DatabaseManager
from sesyjka.oauth import (
    LoopbackOAuthReceiver,
    build_discord_authorize_url,
    create_pkce_pair,
)


class OAuthHelperTests(unittest.TestCase):
    def test_pkce_challenge_matches_verifier(self) -> None:
        verifier, challenge = create_pkce_pair()
        self.assertGreaterEqual(len(verifier), 43)
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).decode("ascii").rstrip("=")
        self.assertEqual(challenge, expected)
        self.assertNotIn("=", challenge)

    def test_discord_authorize_url_contains_pkce_and_redirect(self) -> None:
        redirect = "http://127.0.0.1:8765/auth/callback"
        url = build_discord_authorize_url(
            "https://example.supabase.co", redirect, "challenge_123"
        )
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        self.assertEqual(parsed.path, "/auth/v1/authorize")
        self.assertEqual(params["provider"], ["discord"])
        self.assertEqual(params["redirect_to"], [redirect])
        self.assertEqual(params["code_challenge"], ["challenge_123"])
        self.assertEqual(params["code_challenge_method"], ["s256"])
        self.assertEqual(params["scopes"], ["identify email"])

    def test_loopback_receiver_accepts_code_only_on_callback_path(self) -> None:
        with LoopbackOAuthReceiver(port=0) as receiver:
            def send_callback() -> None:
                urllib.request.urlopen(
                    f"{receiver.redirect_uri}?code=abc-123", timeout=2
                ).read()

            worker = threading.Thread(target=send_callback)
            worker.start()
            callback = receiver.wait(timeout=3)
            worker.join(timeout=3)
        self.assertEqual(callback.code, "abc-123")
        self.assertEqual(callback.error, "")


class DiscordCloudLoginTests(unittest.TestCase):
    def test_discord_login_exchanges_pkce_code_and_persists_session(self) -> None:
        import tempfile
        from pathlib import Path

        temp = tempfile.TemporaryDirectory()
        try:
            root = Path(temp.name)
            databases = DatabaseManager(root / "data")
            databases.initialize()
            token_store = SessionTokenStore(root / "session.json")
            service = CloudService(databases, token_store=token_store)

            class FakeClient:
                def __init__(self) -> None:
                    self.config = type("Config", (), {"url": "https://example.supabase.co"})()
                    self.exchange_args: tuple[str, str] | None = None

                def exchange_pkce_code(self, code: str, verifier: str) -> CloudSession:
                    self.exchange_args = (code, verifier)
                    return CloudSession(
                        "access", "refresh", 9999999999, "user-1", "", "discord"
                    )

                def get_user(self, _token: str) -> dict[str, object]:
                    return {
                        "id": "user-1",
                        "email": "discord@example.com",
                        "app_metadata": {"provider": "discord"},
                    }

            fake_client = FakeClient()
            service._client = lambda _url, _key: fake_client  # type: ignore[method-assign]

            class FakeReceiver:
                redirect_uri = "http://127.0.0.1:8765/auth/callback"

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return None

                def wait(self, _timeout: float):
                    return type(
                        "Callback",
                        (),
                        {"code": "auth-code", "error": "", "error_description": ""},
                    )()

            opened: list[str] = []
            with mock.patch("sesyjka.cloud.LoopbackOAuthReceiver", FakeReceiver), mock.patch(
                "sesyjka.cloud.create_pkce_pair", return_value=("verifier", "challenge")
            ):
                session = service.sign_in_with_discord(
                    "https://example.supabase.co",
                    "sb_publishable_abcdefghijklmnopqrstuvwxyz",
                    open_browser=lambda url: opened.append(url) or True,
                )

            self.assertEqual(session.email, "discord@example.com")
            self.assertEqual(session.provider, "discord")
            self.assertEqual(fake_client.exchange_args, ("auth-code", "verifier"))
            self.assertTrue(opened)
            self.assertEqual(token_store.load().provider, "discord")
        finally:
            temp.cleanup()


if __name__ == "__main__":
    unittest.main()
