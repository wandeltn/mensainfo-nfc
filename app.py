#!/usr/bin/env python3

# --- Enhanced NFC card validation system with auto-update ---
from py122u import nfc
import requests
from flask import Flask, Response
from flask_socketio import SocketIO
import threading
import time
import logging
import os
import json
import shutil
import sys
import subprocess
import argparse
from datetime import datetime, timedelta

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# OS Detection
IS_WINDOWS = os.name == 'nt'
IS_LINUX = os.name == 'posix'
OS_NAME = 'Windows' if IS_WINDOWS else 'Linux/Unix' if IS_LINUX else 'Unknown'

logger.info(f"Detected operating system: {OS_NAME}")

# Global variables
reader = None
nfc_reader_available = False
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

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
            timeout=10  # 10 second timeout
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
    Uses a gentle approach similar to the old version - only create reader when needed.
    
    Returns:
        bool: True if reader is available, False otherwise
    """
    global reader, nfc_reader_available
    
    try:
        # Only create reader instance if it doesn't exist (lazy initialization)
        if reader is None:
            logger.debug(f"Creating NFC reader instance on {OS_NAME}...")
            reader = nfc.Reader()
        
        # Simple connection test - don't be too aggressive
        reader.connect()
        
        nfc_reader_available = True
        logger.debug(f"✅ NFC reader is working on {OS_NAME}")
        
        # Only emit events if we have active WebSocket connections
        try:
            socketio.emit('nfc_reader_available')
        except:
            pass  # Ignore WebSocket emission errors during startup
        
        return True
        
    except Exception as e:
        nfc_reader_available = False
        
        # Clean up silently
        if reader is not None:
            try:
                reader.close()
            except:
                pass
            reader = None
        
        # Log error but don't be too verbose (like old version)
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
    Attempt to connect to NFC reader and get card UID.
    Simple approach similar to the old version.
    
    Returns:
        str or None: Card UID in uppercase hex format, or None if no card/error
    """
    global nfc_reader_available, reader
    
    try:
        # Create reader if it doesn't exist (lazy initialization like old version)
        if reader is None:
            reader = nfc.Reader()
            
        # Try to connect and get UID (similar to old version)
        reader.connect()
        arr = reader.get_uid()
        
        if arr:
            result = ''.join(f'{x:02X}' for x in arr)
            nfc_reader_available = True
            return result
        else:
            return None
            
    except Exception as e:
        # Simple error handling like the old version
        # If error occurs, treat as card removed/reader unavailable
        nfc_reader_available = False
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
                if uid != last_uid:
                    last_uid = uid
                    logger.info(f"New card detected: {uid}")
                    
                    # Validate card with database
                    is_valid = validate_card_with_database(uid)
                    last_validation_result = is_valid
                    
                    if is_valid:
                        logger.info(f"Card {uid} is VALID")
                        socketio.emit('card_success', {
                            'uid': uid,
                            'message': 'Karte berechtigt',
                            'timestamp': time.time()
                        })
                    else:
                        logger.warning(f"Card {uid} is INVALID")
                        socketio.emit('card_unauthorized', {
                            'uid': uid,
                            'message': 'Karte nicht berechtigt',
                            'timestamp': time.time()
                        })
            else:
                # Card removed or no card present
                if last_uid is not None:
                    logger.info(f"Card {last_uid} removed")
                    last_uid = None
                    last_validation_result = None
                    socketio.emit('reload')
                    
        except Exception as e:
            # Simple error handling like old version
            if last_uid is not None:
                logger.info("Card removed (exception)")
                last_uid = None
                last_validation_result = None
                socketio.emit('reload')

        time.sleep(2)  # Check every 2 seconds like the old version

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
    
    release_info = check_for_updates()
    if not release_info:
        return False
    
    logger.info(f"Found new version: {release_info['tag_name']}")
    
    # Create backup
    backup_dir = backup_current_files()
    if not backup_dir:
        logger.error("Failed to create backup, aborting update")
        return False
    
    # Download new files
    if not download_release_files(release_info):
        logger.error("Failed to download release files")
        return False
    
    # Apply update
    if apply_update(release_info):
        logger.info("Update completed successfully")
        return True
    else:
        logger.error("Failed to apply update")
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
    """Restart the current Python application"""
    try:
        logger.info("Restarting application with updated code...")
        
        # Close any open resources gracefully
        cleanup_nfc_reader()
        
        # Try to disconnect all SocketIO clients
        try:
            socketio.emit('server_restart', {'message': 'Server wird neugestartet...'})
            socketio.sleep(1)  # Give time for message to be sent
        except:
            pass
        
        # Get the current Python executable and script arguments
        python_executable = sys.executable
        script_args = sys.argv.copy()
        
        # Use different restart methods based on OS
        logger.info(f"Restarting application on {OS_NAME}")
        
        if IS_WINDOWS:
            # Windows-specific restart using subprocess
            import subprocess
            
            current_dir = os.getcwd()
            logger.info(f"Windows restart: {python_executable} {' '.join(script_args)}")
            
            try:
                # Start new process with Windows-specific flags
                subprocess.Popen(
                    [python_executable] + script_args,
                    cwd=current_dir,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                    close_fds=True,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                
                # Give the new process time to start
                time.sleep(3)
                logger.info("Windows: New process started, exiting current process...")
                os._exit(0)
                
            except Exception as e:
                logger.error(f"Windows subprocess restart failed: {e}")
                raise
                
        elif IS_LINUX:
            # Linux/Unix-specific restart using execv
            logger.info(f"Linux restart: {python_executable} {' '.join(script_args)}")
            
            try:
                # Use execv for Unix systems (more reliable on Linux)
                os.execv(python_executable, [python_executable] + script_args)
            except Exception as e:
                logger.error(f"Linux execv restart failed: {e}")
                raise
                
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

if __name__ == '__main__':
    # Parse command line arguments first
    args = parse_command_line_arguments()
    
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

    # Start Flask-SocketIO server
    logger.info("Starting Flask server on http://0.0.0.0:5000")
    logger.info("Web interface available at: http://localhost:5000")
    
    try:
        socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True, debug=False)
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down gracefully...")
    except Exception as e:
        logger.error(f"Server error on {OS_NAME}: {e}")
    finally:
        logger.info("Application shutting down...")
        cleanup_nfc_reader()
        logger.info("Cleanup completed")
