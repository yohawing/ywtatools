import bpy
from bpy.types import Scene

from bpy.props import BoolProperty
# from bpy.props import CollectionProperty
# from bpy.props import EnumProperty
# from bpy.props import FloatProperty
# from bpy.props import IntProperty
# from bpy.props import PointerProperty
# from bpy.props import StringProperty
# from bpy.props import PropertyGroup


def register():
    Scene.my_property = BoolProperty(default=True)

def unregister():
    del Scene.my_property