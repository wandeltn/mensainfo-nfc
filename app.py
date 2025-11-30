#!/usr/bin/env python3

# --- Enhanced NFC card validation system with auto-update ---
import threading
import time
import logging
import os
import json
import shutil
import sys
import subprocess
import argparse
import socket
from datetime import datetime, timedelta

# Setup logging FIRST, before any imports that use it
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Now import modules that may use logger
try:
    from py_acr122u import nfc
except Exception:
    nfc = None
    # Do not error on import failure - nfc availability is optional
    logger.debug('py_acr122u nfc module not available; nfc.Reader path disabled')
import requests
from flask import Response
from server import app, socketio, run_server, stop_server  # server application instance and helpers
try:
    import acr122u_reader
except Exception:
    acr122u_reader = None

# OS Detection
IS_WINDOWS = os.name == 'nt'
IS_LINUX = os.name == 'posix'
OS_NAME = 'Windows' if IS_WINDOWS else 'Linux/Unix' if IS_LINUX else 'Unknown'

logger.info(f"Detected operating system: {OS_NAME}")

# Global variables
reader = None
nfc_reader_available = False

def cleanup_nfc_reader():
    """
    Safely cleanup the NFC reader instance
    """
    global reader, nfc_reader_available
    
    if reader is not None:
        try:
            reader.close()
            logger.debug("NFC reader closed successfully")
        except Exception as e:
            logger.debug(f"Error closing NFC reader: {e}")
        finally:
            reader = None
            nfc_reader_available = False

# Database server configuration
DATABASE_URL = "http://mensacheck.n-s-w.info"
VALIDATION_HEADERS = {
    'Content-Type': 'application/x-www-form-urlencoded'
}

# Auto-update configuration
GITHUB_REPO = "wandeltn/mensainfo-nfc"  # Your GitHub repository
UPDATE_CHECK_INTERVAL = 86400  # Check for updates every day (86400 seconds)
VERSION_FILE = "current_version.json"
BACKUP_DIR = "backup"
RESTART_DELAY = 10  # Seconds to wait before restarting after app.py update

# Global flags (can be modified by command line arguments)
AUTO_UPDATE_ENABLED = True  # Default: auto-update is enabled
DRY_RUN = False  # Simulate actions instead of actually performing them
DISABLE_READER_BEEP = True

def parse_command_line_arguments():
    """
    Parse command line arguments for the application
    """
    global AUTO_UPDATE_ENABLED
    
    parser = argparse.ArgumentParser(
        description='NFC Card Reader Application with Auto-Update',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python app.py                    # Run with auto-update enabled (default)
  python app.py --no-auto-update   # Run with auto-update disabled (for debugging)
  python app.py --disable-updates  # Same as --no-auto-update
        """
    )
    
    # Auto-update control flags
    update_group = parser.add_mutually_exclusive_group()
    update_group.add_argument(
        '--no-auto-update', '--disable-updates',
        action='store_true',
        help='Disable automatic updates (useful for debugging and development)'
    )
    update_group.add_argument(
        '--enable-auto-update',
        action='store_true',
        help='Explicitly enable automatic updates (default behavior)'
    )
    
    # Debug/development flags
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug mode (implies --no-auto-update)'
    )
    parser.add_argument(
        '--no-beep',
        action='store_true',
        help='Try to disable the hardware beep on the NFC reader (best-effort, vendor-specific)'
    )
    parser.add_argument(
        '--no-fast-read',
        action='store_true',
        help='Disable the pyscard fast read mode; use the default reader library only (py122u/nfcpy)'
    )
    parser.add_argument(
        '--kill-port',
        action='store_true',
        help='Attempt to kill processes that are using the Flask port before starting the server (dangerous; use with care)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Simulate actions without killing processes or launching restart scripts; logs what would be done.'
    )
    
    # Parse arguments
    args = parser.parse_args()
    
    # Apply the settings
    if args.no_auto_update or args.debug:
        AUTO_UPDATE_ENABLED = False
        logger.info("🚫 Auto-update disabled via command line flag")
    elif args.enable_auto_update:
        AUTO_UPDATE_ENABLED = True
        logger.info("✅ Auto-update explicitly enabled via command line flag")
    
    # Show debug mode status
    if args.debug:
        logger.info("🐛 Debug mode enabled")
        # Set logging level to DEBUG for more verbose output
        logging.getLogger().setLevel(logging.DEBUG)
    
    return args


def try_disable_reader_beep():
    """Best-effort approach to disable reader beep. This is vendor-specific and may fail.

    We try two strategies:
    - If `smartcard` (pyscard) is available, attempt to connect and transmit a vendor APDU
      that some readers interpret as buzzer control. These APDUs are vendor-specific.
    - If the `py122u` reader object exposes a method to set beep/led, attempt that.
    """
    try:
        from smartcard.System import readers as sc_readers
        from smartcard.util import toHexString

        r = sc_readers()
        if r:
            try:
                conn = r[0].createConnection()
                conn.connect()
                # Best-effort: try some vendor control APDUs known to exist on some readers.
                candidates = [
                    # Common vendor-specific commands used by some readers (mute/unmute)
                    [0xFF, 0x00, 0x52, 0x00, 0x00],
                    [0xFF, 0x00, 0x52, 0x00, 0x01],
                    [0xFF, 0x00, 0x52, 0x00, 0x02],
                    [0xFF, 0x00, 0x52, 0x00, 0x03],
                    # Some devices use FF 00 40 .. sequences for LED/buzzer control
                    [0xFF, 0x00, 0x40, 0x00, 0x01],
                ]

                # If we detect ACR122 in reader name, add specific candidates
                reader_name = str(r[0])
                if 'ACR' in reader_name.upper() or 'ACS' in reader_name.upper():
                    logger.info(f"Detected ACR reader: {reader_name} - trying ACR122U control APDUs")
                    candidates += [
                        [0xFF, 0x00, 0x51, 0x00, 0x01],
                        [0xFF, 0x00, 0x50, 0x00, 0x00],
                        [0xFF, 0x00, 0x50, 0x00, 0x01],
                    ]

                for apdu in candidates:
                    try:
                        resp, sw1, sw2 = conn.transmit(apdu)
                        # sw1==0x90 indicates success for a lot of readers
                        if sw1 == 0x90:
                            logger.info(f"Reader beep control APDU sent successfully: {apdu}")
                            try:
                                conn.disconnect()
                            except:
                                pass
                            return True
                    except Exception:
                        continue
            except Exception as e:
                logger.debug(f"pyscard control attempt failed: {e}")
    except Exception:
        pass

    # Try acr122u wrapper first (if available and supports set_beep)
    try:
        global acr122u_reader
        if acr122u_reader is not None:
            try:
                w = acr122u_reader.open_reader()
                if w and hasattr(w, 'set_beep'):
                    if w.set_beep(False):
                        logger.info('Disabled beep via acr122u reader API')
                        try:
                            w.close()
                        except Exception:
                            pass
                        return True
            except Exception:
                pass

    except Exception:
        pass

    # Try py122u-specific approach (if library exposes control API)
    try:
        global reader
        if reader is not None:
            # Some py122u-based readers may have attribute methods like `set_beep` or `set_led`.
            if hasattr(reader, 'set_beep'):
                try:
                    reader.set_beep(False)
                    logger.info('Disabled beep via py122u.set_beep')
                    return True
                except Exception:
                    pass
            if hasattr(reader, 'set_led'):
                try:
                    reader.set_led(False)
                    logger.info('Tried to turn off LED (may also disable beep)')
                    return True
                except Exception:
                    pass
    except Exception:
        pass

    logger.info('No hardware beep control available (or operation not supported)')
    return False


def validate_card_with_database(uid):
    """
    Validate NFC card UID with the external database server.
    
    Args:
        uid (str): The card UID in hex format
        
    Returns:
        bool: True if card is valid, False otherwise
    """
    try:
        # Prepare the form data
        payload = f'eingabe={uid}'
        
        logger.info(f"Validating card UID: {uid}")
        
        # Send POST request to database server
        response = requests.post(
            DATABASE_URL, 
            headers=VALIDATION_HEADERS, 
            data=payload,
            timeout=3  # 3 second timeout for faster response
        )
        
        # Check if request was successful (2xx status codes indicate success)
        is_valid = 200 <= response.status_code < 300
        
        logger.info(f"Card {uid} validation result: {'VALID' if is_valid else 'INVALID'} (Status: {response.status_code})")
        
        return is_valid
        
    except requests.exceptions.Timeout:
        logger.error(f"Timeout validating card {uid}")
        return False
    except requests.exceptions.RequestException as e:
        logger.error(f"Error validating card {uid}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error validating card {uid}: {e}")
        return False

def get_html_content():
    """
    Load the HTML content from the index.html file.
    Falls back to a basic template if file is not found.
    """
    try:
        with open('index.html', 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        logger.warning("index.html not found, using fallback template")
        return """
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NFC Reader</title>
</head>
<body>
    <h1>NFC Reader - Bitte index.html Datei hinzufügen</h1>
</body>
</html>
"""

def test_nfc_reader_availability():
    """
    Test if the NFC reader is available and working.
    Simply tries to create a reader instance.
    
    Returns:
        bool: True if reader is available, False otherwise
    """
    global reader, nfc_reader_available
    
    try:
        # Only create reader instance if it doesn't exist (lazy initialization)
        if reader is None:
            if nfc is None:
                logger.debug(f"nfc.Reader unavailable on {OS_NAME}")
                nfc_reader_available = False
                return False
            logger.debug(f"Creating NFC reader instance on {OS_NAME}...")
            reader = nfc.Reader()
        
        nfc_reader_available = True
        logger.debug(f"✅ NFC reader is available on {OS_NAME}")
        
        # Only emit events if we have active WebSocket connections
        try:
            socketio.emit('nfc_reader_available')
        except:
            pass  # Ignore WebSocket emission errors during startup
        
        return True
        
    except Exception as e:
        nfc_reader_available = False
        
        # Clean up on error
        if reader is not None:
            try:
                reader.close()
            except:
                pass
            reader = None
        
        logger.debug(f"NFC reader not available: {e}")
        
        # Only emit events if we have active WebSocket connections
        try:
            socketio.emit('nfc_reader_unavailable', {
                'error': str(e),
                'message': 'NFC-Lesegerät nicht erkannt',
                'os': OS_NAME
            })
        except:
            pass  # Ignore WebSocket emission errors during startup
            
        return False

def try_connect_and_get_uid():
    """
    Attempt to connect to NFC reader and get card UID using py_acr122u nfc.Reader.
    Uses non-blocking pattern from libnfc.py - connect() and get_uid() return immediately
    and raise exceptions if no card is present.
    
    Returns:
        str or None: Card UID in uppercase hex format, or None if no card/error
    """
    global nfc_reader_available, reader
    
    try:
        # Create reader if it doesn't exist (lazy initialization)
        if reader is None:
            if nfc is None:
                logger.debug('nfc.Reader unavailable (py_acr122u not installed)')
                return None
            logger.debug('Creating nfc.Reader instance')
            reader = nfc.Reader()
        
        # Non-blocking connect() and get_uid() - they return immediately
        # If no card is present, they raise exceptions which we catch as "no card"
        try:
            reader.connect()
            uid_response = reader.get_uid()
            
            # get_uid() returns a list of integers (the UID bytes)
            if uid_response:
                uid_hex = ''.join([f'{x:02X}' for x in uid_response])
                logger.info(f'Card detected! UID: {uid_hex}')
                nfc_reader_available = True
                return uid_hex
            else:
                logger.debug('get_uid() returned empty response')
                nfc_reader_available = False
                return None
        except Exception as e:
            # connect() or get_uid() raise exceptions when there's no card
            # We treat these as "no card available" - a normal polling state, not an error
            msg = str(e)
            if any(x in msg.lower() for x in ['card not connected', 'connect', 'no card', 'instruction', 'communication']):
                logger.debug(f'No card detected: {e}')
            else:
                logger.debug(f'Reader call raised exception: {e}')
            nfc_reader_available = False
            return None
    
    except Exception as e:
        # Unexpected error outside of connect/get_uid - reset reader for next attempt
        logger.debug(f'Unexpected error in try_connect_and_get_uid: {e}')
        nfc_reader_available = False
        if reader is not None:
            try:
                reader.close()
            except:
                pass
            reader = None
        return None

# Flask routes
@app.route('/')
def index():
    """Serve the main HTML page."""
    return Response(get_html_content(), mimetype='text/html')

@app.route('/fetch_html')
def fetch_html():
    """Legacy route for HTML content."""
    return Response(get_html_content(), mimetype='text/html')

last_uid = None
last_validation_result = None
reading_in_progress = False  # When True we are validating/processing a card

# pending_validations maps UID to a threading.Event used to cancel a background
# validation if the card is removed before validation completes.
pending_validations = {}
pending_validations_lock = threading.Lock()


def validate_card_async(uid: str, cancel_event: threading.Event):
    """
    Run card validation in a background thread to avoid blocking the main polling loop.
    If cancel_event is set during the procedure, the function will abort without emitting result events.
    """
    try:
        logger.info(f"Background validation started for {uid}")
        # Inform clients the validation is now in progress (distinct from 'processing')
        try:
            socketio.emit('card_validating', {
                'uid': uid,
                'message': 'Karte wird validiert',
                'timestamp': time.time()
            }, broadcast=True)
        except Exception:
            pass

        # Show progress update
        try:
            socketio.emit('card_progress', {'uid': uid, 'progress': 70}, broadcast=True)
        except Exception:
            pass

        # Run validation (blocking network call) - validate_card_with_database has its own timeout
        is_valid = validate_card_with_database(uid)

        # If the cancel event was set during the call, abort and do not emit a final outcome
        if cancel_event.is_set():
            logger.info(f"Validation cancelled for {uid}")
            try:
                socketio.emit('card_processing_cancelled', {
                    'uid': uid,
                    'message': 'Validierung abgebrochen (Karte entfernt)'
                }, broadcast=True)
            except Exception:
                pass
            return

        # Final progress
        try:
            socketio.emit('card_progress', {'uid': uid, 'progress': 100}, broadcast=True)
        except Exception:
            pass

        # Emit final result
        if is_valid:
            logger.info(f"Card {uid} validated (async)")
            try:
                socketio.emit('card_success', {'uid': uid, 'message': 'Karte berechtigt'}, broadcast=True)
            except Exception:
                pass
        else:
            logger.warning(f"Card {uid} invalid (async)")
            try:
                socketio.emit('card_unauthorized', {'uid': uid, 'message': 'Karte nicht berechtigt'}, broadcast=True)
            except Exception:
                pass

    except Exception as e:
        logger.error(f"Error in background validation for {uid}: {e}")
        try:
            socketio.emit('card_validation_error', {'uid': uid, 'message': str(e)}, broadcast=True)
        except Exception:
            pass
    finally:
        # Clean up pending validation entry and leave a small grace before allowing new reads
        with pending_validations_lock:
            try:
                pending_validations.pop(uid, None)
            except Exception:
                pass
        # Ensure the reading flag is cleared so new cards can be processed
        global reading_in_progress, last_uid
        reading_in_progress = False
        last_uid = None

# Read stability behaviour
CARD_STABILITY_CHECKS = 1  # number of consecutive equal UID samples for stability (1 = faster)
CARD_STABILITY_INTERVAL = 0.02  # seconds between stability samples (20ms)
CARD_PROCESSING_GRACE_PERIOD = 0.6  # seconds grace to wait for transient removals
POLL_INTERVAL = 0.3  # default polling interval

def card_check_loop():
    """
    Main card detection and validation loop.
    Checks for card presence, validates with database, and emits appropriate WebSocket events.
    """
    global last_uid, last_validation_result, nfc_reader_available
    
    logger.info("Starting NFC card monitoring loop")
    
    # Don't aggressively test NFC reader on startup - let it initialize naturally
    # This matches the old version's behavior where reader was only tested when needed
    logger.info("NFC reader will be initialized on first card detection attempt")
    
    while True:
        try:
            # Simple approach like the old version - just try to read cards
            uid = try_connect_and_get_uid()
            
            if uid:
                # New card detected
                if uid != last_uid and not reading_in_progress:
                    last_uid = uid
                    logger.info(f"New card detected (pending validation): {uid}")

                    # Emit 'card_processing' to tell clients to wait and hold their card
                    reading_in_progress = True
                    socketio.emit('card_processing', {
                        'uid': uid,
                        'message': 'Bitte halten Sie die Karte bis die Lesung abgeschlossen ist',
                        'timestamp': time.time()
                    }, broadcast=True)
                    # Start progress with a small initial value
                    socketio.emit('card_progress', {
                        'uid': uid,
                        'progress': 10,
                    }, broadcast=True)

                    # Stability sampling: ensure the UID reads stable for N checks
                    stable = False
                    sampled_uid = uid
                    checks = 0
                    start_time = time.time()
                    while checks < CARD_STABILITY_CHECKS and (time.time() - start_time) < 1.0:
                        time.sleep(CARD_STABILITY_INTERVAL)
                        cur = try_connect_and_get_uid()
                        if cur == sampled_uid:
                            checks += 1
                            # Update progress for each stability check
                            progress = 10 + int(30 * (checks / float(CARD_STABILITY_CHECKS)))
                            socketio.emit('card_progress', {
                                'uid': sampled_uid,
                                'progress': progress,
                            })
                        else:
                            # If the card changed or was removed, update sampled_uid and reset checks
                            sampled_uid = cur
                            checks = 0
                            # If removed entirely, break and treat as removal
                            if sampled_uid is None:
                                break

                    # If the card has been removed during stability sampling, don't validate
                    if sampled_uid is None:
                        logger.info("Card removed during processing stability checks")
                        reading_in_progress = False
                        # Emit a 'card_processing_cancelled' event so UI can update accordingly
                        socketio.emit('card_processing_cancelled', {
                            'message': 'Karte entfernt - Bitte erneut halten',
                            'timestamp': time.time()
                        })
                        # Signal any ongoing background validation to cancel
                        with pending_validations_lock:
                            cancel_event = pending_validations.get(uid)
                        if cancel_event:
                            cancel_event.set()
                        socketio.emit('card_progress', {
                            'uid': uid,
                            'progress': 0,
                        })
                        # Keep last_uid None so the next detection is treated freshly
                        last_uid = None
                        continue

                    # Continue with validation for the stable UID, but do it asynchronously
                    socketio.emit('card_progress', {
                        'uid': sampled_uid,
                        'progress': 60,
                    })
                    # If no existing validation is pending for this UID, start a background validator
                    with pending_validations_lock:
                        if sampled_uid not in pending_validations:
                            cancel_event = threading.Event()
                            pending_validations[sampled_uid] = cancel_event
                            logger.debug(f"Spawning async validation thread for UID {sampled_uid}")
                            t = threading.Thread(target=validate_card_async, args=(sampled_uid, cancel_event), daemon=True)
                            t.start()
            else:
                # Card removed or no card present
                if last_uid is not None and not reading_in_progress:
                    logger.info(f"Card {last_uid} removed")
                    # If a pending validation exists for this UID, cancel it
                    with pending_validations_lock:
                        cancel_event = pending_validations.get(last_uid) if last_uid else None
                    if cancel_event:
                        cancel_event.set()
                    last_uid = None
                    last_validation_result = None
                    socketio.emit('reload')
                elif last_uid is not None and reading_in_progress:
                    # Card was removed during processing: wait for grace period before treating removal
                    grace_start = time.time()
                    while time.time() - grace_start < CARD_PROCESSING_GRACE_PERIOD:
                        time.sleep(CARD_STABILITY_INTERVAL)
                        cur = try_connect_and_get_uid()
                        if cur is not None:
                            break
                    # After grace, if still no card, cancel reading and notify UI
                    cur = try_connect_and_get_uid()
                    if cur is None:
                        logger.info("Card removed during processing grace period")
                        # Cancel processing if needed
                        reading_in_progress = False
                        # Signal any ongoing background validation to cancel
                        with pending_validations_lock:
                            cancel_event = None
                            try:
                                cancel_event = pending_validations.get(last_uid)
                            except Exception:
                                cancel_event = None
                        if cancel_event:
                            cancel_event.set()
                        last_uid = None
                        last_validation_result = None
                        socketio.emit('card_processing_cancelled', {
                            'message': 'Karte entfernt - Bitte erneut halten',
                            'timestamp': time.time()
                        })
                        socketio.emit('card_progress', {
                            'uid': last_uid,
                            'progress': 0,
                        })
                    
        except Exception as e:
            # Simple error handling like old version
            if last_uid is not None:
                logger.info("Card removed (exception)")
                # Cancel any pending validation for this UID
                with pending_validations_lock:
                    cancel_event = pending_validations.get(last_uid) if last_uid else None
                if cancel_event:
                    cancel_event.set()
                last_uid = None
                last_validation_result = None
                socketio.emit('reload')

        # Poll at regular interval
        time.sleep(POLL_INTERVAL)

def get_current_version():
    """Get the current version from version file"""
    try:
        with open(VERSION_FILE, 'r') as f:
            version_data = json.load(f)
            return version_data
    except (FileNotFoundError, json.JSONDecodeError):
        # Default version info if file doesn't exist
        logger.warning(f"Version file not found or invalid, using default version")
        return {
            'tag_name': 'v0.0.0',
            'updated_at': datetime.now().isoformat(),
            'commit_sha': 'unknown'
        }

def save_current_version(version_data):
    """Save version information to file"""
    try:
        with open(VERSION_FILE, 'w') as f:
            json.dump(version_data, f, indent=2)
        logger.info(f"Saved version info: {version_data['tag_name']}")
    except Exception as e:
        logger.error(f"Failed to save version info: {e}")

def check_for_updates():
    """Check GitHub for new releases"""
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            latest_release = response.json()
            current_version = get_current_version()
            
            if latest_release['tag_name'] != current_version['tag_name']:
                logger.info(f"New version available: {latest_release['tag_name']} (current: {current_version['tag_name']})")
                return latest_release
            else:
                logger.info(f"Current version {current_version['tag_name']} is up to date")
                return None
        else:
            logger.warning(f"Failed to check for updates: HTTP {response.status_code}")
            return None
            
    except Exception as e:
        logger.error(f"Error checking for updates: {e}")
        return None

def backup_current_files():
    """Create backup of current files before update"""
    try:
        # Ensure backup directory exists (cross-platform)
        backup_dir_path = os.path.abspath(BACKUP_DIR)
        if not os.path.exists(backup_dir_path):
            os.makedirs(backup_dir_path, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_subdir = os.path.join(backup_dir_path, f"backup_{timestamp}")
        os.makedirs(backup_subdir, exist_ok=True)
        
        # Files to backup
        files_to_backup = ['app.py', 'index.html']
        backed_up_files = []
        
        for filename in files_to_backup:
            source_path = os.path.abspath(filename)
            if os.path.exists(source_path):
                dest_path = os.path.join(backup_subdir, filename)
                shutil.copy2(source_path, dest_path)
                backed_up_files.append(filename)
                logger.info(f"Backed up {filename} to {dest_path}")
        
        logger.info(f"Created backup in {backup_subdir} ({OS_NAME}) - Files: {', '.join(backed_up_files)}")
        return backup_subdir
        
    except Exception as e:
        logger.error(f"Failed to create backup on {OS_NAME}: {e}")
        return None

def download_release_files(release_info):
    """Download app.py and index.html from the latest release"""
    try:
        # Get the download URLs for the release files
        tarball_url = release_info.get('tarball_url')
        
        if not tarball_url:
            logger.error("No tarball URL found in release")
            return False
        
        # Download the release tarball
        logger.info(f"Downloading release {release_info['tag_name']}...")
        response = requests.get(tarball_url, timeout=30)
        
        if response.status_code == 200:
            # Save tarball temporarily
            import tempfile
            import tarfile
            
            with tempfile.NamedTemporaryFile(suffix='.tar.gz', delete=False) as tmp_file:
                tmp_file.write(response.content)
                tmp_path = tmp_file.name
            
            # Extract the files we need
            with tarfile.open(tmp_path, 'r:gz') as tar:
                members = tar.getmembers()
                
                # Find app.py and index.html in the tarball
                app_py_member = None
                index_html_member = None
                
                for member in members:
                    if member.name.endswith('app.py'):
                        app_py_member = member
                    elif member.name.endswith('index.html'):
                        index_html_member = member
                
                # Extract and save the files (cross-platform)
                temp_extract_dir = tempfile.mkdtemp()
                
                if app_py_member:
                    tar.extract(app_py_member, path=temp_extract_dir)
                    extracted_app_py = os.path.join(temp_extract_dir, app_py_member.name)
                    dest_app_py = os.path.abspath('app.py.new')
                    shutil.move(extracted_app_py, dest_app_py)
                    logger.info(f"Downloaded new app.py to {dest_app_py} ({OS_NAME})")
                
                if index_html_member:
                    tar.extract(index_html_member, path=temp_extract_dir)
                    extracted_index_html = os.path.join(temp_extract_dir, index_html_member.name)
                    dest_index_html = os.path.abspath('index.html.new')
                    shutil.move(extracted_index_html, dest_index_html)
                    logger.info(f"Downloaded new index.html to {dest_index_html} ({OS_NAME})")
                
                # Clean up temp extraction directory
                try:
                    shutil.rmtree(temp_extract_dir)
                except:
                    pass
            
            # Clean up temp file
            os.unlink(tmp_path)
            
            return app_py_member is not None or index_html_member is not None
        else:
            logger.error(f"Failed to download release: HTTP {response.status_code}")
            return False
            
    except Exception as e:
        logger.error(f"Error downloading release files: {e}")
        return False

def apply_update(release_info):
    """Apply the downloaded update"""
    try:
        updated_files = []
        
        # File replacement mapping
        file_replacements = {
            'app.py.new': 'app.py',
            'index.html.new': 'index.html'
        }
        
        for new_file, target_file in file_replacements.items():
            new_file_path = os.path.abspath(new_file)
            target_file_path = os.path.abspath(target_file)
            
            if os.path.exists(new_file_path):
                try:
                    # Cross-platform file replacement
                    if os.path.exists(target_file_path):
                        if IS_WINDOWS:
                            # On Windows, remove target first if it exists
                            os.remove(target_file_path)
                            shutil.move(new_file_path, target_file_path)
                        else:
                            # On Linux/Unix, os.replace works reliably
                            os.replace(new_file_path, target_file_path)
                    else:
                        # Target doesn't exist, just rename
                        shutil.move(new_file_path, target_file_path)
                    
                    updated_files.append(target_file)
                    logger.info(f"Updated {target_file} ({OS_NAME})")
                    
                except Exception as e:
                    logger.error(f"Failed to update {target_file} on {OS_NAME}: {e}")
                    # Clean up the new file if update failed
                    try:
                        os.remove(new_file_path)
                    except:
                        pass
        
        if updated_files:
            # Save new version info
            version_data = {
                'tag_name': release_info['tag_name'],
                'updated_at': datetime.now().isoformat(),
                'commit_sha': release_info.get('target_commitish', 'unknown'),
                'updated_files': updated_files
            }
            save_current_version(version_data)
            
            logger.info(f"Successfully updated to version {release_info['tag_name']}")
            
            # Check if app.py was updated (requires restart)
            app_py_updated = 'app.py' in updated_files
            
            # Emit update notification to connected clients
            socketio.emit('system_updated', {
                'version': release_info['tag_name'],
                'files': updated_files,
                'restart_required': app_py_updated,
                'restart_delay': RESTART_DELAY if app_py_updated else 0
            })
            
            # Schedule automatic restart if app.py was updated
            if app_py_updated:
                logger.info(f"app.py was updated, scheduling restart in {RESTART_DELAY} seconds...")
                threading.Thread(target=schedule_restart, daemon=True).start()
            
            return True
        else:
            logger.warning("No files were updated")
            return False
            
    except Exception as e:
        logger.error(f"Error applying update: {e}")
        return False

def perform_update():
    """Check for updates and apply them if available"""
    logger.info("Checking for updates...")
    
    try:
        release_info = check_for_updates()
        
        if not release_info:
            # No updates available - notify client and reset status
            current_version = get_current_version()
            logger.info("No updates available")
            socketio.emit('update_check_complete', {
                'updates_available': False,
                'current_version': current_version['tag_name'],
                'message': 'Keine Updates verfügbar',
                'checked_at': datetime.now().isoformat()
            })
            return False
        
        logger.info(f"Found new version: {release_info['tag_name']}")
        
        # Updates available - notify client
        current_version = get_current_version()
        socketio.emit('update_check_complete', {
            'updates_available': True,
            'current_version': current_version['tag_name'],
            'new_version': release_info['tag_name'],
            'message': f'Update verfügbar: {release_info["tag_name"]}',
            'checked_at': datetime.now().isoformat()
        })
        
        # Create backup
        backup_dir = backup_current_files()
        if not backup_dir:
            logger.error("Failed to create backup, aborting update")
            socketio.emit('update_error', {
                'error': 'Backup-Erstellung fehlgeschlagen',
                'message': 'Update abgebrochen'
            })
            return False
        
        # Download new files
        if not download_release_files(release_info):
            logger.error("Failed to download release files")
            socketio.emit('update_error', {
                'error': 'Download fehlgeschlagen',
                'message': 'Update konnte nicht heruntergeladen werden'
            })
            return False
        
        # Apply update
        if apply_update(release_info):
            logger.info("Update completed successfully")
            return True
        else:
            logger.error("Failed to apply update")
            socketio.emit('update_error', {
                'error': 'Installation fehlgeschlagen',
                'message': 'Update konnte nicht angewendet werden'
            })
            return False
            
    except Exception as e:
        logger.error(f"Error during update process: {e}")
        socketio.emit('update_error', {
            'error': str(e),
            'message': 'Unerwarteter Fehler beim Update'
        })
        return False

def schedule_restart():
    """Schedule automatic restart after app.py update"""
    try:
        # Send countdown notifications to clients
        for remaining in range(RESTART_DELAY, 0, -1):
            socketio.emit('restart_countdown', {
                'seconds_remaining': remaining,
                'message': f'Server wird in {remaining} Sekunden neugestartet...'
            })
            time.sleep(1)
        
        # Final notification
        socketio.emit('restart_countdown', {
            'seconds_remaining': 0,
            'message': 'Server wird jetzt neugestartet...'
        })
        
        logger.info("Initiating automatic restart...")
        time.sleep(2)  # Longer pause to ensure messages are sent
        
        # Restart the Python process
        restart_application()
        
    except Exception as e:
        logger.error(f"Error during scheduled restart: {e}")
        # Emit error notification to clients
        socketio.emit('restart_error', {
            'message': 'Fehler beim Neustart! Manueller Neustart erforderlich.',
            'error': str(e)
        })

def restart_application():
    """Restart the current Python application with proper Flask shutdown"""
    try:
        logger.info("🔄 Initiating application restart with updated code...")
        
        # Notify clients about restart
        try:
            socketio.emit('server_restart', {'message': 'Server wird neugestartet...'})
            socketio.sleep(1)  # Give time for message to be sent
        except:
            pass
        
        # Close any open resources gracefully
        cleanup_nfc_reader()
        
        # Get the current Python executable and script arguments
        python_executable = sys.executable
        script_args = sys.argv.copy()
        
        # Use different restart methods based on OS
        logger.info(f"Restarting application on {OS_NAME}")
        
        if IS_WINDOWS:
            # Windows-specific restart with delayed start
            
            current_dir = os.getcwd()
            logger.info(f"Windows restart command: {python_executable} {' '.join(script_args)}")
            
            try:
                # Create a Python script for port waiting (more reliable than embedded code)
                port_wait_script = f"""
import socket
import time
import sys

def is_port_available(host='localhost', port=5000, timeout=1):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            return result != 0
    except Exception:
        return True


    def check_pcsc_service():
#        "Quick diagnostic: check if pcscd / pyscard is installed and returns a reader list."
        try:
            from smartcard.System import readers as sc_readers
        except Exception:
            logger.info('pyscard (smartcard) not installed: `pip install pyscard` to enable PC/SC checks')
            return False

        try:
            r = sc_readers()
            logger.debug(f'PC/SC readers available via pyscard: {r}')
            if not r:
                # If running on Linux, hint to check the pcscd service
                if IS_LINUX:
                    try:
                        import subprocess
                        out = subprocess.check_output(['systemctl', 'is-active', 'pcscd'], stderr=subprocess.DEVNULL, universal_newlines=True)
                        if out.strip() == 'active':
                            logger.debug('pcscd service is active but no readers found - try unplug/replug the device or check udev rules')
                        else:
                            logger.warning('pcscd service appears inactive. Try: sudo systemctl enable --now pcscd')
                    except Exception:
                        logger.debug('Could not detect pcscd service state - if on Linux, make sure pcscd/pcscd.service is installed and running')
                return False
            return True
        except Exception as e:
            logger.debug(f'PC/SC readers check failed: {e}')
            return False

def wait_for_port_available(host='localhost', port=5000, max_wait_time=60, check_interval=0.5):
    start_time = time.time()
    attempts = 0
    while time.time() - start_time < max_wait_time:
        attempts += 1
        if is_port_available(host, port):
            print(f'Port {{port}} is now available (checked {{attempts}} times)')
            return True
        if attempts % 4 == 0:  # Print status every 2 seconds
            elapsed = int(time.time() - start_time)
            print(f'Still waiting for port {{port}}... ({{elapsed}}s elapsed)')
        time.sleep(check_interval)
    print(f'Timeout: Port {{port}} still not available after {{max_wait_time}}s')
    return False

if __name__ == '__main__':
    print('Checking if port 5000 is available...')
    if wait_for_port_available():
        print('Port 5000 is available, waiting additional 3 seconds for OS to fully release it...')
        time.sleep(3)  # Additional delay to ensure OS fully releases the port
        print('Ready to start new instance...')
        sys.exit(0)
    else:
        print('Warning: Starting anyway after timeout')
        sys.exit(0)
"""
                
                # Write the port waiting Python script
                port_wait_script_path = os.path.join(current_dir, "port_wait_temp.py")
                with open(port_wait_script_path, 'w') as f:
                    f.write(port_wait_script)
                
                # Create a batch script that uses the Python script
                restart_script = f"""
@echo off
echo Waiting for port 5000 to become available...
"{python_executable}" "{port_wait_script_path}"
if %ERRORLEVEL% EQU 0 (
    echo Starting new instance...
    cd /d "{current_dir}"
    "{python_executable}" {' '.join(script_args)}
) else (
    echo Port wait failed, but starting anyway...
    cd /d "{current_dir}"
    "{python_executable}" {' '.join(script_args)}
)
"""
                
                # Write the restart script to a temporary file
                restart_script_path = os.path.join(current_dir, "restart_temp.bat")
                with open(restart_script_path, 'w') as f:
                    f.write(restart_script)
                
                # Start the delayed restart script
                if DRY_RUN:
                    logger.info(f"DRY RUN: Would launch Windows restart script: {restart_script_path}")
                else:
                    subprocess.Popen(
                        ["cmd", "/c", restart_script_path],
                        cwd=current_dir,
                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
                        close_fds=True,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )

                logger.info("🚀 Windows: Delayed restart script launched, shutting down current instance...")
                
                # Properly exit the Flask application instead of using os._exit()
                # This allows the Flask server to properly release the port
                time.sleep(2)  # Brief pause to ensure script is launched
                
                # Initiate graceful shutdown
                logger.info("💀 Initiating graceful Flask server shutdown...")
                
                # Method 1: Try to stop SocketIO server gracefully
                try:
                    logger.info("� Stopping SocketIO server...")
                    try:
                        stop_server()
                    except Exception:
                        # Fallback to the socketio instance in case stop_server isn't supported
                        socketio.stop()
                    logger.info("✅ SocketIO server stopped successfully")
                except Exception as e:
                    logger.warning(f"⚠️  SocketIO stop failed: {e}")
                
                # Method 2: Give time for connections to close
                time.sleep(1)
                
                # Method 3: Force close any remaining sockets (Windows specific)
                try:
                    import gc
                    gc.collect()  # Force garbage collection to clean up sockets
                except:
                    pass
                
                # Method 4: Exit cleanly to allow OS to reclaim port
                logger.info("🔚 Exiting application process cleanly...")
                
                # Use sys.exit() instead of os._exit() for cleaner shutdown
                if DRY_RUN:
                    logger.info("DRY RUN: Skipping process exit during restart (Windows)")
                else:
                    sys.exit(0)
                
            except Exception as e:
                logger.error(f"❌ Windows subprocess restart failed: {e}")
                raise
                
        elif IS_LINUX:
            # Linux/Unix-specific restart with delay to avoid port conflicts
            logger.info(f"Linux restart command: {python_executable} {' '.join(script_args)}")
            
            try:
                # Create a shell script with extended port waiting
                current_dir = os.getcwd()
                
                # Create a Python script for port waiting (consistent with Windows approach)
                port_wait_script = f"""
import socket
import time
import sys

def is_port_available(host='localhost', port=5000, timeout=1):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            return result != 0
    except Exception:
        return True

def wait_for_port_available(host='localhost', port=5000, max_wait_time=60, check_interval=0.5):
    start_time = time.time()
    attempts = 0
    while time.time() - start_time < max_wait_time:
        attempts += 1
        if is_port_available(host, port):
            print(f'Port {{port}} is now available (checked {{attempts}} times)')
            return True
        if attempts % 4 == 0:  # Print status every 2 seconds
            elapsed = int(time.time() - start_time)
            print(f'Still waiting for port {{port}}... ({{elapsed}}s elapsed)')
        time.sleep(check_interval)
    print(f'Timeout: Port {{port}} still not available after {{max_wait_time}}s')
    return False

if __name__ == '__main__':
    print('Checking if port 5000 is available...')
    if wait_for_port_available():
        print('Port 5000 is available, waiting additional 3 seconds for OS to fully release it...')
        time.sleep(3)  # Additional delay to ensure OS fully releases the port
        print('Ready to start new instance...')
        sys.exit(0)
    else:
        print('Warning: Starting anyway after timeout')
        sys.exit(0)
"""
                
                # Write the port waiting Python script
                port_wait_script_path = os.path.join(current_dir, "port_wait_temp.py")
                with open(port_wait_script_path, 'w') as f:
                    f.write(port_wait_script)
                
                # Create a shell script that uses the Python script
                restart_script = f"""#!/bin/bash
echo "Waiting for port 5000 to become available..."
"{python_executable}" "{port_wait_script_path}"
if [ $? -eq 0 ]; then
    echo "Starting new instance..."
    cd "{current_dir}"
    "{python_executable}" {' '.join(script_args)}
else
    echo "Port wait failed, but starting anyway..."
    cd "{current_dir}"
    "{python_executable}" {' '.join(script_args)}
fi
"""
                
                # Write the restart script to a temporary file
                restart_script_path = os.path.join(current_dir, "restart_temp.sh")
                with open(restart_script_path, 'w') as f:
                    f.write(restart_script)
                
                # Make the script executable
                os.chmod(restart_script_path, 0o755)
                
                # Start the delayed restart script
                if DRY_RUN:
                    logger.info(f"DRY RUN: Would launch Linux restart script: {restart_script_path}")
                else:
                    subprocess.Popen(
                        ["/bin/bash", restart_script_path],
                        cwd=current_dir,
                        start_new_session=True,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )

                logger.info("🚀 Linux: Delayed restart script launched, shutting down current instance...")
                
                # Properly exit the Flask application instead of using os._exit()
                time.sleep(2)  # Brief pause to ensure script is launched
                
                # Initiate graceful shutdown
                logger.info("💀 Initiating graceful Flask server shutdown...")
                
                # Method 1: Try to stop SocketIO server gracefully
                try:
                    logger.info("� Stopping SocketIO server...")
                    try:
                        stop_server()
                    except Exception:
                        socketio.stop()
                    logger.info("✅ SocketIO server stopped successfully")
                except Exception as e:
                    logger.warning(f"⚠️  SocketIO stop failed: {e}")
                
                # Method 2: Give time for connections to close
                time.sleep(1)
                
                # Method 3: Force garbage collection to clean up sockets
                try:
                    import gc
                    gc.collect()
                except:
                    pass
                
                # Method 4: Exit cleanly using sys.exit() to allow proper cleanup
                logger.info("� Exiting application process cleanly...")
                if DRY_RUN:
                    logger.info("DRY RUN: Skipping process exit during restart (Linux)")
                else:
                    sys.exit(0)
                
            except Exception as e:
                logger.error(f"❌ Linux subprocess restart failed: {e}")
                # Fallback to traditional method with a delay
                time.sleep(3)
                os.execv(python_executable, [python_executable] + script_args)
                
        else:
            # Fallback for other systems
            logger.warning(f"Unknown OS ({os.name}), using fallback restart method")
            os.execv(python_executable, [python_executable] + script_args)
        
    except Exception as e:
        logger.error(f"Failed to restart application: {e}")
        logger.error("Manual restart required!")
        # Fallback: try the old method
        try:
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception as e2:
            logger.error(f"Fallback restart also failed: {e2}")

def update_check_loop():
    """Background thread to periodically check for updates"""
    if not AUTO_UPDATE_ENABLED:
        logger.info("Auto-update is disabled, update check loop will not run")
        return
    
    logger.info("Auto-update check loop started")
    while True:
        try:
            # Double-check in case the flag was changed during runtime
            if AUTO_UPDATE_ENABLED:
                perform_update()
            else:
                logger.info("Auto-update disabled during runtime, stopping update loop")
                break
        except Exception as e:
            logger.error(f"Error in update check loop: {e}")
        
        # Wait for next check
        time.sleep(UPDATE_CHECK_INTERVAL)

@socketio.on('check_for_updates')
def handle_check_for_updates():
    """Manual update check triggered by client"""
    if not AUTO_UPDATE_ENABLED:
        logger.warning("Manual update check requested, but auto-update is disabled")
        socketio.emit('update_disabled', {
            'message': 'Auto-Update ist deaktiviert (--no-auto-update flag aktiv)',
            'reason': 'disabled_by_flag'
        })
        return
    
    logger.info("Manual update check requested")
    threading.Thread(target=perform_update, daemon=True).start()

@socketio.on('get_version_info')
def handle_get_version_info():
    """Send current version info to client"""
    logger.info("🔍 Client requested version info")
    version_info = get_current_version()
    version_info['auto_update_enabled'] = AUTO_UPDATE_ENABLED
    logger.info(f"📡 Sending version info to client: {version_info}")
    logger.info(f"🏷️  Tag name being sent: '{version_info.get('tag_name')}'")
    socketio.emit('version_info', version_info)
    logger.info("✅ Version info emission completed")

@socketio.on('reinitialize_nfc_reader')
def handle_reinitialize_nfc_reader():
    """Manual NFC reader reinitialization triggered by client"""
    logger.info("Manual NFC reader reinitialization requested")
    
    def reinit_reader():
        try:
            cleanup_nfc_reader()
            time.sleep(1)  # Brief pause
            success = test_nfc_reader_availability()
            
            socketio.emit('nfc_reader_reinit_result', {
                'success': success,
                'message': 'NFC-Lesegerät erfolgreich neu initialisiert' if success else 'NFC-Lesegerät Initialisierung fehlgeschlagen',
                'os': OS_NAME
            })
        except Exception as e:
            logger.error(f"Error during manual NFC reader reinitialization: {e}")
            socketio.emit('nfc_reader_reinit_result', {
                'success': False,
                'message': f'Fehler bei Neuinitialisierung: {str(e)}',
                'os': OS_NAME
            })
    
    threading.Thread(target=reinit_reader, daemon=True).start()

@socketio.on('get_nfc_reader_status')
def handle_get_nfc_reader_status():
    """Send current NFC reader status to client"""
    socketio.emit('nfc_reader_status', {
        'available': nfc_reader_available,
        'reader_exists': reader is not None,
        'os': OS_NAME
    })

def is_port_available(host='localhost', port=5000, timeout=1):
    """
    Check if a specific port is available (not in use).
    
    Args:
        host (str): Host to check (default: localhost)
        port (int): Port number to check (default: 5000)
        timeout (int): Connection timeout in seconds
        
    Returns:
        bool: True if port is available, False if in use
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            # If connection fails, port is available
            return result != 0
    except Exception:
        # If any error occurs, assume port is available
        return True


def _parse_netstat_windows_port_pids(port: int):
    """Return a set of PIDs using `netstat -ano` for a given TCP port on Windows.
    """
    pids = set()
    try:
        out = subprocess.check_output(['netstat', '-ano', '-p', 'tcp'], stderr=subprocess.DEVNULL, universal_newlines=True)
        for line in out.splitlines():
            if f':{port} ' in line or f':{port}\r' in line:
                parts = line.split()
                if len(parts) >= 5:
                    try:
                        pid = int(parts[-1])
                        pids.add(pid)
                    except Exception:
                        pass
    except Exception as e:
        logger.debug(f"Windows netstat failed: {e}")
    return pids


def _get_pids_using_port_linux(port: int):
    """Return a set of PIDs using `lsof` or `ss` on Linux/Unix for the given port."""
    pids = set()
    try:
        out = subprocess.check_output(['lsof', '-i', f':{port}'], stderr=subprocess.DEVNULL, universal_newlines=True)
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2:
                try:
                    pid = int(parts[1])
                    pids.add(pid)
                except Exception:
                    pass
        return pids
    except Exception:
        # fallback to ss for listening ports
        try:
            out = subprocess.check_output(['ss', '-ltnp'], stderr=subprocess.DEVNULL, universal_newlines=True)
            for line in out.splitlines():
                if f':{port} ' in line or f':{port}:' in line:
                    # attempt to parse 'pid=1234,' pattern in the line
                    if 'pid=' in line:
                        try:
                            # find substring between pid= and comma
                            start = line.find('pid=') + 4
                            end = line.find(',', start)
                            if end == -1:
                                end = len(line)
                            pid = int(line[start:end])
                            pids.add(pid)
                        except Exception:
                            pass
        except Exception as e:
            logger.debug(f"ss fallback failed: {e}")
    return pids


def get_pids_using_port(port: int):
    """Return a list of OS PIDs using the specified TCP port (best-effort)."""
    if IS_WINDOWS:
        return _parse_netstat_windows_port_pids(port)
    else:
        return _get_pids_using_port_linux(port)


def kill_pid(pid: int, wait: bool = False):
    """Kill a PID cross-platform. Returns True if kill attempt was successful.

    This uses 'taskkill' on Windows and 'kill' on Unix. We try polite kill first then force.
    """
    try:
        if IS_WINDOWS:
            subprocess.check_call(['taskkill', '/PID', str(pid), '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        else:
            os.kill(pid, 15)  # SIGTERM
            if wait:
                for _ in range(10):
                    try:
                        os.kill(pid, 0)
                        time.sleep(0.1)
                    except OSError:
                        return True
            return True
    except Exception as e:
        try:
            # As a fallback, try to force kill
            if not IS_WINDOWS:
                os.kill(pid, 9)  # SIGKILL
                return True
        except Exception:
            logger.debug(f"Failed to kill PID {pid}: {e}")
        return False


def kill_processes_using_port(port: int, exclude_current: bool = True, dry_run: bool = False):
    """Attempt to kill all processes using the specified TCP port.

    Returns a tuple (killed_pids, failed_pids).
    """
    try:
        current_pid = os.getpid() if exclude_current else None
        pids = get_pids_using_port(port)
        if not pids:
            logger.debug(f"No processes found using port {port}")
            return ([], [])

        killed = []
        failed = []
        logger.info(f"Found processes using port {port}: {pids}")
        for pid in pids:
            if exclude_current and pid == current_pid:
                logger.info(f"Skipping own PID {pid}")
                continue
            try:
                logger.info(f"Attempting to kill PID {pid} using port {port}")
                if dry_run:
                    logger.info(f"DRY RUN: Would kill PID: {pid}")
                    failed.append(pid)
                    continue
                ok = kill_pid(pid, wait=True)
                if ok:
                    killed.append(pid)
                else:
                    failed.append(pid)
            except Exception as e:
                failed.append(pid)
                logger.warning(f"Failed to kill {pid}: {e}")

        return (killed, failed)
    except Exception as e:
        logger.error(f"Error while killing processes using port {port}: {e}")
        return ([], [])

def wait_for_port_available(host='localhost', port=5000, max_wait_time=30, check_interval=0.5):
    """
    Wait until a specific port becomes available.
    
    Args:
        host (str): Host to check
        port (int): Port number to check
        max_wait_time (int): Maximum time to wait in seconds
        check_interval (float): Time between checks in seconds
        
    Returns:
        bool: True if port became available, False if timeout reached
    """
    start_time = time.time()
    while time.time() - start_time < max_wait_time:
        if is_port_available(host, port):
            return True
        time.sleep(check_interval)
    return False

def cleanup_temporary_files():
    """Clean up temporary restart script files"""
    try:
        temp_files = ["restart_temp.bat", "restart_temp.sh", "port_wait_temp.py"]
        for temp_file in temp_files:
            if os.path.exists(temp_file):
                os.remove(temp_file)
                logger.debug(f"Cleaned up temporary file: {temp_file}")
    except Exception as e:
        logger.debug(f"Error cleaning temporary files: {e}")

if __name__ == '__main__':
    # Parse command line arguments first
    args = parse_command_line_arguments()
    # Enable dry-run globally if requested
    if hasattr(args, 'dry_run') and args.dry_run:
        DRY_RUN = True
        logger.info('Dry-run mode enabled; actions will be simulated and no processes will be killed or scripts launched')
    # Apply new flags
    if hasattr(args, 'no_beep') and args.no_beep:
        DISABLE_READER_BEEP = True
        logger.info('Attempting to disable reader beep (best-effort)')
        # Best-effort call
        try_disable_reader_beep()
    # Fast read mode flag removed - now always uses blocking get_uid() pattern
    
    # Clean up any leftover temporary restart scripts
    cleanup_temporary_files()
    
    logger.info("=" * 60)
    logger.info("Starting NFC Reader Application")
    logger.info(f"Operating System: {OS_NAME}")
    logger.info(f"Python Version: {sys.version}")
    logger.info(f"Working Directory: {os.getcwd()}")
    logger.info(f"Auto-Update: {'✅ Enabled' if AUTO_UPDATE_ENABLED else '🚫 Disabled'}")
    
    # Show current version
    current_version = get_current_version()
    logger.info(f"Current version: {current_version['tag_name']}")
    logger.info("=" * 60)
    # Check PC/SC availability and log hints for troubleshooting
    try:
        pcsc_ok = check_pcsc_service()
        logger.info(f'PC/SC (pyscard) available: {pcsc_ok}')
        if not pcsc_ok:
            logger.info('If your reader is not detected, consider installing/enabling pcscd and adding udev rules; see readme or app logs for details.')
    except Exception:
        logger.debug('PC/SC check skipped due to lack of pyscard or systemctl detection')
    
    # Start card monitoring thread (it will handle NFC reader initialization)
    monitoring_thread = threading.Thread(target=card_check_loop, daemon=True)
    monitoring_thread.start()
    logger.info("Card monitoring thread started")
    
    # Start auto-update monitoring thread only if auto-update is enabled
    if AUTO_UPDATE_ENABLED:
        update_thread = threading.Thread(target=update_check_loop, daemon=True)
        update_thread.start()
        logger.info("Auto-update monitoring thread started")
    else:
        logger.info("Auto-update monitoring thread skipped (disabled via command line flag)")

    # Start Flask-SocketIO server with enhanced port checking
    flask_port = 5000
    
    # Enhanced port availability check with longer wait time for restart scenarios
    if not is_port_available(port=flask_port):
        logger.warning(f"Port {flask_port} is currently in use. Waiting for it to become available...")
        logger.info("This is normal during automatic restarts after updates...")
        
        # Use longer wait time to handle restart scenarios properly
        if wait_for_port_available(port=flask_port, max_wait_time=60):
            logger.info(f"✅ Port {flask_port} is now available after waiting")
        else:
            logger.error(f"❌ Port {flask_port} is still not available after 60 seconds")
            logger.error("This may indicate another instance is still running or a system issue")
            logger.error("Attempting to start anyway, but this may fail...")
            # If requested, try to kill processes using the port before attempting the server start
            if hasattr(args, 'kill_port') and args.kill_port:
                logger.info(f"Attempting to kill any process using port {flask_port} (user requested)")
                killed, failed = kill_processes_using_port(flask_port, dry_run=DRY_RUN)
                logger.info(f"Killed PIDs: {killed}")
                if failed:
                    logger.warning(f"Failed to kill PIDs: {failed}")
                # Give a brief pause for OS to reclaim the port
                time.sleep(0.5)
    else:
        logger.debug(f"Port {flask_port} is immediately available")
    
    # Start Flask server with retry logic for port conflicts
    max_startup_attempts = 5
    startup_attempt = 0
    server_started = False
    
    while not server_started and startup_attempt < max_startup_attempts:
        startup_attempt += 1
        
        try:
            logger.info(f"Starting Flask server attempt {startup_attempt}/{max_startup_attempts} on http://0.0.0.0:{flask_port}")
            logger.info(f"Web interface will be available at: http://localhost:{flask_port}")
            
            # Start the server managed by server.py
            run_server(host='0.0.0.0', port=flask_port, debug=False)
            server_started = True  # This line will only be reached if server starts successfully
            
        except KeyboardInterrupt:
            logger.info("Received interrupt signal, shutting down gracefully...")
            break
            
        except Exception as e:
            error_msg = str(e).lower()
            
            # Check if this is a port-in-use error
            if "address already in use" in error_msg or "port" in error_msg or "bind" in error_msg:
                logger.warning(f"⚠️  Flask startup attempt {startup_attempt} failed: Port {flask_port} is in use")
                # If user requested, try to kill any processes using the port to free it up
                if hasattr(args, 'kill_port') and args.kill_port:
                    logger.info(f"Attempting to kill processes using port {flask_port} (user requested)")
                    killed, failed = kill_processes_using_port(flask_port, dry_run=DRY_RUN)
                    logger.info(f"Killed PIDs: {killed}")
                    if failed:
                        logger.warning(f"Failed to kill PIDs: {failed}")
                    # Wait briefly for OS to reclaim port
                    time.sleep(0.5)
                if startup_attempt < max_startup_attempts:
                    wait_time = 10 + (startup_attempt * 5)  # Increasing wait time: 15s, 20s, 25s, 30s
                    logger.info(f"⏳ Waiting {wait_time} seconds before retry attempt {startup_attempt + 1}...")
                    
                    # Wait for port to become available
                    if wait_for_port_available(port=flask_port, max_wait_time=wait_time):
                        logger.info(f"✅ Port {flask_port} is now available, retrying server startup...")
                        continue
                    else:
                        logger.warning(f"⚠️  Port {flask_port} still not available after {wait_time}s, but trying anyway...")
                        continue
                else:
                    logger.error(f"❌ Failed to start Flask server after {max_startup_attempts} attempts")
                    logger.error(f"❌ Port {flask_port} appears to be permanently occupied")
                    logger.error("💡 Try manually stopping any other instances of this application")
                    break
            else:
                # Non-port-related error
                logger.error(f"❌ Server error on {OS_NAME}: {e}")
                if startup_attempt < max_startup_attempts:
                    logger.info(f"⏳ Retrying in 5 seconds... (attempt {startup_attempt + 1}/{max_startup_attempts})")
                    time.sleep(5)
                    continue
                else:
                    logger.error(f"❌ Failed to start server after {max_startup_attempts} attempts due to errors")
                    break
    
    # Final cleanup
    logger.info("Application shutting down...")
    cleanup_nfc_reader()
    cleanup_temporary_files()
    logger.info("Cleanup completed")
