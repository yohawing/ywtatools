import maya.cmds as cmds
import maya.mel as mel
from functools import partial
import os

# reference
# https://gist.github.com/timborrelli/2c6c7dafa6e0f87ba88642a6330da8fd

# ネームスペースを消そうとするが、ReferenceされたNamespaceは削除できないようになってる。
# defaults = ['UI', 'shared']
# namespaces = [ns for ns in cmds.namespaceInfo(listOnlyNamespaces=True, recurse=True) if ns not in defaults]
# for ns in namespaces: print(ns)
# namespaces.sort(key=len, reverse=True)
# for ns in namespaces:
#     if cmds.namespace(exists=ns) is True:
#         cmds.namespace(removeNamespace=ns, mergeNamespaceWithRoot=True)


def export_for_unity(*args):
    cmds.loadPlugin("fbxmaya", quiet=True)  # FBXプラグインをロード

    cmds.select(cl=True)
    if cmds.checkBox("Export_Animation_Checkbox", q=True, value=True):
        cmds.select(cmds.textFieldGrp("Motion_Export_Set", q=True, text=True))
    else:
        cmds.select(cmds.textFieldGrp("Model_Export_Set", q=True, text=True))

    current_file_name = cmds.file(q=True, sn=True, shn=True).split(".")[0]

    export_file_path = os.path.join(
        cmds.optionVar(q="Unity_Project_Path"),
        cmds.optionVar(q="Assets_Path"),
        current_file_name + ".fbx",
    )

    print("Export Path: ", export_file_path)

    exportFBX(export_file_path)


def exportFBX(exportFileName):
    # store current user FBX settings
    mel.eval("FBXPushSettings;")

    # export selected as FBX
    # Geometry
    mel.eval("FBXExportSmoothingGroups -v true")
    mel.eval("FBXExportHardEdges -v false")
    mel.eval("FBXExportTangents -v false")
    mel.eval("FBXExportSmoothMesh -v true")
    mel.eval("FBXExportInstances -v false")
    mel.eval("FBXExportReferencedAssetsContent -v false")
    if cmds.checkBox("Export_Animation_Checkbox", q=True, value=True):
        mel.eval("FBXExportAnimationOnly -v false")
        mel.eval("FBXExportBakeComplexAnimation -v true")
        mel.eval(
            "FBXExportBakeComplexStart -v "
            + str(cmds.playbackOptions(q=True, min=True))
        )
        mel.eval(
            "FBXExportBakeComplexEnd -v " + str(cmds.playbackOptions(q=True, max=True))
        )
        mel.eval("FBXExportBakeComplexStep -v 1")
    mel.eval("FBXExportUseSceneName -v false")
    mel.eval("FBXExportQuaternion -v euler")
    mel.eval("FBXExportShapes -v true")
    mel.eval("FBXExportSkins -v true")
    # Constraints
    mel.eval("FBXExportConstraints -v false")
    # Cameras
    mel.eval("FBXExportCameras -v false")
    # Lights
    mel.eval("FBXExportLights -v false")
    # Embed Media
    mel.eval("FBXExportEmbeddedTextures -v false")
    # Connections
    mel.eval("FBXExportInputConnections -v false")
    # Axis Conversion
    mel.eval("FBXExportUpAxis y")
    # Version
    mel.eval("FBXExportFileVersion -v FBX201800")
    mel.eval("FBXExportInAscii -v false")

    cmds.file(
        exportFileName, exportSelected=True, type="FBX export", force=True, prompt=False
    )

    # restore current user FBX settings
    mel.eval("FBXPopSettings;")


def makeOptionVar():
    """UIのOptionVarの初期値を作成"""
    if cmds.optionVar(exists="Unity_Project_Path") == False:
        cmds.optionVar(stringValue=("Unity_Project_Path", "path\\to\\dir"))

    if cmds.optionVar(exists="Assets_Path") == False:
        cmds.optionVar(stringValue=("Assets_Path", "Assets\\Resources"))


def setOptionVar(textFieldGrp, optionVarName, *args):
    """textFieldGrpの値をOptionVarに保存する"""

    textFieldGrpValue = cmds.textFieldGrp(textFieldGrp, q=True, text=True)
    cmds.optionVar(stringValue=(optionVarName, textFieldGrpValue))


def showExportUnityUI():
    """UI作成"""
    win = "UnityExporter"
    ver = "v1.0.0"
    title = "UnityExporter {}".format(ver)
    # UIのOptionVarの初期値を作成
    makeOptionVar()

    # ウィンドウがすでに存在していたら削除して再表示
    if cmds.window(win, q=True, ex=True):
        cmds.deleteUI(win)

    cmds.window(win, title=title, menuBar=True, s=True, width=330, height=70)
    cmds.columnLayout(adjustableColumn=True, rowSpacing=10)

    cmds.text(label="Export to Unity")

    cmds.textFieldGrp("Model_Export_Set", text="exportSet", label="Model Export Set")
    cmds.textFieldGrp(
        "Motion_Export_Set", text="exportMotionSet", label="Animation Export Set"
    )

    cmds.textFieldGrp(
        "Project_Path_Field",
        label="Project Path",
        text=cmds.optionVar(q="Unity_Project_Path"),
        cc=partial(setOptionVar, "Project_Path_Field", "Unity_Project_Path"),
        ann="Unityプロジェクトのディレクトリを指定します。",
    )
    cmds.textFieldGrp(
        "Assets_Path_Field",
        label="Assets Dir",
        text=cmds.optionVar(q="Assets_Path"),
        cc=partial(setOptionVar, "Assets_Path_Field", "Assets_Path"),
        ann="出力するアセットのディレクトリを指定します。",
    )

    cmds.checkBox(
        "Export_Animation_Checkbox",
        label="Export_Animation",
        value=("motion" in cmds.file(q=True, sn=True, shn=True)),
        # cc=partial(checkBoxOptVar, 'Export_Animation_Checkbox', 'Export_Animation'),
        ann="アニメーションを出力するかを指定します。",
    )

    cmds.button(label="Export", command=export_for_unity, height=35)

    cmds.showWindow()
