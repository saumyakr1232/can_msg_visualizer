"""UI widgets for the CAN visualizer application."""

from .signal_browser import SignalBrowserWidget
from .log_table import LogTableWidget
from .plot_widget import PlotWidget
from .state_diagram import StateDiagramWidget
from .fullscreen_plot import FullscreenPlotWindow

__all__ = [
    "SignalBrowserWidget",
    "LogTableWidget",
    "PlotWidget",
    "StateDiagramWidget",
    "FullscreenPlotWindow",
]

