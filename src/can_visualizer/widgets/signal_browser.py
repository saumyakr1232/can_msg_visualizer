"""
DBC Signal Browser Widget.

Provides a hierarchical tree view of CAN messages and signals
from the DBC file with search filtering and multi-selection.
"""

from typing import Optional, Set
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QHeaderView,
)
from PySide6.QtGui import QIcon, QFont

from ..core.models import MessageDefinition, SignalDefinition
from ..utils.logging_config import get_logger

logger = get_logger("signal_browser")


class SignalBrowserWidget(QWidget):
    """
    Hierarchical browser for DBC messages and signals.
    
    Features:
    - Tree view: Message -> Signals hierarchy
    - Search filtering without losing selection state
    - Multi-selection via checkboxes
    - Signal metadata tooltips
    
    Emits:
    - selection_changed: When checked signals change
    """
    
    selection_changed = Signal(list)  # List of (message_name, signal_name) tuples
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._messages: dict[int, MessageDefinition] = {}
        self._checked_signals: Set[str] = set()  # "MessageName.SignalName" format
        self._message_items: dict[int, QTreeWidgetItem] = {}
        self._signal_items: dict[str, QTreeWidgetItem] = {}
        
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """Initialize UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        # Search bar
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("🔍 Search messages or signals...")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.textChanged.connect(self._on_search_changed)
        layout.addWidget(self._search_input)
        
        # Tree widget
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Name", "ID / Bits", "Unit"])
        self._tree.setColumnCount(3)
        self._tree.setAlternatingRowColors(True)
        self._tree.setAnimated(True)
        self._tree.setIndentation(20)
        
        # Column sizing
        header = self._tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        
        self._tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._tree)
    
    def load_dbc(self, messages: dict[int, MessageDefinition]) -> None:
        """
        Load message definitions from DBC.
        
        Args:
            messages: Dict of message_id -> MessageDefinition
        """
        logger.info(f"Loading {len(messages)} messages into browser")
        
        self._messages = messages
        self._checked_signals.clear()
        self._message_items.clear()
        self._signal_items.clear()
        
        self._tree.blockSignals(True)
        self._tree.clear()
        
        # Sort messages by name for better UX
        sorted_messages = sorted(messages.values(), key=lambda m: m.name)
        
        for msg in sorted_messages:
            msg_item = self._create_message_item(msg)
            self._tree.addTopLevelItem(msg_item)
            self._message_items[msg.message_id] = msg_item
            
            # Add signals
            for sig in sorted(msg.signals, key=lambda s: s.name):
                sig_item = self._create_signal_item(sig)
                msg_item.addChild(sig_item)
                self._signal_items[sig.full_name] = sig_item
        
        self._tree.blockSignals(False)
        
        logger.info(f"Browser loaded: {len(self._signal_items)} signals")
    
    def _create_message_item(self, msg: MessageDefinition) -> QTreeWidgetItem:
        """Create tree item for a CAN message."""
        item = QTreeWidgetItem()
        item.setText(0, msg.name)
        item.setText(1, msg.hex_id)
        item.setData(0, Qt.ItemDataRole.UserRole, ("message", msg.message_id))
        
        # Bold font for messages
        font = QFont()
        font.setBold(True)
        item.setFont(0, font)
        
        # Tooltip with details
        tooltip = f"<b>{msg.name}</b><br>"
        tooltip += f"ID: {msg.hex_id}<br>"
        tooltip += f"DLC: {msg.length} bytes<br>"
        tooltip += f"Signals: {len(msg.signals)}"
        if msg.comment:
            tooltip += f"<br><br>{msg.comment}"
        item.setToolTip(0, tooltip)
        
        return item
    
    def _create_signal_item(self, sig: SignalDefinition) -> QTreeWidgetItem:
        """Create tree item for a CAN signal."""
        item = QTreeWidgetItem()
        item.setText(0, sig.name)
        item.setText(1, f"{sig.start_bit}:{sig.length}")
        item.setText(2, sig.unit)
        
        # Enable checkbox
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, Qt.CheckState.Unchecked)
        
        # Store full signal path for identification
        full_name = f"{sig.message_name}.{sig.name}"
        item.setData(0, Qt.ItemDataRole.UserRole, ("signal", full_name))
        
        # Different style for enum signals
        if sig.is_enum:
            item.setForeground(0, Qt.GlobalColor.darkMagenta)
        
        # Detailed tooltip
        tooltip = f"<b>{sig.name}</b><br>"
        tooltip += f"Message: {sig.message_name}<br>"
        tooltip += f"Start bit: {sig.start_bit}, Length: {sig.length}<br>"
        tooltip += f"Byte order: {sig.byte_order}<br>"
        tooltip += f"Factor: {sig.factor}, Offset: {sig.offset}<br>"
        
        if sig.minimum is not None and sig.maximum is not None:
            tooltip += f"Range: [{sig.minimum}, {sig.maximum}] {sig.unit}<br>"
        
        if sig.is_enum and sig.choices:
            tooltip += "<br><b>Values:</b><br>"
            for val, name in sorted(sig.choices.items())[:10]:
                tooltip += f"  {val}: {name}<br>"
            if len(sig.choices) > 10:
                tooltip += f"  ... and {len(sig.choices) - 10} more"
        
        if sig.comment:
            tooltip += f"<br>{sig.comment}"
        
        item.setToolTip(0, tooltip)
        
        return item
    
    def _on_search_changed(self, text: str) -> None:
        """
        Filter tree based on search text.
        
        Preserves checked state during filtering.
        """
        search_text = text.lower().strip()
        
        self._tree.blockSignals(True)
        
        for msg_id, msg_item in self._message_items.items():
            msg_def = self._messages.get(msg_id)
            if not msg_def:
                continue
            
            # Check if message matches
            msg_matches = (
                not search_text or
                search_text in msg_def.name.lower() or
                search_text in msg_def.hex_id.lower()
            )
            
            # Track if any child signal matches
            any_signal_matches = False
            
            for i in range(msg_item.childCount()):
                sig_item = msg_item.child(i)
                item_data = sig_item.data(0, Qt.ItemDataRole.UserRole)
                
                if item_data and item_data[0] == "signal":
                    sig_name = item_data[1].split(".")[-1]
                    sig_matches = not search_text or search_text in sig_name.lower()
                    
                    sig_item.setHidden(not sig_matches and not msg_matches)
                    
                    if sig_matches:
                        any_signal_matches = True
            
            # Show message if it matches or any signals match
            msg_item.setHidden(not msg_matches and not any_signal_matches)
            
            # Expand matching messages
            if (msg_matches or any_signal_matches) and search_text:
                msg_item.setExpanded(True)
        
        self._tree.blockSignals(False)
    
    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        """Handle checkbox state changes."""
        if column != 0:
            return
        
        item_data = item.data(0, Qt.ItemDataRole.UserRole)
        if not item_data or item_data[0] != "signal":
            return
        
        full_name = item_data[1]
        is_checked = item.checkState(0) == Qt.CheckState.Checked
        
        if is_checked:
            self._checked_signals.add(full_name)
        else:
            self._checked_signals.discard(full_name)
        
        # Emit selection change
        selected = [
            tuple(name.split(".", 1)) for name in sorted(self._checked_signals)
        ]
        self.selection_changed.emit(selected)
        
        logger.debug(f"Signal selection changed: {len(self._checked_signals)} selected")
    
    def get_selected_signals(self) -> list[tuple[str, str]]:
        """
        Get list of currently selected signals.
        
        Returns:
            List of (message_name, signal_name) tuples
        """
        return [
            tuple(name.split(".", 1)) for name in sorted(self._checked_signals)
        ]
    
    def get_selected_signal_names(self) -> list[str]:
        """Get list of selected signal names (without message prefix)."""
        return [name.split(".")[-1] for name in sorted(self._checked_signals)]
    
    def get_selected_full_names(self) -> list[str]:
        """Get list of selected signals as full names (Message.Signal)."""
        return sorted(self._checked_signals)
    
    def clear_selection(self) -> None:
        """Uncheck all signals."""
        self._tree.blockSignals(True)
        
        for full_name in list(self._checked_signals):
            if full_name in self._signal_items:
                self._signal_items[full_name].setCheckState(0, Qt.CheckState.Unchecked)
        
        self._checked_signals.clear()
        self._tree.blockSignals(False)
        
        self.selection_changed.emit([])
    
    def select_signals(self, full_names: list[str]) -> None:
        """
        Programmatically select signals by full name.
        
        Args:
            full_names: List of "MessageName.SignalName" strings
        """
        self._tree.blockSignals(True)
        
        for full_name in full_names:
            if full_name in self._signal_items:
                self._signal_items[full_name].setCheckState(0, Qt.CheckState.Checked)
                self._checked_signals.add(full_name)
        
        self._tree.blockSignals(False)
        
        selected = [
            tuple(name.split(".", 1)) for name in sorted(self._checked_signals)
        ]
        self.selection_changed.emit(selected)
    
    def expand_all(self) -> None:
        """Expand all message nodes."""
        self._tree.expandAll()
    
    def collapse_all(self) -> None:
        """Collapse all message nodes."""
        self._tree.collapseAll()
    
    @property
    def signal_count(self) -> int:
        """Total number of signals in DBC."""
        return len(self._signal_items)
    
    @property
    def message_count(self) -> int:
        """Total number of messages in DBC."""
        return len(self._message_items)

