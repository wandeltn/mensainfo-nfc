#!/usr/bin/env python3
"""
server.py

Provides a centralized Flask `app` and Flask-SocketIO `socketio` instance
so that the web server (routes/event handlers) can be defined elsewhere and
the server can be started/restarted without causing circular imports.

This file exposes helpers to run and stop the server.
"""
from flask import Flask
from flask_socketio import SocketIO
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# Create Flask application and SocketIO instance here so other modules can
# import them without starting the server automatically.
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")


def run_server(host: str = '0.0.0.0', port: int = 5000, debug: bool = False) -> None:
    """Start the Flask-SocketIO server. This call blocks until the server stops.

    Args:
        host: Host to bind to
        port: Port to bind to
        debug: Run in debug mode
    """
    logger.info(f"Starting Flask-SocketIO server on {host}:{port} (debug={debug})")
    socketio.run(app, host=host, port=port, allow_unsafe_werkzeug=True, debug=debug)


def stop_server() -> None:
    """Stop the running SocketIO server, if possible.

    This calls the `socketio.stop()` method that works with compatible async
    servers; when using the werkzeug server this will attempt to stop the
    running server gracefully.
    """
    try:
        socketio.stop()
    except Exception as e:
        logger.debug(f"Error stopping server: {e}")


# Optional background thread management
_server_thread: Optional[threading.Thread] = None


def start_server_in_thread(host: str = '0.0.0.0', port: int = 5000, debug: bool = False) -> None:
    """Start the SocketIO server in a background thread.

    This is handy during unit tests or when the server should not block the
    main program flow. Repeated calls to this function will not spawn multiple
    servers if one is already running in the background thread.
    """
    global _server_thread
    if _server_thread and _server_thread.is_alive():
        logger.debug("Server thread is already running, ignoring start request")
        return

    def _target():
        try:
            run_server(host=host, port=port, debug=debug)
        except Exception as ex:
            logger.error(f"Server thread exited unexpectedly: {ex}")

    _server_thread = threading.Thread(target=_target, daemon=True)
    _server_thread.start()


def server_thread_is_alive() -> bool:
    return _server_thread is not None and _server_thread.is_alive()


def get_app() -> Flask:
    return app


def get_socketio() -> SocketIO:
    return socketio
