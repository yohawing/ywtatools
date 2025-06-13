import unittest
import os
import maya.cmds as cmds
import ywta.deform.blendshape as bs

from ywta.test import TestCase


class BlendShapeTests(TestCase):
    def test_get_blendshape_on_new_shape(self):
        shape = cmds.polyCube()[0]
        blendshape = bs.get_or_create_blendshape_node(shape)
        self.assertTrue(cmds.objExists(blendshape))
        blendshapes = cmds.ls(type="blendShape")
        self.assertEqual(len(blendshapes), 1)
        self.assertEqual(blendshapes[0], blendshape)

        blendshape = bs.get_or_create_blendshape_node(shape)
        blendshapes = cmds.ls(type="blendShape")
        self.assertEqual(len(blendshapes), 1)
        self.assertEqual(blendshapes[0], blendshape)

    def test_get_blendshape_on_existing_blendshape(self):
        shape = cmds.polyCube()[0]
        blendshape = cmds.blendShape(shape)[0]
        existing_blendshape = bs.get_or_create_blendshape_node(shape)
        self.assertEqual(blendshape, existing_blendshape)

    def test_get_blendshape_node(self):
        """Test getting a blendshape node from geometry"""
        # Create a mesh with no blendshape
        shape = cmds.polyCube()[0]
        # Should return None when no blendshape exists
        self.assertIsNone(bs.get_blendshape_node(shape))

        # Create a blendshape
        blendshape = cmds.blendShape(shape)[0]
        # Should return the blendshape node
        self.assertEqual(bs.get_blendshape_node(shape), blendshape)

    def test_add_target_and_get_target_list(self):
        """Test adding targets to a blendshape and getting the target list"""
        # Create base mesh and blendshape
        base_mesh = cmds.polyCube(name="base_mesh")[0]
        blendshape = bs.get_or_create_blendshape_node(base_mesh)

        # Create target meshes
        target1 = cmds.polyCube(name="target1")[0]
        target2 = cmds.polyCube(name="target2")[0]

        # Add targets to blendshape
        bs.add_target(blendshape, target1)
        bs.add_target(blendshape, target2, new_target_name="renamed_target")

        # Get target list
        targets = bs.get_target_list(blendshape)

        # Verify targets were added correctly
        self.assertEqual(len(targets), 2)
        self.assertIn("target1", targets)
        self.assertIn("renamed_target", targets)
        self.assertNotIn("target2", targets)  # Should be renamed

    def test_get_target_index(self):
        """Test getting the index of a target in a blendshape"""
        # Create base mesh and blendshape
        base_mesh = cmds.polyCube()[0]
        blendshape = bs.get_or_create_blendshape_node(base_mesh)

        # Create and add targets
        target1 = cmds.polyCube(name="target1")[0]
        target2 = cmds.polyCube(name="target2")[0]

        # Add targets with specific indices
        index1 = bs.add_target(blendshape, target1)
        index2 = bs.add_target(blendshape, target2)

        # Verify indices
        self.assertEqual(bs.get_target_index(blendshape, "target1"), index1)
        self.assertEqual(bs.get_target_index(blendshape, "target2"), index2)

        # Test non-existent target
        with self.assertRaises(RuntimeError):
            bs.get_target_index(blendshape, "non_existent_target")

    def test_zero_and_restore_weights(self):
        """Test zeroing weights and restoring them"""
        # Create base mesh and blendshape
        base_mesh = cmds.polyCube()[0]
        blendshape = bs.get_or_create_blendshape_node(base_mesh)

        # Create and add targets
        target1 = cmds.polyCube(name="target1")[0]
        target2 = cmds.polyCube(name="target2")[0]
        bs.add_target(blendshape, target1)
        bs.add_target(blendshape, target2)

        # Set weights
        cmds.setAttr(f"{blendshape}.target1", 0.5)
        cmds.setAttr(f"{blendshape}.target2", 0.7)

        # Verify weights are set
        self.assertAlmostEqual(cmds.getAttr(f"{blendshape}.target1"), 0.5)
        self.assertAlmostEqual(cmds.getAttr(f"{blendshape}.target2"), 0.7)

        # Zero weights
        connections = bs.zero_weights(blendshape)

        # Verify weights are zeroed
        self.assertAlmostEqual(cmds.getAttr(f"{blendshape}.target1"), 0.0)
        self.assertAlmostEqual(cmds.getAttr(f"{blendshape}.target2"), 0.0)

        # Set different weights
        cmds.setAttr(f"{blendshape}.target1", 0.3)
        cmds.setAttr(f"{blendshape}.target2", 0.4)

        # Restore weights (should reconnect any connections, not restore values)
        bs.restore_weights(blendshape, connections)

        # Since we didn't have connections, values should remain
        self.assertAlmostEqual(cmds.getAttr(f"{blendshape}.target1"), 0.3)
        self.assertAlmostEqual(cmds.getAttr(f"{blendshape}.target2"), 0.4)

    def test_find_replace_target_names(self):
        """Test finding and replacing text in target names"""
        # Create base mesh and blendshape
        base_mesh = cmds.polyCube()[0]
        blendshape = bs.get_or_create_blendshape_node(base_mesh)

        # Create and add targets with specific naming pattern
        target1 = cmds.polyCube(name="prefix_name_suffix")[0]
        target2 = cmds.polyCube(name="prefix_other_suffix")[0]
        target3 = cmds.polyCube(name="different_name")[0]

        bs.add_target(blendshape, target1)
        bs.add_target(blendshape, target2)
        bs.add_target(blendshape, target3)

        # Test case-sensitive replacement
        renamed = bs.find_replace_target_names(
            blendshape, "prefix_", "new_", case_sensitive=True
        )

        # Verify renamed targets
        targets = bs.get_target_list(blendshape)
        self.assertIn("new_name_suffix", targets)
        self.assertIn("new_other_suffix", targets)
        self.assertIn("different_name", targets)  # Should not be renamed

        # Verify returned dictionary
        self.assertEqual(len(renamed), 2)
        self.assertEqual(renamed["prefix_name_suffix"], "new_name_suffix")
        self.assertEqual(renamed["prefix_other_suffix"], "new_other_suffix")

    def test_find_replace_target_names_case_insensitive(self):
        """Test finding and replacing text in target names with case insensitivity"""
        # Create base mesh and blendshape
        base_mesh = cmds.polyCube()[0]
        blendshape = bs.get_or_create_blendshape_node(base_mesh)

        # Create and add targets with mixed case
        target1 = cmds.polyCube(name="Prefix_name")[0]
        target2 = cmds.polyCube(name="prefix_Other")[0]

        bs.add_target(blendshape, target1)
        bs.add_target(blendshape, target2)

        # Test case-insensitive replacement
        renamed = bs.find_replace_target_names(
            blendshape, "prefix", "NEW", case_sensitive=False
        )

        # Verify renamed targets
        targets = bs.get_target_list(blendshape)
        self.assertIn("NEW_name", targets)
        self.assertIn("NEW_Other", targets)

        # Verify returned dictionary
        self.assertEqual(len(renamed), 2)
        self.assertEqual(renamed["Prefix_name"], "NEW_name")
        self.assertEqual(renamed["prefix_Other"], "NEW_Other")

    def test_find_replace_target_names_regex(self):
        """Test finding and replacing text in target names using regex"""
        # Create base mesh and blendshape
        base_mesh = cmds.polyCube()[0]
        blendshape = bs.get_or_create_blendshape_node(base_mesh)

        # Create and add targets with specific naming pattern
        target1 = cmds.polyCube(name="left_eye_blink")[0]
        target2 = cmds.polyCube(name="left_brow_up")[0]
        target3 = cmds.polyCube(name="right_eye_blink")[0]

        bs.add_target(blendshape, target1)
        bs.add_target(blendshape, target2)
        bs.add_target(blendshape, target3)

        # Test regex replacement (swap left/right)
        renamed = bs.find_replace_target_names_regex(
            blendshape, r"(left|right)_(.+)", r"side_\2_\1"
        )

        # Verify renamed targets
        targets = bs.get_target_list(blendshape)
        self.assertIn("side_eye_blink_left", targets)
        self.assertIn("side_brow_up_left", targets)
        self.assertIn("side_eye_blink_right", targets)

        # Verify returned dictionary
        self.assertEqual(len(renamed), 3)
        self.assertEqual(renamed["left_eye_blink"], "side_eye_blink_left")
        self.assertEqual(renamed["left_brow_up"], "side_brow_up_left")
        self.assertEqual(renamed["right_eye_blink"], "side_eye_blink_right")
