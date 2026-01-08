"""
State Diagram Widget - Gantt-Chart Style Timeline.

Displays CAN signals as horizontal bars over time, similar to CANalyzer's
state diagram view. Each signal is a row, with bar segments showing
value changes over time.
"""

from typing import Optional
import numpy as np
from PySide6.QtCore import Qt, Signal, Slot, QTimer
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QFrame,
    QSizePolicy,
    QGroupBox,
    QSplitter,
    QListWidget,
    QListWidgetItem,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QFontMetrics
import pyqtgraph as pg

from ..core.models import DecodedSignal, SignalDefinition
from ..utils.logging_config import get_logger

logger = get_logger("state_diagram")


# Color palette for different state values
STATE_COLORS = [
    "#4ECDC4",  # Teal
    "#FF6B6B",  # Red
    "#45B7D1",  # Blue
    "#96CEB4",  # Green
    "#FFEAA7",  # Yellow
    "#DDA0DD",  # Plum
    "#98D8C8",  # Mint
    "#F7DC6F",  # Gold
    "#BB8FCE",  # Violet
    "#85C1E9",  # Sky blue
    "#F8B500",  # Amber
    "#82E0AA",  # Light green
]


class StateTimelineRow(QFrame):
    """
    Single row in the state diagram representing one signal.
    
    Displays horizontal bar segments where each segment represents
    a time period with a constant value.
    """
    
    ROW_HEIGHT = 50
    LABEL_WIDTH = 120
    
    def __init__(self, signal_name: str, signal_def: Optional[SignalDefinition] = None, parent=None):
        super().__init__(parent)
        
        self.signal_name = signal_name
        self.signal_def = signal_def
        self.short_name = signal_name.split(".")[-1]
        
        # Segments: list of (start_time, end_time, value, color)
        self.segments: list[tuple[float, float, float, str]] = []
        
        # Time range for display
        self.time_min = 0.0
        self.time_max = 10.0  # Default to 10 seconds
        
        # Value to color mapping
        self._value_colors: dict[float, str] = {}
        self._color_index = 0
        
        # Size policy
        self.setFixedHeight(self.ROW_HEIGHT)
        self.setMinimumWidth(300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        # Style
        self.setStyleSheet("""
            StateTimelineRow {
                background: #252526;
                border-bottom: 1px solid #3D3D3D;
            }
        """)
        self.setAutoFillBackground(True)
    
    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(600, self.ROW_HEIGHT)
    
    def get_color_for_value(self, value: float) -> str:
        """Get or assign a color for a value."""
        # Round to handle floating point
        key = round(value, 6)
        if key not in self._value_colors:
            self._value_colors[key] = STATE_COLORS[self._color_index % len(STATE_COLORS)]
            self._color_index += 1
        return self._value_colors[key]
    
    def add_segment(self, start_time: float, end_time: float, value: float) -> None:
        """Add a new segment to this row."""
        color = self.get_color_for_value(value)
        # Ensure minimum segment duration for visibility
        if end_time <= start_time:
            end_time = start_time + 0.001  # Minimum 1ms
        self.segments.append((start_time, end_time, value, color))
        self.repaint()  # Force immediate repaint
    
    def update_last_segment(self, end_time: float) -> None:
        """Extend the last segment's end time."""
        if self.segments:
            start, _, value, color = self.segments[-1]
            self.segments[-1] = (start, end_time, value, color)
            self.repaint()  # Force immediate repaint
    
    def set_time_range(self, time_min: float, time_max: float) -> None:
        """Set the visible time range for coordinate mapping."""
        if time_max > time_min:
            self.time_min = time_min
            self.time_max = time_max
            self.repaint()
    
    def clear(self) -> None:
        """Clear all segments."""
        self.segments.clear()
        self._value_colors.clear()
        self._color_index = 0
        self.repaint()
    
    def paintEvent(self, event) -> None:
        """Custom paint for the timeline row."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        width = self.width()
        height = self.height()
        
        # Background
        painter.fillRect(0, 0, width, height, QColor("#252526"))
        
        # Draw label area background
        label_rect_width = self.LABEL_WIDTH
        painter.fillRect(0, 0, label_rect_width, height, QColor("#2D2D2D"))
        
        # Draw signal name
        painter.setPen(QColor("#E0E0E0"))
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        
        # Elide text if too long
        fm = QFontMetrics(font)
        elided_name = fm.elidedText(self.short_name, Qt.TextElideMode.ElideRight, label_rect_width - 16)
        text_y = (height + fm.ascent() - fm.descent()) // 2
        painter.drawText(8, text_y, elided_name)
        
        # Draw separator line
        painter.setPen(QPen(QColor("#3D3D3D"), 1))
        painter.drawLine(label_rect_width, 0, label_rect_width, height)
        
        # Draw bottom border
        painter.drawLine(0, height - 1, width, height - 1)
        
        # Timeline area
        timeline_x = label_rect_width + 5
        timeline_width = width - label_rect_width - 10
        
        if timeline_width <= 0:
            return
        
        # Time to pixel conversion
        time_range = self.time_max - self.time_min
        if time_range <= 0:
            time_range = 1.0
        
        def time_to_x(t: float) -> int:
            normalized = (t - self.time_min) / time_range
            return int(timeline_x + normalized * timeline_width)
        
        # Draw segments
        bar_y = 8
        bar_height = height - 16
        
        font = QFont("Consolas", 8)
        painter.setFont(font)
        fm = QFontMetrics(font)
        
        for start_time, end_time, value, color in self.segments:
            x1 = max(timeline_x, time_to_x(start_time))
            x2 = min(timeline_x + timeline_width, time_to_x(end_time))
            
            # Skip if outside view
            if x2 < timeline_x or x1 > timeline_x + timeline_width:
                continue
            
            # Minimum segment width for visibility
            segment_width = max(4, x2 - x1)
            
            # Draw bar fill
            painter.fillRect(x1, bar_y, segment_width, bar_height, QColor(color))
            
            # Draw border
            painter.setPen(QPen(QColor("#1E1E1E"), 1))
            painter.drawRect(x1, bar_y, segment_width, bar_height)
            
            # Draw value text if segment is wide enough
            if segment_width > 25:
                # Get display text
                if self.signal_def and self.signal_def.choices:
                    int_val = int(round(value))
                    display_value = self.signal_def.choices.get(int_val, str(int_val))
                else:
                    if abs(value - round(value)) < 0.001:
                        display_value = str(int(round(value)))
                    else:
                        display_value = f"{value:.1f}"
                
                # Elide if needed
                text_width = fm.horizontalAdvance(display_value)
                if text_width > segment_width - 6:
                    display_value = fm.elidedText(display_value, Qt.TextElideMode.ElideRight, segment_width - 6)
                    text_width = fm.horizontalAdvance(display_value)
                
                # Draw text centered in bar
                painter.setPen(QColor("#000000"))  # Black text on colored background
                text_x = x1 + (segment_width - text_width) // 2
                text_y = bar_y + (bar_height + fm.ascent() - fm.descent()) // 2
                painter.drawText(text_x, text_y, display_value)
        
        painter.end()


class TimeAxisWidget(QFrame):
    """Time axis header showing time scale."""
    
    LABEL_WIDTH = 120  # Match row label width
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.time_min = 0.0
        self.time_max = 10.0
        
        self.setFixedHeight(28)
        self.setAutoFillBackground(True)
        self.setStyleSheet("background: #2D2D2D;")
    
    def set_time_range(self, time_min: float, time_max: float) -> None:
        """Set the time range to display."""
        if time_max > time_min:
            self.time_min = time_min
            self.time_max = time_max
            self.repaint()
    
    def paintEvent(self, event) -> None:
        """Paint the time axis."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        width = self.width()
        height = self.height()
        
        # Background
        painter.fillRect(0, 0, width, height, QColor("#2D2D2D"))
        
        # Label area
        painter.fillRect(0, 0, self.LABEL_WIDTH, height, QColor("#2D2D2D"))
        
        # Draw "Time [s]" label
        painter.setPen(QColor("#888888"))
        font = QFont()
        font.setPointSize(9)
        painter.setFont(font)
        painter.drawText(8, height - 8, "Time [s]")
        
        # Draw separator
        painter.setPen(QPen(QColor("#3D3D3D"), 1))
        painter.drawLine(self.LABEL_WIDTH, 0, self.LABEL_WIDTH, height)
        painter.drawLine(0, height - 1, width, height - 1)
        
        # Timeline area
        timeline_x = self.LABEL_WIDTH + 5
        timeline_width = width - self.LABEL_WIDTH - 10
        
        if timeline_width <= 0:
            painter.end()
            return
        
        time_range = self.time_max - self.time_min
        if time_range <= 0:
            time_range = 1.0
        
        # Calculate tick spacing - aim for roughly 80 pixels between ticks
        approx_ticks = max(2, timeline_width / 80)
        tick_interval = time_range / approx_ticks
        
        # Round to nice intervals
        if tick_interval > 0:
            magnitude = 10 ** int(np.floor(np.log10(max(tick_interval, 1e-10))))
            normalized = tick_interval / magnitude
            
            if normalized < 1.5:
                nice_interval = 1 * magnitude
            elif normalized < 3.5:
                nice_interval = 2 * magnitude
            elif normalized < 7.5:
                nice_interval = 5 * magnitude
            else:
                nice_interval = 10 * magnitude
        else:
            nice_interval = 1.0
        
        # Draw ticks
        font = QFont("Consolas", 8)
        painter.setFont(font)
        fm = painter.fontMetrics()
        
        first_tick = np.ceil(self.time_min / nice_interval) * nice_interval
        tick = first_tick
        
        while tick <= self.time_max + nice_interval * 0.1:
            normalized = (tick - self.time_min) / time_range
            x = int(timeline_x + normalized * timeline_width)
            
            if x < timeline_x or x > timeline_x + timeline_width:
                tick += nice_interval
                continue
            
            # Draw tick line
            painter.setPen(QPen(QColor("#555555"), 1))
            painter.drawLine(x, height - 6, x, height - 1)
            
            # Draw label
            painter.setPen(QColor("#AAAAAA"))
            label = f"{tick:.3g}"
            label_width = fm.horizontalAdvance(label)
            painter.drawText(x - label_width // 2, height - 10, label)
            
            tick += nice_interval
        
        painter.end()


class StateDiagramControlPanel(QWidget):
    """Left panel with controls for the state diagram."""
    
    add_signals_requested = Signal()
    run_clicked = Signal()
    stop_clicked = Signal()
    reset_clicked = Signal()
    signal_removed = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._active_signals: list[str] = []
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # Add signals button
        self._add_btn = QPushButton("➕ Add Signals")
        self._add_btn.setMinimumHeight(36)
        self._add_btn.clicked.connect(self.add_signals_requested.emit)
        layout.addWidget(self._add_btn)
        
        # Selected signals list
        signals_label = QLabel("Selected Signals:")
        signals_label.setStyleSheet("color: #888; font-size: 11px; margin-top: 8px;")
        layout.addWidget(signals_label)
        
        self._signals_list = QListWidget()
        self._signals_list.setStyleSheet("""
            QListWidget {
                background: #252526;
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
        self._signals_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._signals_list.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self._signals_list)
        
        # Playback controls
        controls_label = QLabel("Timeline Controls:")
        controls_label.setStyleSheet("color: #888; font-size: 11px; margin-top: 8px;")
        layout.addWidget(controls_label)
        
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(4)
        
        self._run_btn = QPushButton("▶ Run")
        self._run_btn.clicked.connect(self.run_clicked.emit)
        controls_layout.addWidget(self._run_btn)
        
        self._stop_btn = QPushButton("⏹ Stop")
        self._stop_btn.clicked.connect(self.stop_clicked.emit)
        controls_layout.addWidget(self._stop_btn)
        
        layout.addLayout(controls_layout)
        
        self._reset_btn = QPushButton("🔄 Reset")
        self._reset_btn.clicked.connect(self.reset_clicked.emit)
        layout.addWidget(self._reset_btn)
        
        # Clear all button
        self._clear_btn = QPushButton("🗑️ Clear All")
        self._clear_btn.setStyleSheet("background: #8B0000;")
        self._clear_btn.clicked.connect(self._on_clear_all)
        layout.addWidget(self._clear_btn)
        
        layout.addStretch()
        
        # Info label
        self._info_label = QLabel("0 signals")
        self._info_label.setStyleSheet("color: #666; font-size: 10px;")
        self._info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._info_label)
    
    def set_signals(self, signal_names: list[str]):
        """Update the signals list."""
        self._active_signals = list(signal_names)
        self._signals_list.clear()
        
        for i, name in enumerate(signal_names):
            short_name = name.split(".")[-1]
            color = STATE_COLORS[i % len(STATE_COLORS)]
            
            item = QListWidgetItem(f"● {short_name}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setForeground(QColor(color))
            item.setToolTip(name)
            self._signals_list.addItem(item)
        
        self._info_label.setText(f"{len(signal_names)} signal{'s' if len(signal_names) != 1 else ''}")
    
    def _show_context_menu(self, pos):
        from PySide6.QtWidgets import QMenu
        item = self._signals_list.itemAt(pos)
        if item:
            menu = QMenu(self)
            remove_action = menu.addAction("Remove")
            action = menu.exec(self._signals_list.mapToGlobal(pos))
            if action == remove_action:
                full_name = item.data(Qt.ItemDataRole.UserRole)
                self.signal_removed.emit(full_name)
    
    def _on_clear_all(self):
        self._active_signals.clear()
        self._signals_list.clear()
        self._info_label.setText("0 signals")
        self.reset_clicked.emit()


class StateDiagramWidget(QWidget):
    """
    State diagram visualization as Gantt-chart style horizontal bars.
    
    This is the main widget containing both the control panel and timeline.
    """
    
    add_signals_requested = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._signal_defs: dict[str, SignalDefinition] = {}
        self._active_signals: list[str] = []
        self._rows: dict[str, StateTimelineRow] = {}
        self._last_values: dict[str, tuple[float, float]] = {}
        
        self._time_min = 0.0
        self._time_max = 10.0
        self._is_running = False
        
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Main splitter
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left panel - Controls
        self._control_panel = StateDiagramControlPanel()
        self._control_panel.setMinimumWidth(180)
        self._control_panel.setMaximumWidth(280)
        self._control_panel.add_signals_requested.connect(self.add_signals_requested.emit)
        self._control_panel.run_clicked.connect(self._on_run)
        self._control_panel.stop_clicked.connect(self._on_stop)
        self._control_panel.reset_clicked.connect(self._on_reset)
        self._control_panel.signal_removed.connect(self._on_signal_removed)
        self._splitter.addWidget(self._control_panel)
        
        # Right panel - Timeline
        timeline_container = QWidget()
        timeline_layout = QVBoxLayout(timeline_container)
        timeline_layout.setContentsMargins(0, 0, 0, 0)
        timeline_layout.setSpacing(0)
        
        # Time axis header
        self._time_header = TimeAxisWidget()
        timeline_layout.addWidget(self._time_header)
        
        # Scroll area for rows
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll_area.setStyleSheet("""
            QScrollArea {
                background: #1E1E1E;
                border: none;
            }
        """)
        
        # Container for rows
        self._rows_container = QWidget()
        self._rows_container.setStyleSheet("background: #1E1E1E;")
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(0)
        self._rows_layout.addStretch()
        
        # Empty state message
        self._empty_label = QLabel("Click 'Add Signals' to select signals for the state diagram")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color: #666; font-size: 12px; padding: 60px;")
        self._rows_layout.insertWidget(0, self._empty_label)
        
        self._scroll_area.setWidget(self._rows_container)
        timeline_layout.addWidget(self._scroll_area)
        
        self._splitter.addWidget(timeline_container)
        self._splitter.setSizes([200, 600])
        
        layout.addWidget(self._splitter)
    
    def set_signal_definitions(self, definitions: dict[str, SignalDefinition]) -> None:
        """Set available signal definitions from DBC."""
        self._signal_defs = definitions
    
    def set_active_signals(self, signal_names: list[str]) -> None:
        """Set which signals to display."""
        # Remove old rows
        for name in list(self._rows.keys()):
            if name not in signal_names:
                row = self._rows.pop(name)
                self._rows_layout.removeWidget(row)
                row.deleteLater()
                if name in self._last_values:
                    del self._last_values[name]
        
        # Add new rows
        for name in signal_names:
            if name not in self._rows:
                sig_def = self._signal_defs.get(name)
                row = StateTimelineRow(name, sig_def)
                row.set_time_range(self._time_min, self._time_max)
                self._rows[name] = row
                self._rows_layout.insertWidget(self._rows_layout.count() - 1, row)
        
        self._active_signals = list(signal_names)
        self._empty_label.setVisible(len(self._active_signals) == 0)
        self._control_panel.set_signals(signal_names)
        self._sync_time_range()
    
    def get_active_signals(self) -> list[str]:
        """Get list of currently active signal names."""
        return self._active_signals.copy()
    
    @Slot(list)
    def add_signals(self, signals: list[DecodedSignal]) -> None:
        """Add new decoded signals (streaming mode)."""
        if not self._active_signals:
            return
        
        updated = False
        
        for signal in signals:
            full_name = signal.full_name
            
            if full_name not in self._active_signals:
                continue
            
            row = self._rows.get(full_name)
            if not row:
                continue
            
            timestamp = signal.timestamp
            value = signal.raw_value
            
            # Update time range
            if self._time_min == 0.0 or timestamp < self._time_min:
                self._time_min = timestamp
            if timestamp > self._time_max:
                self._time_max = timestamp + 1.0  # Add buffer
                updated = True
            
            # Check if value changed
            if full_name in self._last_values:
                last_ts, last_val = self._last_values[full_name]
                
                if abs(value - last_val) > 0.0001:
                    # Value changed - start new segment
                    row.add_segment(timestamp, timestamp + 0.01, value)
                else:
                    # Same value - extend current segment
                    row.update_last_segment(timestamp)
            else:
                # First value for this signal
                row.add_segment(timestamp, timestamp + 0.01, value)
            
            self._last_values[full_name] = (timestamp, value)
        
        if updated:
            self._sync_time_range()
            self._time_header.set_time_range(self._time_min, self._time_max)
    
    def _sync_time_range(self) -> None:
        """Synchronize time range across all rows."""
        for row in self._rows.values():
            row.set_time_range(self._time_min, self._time_max)
    
    def _on_run(self):
        """Handle run button click."""
        self._is_running = True
        logger.info("State diagram: Run")
    
    def _on_stop(self):
        """Handle stop button click."""
        self._is_running = False
        logger.info("State diagram: Stop")
    
    def _on_reset(self):
        """Handle reset button click."""
        self.clear_data()
        logger.info("State diagram: Reset")
    
    def _on_signal_removed(self, full_name: str):
        """Handle signal removal from control panel."""
        if full_name in self._active_signals:
            new_signals = [s for s in self._active_signals if s != full_name]
            self.set_active_signals(new_signals)
    
    def clear_data(self) -> None:
        """Clear data but keep signal selection."""
        for row in self._rows.values():
            row.clear()
        
        self._last_values.clear()
        self._time_min = 0.0
        self._time_max = 10.0
        self._time_header.set_time_range(0, 10)
        self._sync_time_range()
    
    def clear(self) -> None:
        """Clear everything including signal selection."""
        self._active_signals.clear()
        
        for row in self._rows.values():
            self._rows_layout.removeWidget(row)
            row.deleteLater()
        
        self._rows.clear()
        self._last_values.clear()
        self._time_min = 0.0
        self._time_max = 10.0
        
        self._empty_label.setVisible(True)
        self._control_panel.set_signals([])
        self._time_header.set_time_range(0, 10)
