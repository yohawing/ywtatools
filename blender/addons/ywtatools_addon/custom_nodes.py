import bpy
import math

# カスタムノードの定義

class NodeVectorAngle(bpy.types.Node):
    '''ベクトル間の角度を計算するノード'''
    bl_idname = 'VectorAngleNodeType'
    bl_label = 'Angle From Vector'
    bl_icon = 'NODE'

    my_float_prop: bpy.props.FloatProperty(default=3.1415926)


    def init(self, context):
        self.inputs.new('NodeSocketVector', "vector1")
        self.inputs.new('NodeSocketVector', "vector2")
        self.outputs.new('NodeSocketFloat', "degree")

    def update(self):
        input1 = self.inputs["vector1"].default_value
        input2 = self.inputs["vector2"].default_value
        vec1 = Vector((input1[0], input1[1], input1[2]))
        vec2 = Vector((input2[0], input2[1], input2[2]))
        angle = vec1.angle(vec2)
        self.outputs["degree"].default_value = math.degrees(angle)

    def copy(self, node):
        print("Copying from node ", node)

    # Free function to clean up on removal.
    def free(self):
        print("Removing node ", self, ", Goodbye!")

    # Additional buttons displayed on the node.
    def draw_buttons(self, context, layout):
        layout.label(text="Node settings")
        layout.prop(self, "my_float_prop")


class EXTRANODEGROUPWRAPPER_NG_group_wrapper(bpy.types.GeometryNodeCustomGroup):
    bl_idname = "GeometryNodeGroupWrapper"
    bl_label = "Group Wrapper"

    @classmethod
    def poll(cls, context):  #mandatory with geonode
        """If this returns False, when trying to add the node from an operator you will get an error."""
        return True

    def init(self, context):
        """this is run when appending the node for the first time"""
        self.width = 250
        # here you could set the node group you want to wrap on startup
        # self.node_tree = ...

    def copy(self, node):
        """Run when dupplicating the node"""
        self.node_tree = node.node_tree.copy()

    def update(self):
        """generic update function. Called when the node tree is updated"""
        pass

    def draw_label(self,):
        """The return result of this is used shown as the label of the node"""
        if not self.node_tree:
            return "Pick a group!"
        return self.node_tree.name if self.node_tree.name else ""

    def draw_buttons(self, context, layout):
        """This is where you can draw custom properties for your node"""

        # remove this if you don't want people to be able to change which node is selected
        layout.template_ID(self, "node_tree")

# カスタムノードのカテゴリー登録
class NODE_MT_category_GEO_EXTRA(bpy.types.Menu):

    bl_idname = "NODE_MT_category_GEO_EXTRA"
    bl_label = "Extra"

    @classmethod
    def poll(cls, context):
        return (bpy.context.space_data.tree_type == "GeometryNodeTree")

    def draw(self, context):
        return None

def extra_node_group_wrapper(self, context):
    """extend extra menu with new node"""
    op = self.layout.operator("node.add_node", text=EXTRANODEGROUPWRAPPER_NG_group_wrapper.bl_label)
    op.type = EXTRANODEGROUPWRAPPER_NG_group_wrapper.bl_idname
    op.use_transform = True
    op = self.layout.operator("node.add_node", text=NodeVectorAngle.bl_label)
    op.type = NodeVectorAngle.bl_idname
    op.use_transform = True

def extra_geonode_menu(self, context):
    """extend NODE_MT_add with new extra menu"""
    self.layout.menu(NODE_MT_category_GEO_EXTRA.bl_idname, text=NODE_MT_category_GEO_EXTRA.bl_label)
    return None


def register_menus():
    """register extra menu, if not already, append item, if not already"""

    #register new extra menu class if not exists already, perhaps another plugin already implemented it
    if "NODE_MT_category_GEO_EXTRA" not in bpy.types.__dir__():
        bpy.utils.register_class(NODE_MT_category_GEO_EXTRA)

    #extend add menu with extra menu if not already, _dyn_ui_initialize() will get appended drawing functions of a menu
    add_menu = bpy.types.NODE_MT_add
    if "extra_geonode_menu" not in [f.__name__ for f in add_menu._dyn_ui_initialize()]:
        add_menu.append(extra_geonode_menu)

    #extend extra menu with our custom nodes if not already
    extra_menu = bpy.types.NODE_MT_category_GEO_EXTRA
    if "extra_node_group_wrapper" not in [f.__name__ for f in extra_menu._dyn_ui_initialize()]:
        extra_menu.append(extra_node_group_wrapper)

    return None

def unregister_menus():

    add_menu = bpy.types.NODE_MT_add
    extra_menu = bpy.types.NODE_MT_category_GEO_EXTRA

    #remove our custom function to extra menu
    for f in extra_menu._dyn_ui_initialize().copy():
        if (f.__name__ == "extra_node_group_wrapper"):
            extra_menu.remove(f)

    #if extra menu is empty
    if len(extra_menu._dyn_ui_initialize()) == 1:

        #remove our extra menu item draw fct add menu
        for f in add_menu._dyn_ui_initialize().copy():
            if (f.__name__ == "extra_geonode_menu"):
                add_menu.remove(f)

        #unregister extra menu
        bpy.utils.unregister_class(extra_menu)

    return None

classes = [
    EXTRANODEGROUPWRAPPER_NG_group_wrapper,
    NodeVectorAngle,
]

def register():

    #classes
    for cls in classes:
        bpy.utils.register_class(cls)

    #extend add menu
    register_menus()

    return None


def unregister():

    #extend add menu
    unregister_menus()

    #classes
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    return None

if __name__ == "__main__":
    register()