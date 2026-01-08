"""
Interactive Signal Plotting Widget using pyqtgraph.

Provides high-performance real-time plotting for CAN signals
with zoom, pan, and multiple signal overlay support.
"""

import time
from typing import Optional
import numpy as np
from PySide6.QtCore import Qt, Signal, Slot, QPointF, QTimer
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QCheckBox,
    QLabel,
    QComboBox,
)
from PySide6.QtGui import QFont
import pyqtgraph as pg

from ..core.models import DecodedSignal
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
    - Real-time streaming updates
    - Zoom, pan, and auto-range
    - Downsampling for large datasets
    - Grid and legend toggle
    - Point capping for performance
    
    Design decisions:
    - pyqtgraph for performance with large datasets
    - Downsampling when zoomed out
    - Clip-to-view for efficient rendering
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
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._signal_data: dict[str, tuple[list[float], list[float]]] = {}
        self._plot_items: dict[str, pg.PlotDataItem] = {}
        self._selected_signals: list[str] = []
        
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
        
        self._setup_ui()
        self._setup_crosshair()
    
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
        self._plot_widget.setBackground('#1E1E1E')
        self._plot_widget.showGrid(x=True, y=True, alpha=0.3)
        
        # Configure axes
        self._plot_widget.setLabel('bottom', 'Time', units='s')
        self._plot_widget.setLabel('left', 'Value')
        
        # Enable mouse interaction
        self._plot_widget.setMouseEnabled(x=True, y=True)
        self._plot_widget.enableAutoRange()
        
        # Add legend
        self._legend = self._plot_widget.addLegend(offset=(10, 10))
        self._legend.setParentItem(self._plot_widget.graphicsItem())
        
        # Configure for performance
        self._plot_widget.setClipToView(True)
        self._plot_widget.setDownsampling(auto=True, mode='peak')
        
        layout.addWidget(self._plot_widget)
    
    def _setup_crosshair(self) -> None:
        """Setup crosshair cursor and tooltip for hover information."""
        plot_item = self._plot_widget.getPlotItem()
        
        # Vertical crosshair line
        self._vline = pg.InfiniteLine(
            angle=90, 
            movable=False, 
            pen=pg.mkPen('#888888', width=1, style=Qt.PenStyle.DashLine)
        )
        self._vline.setZValue(1000)
        plot_item.addItem(self._vline, ignoreBounds=True)
        
        # Horizontal crosshair line
        self._hline = pg.InfiniteLine(
            angle=0, 
            movable=False, 
            pen=pg.mkPen('#888888', width=1, style=Qt.PenStyle.DashLine)
        )
        self._hline.setZValue(1000)
        plot_item.addItem(self._hline, ignoreBounds=True)
        
        # Tooltip text item
        self._tooltip = pg.TextItem(
            text='',
            color='#E0E0E0',
            fill=pg.mkBrush('#2D2D2D'),
            border=pg.mkPen('#555555'),
            anchor=(0, 1),  # Anchor at bottom-left
        )
        self._tooltip.setZValue(1001)
        self._tooltip.setFont(QFont('Consolas', 9))
        plot_item.addItem(self._tooltip, ignoreBounds=True)
        self._tooltip.hide()
        
        # Connect mouse move signal using SignalProxy for efficiency
        self._proxy = pg.SignalProxy(
            self._plot_widget.scene().sigMouseMoved,
            rateLimit=60,  # Limit updates to 60 fps
            slot=self._on_mouse_moved
        )
        
        # Hide crosshair when mouse leaves
        self._plot_widget.scene().sigMouseMoved.connect(self._check_mouse_in_plot)
    
    def _on_mouse_moved(self, evt) -> None:
        """Handle mouse movement for crosshair and tooltip updates."""
        if not self._crosshair_enabled:
            return
        
        pos = evt[0]  # SignalProxy wraps in tuple
        plot_item = self._plot_widget.getPlotItem()
        vb = plot_item.vb
        
        # Check if mouse is within the plot area
        if not plot_item.sceneBoundingRect().contains(pos):
            self._hide_crosshair()
            return
        
        # Map to data coordinates
        mouse_point = vb.mapSceneToView(pos)
        x_pos = mouse_point.x()
        y_pos = mouse_point.y()
        
        # Update crosshair position
        self._vline.setPos(x_pos)
        self._hline.setPos(y_pos)
        self._vline.show()
        self._hline.show()
        
        # Find closest data points for all selected signals
        tooltip_lines = [f"Time: {x_pos:.6f} s"]
        
        for name in self._selected_signals:
            if name not in self._signal_data:
                continue
            
            timestamps, values = self._signal_data[name]
            if not timestamps:
                continue
            
            # Find closest point by timestamp
            x_arr = np.array(timestamps)
            y_arr = np.array(values)
            
            # Binary search for closest timestamp
            idx = np.searchsorted(x_arr, x_pos)
            
            # Check bounds and find closest
            if idx == 0:
                closest_idx = 0
            elif idx >= len(x_arr):
                closest_idx = len(x_arr) - 1
            else:
                # Compare distances to neighbors
                if abs(x_arr[idx] - x_pos) < abs(x_arr[idx - 1] - x_pos):
                    closest_idx = idx
                else:
                    closest_idx = idx - 1
            
            # Get the signal color for the tooltip
            signal_idx = self._selected_signals.index(name)
            color = self.COLORS[signal_idx % len(self.COLORS)]
            
            # Format signal value
            signal_name = name.split('.')[-1]
            value = y_arr[closest_idx]
            timestamp = x_arr[closest_idx]
            
            # Show value with delta time from cursor
            dt = timestamp - x_pos
            if abs(dt) < 0.001:
                tooltip_lines.append(f"{signal_name}: {value:.4g}")
            else:
                tooltip_lines.append(f"{signal_name}: {value:.4g} (Δt={dt:+.4f}s)")
        
        # Update tooltip
        if len(tooltip_lines) > 1:
            self._tooltip.setText('\n'.join(tooltip_lines))
            
            # Position tooltip near cursor but within view
            view_range = vb.viewRange()
            x_range = view_range[0]
            y_range = view_range[1]
            
            # Offset tooltip from cursor
            x_offset = (x_range[1] - x_range[0]) * 0.02
            y_offset = (y_range[1] - y_range[0]) * 0.02
            
            # Position to right of cursor, flip if near edge
            if x_pos > (x_range[0] + x_range[1]) / 2:
                self._tooltip.setAnchor((1, 1))  # Anchor at bottom-right
                self._tooltip.setPos(x_pos - x_offset, y_pos + y_offset)
            else:
                self._tooltip.setAnchor((0, 1))  # Anchor at bottom-left
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
        
        Args:
            signal_names: List of signal full names (Message.Signal)
        """
        self._selected_signals = signal_names
        self._update_plot()
    
    @Slot(list)
    def add_signals(self, signals: list[DecodedSignal]) -> None:
        """
        Add new decoded signals to the plot data.
        
        Called during streaming - accumulates data for plotting.
        Uses throttling to prevent UI blocking.
        """
        for signal in signals:
            full_name = signal.full_name
            
            if full_name not in self._signal_data:
                self._signal_data[full_name] = ([], [])
            
            timestamps, values = self._signal_data[full_name]
            timestamps.append(signal.timestamp)
            values.append(signal.physical_value)
        
        # Update plot if these signals are selected (with throttling)
        if any(sig.full_name in self._selected_signals for sig in signals):
            self._request_plot_update()
    
    def _request_plot_update(self) -> None:
        """Request a throttled plot update."""
        current_time = time.time()
        
        # Throttle updates to max 10 fps during streaming
        if current_time - self._last_plot_update < 0.1:
            # Schedule deferred update if not already pending
            if not self._plot_update_pending:
                self._plot_update_pending = True
                self._update_timer.start(100)  # 100ms delay
            return
        
        self._last_plot_update = current_time
        self._plot_update_pending = False
        self._update_plot()
    
    def _do_deferred_update(self) -> None:
        """Execute deferred plot update."""
        self._plot_update_pending = False
        self._last_plot_update = time.time()
        self._update_plot()
    
    def load_signal_data(
        self,
        data: dict[str, tuple[list[float], list[float]]]
    ) -> None:
        """
        Load pre-computed signal data (from cache).
        
        Args:
            data: Dict mapping signal name to (timestamps, values) tuples
        """
        for name, (timestamps, values) in data.items():
            if name not in self._signal_data:
                self._signal_data[name] = ([], [])
            
            self._signal_data[name][0].extend(timestamps)
            self._signal_data[name][1].extend(values)
        
        self._update_plot()
    
    def _update_plot(self) -> None:
        """Refresh plot with current data and selection."""
        # Remove unselected signals from plot
        for name in list(self._plot_items.keys()):
            if name not in self._selected_signals:
                item = self._plot_items.pop(name)
                self._plot_widget.removeItem(item)
        
        total_points = 0
        
        # Add/update selected signals
        for i, name in enumerate(self._selected_signals):
            if name not in self._signal_data:
                continue
            
            timestamps, values = self._signal_data[name]
            if not timestamps:
                continue
            
            # Convert to numpy arrays
            x = np.array(timestamps)
            y = np.array(values)
            
            # Downsample if needed
            if len(x) > self.MAX_POINTS:
                factor = len(x) // self.MAX_POINTS
                x = x[::factor]
                y = y[::factor]
            
            total_points += len(x)
            
            # Get color
            color = self.COLORS[i % len(self.COLORS)]
            
            # Update or create plot item
            if name in self._plot_items:
                self._plot_items[name].setData(x, y)
            else:
                pen = pg.mkPen(color=color, width=1.5)
                item = self._plot_widget.plot(
                    x, y,
                    pen=pen,
                    name=name.split('.')[-1],  # Just signal name in legend
                )
                self._plot_items[name] = item
        
        # Update point count
        self._point_label.setText(f"{total_points:,} points")
    
    def clear_plot(self) -> None:
        """Clear all plot data and items."""
        for item in self._plot_items.values():
            self._plot_widget.removeItem(item)
        
        self._plot_items.clear()
        self._signal_data.clear()
        self._point_label.setText("0 points")
        
        logger.debug("Plot cleared")
    
    def clear_data_only(self) -> None:
        """Clear data but keep signal selection."""
        self._signal_data.clear()
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

