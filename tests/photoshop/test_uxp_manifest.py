"""Photoshop UXP プラグイン manifest の静的検証。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPOSITORY_ROOT / "photoshop" / "ywtatools-uxp"
MANIFEST_PATH = PLUGIN_ROOT / "manifest.json"


class UxpManifestTest(unittest.TestCase):
    """UXP Developer Tool へ渡す manifest contract を検証する。"""

    @classmethod
    def setUpClass(cls) -> None:
        """各テストで共有する manifest を読み込む。"""
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_manifest_targets_photoshop_with_version_five(self) -> None:
        """Photoshop 向け Manifest v5 であることを確認する。"""
        self.assertEqual(self.manifest["manifestVersion"], 5)
        self.assertEqual(self.manifest["host"]["app"], "PS")
        minimum_version = tuple(
            int(part) for part in self.manifest["host"]["minVersion"].split(".")
        )
        self.assertGreaterEqual(minimum_version, (24, 4, 0))
        self.assertEqual(
            self.manifest["requiredPermissions"]["localFileSystem"], "request"
        )

    def test_main_file_exists(self) -> None:
        """manifest の main が実在するファイルを参照することを確認する。"""
        self.assertTrue((PLUGIN_ROOT / self.manifest["main"]).is_file())

    def test_html_references_existing_assets(self) -> None:
        """HTML が参照するスクリプトとスタイルが存在することを確認する。"""
        html = (PLUGIN_ROOT / self.manifest["main"]).read_text(encoding="utf-8")
        for asset_name in ("index.js", "styles.css"):
            self.assertIn(asset_name, html)
            self.assertTrue((PLUGIN_ROOT / asset_name).is_file())

    def test_panel_entrypoint_matches_javascript_registration(self) -> None:
        """パネル ID が JavaScript 側にも登録されていることを確認する。"""
        panels = [
            entrypoint
            for entrypoint in self.manifest["entrypoints"]
            if entrypoint["type"] == "panel"
        ]
        self.assertEqual(len(panels), 1)
        javascript = (PLUGIN_ROOT / "index.js").read_text(encoding="utf-8")
        self.assertIn(f'{panels[0]["id"]}:', javascript)


if __name__ == "__main__":
    unittest.main()
