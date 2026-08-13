"""YWTA共通例外の互換性とserializationを検証する。"""

import unittest

from ywta.config.base_config import ConfigError, ValidationError
from ywta.exceptions import DeformError, ErrorCode, RigError, YWTAError


class ExceptionHierarchyTests(unittest.TestCase):
    """例外階層と安定したerror codeを検証する。"""

    def test_domain_error_has_default_code(self):
        error = RigError("joint mapping failed", details={"joint": "arm_L"})
        self.assertIsInstance(error, YWTAError)
        self.assertEqual(ErrorCode.RIG.value, error.code)
        self.assertEqual(
            {
                "code": "YWTA_RIG",
                "message": "joint mapping failed",
                "details": {"joint": "arm_L"},
            },
            error.to_dict(),
        )

    def test_custom_code_is_preserved_as_string(self):
        error = DeformError("weight transfer failed", code="YWTA_DEFORM_SKIN_001")
        self.assertEqual("YWTA_DEFORM_SKIN_001", error.code)

    def test_serialized_details_are_copied(self):
        error = RigError("failed", details={"nodes": ["root"]})
        serialized = error.to_dict()
        serialized["details"]["extra"] = True
        self.assertNotIn("extra", error.details)

    def test_existing_config_errors_keep_catch_hierarchy(self):
        config_error = ConfigError("bad config")
        validation_error = ValidationError("bad value")
        self.assertIsInstance(validation_error, ConfigError)
        self.assertIsInstance(config_error, YWTAError)
        self.assertEqual("YWTA_CONFIGURATION", config_error.code)
        self.assertEqual("YWTA_VALIDATION", validation_error.code)


if __name__ == "__main__":
    unittest.main()
