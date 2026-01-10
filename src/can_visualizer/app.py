"""
Main Application Window for CAN Message Visualizer.

Integrates all widgets and coordinates:
- File loading
- Parse worker management
- Signal routing between components
- UI state management
"""

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Slot, QTimer
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QTabWidget,
    QFileDialog,
    QMenuBar,
    QMenu,
    QToolBar,
    QStatusBar,
    QLabel,
    QPushButton,
    QProgressBar,
    QMessageBox,
    QGroupBox,
    QFrame,
)
from PySide6.QtGui import QAction, QActionGroup, QKeySequence

from .core import DataStore, ThemeMode, get_theme_manager
from .core.decoder import DBCDecoder
from .core.models import ParseProgress, ParseState, DecodedSignal, SignalDefinition
from .workers.parse_worker import ParseWorker
from .widgets.signal_browser import SignalBrowserWidget
from .widgets.log_table import LogTableWidget
from .widgets.plot_widget import PlotWidget
from .widgets.state_diagram import StateDiagramWidget
from .widgets.fullscreen_plot import FullscreenPlotWindow
from .widgets.selected_signals import SelectedSignalsWidget
from .widgets.signal_selector_dialog import SignalSelectorDialog
from .utils.logging_config import get_logger

logger = get_logger("app")


class SignalPlotTab(QWidget):
    """Signal Plot tab with its own left panel for DBC browser."""

    def __init__(self, data_store: DataStore, parent=None):
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Main splitter
        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel - Signal Browser and Selected Signals
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.setSpacing(4)

        # Vertical splitter for browser and selected signals
        left_splitter = QSplitter(Qt.Orientation.Vertical)

        # DBC Signal Browser
        browser_group = QGroupBox("DBC Signals")
        browser_layout = QVBoxLayout(browser_group)
        browser_layout.setContentsMargins(4, 4, 4, 4)

        self.signal_browser = SignalBrowserWidget()
        browser_layout.addWidget(self.signal_browser)

        # Buttons for browser
        browser_buttons = QHBoxLayout()
        self._expand_btn = QPushButton("Expand All")
        self._expand_btn.clicked.connect(self.signal_browser.expand_all)
        self._collapse_btn = QPushButton("Collapse All")
        self._collapse_btn.clicked.connect(self.signal_browser.collapse_all)

        browser_buttons.addWidget(self._expand_btn)
        browser_buttons.addWidget(self._collapse_btn)
        browser_layout.addLayout(browser_buttons)

        left_splitter.addWidget(browser_group)

        # Selected Signals Panel
        selected_group = QGroupBox("Selected Signals")
        selected_layout = QVBoxLayout(selected_group)
        selected_layout.setContentsMargins(4, 4, 4, 4)

        self.selected_signals_widget = SelectedSignalsWidget()
        selected_layout.addWidget(self.selected_signals_widget)

        left_splitter.addWidget(selected_group)

        # Set initial splitter sizes (60% browser, 40% selected)
        left_splitter.setSizes([300, 200])

        left_layout.addWidget(left_splitter)

        left_panel.setMinimumWidth(250)
        left_panel.setMaximumWidth(450)
        self._splitter.addWidget(left_panel)

        # Right panel - Plot
        self.plot_widget = PlotWidget(data_store=data_store)
        self._splitter.addWidget(self.plot_widget)

        # Set splitter proportions
        self._splitter.setSizes([280, 700])

        layout.addWidget(self._splitter)


class MainWindow(QMainWindow):
    """
    Main application window.

    Layout:
    - Each tab has its own left panel with relevant controls:
      - Signal Plot: DBC browser + selected signals | plot
      - State Diagram: Timeline controls | timeline view
      - Message Log: Signal filters | log table
    - Bottom: Status bar with progress

    Responsibilities:
    - File loading dialogs
    - Worker thread lifecycle
    - Signal routing between widgets
    - Menu and toolbar actions
    """

    def __init__(self):
        super().__init__()

        # State
        self._dbc_path: Optional[Path] = None
        self._data_store: Optional[DataStore] = DataStore()
        self._trace_path: Optional[Path] = None
        self._decoder: Optional[DBCDecoder] = None
        self._parse_worker: Optional[ParseWorker] = None
        self._fullscreen_window: Optional[FullscreenPlotWindow] = None

        # Get theme manager
        self._theme_manager = get_theme_manager()

        self._setup_ui()
        self._setup_menu()
        self._setup_toolbar()
        self._setup_statusbar()
        self._connect_signals()

        # Connect theme manager
        self._theme_manager.theme_changed.connect(self._on_theme_changed)

        # Apply initial color scheme for title bar
        self._theme_manager.apply_color_scheme()

        # Apply initial theme to all widgets
        self._apply_theme_to_widgets()

        logger.info("Main window initialized")

    def _setup_ui(self) -> None:
        """Initialize the main UI layout."""
        self.setWindowTitle("CAN Message Visualizer")
        self.setMinimumSize(1200, 800)

        # Apply theme from ThemeManager
        self.setStyleSheet(self._theme_manager.get_stylesheet())

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        # Tabs - each tab has its own splitter layout
        self._tabs = QTabWidget()

        # Message Log Tab (with built-in filter panel)
        self._log_table = LogTableWidget(data_store=self._data_store)
        self._tabs.addTab(self._log_table, "📋 Message Log")

        # Signal Plot Tab (with DBC browser)
        self._signal_plot_tab = SignalPlotTab(data_store=self._data_store)
        self._tabs.addTab(self._signal_plot_tab, "📈 Signal Plot")

        # State Diagram Tab (with built-in control panel)
        self._state_diagram = StateDiagramWidget(data_store=self._data_store)
        self._tabs.addTab(self._state_diagram, "📊 State Diagram")

        main_layout.addWidget(self._tabs)

        # Shortcut references
        self._signal_browser = self._signal_plot_tab.signal_browser
        self._selected_signals_widget = self._signal_plot_tab.selected_signals_widget
        self._plot_widget = self._signal_plot_tab.plot_widget

    def _setup_menu(self) -> None:
        """Setup application menu bar."""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")

        self._load_dbc_action = QAction("Load &DBC File...", self)
        self._load_dbc_action.setShortcut(QKeySequence("Ctrl+D"))
        self._load_dbc_action.triggered.connect(self._on_load_dbc)
        file_menu.addAction(self._load_dbc_action)

        self._load_trace_action = QAction("Load &Trace File...", self)
        self._load_trace_action.setShortcut(QKeySequence("Ctrl+O"))
        self._load_trace_action.triggered.connect(self._on_load_trace)
        self._load_trace_action.setEnabled(False)
        file_menu.addAction(self._load_trace_action)

        file_menu.addSeparator()

        self._stop_action = QAction("&Stop Parsing", self)
        self._stop_action.setShortcut(QKeySequence("Ctrl+."))
        self._stop_action.triggered.connect(self._on_stop_parsing)
        self._stop_action.setEnabled(False)
        file_menu.addAction(self._stop_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # View menu
        view_menu = menubar.addMenu("&View")

        self._fullscreen_action = QAction("&Fullscreen Plot", self)
        self._fullscreen_action.setShortcut(QKeySequence("F11"))
        self._fullscreen_action.triggered.connect(self._on_open_fullscreen)
        view_menu.addAction(self._fullscreen_action)

        view_menu.addSeparator()

        # Theme submenu
        theme_menu = QMenu("&Theme", self)
        view_menu.addMenu(theme_menu)

        # Theme action group for radio behavior
        self._theme_action_group = QActionGroup(self)
        self._theme_action_group.setExclusive(True)

        self._theme_system_action = QAction("&System", self)
        self._theme_system_action.setCheckable(True)
        self._theme_system_action.triggered.connect(
            lambda: self._theme_manager.set_theme(ThemeMode.SYSTEM)
        )
        self._theme_action_group.addAction(self._theme_system_action)
        theme_menu.addAction(self._theme_system_action)

        self._theme_dark_action = QAction("&Dark", self)
        self._theme_dark_action.setCheckable(True)
        self._theme_dark_action.triggered.connect(
            lambda: self._theme_manager.set_theme(ThemeMode.DARK)
        )
        self._theme_action_group.addAction(self._theme_dark_action)
        theme_menu.addAction(self._theme_dark_action)

        self._theme_light_action = QAction("&Light", self)
        self._theme_light_action.setCheckable(True)
        self._theme_light_action.triggered.connect(
            lambda: self._theme_manager.set_theme(ThemeMode.LIGHT)
        )
        self._theme_action_group.addAction(self._theme_light_action)
        theme_menu.addAction(self._theme_light_action)

        # Set initial checked state based on current theme
        current_mode = self._theme_manager.current_mode
        if current_mode == ThemeMode.SYSTEM:
            self._theme_system_action.setChecked(True)
        elif current_mode == ThemeMode.DARK:
            self._theme_dark_action.setChecked(True)
        else:
            self._theme_light_action.setChecked(True)

        view_menu.addSeparator()

        self._clear_action = QAction("&Clear All Data", self)
        self._clear_action.setShortcut(QKeySequence("Ctrl+Shift+C"))
        self._clear_action.triggered.connect(self._on_clear_all)
        view_menu.addAction(self._clear_action)

    def _setup_toolbar(self) -> None:
        """Setup main toolbar."""
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        # File buttons
        self._dbc_btn = QPushButton("📁 Load DBC")
        self._dbc_btn.clicked.connect(self._on_load_dbc)
        toolbar.addWidget(self._dbc_btn)

        self._trace_btn = QPushButton("📂 Load Trace")
        self._trace_btn.clicked.connect(self._on_load_trace)
        self._trace_btn.setEnabled(False)
        toolbar.addWidget(self._trace_btn)

        toolbar.addSeparator()

        # Control buttons
        self._stop_btn = QPushButton("⏹ Stop")
        self._stop_btn.clicked.connect(self._on_stop_parsing)
        self._stop_btn.setEnabled(False)
        toolbar.addWidget(self._stop_btn)

        toolbar.addSeparator()

        # Current file labels
        self._dbc_label = QLabel("DBC: (none)")
        self._dbc_label.setStyleSheet("color: #888; padding: 0 8px;")
        toolbar.addWidget(self._dbc_label)

        self._trace_label = QLabel("Trace: (none)")
        self._trace_label.setStyleSheet("color: #888; padding: 0 8px;")
        toolbar.addWidget(self._trace_label)

    def _setup_statusbar(self) -> None:
        """Setup status bar with progress."""
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)

        # Status message
        self._status_message = QLabel("Ready")
        self._statusbar.addWidget(self._status_message, stretch=1)

        # Progress bar
        self._progress_bar = QProgressBar()
        self._progress_bar.setMaximumWidth(200)
        self._progress_bar.setVisible(False)
        self._statusbar.addPermanentWidget(self._progress_bar)

        # Stats labels
        self._msg_count_label = QLabel("Messages: 0")
        self._statusbar.addPermanentWidget(self._msg_count_label)

        self._rate_label = QLabel("Rate: 0 msg/s")
        self._statusbar.addPermanentWidget(self._rate_label)

    def _connect_signals(self) -> None:
        """Connect widget signals."""
        # Signal browser -> Selected signals panel and plot
        self._signal_browser.selection_changed.connect(
            self._on_signal_selection_changed
        )

        # Selected signals panel -> Signal browser (for removing signals)
        self._selected_signals_widget.signal_removed.connect(
            self._on_signal_removed_from_panel
        )
        self._selected_signals_widget.signals_cleared.connect(
            self._on_signals_cleared_from_panel
        )
        self._selected_signals_widget.selection_changed.connect(
            self._on_selected_panel_changed
        )
        self._selected_signals_widget.color_changed.connect(
            self._on_signal_color_changed
        )

        # Plot fullscreen request
        self._plot_widget.fullscreen_requested.connect(self._on_open_fullscreen)

        # State diagram -> Signal selector dialog
        self._state_diagram.add_signals_requested.connect(
            self._on_state_diagram_add_signals
        )

        # Message log filter -> Signal selector dialog
        self._log_table.add_filter_requested.connect(self._on_message_log_add_filter)

    # ================== File Loading ==================

    @Slot()
    def _on_load_dbc(self) -> None:
        """Handle DBC file loading."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select DBC File",
            "",
            "DBC Files (*.dbc);;All Files (*)",
        )

        if not file_path:
            return

        try:
            self._dbc_path = Path(file_path)
            self._decoder = DBCDecoder(self._dbc_path)

            # Update UI
            self._dbc_label.setText(f"DBC: {self._dbc_path.name}")
            self._load_trace_action.setEnabled(True)
            self._trace_btn.setEnabled(True)

            # Load into signal browser
            self._signal_browser.load_dbc(self._decoder.message_definitions)

            # Setup signal definitions for state diagram and selected signals panel
            signal_defs = {}
            for msg in self._decoder.get_all_messages():
                for sig in msg.signals:
                    full_name = f"{msg.name}.{sig.name}"
                    signal_defs[full_name] = sig
            self._state_diagram.set_signal_definitions(signal_defs)
            self._selected_signals_widget.set_signal_definitions(signal_defs)

            self._status_message.setText(
                f"Loaded DBC: {self._decoder.message_count} messages, "
                f"{self._signal_browser.signal_count} signals"
            )

            logger.info(f"Loaded DBC: {self._dbc_path.name}")

        except Exception as e:
            logger.exception("Failed to load DBC")
            QMessageBox.critical(
                self,
                "Error Loading DBC",
                f"Failed to load DBC file:\n{e}",
            )

    @Slot()
    def _on_load_trace(self) -> None:
        """Handle trace file loading."""
        if not self._decoder:
            QMessageBox.warning(
                self,
                "No DBC Loaded",
                "Please load a DBC file first.",
            )
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select CAN Trace File",
            "",
            "CAN Traces (*.blf *.asc);;BLF Files (*.blf);;ASC Files (*.asc);;All Files (*)",
        )

        if not file_path:
            return

        self._trace_path = Path(file_path)
        self._trace_label.setText(f"Trace: {self._trace_path.name}")

        # Start parsing
        self._start_parsing()

    def _start_parsing(self) -> None:
        """Start the parse worker thread."""
        if self._parse_worker and self._parse_worker.isRunning():
            self._parse_worker.cancel()
            self._parse_worker.wait()

        # Clear existing data
        self._on_clear_all()

        # Create worker
        self._parse_worker = ParseWorker(
            self._trace_path,
            self._dbc_path,
            self._data_store,
        )

        # Connect signals with QueuedConnection for thread safety
        # This ensures signals are processed in the main thread's event loop
        self._parse_worker.counting_started.connect(
            self._on_counting_started, Qt.ConnectionType.QueuedConnection
        )
        self._parse_worker.parsing_started.connect(
            self._on_parsing_started, Qt.ConnectionType.QueuedConnection
        )
        self._parse_worker.progress_updated.connect(
            self._on_progress_updated, Qt.ConnectionType.QueuedConnection
        )
        self._parse_worker.signals_decoded.connect(
            self._on_signals_decoded, Qt.ConnectionType.QueuedConnection
        )
        self._parse_worker.parsing_completed.connect(
            self._on_parsing_completed, Qt.ConnectionType.QueuedConnection
        )
        self._parse_worker.parsing_cancelled.connect(
            self._on_parsing_cancelled, Qt.ConnectionType.QueuedConnection
        )
        self._parse_worker.parsing_error.connect(
            self._on_parsing_error, Qt.ConnectionType.QueuedConnection
        )

        # Start
        self._parse_worker.start()

        logger.info(f"Started parsing: {self._trace_path.name}")

    @Slot()
    def _on_stop_parsing(self) -> None:
        """Stop current parsing operation."""
        if self._parse_worker and self._parse_worker.isRunning():
            self._parse_worker.cancel()

    # ================== Worker Signals ==================

    @Slot()
    def _on_counting_started(self) -> None:
        """Handle message counting phase."""
        self._stop_action.setEnabled(True)
        self._stop_btn.setEnabled(True)
        self._progress_bar.setVisible(True)
        self._progress_bar.setRange(0, 0)  # Indeterminate mode
        self._status_message.setText("Counting messages...")

    @Slot()
    def _on_parsing_started(self) -> None:
        """Handle parse start."""
        self._stop_action.setEnabled(True)
        self._stop_btn.setEnabled(True)
        self._progress_bar.setVisible(True)
        self._progress_bar.setRange(0, 100)  # Determinate mode
        self._progress_bar.setValue(0)
        self._status_message.setText("Parsing...")

    @Slot(ParseProgress)
    def _on_progress_updated(self, progress: ParseProgress) -> None:
        """Handle progress updates."""
        # Cap progress at 100% to handle estimation errors
        percent = min(100, max(0, int(progress.progress_percent)))
        self._progress_bar.setValue(percent)
        self._msg_count_label.setText(f"Messages: {progress.decoded_messages:,}")
        self._rate_label.setText(f"Rate: {progress.decode_rate:,.0f} msg/s")

        if progress.state == ParseState.PARSING:
            self._status_message.setText(f"Parsing... {progress.progress_percent:.1f}%")
        else:
            self._status_message.setText(str(progress.state.value))

    @Slot()
    def _on_signals_decoded(self) -> None:
        """Handle decoded signal batch."""
        # Route to widgets
        self._log_table.new_data()
        self._plot_widget.new_data()
        # self._state_diagram.new_data()

        # # Update fullscreen window if open
        # if self._fullscreen_window and self._fullscreen_window.isVisible():
        #     self._fullscreen_window.new(signals)

    @Slot()
    def _on_parsing_completed(self) -> None:
        """Handle parse completion."""
        self._stop_action.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._progress_bar.setVisible(False)

        self._status_message.setText(
            f"Parsing complete - {self._log_table.signal_count:,} signals"
        )

        logger.info("Parsing completed")

    @Slot()
    def _on_parsing_cancelled(self) -> None:
        """Handle parse cancellation."""
        self._stop_action.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._progress_bar.setVisible(False)
        self._status_message.setText("Parsing cancelled")

    @Slot(str)
    def _on_parsing_error(self, error: str) -> None:
        """Handle parse error."""
        self._stop_action.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._progress_bar.setVisible(False)
        self._status_message.setText(f"Error: {error}")

        QMessageBox.critical(
            self,
            "Parsing Error",
            f"An error occurred while parsing:\n{error}",
        )

    # ================== Signal Selection ==================

    @Slot(list)
    def _on_signal_selection_changed(self, selection: list[tuple[str, str]]) -> None:
        """Handle signal selection changes from browser."""
        full_names = [f"{msg}.{sig}" for msg, sig in selection]

        # Update selected signals panel
        self._selected_signals_widget.set_selected_signals(full_names)

        # Update plot
        self._plot_widget.set_selected_signals(full_names)

        # Update fullscreen window
        if self._fullscreen_window and self._fullscreen_window.isVisible():
            self._fullscreen_window.set_selected_signals(full_names)

        logger.debug(f"Signal selection changed: {len(full_names)} signals")

    @Slot(str)
    def _on_signal_removed_from_panel(self, full_name: str) -> None:
        """Handle signal removal from selected signals panel."""
        # Parse full name back to message.signal
        parts = full_name.split(".", 1)
        if len(parts) == 2:
            # Uncheck in signal browser - this will trigger selection_changed
            self._signal_browser.clear_selection()
            # Re-select remaining signals
            remaining = self._selected_signals_widget.get_selected_signals()
            self._signal_browser.select_signals(remaining)

    @Slot()
    def _on_signals_cleared_from_panel(self) -> None:
        """Handle clear all from selected signals panel."""
        self._signal_browser.clear_selection()

    @Slot(list)
    def _on_selected_panel_changed(self, full_names: list[str]) -> None:
        """Handle selection change from the selected signals panel."""
        # Update plot directly
        self._plot_widget.set_selected_signals(full_names)

        # Update fullscreen window
        if self._fullscreen_window and self._fullscreen_window.isVisible():
            self._fullscreen_window.set_selected_signals(full_names)

    @Slot(str, str)
    def _on_signal_color_changed(self, full_name: str, color: str) -> None:
        """Handle custom color change from selected signals panel."""
        # Update plot widget
        self._plot_widget.set_signal_color(full_name, color)

        # Update fullscreen window if visible
        if self._fullscreen_window and self._fullscreen_window.isVisible():
            self._fullscreen_window.set_signal_color(full_name, color)

    # ================== View Actions ==================

    @Slot()
    def _on_open_fullscreen(self) -> None:
        """Open fullscreen plot window."""
        if not self._fullscreen_window:
            self._fullscreen_window = FullscreenPlotWindow(self)
            self._fullscreen_window.closed.connect(self._on_fullscreen_closed)

        # Sync data and selection
        selected = self._signal_browser.get_selected_full_names()
        self._fullscreen_window.sync_data(self._plot_widget._signal_data)
        self._fullscreen_window.set_selected_signals(selected)

        self._fullscreen_window.show()
        self._fullscreen_window.raise_()

    @Slot()
    def _on_fullscreen_closed(self) -> None:
        """Handle fullscreen window close."""
        pass  # Keep reference for reuse

    # ================== State Diagram ==================

    @Slot()
    def _on_state_diagram_add_signals(self) -> None:
        """Open signal selector dialog for state diagram."""
        if not self._decoder:
            QMessageBox.warning(
                self,
                "No DBC Loaded",
                "Please load a DBC file first.",
            )
            return

        # Get signal definitions
        signal_defs = {}
        for msg in self._decoder.get_all_messages():
            for sig in msg.signals:
                full_name = f"{msg.name}.{sig.name}"
                signal_defs[full_name] = sig

        # Get currently active signals
        current_signals = self._state_diagram.get_active_signals()

        # Show dialog
        selected = SignalSelectorDialog.select_signals(
            signal_defs,
            already_selected=current_signals,
            parent=self,
        )

        if selected is not None:
            self._state_diagram.set_active_signals(selected)
            logger.info(f"State diagram signals updated: {len(selected)} signals")

    # ================== Message Log Filter ==================

    @Slot()
    def _on_message_log_add_filter(self) -> None:
        """Open signal selector dialog to add signals to message log filter."""
        if not self._decoder:
            QMessageBox.warning(
                self,
                "No DBC Loaded",
                "Please load a DBC file first.",
            )
            return

        # Get signal definitions
        signal_defs = {}
        for msg in self._decoder.get_all_messages():
            for sig in msg.signals:
                full_name = f"{msg.name}.{sig.name}"
                signal_defs[full_name] = sig

        # Get currently active filters
        already_selected = self._log_table.get_signal_filter()

        # Show dialog with already selected signals pre-checked
        selected = SignalSelectorDialog.select_signals(
            signal_defs,
            already_selected=already_selected,
            parent=self,
        )

        if selected is not None:
            # Add new selections to existing filter
            self._log_table.add_signal_filter(selected)
            logger.info(f"Added {len(selected)} signals to message log filter")

    @Slot()
    def _on_clear_all(self) -> None:
        """Clear all data from widgets."""
        self._log_table.clear()
        self._plot_widget.clear_plot()
        self._state_diagram.clear_data()  # Keep signal selection, just clear data

        if self._fullscreen_window:
            self._fullscreen_window.clear()

        self._msg_count_label.setText("Messages: 0")
        self._status_message.setText("Data cleared")

    # ================== Theme ==================

    @Slot()
    def _on_theme_changed(self, mode: ThemeMode) -> None:
        """Handle theme change from ThemeManager."""
        # Apply new stylesheet to main window
        self.setStyleSheet(self._theme_manager.get_stylesheet())

        # Apply theme to all widgets
        self._apply_theme_to_widgets()

        logger.info(f"Theme changed to: {mode.value}")

    def _apply_theme_to_widgets(self) -> None:
        """Apply current theme to all widgets."""
        is_dark = self._theme_manager.is_dark_mode()
        bg_color = self._theme_manager.get_plot_background()
        fg_color = self._theme_manager.get_plot_foreground()

        # Update plot widgets
        self._plot_widget.update_theme(bg_color, fg_color)
        self._state_diagram.update_theme(bg_color, fg_color)

        # Update table widgets
        self._log_table.update_theme(is_dark)
        self._selected_signals_widget.update_theme(is_dark)
        self._signal_browser.update_theme(is_dark)

        # Update fullscreen window if open
        if self._fullscreen_window and self._fullscreen_window.isVisible():
            self._fullscreen_window.update_theme(bg_color, fg_color)

    # ================== Cleanup ==================

    def closeEvent(self, event) -> None:
        """Handle application close."""
        # Stop any running worker
        if self._parse_worker and self._parse_worker.isRunning():
            self._parse_worker.cancel()
            self._parse_worker.wait(5000)  # Wait up to 5 seconds

        # Close fullscreen window
        if self._fullscreen_window:
            self._fullscreen_window.close()

        logger.info("Application closing")
        super().closeEvent(event)
