"""A QC tab for a datatype tool: a Run Checks button above a list of the
checks, each with its problems folded under it once run. A check with
options has an options button (sliders icon) on its row that opens them
(:class:`QCOptionsDialog`); hover the check to see them. A check with a
``fix`` gets a Fix button (wrench icon) at the right of its row when a
run finds something. Also :class:`QCResultsDialog`, results in a dialog with a
go-ahead button (Builder's Publish shows it when QC finds problems).

The tool passes in its checks (:class:`kaiju_suite.core.checks.Check`) and
callbacks, so this never imports ``datatypes`` or a tool:

- ``on_setting(key, option, value)``: an option changed.
- ``on_run()``: run the checks on the selection; returns ``(check,
  problems)`` pairs, or ``None`` after warning why it couldn't.
- ``on_pick(problem)``: a problem was clicked; select what it points at.
- ``on_fix(check)`` (optional): fix what ``check`` found, then return fresh
  ``(check, problems)`` pairs, or ``None`` after warning why it couldn't.
"""

from PySide6 import QtCore, QtWidgets

from kaiju_suite.ui import icons, status_icons

# An index into QCResults.problems: Qt would turn a Problem into plain text,
# losing what it selects.
PROBLEM_ROLE = QtCore.Qt.ItemDataRole.UserRole
OK_COLOR = "#5cb85c"
FOUND_COLOR = "#e8a33d"
OPTIONS_ICON = "qc_options.svg"
FIX_ICON = "qc_fix.svg"
# The Run Checks button's background after a run: every check passed, or not.
PASS_BUTTON_COLOR = "#3f8f4f"
FAIL_BUTTON_COLOR = "#e53935"


def option_label(option):
    """``"max_influences"`` → ``"Max influences"``."""
    return option.replace("_", " ").capitalize()


def result_label(check, problems):
    """The heading of a check's results, e.g. ``"Tiny weights: 2 found"``."""
    return f"{check.label}: {len(problems)} found" if problems else f"{check.label}: OK"


class QCResults(QtWidgets.QTreeWidget):
    """A row per check, with its problems under it once run (expanded if
    ``expand``); clicking a problem calls ``on_pick`` with it. Rows for
    ``checks`` are there before any run; other checks get a row when their
    results come in."""

    def __init__(self, on_pick, checks=(), expand=False, parent=None):
        super().__init__(parent)
        self.on_pick, self.expand = on_pick, expand
        self.problems = []
        self.rows = {}
        self.setHeaderHidden(True)
        # Column 1 holds a check's options button, column 2 its Fix button.
        self.setColumnCount(3)
        header = self.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.setToolTip("Click a problem to select what it points at.")
        self.itemClicked.connect(self._picked)
        for check in checks:
            self._row(check)

    def _row(self, check):
        row = self.rows.get(check.key)
        if row is None:
            row = QtWidgets.QTreeWidgetItem([check.label])
            row.setToolTip(0, check.description)
            self.addTopLevelItem(row)
            self.rows[check.key] = row
        return row

    def show_results(self, found):
        """Put ``(check, problems)`` pairs under their checks' rows; returns
        how many problems there are."""
        self.problems = []
        for row in self.rows.values():
            row.takeChildren()
        for check, problems in found:
            row = self._row(check)
            row.setText(0, result_label(check, problems))
            color = FOUND_COLOR if problems else OK_COLOR
            row.setIcon(0, status_icons.cross(color) if problems else status_icons.check(color))
            for problem in problems:
                child = QtWidgets.QTreeWidgetItem([str(problem)])
                child.setData(0, PROBLEM_ROLE, len(self.problems))
                child.setToolTip(0, str(problem))
                self.problems.append(problem)
                row.addChild(child)
                child.setFirstColumnSpanned(True)
            row.setExpanded(self.expand and bool(problems))
        return len(self.problems)

    def _picked(self, item, _column):
        index = item.data(0, PROBLEM_ROLE)
        if index is not None:
            self.on_pick(self.problems[index])


class QCTab(QtWidgets.QWidget):
    def __init__(self, checks, settings, on_setting, on_run, on_pick, parent=None, on_fix=None):
        super().__init__(parent)
        self.on_setting, self.on_run, self.on_fix = on_setting, on_run, on_fix
        self.fix_buttons = {}
        layout = QtWidgets.QVBoxLayout(self)

        self.run_button = QtWidgets.QPushButton("Run Checks")
        self.run_button.setToolTip(
            "Run every check below on the selected meshes. Changes nothing. "
            "Turns green when they all pass, red when any finds a problem."
        )
        self.run_button.clicked.connect(self._run)
        layout.addWidget(self.run_button)

        self.checks = {check.key: check for check in checks}
        self.settings = {check.key: dict(settings[check.key]) for check in checks}
        self.results = QCResults(on_pick, checks)
        for check in checks:
            self._show_options(check)
            if check.options:
                button = QtWidgets.QToolButton()
                button.setIcon(icons.icon(OPTIONS_ICON))
                button.setAutoRaise(True)
                button.setToolTip("Options...")
                button.clicked.connect(lambda _=False, check=check: self._edit_options(check))
                self.results.setItemWidget(self.results.rows[check.key], 1, button)
            if check.fix and on_fix:
                fix = QtWidgets.QToolButton()
                fix.setIcon(icons.icon(FIX_ICON))
                fix.setAutoRaise(True)
                fix.setToolTip(f"Fix what {check.label} found, as one undo step, then run the checks again.")
                fix.clicked.connect(lambda _=False, check=check: self._fix(check))
                self.results.setItemWidget(self.results.rows[check.key], 2, fix)
                fix.hide()  # after setItemWidget, which shows it
                self.fix_buttons[check.key] = fix
        layout.addWidget(self.results, 1)
        self.status = QtWidgets.QLabel("Select meshes and click Run Checks. Click a check's button to set its options.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def _show_options(self, check):
        lines = [check.description]
        lines += [f"{option_label(option)}: {self.settings[check.key][option]:g}" for option in check.options]
        self.results.rows[check.key].setToolTip(0, "\n".join(lines))

    def _edit_options(self, check):
        key = check.key
        current = {option: self.settings[key][option] for option in check.options}
        dialog = QCOptionsDialog(self, check, current)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        for option, value in dialog.values().items():
            if value != current[option]:
                self.settings[key][option] = value
                self.on_setting(key, option, value)
        self._show_options(check)

    def _run(self):
        found = self.on_run()
        if found is not None:
            self._show(found)

    def _fix(self, check):
        found = self.on_fix(check)
        if found is not None:
            self._show(found)

    def _show(self, found):
        total = self.results.show_results(found)
        problems = {check.key: problems for check, problems in found}
        for key, button in self.fix_buttons.items():
            button.setVisible(bool(problems.get(key)))
        color = FAIL_BUTTON_COLOR if total else PASS_BUTTON_COLOR
        self.run_button.setStyleSheet(f"QPushButton {{ background-color: {color}; color: white; }}")
        self.status.setText(f"{total} problem(s) found." if total else "No problems found.")


class QCOptionsDialog(QtWidgets.QDialog):
    """A row per option of ``check``, its label then a spin box starting at
    ``values``, with OK and Cancel. After ``exec()``, :meth:`values` gives
    what was set."""

    def __init__(self, parent, check, values):
        super().__init__(parent)
        self.check = check
        self.setWindowTitle(f"{check.label} Options")
        layout = QtWidgets.QVBoxLayout(self)
        label = QtWidgets.QLabel(check.description)
        label.setWordWrap(True)
        layout.addWidget(label)
        form = QtWidgets.QFormLayout()
        self.spins = {}
        for option, default in check.options.items():
            if isinstance(default, int):
                spin = QtWidgets.QSpinBox(minimum=0, maximum=99)
            else:
                spin = QtWidgets.QDoubleSpinBox(minimum=0.0, maximum=1.0, decimals=4, singleStep=0.001)
            spin.setValue(values[option])
            form.addRow(option_label(option), spin)
            self.spins[option] = spin
        layout.addLayout(form)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        ok = QtWidgets.QPushButton("OK")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        cancel = QtWidgets.QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(ok)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

    def values(self):
        """``{option: value}``, each value of its default's type."""
        return {option: type(self.check.options[option])(spin.value()) for option, spin in self.spins.items()}


class QCResultsDialog(QtWidgets.QDialog):
    """QC results under a ``message``, with a ``go_label`` button (accepts)
    then Cancel at the bottom. Run it with ``exec()``."""

    def __init__(self, parent, title, message, found, go_label, on_pick):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(480, 320)
        layout = QtWidgets.QVBoxLayout(self)
        label = QtWidgets.QLabel(message)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.results = QCResults(on_pick, expand=True)
        self.results.show_results(found)
        layout.addWidget(self.results, 1)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        go = QtWidgets.QPushButton(go_label)
        go.clicked.connect(self.accept)
        cancel = QtWidgets.QPushButton("Cancel")
        cancel.setDefault(True)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(go)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
