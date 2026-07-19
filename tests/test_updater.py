from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sesyjka.updater import (
    LatestRelease,
    ReleaseAsset,
    UpdateError,
    _safe_extract_tar,
    asset_for_channel,
    detect_install_channel,
    download_release_asset,
    fetch_latest_release,
    is_newer_version,
    parse_version,
)


class UpdaterTests(unittest.TestCase):
    def test_semantic_release_versions_are_compared_numerically(self) -> None:
        self.assertEqual(parse_version("v1.12.3"), (1, 12, 3))
        self.assertTrue(is_newer_version("0.10.0", "0.9.9"))
        self.assertFalse(is_newer_version("0.7.0", "0.7.0"))
        with self.assertRaises(ValueError):
            parse_version("latest")

    def test_latest_release_response_is_parsed(self) -> None:
        payload = {
            "tag_name": "v0.8.0",
            "html_url": "https://github.com/Lioheart/Sesyjka/releases/tag/v0.8.0",
            "body": "Zmiany",
            "assets": [
                {
                    "name": "sesyjka_0.8.0_all.deb",
                    "browser_download_url": "https://example.test/sesyjka.deb",
                    "size": 123,
                    "digest": "sha256:" + "a" * 64,
                }
            ],
        }
        with patch("sesyjka.updater._request", return_value=json.dumps(payload).encode()):
            release = fetch_latest_release()
        self.assertEqual(release.version, "0.8.0")
        self.assertEqual(release.assets[0].name, "sesyjka_0.8.0_all.deb")

    def test_assets_are_selected_for_every_install_channel(self) -> None:
        release = LatestRelease(
            version="0.8.0",
            tag_name="v0.8.0",
            html_url="https://example.test",
            body="",
            assets=(
                ReleaseAsset("sesyjka_0.8.0_all.deb", "https://example.test/deb"),
                ReleaseAsset("sesyjka-0.8.0-1.fc43.noarch.rpm", "https://example.test/rpm"),
                ReleaseAsset(
                    "sesyjka-0.8.0-linux-installer.tar.gz",
                    "https://example.test/tar",
                ),
            ),
        )
        self.assertTrue(asset_for_channel(release, "deb").name.endswith(".deb"))
        self.assertTrue(asset_for_channel(release, "rpm").name.endswith(".rpm"))
        self.assertTrue(asset_for_channel(release, "generic").name.endswith(".tar.gz"))
        with self.assertRaises(UpdateError):
            asset_for_channel(release, "local")

    def test_downloaded_asset_is_verified_with_sha256_digest(self) -> None:
        content = b"verified package"
        digest = hashlib.sha256(content).hexdigest()
        asset = ReleaseAsset(
            "sesyjka_0.8.0_all.deb",
            "https://example.test/deb",
            digest=f"sha256:{digest}",
        )
        release = LatestRelease(
            "0.8.0",
            "v0.8.0",
            "https://example.test",
            "",
            (asset,),
        )

        def fake_download(_asset: ReleaseAsset, target: Path, timeout: float = 60.0) -> None:
            del timeout
            target.write_bytes(content)

        with tempfile.TemporaryDirectory() as raw, patch(
            "sesyjka.updater._download", side_effect=fake_download
        ):
            path = download_release_asset(release, "deb", Path(raw))
            self.assertEqual(path.read_bytes(), content)

    def test_unsafe_generic_installer_archive_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "unsafe.tar.gz"
            with tarfile.open(archive, "w:gz") as handle:
                data = b"bad"
                entry = tarfile.TarInfo("../install-linux.sh")
                entry.size = len(data)
                handle.addfile(entry, io.BytesIO(data))
            with self.assertRaises(UpdateError):
                _safe_extract_tar(archive, root / "out")

    def test_explicit_install_channel_has_priority(self) -> None:
        with patch.dict(os.environ, {"SESYJKA_INSTALL_CHANNEL": "rpm"}, clear=False):
            self.assertEqual(detect_install_channel(), "rpm")


if __name__ == "__main__":
    unittest.main()
