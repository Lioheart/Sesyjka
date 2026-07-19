from __future__ import annotations

import re
import unittest
from pathlib import Path


class ReleasePackagingTests(unittest.TestCase):
    @property
    def root(self) -> Path:
        return Path(__file__).parents[1]

    def test_flatpak_packaging_was_removed(self) -> None:
        self.assertFalse((self.root / "flatpak").exists())
        self.assertFalse((self.root / "FLATHUB.md").exists())

    def test_release_workflow_builds_and_uploads_three_distribution_channels(self) -> None:
        source = (self.root / ".github/workflows/release.yml").read_text(encoding="utf-8")
        self.assertIn("release:", source)
        self.assertIn("types: [published]", source)
        self.assertIn("build-generic.sh", source)
        self.assertIn("build-deb.sh", source)
        self.assertIn("build-rpm.sh", source)
        self.assertIn("SHA256SUMS", source)
        self.assertIn("gh release upload", source)
        self.assertIn("permissions:\n  contents: write", source)

    def test_package_builders_set_update_channels(self) -> None:
        common = (self.root / "packaging/common.sh").read_text(encoding="utf-8")
        rpm = (self.root / "packaging/rpm/sesyjka.spec.in").read_text(encoding="utf-8")
        generic = (self.root / "install-linux.sh").read_text(encoding="utf-8")
        self.assertIn('SESYJKA_INSTALL_CHANNEL="$channel"', common)
        self.assertIn('SESYJKA_INSTALL_CHANNEL="rpm"', rpm)
        self.assertIn('SESYJKA_INSTALL_CHANNEL="generic"', generic)
        for source in (common, rpm, generic):
            self.assertIn("Lioheart/Sesyjka", source)

    def test_versions_are_consistent(self) -> None:
        pyproject = (self.root / "pyproject.toml").read_text(encoding="utf-8")
        init = (self.root / "sesyjka/__init__.py").read_text(encoding="utf-8")
        project_match = re.search(r'^version = "([0-9.]+)"$', pyproject, re.MULTILINE)
        app_match = re.search(r'^APP_VERSION = "([0-9.]+)"$', init, re.MULTILINE)
        self.assertIsNotNone(project_match)
        self.assertIsNotNone(app_match)
        self.assertEqual(project_match.group(1), app_match.group(1))
        self.assertEqual(project_match.group(1), "0.7.0")

    def test_updater_is_integrated_without_blocking_the_gtk_thread(self) -> None:
        app = (self.root / "sesyjka/app.py").read_text(encoding="utf-8")
        updater = (self.root / "sesyjka/updater.py").read_text(encoding="utf-8")
        config = (self.root / "sesyjka/config.py").read_text(encoding="utf-8")
        self.assertIn("threading.Thread", app)
        self.assertIn("GLib.idle_add", app)
        self.assertIn("fetch_latest_release", app)
        self.assertIn("download_and_install", app)
        self.assertIn('"check_updates": True', config)
        self.assertIn("SHA256SUMS", updater)
        self.assertIn("pkexec", updater)

    def test_repository_metadata_points_to_result_repository(self) -> None:
        metainfo = (
            self.root / "data/io.github.zuraffpl.Sesyjka.metainfo.xml"
        ).read_text(encoding="utf-8")
        self.assertIn("https://github.com/Lioheart/Sesyjka", metainfo)
        self.assertIn('<release version="0.7.0"', metainfo)
        self.assertNotIn("github.com/ZuraffPL/sesyjka", metainfo)


if __name__ == "__main__":
    unittest.main()
