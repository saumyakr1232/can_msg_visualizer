"""
Interactive Signal Plotting Widget using pyqtgraph.

Provides high-performance real-time plotting for CAN signals
with zoom, pan, and multiple signal overlay support.
"""

import time
from typing import Optional
import numpy as np
from PySide6.QtCore import Qt, Signal, Slot, QTimer
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QCheckBox,
    QLabel,
    QMenu,
    QColorDialog,
)
from PySide6.QtGui import QFont, QColor
import pyqtgraph as pg

from ..core.models import DecodedSignal
from ..core.data_store import DataStore
from ..utils.logging_config import get_logger

logger = get_logger("plot")


# Configure pyqtgraph for performance
pg.setConfigOptions(
    antialias=False,  # Faster rendering
    useOpenGL=False,  # More compatible
    enableExperimental=False,
)


class PlotWidget(QWidget):
    """
    Interactive signal plotting widget.

    Features:
    - Multiple signal overlay with distinct colors
    - Real-time streaming updates from DataStore
    - Zoom, pan, and auto-range
    - Downsampling for large datasets
    - Grid and legend toggle
    - Point capping for performance

    Design decisions:
    - pyqtgraph for performance with large datasets
    - Data pulled from DataStore on demand
    - Only maintains buffer for SELECTED signals to save memory
    """

    # Signal for fullscreen request
    fullscreen_requested = Signal()

    # Color palette for signals (distinct, colorblind-friendly)
    COLORS = [
        "#E63946",  # Red
        "#2A9D8F",  # Teal
        "#E9C46A",  # Yellow
        "#264653",  # Dark blue
        "#F4A261",  # Orange
        "#9B5DE5",  # Purple
        "#00BBF9",  # Cyan
        "#00F5D4",  # Mint
        "#F15BB5",  # Pink
        "#FEE440",  # Bright yellow
        "#9EF01A",  # Lime
        "#4CC9F0",  # Light blue
    ]

    # Maximum points per signal before downsampling
    MAX_POINTS = 100_000

    def __init__(self, data_store: DataStore, parent=None):
        super().__init__(parent)

        self._data_store = data_store

        # Storage for currently selected signals only
        # Dict[signal_name, tuple[list[timestamps], list[values]]]
        self._signal_data: dict[str, tuple[list[float], list[float]]] = {}

        # Track last loaded timestamp per signal for incremental updates
        # Dict[signal_name, float]
        self._last_loaded_ts: dict[str, float] = {}

        # Time offset for elapsed time display (first timestamp = 0)
        self._time_offset: Optional[float] = None

        self._plot_items: dict[str, pg.PlotDataItem] = {}
        self._selected_signals: list[str] = []
        self._custom_colors: dict[str, str] = {}  # signal_name -> hex color

        # Crosshair and tooltip components
        self._vline: Optional[pg.InfiniteLine] = None
        self._hline: Optional[pg.InfiniteLine] = None
        self._tooltip: Optional[pg.TextItem] = None
        self._crosshair_enabled = True

        # Throttling for plot updates during streaming
        self._last_plot_update = 0.0
        self._plot_update_pending = False
        self._update_timer = QTimer(self)
        self._update_timer.setSingleShot(True)
        self._update_timer.timeout.connect(self._do_deferred_update)

        # Auto-update timer for streaming
        self._auto_update_timer = QTimer(self)
        self._auto_update_timer.setInterval(200)  # 5fps update check
        self._auto_update_timer.timeout.connect(self._check_for_updates)
        self._auto_update_timer.start()

        self._setup_ui()
        self._setup_crosshair()
        self._setup_legend_context_menu()

    def _setup_ui(self) -> None:
        """Initialize UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
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

        # Crosshair/tooltip toggle
        self._crosshair_checkbox = QCheckBox("Crosshair")
        self._crosshair_checkbox.setChecked(True)
        self._crosshair_checkbox.toggled.connect(self._on_crosshair_toggled)
        toolbar.addWidget(self._crosshair_checkbox)

        # Auto-range button
        self._auto_range_btn = QPushButton("📐 Auto Range")
        self._auto_range_btn.clicked.connect(self._on_auto_range)
        toolbar.addWidget(self._auto_range_btn)

        # Fullscreen button
        self._fullscreen_btn = QPushButton("⛶ Fullscreen")
        self._fullscreen_btn.clicked.connect(self.fullscreen_requested.emit)
        toolbar.addWidget(self._fullscreen_btn)

        # Clear plot button
        self._clear_btn = QPushButton("🗑️ Clear")
        self._clear_btn.clicked.connect(self.clear_plot)
        toolbar.addWidget(self._clear_btn)

        toolbar.addStretch()

        # Point count indicator
        self._point_label = QLabel("0 points")
        self._point_label.setStyleSheet("color: #666; font-size: 11px;")
        toolbar.addWidget(self._point_label)

        layout.addLayout(toolbar)

        # Plot widget
        self._plot_widget = pg.PlotWidget()
        self._plot_widget.setBackground("#1E1E1E")
        self._plot_widget.showGrid(x=True, y=True, alpha=0.3)

        # Configure axes
        self._plot_widget.setLabel("bottom", "Elapsed Time", units="s")
        self._plot_widget.setLabel("left", "Value")

        # Enable mouse interaction
        self._plot_widget.setMouseEnabled(x=True, y=True)
        self._plot_widget.enableAutoRange()

        # Add legend
        self._legend = self._plot_widget.addLegend(offset=(10, 10))
        self._legend.setParentItem(self._plot_widget.graphicsItem())

        # Configure for performance
        self._plot_widget.setClipToView(True)
        self._plot_widget.setDownsampling(auto=True, mode="peak")

        layout.addWidget(self._plot_widget)

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
            anchor=(0, 1),  # Anchor at bottom-left
        )
        self._tooltip.setZValue(1001)
        self._tooltip.setFont(QFont("Consolas", 9))
        plot_item.addItem(self._tooltip, ignoreBounds=True)
        self._tooltip.hide()

        # Connect mouse move signal using SignalProxy for efficiency
        self._proxy = pg.SignalProxy(
            self._plot_widget.scene().sigMouseMoved,
            rateLimit=60,  # Limit updates to 60 fps
            slot=self._on_mouse_moved,
        )

        # Hide crosshair when mouse leaves
        self._plot_widget.scene().sigMouseMoved.connect(self._check_mouse_in_plot)

    def _setup_legend_context_menu(self) -> None:
        """Setup right-click context menu on legend items."""
        self._context_menu_signal: Optional[str] = None
        self._plot_widget.scene().sigMouseClicked.connect(self._on_scene_clicked)

    def _on_scene_clicked(self, evt) -> None:
        """Handle mouse clicks on the scene to detect legend or plot curve clicks."""
        if evt.button() != Qt.MouseButton.RightButton:
            return

        clicked_items = self._plot_widget.scene().items(evt.scenePos())

        for item in clicked_items:
            # Legend Item Check
            if hasattr(item, "parentItem") and item.parentItem() == self._legend:
                signal_name = self._find_signal_from_legend_item(item)
                if signal_name:
                    self._show_color_context_menu(evt.screenPos(), signal_name)
                    evt.accept()
                    return

            # Legend Sample Check
            parent = item.parentItem() if hasattr(item, "parentItem") else None
            if (
                parent
                and hasattr(parent, "parentItem")
                and parent.parentItem() == self._legend
            ):
                signal_name = self._find_signal_from_legend_item(parent)
                if signal_name:
                    self._show_color_context_menu(evt.screenPos(), signal_name)
                    evt.accept()
                    return

            # Plot Curve Check
            signal_name = self._find_signal_from_plot_item(item)
            if signal_name:
                self._show_color_context_menu(evt.screenPos(), signal_name)
                evt.accept()
                return

    def _find_signal_from_legend_item(self, item) -> Optional[str]:
        """Find the signal name corresponding to a legend item."""
        for sample, label in self._legend.items:
            if item == sample or item == label:
                short_name = label.text
                for full_name in self._selected_signals:
                    if full_name.split(".")[-1] == short_name:
                        return full_name
        return None

    def _find_signal_from_plot_item(self, item) -> Optional[str]:
        """Find the signal name corresponding to a clicked plot curve."""
        for signal_name, plot_item in self._plot_items.items():
            if item == plot_item:
                return signal_name
            if hasattr(plot_item, "curve") and item == plot_item.curve:
                return signal_name
            if hasattr(item, "parentItem") and item.parentItem() == plot_item:
                return signal_name
        return None

    def _show_color_context_menu(self, screen_pos, signal_name: str) -> None:
        """Show context menu for signal color customization."""
        self._context_menu_signal = signal_name

        menu = QMenu(self)
        set_color_action = menu.addAction("🎨 Set Color...")
        set_color_action.triggered.connect(self._on_set_color)

        if signal_name in self._custom_colors:
            menu.addSeparator()
            reset_action = menu.addAction("↩️ Reset to Default")
            reset_action.triggered.connect(self._on_reset_color)

        menu.exec(screen_pos.toPoint())

    def _on_set_color(self) -> None:
        """Open color dialog to set custom signal color."""
        if not self._context_menu_signal:
            return

        signal_name = self._context_menu_signal
        if signal_name in self._custom_colors:
            initial_color = QColor(self._custom_colors[signal_name])
        else:
            signal_idx = self._selected_signals.index(signal_name)
            initial_color = QColor(self.COLORS[signal_idx % len(self.COLORS)])

        color = QColorDialog.getColor(
            initial_color, self, f"Select Color for {signal_name.split('.')[-1]}"
        )

        if color.isValid():
            self._custom_colors[signal_name] = color.name()
            self._update_plot()

    def _on_reset_color(self) -> None:
        """Reset signal to default palette color."""
        if not self._context_menu_signal:
            return

        signal_name = self._context_menu_signal
        if signal_name in self._custom_colors:
            del self._custom_colors[signal_name]
            self._update_plot()

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

        tooltip_lines = [f"Time: {x_pos:.6f} s"]

        for name in self._selected_signals:
            if name not in self._signal_data:
                continue

            timestamps, values = self._signal_data[name]
            if not timestamps:
                continue

            x_arr = np.array(timestamps)
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

            value = values[closest_idx]
            timestamp = x_arr[closest_idx]
            signal_name = name.split(".")[-1]

            dt = timestamp - x_pos
            if abs(dt) < 0.001:
                tooltip_lines.append(f"{signal_name}: {value:.4g}")
            else:
                tooltip_lines.append(f"{signal_name}: {value:.4g} (Δt={dt:+.4f}s)")

        if len(tooltip_lines) > 1:
            self._tooltip.setText("\n".join(tooltip_lines))
            # Tooltip positioning logic...
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

    def set_selected_signals(self, signal_names: list[str]) -> None:
        """
        Update which signals are displayed.
        Refreshes data from DataStore for newly selected signals.
        """
        self._selected_signals = signal_names

        # Cleanup deselected signals from cache
        current_signals = set(self._signal_data.keys())
        new_signals = set(signal_names)

        for name in current_signals - new_signals:
            del self._signal_data[name]
            if name in self._last_loaded_ts:
                del self._last_loaded_ts[name]

        # Load data for new signals
        for name in new_signals - current_signals:
            self._load_data_for_signal(name)

        self._update_plot()

    def _load_data_for_signal(self, full_name: str) -> None:
        """Load initial or missing data for a signal from DataStore."""

        signal_name = full_name.split(".")[-1]

        timestamps, values = self._data_store.get_signal_data(signal_name)

        # Set time offset on first data load (first timestamp becomes 0)
        if timestamps and self._time_offset is None:
            self._time_offset = timestamps[0]

        self._signal_data[full_name] = (timestamps, values)
        if timestamps:
            self._last_loaded_ts[full_name] = timestamps[-1]
        else:
            self._last_loaded_ts[full_name] = 0.0

    @Slot()
    def new_data(self) -> None:
        """
        Slot called when new data is available in DataStore.
        Triggers deferred update.
        """
        # We don't fetch immediately, just ensure update loop catches it
        pass

    def _check_for_updates(self) -> None:
        """
        Periodically check for fresh data for *selected* signals.
        """
        if not self._selected_signals:
            return

        updated = False

        for full_name in self._selected_signals:
            if full_name not in self._last_loaded_ts:
                # Should have been initialized in set_selected_signals, but safe guard
                self._load_data_for_signal(full_name)
                updated = True
                continue

            last_ts = self._last_loaded_ts[full_name]
            signal_name = full_name.split(".")[-1]

            # Fetch incremental
            new_ts, new_val = self._data_store.get_signal_data(
                signal_name, min_timestamp=last_ts
            )

            if new_ts:
                # Append to existing
                current_ts, current_val = self._signal_data[full_name]
                current_ts.extend(new_ts)
                current_val.extend(new_val)

                self._last_loaded_ts[full_name] = new_ts[-1]
                updated = True

        if updated:
            self._request_plot_update()

    def _request_plot_update(self) -> None:
        """Request a throttled plot update."""
        current_time = time.time()

        if current_time - self._last_plot_update < 0.1:
            if not self._plot_update_pending:
                self._plot_update_pending = True
                self._update_timer.start(100)
            return

        self._last_plot_update = current_time
        self._plot_update_pending = False
        self._update_plot()

    def _do_deferred_update(self) -> None:
        """Execute deferred plot update."""
        self._plot_update_pending = False
        self._last_plot_update = time.time()
        self._update_plot()

    def _update_plot(self) -> None:
        """Refresh plot with current data and selection."""
        # Cleanup plot items
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

            # Convert to elapsed time (subtract first timestamp offset)
            if self._time_offset is not None:
                x = x - self._time_offset

            # Downsample if needed (already handled by pyqtgraph auto downsample, but we can pre-clip)
            # Actually pg downsampling usually handles this well.
            # If we manually downsample, we save memory/transfer to GPU.
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

    def clear_plot(self) -> None:
        """Clear all plot data and items."""
        for item in self._plot_items.values():
            self._plot_widget.removeItem(item)

        self._plot_items.clear()
        self._signal_data.clear()
        self._last_loaded_ts.clear()
        self._time_offset = None  # Reset time offset
        self._point_label.setText("0 points")

    def clear_data_only(self) -> None:
        """Clear data but keep signal selection."""
        self._signal_data.clear()
        self._last_loaded_ts.clear()
        self._time_offset = None  # Reset time offset
        self._update_plot()

    def _on_grid_toggled(self, checked: bool) -> None:
        """Toggle grid visibility."""
        self._plot_widget.showGrid(x=checked, y=checked, alpha=0.3 if checked else 0)

    def _on_legend_toggled(self, checked: bool) -> None:
        """Toggle legend visibility."""
        if checked:
            self._legend.show()
        else:
            self._legend.hide()

    def _on_auto_range(self) -> None:
        """Reset view to show all data."""
        self._plot_widget.autoRange()

    def get_plot_widget(self) -> pg.PlotWidget:
        """Get the underlying pyqtgraph widget for advanced use."""
        return self._plot_widget

    def get_view_range(self) -> tuple:
        """Get current X and Y view ranges."""
        return self._plot_widget.viewRange()

    def set_view_range(self, x_range: tuple, y_range: tuple) -> None:
        """Set view ranges for synchronized views."""
        self._plot_widget.setXRange(*x_range, padding=0)
        self._plot_widget.setYRange(*y_range, padding=0)

    @property
    def signal_names(self) -> list[str]:
        """Get list of available signal names with data."""
        return list(self._signal_data.keys())

    @property
    def total_points(self) -> int:
        """Get total data points across all signals."""
        return sum(len(v[0]) for v in self._signal_data.values())

    def set_signal_color(self, signal_name: str, color: str) -> None:
        """
        Set custom color for a signal (called externally).
        """
        if color:
            self._custom_colors[signal_name] = color
        elif signal_name in self._custom_colors:
            del self._custom_colors[signal_name]
        self._update_plot()

    def get_custom_colors(self) -> dict[str, str]:
        """Get all custom color assignments."""
        return self._custom_colors.copy()

    def update_theme(self, bg_color: str, fg_color: str) -> None:
        """
        Update colors for theme change.

        Args:
            bg_color: Background color hex string
            fg_color: Foreground color hex string
        """
        self._plot_widget.setBackground(bg_color)

        # Update axis colors
        axis_pen = pg.mkPen(color=fg_color)
        self._plot_widget.getPlotItem().getAxis("bottom").setPen(axis_pen)
        self._plot_widget.getPlotItem().getAxis("bottom").setTextPen(axis_pen)
        self._plot_widget.getPlotItem().getAxis("left").setPen(axis_pen)
        self._plot_widget.getPlotItem().getAxis("left").setTextPen(axis_pen)

        # Update crosshair colors
        if self._vline:
            crosshair_color = (
                "#888888"
                if bg_color.startswith("#1") or bg_color.startswith("#2")
                else "#666666"
            )
            self._vline.setPen(
                pg.mkPen(crosshair_color, width=1, style=Qt.PenStyle.DashLine)
            )
        if self._hline:
            crosshair_color = (
                "#888888"
                if bg_color.startswith("#1") or bg_color.startswith("#2")
                else "#666666"
            )
            self._hline.setPen(
                pg.mkPen(crosshair_color, width=1, style=Qt.PenStyle.DashLine)
            )
