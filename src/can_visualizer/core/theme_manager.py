"""
Theme Manager for CAN Message Visualizer.

Provides centralized theme management with System/Dark/Light modes,
persistent preferences, and notifications for theme changes.
"""

from enum import Enum
from typing import Optional

from PySide6.QtCore import QObject, Signal, QSettings, Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPalette, QGuiApplication


class ThemeMode(Enum):
    """Available theme modes."""

    SYSTEM = "system"
    DARK = "dark"
    LIGHT = "light"


class ThemeManager(QObject):
    """
    Singleton theme manager for the application.

    Manages theme switching between System/Dark/Light modes,
    persists preferences, and emits signals when theme changes.
    """

    _instance: Optional["ThemeManager"] = None

    # Signal emitted when theme changes
    theme_changed = Signal(ThemeMode)

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        super().__init__()
        self._initialized = True

        self._settings = QSettings("CAN Tools", "CAN Message Visualizer")
        self._current_mode = ThemeMode.DARK  # Default to dark
        self._load_preference()

    def _load_preference(self) -> None:
        """Load saved theme preference."""
        saved = self._settings.value("theme/mode", "dark")
        try:
            self._current_mode = ThemeMode(saved)
        except ValueError:
            self._current_mode = ThemeMode.DARK

    def _save_preference(self) -> None:
        """Save current theme preference."""
        self._settings.setValue("theme/mode", self._current_mode.value)

    @property
    def current_mode(self) -> ThemeMode:
        """Get current theme mode."""
        return self._current_mode

    def set_theme(self, mode: ThemeMode) -> None:
        """
        Set the application theme.

        Args:
            mode: The theme mode to apply
        """
        if mode == self._current_mode:
            return

        self._current_mode = mode
        self._save_preference()
        self.apply_color_scheme()
        self.theme_changed.emit(mode)

    def apply_color_scheme(self) -> None:
        """
        Apply the Qt color scheme for native widgets like title bar.

        On macOS, this sets the appearance for the window chrome.
        """
        app = QGuiApplication.instance()
        if not app:
            return

        style_hints = app.styleHints()
        if not style_hints:
            return

        if self._current_mode == ThemeMode.SYSTEM:
            # Reset to follow system
            style_hints.setColorScheme(Qt.ColorScheme.Unknown)
        elif self._current_mode == ThemeMode.DARK:
            style_hints.setColorScheme(Qt.ColorScheme.Dark)
        else:
            style_hints.setColorScheme(Qt.ColorScheme.Light)

    def is_dark_mode(self) -> bool:
        """
        Check if current effective theme is dark.

        For SYSTEM mode, checks the system preference.
        """
        if self._current_mode == ThemeMode.LIGHT:
            return False
        if self._current_mode == ThemeMode.DARK:
            return True

        # SYSTEM mode - check system preference
        app = QApplication.instance()
        if app:
            palette = app.palette()
            # If window color is dark, system is in dark mode
            return palette.color(QPalette.ColorRole.Window).lightness() < 128
        return True  # Default to dark

    def get_stylesheet(self) -> str:
        """Get the stylesheet for current theme."""
        if self.is_dark_mode():
            return self._get_dark_stylesheet()
        return self._get_light_stylesheet()

    def get_plot_background(self) -> str:
        """Get background color for pyqtgraph plots."""
        return "#1E1E1E" if self.is_dark_mode() else "#FAFAFA"

    def get_plot_foreground(self) -> str:
        """Get foreground color for pyqtgraph plots."""
        return "#D4D4D4" if self.is_dark_mode() else "#333333"

    def _get_dark_stylesheet(self) -> str:
        """Return dark theme stylesheet."""
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
            QPushButton:checked {
                background: #005A9E;
                border: 1px solid #0078D4;
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
                alternate-background-color: #2D2D2D;
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
                background: #1E1E1E;
                alternate-background-color: #252526;
                border: 1px solid #3D3D3D;
                gridline-color: transparent;
            }
            QTableView::item {
                padding: 4px 8px;
                border: none;
            }
            QTableView::item:selected {
                background: #094771;
                color: #FFFFFF;
            }
            QTableView::item:hover {
                background: #2D2D2D;
            }
            QHeaderView::section {
                background: #2D2D2D;
                color: #E0E0E0;
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
            QMenu::separator {
                height: 1px;
                background: #3D3D3D;
                margin: 4px 8px;
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
                background: #1E1E1E;
                alternate-background-color: #252526;
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
            QListWidget::item:selected {
                background: #0078D4;
            }
            QFrame[frameShape="4"], QFrame[frameShape="5"] {
                background: #3D3D3D;
            }
        """

    def _get_light_stylesheet(self) -> str:
        """Return light theme stylesheet."""
        return """
            QMainWindow {
                background: #F5F5F5;
            }
            QWidget {
                background: #F5F5F5;
                color: #1E1E1E;
                font-family: 'Segoe UI', 'SF Pro Display', -apple-system, sans-serif;
                font-size: 13px;
            }
            QGroupBox {
                border: 1px solid #D0D0D0;
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
                border: 1px solid #D0D0D0;
                border-radius: 4px;
            }
            QTabBar::tab {
                background: #E8E8E8;
                border: 1px solid #D0D0D0;
                border-bottom: none;
                padding: 8px 16px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background: #F5F5F5;
                border-bottom: 2px solid #0078D4;
            }
            QTabBar::tab:hover {
                background: #DFDFDF;
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
                background: #D0D0D0;
                color: #888;
            }
            QPushButton:checked {
                background: #005A9E;
                border: 1px solid #0078D4;
            }
            QLineEdit {
                background: #FFFFFF;
                border: 1px solid #D0D0D0;
                border-radius: 4px;
                padding: 6px 8px;
                selection-background-color: #0078D4;
            }
            QLineEdit:focus {
                border-color: #0078D4;
            }
            QTreeWidget {
                background: #FFFFFF;
                alternate-background-color: #F8F8F8;
                border: 1px solid #D0D0D0;
                border-radius: 4px;
            }
            QTreeWidget::item {
                padding: 4px;
            }
            QTreeWidget::item:hover {
                background: #E8E8E8;
            }
            QTreeWidget::item:selected {
                background: #0078D4;
                color: white;
            }
            QTableView {
                background: #FFFFFF;
                alternate-background-color: #F8F8F8;
                border: 1px solid #D0D0D0;
                gridline-color: transparent;
            }
            QTableView::item {
                padding: 4px 8px;
                border: none;
            }
            QTableView::item:selected {
                background: #0078D4;
                color: #FFFFFF;
            }
            QTableView::item:hover {
                background: #E8E8E8;
            }
            QHeaderView::section {
                background: #E8E8E8;
                color: #1E1E1E;
                border: none;
                border-right: 1px solid #D0D0D0;
                border-bottom: 1px solid #D0D0D0;
                padding: 6px;
                font-weight: bold;
            }
            QProgressBar {
                background: #E8E8E8;
                border: none;
                border-radius: 4px;
                text-align: center;
            }
            QProgressBar::chunk {
                background: #0078D4;
                border-radius: 4px;
            }
            QStatusBar {
                background: #E8E8E8;
                border-top: 1px solid #D0D0D0;
            }
            QMenuBar {
                background: #E8E8E8;
                border-bottom: 1px solid #D0D0D0;
            }
            QMenuBar::item {
                padding: 6px 12px;
            }
            QMenuBar::item:selected {
                background: #D0D0D0;
            }
            QMenu {
                background: #FFFFFF;
                border: 1px solid #D0D0D0;
            }
            QMenu::item {
                padding: 6px 24px;
            }
            QMenu::item:selected {
                background: #0078D4;
                color: white;
            }
            QMenu::separator {
                height: 1px;
                background: #D0D0D0;
                margin: 4px 8px;
            }
            QToolBar {
                background: #E8E8E8;
                border-bottom: 1px solid #D0D0D0;
                spacing: 4px;
                padding: 4px;
            }
            QSplitter::handle {
                background: #D0D0D0;
            }
            QComboBox {
                background: #FFFFFF;
                border: 1px solid #D0D0D0;
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
                background: #FFFFFF;
                border: 1px solid #D0D0D0;
                selection-background-color: #0078D4;
            }
            QCheckBox {
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 3px;
                border: 1px solid #D0D0D0;
                background: #FFFFFF;
            }
            QCheckBox::indicator:checked {
                background: #0078D4;
                border-color: #0078D4;
            }
            QScrollBar:vertical {
                background: #F5F5F5;
                width: 12px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #C0C0C0;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: #A0A0A0;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            QScrollBar:horizontal {
                background: #F5F5F5;
                height: 12px;
                margin: 0;
            }
            QScrollBar::handle:horizontal {
                background: #C0C0C0;
                border-radius: 6px;
                min-width: 20px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #A0A0A0;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0;
            }
            QListWidget {
                background: #FFFFFF;
                alternate-background-color: #F8F8F8;
                border: 1px solid #D0D0D0;
                border-radius: 4px;
            }
            QListWidget::item {
                padding: 6px;
                border-bottom: 1px solid #E8E8E8;
            }
            QListWidget::item:hover {
                background: #E8E8E8;
            }
            QListWidget::item:selected {
                background: #0078D4;
                color: white;
            }
            QFrame[frameShape="4"], QFrame[frameShape="5"] {
                background: #D0D0D0;
            }
        """


# Global instance accessor
def get_theme_manager() -> ThemeManager:
    """Get the global ThemeManager instance."""
    return ThemeManager()
