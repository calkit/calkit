"""A GUI to help users manage their system.

This app helps install and track system-wide dependencies and open projects
in their editor of choice.
"""

import sys

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QInputDialog,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class ChecklistApp(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Simple Checklist")
        self.layout = QVBoxLayout(self)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_widget = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_widget)
        self.scroll_area.setWidget(self.scroll_widget)
        self.layout.addWidget(self.scroll_area)

        self.add_button = QPushButton("Add Item")
        self.add_button.clicked.connect(self.add_item)
        self.layout.addWidget(self.add_button)

        self.clear_button = QPushButton("Clear Completed")
        self.clear_button.clicked.connect(self.clear_completed)
        self.layout.addWidget(self.clear_button)

        self.items = []

    def add_item(self):
        item_text, ok = QInputDialog.getText(
            self, "Add Item", "Enter item text:"
        )
        if ok and item_text:
            checkbox = QCheckBox(item_text)
            self.scroll_layout.addWidget(checkbox)
            self.items.append(checkbox)

    def clear_completed(self):
        items_to_remove = []
        for item in self.items:
            if item.isChecked():
                self.scroll_layout.removeWidget(item)
                item.deleteLater()
                items_to_remove.append(item)

        for item in items_to_remove:
            self.items.remove(item)


def run():
    app = QApplication(sys.argv)
    window = ChecklistApp()
    window.show()
    sys.exit(app.exec())
