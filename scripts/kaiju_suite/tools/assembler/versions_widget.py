"""Version windows: the prompt for a short description of what changed, asked
on Publish, and the Versions window, the item's changelog (every version
with its date and description, to restore or compare). The data comes from
:mod:`.versions`."""

from PySide6 import QtCore, QtGui, QtWidgets

from kaiju_suite.tools.assembler import versions

_HEADERS = ("Version", "Date", "Description")


class DescriptionDialog(QtWidgets.QDialog):
    """Asks for a description of a change. It's optional: left empty, the
    version reads "(no description)". ``text`` is what the box starts with,
    e.g. a folder's changed items."""

    def __init__(self, parent, title, text=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("Describe what changed (optional):"))
        self._edit = QtWidgets.QLineEdit(text)
        self._edit.setPlaceholderText(versions.NO_DESCRIPTION)
        layout.addWidget(self._edit)
        Button = QtWidgets.QDialogButtonBox.StandardButton
        buttons = QtWidgets.QDialogButtonBox(Button.Ok | Button.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.ok_button = buttons.button(Button.Ok)

    def description(self):
        return self._edit.text().strip()


def ask_description(parent, title, text=""):
    """Ask for a description; returns it, or ``None`` if cancelled."""
    dialog = DescriptionDialog(parent, title, text)
    return dialog.description() if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted else None


class VersionsDialog(QtWidgets.QDialog):
    """Non-modal changelog of ``make_changelog()`` (a :class:`.versions.Changelog`).

    Restore calls ``restore(action)`` with the selected row's Restore
    :class:`Action`, then rebuilds; Compare calls ``compare(number)``.
    """

    def __init__(self, parent, title, make_changelog, restore, compare):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(title)
        self._make_changelog = make_changelog
        self._restore = restore
        self._compare = compare
        self._rows = []
        layout = QtWidgets.QVBoxLayout(self)

        self._summary = QtWidgets.QLabel()
        layout.addWidget(self._summary)
        self._table = QtWidgets.QTableWidget(0, len(_HEADERS))
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.verticalHeader().hide()
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self._table.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self._table, 1)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        self._restore_button = QtWidgets.QPushButton("Restore")
        self._restore_button.clicked.connect(self._on_restore)
        buttons.addWidget(self._restore_button)
        self._compare_button = QtWidgets.QPushButton("Compare")
        self._compare_button.setToolTip("Compare this version with the file as it is now")
        self._compare_button.clicked.connect(self._on_compare)
        buttons.addWidget(self._compare_button)
        layout.addLayout(buttons)

        self.reload()
        self.resize(640, 360)

    def reload(self):
        """Re-read the changelog, e.g. after a restore or a publish. The
        selected version stays selected."""
        selected = self._selected()
        changelog = self._make_changelog()
        self._rows = changelog.rows
        self._summary.setText(changelog.summary)
        self._compare_button.setVisible(changelog.can_compare)
        self._table.clearSelection()
        self._table.setRowCount(len(self._rows))
        for r, row in enumerate(self._rows):
            tag = QtWidgets.QTableWidgetItem(f"{row.tag} (current)" if row.current else row.tag)
            description = QtWidgets.QTableWidgetItem(row.description)
            description.setToolTip(row.description)
            items = (tag, QtWidgets.QTableWidgetItem(row.when), description)
            for column, item in enumerate(items):
                if row.current:
                    font = QtGui.QFont(item.font())
                    font.setBold(True)
                    item.setFont(font)
                self._table.setItem(r, column, item)
            if selected is not None and row.number == selected.number:
                self._table.selectRow(r)
        self._update_buttons()

    def _selected(self):
        rows = self._table.selectionModel().selectedRows()
        return self._rows[rows[0].row()] if rows else None

    def _update_buttons(self):
        row = self._selected()
        self._restore_button.setEnabled(row is not None and row.restore is not None)
        self._compare_button.setEnabled(row is not None and not row.current)

    def _on_restore(self):
        row = self._selected()
        if row is not None and row.restore is not None:
            self._restore(row.restore)
            self.reload()

    def _on_compare(self):
        row = self._selected()
        if row is not None and not row.current:
            self._compare(row.number)
