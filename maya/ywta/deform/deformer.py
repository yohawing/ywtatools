"""
Deformer utilities for Maya.

This module provides functions for baking deformed meshes to blendshape targets
and managing blendshape keyframes.
"""

import maya.cmds as cmds
import ywta.deform.blendshape as blendshape


def add_blendshape_target_with_frame(target_mesh, source_mesh, frame):
    """
    Add a blendshape target from source mesh at a specific frame.

    Args:
        target_mesh (str): The mesh that will receive the blendshape target
        source_mesh (str): The mesh to use as the blendshape target
        frame (int): Frame number for naming the target

    Returns:
        str: Name of the created target

    Raises:
        RuntimeError: If blendshape node cannot be found or created
    """
    try:
        blendshape_name = blendshape.get_blendshape_node(target_mesh)
        if not blendshape_name:
            raise RuntimeError(f"Could not get blendshape node for {target_mesh}")

        # Duplicate the source mesh
        target_name = f"deformer_{frame}"
        duplicated_mesh = cmds.duplicate(source_mesh, name=target_name)[0]

        # Add as blendshape target
        blendshape.add_target(blendshape_name, duplicated_mesh)

        # Clean up the duplicated mesh
        cmds.delete(duplicated_mesh)

        return target_name

    except Exception as e:
        cmds.error(f"Failed to add blendshape target: {str(e)}")
        return None


def add_key_blendshape_target(target_mesh, source_mesh, frame=None):
    """
    Add a blendshape target and set keyframes for it.

    Args:
        target_mesh (str): The mesh that will receive the blendshape target
        source_mesh (str): The mesh to use as the blendshape target
        frame (int, optional): Frame number. If None, uses current frame

    Returns:
        str: Name of the created target
    """
    if frame is None:
        frame = int(cmds.currentTime(query=True))

    target_name = add_blendshape_target_with_frame(target_mesh, source_mesh, frame)

    if target_name:
        blendshape_name = blendshape.get_blendshape_node(target_mesh)

        # Set keyframes for the target
        _set_target_keyframes(blendshape_name, target_name, frame)

    return target_name


def bake_deformed_to_blendshape():
    """
    Bake deformed mesh to blendshape targets across time range.

    Creates blendshape targets for each frame in the timeline range.
    The mesh must be selected before running this function.

    If two meshes are selected:
    - First mesh: source (deformed mesh)
    - Second mesh: target (receives blendshape targets)

    If one mesh is selected:
    - Same mesh is used as both source and target
    """
    selection = cmds.ls(selection=True, type="transform")

    if not selection:
        cmds.warning("No mesh selected. Please select a mesh and try again.")
        return

    # Validate selection contains meshes
    valid_meshes = []
    for obj in selection:
        shapes = cmds.listRelatives(obj, shapes=True, type="mesh")
        if shapes:
            valid_meshes.append(obj)

    if not valid_meshes:
        cmds.warning("Selected objects do not contain any meshes.")
        return

    source_mesh = valid_meshes[0]
    target_mesh = valid_meshes[1] if len(valid_meshes) > 1 else valid_meshes[0]

    try:
        blendshape_name = blendshape.get_blendshape_node(target_mesh)
        if not blendshape_name:
            cmds.warning(f"No blendshape node found on {target_mesh}")
            return

        # Get timeline range
        start_frame = int(cmds.playbackOptions(query=True, minTime=True))
        end_frame = int(cmds.playbackOptions(query=True, maxTime=True))

        # Store current time to restore later
        current_time = cmds.currentTime(query=True)

        created_targets = []

        for frame in range(start_frame, end_frame + 1):
            # Move to frame
            cmds.currentTime(frame)

            # Create blendshape target
            target_name = add_blendshape_target_with_frame(
                target_mesh, source_mesh, frame
            )

            if target_name:
                created_targets.append(target_name)
                # Set keyframes for this target
                _set_target_keyframes(
                    blendshape_name, target_name, frame, start_frame, end_frame
                )

        # Restore original time
        cmds.currentTime(current_time)

        print(
            f"Successfully baked {len(created_targets)} blendshape targets "
            f"from frame {start_frame} to {end_frame}"
        )

    except Exception as e:
        cmds.error(f"Failed to bake deformed mesh to blendshape: {str(e)}")


def set_keyframe_blendshape_per_frame():
    """
    Set keyframes for existing blendshape targets, one target per frame.

    This function assumes blendshape targets already exist and sets up
    keyframes so that each target is active for one frame only.
    """
    selection = cmds.ls(selection=True, type="transform")

    if not selection:
        cmds.warning("No mesh selected. Please select a mesh with blendshape targets.")
        return

    target_mesh = selection[0]

    try:
        blendshape_name = blendshape.get_blendshape_node(target_mesh)
        if not blendshape_name:
            cmds.warning(f"No blendshape node found on {target_mesh}")
            return

        target_list = blendshape.get_target_list(blendshape_name)
        if not target_list:
            cmds.warning("No blendshape targets found")
            return

        # Clear existing keyframes
        for i in range(len(target_list)):
            cmds.cutKey(f"{blendshape_name}.w[{i}]")

        # Get timeline range
        start_frame = int(cmds.playbackOptions(query=True, minTime=True))
        end_frame = int(cmds.playbackOptions(query=True, maxTime=True))

        # Limit end frame to available targets
        max_frame = min(end_frame, len(target_list) - 1)

        # Store current time
        current_time = cmds.currentTime(query=True)

        for frame in range(start_frame, max_frame + 1):
            cmds.currentTime(frame)

            # Set all targets to 0 first
            for i in range(len(target_list)):
                cmds.setAttr(f"{blendshape_name}.w[{i}]", 0)
                cmds.setKeyframe(f"{blendshape_name}.w[{i}]")

            # Set current frame target to 1
            if frame < len(target_list):
                cmds.setAttr(f"{blendshape_name}.w[{frame}]", 1)
                cmds.setKeyframe(f"{blendshape_name}.w[{frame}]")

        # Restore original time
        cmds.currentTime(current_time)

        print(
            f"Set keyframes for {len(target_list)} blendshape targets, "
            f"one target per frame from {start_frame} to {max_frame}"
        )

    except Exception as e:
        cmds.error(f"Failed to set blendshape keyframes: {str(e)}")


def _set_target_keyframes(
    blendshape_name, target_name, frame, start_frame=None, end_frame=None
):
    """
    Set keyframes for a blendshape target.

    Args:
        blendshape_name (str): Name of the blendshape node
        target_name (str): Name of the target
        frame (int): Frame where target should be active
        start_frame (int, optional): Start frame of range
        end_frame (int, optional): End frame of range
    """
    if start_frame is None:
        start_frame = int(cmds.playbackOptions(query=True, minTime=True))
    if end_frame is None:
        end_frame = int(cmds.playbackOptions(query=True, maxTime=True))

    target_attr = f"{blendshape_name}.{target_name}"

    # Set target to 1 at current frame
    cmds.setAttr(target_attr, 1)
    cmds.setKeyframe(target_attr)

    # Set target to 0 at adjacent frames
    if frame > start_frame:
        cmds.currentTime(frame - 1)
        cmds.setAttr(target_attr, 0)
        cmds.setKeyframe(target_attr)

    if frame < end_frame:
        cmds.currentTime(frame + 1)
        cmds.setAttr(target_attr, 0)
        cmds.setKeyframe(target_attr)

    # Return to original frame
    cmds.currentTime(frame)
