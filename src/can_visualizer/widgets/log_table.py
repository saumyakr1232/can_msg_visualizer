"""
CAN Message Log Table Widget.

High-performance table view for streaming decoded CAN signals.
Designed to handle millions of rows efficiently using:
- Infinite scroll pagination (load 1000 signals at a time)
- Lazy UI updates (buffer signals, update on timer/scroll)
- Virtual scrolling (Qt only requests visible rows)
"""

from typing import Optional
from collections import deque
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, Signal, Slot, QTimer
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTableView,
    QHeaderView,
    QLabel,
    QPushButton,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QFrame,
)
from PySide6.QtGui import QColor

from ..core.models import DecodedSignal
from ..utils.logging_config import get_logger

logger = get_logger("log_table")


class SignalTableModel(QAbstractTableModel):
    """
    Custom table model with infinite scroll pagination.

    Architecture:
    - _all_signals: Backing buffer holding ALL received signals
    - _signals: Loaded subset for display (paginated, 1000 at a time)
    - User scrolls to bottom -> load_more() adds next page

    This reduces UI memory pressure by only keeping loaded pages in the
    Qt model while maintaining full data in the backing buffer.
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

    # Pagination settings
    PAGE_SIZE = 1000  # Signals per page for infinite scroll
    MAX_BUFFER_SIZE = 500_000  # Max signals in backing buffer

    # Signal emitted when more data is available to load
    more_available = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # Backing buffer - holds ALL signals
        self._all_signals: list[DecodedSignal] = []
        # Loaded signals - paginated subset for display
        self._signals: list[DecodedSignal] = []
        # Pagination state
        self._loaded_count = 0

        # Filtering
        self._filter_text: str = ""
        self._signal_filter: set[str] = set()
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
                QColor("#2E86AB"),
                QColor("#A23B72"),
                QColor("#F18F01"),
                QColor("#C73E1D"),
                QColor("#3A506B"),
                QColor("#5BC0BE"),
                QColor("#6B2D5C"),
                QColor("#F0A202"),
                QColor("#0D3B66"),
                QColor("#7B2D26"),
                QColor("#2D6A4F"),
                QColor("#9B5DE5"),
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
        Add new signals to the backing buffer.

        Signals are added to _all_signals buffer. If this is the first
        batch, automatically loads the first page into display.
        """
        if not signals:
            return

        # Add to backing buffer
        self._all_signals.extend(signals)

        # Trim backing buffer if too large
        if len(self._all_signals) > self.MAX_BUFFER_SIZE:
            trim_count = len(self._all_signals) - self.MAX_BUFFER_SIZE
            self._all_signals = self._all_signals[trim_count:]
            # Adjust loaded count if we trimmed loaded signals
            if self._loaded_count > len(self._all_signals):
                self._loaded_count = len(self._all_signals)
                # Need to reload display signals
                self._reload_display_signals()

        # Auto-load first page if nothing loaded yet
        if self._loaded_count == 0 and len(self._all_signals) > 0:
            self.load_more()

        # Notify that more data is available
        if self.has_more():
            self.more_available.emit()

    def load_more(self) -> int:
        """
        Load the next page of signals into display.

        Returns:
            Number of signals loaded in this page
        """
        if not self.has_more():
            return 0

        # Calculate range to load
        start = self._loaded_count
        end = min(start + self.PAGE_SIZE, len(self._all_signals))
        new_signals = self._all_signals[start:end]

        if not new_signals:
            return 0

        # Add to display signals
        first_row = len(self._signals)
        last_row = first_row + len(new_signals) - 1

        self.beginInsertRows(QModelIndex(), first_row, last_row)
        self._signals.extend(new_signals)
        self._loaded_count = end

        # Update filter if active
        if self._filter_text or self._signal_filter:
            self._apply_filter()

        self.endInsertRows()

        logger.debug(
            f"Loaded page: {len(new_signals)} signals (total loaded: {self._loaded_count})"
        )
        return len(new_signals)

    def load_all(self) -> None:
        """Load all remaining signals (use sparingly for large datasets)."""
        while self.has_more():
            self.load_more()

    def _reload_display_signals(self) -> None:
        """Reload display signals from backing buffer after trim."""
        self.beginResetModel()
        self._signals = self._all_signals[: self._loaded_count]
        if self._filter_text or self._signal_filter:
            self._apply_filter()
        else:
            self._filtered_indices = None
        self.endResetModel()

    def has_more(self) -> bool:
        """Check if there are more signals to load."""
        return self._loaded_count < len(self._all_signals)

    def clear(self) -> None:
        """Clear all signals (both buffer and display)."""
        self.beginResetModel()
        self._all_signals.clear()
        self._signals.clear()
        self._loaded_count = 0
        self._filtered_indices = None
        self.endResetModel()

    def set_filter(self, text: str) -> None:
        """Set filter text for signal/message names."""
        self.beginResetModel()
        self._filter_text = text.lower().strip()
        self._apply_filter()
        self.endResetModel()

    def set_signal_filter(self, signal_names: list[str]) -> None:
        """Set filter by specific signal full names."""
        self.beginResetModel()
        self._signal_filter = set(signal_names)
        self._apply_filter()
        self.endResetModel()

    def _apply_filter(self) -> None:
        """Apply current filters to loaded signals."""
        has_text_filter = bool(self._filter_text)
        has_signal_filter = bool(self._signal_filter)

        if not has_text_filter and not has_signal_filter:
            self._filtered_indices = None
            return

        indices = []
        for i, sig in enumerate(self._signals):
            if has_signal_filter:
                full_name = f"{sig.message_name}.{sig.signal_name}"
                if full_name not in self._signal_filter:
                    continue

            if has_text_filter:
                if not (
                    self._filter_text in sig.message_name.lower()
                    or self._filter_text in sig.signal_name.lower()
                ):
                    continue

            indices.append(i)

        self._filtered_indices = indices

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
        """Total signals in backing buffer."""
        return len(self._all_signals)

    @property
    def loaded_count(self) -> int:
        """Number of signals loaded into display."""
        return len(self._signals)

    @property
    def filtered_count(self) -> int:
        """Visible signals (after filter)."""
        if self._filtered_indices is not None:
            return len(self._filtered_indices)
        return len(self._signals)

    @property
    def has_signal_filter(self) -> bool:
        """Check if signal filter is active."""
        return bool(self._signal_filter)

    @property
    def signal_filter_count(self) -> int:
        """Number of signals in the filter."""
        return len(self._signal_filter)


class MessageLogFilterPanel(QFrame):
    """Left panel with signal filter controls for the message log."""

    add_filter_requested = Signal()
    filter_changed = Signal(list)  # Emits list of signal full names

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filter_signals: list[str] = []
        self._setup_ui()

    def _setup_ui(self):
        self.setStyleSheet("""
            MessageLogFilterPanel {
                background: #252526;
                border-right: 1px solid #3D3D3D;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Add signal button
        self._add_btn = QPushButton("➕ Add Signal")
        self._add_btn.setMinimumHeight(36)
        self._add_btn.setToolTip("Add signals to filter the message log")
        self._add_btn.clicked.connect(self.add_filter_requested.emit)
        layout.addWidget(self._add_btn)

        # Active filters label
        filters_label = QLabel("Active Filters:")
        filters_label.setStyleSheet("color: #888; font-size: 11px; margin-top: 8px;")
        layout.addWidget(filters_label)

        # Filters list
        self._filters_list = QListWidget()
        self._filters_list.setStyleSheet("""
            QListWidget {
                background: #1E1E1E;
                border: 1px solid #3D3D3D;
                border-radius: 4px;
            }
            QListWidget::item {
                padding: 6px;
                border-bottom: 1px solid #3D3D3D;
            }
            QListWidget::item:hover {
                background: #2D2D2D;
            }
        """)
        self._filters_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._filters_list.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self._filters_list)

        # Clear filters button
        self._clear_btn = QPushButton("🗑️ Clear Filters")
        self._clear_btn.clicked.connect(self._on_clear_filters)
        layout.addWidget(self._clear_btn)

        layout.addStretch()

        # Status label
        self._status_label = QLabel("Showing all signals")
        self._status_label.setStyleSheet("color: #666; font-size: 10px;")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status_label)

    def set_filter_signals(self, signal_names: list[str]):
        """Set the list of signals to filter by (replaces existing)."""
        self._filter_signals = list(signal_names)
        self._update_list()
        self.filter_changed.emit(self._filter_signals)

    def add_filter_signals(self, signal_names: list[str]):
        """Add signals to the existing filter (does not replace)."""
        for name in signal_names:
            if name not in self._filter_signals:
                self._filter_signals.append(name)
        self._update_list()
        self.filter_changed.emit(self._filter_signals)

    def get_filter_signals(self) -> list[str]:
        """Get the current list of filter signals."""
        return list(self._filter_signals)

    def _update_list(self):
        """Update the filters list widget."""
        self._filters_list.clear()

        for full_name in self._filter_signals:
            short_name = full_name.split(".")[-1]
            item = QListWidgetItem(f"● {short_name}")
            item.setData(Qt.ItemDataRole.UserRole, full_name)
            item.setToolTip(full_name)
            self._filters_list.addItem(item)

        if self._filter_signals:
            self._status_label.setText(
                f"Showing {len(self._filter_signals)} signal{'s' if len(self._filter_signals) != 1 else ''}"
            )
        else:
            self._status_label.setText("Showing all signals")

    def _show_context_menu(self, pos):
        from PySide6.QtWidgets import QMenu

        item = self._filters_list.itemAt(pos)
        if item:
            menu = QMenu(self)
            remove_action = menu.addAction("Remove")
            action = menu.exec(self._filters_list.mapToGlobal(pos))
            if action == remove_action:
                full_name = item.data(Qt.ItemDataRole.UserRole)
                self._filter_signals = [
                    s for s in self._filter_signals if s != full_name
                ]
                self._update_list()
                self.filter_changed.emit(self._filter_signals)

    def _on_clear_filters(self):
        """Clear all filters."""
        self._filter_signals.clear()
        self._update_list()
        self.filter_changed.emit(self._filter_signals)


class LogTableWidget(QWidget):
    """
    Widget containing the signal log table with infinite scroll pagination.

    Features:
    - Infinite scroll pagination (1000 signals per page)
    - Lazy UI updates (buffer incoming signals)
    - High-performance virtual scrolling
    - Search/filter capability
    - Signal name filtering
    - Auto-scroll to latest

    Pagination Strategy:
    - Incoming signals buffered in pending queue
    - Timer flushes pending to model's backing buffer
    - Model only displays loaded pages (1000 at a time)
    - Scrolling near bottom triggers load_more()
    """

    signal_selected = Signal(DecodedSignal)
    add_filter_requested = Signal()  # Request to open signal selector

    # Lazy update configuration
    UPDATE_TIMER_INTERVAL = 500  # ms between automatic updates
    MAX_PENDING_SIGNALS = 50000  # Force flush if buffer exceeds this
    SCROLL_LOAD_THRESHOLD = 50  # Pixels from bottom to trigger load more

    def __init__(self, parent=None):
        super().__init__(parent)

        self._model = SignalTableModel(self)
        self._auto_scroll = True
        self._is_parsing = False
        self._is_loading_more = False

        # Lazy update buffer
        self._pending_signals: deque[DecodedSignal] = deque()
        self._pending_count = 0

        # Update timer for lazy flushing
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(self.UPDATE_TIMER_INTERVAL)
        self._update_timer.timeout.connect(self._flush_pending_signals)

        self._setup_ui()
        self._connect_model_signals()

        # Start the update timer
        self._update_timer.start()

    def _setup_ui(self) -> None:
        """Initialize UI components."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Main splitter
        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel - Filter controls
        self._filter_panel = MessageLogFilterPanel()
        self._filter_panel.setMinimumWidth(180)
        self._filter_panel.setMaximumWidth(280)
        self._filter_panel.add_filter_requested.connect(self.add_filter_requested.emit)
        self._filter_panel.filter_changed.connect(self._on_signal_filter_changed)
        self._splitter.addWidget(self._filter_panel)

        # Right panel - Table
        table_container = QWidget()
        table_layout = QVBoxLayout(table_container)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(4)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(8, 8, 8, 8)
        toolbar.setSpacing(8)

        # Filter input
        self._filter_input = QLineEdit()
        self._filter_input.setPlaceholderText("🔍 Search by message or signal name...")
        self._filter_input.setClearButtonEnabled(True)
        self._filter_input.textChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self._filter_input, stretch=1)

        # Load all button (for loading remaining pages)
        self._load_all_btn = QPushButton("⏬ Load All")
        self._load_all_btn.setToolTip("Load all remaining signals into view")
        self._load_all_btn.clicked.connect(self._on_load_all_clicked)
        self._load_all_btn.setVisible(False)  # Hidden until there's more to load
        toolbar.addWidget(self._load_all_btn)

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

        table_layout.addLayout(toolbar)

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
        header.setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )  # Timestamp
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # Message
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # ID
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)  # Signal
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # Raw
        header.setSectionResizeMode(
            5, QHeaderView.ResizeMode.ResizeToContents
        )  # Physical
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)  # Unit

        # Optimize for performance
        self._table.setVerticalScrollMode(QTableView.ScrollMode.ScrollPerPixel)
        self._table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self._table.verticalHeader().setDefaultSectionSize(22)

        # Connect scroll events for infinite scroll
        scrollbar = self._table.verticalScrollBar()
        if scrollbar:
            scrollbar.valueChanged.connect(self._on_scroll)

        self._table.clicked.connect(self._on_row_clicked)
        table_layout.addWidget(self._table)

        # Status bar
        self._status_label = QLabel("0 signals")
        self._status_label.setStyleSheet(
            "color: #666; font-size: 11px; padding-left: 8px;"
        )
        table_layout.addWidget(self._status_label)

        self._splitter.addWidget(table_container)
        self._splitter.setSizes([200, 600])

        layout.addWidget(self._splitter)

    def _connect_model_signals(self) -> None:
        """Connect model signals."""
        self._model.more_available.connect(self._on_more_available)

    @Slot(list)
    def add_signals(self, signals: list[DecodedSignal]) -> None:
        """
        Add new signals to the pending buffer.

        Signals are buffered and flushed lazily to avoid blocking the UI
        during rapid streaming.
        """
        if not signals:
            return

        # Add to pending buffer
        self._pending_signals.extend(signals)
        self._pending_count += len(signals)

        # Force flush if buffer is getting too large
        if self._pending_count >= self.MAX_PENDING_SIGNALS:
            self._flush_pending_signals()

    def _flush_pending_signals(self) -> None:
        """Flush pending signals to the model's backing buffer."""
        if not self._pending_signals:
            return

        # Convert deque to list and clear
        signals_to_add = list(self._pending_signals)
        self._pending_signals.clear()
        self._pending_count = 0

        # Add to model (goes to backing buffer, auto-loads first page)
        self._model.add_signals(signals_to_add)
        self._update_status()

        # Auto-scroll if enabled and at bottom
        if self._auto_scroll and not self._table.underMouse():
            scrollbar = self._table.verticalScrollBar()
            if scrollbar:
                scrollbar.setValue(scrollbar.maximum())

    def _on_scroll(self, value: int) -> None:
        """
        Handle scroll events for infinite scroll pagination.

        When user scrolls near bottom of loaded data, load more signals.
        """
        scrollbar = self._table.verticalScrollBar()
        if not scrollbar:
            return

        # Check if near bottom
        pixels_from_bottom = scrollbar.maximum() - value

        if pixels_from_bottom <= self.SCROLL_LOAD_THRESHOLD:
            # Try to load more if available
            if self._model.has_more() and not self._is_loading_more:
                self._load_more_signals()

    def _load_more_signals(self) -> None:
        """Load more signals from backing buffer into display."""
        if self._is_loading_more:
            return

        self._is_loading_more = True
        loaded = self._model.load_more()
        self._is_loading_more = False

        if loaded > 0:
            self._update_status()
            logger.debug(f"Loaded {loaded} more signals via infinite scroll")

    def _on_more_available(self) -> None:
        """Handle notification that more data is available to load."""
        self._update_load_all_button()

    def _update_load_all_button(self) -> None:
        """Update visibility of Load All button."""
        has_more = self._model.has_more()
        self._load_all_btn.setVisible(has_more)

    def _on_load_all_clicked(self) -> None:
        """Handle Load All button click."""
        self._model.load_all()
        self._update_status()
        self._update_load_all_button()

    def set_parsing_state(self, is_parsing: bool) -> None:
        """
        Set parsing state to adjust update behavior.

        When parsing completes, forces a final flush of pending signals.
        """
        was_parsing = self._is_parsing
        self._is_parsing = is_parsing

        # On parsing complete, flush all pending
        if was_parsing and not is_parsing:
            self._flush_pending_signals()

    def clear(self) -> None:
        """Clear all signals from the table and buffers."""
        self._pending_signals.clear()
        self._pending_count = 0
        self._model.clear()
        self._update_status()
        self._update_load_all_button()

    def set_signal_filter(self, signal_names: list[str]) -> None:
        """Set filter by specific signal full names (replaces existing)."""
        self._filter_panel.set_filter_signals(signal_names)

    def add_signal_filter(self, signal_names: list[str]) -> None:
        """Add signals to the existing filter (does not replace)."""
        self._filter_panel.add_filter_signals(signal_names)

    def get_signal_filter(self) -> list[str]:
        """Get the current list of filter signals."""
        return self._filter_panel.get_filter_signals()

    def _on_filter_changed(self, text: str) -> None:
        """Handle filter text changes."""
        # Flush pending before applying filter
        self._flush_pending_signals()
        self._model.set_filter(text)
        self._update_status()

    def _on_signal_filter_changed(self, signal_names: list[str]) -> None:
        """Handle signal filter changes from panel."""
        # Flush pending before applying filter
        self._flush_pending_signals()
        self._model.set_signal_filter(signal_names)
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
        """Update status label with pagination info."""
        total = self._model.total_count
        loaded = self._model.loaded_count
        filtered = self._model.filtered_count
        pending = self._pending_count

        # Build status parts
        parts = []

        # Main count - show loaded of total
        if loaded < total:
            parts.append(f"{loaded:,} of {total:,} loaded")
        else:
            parts.append(f"{total:,} signals")

        # Pending indicator
        if pending > 0:
            parts.append(f"+{pending:,} pending")

        # Filter indicator
        if self._model.has_signal_filter:
            filter_count = self._model.signal_filter_count
            parts.append(
                f"filtering by {filter_count} signal{'s' if filter_count != 1 else ''}"
            )

        # Filtered count if different
        if self._model.has_signal_filter or self._model._filter_text:
            if filtered != loaded:
                parts[0] = f"{filtered:,} shown ({parts[0]})"

        self._status_label.setText(" • ".join(parts))
        self._update_load_all_button()

    @property
    def signal_count(self) -> int:
        """Get total signal count (including pending)."""
        return self._model.total_count + self._pending_count

    @property
    def loaded_count(self) -> int:
        """Get count of signals loaded into display."""
        return self._model.loaded_count

    @property
    def pending_count(self) -> int:
        """Get count of pending signals not yet flushed."""
        return self._pending_count
