"""
Contains the menu creation functions as wells as any other functions the menus rely on.
"""

import webbrowser
import maya.cmds as cmds
import maya.mel as mel
from ywta.settings import DOCUMENTATION_ROOT


def create_menu():
    """Creates the YWTA menu."""
    # delete the menu if it already exists
    delete_menu()

    gmainwindow = mel.eval("$tmp = $gMainWindow;")
    menu = cmds.menu("YWTA", parent=gmainwindow, tearOff=True, label="YWTA")

    cmds.menuItem(
        parent=menu,
        label="Reload YWTA",
        command="import ywta.reloadmodules; ywta.reloadmodules.unload_packages()",
        imageOverlayLabel="Test",
    )

    # region Animation
    animation_menu = cmds.menuItem(
        subMenu=True, tearOff=True, parent=menu, label="Animation"
    )
    # cmds.menuItem(
    #     parent=deformer,
    #     label="Set Keyframe Blendshape Per Frame",
    #     command="import ywta.deformer as def; def.set_keyframe_blendshape_per_frame()",
    # )

    # region Mesh
    mesh_menu = cmds.menuItem(subMenu=True, tearOff=True, parent=menu, label="Mesh")
    cmds.menuItem(
        parent=mesh_menu,
        label="Lock Selected Vertices",
        command="import ywta.mesh.lock_selected_vertices as lsv; lsv.lock()",
    )
    cmds.menuItem(
        parent=mesh_menu,
        label="Unlock Selected Vertices",
        command="import ywta.mesh.lock_selected_vertices as lsv; lsv.unlock()",
    )
    # 複数のオブジェクトをマージして階層をJoint化しBindSkinする
    cmds.menuItem(
        parent=mesh_menu,
        label="Merge Objects and Skinning",
        command="import ywta.mesh.merge_and_skin as mas; mas.merge_and_skin()",
    )
    # endregion

    # region Rig
    rig_menu = cmds.menuItem(subMenu=True, tearOff=True, parent=menu, label="Rigging")
    cmds.menuItem(
        parent=rig_menu,
        label="Freeze to offsetParentMatrix",
        command="import ywta.rig.common; ywta.rig.common.freeze_to_parent_offset()",
    )
    # cmds.menuItem(
    #     parent=rig_menu,
    #     label="CQueue",
    #     command="import ywta.cqueue.window; ywta.cqueue.window.show()",
    #     imageOverlayLabel="cqueue",
    # )
    cmds.menuItem(parent=rig_menu, divider=True, dividerLabel="Skeleton")
    cmds.menuItem(
        parent=rig_menu,
        label="Joint Edit Tools",
        command="import ywta.rig.orientjoints as oj; oj.OrientJointsWindow()",
        image="orientJoint.png",
    )
    cmds.menuItem(
        parent=rig_menu,
        label="Create Joint",
        command="import ywta.rig.create_joint as cj; cj.create_joint_from_selected_component()",
        image="joint.png",
    )
    cmds.menuItem(
        parent=rig_menu,
        label="Rename Chain",
        command="import ywta.name; ywta.name.rename_chain_ui()",
        image="menuIconModify.png",
        imageOverlayLabel="name",
    )
    cmds.menuItem(
        parent=rig_menu,
        label="Export Skeleton",
        command="import ywta.rig.skeleton as skeleton; skeleton.dump()",
        image="kinJoint.png",
    )
    cmds.menuItem(
        parent=rig_menu,
        label="Import Skeleton",
        command="import ywta.rig.skeleton as skeleton; skeleton.load()",
        image="kinJoint.png",
    )
    item = cmds.menuItem(
        parent=rig_menu,
        label="Connect Twist Joint",
        command="import ywta.rig.swingtwist as st; st.create_from_menu()",
    )
    cmds.menuItem(
        parent=rig_menu,
        insertAfter=item,
        optionBox=True,
        command="import ywta.rig.swingtwist as st; st.display_menu_options()",
    )
    cmds.menuItem(parent=rig_menu, divider=True, dividerLabel="Animation Rig")
    cmds.menuItem(
        parent=rig_menu,
        label="Control Creator",
        command="import ywta.rig.control_ui as control_ui; control_ui.show()",
        image="orientJoint.png",
    )
    cmds.menuItem(
        parent=rig_menu,
        label="Export Selected Control Curves",
        command="import ywta.rig.control as control; control.export_curves()",
    )

    cmds.menuItem(
        parent=rig_menu,
        label="Import Control Curves",
        command="import ywta.rig.control as control; control.import_curves()",
    )
    cmds.menuItem(parent=rig_menu, divider=True, dividerLabel="HumanIK")
    cmds.menuItem(
        parent=rig_menu,
        label="HumanIK Auto Setup",
        command="import ywta.rig.humanik as humanik; humanik.setup_hik_character()",
    )
    # endregion

    # region Deform
    deform_menu = cmds.menuItem(subMenu=True, tearOff=True, parent=menu, label="Deform")
    cmds.menuItem(parent=deform_menu, divider=True, dividerLabel="Skinning")
    transfer_shape_menu_item = cmds.menuItem(
        parent=deform_menu,
        label="Transfer Shape",
        command="import ywta.deform.transfer_shape as tbs;tbs.exec_from_menu()",
        image="exportSmoothSkin.png",
    )
    cmds.menuItem(
        parent=deform_menu,
        label="Bake Deformer to Blendshape",
        command="import ywta.deform.deformer as bd; bd.bake_deformed_to_blendshape()",
    )
    cmds.menuItem(
        parent=deform_menu,
        label="Set Keyframe Blendshape Per Frame",
        command="import ywta.deform.deformer as bd; bd.set_keyframe_blendshape_per_frame()",
    )
    cmds.menuItem(
        parent=deform_menu,
        insertAfter=transfer_shape_menu_item,
        optionBox=True,
        command="import ywta.deform.transfer_shape as tbs; tbs.display_menu_options()",
    )
    cmds.menuItem(
        parent=deform_menu,
        label="Duplicate Skinned Mesh",
        command="import ywta.rig.skin_duplicate as sd; sd.duplicate_skinned_mesh()",
    )
    cmds.menuItem(
        parent=deform_menu,
        label="Export Skin Weights",
        command="import ywta.deform.skinio as skinio; skinio.export_skin()",
        # image="exportSmoothSkin.png",
    )
    cmds.menuItem(
        parent=deform_menu,
        label="Import Skin Weights",
        command="import ywta.deform.skinio as skinio; skinio.import_skin(to_selected_shapes=True)",
        image="importSmoothSkin.png",
    )
    cmds.menuItem(parent=deform_menu, divider=True, dividerLabel="BlendShape")
    cmds.menuItem(
        parent=deform_menu,
        label="BlendShape Target Renamer",
        command="import ywta.deform.target_renamer as tr; tr.show_blendshape_target_renamer()",
        image="blendShape.png",
    )
    # endregion

    # region Utility
    utility_menu = cmds.menuItem(
        subMenu=True, tearOff=True, parent=menu, label="Utility"
    )
    cmds.menuItem(
        parent=utility_menu,
        label="Unit Test Runner",
        command="import ywta.test.mayaunittestui; ywta.test.mayaunittestui.show()",
        imageOverlayLabel="Test",
    )
    cmds.menuItem(
        parent=utility_menu,
        label="Reload All Modules",
        command="import ywta.reloadmodules; ywta.reloadmodules.reload_modules()",
        imageOverlayLabel="Test",
    )
    cmds.menuItem(
        parent=utility_menu,
        label="Resource Browser",
        command="import maya.app.general.resourceBrowser as rb; rb.resourceBrowser().run()",
        imageOverlayLabel="name",
    )
    cmds.menuItem(
        parent=utility_menu,
        label="Unity Exporter",
        command="import ywta.scripts.simple_unity_exporter; ywta.scripts.simple_unity_exporter.showExportUnityUI()",
        imageOverlayLabel="name",
    )
    # endregion

    cmds.menuItem(
        parent=menu,
        label="Shapes UI",
        command="import ywta.deform.shapesui; ywta.deform.shapesui.show()",
    )

    cmds.menuItem(
        parent=menu,
        label="Run Script",
        command="import ywta.pipeline.runscript; ywta.pipeline.runscript.show()",
    )

    cmds.menuItem(parent=menu, divider=True, dividerLabel="About")

    cmds.menuItem(
        parent=menu,
        label="About YWTA",
        command="import ywta.menu; ywta.menu.about()",
        image="menuIconHelp.png",
    )
    cmds.menuItem(
        parent=menu,
        label="Documentation",
        command="import ywta.menu; ywta.menu.documentation()",
        image="menuIconHelp.png",
    )


def delete_menu():
    """Deletes the YWTA menu."""
    # check if the menu exists
    if cmds.menu("YWTA", exists=True):
        cmds.deleteUI("YWTA", menu=True)


def documentation():
    """Opens the documentation web page."""
    webbrowser.open(DOCUMENTATION_ROOT)


def about():
    """Displays the YWTA About dialog."""
    name = "ywta_about"
    if cmds.window(name, exists=True):
        cmds.deleteUI(name, window=True)
    if cmds.windowPref(name, exists=True):
        cmds.windowPref(name, remove=True)
    window = cmds.window(
        name, title="About YWTA", widthHeight=(600, 500), sizeable=False
    )
    form = cmds.formLayout(nd=100)
    text = cmds.scrollField(editable=False, wordWrap=True, text=ywta.__doc__.strip())
    button = cmds.button(
        label="Documentation", command="import ywta.menu; ywta.menu.documentation()"
    )
    margin = 8
    cmds.formLayout(
        form,
        e=True,
        attachForm=(
            (text, "top", margin),
            (text, "right", margin),
            (text, "left", margin),
            (text, "bottom", 40),
            (button, "right", margin),
            (button, "left", margin),
            (button, "bottom", margin),
        ),
        attachControl=((button, "top", 2, text)),
    )
    cmds.showWindow(window)
