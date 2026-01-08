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
from PySide6.QtGui import QAction, QKeySequence

from .core.cache import CacheManager
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
    
    def __init__(self, parent=None):
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
        self.plot_widget = PlotWidget()
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
        self._trace_path: Optional[Path] = None
        self._decoder: Optional[DBCDecoder] = None
        self._cache_manager = CacheManager()
        self._parse_worker: Optional[ParseWorker] = None
        self._cache_key: Optional[str] = None
        self._fullscreen_window: Optional[FullscreenPlotWindow] = None
        
        self._setup_ui()
        self._setup_menu()
        self._setup_toolbar()
        self._setup_statusbar()
        self._connect_signals()
        
        logger.info("Main window initialized")
    
    def _setup_ui(self) -> None:
        """Initialize the main UI layout."""
        self.setWindowTitle("CAN Message Visualizer")
        self.setMinimumSize(1200, 800)
        
        # Apply dark theme
        self.setStyleSheet(self._get_stylesheet())
        
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)
        
        # Tabs - each tab has its own splitter layout
        self._tabs = QTabWidget()
        
        # Message Log Tab (with built-in filter panel)
        self._log_table = LogTableWidget()
        self._tabs.addTab(self._log_table, "📋 Message Log")
        
        # Signal Plot Tab (with DBC browser)
        self._signal_plot_tab = SignalPlotTab()
        self._tabs.addTab(self._signal_plot_tab, "📈 Signal Plot")
        
        # State Diagram Tab (with built-in control panel)
        self._state_diagram = StateDiagramWidget()
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
        
        self._clear_action = QAction("&Clear All Data", self)
        self._clear_action.setShortcut(QKeySequence("Ctrl+Shift+C"))
        self._clear_action.triggered.connect(self._on_clear_all)
        view_menu.addAction(self._clear_action)
        
        # Cache menu
        cache_menu = menubar.addMenu("&Cache")
        
        cache_stats_action = QAction("Show Cache &Statistics", self)
        cache_stats_action.triggered.connect(self._on_show_cache_stats)
        cache_menu.addAction(cache_stats_action)
        
        clear_cache_action = QAction("&Clear All Cache", self)
        clear_cache_action.triggered.connect(self._on_clear_cache)
        cache_menu.addAction(clear_cache_action)
    
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
        self._signal_browser.selection_changed.connect(self._on_signal_selection_changed)
        
        # Selected signals panel -> Signal browser (for removing signals)
        self._selected_signals_widget.signal_removed.connect(self._on_signal_removed_from_panel)
        self._selected_signals_widget.signals_cleared.connect(self._on_signals_cleared_from_panel)
        self._selected_signals_widget.selection_changed.connect(self._on_selected_panel_changed)
        
        # Plot fullscreen request
        self._plot_widget.fullscreen_requested.connect(self._on_open_fullscreen)
        
        # State diagram -> Signal selector dialog
        self._state_diagram.add_signals_requested.connect(self._on_state_diagram_add_signals)
        
        # Message log filter -> Signal selector dialog
        self._log_table.add_filter_requested.connect(self._on_message_log_add_filter)
    
    def _get_stylesheet(self) -> str:
        """Return application stylesheet."""
        return """
            QMainWindow {
                background: #1E1E1E;
            }
            QWidget {
                background: #1E1E1E;
                color: #D4D4D4;
                font-family: 'Segoe UI', 'SF Pro Display', -apple-system, sans-serif;
                font-size: 13px;
            }
            QGroupBox {
                border: 1px solid #3D3D3D;
                border-radius: 4px;
                margin-top: 8px;
                padding-top: 8px;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
            }
            QTabWidget::pane {
                border: 1px solid #3D3D3D;
                border-radius: 4px;
            }
            QTabBar::tab {
                background: #2D2D2D;
                border: 1px solid #3D3D3D;
                border-bottom: none;
                padding: 8px 16px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background: #1E1E1E;
                border-bottom: 2px solid #0078D4;
            }
            QTabBar::tab:hover {
                background: #3D3D3D;
            }
            QPushButton {
                background: #0078D4;
                border: none;
                border-radius: 4px;
                padding: 6px 16px;
                color: white;
                font-weight: 500;
            }
            QPushButton:hover {
                background: #1084D9;
            }
            QPushButton:pressed {
                background: #006CC1;
            }
            QPushButton:disabled {
                background: #3D3D3D;
                color: #666;
            }
            QLineEdit {
                background: #2D2D2D;
                border: 1px solid #3D3D3D;
                border-radius: 4px;
                padding: 6px 8px;
                selection-background-color: #0078D4;
            }
            QLineEdit:focus {
                border-color: #0078D4;
            }
            QTreeWidget {
                background: #252526;
                border: 1px solid #3D3D3D;
                border-radius: 4px;
            }
            QTreeWidget::item {
                padding: 4px;
            }
            QTreeWidget::item:hover {
                background: #2D2D2D;
            }
            QTreeWidget::item:selected {
                background: #0078D4;
            }
            QTableView {
                background: #252526;
                border: 1px solid #3D3D3D;
                gridline-color: #3D3D3D;
            }
            QTableView::item:selected {
                background: #0078D4;
            }
            QHeaderView::section {
                background: #2D2D2D;
                border: none;
                border-right: 1px solid #3D3D3D;
                border-bottom: 1px solid #3D3D3D;
                padding: 6px;
                font-weight: bold;
            }
            QProgressBar {
                background: #2D2D2D;
                border: none;
                border-radius: 4px;
                text-align: center;
            }
            QProgressBar::chunk {
                background: #0078D4;
                border-radius: 4px;
            }
            QStatusBar {
                background: #252526;
                border-top: 1px solid #3D3D3D;
            }
            QMenuBar {
                background: #252526;
                border-bottom: 1px solid #3D3D3D;
            }
            QMenuBar::item {
                padding: 6px 12px;
            }
            QMenuBar::item:selected {
                background: #3D3D3D;
            }
            QMenu {
                background: #2D2D2D;
                border: 1px solid #3D3D3D;
            }
            QMenu::item {
                padding: 6px 24px;
            }
            QMenu::item:selected {
                background: #0078D4;
            }
            QToolBar {
                background: #252526;
                border-bottom: 1px solid #3D3D3D;
                spacing: 4px;
                padding: 4px;
            }
            QSplitter::handle {
                background: #3D3D3D;
            }
            QComboBox {
                background: #2D2D2D;
                border: 1px solid #3D3D3D;
                border-radius: 4px;
                padding: 6px 8px;
            }
            QComboBox:hover {
                border-color: #0078D4;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox QAbstractItemView {
                background: #2D2D2D;
                border: 1px solid #3D3D3D;
                selection-background-color: #0078D4;
            }
            QCheckBox {
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 3px;
                border: 1px solid #3D3D3D;
                background: #2D2D2D;
            }
            QCheckBox::indicator:checked {
                background: #0078D4;
                border-color: #0078D4;
            }
            QScrollBar:vertical {
                background: #1E1E1E;
                width: 12px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #3D3D3D;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: #4D4D4D;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            QScrollBar:horizontal {
                background: #1E1E1E;
                height: 12px;
                margin: 0;
            }
            QScrollBar::handle:horizontal {
                background: #3D3D3D;
                border-radius: 6px;
                min-width: 20px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #4D4D4D;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0;
            }
            QListWidget {
                background: #252526;
                border: 1px solid #3D3D3D;
                border-radius: 4px;
            }
            QListWidget::item {
                padding: 6px;
            }
            QListWidget::item:hover {
                background: #2D2D2D;
            }
            QListWidget::item:selected {
                background: #0078D4;
            }
        """
    
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
            self._cache_manager,
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
        
        # Notify log table that parsing has started (for lazy updates)
        self._log_table.set_parsing_state(True)
    
    @Slot(ParseProgress)
    def _on_progress_updated(self, progress: ParseProgress) -> None:
        """Handle progress updates."""
        # Cap progress at 100% to handle estimation errors
        percent = min(100, max(0, int(progress.progress_percent)))
        self._progress_bar.setValue(percent)
        self._msg_count_label.setText(f"Messages: {progress.decoded_messages:,}")
        self._rate_label.setText(f"Rate: {progress.decode_rate:,.0f} msg/s")
        
        if progress.state == ParseState.PARSING:
            self._status_message.setText(
                f"Parsing... {progress.progress_percent:.1f}%"
            )
    
    @Slot(list)
    def _on_signals_decoded(self, signals: list[DecodedSignal]) -> None:
        """Handle decoded signal batch."""
        # Route to widgets
        self._log_table.add_signals(signals)
        self._plot_widget.add_signals(signals)
        self._state_diagram.add_signals(signals)
        
        # Update fullscreen window if open
        if self._fullscreen_window and self._fullscreen_window.isVisible():
            self._fullscreen_window.add_signals(signals)
    
    @Slot(str)
    def _on_parsing_completed(self, cache_key: str) -> None:
        """Handle parse completion."""
        self._cache_key = cache_key
        
        self._stop_action.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._progress_bar.setVisible(False)
        
        # Notify log table that parsing completed (triggers final lazy flush)
        self._log_table.set_parsing_state(False)
        
        self._status_message.setText(
            f"Parsing complete - {self._log_table.signal_count:,} signals"
        )
        
        logger.info(f"Parsing completed, cache key: {cache_key[:16]}...")
    
    @Slot()
    def _on_parsing_cancelled(self) -> None:
        """Handle parse cancellation."""
        self._stop_action.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._progress_bar.setVisible(False)
        self._status_message.setText("Parsing cancelled")
        
        # Notify log table that parsing stopped (triggers lazy flush)
        self._log_table.set_parsing_state(False)
    
    @Slot(str)
    def _on_parsing_error(self, error: str) -> None:
        """Handle parse error."""
        self._stop_action.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._progress_bar.setVisible(False)
        self._status_message.setText(f"Error: {error}")
        
        # Notify log table that parsing stopped (triggers lazy flush)
        self._log_table.set_parsing_state(False)
        
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
        """Open signal selector dialog for message log filter."""
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
        
        # Show dialog
        selected = SignalSelectorDialog.select_signals(
            signal_defs,
            already_selected=[],
            parent=self,
        )
        
        if selected is not None:
            self._log_table.set_signal_filter(selected)
            logger.info(f"Message log filter updated: {len(selected)} signals")
    
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
    
    # ================== Cache Actions ==================
    
    @Slot()
    def _on_show_cache_stats(self) -> None:
        """Show cache statistics dialog."""
        stats = self._cache_manager.get_cache_stats()
        
        QMessageBox.information(
            self,
            "Cache Statistics",
            f"Cached files: {stats['cached_files']}\n"
            f"Total signals: {stats['total_signals']:,}\n"
            f"Database size: {stats['database_size_mb']:.2f} MB",
        )
    
    @Slot()
    def _on_clear_cache(self) -> None:
        """Clear all cached data."""
        reply = QMessageBox.question(
            self,
            "Clear Cache",
            "Are you sure you want to clear all cached data?\n"
            "This will require re-parsing previously loaded files.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self._cache_manager.clear_all()
            self._status_message.setText("Cache cleared")
            logger.info("Cache cleared by user")
    
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
