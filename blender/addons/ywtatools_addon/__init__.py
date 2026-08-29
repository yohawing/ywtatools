# YWTATools: 2024 yohawing
#
# The MIT License (MIT)

bl_info = {
    "name": "YWTA Tools",
    "author": "yohawing",
    "version": (0, 0, 1),
    "blender": (4, 4, 0),
    "location": "See Addon Preferences",
    "description": "Yohawing's Tools for Blender",
    "support": "COMMUNITY",
    "wiki_url": "",
    "tracker_url": "",
    "category": "User",
}

if "custom_nodes" in locals():
    import importlib

    from . import hair_tube
    from . import mesh_diagnostics
    from . import link_ui

    importlib.reload(custom_nodes)  # noqa: F821
    importlib.reload(properties)  # noqa: F821
    importlib.reload(ui)  # noqa: F821
    importlib.reload(shape_key_rename)  # noqa: F821
    importlib.reload(autoremesher)  # noqa: F821
    importlib.reload(volume_smoothing)  # noqa: F821
    importlib.reload(hair_tube)
    importlib.reload(mesh_diagnostics)
    importlib.reload(link_ui)
else:
    from . import custom_nodes
    from . import properties
    from . import ui
    from . import shape_key_rename
    from . import autoremesher
    from . import volume_smoothing
    from . import hair_tube
    from . import mesh_diagnostics
    from . import link_ui


def register():
    print("register YWTA Tools")
    custom_nodes.register()
    properties.register()
    ui.register()
    shape_key_rename.register()
    autoremesher.register()
    volume_smoothing.register()
    hair_tube.register()
    mesh_diagnostics.register()
    link_ui.register()


def unregister():
    print("unregister YWTA Tools")
    link_ui.unregister()
    mesh_diagnostics.unregister()
    hair_tube.unregister()
    volume_smoothing.unregister()
    autoremesher.unregister()
    shape_key_rename.unregister()
    custom_nodes.unregister()
    properties.unregister()
    ui.unregister()


if __name__ == "__main__":
    register()
