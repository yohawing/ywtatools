import json

try:
    from PySide6.QtCore import QStringListModel
except ImportError:
    from PySide2.QtCore import QStringListModel

from ywta.core import settings_utils


class StringCache(QStringListModel):
    """A QStringListModel that saves its values in a persistent cache."""

    def __init__(self, name, max_values=10, parent=None):
        """Constructor

        :param name: Name used to query persistent data
        :param max_values: Maximum number of values to store in the cache
        :param parent: QWidget parent
        """
        super(StringCache, self).__init__(parent)
        self._name = name
        self.max_values = max_values
        data = settings_utils.get_setting(self._name)
        if data:
            data = json.loads(data)
            self.setStringList(data)

    def push(self, value):
        """Push a new value onto the cache stack.

        :param value: New value.
        """
        values = self.stringList()
        if value in values:
            values.remove(value)
        values.insert(0, value)
        if len(values) > self.max_values:
            values = values[: self.max_values]
        self.setStringList(values)
        self._save()

    def _save(self):
        """Saves the string list to the persistent cache."""
        settings_utils.set_setting(self._name, json.dumps(self.stringList()))
