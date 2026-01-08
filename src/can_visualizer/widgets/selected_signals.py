"""
Selected Signals Panel Widget.

Displays currently selected signals with options to remove them
and provides a clear overview of what's being plotted/analyzed.
"""

from typing import Optional
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QLabel,
    QMenu,
    QAbstractItemView,
    QColorDialog,
)
from PySide6.QtGui import QColor, QAction

from ..core.models import SignalDefinition
from ..utils.logging_config import get_logger

logger = get_logger("selected_signals")


class SelectedSignalsWidget(QWidget):
    """
    Panel showing currently selected signals.

    Features:
    - List of selected signals with color indicators
    - Remove individual signals or clear all
    - Signal metadata on hover
    - Context menu for quick actions

    Emits:
    - signal_removed: When a signal is removed from selection
    - signals_cleared: When all signals are cleared
    - signal_double_clicked: When a signal is double-clicked (for focus)
    """

    signal_removed = Signal(str)  # full_name of removed signal
    signals_cleared = Signal()
    signal_double_clicked = Signal(str)  # full_name for focusing in plot
    selection_changed = Signal(list)  # List of full_names
    color_changed = Signal(str, str)  # (full_name, hex_color) - empty string for reset

    # Same color palette as plot for consistency
    COLORS = [
        "#E63946",
        "#2A9D8F",
        "#E9C46A",
        "#264653",
        "#F4A261",
        "#9B5DE5",
        "#00BBF9",
        "#00F5D4",
        "#F15BB5",
        "#FEE440",
        "#9EF01A",
        "#4CC9F0",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)

        self._selected_signals: list[str] = []  # List of full_names
        self._signal_defs: dict[str, SignalDefinition] = {}
        self._custom_colors: dict[str, str] = {}  # signal_name -> hex color

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Initialize UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Header with count and actions
        header = QHBoxLayout()
        header.setSpacing(4)

        self._title_label = QLabel("Selected Signals")
        self._title_label.setStyleSheet("font-weight: bold;")
        header.addWidget(self._title_label)

        header.addStretch()

        self._count_label = QLabel("0 signals")
        self._count_label.setStyleSheet("color: #888; font-size: 11px;")
        header.addWidget(self._count_label)

        layout.addLayout(header)

        # Signal list
        self._list_widget = QListWidget()
        self._list_widget.setAlternatingRowColors(True)
        self._list_widget.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list_widget.customContextMenuRequested.connect(self._show_context_menu)
        self._list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._list_widget.setStyleSheet("""
            QListWidget {
                background: #252526;
                border: 1px solid #3D3D3D;
                border-radius: 4px;
            }
            QListWidget::item {
                padding: 6px 8px;
                border-bottom: 1px solid #3D3D3D;
            }
            QListWidget::item:selected {
                background: #0078D4;
            }
            QListWidget::item:hover {
                background: #2D2D2D;
            }
        """)
        layout.addWidget(self._list_widget)

        # Action buttons
        buttons = QHBoxLayout()
        buttons.setSpacing(4)

        self._remove_btn = QPushButton("Remove Selected")
        self._remove_btn.clicked.connect(self._on_remove_selected)
        self._remove_btn.setEnabled(False)
        buttons.addWidget(self._remove_btn)

        self._clear_btn = QPushButton("Clear All")
        self._clear_btn.clicked.connect(self._on_clear_all)
        self._clear_btn.setEnabled(False)
        buttons.addWidget(self._clear_btn)

        layout.addLayout(buttons)

        # Connect list selection change
        self._list_widget.itemSelectionChanged.connect(self._on_list_selection_changed)

    def set_signal_definitions(self, definitions: dict[str, SignalDefinition]) -> None:
        """
        Set signal definitions for metadata display.

        Args:
            definitions: Dict mapping full signal name to definition
        """
        self._signal_defs = definitions

    def set_selected_signals(self, full_names: list[str]) -> None:
        """
        Set the list of selected signals.

        Args:
            full_names: List of "MessageName.SignalName" strings
        """
        self._selected_signals = list(full_names)
        self._rebuild_list()

    def add_signal(self, full_name: str) -> None:
        """Add a signal to the selection."""
        if full_name not in self._selected_signals:
            self._selected_signals.append(full_name)
            self._rebuild_list()
            self.selection_changed.emit(self._selected_signals.copy())

    def remove_signal(self, full_name: str) -> None:
        """Remove a signal from the selection."""
        if full_name in self._selected_signals:
            self._selected_signals.remove(full_name)
            self._rebuild_list()
            self.signal_removed.emit(full_name)
            self.selection_changed.emit(self._selected_signals.copy())

    def clear_signals(self) -> None:
        """Clear all selected signals."""
        self._selected_signals.clear()
        self._rebuild_list()
        self.signals_cleared.emit()
        self.selection_changed.emit([])

    def _rebuild_list(self) -> None:
        """Rebuild the list widget from current selection."""
        self._list_widget.clear()

        for i, full_name in enumerate(self._selected_signals):
            item = QListWidgetItem()

            # Get signal definition for metadata
            sig_def = self._signal_defs.get(full_name)

            # Parse message and signal name
            parts = full_name.split(".", 1)
            msg_name = parts[0] if len(parts) > 0 else ""
            sig_name = parts[1] if len(parts) > 1 else full_name

            # Get color for this signal (custom or default from palette)
            color = (
                self._custom_colors.get(full_name) or self.COLORS[i % len(self.COLORS)]
            )

            # Create display text
            if sig_def:
                display_text = f"● {sig_name}"
                if sig_def.unit:
                    display_text += f" [{sig_def.unit}]"
                display_text += f"\n   {msg_name}"
            else:
                display_text = f"● {sig_name}\n   {msg_name}"

            item.setText(display_text)
            item.setData(Qt.ItemDataRole.UserRole, full_name)

            # Set color indicator
            item.setForeground(QColor(color))

            # Tooltip with full details
            tooltip = f"<b>{sig_name}</b><br>"
            tooltip += f"Message: {msg_name}<br>"
            if sig_def:
                tooltip += f"Unit: {sig_def.unit or 'none'}<br>"
                tooltip += f"Factor: {sig_def.factor}, Offset: {sig_def.offset}<br>"
                if sig_def.minimum is not None and sig_def.maximum is not None:
                    tooltip += f"Range: [{sig_def.minimum}, {sig_def.maximum}]<br>"
                if sig_def.is_enum and sig_def.choices:
                    tooltip += "<br><b>Enum values:</b><br>"
                    for val, name in list(sig_def.choices.items())[:5]:
                        tooltip += f"  {val}: {name}<br>"
                    if len(sig_def.choices) > 5:
                        tooltip += f"  ... and {len(sig_def.choices) - 5} more"
            tooltip += "<br><i>Double-click to focus in plot</i>"
            item.setToolTip(tooltip)

            self._list_widget.addItem(item)

        # Update UI state
        count = len(self._selected_signals)
        self._count_label.setText(f"{count} signal{'s' if count != 1 else ''}")
        self._clear_btn.setEnabled(count > 0)

    def _on_list_selection_changed(self) -> None:
        """Handle list selection changes."""
        has_selection = len(self._list_widget.selectedItems()) > 0
        self._remove_btn.setEnabled(has_selection)

    def _on_remove_selected(self) -> None:
        """Remove selected items from the list."""
        selected_items = self._list_widget.selectedItems()

        for item in selected_items:
            full_name = item.data(Qt.ItemDataRole.UserRole)
            if full_name in self._selected_signals:
                self._selected_signals.remove(full_name)
                self.signal_removed.emit(full_name)

        self._rebuild_list()
        self.selection_changed.emit(self._selected_signals.copy())

    def _on_clear_all(self) -> None:
        """Clear all signals."""
        self.clear_signals()

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        """Handle double-click on an item."""
        full_name = item.data(Qt.ItemDataRole.UserRole)
        if full_name:
            self.signal_double_clicked.emit(full_name)

    def _show_context_menu(self, position) -> None:
        """Show context menu for signal items."""
        item = self._list_widget.itemAt(position)

        menu = QMenu(self)

        if item:
            full_name = item.data(Qt.ItemDataRole.UserRole)
            sig_name = full_name.split(".")[-1] if full_name else "Signal"

            # Set Color action
            set_color_action = QAction(f"🎨 Set Color...", self)
            set_color_action.triggered.connect(lambda: self._on_set_color(full_name))
            menu.addAction(set_color_action)

            # Reset Color action (only if custom color is set)
            if full_name in self._custom_colors:
                reset_color_action = QAction(f"↩️ Reset Color", self)
                reset_color_action.triggered.connect(
                    lambda: self._on_reset_color(full_name)
                )
                menu.addAction(reset_color_action)

            menu.addSeparator()

            # Focus action
            focus_action = QAction(f"Focus '{sig_name}' in Plot", self)
            focus_action.triggered.connect(
                lambda: self.signal_double_clicked.emit(full_name)
            )
            menu.addAction(focus_action)

            menu.addSeparator()

            # Remove action
            remove_action = QAction(f"Remove '{sig_name}'", self)
            remove_action.triggered.connect(lambda: self.remove_signal(full_name))
            menu.addAction(remove_action)

        # Remove selected (if multiple selected)
        if len(self._list_widget.selectedItems()) > 1:
            remove_selected_action = QAction(
                f"Remove {len(self._list_widget.selectedItems())} Selected", self
            )
            remove_selected_action.triggered.connect(self._on_remove_selected)
            menu.addAction(remove_selected_action)

        menu.addSeparator()

        # Clear all
        clear_action = QAction("Clear All Signals", self)
        clear_action.triggered.connect(self._on_clear_all)
        clear_action.setEnabled(len(self._selected_signals) > 0)
        menu.addAction(clear_action)

        menu.exec(self._list_widget.mapToGlobal(position))

    def get_selected_signals(self) -> list[str]:
        """Get list of currently selected signal full names."""
        return self._selected_signals.copy()

    @property
    def signal_count(self) -> int:
        """Get number of selected signals."""
        return len(self._selected_signals)

    def _on_set_color(self, full_name: str) -> None:
        """Open color dialog to set custom signal color."""
        sig_name = full_name.split(".")[-1]

        # Get current color as initial color
        if full_name in self._custom_colors:
            initial_color = QColor(self._custom_colors[full_name])
        else:
            # Use default color from palette
            signal_idx = (
                self._selected_signals.index(full_name)
                if full_name in self._selected_signals
                else 0
            )
            initial_color = QColor(self.COLORS[signal_idx % len(self.COLORS)])

        # Open color dialog
        color = QColorDialog.getColor(
            initial_color, self, f"Select Color for {sig_name}"
        )

        if color.isValid():
            # Store custom color
            self._custom_colors[full_name] = color.name()
            # Rebuild list to show new color
            self._rebuild_list()
            # Emit signal so plot can update
            self.color_changed.emit(full_name, color.name())
            logger.debug(f"Set custom color for {full_name}: {color.name()}")

    def _on_reset_color(self, full_name: str) -> None:
        """Reset signal to default palette color."""
        if full_name in self._custom_colors:
            del self._custom_colors[full_name]
            # Rebuild list to show default color
            self._rebuild_list()
            # Emit signal with empty string to indicate reset
            self.color_changed.emit(full_name, "")
            logger.debug(f"Reset color for {full_name} to default")

    def set_custom_color(self, full_name: str, color: str) -> None:
        """Set custom color for a signal (called externally)."""
        if color:
            self._custom_colors[full_name] = color
        elif full_name in self._custom_colors:
            del self._custom_colors[full_name]
        self._rebuild_list()

    def get_custom_colors(self) -> dict[str, str]:
        """Get all custom color assignments."""
        return self._custom_colors.copy()
