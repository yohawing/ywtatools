# YWTATools: 2024 yohawing
#
# The MIT License (MIT)

bl_info = {
    "name": "YWTA Tools",
    "author": "yohawing",
    "version": (0, 0, 1),
    "blender": (4, 0, 0),
    "location": "See Addon Preferences",
    "description": "Yohawing's Tools for Blender",
    "support": "COMMUNITY",
    "wiki_url": "",
    "tracker_url": "",
    "category": "User",
}

if "bpy" in locals():
    import importlib
    importlib.reload(custom_nodes)
    importlib.reload(properties)
    importlib.reload(ui)
else:
    from . import custom_nodes
    from . import properties
    from . import ui

import bpy

def register():
    print("register YWTA Tools")
    custom_nodes.register()
    properties.register()
    ui.register()

def unregister():
    print("unregister YWTA Tools")
    custom_nodes.unregister()
    properties.unregister()
    ui.unregister()

if __name__ == "__main__":
    register()