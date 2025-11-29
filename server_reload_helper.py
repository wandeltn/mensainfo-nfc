#!/usr/bin/env python3
"""
Simple helper script to show how to stop and restart the webserver in-place
without restarting the whole Python process. Run this from the same Python
process or import the functions from within your running application.

Note: This will only affect the running process (it cannot restart another
process that is already running). For production restarts of the whole app
the existing `restart_application()` behavior in `app.py` remains appropriate.
"""
import time
import logging
from server import start_server_in_thread, stop_server, server_thread_is_alive

logger = logging.getLogger(__name__)


def restart_web_server(wait_for_port: float = 2.0, host: str = '0.0.0.0', port: int = 5000, debug: bool = False):
    """Stop the running webserver, wait for socket release, then restart it.
    This keeps all other threads (NFC thread, update thread) running.
    """
    logger.info("Stopping web server and starting it again in background thread...")
    try:
        stop_server()
    except Exception:
        logger.debug("stop_server() failed; continuing and attempting fallback")

    # Give the OS some time to release the port
    time.sleep(wait_for_port)

    # Start server in a background thread so we don't block
    start_server_in_thread(host=host, port=port, debug=debug)


if __name__ == '__main__':
    # Example usage: restart the web server in this process
    logging.basicConfig(level=logging.INFO)
    restart_web_server()
