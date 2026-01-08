"""
State Diagram Widget - Gantt-Chart Style Timeline.

Displays CAN signals as horizontal bars over time, similar to CANalyzer's
state diagram view. Each signal is a row, with bar segments showing
value changes over time.

Features:
- Interactive pan/zoom with mouse
- Hover tooltips showing signal values
- Playback cursor for timeline animation
"""

from typing import Optional
import numpy as np
from PySide6.QtCore import Qt, Signal, Slot, QTimer, QPoint
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
    QSlider,
    QToolTip,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QFontMetrics, QCursor, QWheelEvent, QMouseEvent
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
    
    Features:
    - Hover tooltip showing value at cursor position
    - Mouse wheel zoom (forwarded to parent)
    - Drag to pan (forwarded to parent)
    """
    
    ROW_HEIGHT = 50
    LABEL_WIDTH = 120
    
    # Signals for interaction
    wheel_zoom = Signal(float, float)  # (delta, mouse_time_position)
    drag_pan = Signal(float)  # delta_time
    
    def __init__(self, signal_name: str, signal_def: Optional[SignalDefinition] = None, parent=None):
        super().__init__(parent)
        
        self.signal_name = signal_name
        self.signal_def = signal_def
        self.short_name = signal_name.split(".")[-1]
        
        # Segments: list of (start_time, end_time, value, color)
        self.segments: list[tuple[float, float, float, str]] = []
        
        # Time range for display (view window)
        self.time_min = 0.0
        self.time_max = 10.0  # Default to 10 seconds
        
        # Current playback position (for cursor line)
        self.cursor_time: Optional[float] = None
        
        # Value to color mapping
        self._value_colors: dict[float, str] = {}
        self._color_index = 0
        
        # Mouse interaction state
        self._is_dragging = False
        self._drag_start_x = 0
        self._drag_start_time = 0.0
        
        # Size policy
        self.setFixedHeight(self.ROW_HEIGHT)
        self.setMinimumWidth(300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        # Enable mouse tracking for hover tooltips
        self.setMouseTracking(True)
        
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
        key = round(value, 6)
        if key not in self._value_colors:
            self._value_colors[key] = STATE_COLORS[self._color_index % len(STATE_COLORS)]
            self._color_index += 1
        return self._value_colors[key]
    
    def add_segment(self, start_time: float, end_time: float, value: float) -> None:
        """Add a new segment to this row."""
        color = self.get_color_for_value(value)
        if end_time <= start_time:
            end_time = start_time + 0.001
        self.segments.append((start_time, end_time, value, color))
        self.repaint()
    
    def update_last_segment(self, end_time: float) -> None:
        """Extend the last segment's end time."""
        if self.segments:
            start, _, value, color = self.segments[-1]
            self.segments[-1] = (start, end_time, value, color)
            self.repaint()
    
    def set_time_range(self, time_min: float, time_max: float) -> None:
        """Set the visible time range for coordinate mapping."""
        if time_max > time_min:
            self.time_min = time_min
            self.time_max = time_max
            self.repaint()
    
    def set_cursor(self, cursor_time: Optional[float]) -> None:
        """Set the cursor position for playback."""
        self.cursor_time = cursor_time
        self.repaint()
    
    def clear(self) -> None:
        """Clear all segments."""
        self.segments.clear()
        self._value_colors.clear()
        self._color_index = 0
        self.cursor_time = None
        self.repaint()
    
    def get_data_time_range(self) -> tuple[float, float]:
        """Get the actual time range of data in this row."""
        if not self.segments:
            return (0.0, 0.0)
        min_t = min(s[0] for s in self.segments)
        max_t = max(s[1] for s in self.segments)
        return (min_t, max_t)
    
    def _x_to_time(self, x: int) -> float:
        """Convert x pixel coordinate to time value."""
        timeline_x = self.LABEL_WIDTH + 5
        timeline_width = self.width() - self.LABEL_WIDTH - 10
        if timeline_width <= 0:
            return self.time_min
        normalized = (x - timeline_x) / timeline_width
        return self.time_min + normalized * (self.time_max - self.time_min)
    
    def _time_to_x(self, t: float) -> int:
        """Convert time value to x pixel coordinate."""
        timeline_x = self.LABEL_WIDTH + 5
        timeline_width = self.width() - self.LABEL_WIDTH - 10
        time_range = self.time_max - self.time_min
        if time_range <= 0:
            return timeline_x
        normalized = (t - self.time_min) / time_range
        return int(timeline_x + normalized * timeline_width)
    
    def _get_value_at_time(self, time: float) -> Optional[tuple[float, str]]:
        """Get the value and display string at a given time."""
        for start, end, value, color in self.segments:
            if start <= time <= end:
                if self.signal_def and self.signal_def.choices:
                    int_val = int(round(value))
                    display = self.signal_def.choices.get(int_val, str(int_val))
                else:
                    if abs(value - round(value)) < 0.001:
                        display = str(int(round(value)))
                    else:
                        display = f"{value:.3f}"
                return (value, display)
        return None
    
    def wheelEvent(self, event: QWheelEvent) -> None:
        """Handle mouse wheel for zooming."""
        if event.position().x() > self.LABEL_WIDTH:
            mouse_time = self._x_to_time(int(event.position().x()))
            delta = event.angleDelta().y()
            self.wheel_zoom.emit(delta, mouse_time)
        event.accept()
    
    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Start drag operation for panning."""
        if event.button() == Qt.MouseButton.LeftButton and event.position().x() > self.LABEL_WIDTH:
            self._is_dragging = True
            self._drag_start_x = int(event.position().x())
            self._drag_start_time = self._x_to_time(self._drag_start_x)
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            event.accept()
        else:
            super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Handle mouse move for drag panning and tooltips."""
        x = int(event.position().x())
        
        if self._is_dragging:
            # Calculate time delta and emit pan signal
            current_time = self._x_to_time(x)
            delta_time = self._drag_start_time - current_time
            self.drag_pan.emit(delta_time)
            self._drag_start_x = x
            self._drag_start_time = self._x_to_time(x)
        elif x > self.LABEL_WIDTH:
            # Show tooltip with value at cursor
            time = self._x_to_time(x)
            result = self._get_value_at_time(time)
            if result:
                value, display = result
                tooltip_text = f"{self.short_name}\nTime: {time:.4f}s\nValue: {display}"
                QToolTip.showText(event.globalPosition().toPoint(), tooltip_text, self)
            else:
                QToolTip.hideText()
            # Change cursor to indicate interactivity
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        else:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            QToolTip.hideText()
        
        event.accept()
    
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """End drag operation."""
        if event.button() == Qt.MouseButton.LeftButton and self._is_dragging:
            self._is_dragging = False
            if event.position().x() > self.LABEL_WIDTH:
                self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
            else:
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            event.accept()
        else:
            super().mouseReleaseEvent(event)
    
    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Double-click to reset view (handled by parent)."""
        if event.position().x() > self.LABEL_WIDTH:
            # Let parent handle fit-to-data
            event.ignore()
        else:
            super().mouseDoubleClickEvent(event)
    
    def leaveEvent(self, event) -> None:
        """Hide tooltip when mouse leaves."""
        QToolTip.hideText()
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        super().leaveEvent(event)
    
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
        
        fm = QFontMetrics(font)
        elided_name = fm.elidedText(self.short_name, Qt.TextElideMode.ElideRight, label_rect_width - 16)
        text_y = (height + fm.ascent() - fm.descent()) // 2
        painter.drawText(8, text_y, elided_name)
        
        # Draw separator line
        painter.setPen(QPen(QColor("#3D3D3D"), 1))
        painter.drawLine(label_rect_width, 0, label_rect_width, height)
        painter.drawLine(0, height - 1, width, height - 1)
        
        # Timeline area
        timeline_x = label_rect_width + 5
        timeline_width = width - label_rect_width - 10
        
        if timeline_width <= 0:
            painter.end()
            return
        
        time_range = self.time_max - self.time_min
        if time_range <= 0:
            time_range = 1.0
        
        # Draw segments
        bar_y = 8
        bar_height = height - 16
        
        font = QFont("Consolas", 8)
        painter.setFont(font)
        fm = QFontMetrics(font)
        
        for start_time, end_time, value, color in self.segments:
            x1 = max(timeline_x, self._time_to_x(start_time))
            x2 = min(timeline_x + timeline_width, self._time_to_x(end_time))
            
            if x2 < timeline_x or x1 > timeline_x + timeline_width:
                continue
            
            segment_width = max(4, x2 - x1)
            
            painter.fillRect(x1, bar_y, segment_width, bar_height, QColor(color))
            
            painter.setPen(QPen(QColor("#1E1E1E"), 1))
            painter.drawRect(x1, bar_y, segment_width, bar_height)
            
            if segment_width > 25:
                if self.signal_def and self.signal_def.choices:
                    int_val = int(round(value))
                    display_value = self.signal_def.choices.get(int_val, str(int_val))
                else:
                    if abs(value - round(value)) < 0.001:
                        display_value = str(int(round(value)))
                    else:
                        display_value = f"{value:.1f}"
                
                text_width = fm.horizontalAdvance(display_value)
                if text_width > segment_width - 6:
                    display_value = fm.elidedText(display_value, Qt.TextElideMode.ElideRight, segment_width - 6)
                    text_width = fm.horizontalAdvance(display_value)
                
                painter.setPen(QColor("#000000"))
                text_x = x1 + (segment_width - text_width) // 2
                text_y = bar_y + (bar_height + fm.ascent() - fm.descent()) // 2
                painter.drawText(text_x, text_y, display_value)
        
        # Draw cursor line if set
        if self.cursor_time is not None and self.time_min <= self.cursor_time <= self.time_max:
            cursor_x = self._time_to_x(self.cursor_time)
            painter.setPen(QPen(QColor("#FF5722"), 2))
            painter.drawLine(cursor_x, 2, cursor_x, height - 2)
        
        painter.end()


class TimeAxisWidget(QFrame):
    """
    Time axis header showing time scale.
    
    Features:
    - Mouse wheel zoom (centered on cursor)
    - Drag to pan
    - Double-click to reset view
    """
    
    LABEL_WIDTH = 120
    
    # Signals for interaction
    wheel_zoom = Signal(float, float)  # (delta, mouse_time_position)
    drag_pan = Signal(float)  # delta_time
    reset_view = Signal()  # Double-click to fit all data
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.time_min = 0.0
        self.time_max = 10.0
        self.cursor_time: Optional[float] = None
        
        # Drag state
        self._is_dragging = False
        self._drag_start_x = 0
        self._drag_start_time = 0.0
        
        self.setFixedHeight(28)
        self.setAutoFillBackground(True)
        self.setMouseTracking(True)
        self.setStyleSheet("background: #2D2D2D;")
    
    def set_time_range(self, time_min: float, time_max: float) -> None:
        """Set the time range to display."""
        if time_max > time_min:
            self.time_min = time_min
            self.time_max = time_max
            self.repaint()
    
    def set_cursor(self, cursor_time: Optional[float]) -> None:
        """Set the cursor position."""
        self.cursor_time = cursor_time
        self.repaint()
    
    def _x_to_time(self, x: int) -> float:
        """Convert x pixel coordinate to time value."""
        timeline_x = self.LABEL_WIDTH + 5
        timeline_width = self.width() - self.LABEL_WIDTH - 10
        if timeline_width <= 0:
            return self.time_min
        normalized = (x - timeline_x) / timeline_width
        return self.time_min + normalized * (self.time_max - self.time_min)
    
    def _time_to_x(self, t: float) -> int:
        """Convert time value to x pixel coordinate."""
        timeline_x = self.LABEL_WIDTH + 5
        timeline_width = self.width() - self.LABEL_WIDTH - 10
        time_range = self.time_max - self.time_min
        if time_range <= 0:
            return timeline_x
        normalized = (t - self.time_min) / time_range
        return int(timeline_x + normalized * timeline_width)
    
    def wheelEvent(self, event: QWheelEvent) -> None:
        """Handle mouse wheel for zooming."""
        if event.position().x() > self.LABEL_WIDTH:
            mouse_time = self._x_to_time(int(event.position().x()))
            delta = event.angleDelta().y()
            self.wheel_zoom.emit(delta, mouse_time)
        event.accept()
    
    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Start drag operation for panning."""
        if event.button() == Qt.MouseButton.LeftButton and event.position().x() > self.LABEL_WIDTH:
            self._is_dragging = True
            self._drag_start_x = int(event.position().x())
            self._drag_start_time = self._x_to_time(self._drag_start_x)
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            event.accept()
        else:
            super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Handle mouse move for drag panning."""
        x = int(event.position().x())
        
        if self._is_dragging:
            current_time = self._x_to_time(x)
            delta_time = self._drag_start_time - current_time
            self.drag_pan.emit(delta_time)
            self._drag_start_x = x
            self._drag_start_time = self._x_to_time(x)
        elif x > self.LABEL_WIDTH:
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        else:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        
        event.accept()
    
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """End drag operation."""
        if event.button() == Qt.MouseButton.LeftButton and self._is_dragging:
            self._is_dragging = False
            if event.position().x() > self.LABEL_WIDTH:
                self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
            else:
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            event.accept()
        else:
            super().mouseReleaseEvent(event)
    
    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Double-click to reset view to fit all data."""
        if event.position().x() > self.LABEL_WIDTH:
            self.reset_view.emit()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)
    
    def leaveEvent(self, event) -> None:
        """Reset cursor when mouse leaves."""
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        super().leaveEvent(event)
    
    def paintEvent(self, event) -> None:
        """Paint the time axis."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        width = self.width()
        height = self.height()
        
        painter.fillRect(0, 0, width, height, QColor("#2D2D2D"))
        painter.fillRect(0, 0, self.LABEL_WIDTH, height, QColor("#2D2D2D"))
        
        painter.setPen(QColor("#888888"))
        font = QFont()
        font.setPointSize(9)
        painter.setFont(font)
        painter.drawText(8, height - 8, "Time [s]")
        
        painter.setPen(QPen(QColor("#3D3D3D"), 1))
        painter.drawLine(self.LABEL_WIDTH, 0, self.LABEL_WIDTH, height)
        painter.drawLine(0, height - 1, width, height - 1)
        
        timeline_x = self.LABEL_WIDTH + 5
        timeline_width = width - self.LABEL_WIDTH - 10
        
        if timeline_width <= 0:
            painter.end()
            return
        
        time_range = self.time_max - self.time_min
        if time_range <= 0:
            time_range = 1.0
        
        # Calculate tick spacing
        approx_ticks = max(2, timeline_width / 80)
        tick_interval = time_range / approx_ticks
        
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
        
        font = QFont("Consolas", 8)
        painter.setFont(font)
        fm = painter.fontMetrics()
        
        first_tick = np.ceil(self.time_min / nice_interval) * nice_interval
        tick = first_tick
        
        while tick <= self.time_max + nice_interval * 0.1:
            x = self._time_to_x(tick)
            
            if x < timeline_x or x > timeline_x + timeline_width:
                tick += nice_interval
                continue
            
            painter.setPen(QPen(QColor("#555555"), 1))
            painter.drawLine(x, height - 6, x, height - 1)
            
            painter.setPen(QColor("#AAAAAA"))
            label = f"{tick:.3g}"
            label_width = fm.horizontalAdvance(label)
            painter.drawText(x - label_width // 2, height - 10, label)
            
            tick += nice_interval
        
        # Draw cursor line
        if self.cursor_time is not None and self.time_min <= self.cursor_time <= self.time_max:
            cursor_x = self._time_to_x(self.cursor_time)
            painter.setPen(QPen(QColor("#FF5722"), 2))
            painter.drawLine(cursor_x, 2, cursor_x, height - 2)
            
            painter.setPen(QColor("#FF5722"))
            cursor_label = f"{self.cursor_time:.3f}s"
            painter.drawText(cursor_x + 4, height - 10, cursor_label)
        
        painter.end()


class StateDiagramControlPanel(QWidget):
    """Left panel with controls for the state diagram."""
    
    add_signals_requested = Signal()
    run_clicked = Signal()
    stop_clicked = Signal()
    reset_clicked = Signal()
    signal_removed = Signal(str)
    speed_changed = Signal(float)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._active_signals: list[str] = []
        self._is_running = False
    
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
        controls_label = QLabel("Timeline Playback:")
        controls_label.setStyleSheet("color: #888; font-size: 11px; margin-top: 8px;")
        layout.addWidget(controls_label)
        
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(4)
        
        self._run_btn = QPushButton("▶ Run")
        self._run_btn.clicked.connect(self._on_run_clicked)
        controls_layout.addWidget(self._run_btn)
        
        self._stop_btn = QPushButton("⏹ Stop")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop_clicked)
        controls_layout.addWidget(self._stop_btn)
        
        layout.addLayout(controls_layout)
        
        self._reset_btn = QPushButton("🔄 Reset")
        self._reset_btn.clicked.connect(self.reset_clicked.emit)
        layout.addWidget(self._reset_btn)
        
        # Playback speed control
        speed_label = QLabel("Playback Speed:")
        speed_label.setStyleSheet("color: #888; font-size: 11px; margin-top: 8px;")
        layout.addWidget(speed_label)
        
        speed_layout = QHBoxLayout()
        self._speed_slider = QSlider(Qt.Orientation.Horizontal)
        self._speed_slider.setMinimum(1)
        self._speed_slider.setMaximum(100)
        self._speed_slider.setValue(10)
        self._speed_slider.valueChanged.connect(self._on_speed_changed)
        speed_layout.addWidget(self._speed_slider)
        
        self._speed_label = QLabel("1.0x")
        self._speed_label.setMinimumWidth(40)
        speed_layout.addWidget(self._speed_label)
        
        layout.addLayout(speed_layout)
        
        # Clear all button
        self._clear_btn = QPushButton("🗑️ Clear All")
        self._clear_btn.setStyleSheet("background: #8B0000;")
        self._clear_btn.clicked.connect(self._on_clear_all)
        layout.addWidget(self._clear_btn)
        
        layout.addStretch()
        
        # Zoom info label
        self._zoom_label = QLabel("Scroll: zoom | Drag: pan")
        self._zoom_label.setStyleSheet("color: #555; font-size: 9px;")
        self._zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._zoom_label)
        
        # Status label
        self._status_label = QLabel("Stopped")
        self._status_label.setStyleSheet("color: #888; font-size: 10px;")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status_label)
        
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
    
    def set_running(self, running: bool):
        """Update button states based on running status."""
        self._is_running = running
        self._run_btn.setEnabled(not running)
        self._stop_btn.setEnabled(running)
        self._status_label.setText("▶ Playing..." if running else "⏹ Stopped")
        self._status_label.setStyleSheet(f"color: {'#4CAF50' if running else '#888'}; font-size: 10px;")
    
    def set_playback_time(self, current_time: float, total_time: float):
        """Update status with playback position."""
        if total_time > 0:
            percent = (current_time / total_time) * 100
            self._status_label.setText(f"▶ {percent:.1f}% ({current_time:.2f}s / {total_time:.2f}s)")
    
    def _on_run_clicked(self):
        self.run_clicked.emit()
    
    def _on_stop_clicked(self):
        self.stop_clicked.emit()
    
    def _on_speed_changed(self, value: int):
        speed = value / 10.0
        self._speed_label.setText(f"{speed:.1f}x")
        self.speed_changed.emit(speed)
    
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
    
    Features:
    - Interactive pan/zoom with mouse wheel and drag
    - Hover tooltips showing signal values
    - Timeline playback with cursor
    - Adjustable playback speed
    - Stores ALL signal data so signals can be added after parsing
    """
    
    add_signals_requested = Signal()
    
    PLAYBACK_INTERVAL_MS = 50
    MAX_STORED_SIGNALS = 100_000
    ZOOM_FACTOR = 0.15  # Zoom amount per wheel step
    MIN_TIME_RANGE = 0.001  # Minimum visible time range (1ms)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._signal_defs: dict[str, SignalDefinition] = {}
        self._active_signals: list[str] = []
        self._rows: dict[str, StateTimelineRow] = {}
        self._last_values: dict[str, tuple[float, float]] = {}
        
        self._all_signal_data: dict[str, list[tuple[float, float]]] = {}
        
        # Time offset - first timestamp becomes 0
        self._time_offset = 0.0
        self._time_offset_set = False
        
        self._view_time_min = 0.0
        self._view_time_max = 10.0
        
        # Data time range (relative to offset, so starts at 0)
        self._data_time_min = 0.0
        self._data_time_max = 0.0
        
        self._is_running = False
        self._playback_position = 0.0
        self._playback_speed = 1.0
        self._view_window_size = 10.0
        
        self._playback_timer = QTimer(self)
        self._playback_timer.setInterval(self.PLAYBACK_INTERVAL_MS)
        self._playback_timer.timeout.connect(self._on_playback_tick)
        
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
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
        self._control_panel.speed_changed.connect(self._on_speed_changed)
        self._splitter.addWidget(self._control_panel)
        
        # Right panel - Timeline
        timeline_container = QWidget()
        timeline_layout = QVBoxLayout(timeline_container)
        timeline_layout.setContentsMargins(0, 0, 0, 0)
        timeline_layout.setSpacing(0)
        
        # Time axis header
        self._time_header = TimeAxisWidget()
        self._time_header.wheel_zoom.connect(self._on_wheel_zoom)
        self._time_header.drag_pan.connect(self._on_drag_pan)
        self._time_header.reset_view.connect(self._fit_view_to_data)
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
        
        self._rows_container = QWidget()
        self._rows_container.setStyleSheet("background: #1E1E1E;")
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(0)
        self._rows_layout.addStretch()
        
        self._empty_label = QLabel("Click 'Add Signals' to select signals for the state diagram")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color: #666; font-size: 12px; padding: 60px;")
        self._rows_layout.insertWidget(0, self._empty_label)
        
        self._scroll_area.setWidget(self._rows_container)
        timeline_layout.addWidget(self._scroll_area)
        
        self._splitter.addWidget(timeline_container)
        self._splitter.setSizes([200, 600])
        
        layout.addWidget(self._splitter)
    
    def _on_wheel_zoom(self, delta: float, mouse_time: float) -> None:
        """Handle mouse wheel zoom centered on mouse position."""
        if self._is_running:
            return  # Don't zoom during playback
        
        # Calculate zoom factor
        if delta > 0:
            factor = 1 - self.ZOOM_FACTOR  # Zoom in
        else:
            factor = 1 + self.ZOOM_FACTOR  # Zoom out
        
        # Current range
        current_range = self._view_time_max - self._view_time_min
        new_range = current_range * factor
        
        # Clamp minimum zoom
        if new_range < self.MIN_TIME_RANGE:
            new_range = self.MIN_TIME_RANGE
        
        # Keep mouse position fixed on screen
        mouse_ratio = (mouse_time - self._view_time_min) / current_range if current_range > 0 else 0.5
        
        self._view_time_min = mouse_time - mouse_ratio * new_range
        self._view_time_max = mouse_time + (1 - mouse_ratio) * new_range
        self._view_window_size = new_range
        
        self._sync_time_range()
        self._time_header.set_time_range(self._view_time_min, self._view_time_max)
    
    def _on_drag_pan(self, delta_time: float) -> None:
        """Handle drag panning."""
        if self._is_running:
            return  # Don't pan during playback
        
        self._view_time_min += delta_time
        self._view_time_max += delta_time
        
        self._sync_time_range()
        self._time_header.set_time_range(self._view_time_min, self._view_time_max)
    
    def set_signal_definitions(self, definitions: dict[str, SignalDefinition]) -> None:
        """Set available signal definitions from DBC."""
        self._signal_defs = definitions
    
    def set_active_signals(self, signal_names: list[str]) -> None:
        """Set which signals to display."""
        self._on_stop()
        
        for name in list(self._rows.keys()):
            if name not in signal_names:
                row = self._rows.pop(name)
                self._rows_layout.removeWidget(row)
                row.deleteLater()
                if name in self._last_values:
                    del self._last_values[name]
        
        for name in signal_names:
            if name not in self._rows:
                sig_def = self._signal_defs.get(name)
                row = StateTimelineRow(name, sig_def)
                row.set_time_range(self._view_time_min, self._view_time_max)
                # Connect row signals for zoom/pan
                row.wheel_zoom.connect(self._on_wheel_zoom)
                row.drag_pan.connect(self._on_drag_pan)
                self._rows[name] = row
                self._rows_layout.insertWidget(self._rows_layout.count() - 1, row)
                
                self._rebuild_row_from_data(name, row)
        
        self._active_signals = list(signal_names)
        self._empty_label.setVisible(len(self._active_signals) == 0)
        self._control_panel.set_signals(signal_names)
        
        self._fit_view_to_data()
    
    def _rebuild_row_from_data(self, signal_name: str, row: StateTimelineRow) -> None:
        """Rebuild a row's timeline from stored signal data."""
        if signal_name not in self._all_signal_data:
            return
        
        data = self._all_signal_data[signal_name]
        if not data:
            return
        
        logger.info(f"Rebuilding timeline for {signal_name} with {len(data)} data points")
        
        last_val = None
        last_ts = None
        
        for timestamp, value in data:
            if last_val is None:
                row.add_segment(timestamp, timestamp + 0.01, value)
            elif abs(value - last_val) > 0.0001:
                row.add_segment(timestamp, timestamp + 0.01, value)
            else:
                row.update_last_segment(timestamp)
            
            last_val = value
            last_ts = timestamp
        
        if last_ts is not None and last_val is not None:
            self._last_values[signal_name] = (last_ts, last_val)
    
    def get_active_signals(self) -> list[str]:
        """Get list of currently active signal names."""
        return self._active_signals.copy()
    
    @Slot(list)
    def add_signals(self, signals: list[DecodedSignal]) -> None:
        """Add new decoded signals (streaming mode)."""
        for signal in signals:
            full_name = signal.full_name
            abs_timestamp = signal.timestamp
            value = signal.raw_value
            
            # Set time offset on first signal (first timestamp becomes 0)
            if not self._time_offset_set:
                self._time_offset = abs_timestamp
                self._time_offset_set = True
            
            # Convert to relative time (duration from start)
            rel_timestamp = abs_timestamp - self._time_offset
            
            if full_name not in self._all_signal_data:
                self._all_signal_data[full_name] = []
            
            # Store relative timestamp
            self._all_signal_data[full_name].append((rel_timestamp, value))
            
            if len(self._all_signal_data[full_name]) > self.MAX_STORED_SIGNALS:
                self._all_signal_data[full_name] = self._all_signal_data[full_name][-self.MAX_STORED_SIGNALS:]
            
            # Update data time range (relative times)
            if rel_timestamp < self._data_time_min:
                self._data_time_min = rel_timestamp
            if rel_timestamp > self._data_time_max:
                self._data_time_max = rel_timestamp
            
            if full_name not in self._active_signals:
                continue
            
            row = self._rows.get(full_name)
            if not row:
                continue
            
            if full_name in self._last_values:
                last_ts, last_val = self._last_values[full_name]
                
                if abs(value - last_val) > 0.0001:
                    row.add_segment(rel_timestamp, rel_timestamp + 0.01, value)
                else:
                    row.update_last_segment(rel_timestamp)
            else:
                row.add_segment(rel_timestamp, rel_timestamp + 0.01, value)
            
            self._last_values[full_name] = (rel_timestamp, value)
        
        if not self._is_running and self._active_signals:
            self._fit_view_to_data()
    
    def _fit_view_to_data(self) -> None:
        """Fit the view to show all data (relative time starting from 0)."""
        if self._data_time_max > 0:
            # Start from 0, add small padding at end
            padding = self._data_time_max * 0.05
            self._view_time_min = 0.0
            self._view_time_max = self._data_time_max + padding
            self._view_window_size = self._view_time_max - self._view_time_min
            self._sync_time_range()
            self._time_header.set_time_range(self._view_time_min, self._view_time_max)
    
    def _sync_time_range(self) -> None:
        """Synchronize time range across all rows."""
        for row in self._rows.values():
            row.set_time_range(self._view_time_min, self._view_time_max)
    
    def _set_cursor(self, cursor_time: Optional[float]) -> None:
        """Set cursor position on all rows and header."""
        self._time_header.set_cursor(cursor_time)
        for row in self._rows.values():
            row.set_cursor(cursor_time)
    
    def _on_run(self):
        """Start playback."""
        if not self._rows or self._data_time_max <= 0:
            logger.warning("No data to play back")
            return
        
        self._is_running = True
        
        # Start from 0 if at end or before start
        if self._playback_position >= self._data_time_max or self._playback_position < 0:
            self._playback_position = 0.0
        
        self._view_time_min = self._playback_position
        self._view_time_max = self._playback_position + self._view_window_size
        
        self._control_panel.set_running(True)
        self._playback_timer.start()
        logger.info(f"Playback started at {self._playback_position:.3f}s")
    
    def _on_stop(self):
        """Stop playback."""
        self._is_running = False
        self._playback_timer.stop()
        self._control_panel.set_running(False)
        self._set_cursor(None)
        logger.info("Playback stopped")
    
    def _on_reset(self):
        """Reset playback and clear data."""
        self._on_stop()
        self.clear_data()
        logger.info("State diagram reset")
    
    def _on_speed_changed(self, speed: float):
        """Handle playback speed change."""
        self._playback_speed = speed
    
    def _on_playback_tick(self):
        """Called by timer during playback."""
        if not self._is_running:
            return
        
        time_step = (self.PLAYBACK_INTERVAL_MS / 1000.0) * self._playback_speed
        self._playback_position += time_step
        
        if self._playback_position >= self._data_time_max:
            self._playback_position = self._data_time_max
            self._on_stop()
            return
        
        cursor_offset = self._view_window_size * 0.2
        self._view_time_min = self._playback_position - cursor_offset
        self._view_time_max = self._view_time_min + self._view_window_size
        
        # Clamp to start at 0
        if self._view_time_min < 0:
            self._view_time_min = 0
            self._view_time_max = self._view_window_size
        
        self._sync_time_range()
        self._time_header.set_time_range(self._view_time_min, self._view_time_max)
        self._set_cursor(self._playback_position)
        
        # Show duration (data_time_max is already relative, starting from 0)
        self._control_panel.set_playback_time(
            self._playback_position,
            self._data_time_max
        )
    
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
        self._all_signal_data.clear()
        self._time_offset = 0.0
        self._time_offset_set = False
        self._data_time_min = 0.0
        self._data_time_max = 0.0
        self._view_time_min = 0.0
        self._view_time_max = 10.0
        self._playback_position = 0.0
        self._time_header.set_time_range(0, 10)
        self._time_header.set_cursor(None)
        self._sync_time_range()
    
    def clear(self) -> None:
        """Clear everything including signal selection."""
        self._on_stop()
        self._active_signals.clear()
        
        for row in self._rows.values():
            self._rows_layout.removeWidget(row)
            row.deleteLater()
        
        self._rows.clear()
        self._last_values.clear()
        self._all_signal_data.clear()
        self._time_offset = 0.0
        self._time_offset_set = False
        self._data_time_min = 0.0
        self._data_time_max = 0.0
        self._view_time_min = 0.0
        self._view_time_max = 10.0
        self._playback_position = 0.0
        
        self._empty_label.setVisible(True)
        self._control_panel.set_signals([])
        self._time_header.set_time_range(0, 10)
        self._time_header.set_cursor(None)
