"""YWTA Python plugin descriptor registry の単体テスト。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from ywta.plugin_manager import (
    DuplicatePluginError,
    PluginDescriptor,
    PluginRegistry,
    UnknownPluginError,
    clear_registry,
    discover_plugins,
    get_plugin,
    register_plugin,
    search_plugins,
    unregister_plugin,
)


class PluginRegistryTests(unittest.TestCase):
    """登録・検索・解除の基本契約を検証する。"""

    def setUp(self) -> None:
        """共有 registry をテスト前にリセットする。"""

        clear_registry()

    def tearDown(self) -> None:
        """共有 registry をテスト後にリセットする。"""

        clear_registry()

    def test_descriptor_is_immutable_and_metadata_is_normalized(self):
        descriptor = PluginDescriptor(
            name="  Weight Tools ",
            version="1.2.0",
            description="Skin weight helpers",
            module="ywta.rig.weights",
            tags=["Rigging", "weights"],
        )

        self.assertEqual("Weight Tools", descriptor.name)
        self.assertEqual(("Rigging", "weights"), descriptor.tags)
        with self.assertRaises(AttributeError):
            descriptor.name = "Other"

    def test_register_duplicate_and_unregister(self):
        registered = register_plugin(
            name="Mesh Helper",
            version="1.0",
            description="Mesh utility",
            tags=("mesh",),
            module="ywta.mesh.helper",
        )

        self.assertIs(registered, search_plugins("MESH")[0])
        with self.assertRaises(DuplicatePluginError):
            register_plugin(
                name="mesh helper",
                version="2.0",
                description="Another utility",
                module="ywta.mesh.other",
            )

        self.assertEqual("Mesh Helper", registered.name)
        self.assertEqual(registered, get_plugin("MESH HELPER"))
        self.assertEqual(registered, unregister_plugin("mesh helper"))
        with self.assertRaises(UnknownPluginError):
            get_plugin("missing")

    def test_search_matches_name_description_and_tags_in_deterministic_order(self):
        registry = PluginRegistry()
        registry.register(
            name="Z Tool",
            version="1",
            description="Sculpt helper",
            tags=("modeling",),
            module="example.z",
        )
        registry.register(
            name="A Tool",
            version="1",
            description="Weight helper",
            tags=("RIGGING",),
            module="example.a",
        )

        self.assertEqual(("A Tool", "Z Tool"), tuple(item.name for item in registry.list_plugins()))
        self.assertEqual(("A Tool",), tuple(item.name for item in registry.search("rig")))
        self.assertEqual(("Z Tool",), tuple(item.name for item in registry.search("SCULPT")))
        self.assertEqual(("A Tool", "Z Tool"), tuple(item.name for item in registry.search("")))
        self.assertEqual(("A Tool", "Z Tool"), tuple(item.name for item in registry.search("  ")))

    def test_invalid_metadata_fails_fast(self):
        with self.assertRaises(ValueError):
            PluginDescriptor("", "1", "description", "module")
        with self.assertRaises(TypeError):
            PluginDescriptor("name", "1", "description", "module", "not-tags")
        with self.assertRaises(ValueError):
            PluginDescriptor("name", "1", "description", "module", ("",))


class PluginDiscoveryTests(unittest.TestCase):
    """副作用のない package discovery を検証する。"""

    def test_discovery_is_sorted_and_excludes_private_modules_and_packages(self):
        package_name = f"ywta_discovery_{uuid4().hex}"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            package = root / package_name
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "z_tool.py").write_text("", encoding="utf-8")
            (package / "a_tool.py").write_text("", encoding="utf-8")
            (package / "_private.py").write_text("", encoding="utf-8")
            (package / "public_package").mkdir()
            (package / "public_package" / "__init__.py").write_text("", encoding="utf-8")
            (package / "_private_package").mkdir()
            (package / "_private_package" / "__init__.py").write_text("", encoding="utf-8")
            side_effect_module = package / "side_effect.py"
            side_effect_module.write_text("raise RuntimeError('module was imported')", encoding="utf-8")

            sys.path.insert(0, str(root))
            try:
                discovered = discover_plugins(package_name)
                self.assertEqual(
                    (
                        f"{package_name}.a_tool",
                        f"{package_name}.public_package",
                        f"{package_name}.side_effect",
                        f"{package_name}.z_tool",
                    ),
                    discovered,
                )
                self.assertNotIn(f"{package_name}.side_effect", sys.modules)
            finally:
                sys.path.remove(str(root))


if __name__ == "__main__":
    unittest.main()
