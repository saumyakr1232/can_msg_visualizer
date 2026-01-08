xYou are a senior desktop systems engineer building a professional CAN bus analysis tool, similar in spirit to CANalyzer, but fully local, offline, and developer-focused.

This is a production-grade engineering application used daily by automotive developers.

⸻

🎯 Goal

Build a modern PySide6 desktop application that parses, decodes, streams, and visualizes CAN logs from BLF and ASC files using a DBC file, with emphasis on:
	•	Performance with very large files
	•	Responsive UI at all times
	•	Modular and maintainable architecture

⸻

🧰 Project Initialization (Mandatory)

Use uv for project setup and dependency management.

Requirements
	•	Initialize project using uv init
	•	Manage dependencies via pyproject.toml
	•	Use uv add for all packages
	•	Use uv run for execution
	•	Target Python 3.10+


    Dependencies

Install via uv add:
	•	PySide6
	•	python-can
	•	cantools
	•	pyqtgraph

Logging must use Python standard logging with rotating file handlers.

⸻

📁 File Handling
	•	User selects local file paths only
	•	DBC file
	•	BLF or ASC trace file
	•	No uploads
	•	No networking
	•	Must support very large trace files

⸻

🧠 CAN Parsing and Decoding
	•	Use python-can to read BLF and ASC files
	•	Use cantools to decode signals using the DBC
	•	Extract:
	•	timestamp
	•	CAN ID
	•	message name
	•	signal name
	•	raw value
	•	physical value
	•	Parsing must be fully asynchronous
	•	UI must never block

⸻

🔄 Streaming Mode

While parsing:
	•	Stream decoded CAN logs into a table view
	•	Stream signal values into plots in near real time
	•	Display:
	•	progress indicator
	•	message count
	•	decode rate

Use QThread or QRunnable with signal-slot communication.

⸻

💾 Batch Parse and Cache
	•	Once parsing completes:
	•	Cache decoded data to disk using SQLite or pickle
	•	Reopening the same BLF or ASC file must load instantly
	•	Support switching between:
	•	live streaming mode
	•	cached replay mode

⸻

📊 Interactive Plotting

Use pyqtgraph.

Plot Features
	•	Multiple signal selection
	•	Time on X axis
	•	Physical value on Y axis
	•	Zoom and pan
	•	Grid toggle
	•	Legend
	•	Auto-range
	•	Clip-to-view
	•	Downsampling
	•	Maximum point capping

Multiple signals must be plotted together with distinct colors.

⸻

🖥 Full-Screen Plot Window
	•	Detachable full-screen plot window
	•	Mirrors selected signals
	•	Continues updating during live streaming

⸻

🔍 DBC Signal Browser
	•	Hierarchical tree:
	•	Message
	•	Signals
	•	Search bar filters messages and signals
	•	Search must not reset checked signals
	•	Multi-selection supported

⸻

🔁 State Diagram View

Add a dedicated State Diagram visualization mode.

Requirements
	•	Works for one signal at a time
	•	Shows discrete signal values against time
	•	Designed for enums, modes, flags
	•	Updates live during streaming
	•	Uses step or timeline style rendering

⸻

🧩 Architecture Guidelines
	•	Strong separation of concerns
	•	No god classes
	•	Modular components:
	•	Parser worker
	•	Decoder
	•	Cache manager
	•	Plot controller
	•	UI widgets
	•	Prefer composition over inheritance
	•	Clear signal-slot boundaries

⸻

📝 Logging
	•	Rotating file logging
	•	Console logging
	•	Log:
	•	parsing lifecycle
	•	decode failures
	•	cache hits and misses
	•	performance metrics

⸻

⚙️ Non-Functional Requirements
	•	Handle millions of CAN messages
	•	UI remains responsive under load
	•	Code must be readable and extensible
	•	Avoid blocking calls in the main thread
	•	Optimize memory usage

⸻

🧪 Expectations
	•	Propose a clean architecture first
	•	Explain threading and streaming decisions
	•	Optimize plotting for large datasets
	•	Write production-quality Python code
	•	Add comments where design choices matter

Build this as a serious engineering tool, not a demo.

Start with architecture, then implement step by step.
