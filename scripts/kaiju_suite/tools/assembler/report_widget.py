"""Build report window, shown after Run All: each step's status, time taken
and a button to open its log. The data comes from :mod:`.report`."""

from PySide6 import QtCore, QtGui, QtWidgets

from kaiju_suite.tools.assembler import report

STATUS_COLORS = {
    report.OK: QtGui.QColor(95, 190, 95),
    report.WARNING: QtGui.QColor(230, 200, 60),
    report.ERROR: QtGui.QColor(225, 85, 85),
    report.SKIPPED: QtGui.QColor(115, 115, 115),
}
_HEADERS = ("Step", "Status", "Time", "")


class ReportDialog(QtWidgets.QDialog):
    """Non-modal table of ``results`` (:class:`.report.StepResult`).
    ``open_log(path)`` is called by a step's Log button (or double-click)."""

    def __init__(self, parent, title, results, open_log):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(title)
        self.resize(560, 360)
        self._results = results
        self._open_log = open_log
        layout = QtWidgets.QVBoxLayout(self)

        table = QtWidgets.QTableWidget(len(results), len(_HEADERS))
        table.setHorizontalHeaderLabels(_HEADERS)
        table.verticalHeader().hide()
        table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        for column in range(1, len(_HEADERS)):
            header.setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        right = QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
        for row, result in enumerate(results):
            name = QtWidgets.QTableWidgetItem(result.name)
            name.setToolTip(result.path)
            status = QtWidgets.QTableWidgetItem(result.status)
            status.setForeground(STATUS_COLORS[result.status])
            took = QtWidgets.QTableWidgetItem(report.format_seconds(result.seconds))
            took.setTextAlignment(right)
            for column, item in enumerate((name, status, took)):
                table.setItem(row, column, item)
            button = QtWidgets.QPushButton("Log")
            button.setEnabled(result.has_log)
            button.clicked.connect(lambda _=False, p=result.path: self._open_log(p))
            table.setCellWidget(row, 3, button)
        table.cellDoubleClicked.connect(self._on_double_click)
        layout.addWidget(table)

        totals = f"{report.count_line(results)}    Total: {report.format_seconds(report.total_seconds(results))}"
        layout.addWidget(QtWidgets.QLabel(totals))

        buttons = QtWidgets.QHBoxLayout()
        copy = QtWidgets.QPushButton("Copy as Text")
        copy.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(report.summary(results)))
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.close)
        buttons.addWidget(copy)
        buttons.addStretch()
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _on_double_click(self, row, _column):
        result = self._results[row]
        if result.has_log:
            self._open_log(result.path)
