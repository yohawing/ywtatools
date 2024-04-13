from math import e
import sys
import importlib
import ywta

DEFAULT_RELOAD_PACKAGES = ["ywta"]

class RollbackImporter(object):
    """Used to remove imported modules from the module list.

    This allows tests to be rerun after code updates without doing any reloads.
    Original idea from: http://pyunit.sourceforge.net/notes/reloading.html

    Usage:
    def run_tests(self):
        if self.rollback_importer:
            self.rollback_importer.uninstall()
        self.rollback_importer = RollbackImporter()
        self.load_and_execute_tests()
    """

    def __init__(self):
        """Creates an instance and installs as the global importer"""
        self.previous_modules = set(sys.modules.keys())

    def uninstall(self):
        for modname in sys.modules.keys():
            if modname not in self.previous_modules:
                # Force reload when modname next imported
                try:
                    # del(sys.modules[modname])
                    importlib.reload(sys.modules[modname])
                    print(f"Unloaded: {modname}")
                except:
                    pass

    def unload_packages(self, packages=None):
        if packages is None:
            packages = DEFAULT_RELOAD_PACKAGES

        # construct reload list
        reloadList = []
        for i in sys.modules.keys():
            for package in packages:
                if i.startswith(package):
                    reloadList.append(i)

        # unload everything
        for modname in reloadList:
            try:
                if sys.modules[modname] is not None:
                    importlib.reload(sys.modules[modname])
                    print(f"Unloaded: {modname}")
            except:
                print(f"Failed to unload: {modname}")

        ywta.initialize()


_rollbackimporter = RollbackImporter()


def save_modules():
    global _rollbackimporter
    _rollbackimporter = RollbackImporter()

def reload_modules():
    global _rollbackimporter
    _rollbackimporter.uninstall()

def unload_packages():
    global _rollbackimporter
    _rollbackimporter.unload_packages()
