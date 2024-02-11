# -*- coding: utf-8 -*-
# ====================================================================
#   名前：    coyoteSkinDuplicate.py
#   説明：    スキニング後のモデルを複製
#   作者：    COYOTE 3DCG Studio TAチーム
# ====================================================================

import functools
import maya.cmds as cmds
import maya.mel as mel
import math as math

#プログレスバー
def Coyote_PROGRESS_BAR(msg='Processing...'):
    if cmds.window('Coyote_PROGRESS_WIN',q=True,ex=True)==True:cmds.deleteUI('Coyote_PROGRESS_WIN')
    win = cmds.window('Coyote_PROGRESS_WIN',s=False,wh=(300,40))
    cmds.columnLayout()
    cmds.text('Coyote_PROGRESS_MSG',l=msg)
    cmds.progressBar('Coyote_PROGRESS_PRG',width=300)
    cmds.setParent('..')
    cmds.showWindow('Coyote_PROGRESS_WIN')
    cmds.window('Coyote_PROGRESS_WIN',e=True,wh=(300,40))

    return win

def Coyote_ResetBindpose():
    """バインドポーズリセット
    """
    nodeList = cmds.ls(typ='joint')
    if not nodeList:
        res = u"再設定するジョイントを選択してください。"
        cmds.inViewMessage( amg=u'<hl>{}</hl>'.format(res), pos='midCenter', fade=True )
        cmds.warning(res)
    else:
        nodeList = cmds.ls(typ='dagPose')
        for node in nodeList:
            cmds.delete(node)
        cmds.dagPose(bp=True, save=True)

        res = u"//バインドポーズを再設定しました。//"
        cmds.inViewMessage( amg=res, pos='midCenter', fade=True )
        mel.eval(u'print("{}\\n")'.format(res))

def Coyote_ChangeSelectListToListRelatives(nodeList):
    """選択をすべての子階層に変換する
    """
    returnList = []
    for node in nodeList:
        if not cmds.listRelatives(node, ad=True, pa=True):
            continue
        returnList.append(node)
        returnList.extend(cmds.listRelatives(node, ad=True, pa=True))

    return returnList

def Coyote_optimizeUnusedIntermediateMesh():
    """選択ノードに関連する、使用していない中間ノードを返す

    Returns:
        list: 使用していない中間ノードを返す
    """
    nodes = Coyote_ChangeSelectListToListRelatives(cmds.ls(sl=True))
    nodes = cmds.ls(nodes, typ='mesh', intermediateObjects=True)

    # print("------------")
    # print(nodes)

    unused = []
    for node in nodes:
        if not cmds.listConnections(node, s=False, d=True):
            unused.append(node)

    # print("------------")
    # print(unused)

    return unused

#スキンクラスター　取得
def get_skinClusterList(node=None):
    skinClusterNode=''
    if not node is None:
        skinClusterNode=(mel.eval('findRelatedSkinCluster ' + node))
    return skinClusterNode

#インフルエンス取得
def get_InfluenceList(skinClusterNode=None):
    returnList=[]
    if skinClusterNode is not None:
        returnList.extend(cmds.skinCluster(skinClusterNode,q=True,wi=True))

    return returnList

#ウエイト情報　取得
def get_skinWeightList(skinClusterNode=None,inflList=[],vtxList=[]):
    returnDictList={'_init':None}
    returnList=[]
    if not skinClusterNode is None:

        returnList=[[cmds.skinPercent(skinClusterNode,vtx,t=infl,q=True) for infl in inflList ] for vtx in vtxList]

    return returnList

#選択式ウエイトコピー　計算処理
def Coyote_addWeightCopy_culProc(skinPctList=None,tgtSkiPctList=None):
    tempList=[]
    returnList=[]

    for (sourceList,targetList) in zip(skinPctList,tgtSkiPctList):
        for(listX,listY) in zip(sourceList,targetList):
            tempList.append([x+y for(x,y) in zip(listX,listY)])

    for list in tempList:
        max=sum(list)
        returnList.append([x/max for x in list] for list in tempList)

    return returnList

#ダイレクトウエイトコピー
def Coyote_DirectWeightCopy_proc(targetVtxList=None,sourceNode=None,targetNode=None,inflenceList=None,sourceSkinCluster=None,targetSkinCluster=None,addMode=False):

    if not targetVtxList is None:
        #getVtxList
        indexList=[x.split('.')[len(x.split('.'))-1] for x in targetVtxList]
        inflList=[x.split('|')[len(x.split('|'))-1] for x in inflenceList]

        cmds.select(targetVtxList)
        cmds.setAttr((targetSkinCluster + '.normalizeWeights'),0)
        cmds.skinPercent(targetSkinCluster,prw=1.1)
        cmds.select(cl=True)

        if cmds.progressBar('Coyote_PROGRESS_PRG',q=True,ex=True):
            cmds.progressBar('Coyote_PROGRESS_PRG',e=True,max=len(inflList))


        cmds.progressBar('Coyote_PROGRESS_PRG',e=True,pr=0)
        i=0
        if addMode==False:
            for infl in inflList:
                cmds.progressBar('Coyote_PROGRESS_PRG',e=True,s=1)

                skinPctList=get_skinWeightList(sourceSkinCluster,[infl],[sourceNode+'.'+index for index in indexList])
                [cmds.skinPercent(targetSkinCluster,vtx,tv=('%s'%infl,skinVal[0])) if skinVal[0]>0.0 else 0.0 for (vtx,skinVal) in zip(targetVtxList,skinPctList)]
        else:
            skinPctList=[]
            tgtSkiPctList=[]
            skinPctList.append(get_skinWeightList(sourceSkinCluster,inflList,[sourceNode+'.'+index for index in indexList]))
            tgtSkiPctList.append(get_skinWeightList(targetSkinCluster,inflList,[targetNode+'.'+index for index in indexList]))

            cmds.progressBar('Coyote_PROGRESS_PRG',e=True,pr=0)

            newSkinPctList=Coyote_addWeightCopy_culProc(skinPctList,tgtSkiPctList)

            for (infl,skinValList) in zip(inflList,newSkinPctList):
                cmds.progressBar('Coyote_PROGRESS_PRG',e=True,s=1)
                [cmds.skinPercent(targetSkinCluster,vtx,tv=('%s'%infl,skinVal)) if skinVal>0.0 else 0.0 for (vtx,skinVal) in zip (targetVtxList,skinValList)]


        cmds.setAttr((targetSkinCluster + '.normalizeWeights'),1)

#ダイレクトウエイトコピー　処理開始
def Coyote_DirectWeightCopy_start(sourceNode=None,targetNode=None):

    if not targetNode is None:
        targetVtxList=cmds.ls(targetNode+'.vtx[*]',fl=True)

        sourceSkinCluster=get_skinClusterList(sourceNode)
        targetSkinCluster=get_skinClusterList(targetNode)
        inflenceList=[]
        inflenceList = get_InfluenceList(sourceSkinCluster)

        win=Coyote_PROGRESS_BAR()
        Coyote_DirectWeightCopy_proc(targetVtxList,sourceNode,targetNode,inflenceList,sourceSkinCluster,targetSkinCluster)
        cmds.deleteUI(win)

#スキンの複製・きれいにする
def Coyote_skinDuplicate(*args):
    node_list=[]
    joint_list=[]
    pre_joint_list=[]
    attr_list=[]
    vtx_list=[]
    del node_list
    node_list = cmds.ls(sl=True, ni=True, dag=True, typ="mesh")
    node_list = cmds.listRelatives(node_list, p=True)

    if not node_list:
        res = u"メッシュモデルを選択してください。"
        cmds.inViewMessage( amg=u'<hl>{}</hl>'.format(res), pos='midCenter', fade=True )
        cmds.warning(res)
        return

    for node in node_list:
        #スキンクラスターを探す
        command = 'findRelatedSkinCluster ("{}")'.format(node)
        skincluster = mel.eval(command)
        if skincluster:
            joint_list[:] = []
            maxInfluence = cmds.skinCluster(node,q=True,mi=True)
            obayMI = cmds.skinCluster(node,q=True,omi=True)
            vtx_list = cmds.ls(node + ".vtx[*]")

            del joint_list
            joint_list = cmds.skinCluster(skincluster,q=True,inf=True)

            old_node = cmds.rename(node,(node + '_old'))
            dup_node = cmds.duplicate(old_node,n=node)[0]

            Unuse_inNodeList =[]
            cmds.select(dup_node)
            Unuse_inNodeList = Coyote_optimizeUnusedIntermediateMesh()

            if len(Unuse_inNodeList)>0:
                cmds.delete(Unuse_inNodeList)

            for attr in ['.tx','.ty','.tz','.rx','.ry','.rz','.sx','.sy','.sz',]:
                cmds.setAttr(dup_node + attr,l=False)

            cmds.select(dup_node)
            mel.eval('DeleteHistory')
            cmds.select(cl=True)
            if cmds.objExists((dup_node + 'ShapeOrig')):
                cmds.delete((dup_node + 'ShapeOrig'))
            bindpose=cmds.dagPose(joint_list,q=True,bp=True)
            cmds.delete(bindpose)
            cmds.skinCluster(joint_list,dup_node,tsb=True,nw=1,mi=maxInfluence,omi=obayMI)
            cmds.select(old_node)
            cmds.select(dup_node,add=True)
            if cmds.checkBox('Coyote_SDP_DWCcheck',q=True,v=True)==1:
                mel.eval('doBakeNonDefHistory( 1, {"prePost" });')
                Coyote_DirectWeightCopy_start(old_node,dup_node)
            else:
                mel.eval('CopySkinWeights')
    try:
        cmds.select(joint_list)
        Coyote_ResetBindpose()
        cmds.select(cl=True)
    except:
        res = u"バインドポーズの再設定に失敗しました。　ジョイントにエクスプレッションやアニメーションが適応されたままではありませんか？"
        cmds.inViewMessage( amg=u'<hl>{}</hl>'.format(res), pos='midCenter', fade=True )
        cmds.warning(res)

    cmds.headsUpMessage('[Finished]')


# --------------------------------------------------------------------
#   以下GUI関連
# --------------------------------------------------------------------
def makeOptionVar():
    """UIのOptionVarの初期値を作成
    """
    if cmds.optionVar(exists='Coyote_SDP_DWCcheck') == False:
        cmds.optionVar(iv=('Coyote_SDP_DWCcheck', 0))

def checkBoxOptVar(checkBoxName, optionVarName, *args):
    """checkBoxの値をOptionVarに入れる
    
    args:
    checkBoxName :   checkBox名
    optionVarName :   optionVar名
    """
    value = cmds.checkBox(checkBoxName, q=True, value=True)
    cmds.optionVar(iv=(optionVarName, value))

def showUI():
    """UI作成
    """
    win = 'CoyoteSkinDuplicate'
    ver = 'v1.0.0'
    title = 'Coyote Skin Duplicate {}'.format(ver)
    # UIのOptionVarの初期値を作成
    makeOptionVar()

    #ウィンドウがすでに存在していたら削除して再表示
    if cmds.window(win, q=True, ex=True):
        cmds.deleteUI(win)

    cmds.window(win, title=title, menuBar=True, s=True, width=330, height=70)
    cmds.columnLayout(adjustableColumn=True, rowSpacing=10)

    ann = u'スキニング後のモデルを複製します。\nヒストリ削除・不要な中間ノード削除・ウェイトコピーまでを自動化。'
    cmds.button(label=u'Skin Duplicate', command=Coyote_skinDuplicate, height=35, ann=ann)

    ann = u'頂点単位でウェイト転写します。\nチェックがOFFならCopy Skin Weightsを実行。'
    cmds.checkBox('Coyote_SDP_DWCcheck',label=u"Direct Weight Copy Mode", align="center",\
                        value=cmds.optionVar(q='Coyote_SDP_DWCcheck'),\
                        cc=functools.partial(checkBoxOptVar, 'Coyote_SDP_DWCcheck','Coyote_SDP_DWCcheck'),\
                        ann=ann)

    cmds.showWindow()
