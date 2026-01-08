"""
Signal Selector Dialog.

Modal dialog for selecting signals to display in the state diagram.
Features searchable list with multi-selection support.
"""

from typing import Optional
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QLabel,
    QDialogButtonBox,
    QAbstractItemView,
)
from PySide6.QtGui import QColor

from ..core.models import SignalDefinition
from ..utils.logging_config import get_logger

logger = get_logger("signal_selector")


class SignalSelectorDialog(QDialog):
    """
    Modal dialog for selecting signals.

    Features:
    - Searchable signal list
    - Multi-selection with checkboxes
    - Signal metadata display
    - Filters by message and signal name
    """

    def __init__(
        self,
        signal_definitions: dict[str, SignalDefinition],
        already_selected: Optional[list[str]] = None,
        parent=None,
    ):
        """
        Initialize the signal selector dialog.

        Args:
            signal_definitions: Dict mapping full signal name to definition
            already_selected: List of already selected signal full names
            parent: Parent widget
        """
        super().__init__(parent)

        self._signal_defs = signal_definitions
        self._already_selected = set(already_selected or [])
        self._selected_signals: list[str] = []

        self._setup_ui()
        self._populate_list()

    def _setup_ui(self) -> None:
        """Initialize UI components."""
        self.setWindowTitle("Select Signals for State Diagram")
        self.setMinimumSize(500, 600)
        self.setModal(True)

        # Dark theme
        self.setStyleSheet("""
            QDialog {
                background: #1E1E1E;
                color: #E0E0E0;
            }
            QLineEdit {
                background: #2D2D2D;
                border: 1px solid #3D3D3D;
                border-radius: 4px;
                padding: 8px;
                color: #E0E0E0;
            }
            QLineEdit:focus {
                border-color: #0078D4;
            }
            QListWidget {
                background: #252526;
                border: 1px solid #3D3D3D;
                border-radius: 4px;
                color: #E0E0E0;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #3D3D3D;
            }
            QListWidget::item:hover {
                background: #2D2D2D;
            }
            QListWidget::item:selected {
                background: #0078D4;
            }
            QPushButton {
                background: #0078D4;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                color: white;
                font-weight: 500;
            }
            QPushButton:hover {
                background: #1084D9;
            }
            QPushButton:pressed {
                background: #006CC1;
            }
            QPushButton:disabled {
                background: #3D3D3D;
                color: #666;
            }
            QLabel {
                color: #E0E0E0;
            }
            QCheckBox {
                color: #E0E0E0;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # Header
        header = QLabel("Select signals to display in the state diagram:")
        header.setStyleSheet("font-size: 13px; margin-bottom: 4px;")
        layout.addWidget(header)

        # Search bar
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("🔍 Search signals by name or message...")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.textChanged.connect(self._on_search_changed)
        layout.addWidget(self._search_input)

        # Signal list
        self._list_widget = QListWidget()
        self._list_widget.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._list_widget.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._list_widget)

        # Selection info
        info_layout = QHBoxLayout()
        self._selection_label = QLabel("0 signals selected")
        self._selection_label.setStyleSheet("color: #888; font-size: 11px;")
        info_layout.addWidget(self._selection_label)

        info_layout.addStretch()

        # Select all / Clear buttons
        self._select_all_btn = QPushButton("Select All Visible")
        self._select_all_btn.setStyleSheet("background: #3D3D3D;")
        self._select_all_btn.clicked.connect(self._on_select_all)
        info_layout.addWidget(self._select_all_btn)

        self._clear_btn = QPushButton("Clear Selection")
        self._clear_btn.setStyleSheet("background: #3D3D3D;")
        self._clear_btn.clicked.connect(self._on_clear_selection)
        info_layout.addWidget(self._clear_btn)

        layout.addLayout(info_layout)

        # Dialog buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        # Style the buttons
        ok_btn = button_box.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setText("Add Selected")

        layout.addWidget(button_box)

    def _populate_list(self) -> None:
        """Populate the signal list."""
        self._list_widget.clear()

        # Sort signals by message then signal name
        sorted_signals = sorted(
            self._signal_defs.items(), key=lambda x: (x[1].message_name, x[1].name)
        )

        for full_name, sig_def in sorted_signals:
            item = QListWidgetItem()

            # Create display text
            display_text = f"{sig_def.name}"
            if sig_def.unit:
                display_text += f" [{sig_def.unit}]"
            display_text += f"  —  {sig_def.message_name}"

            # Add enum indicator
            if sig_def.is_enum:
                display_text += " (enum)"

            item.setText(display_text)
            item.setData(Qt.ItemDataRole.UserRole, full_name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)

            # Check if already selected
            if full_name in self._already_selected:
                item.setCheckState(Qt.CheckState.Checked)
            else:
                item.setCheckState(Qt.CheckState.Unchecked)

            # Tooltip with details
            tooltip = f"<b>{sig_def.name}</b><br>"
            tooltip += (
                f"Message: {sig_def.message_name} (0x{sig_def.message_id:03X})<br>"
            )
            tooltip += f"Unit: {sig_def.unit or 'none'}<br>"

            if sig_def.is_enum and sig_def.choices:
                tooltip += "<br><b>Values:</b><br>"
                for val, name in list(sig_def.choices.items())[:8]:
                    tooltip += f"  {val}: {name}<br>"
                if len(sig_def.choices) > 8:
                    tooltip += f"  ... and {len(sig_def.choices) - 8} more"

            item.setToolTip(tooltip)

            # Highlight enum signals (better for state diagrams)
            if sig_def.is_enum:
                item.setForeground(QColor("#4ECDC4"))

            self._list_widget.addItem(item)

        self._update_selection_count()

    def _on_search_changed(self, text: str) -> None:
        """Filter list based on search text."""
        search_text = text.lower().strip()

        for i in range(self._list_widget.count()):
            item = self._list_widget.item(i)
            full_name = item.data(Qt.ItemDataRole.UserRole)

            if not search_text:
                item.setHidden(False)
            else:
                # Search in signal name and message name
                sig_def = self._signal_defs.get(full_name)
                if sig_def:
                    matches = (
                        search_text in sig_def.name.lower()
                        or search_text in sig_def.message_name.lower()
                        or search_text in full_name.lower()
                    )
                    item.setHidden(not matches)
                else:
                    item.setHidden(True)

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        """Handle checkbox state changes."""
        self._update_selection_count()

    def _on_select_all(self) -> None:
        """Select all visible items."""
        self._list_widget.blockSignals(True)

        for i in range(self._list_widget.count()):
            item = self._list_widget.item(i)
            if not item.isHidden():
                item.setCheckState(Qt.CheckState.Checked)

        self._list_widget.blockSignals(False)
        self._update_selection_count()

    def _on_clear_selection(self) -> None:
        """Clear all selections."""
        self._list_widget.blockSignals(True)

        for i in range(self._list_widget.count()):
            item = self._list_widget.item(i)
            item.setCheckState(Qt.CheckState.Unchecked)

        self._list_widget.blockSignals(False)
        self._update_selection_count()

    def _update_selection_count(self) -> None:
        """Update the selection count label."""
        count = 0
        for i in range(self._list_widget.count()):
            item = self._list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                count += 1

        self._selection_label.setText(
            f"{count} signal{'s' if count != 1 else ''} selected"
        )

    def get_selected_signals(self) -> list[str]:
        """
        Get list of selected signal full names.

        Returns:
            List of selected "MessageName.SignalName" strings
        """
        selected = []

        for i in range(self._list_widget.count()):
            item = self._list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                full_name = item.data(Qt.ItemDataRole.UserRole)
                if full_name:
                    selected.append(full_name)

        return selected

    @staticmethod
    def select_signals(
        signal_definitions: dict[str, SignalDefinition],
        already_selected: Optional[list[str]] = None,
        parent=None,
    ) -> Optional[list[str]]:
        """
        Static method to show dialog and return selected signals.

        Args:
            signal_definitions: Available signal definitions
            already_selected: Already selected signals
            parent: Parent widget

        Returns:
            List of selected signal full names, or None if cancelled
        """
        dialog = SignalSelectorDialog(signal_definitions, already_selected, parent)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.get_selected_signals()

        return None
