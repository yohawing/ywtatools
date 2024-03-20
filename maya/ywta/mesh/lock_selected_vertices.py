# -*- coding: utf-8 -*-
import maya.cmds as cmds
import maya.mel as mel

# Invert selection
def invSelection( *args ):
	mel.eval( 'invertSelection' )

# Lock selected Vertices
def lock( *args ):
	selection = cmds.ls( fl=True, sl=True )
	verts = cmds.filterExpand( selection, sm=31 )

	for v in verts:
		cmds.setAttr( v, l=True )

# Unlock selected Vertices
def unlock( *args ):
	selection = cmds.ls( fl=True, sl=True )
	verts = cmds.filterExpand( selection, sm=31 )

	for v in verts:
		cmds.setAttr( v, l=False )