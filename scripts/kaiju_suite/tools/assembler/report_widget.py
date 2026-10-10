"""Build report window, shown after Run '<folder>': each step's status and
time taken; its "..." button (or a double-click) opens its log. The data
comes from :mod:`.report`."""

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
    ``open_log(path)`` is called by a step's "..." button (or double-click)."""

    def __init__(self, parent, title, results, open_log):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(title)
        self._results = results
        self._open_log = open_log
        layout = QtWidgets.QVBoxLayout(self)

        table = QtWidgets.QTableWidget(len(results), len(_HEADERS))
        table.setHorizontalHeaderLabels(_HEADERS)
        table.verticalHeader().hide()
        table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        header = table.horizontalHeader()
        # Step takes whatever width is left, so the table fills the window;
        # the window opens just wide enough for the columns (below).
        header.setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setStretchLastSection(False)
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
            button = QtWidgets.QToolButton()
            button.setText("...")
            button.setToolTip("Show Log")
            button.setFixedWidth(button.fontMetrics().horizontalAdvance("...") + 16)
            button.setEnabled(result.has_log)
            button.clicked.connect(lambda _=False, p=result.path: self._open_log(p))
            table.setCellWidget(row, 3, button)
        table.cellDoubleClicked.connect(self._on_double_click)
        layout.addWidget(table)

        totals = f"{report.count_line(results)}    Total: {report.format_seconds(report.total_seconds(results))}"
        totals = QtWidgets.QLabel(totals)
        totals.setWordWrap(True)  # so a long line doesn't widen the window
        layout.addWidget(totals)

        # Fit the window to the columns (plus room for a scroll bar).
        width = sum(max(table.sizeHintForColumn(c), header.sectionSizeHint(c)) for c in range(len(_HEADERS)))
        width += table.verticalScrollBar().sizeHint().width() + 2 * table.frameWidth()
        margins = layout.contentsMargins()
        self.resize(max(width + margins.left() + margins.right(), 260), 360)

    def _on_double_click(self, row, _column):
        result = self._results[row]
        if result.has_log:
            self._open_log(result.path)
