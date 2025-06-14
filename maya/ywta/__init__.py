import logging
import sys

log = logging.getLogger(__name__)

def initialize():
    import ywta.reloadmodules
    import ywta.menu

    ywta.menu.create_menu()

# Dependencies:
#   - ywta.test.mayaunittest