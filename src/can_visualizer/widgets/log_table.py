"""
CAN Message Log Table Widget.

High-performance table view for streaming decoded CAN signals.
Designed to handle millions of rows efficiently using virtual scrolling.
"""

from typing import Optional
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, Signal, Slot
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTableView,
    QHeaderView,
    QLabel,
    QPushButton,
    QLineEdit,
)
from PySide6.QtGui import QColor, QFont

from ..core.models import DecodedSignal
from ..utils.logging_config import get_logger

logger = get_logger("log_table")


class SignalTableModel(QAbstractTableModel):
    """
    Custom table model for efficient signal display.
    
    Uses virtual scrolling - Qt only requests visible rows,
    so we can handle millions of signals without memory issues.
    """
    
    COLUMNS = [
        ("Timestamp", "timestamp"),
        ("Message", "message_name"),
        ("ID", "message_id"),
        ("Signal", "signal_name"),
        ("Raw", "raw_value"),
        ("Physical", "physical_value"),
        ("Unit", "unit"),
    ]
    
    # Maximum rows to keep in memory for live view
    MAX_ROWS = 500_000
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._signals: list[DecodedSignal] = []
        self._filter_text: str = ""
        self._filtered_indices: Optional[list[int]] = None
    
    def rowCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        if self._filtered_indices is not None:
            return len(self._filtered_indices)
        return len(self._signals)
    
    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.COLUMNS)
    
    def data(self, index: QModelIndex, role: int):
        if not index.isValid():
            return None
        
        # Get actual row index (handle filtering)
        if self._filtered_indices is not None:
            if index.row() >= len(self._filtered_indices):
                return None
            actual_row = self._filtered_indices[index.row()]
        else:
            actual_row = index.row()
        
        if actual_row >= len(self._signals):
            return None
        
        signal = self._signals[actual_row]
        col = index.column()
        
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:  # Timestamp
                return f"{signal.timestamp:.6f}"
            elif col == 1:  # Message
                return signal.message_name
            elif col == 2:  # ID
                return f"0x{signal.message_id:03X}"
            elif col == 3:  # Signal
                return signal.signal_name
            elif col == 4:  # Raw
                return str(signal.raw_value)
            elif col == 5:  # Physical
                return f"{signal.physical_value:.4g}"
            elif col == 6:  # Unit
                return signal.unit
        
        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (0, 2, 4, 5):  # Numeric columns
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        
        elif role == Qt.ItemDataRole.ForegroundRole:
            # Color code by message for easier reading
            msg_hash = hash(signal.message_name) % 12
            colors = [
                QColor("#2E86AB"), QColor("#A23B72"), QColor("#F18F01"),
                QColor("#C73E1D"), QColor("#3A506B"), QColor("#5BC0BE"),
                QColor("#6B2D5C"), QColor("#F0A202"), QColor("#0D3B66"),
                QColor("#7B2D26"), QColor("#2D6A4F"), QColor("#9B5DE5"),
            ]
            return colors[msg_hash]
        
        return None
    
    def headerData(self, section: int, orientation: Qt.Orientation, role: int):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        
        if orientation == Qt.Orientation.Horizontal:
            return self.COLUMNS[section][0]
        
        return str(section + 1)
    
    def add_signals(self, signals: list[DecodedSignal]) -> None:
        """
        Add new signals to the model.
        
        Handles memory management by trimming old entries
        when MAX_ROWS is exceeded.
        
        Optimized for streaming: defers filter until necessary.
        """
        if not signals:
            return
        
        # Check if we need to trim
        current_count = len(self._signals)
        new_count = len(signals)
        total = current_count + new_count
        
        if total > self.MAX_ROWS:
            # Trim oldest entries - use reset for efficiency
            trim_count = total - self.MAX_ROWS
            self.beginResetModel()
            if trim_count >= current_count:
                self._signals = list(signals[-self.MAX_ROWS:])
            else:
                self._signals = self._signals[trim_count:] + list(signals)
            # Only apply filter if active
            if self._filter_text:
                self._apply_filter()
            else:
                self._filtered_indices = None
            self.endResetModel()
        else:
            # Simple append - faster path
            self.beginResetModel()
            self._signals.extend(signals)
            # Only apply filter if active
            if self._filter_text:
                self._apply_filter()
            else:
                self._filtered_indices = None
            self.endResetModel()
    
    def clear(self) -> None:
        """Clear all signals."""
        self.beginResetModel()
        self._signals.clear()
        self._filtered_indices = None
        self.endResetModel()
    
    def set_filter(self, text: str) -> None:
        """Set filter text for signal/message names."""
        self.beginResetModel()
        self._filter_text = text.lower().strip()
        self._apply_filter()
        self.endResetModel()
    
    def _apply_filter(self) -> None:
        """Apply current filter to signals."""
        if not self._filter_text:
            self._filtered_indices = None
            return
        
        self._filtered_indices = [
            i for i, sig in enumerate(self._signals)
            if (self._filter_text in sig.message_name.lower() or
                self._filter_text in sig.signal_name.lower())
        ]
    
    def get_signal(self, row: int) -> Optional[DecodedSignal]:
        """Get signal at given row (accounting for filter)."""
        if self._filtered_indices is not None:
            if row >= len(self._filtered_indices):
                return None
            actual_row = self._filtered_indices[row]
        else:
            actual_row = row
        
        if actual_row >= len(self._signals):
            return None
        
        return self._signals[actual_row]
    
    @property
    def total_count(self) -> int:
        """Total signals (unfiltered)."""
        return len(self._signals)
    
    @property
    def filtered_count(self) -> int:
        """Visible signals (after filter)."""
        if self._filtered_indices is not None:
            return len(self._filtered_indices)
        return len(self._signals)


class LogTableWidget(QWidget):
    """
    Widget containing the signal log table with controls.
    
    Features:
    - High-performance virtual scrolling
    - Real-time streaming updates
    - Search/filter capability
    - Auto-scroll to latest
    """
    
    signal_selected = Signal(DecodedSignal)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._model = SignalTableModel(self)
        self._auto_scroll = True
        
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """Initialize UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        
        # Filter input
        self._filter_input = QLineEdit()
        self._filter_input.setPlaceholderText("🔍 Filter by message or signal...")
        self._filter_input.setClearButtonEnabled(True)
        self._filter_input.textChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self._filter_input, stretch=1)
        
        # Auto-scroll toggle
        self._auto_scroll_btn = QPushButton("📜 Auto-scroll")
        self._auto_scroll_btn.setCheckable(True)
        self._auto_scroll_btn.setChecked(True)
        self._auto_scroll_btn.clicked.connect(self._on_auto_scroll_toggled)
        toolbar.addWidget(self._auto_scroll_btn)
        
        # Clear button
        self._clear_btn = QPushButton("🗑️ Clear")
        self._clear_btn.clicked.connect(self._on_clear_clicked)
        toolbar.addWidget(self._clear_btn)
        
        layout.addLayout(toolbar)
        
        # Table view
        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        
        # Column sizing
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)  # Timestamp
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # Message
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # ID
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)  # Signal
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # Raw
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)  # Physical
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)  # Unit
        
        # Optimize for performance
        self._table.setVerticalScrollMode(QTableView.ScrollMode.ScrollPerPixel)
        self._table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self._table.verticalHeader().setDefaultSectionSize(22)
        
        self._table.clicked.connect(self._on_row_clicked)
        layout.addWidget(self._table)
        
        # Status bar
        self._status_label = QLabel("0 signals")
        self._status_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(self._status_label)
    
    @Slot(list)
    def add_signals(self, signals: list[DecodedSignal]) -> None:
        """Add new signals to the table (called from worker thread via signal)."""
        self._model.add_signals(signals)
        self._update_status()
        
        # Only scroll if auto-scroll enabled and table not being interacted with
        if self._auto_scroll and not self._table.underMouse():
            # Use scrollToBottom sparingly - it can be expensive
            scrollbar = self._table.verticalScrollBar()
            if scrollbar:
                scrollbar.setValue(scrollbar.maximum())
    
    def clear(self) -> None:
        """Clear all signals from the table."""
        self._model.clear()
        self._update_status()
    
    def _on_filter_changed(self, text: str) -> None:
        """Handle filter text changes."""
        self._model.set_filter(text)
        self._update_status()
    
    def _on_auto_scroll_toggled(self, checked: bool) -> None:
        """Toggle auto-scroll behavior."""
        self._auto_scroll = checked
    
    def _on_clear_clicked(self) -> None:
        """Handle clear button click."""
        self.clear()
    
    def _on_row_clicked(self, index: QModelIndex) -> None:
        """Handle row selection."""
        signal = self._model.get_signal(index.row())
        if signal:
            self.signal_selected.emit(signal)
    
    def _update_status(self) -> None:
        """Update status label."""
        total = self._model.total_count
        filtered = self._model.filtered_count
        
        if total == filtered:
            self._status_label.setText(f"{total:,} signals")
        else:
            self._status_label.setText(f"{filtered:,} / {total:,} signals")
    
    @property
    def signal_count(self) -> int:
        """Get total signal count."""
        return self._model.total_count

