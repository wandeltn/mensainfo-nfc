# Copilot Instructions for MensaInfo NFC Project

## Project Architecture

This is a **hybrid NFC card reader application** with three distinct components:
- **Flask web server** (`app.py`) - Main application serving HTML and managing WebSocket communication
- **Direct NFC interfaces** (`main.py`, `libnfc.py`) - Standalone card reading implementations
- **Browser automation testing** (`browser-test.py`) - Selenium-based testing utilities

## Key Components

### Main Application (`app.py`)
- **Flask + SocketIO server** on port 5000 with CORS enabled
- **Threading architecture**: Background NFC polling thread + main Flask thread
- **WebSocket events**: `reload`, `card_success`, `card_unauthorized` for real-time UI updates
- **Card detection logic**: Tracks `last_uid` to detect card insertion/removal events
- **External service integration**: Validates cards against `https://mensacheck.n-s-w.info`

### NFC Reader Implementations
- **`py122u` library** (app.py) - Primary NFC interface using `nfc.Reader()`
- **`smartcard` library** (main.py) - Alternative PCSC-based implementation
- **`nfc` library** (libnfc.py) - ContactlessFrontend approach with tag callbacks

### UI Pattern
- **Embedded HTML** in Python with injected WebSocket client code
- **Auto-reload mechanism** triggered by card events via WebSocket
- **Centered layout** with viewport-responsive design (90vw/90vh containers)

## Development Workflow

### Environment Setup
```bash
# Python 3.13.7 virtual environment
.venv\Scripts\activate  # Windows activation
# No requirements.txt - dependencies managed manually
```

### Running Applications
```bash
python app.py           # Main Flask server (port 5000)
python main.py          # Standalone smartcard reader
python libnfc.py        # Standalone nfc library reader
python browser-test.py  # Selenium testing
```

### Key Dependencies
- **Flask + Flask-SocketIO** for web server and real-time communication
- **py122u** for primary NFC reading
- **pyscard/smartcard** for PCSC interface
- **nfcpy** for ContactlessFrontend
- **Selenium + Firefox** for browser automation testing

## Project-Specific Patterns

### NFC Reading Strategy
- **Multiple library support** - Three different NFC approaches for hardware compatibility
- **UID formatting** - Always uppercase hex strings (`''.join(f'{x:02X}' for x in arr)`)
- **Connection error handling** - Graceful degradation when NFC hardware unavailable

### Card Validation Flow
1. Read UID from card → Format as hex string
2. POST to mensacheck.n-s-w.info with `eingabe=<UID>`
3. Success detection: Check for "Erfolgreich gespeichert!" in response

### WebSocket Communication
- **Event-driven UI updates** - No polling, cards trigger immediate `reload` events
- **Error propagation** - `card_unauthorized` events for validation failures
- **Connection resilience** - Client auto-reconnection via Socket.IO

## Critical Integration Points

- **Hardware dependency**: NFC readers via USB (py122u/PCSC compatible)
- **External validation**: mensacheck.n-s-w.info service for card authorization
- **Browser testing**: Firefox with geckodriver for Selenium automation
- **Network binding**: Flask serves on `0.0.0.0:5000` for network access

## Development Notes

- **Threading considerations**: NFC polling runs as daemon thread to prevent blocking
- **Error handling**: Multiple fallback strategies for different NFC hardware failures  
- **Unsafe Werkzeug**: Intentionally enabled for development (`allow_unsafe_werkzeug=True`)
- **No formal dependency management** - Libraries installed directly in venv