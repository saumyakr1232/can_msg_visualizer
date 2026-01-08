"""
State Diagram Visualization Widget.

Displays discrete signal values over time using a timeline/step style,
ideal for enum signals, mode flags, and state machines.
"""

from typing import Optional
import numpy as np
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QPushButton,
)
import pyqtgraph as pg

from ..core.models import DecodedSignal, SignalDefinition
from ..utils.logging_config import get_logger

logger = get_logger("state_diagram")


class StateDiagramWidget(QWidget):
    """
    State diagram visualization for discrete CAN signals.
    
    Shows signal values as horizontal bars with state labels,
    perfect for visualizing:
    - Enum signals (gear position, vehicle mode)
    - Boolean flags
    - State machine transitions
    
    Features:
    - Step/timeline rendering
    - State labels from DBC choices
    - Color-coded states
    - Zoom and pan
    - Live streaming updates
    """
    
    # Color palette for states
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
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._signal_data: dict[str, tuple[list[float], list[float]]] = {}
        self._signal_defs: dict[str, SignalDefinition] = {}
        self._current_signal: Optional[str] = None
        
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """Initialize UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        
        # Signal selector
        toolbar.addWidget(QLabel("Signal:"))
        self._signal_combo = QComboBox()
        self._signal_combo.setMinimumWidth(200)
        self._signal_combo.currentTextChanged.connect(self._on_signal_selected)
        toolbar.addWidget(self._signal_combo)
        
        # Auto-range button
        self._auto_range_btn = QPushButton("📐 Auto Range")
        self._auto_range_btn.clicked.connect(self._on_auto_range)
        toolbar.addWidget(self._auto_range_btn)
        
        # Clear button
        self._clear_btn = QPushButton("🗑️ Clear")
        self._clear_btn.clicked.connect(self.clear)
        toolbar.addWidget(self._clear_btn)
        
        toolbar.addStretch()
        
        # State info label
        self._info_label = QLabel("")
        self._info_label.setStyleSheet("color: #888; font-size: 11px;")
        toolbar.addWidget(self._info_label)
        
        layout.addLayout(toolbar)
        
        # Plot widget
        self._plot_widget = pg.PlotWidget()
        self._plot_widget.setBackground('#1E1E1E')
        self._plot_widget.showGrid(x=True, y=False, alpha=0.3)
        
        # Configure axes
        self._plot_widget.setLabel('bottom', 'Time', units='s')
        self._plot_widget.setLabel('left', 'State')
        
        # Enable interaction
        self._plot_widget.setMouseEnabled(x=True, y=True)
        self._plot_widget.enableAutoRange()
        
        layout.addWidget(self._plot_widget)
        
        # State legend area
        self._legend_label = QLabel("")
        self._legend_label.setWordWrap(True)
        self._legend_label.setStyleSheet(
            "background: #2D2D2D; padding: 8px; border-radius: 4px; font-size: 11px;"
        )
        layout.addWidget(self._legend_label)
    
    def set_signal_definitions(self, definitions: dict[str, SignalDefinition]) -> None:
        """
        Set available signal definitions from DBC.
        
        Filters to show only enum/discrete signals in the combo box.
        
        Args:
            definitions: Dict mapping full signal name to definition
        """
        self._signal_defs = definitions
        
        # Filter to enum signals preferentially
        self._signal_combo.clear()
        
        # First add enum signals
        enum_signals = [
            name for name, sig_def in definitions.items()
            if sig_def.is_enum
        ]
        
        # Then add integer signals (potential discrete)
        int_signals = [
            name for name, sig_def in definitions.items()
            if not sig_def.is_enum and sig_def.length <= 8
        ]
        
        all_signals = sorted(enum_signals) + sorted(int_signals)
        
        for name in all_signals:
            self._signal_combo.addItem(name)
        
        logger.debug(
            f"State diagram: {len(enum_signals)} enum signals, "
            f"{len(int_signals)} integer signals"
        )
    
    @Slot(list)
    def add_signals(self, signals: list[DecodedSignal]) -> None:
        """
        Add new decoded signals to the data.
        
        Only stores data for signals that might be discrete.
        """
        for signal in signals:
            full_name = signal.full_name
            
            if full_name not in self._signal_data:
                self._signal_data[full_name] = ([], [])
            
            timestamps, values = self._signal_data[full_name]
            timestamps.append(signal.timestamp)
            values.append(signal.physical_value)
        
        # Update if current signal received data
        if self._current_signal and any(
            sig.full_name == self._current_signal for sig in signals
        ):
            self._update_plot()
    
    def load_signal_data(
        self,
        data: dict[str, tuple[list[float], list[float]]]
    ) -> None:
        """Load pre-computed signal data."""
        for name, (timestamps, values) in data.items():
            if name not in self._signal_data:
                self._signal_data[name] = ([], [])
            
            self._signal_data[name][0].extend(timestamps)
            self._signal_data[name][1].extend(values)
        
        self._update_plot()
    
    def _on_signal_selected(self, signal_name: str) -> None:
        """Handle signal selection from combo box."""
        self._current_signal = signal_name
        self._update_plot()
    
    def _update_plot(self) -> None:
        """Refresh the state diagram plot."""
        self._plot_widget.clear()
        
        if not self._current_signal:
            return
        
        if self._current_signal not in self._signal_data:
            self._info_label.setText("No data for selected signal")
            return
        
        timestamps, values = self._signal_data[self._current_signal]
        
        if not timestamps:
            self._info_label.setText("No data for selected signal")
            return
        
        # Convert to numpy
        x = np.array(timestamps)
        y = np.array(values)
        
        # Get unique states
        unique_values = sorted(set(y))
        value_to_index = {v: i for i, v in enumerate(unique_values)}
        
        # Get state labels from DBC if available
        sig_def = self._signal_defs.get(self._current_signal)
        state_labels = {}
        
        if sig_def and sig_def.choices:
            state_labels = {int(k): v for k, v in sig_def.choices.items()}
        
        # Create step plot data
        # For step plot, we need to duplicate points at transitions
        if len(x) > 1:
            x_step = np.zeros(len(x) * 2 - 1)
            y_step = np.zeros(len(x) * 2 - 1)
            
            for i in range(len(x)):
                x_step[i * 2] = x[i]
                y_step[i * 2] = value_to_index[y[i]]
                
                if i < len(x) - 1:
                    x_step[i * 2 + 1] = x[i + 1]
                    y_step[i * 2 + 1] = value_to_index[y[i]]
        else:
            x_step = x
            y_step = np.array([value_to_index[v] for v in y])
        
        # Plot the step function
        pen = pg.mkPen(color='#4ECDC4', width=2)
        self._plot_widget.plot(x_step, y_step, pen=pen, stepMode='left')
        
        # Add colored regions for each state
        for i, val in enumerate(unique_values):
            mask = y == val
            if not np.any(mask):
                continue
            
            color = self.STATE_COLORS[i % len(self.STATE_COLORS)]
            
            # Find continuous regions
            indices = np.where(mask)[0]
            if len(indices) == 0:
                continue
            
            # Draw scatter points at state values
            scatter_x = x[mask]
            scatter_y = np.full(len(scatter_x), i)
            
            brush = pg.mkBrush(color=color)
            scatter = pg.ScatterPlotItem(
                x=scatter_x, y=scatter_y,
                size=8, brush=brush, pen=None
            )
            self._plot_widget.addItem(scatter)
        
        # Set Y axis ticks to state labels
        y_axis = self._plot_widget.getAxis('left')
        ticks = []
        
        for val in unique_values:
            idx = value_to_index[val]
            label = state_labels.get(int(val), f"{val:.0f}")
            ticks.append((idx, label))
        
        y_axis.setTicks([ticks])
        
        # Update info
        unique_count = len(unique_values)
        transition_count = np.sum(np.diff(y) != 0)
        self._info_label.setText(
            f"{unique_count} states, {transition_count} transitions, {len(x)} samples"
        )
        
        # Update legend
        legend_parts = []
        for i, val in enumerate(unique_values):
            color = self.STATE_COLORS[i % len(self.STATE_COLORS)]
            label = state_labels.get(int(val), f"{val:.0f}")
            legend_parts.append(
                f'<span style="color:{color}">■</span> {label}'
            )
        
        self._legend_label.setText(" &nbsp;&nbsp; ".join(legend_parts))
    
    def _on_auto_range(self) -> None:
        """Reset view to show all data."""
        self._plot_widget.autoRange()
    
    def clear(self) -> None:
        """Clear all data and plot."""
        self._signal_data.clear()
        self._plot_widget.clear()
        self._info_label.setText("")
        self._legend_label.setText("")
    
    def set_current_signal(self, signal_name: str) -> None:
        """Programmatically set the displayed signal."""
        idx = self._signal_combo.findText(signal_name)
        if idx >= 0:
            self._signal_combo.setCurrentIndex(idx)
    
    @property
    def available_signals(self) -> list[str]:
        """Get list of signals with data."""
        return list(self._signal_data.keys())

