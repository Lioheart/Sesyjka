from __future__ import annotations

import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


class FlatpakPackagingTests(unittest.TestCase):
    @property
    def root(self) -> Path:
        return Path(__file__).parents[1]

    def test_manifest_targets_gnome_50_without_home_access(self) -> None:
        manifest = (self.root / "flatpak" / "io.github.zuraffpl.Sesyjka.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("runtime: org.gnome.Platform", manifest)
        self.assertIn("runtime-version: '50'", manifest)
        self.assertIn("--socket=wayland", manifest)
        self.assertIn("--socket=fallback-x11", manifest)
        self.assertNotIn("--filesystem=home", manifest)
        self.assertNotIn("--filesystem=host", manifest)

    def test_python_dependencies_are_pinned_source_archives(self) -> None:
        payload = json.loads(
            (self.root / "flatpak" / "python3-openpyxl.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(payload["name"], "python3-openpyxl")
        self.assertEqual(len(payload["sources"]), 2)
        for source in payload["sources"]:
            self.assertEqual(source["type"], "file")
            self.assertTrue(source["url"].endswith(".tar.gz"))
            self.assertEqual(len(source["sha256"]), 64)

    def test_required_desktop_metadata_exists(self) -> None:
        app_id = "io.github.zuraffpl.Sesyjka"
        desktop = self.root / "data" / f"{app_id}.desktop"
        metainfo = self.root / "data" / f"{app_id}.metainfo.xml"
        icon = (
            self.root
            / "data"
            / "icons"
            / "hicolor"
            / "scalable"
            / "apps"
            / f"{app_id}.svg"
        )
        self.assertTrue(desktop.is_file())
        self.assertTrue(metainfo.is_file())
        self.assertTrue(icon.is_file())
        self.assertIn(
            "Comment=Manage tabletop RPG collections and sessions",
            desktop.read_text(encoding="utf-8"),
        )
        metadata = metainfo.read_text(encoding="utf-8")
        self.assertIn('<developer id="io.github.zuraffpl">', metadata)
        self.assertIn('<content_rating type="oars-1.1"', metadata)
        self.assertIn('<release version="0.6.4"', metadata)
        ET.parse(metainfo)

    def test_metainfo_references_release_screenshots(self) -> None:
        app_id = "io.github.zuraffpl.Sesyjka"
        tree = ET.parse(self.root / "data" / f"{app_id}.metainfo.xml")
        images = [element.text or "" for element in tree.findall("./screenshots/screenshot/image")]
        self.assertGreaterEqual(len(images), 6)
        self.assertLessEqual(len(images), 10)
        self.assertTrue(all("/v0.6.4/screenshots/" in image for image in images))
        local_names = {path.name for path in (self.root / "screenshots").glob("*.png")}
        self.assertTrue({Path(image).name for image in images}.issubset(local_names))


if __name__ == "__main__":
    unittest.main()
