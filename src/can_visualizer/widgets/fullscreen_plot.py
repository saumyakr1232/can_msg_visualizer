"""
Fullscreen Plot Window.

Provides a detachable, fullscreen-capable plot window that
mirrors the main plot with synchronized signal selection.
"""

from typing import Optional
import numpy as np
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QCheckBox,
    QLabel,
)
from PySide6.QtGui import QKeySequence, QShortcut, QFont
import pyqtgraph as pg

from ..core.models import DecodedSignal
from ..utils.logging_config import get_logger

logger = get_logger("fullscreen_plot")


class FullscreenPlotWindow(QMainWindow):
    """
    Detachable fullscreen plot window.

    Features:
    - Mirrors main plot signal selection
    - Independent zoom/pan
    - Continues updating during streaming
    - Keyboard shortcuts (Escape to exit, F to toggle fullscreen)
    """

    closed = Signal()

    # Same color palette as main plot for consistency
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

    MAX_POINTS = 100_000

    def __init__(self, parent=None):
        super().__init__(parent)

        self._signal_data: dict[str, tuple[list[float], list[float]]] = {}
        self._plot_items: dict[str, pg.PlotDataItem] = {}
        self._selected_signals: list[str] = []
        self._custom_colors: dict[str, str] = {}  # signal_name -> hex color

        # Crosshair and tooltip components
        self._vline: Optional[pg.InfiniteLine] = None
        self._hline: Optional[pg.InfiniteLine] = None
        self._tooltip: Optional[pg.TextItem] = None
        self._crosshair_enabled = True

        self._setup_ui()
        self._setup_shortcuts()
        self._setup_crosshair()

    def _setup_ui(self) -> None:
        """Initialize UI components."""
        self.setWindowTitle("CAN Signal Plot - Fullscreen")
        self.setMinimumSize(800, 600)

        # Dark theme
        self.setStyleSheet("""
            QMainWindow {
                background: #1E1E1E;
            }
            QWidget {
                background: #1E1E1E;
                color: #E0E0E0;
            }
            QPushButton {
                background: #3D3D3D;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 6px 12px;
                color: #E0E0E0;
            }
            QPushButton:hover {
                background: #4D4D4D;
            }
            QPushButton:pressed {
                background: #2D2D2D;
            }
            QCheckBox {
                color: #E0E0E0;
            }
            QLabel {
                color: #888;
            }
        """)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        # Grid toggle
        self._grid_checkbox = QCheckBox("Grid")
        self._grid_checkbox.setChecked(True)
        self._grid_checkbox.toggled.connect(self._on_grid_toggled)
        toolbar.addWidget(self._grid_checkbox)

        # Legend toggle
        self._legend_checkbox = QCheckBox("Legend")
        self._legend_checkbox.setChecked(True)
        self._legend_checkbox.toggled.connect(self._on_legend_toggled)
        toolbar.addWidget(self._legend_checkbox)

        # Crosshair toggle
        self._crosshair_checkbox = QCheckBox("Crosshair")
        self._crosshair_checkbox.setChecked(True)
        self._crosshair_checkbox.toggled.connect(self._on_crosshair_toggled)
        toolbar.addWidget(self._crosshair_checkbox)

        # Auto-range
        self._auto_range_btn = QPushButton("📐 Auto Range")
        self._auto_range_btn.clicked.connect(self._on_auto_range)
        toolbar.addWidget(self._auto_range_btn)

        # Fullscreen toggle
        self._fullscreen_btn = QPushButton("⛶ Toggle Fullscreen")
        self._fullscreen_btn.clicked.connect(self._toggle_fullscreen)
        toolbar.addWidget(self._fullscreen_btn)

        toolbar.addStretch()

        # Point count
        self._point_label = QLabel("0 points")
        toolbar.addWidget(self._point_label)

        # Close button
        self._close_btn = QPushButton("✕ Close")
        self._close_btn.clicked.connect(self.close)
        toolbar.addWidget(self._close_btn)

        layout.addLayout(toolbar)

        # Plot widget
        self._plot_widget = pg.PlotWidget()
        self._plot_widget.setBackground("#1E1E1E")
        self._plot_widget.showGrid(x=True, y=True, alpha=0.3)

        self._plot_widget.setLabel("bottom", "Time", units="s")
        self._plot_widget.setLabel("left", "Value")

        self._plot_widget.setMouseEnabled(x=True, y=True)
        self._plot_widget.enableAutoRange()

        self._legend = self._plot_widget.addLegend(offset=(10, 10))
        self._legend.setParentItem(self._plot_widget.graphicsItem())

        self._plot_widget.setClipToView(True)
        self._plot_widget.setDownsampling(auto=True, mode="peak")

        layout.addWidget(self._plot_widget)

        # Status bar
        status = QHBoxLayout()
        self._status_label = QLabel("Press F for fullscreen, Escape to close")
        self._status_label.setStyleSheet("color: #666; font-size: 11px;")
        status.addWidget(self._status_label)
        status.addStretch()

        self._signal_label = QLabel("")
        self._signal_label.setStyleSheet("color: #888; font-size: 11px;")
        status.addWidget(self._signal_label)

        layout.addLayout(status)

    def _setup_shortcuts(self) -> None:
        """Setup keyboard shortcuts."""
        # Escape to close
        escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        escape.activated.connect(self.close)

        # F to toggle fullscreen
        fullscreen = QShortcut(QKeySequence(Qt.Key.Key_F), self)
        fullscreen.activated.connect(self._toggle_fullscreen)

        # R for auto-range
        auto_range = QShortcut(QKeySequence(Qt.Key.Key_R), self)
        auto_range.activated.connect(self._on_auto_range)

    def set_selected_signals(self, signal_names: list[str]) -> None:
        """Update displayed signals."""
        self._selected_signals = signal_names
        self._update_plot()

        self._signal_label.setText(f"{len(signal_names)} signals selected")

    @Slot(list)
    def add_signals(self, signals: list[DecodedSignal]) -> None:
        """Add new signal data during streaming."""
        for signal in signals:
            full_name = signal.full_name

            if full_name not in self._signal_data:
                self._signal_data[full_name] = ([], [])

            timestamps, values = self._signal_data[full_name]
            timestamps.append(signal.timestamp)
            values.append(signal.physical_value)

        if any(sig.full_name in self._selected_signals for sig in signals):
            self._update_plot()

    def load_signal_data(
        self, data: dict[str, tuple[list[float], list[float]]]
    ) -> None:
        """Load pre-computed signal data."""
        for name, (timestamps, values) in data.items():
            if name not in self._signal_data:
                self._signal_data[name] = ([], [])

            self._signal_data[name][0].extend(timestamps)
            self._signal_data[name][1].extend(values)

        self._update_plot()

    def _update_plot(self) -> None:
        """Refresh plot display."""
        # Remove unselected
        for name in list(self._plot_items.keys()):
            if name not in self._selected_signals:
                item = self._plot_items.pop(name)
                self._plot_widget.removeItem(item)

        total_points = 0

        for i, name in enumerate(self._selected_signals):
            if name not in self._signal_data:
                continue

            timestamps, values = self._signal_data[name]
            if not timestamps:
                continue

            x = np.array(timestamps)
            y = np.array(values)

            if len(x) > self.MAX_POINTS:
                factor = len(x) // self.MAX_POINTS
                x = x[::factor]
                y = y[::factor]

            total_points += len(x)
            color = self._custom_colors.get(name) or self.COLORS[i % len(self.COLORS)]

            if name in self._plot_items:
                self._plot_items[name].setData(x, y)
                self._plot_items[name].setPen(pg.mkPen(color=color, width=1.5))
            else:
                pen = pg.mkPen(color=color, width=1.5)
                item = self._plot_widget.plot(
                    x,
                    y,
                    pen=pen,
                    name=name.split(".")[-1],
                )
                self._plot_items[name] = item

        self._point_label.setText(f"{total_points:,} points")

    def clear(self) -> None:
        """Clear all data."""
        for item in self._plot_items.values():
            self._plot_widget.removeItem(item)

        self._plot_items.clear()
        self._signal_data.clear()
        self._point_label.setText("0 points")

    def sync_data(self, data: dict[str, tuple[list[float], list[float]]]) -> None:
        """Sync data from main plot."""
        self._signal_data = {
            name: (list(ts), list(vs)) for name, (ts, vs) in data.items()
        }
        self._update_plot()

    def set_signal_color(self, signal_name: str, color: str) -> None:
        """
        Set custom color for a signal.

        Args:
            signal_name: Full signal name (Message.Signal)
            color: Hex color string, or empty string to reset to default
        """
        if color:
            self._custom_colors[signal_name] = color
        elif signal_name in self._custom_colors:
            del self._custom_colors[signal_name]
        self._update_plot()

    def _on_grid_toggled(self, checked: bool) -> None:
        """Toggle grid."""
        self._plot_widget.showGrid(x=checked, y=checked, alpha=0.3 if checked else 0)

    def _on_legend_toggled(self, checked: bool) -> None:
        """Toggle legend."""
        if checked:
            self._legend.show()
        else:
            self._legend.hide()

    def _on_auto_range(self) -> None:
        """Auto-range view."""
        self._plot_widget.autoRange()

    def _toggle_fullscreen(self) -> None:
        """Toggle fullscreen mode."""
        if self.isFullScreen():
            self.showNormal()
            self._fullscreen_btn.setText("⛶ Fullscreen")
        else:
            self.showFullScreen()
            self._fullscreen_btn.setText("⛶ Exit Fullscreen")

    def closeEvent(self, event) -> None:
        """Handle window close."""
        self.closed.emit()
        super().closeEvent(event)

    def _setup_crosshair(self) -> None:
        """Setup crosshair cursor and tooltip for hover information."""
        plot_item = self._plot_widget.getPlotItem()

        # Vertical crosshair line
        self._vline = pg.InfiniteLine(
            angle=90,
            movable=False,
            pen=pg.mkPen("#888888", width=1, style=Qt.PenStyle.DashLine),
        )
        self._vline.setZValue(1000)
        plot_item.addItem(self._vline, ignoreBounds=True)

        # Horizontal crosshair line
        self._hline = pg.InfiniteLine(
            angle=0,
            movable=False,
            pen=pg.mkPen("#888888", width=1, style=Qt.PenStyle.DashLine),
        )
        self._hline.setZValue(1000)
        plot_item.addItem(self._hline, ignoreBounds=True)

        # Tooltip text item
        self._tooltip = pg.TextItem(
            text="",
            color="#E0E0E0",
            fill=pg.mkBrush("#2D2D2D"),
            border=pg.mkPen("#555555"),
            anchor=(0, 1),
        )
        self._tooltip.setZValue(1001)
        self._tooltip.setFont(QFont("Consolas", 9))
        plot_item.addItem(self._tooltip, ignoreBounds=True)
        self._tooltip.hide()

        # Connect mouse move signal
        self._proxy = pg.SignalProxy(
            self._plot_widget.scene().sigMouseMoved,
            rateLimit=60,
            slot=self._on_mouse_moved,
        )
        self._plot_widget.scene().sigMouseMoved.connect(self._check_mouse_in_plot)

    def _on_mouse_moved(self, evt) -> None:
        """Handle mouse movement for crosshair and tooltip updates."""
        if not self._crosshair_enabled:
            return

        pos = evt[0]
        plot_item = self._plot_widget.getPlotItem()
        vb = plot_item.vb

        if not plot_item.sceneBoundingRect().contains(pos):
            self._hide_crosshair()
            return

        mouse_point = vb.mapSceneToView(pos)
        x_pos = mouse_point.x()
        y_pos = mouse_point.y()

        self._vline.setPos(x_pos)
        self._hline.setPos(y_pos)
        self._vline.show()
        self._hline.show()

        # Find closest data points
        tooltip_lines = [f"Time: {x_pos:.6f} s"]

        for name in self._selected_signals:
            if name not in self._signal_data:
                continue

            timestamps, values = self._signal_data[name]
            if not timestamps:
                continue

            x_arr = np.array(timestamps)
            y_arr = np.array(values)

            idx = np.searchsorted(x_arr, x_pos)

            if idx == 0:
                closest_idx = 0
            elif idx >= len(x_arr):
                closest_idx = len(x_arr) - 1
            else:
                if abs(x_arr[idx] - x_pos) < abs(x_arr[idx - 1] - x_pos):
                    closest_idx = idx
                else:
                    closest_idx = idx - 1

            signal_name = name.split(".")[-1]
            value = y_arr[closest_idx]
            timestamp = x_arr[closest_idx]

            dt = timestamp - x_pos
            if abs(dt) < 0.001:
                tooltip_lines.append(f"{signal_name}: {value:.4g}")
            else:
                tooltip_lines.append(f"{signal_name}: {value:.4g} (Δt={dt:+.4f}s)")

        if len(tooltip_lines) > 1:
            self._tooltip.setText("\n".join(tooltip_lines))

            view_range = vb.viewRange()
            x_range = view_range[0]
            y_range = view_range[1]

            x_offset = (x_range[1] - x_range[0]) * 0.02
            y_offset = (y_range[1] - y_range[0]) * 0.02

            if x_pos > (x_range[0] + x_range[1]) / 2:
                self._tooltip.setAnchor((1, 1))
                self._tooltip.setPos(x_pos - x_offset, y_pos + y_offset)
            else:
                self._tooltip.setAnchor((0, 1))
                self._tooltip.setPos(x_pos + x_offset, y_pos + y_offset)

            self._tooltip.show()
        else:
            self._tooltip.hide()

    def _check_mouse_in_plot(self, pos) -> None:
        """Hide crosshair when mouse leaves plot area."""
        plot_item = self._plot_widget.getPlotItem()
        if not plot_item.sceneBoundingRect().contains(pos):
            self._hide_crosshair()

    def _hide_crosshair(self) -> None:
        """Hide crosshair and tooltip."""
        if self._vline:
            self._vline.hide()
        if self._hline:
            self._hline.hide()
        if self._tooltip:
            self._tooltip.hide()

    def _on_crosshair_toggled(self, checked: bool) -> None:
        """Toggle crosshair and tooltip visibility."""
        self._crosshair_enabled = checked
        if not checked:
            self._hide_crosshair()
