import bpy
from bpy.types import Panel

#
# Add additional functions here
#

class ObjectSelectPanel(bpy.types.Panel):
    bl_idname = "OBJECT_PT_select"
    bl_label = "Select"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return (context.object is not None)

    def draw_header(self, context):
        layout = self.layout
        layout.label(text="My Select Panel")

    def draw(self, context):
        layout = self.layout

        box = layout.box()
        box.label(text="Selection Tools")
        box.operator("object.select_all").action = 'TOGGLE'
        row = box.row()
        row.operator("object.select_all").action = 'INVERT'
        row.operator("object.select_random")

class MyPanel(Panel):
    bl_idname = "OBJECT_PT_awesom_panel"
    bl_label = 'YWTA render panel'
    bl_space_type = 'PROPERTIES'
    bl_region_type= 'WINDOW'
    bl_context = 'render'

    def draw(self, context):
        row = self.layout.row()
        row.prop(context.scene, 'my_property')


class YWTAToolsPanel(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "YWTA"
    bl_label = "info"

    @classmethod
    def poll(cls, context):
        return (context.object is not None)

    def draw(self, context):
        self.layout.label(text=" Yohawing's Tools for Blender")

        # add a reload module button
        self.layout.operator("script.reload")

        # add a button to open the preferences
        self.layout.operator("wm.preferences_open")


classes = [
    YWTAToolsPanel,
    ObjectSelectPanel,
    # MyPanel,
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)