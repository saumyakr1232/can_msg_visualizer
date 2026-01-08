# CAN Message Visualizer

A professional-grade CAN bus analysis tool for parsing, decoding, streaming, and visualizing CAN logs from BLF and ASC files using DBC databases.

![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)
![PySide6](https://img.shields.io/badge/GUI-PySide6-green.svg)
![License](https://img.shields.io/badge/license-MIT-blue.svg)

## Features

### Core Functionality
- **File Support**: Parse BLF (Vector) and ASC (text) CAN trace files
- **DBC Decoding**: Decode raw CAN data using standard DBC database files
- **Streaming Mode**: Real-time streaming of decoded signals during parsing
- **Caching**: SQLite-based caching for instant reload of previously parsed files

### Visualization
- **Message Log**: High-performance table view with virtual scrolling for millions of messages
- **Signal Plotting**: Interactive pyqtgraph-based plotting with:
  - Multiple signal overlay
  - Zoom and pan
  - Auto-downsampling for large datasets
  - Grid and legend toggles
  - Fullscreen detachable window
- **State Diagram**: Timeline visualization for discrete/enum signals

### User Interface
- **Signal Browser**: Hierarchical tree view of DBC messages and signals
  - Search filtering
  - Multi-selection via checkboxes
  - Signal metadata tooltips
- **Dark Theme**: Modern, professional dark UI
- **Responsive**: UI remains responsive during parsing via background threading

## Installation

### Prerequisites
- Python 3.10 or higher
- [uv](https://github.com/astral-sh/uv) package manager

### Setup

```bash
# Clone the repository
git clone <repository-url>
cd can_msg_visualizer

# Install dependencies
uv sync

# Run the application
uv run can-visualizer
```

Or run directly:

```bash
uv run python -m can_visualizer.main
```

## Usage

### Quick Start

1. **Load DBC File**: Click "Load DBC" or press `Ctrl+D` to select your DBC database file
2. **Load Trace File**: Click "Load Trace" or press `Ctrl+O` to select a BLF or ASC trace file
3. **Browse Signals**: Use the left panel to explore and select signals
4. **View Data**: 
   - Message Log tab shows all decoded messages
   - Signal Plot tab shows selected signals over time
   - State Diagram tab visualizes discrete signal states

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+D` | Load DBC file |
| `Ctrl+O` | Load trace file |
| `Ctrl+.` | Stop parsing |
| `F11` | Open fullscreen plot |
| `Ctrl+Shift+C` | Clear all data |
| `Ctrl+Q` | Exit application |

### Fullscreen Plot Window

| Shortcut | Action |
|----------|--------|
| `F` | Toggle fullscreen |
| `R` | Auto-range view |
| `Escape` | Close window |

## Architecture

```
src/can_visualizer/
├── main.py              # Entry point
├── app.py               # Main window and application logic
├── core/
│   ├── models.py        # Data models (CANMessage, DecodedSignal, etc.)
│   ├── parser.py        # BLF/ASC file parser using python-can
│   ├── decoder.py       # DBC-based signal decoder using cantools
│   └── cache.py         # SQLite caching for decoded data
├── workers/
│   └── parse_worker.py  # QThread for async parsing
├── widgets/
│   ├── signal_browser.py    # DBC tree browser
│   ├── log_table.py         # Message table view
│   ├── plot_widget.py       # pyqtgraph plotting
│   ├── state_diagram.py     # State timeline view
│   └── fullscreen_plot.py   # Detachable plot window
└── utils/
    └── logging_config.py    # Rotating file logging
```

### Design Principles

- **Separation of Concerns**: Each module has a single responsibility
- **Thread Safety**: Background parsing with Qt signal-slot communication
- **Memory Efficiency**: Streaming parsing, virtual scrolling, data capping
- **Performance**: Downsampling, clip-to-view, batch updates

## Performance

The application is designed to handle large CAN trace files:

- **Parsing**: Streaming parser processes files without loading entirely into memory
- **Table View**: Virtual scrolling handles 500,000+ rows efficiently
- **Plotting**: Automatic downsampling when data exceeds 100,000 points per signal
- **Caching**: Previously parsed files load instantly from SQLite cache

## Logging

Logs are stored in `~/.can_visualizer/logs/` with rotating file handlers:
- Maximum 10 MB per log file
- 5 backup files retained
- Both file and console logging

## Cache

Decoded signal data is cached in `~/.can_visualizer/cache/`:
- SQLite database for reliability
- Content-based cache keys (file name + size + modification time)
- Cache menu for statistics and clearing

## Dependencies

- **PySide6**: Qt6 bindings for Python GUI
- **python-can**: CAN bus interface library for BLF/ASC parsing
- **cantools**: DBC file parsing and signal decoding
- **pyqtgraph**: High-performance plotting library

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions are welcome! Please ensure:
- Code follows existing style conventions
- New features include appropriate logging
- Large datasets are handled efficiently

