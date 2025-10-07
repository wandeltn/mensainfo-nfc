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
from datetime import datetime, timedelta

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Global variables
reader = None
nfc_reader_available = False
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

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
    
    Returns:
        bool: True if reader is available, False otherwise
    """
    global reader, nfc_reader_available
    
    try:
        if reader is None:
            reader = nfc.Reader()
            
        # Try to connect to test availability
        reader.connect()
        nfc_reader_available = True
        logger.info("NFC reader is available and working")
        
        # Emit reader available event
        socketio.emit('nfc_reader_available')
        return True
        
    except Exception as e:
        nfc_reader_available = False
        logger.error(f"NFC reader not available: {e}")
        
        # Emit reader unavailable event
        socketio.emit('nfc_reader_unavailable', {
            'error': str(e),
            'message': 'NFC-Lesegerät nicht erkannt'
        })
        return False

def try_connect_and_get_uid():
    """
    Attempt to connect to NFC reader and get card UID.
    
    Returns:
        str or None: Card UID in uppercase hex format, or None if no card/error
    """
    global nfc_reader_available
    
    if not nfc_reader_available:
        return None
        
    try:
        reader.connect()
        arr = reader.get_uid()
        if arr:
            result = ''.join(f'{x:02X}' for x in arr)
            return result
        else:
            return None
    except Exception as e:
        logger.debug(f"NFC reading error: {e}")
        
        # Check if this is a connectivity issue that requires re-testing availability
        if "No readers available" in str(e) or "Reader not found" in str(e):
            logger.warning("NFC reader may have been disconnected")
            test_nfc_reader_availability()
            
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
    
    # Initial NFC reader availability test
    test_nfc_reader_availability()
    
    reader_check_counter = 0
    
    while True:
        try:
            # Periodically recheck reader availability (every 30 seconds)
            reader_check_counter += 1
            if reader_check_counter >= 20:  # 20 * 1.5s = 30s
                reader_check_counter = 0
                if not nfc_reader_available:
                    test_nfc_reader_availability()
            
            if not nfc_reader_available:
                # Skip card reading if reader is not available
                time.sleep(1.5)
                continue
                
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
            logger.error(f"Error in card check loop: {e}")
            
        time.sleep(1.5)  # Check every 1.5 seconds for more responsive detection

def get_current_version():
    """Get the current version from version file"""
    try:
        with open(VERSION_FILE, 'r') as f:
            version_data = json.load(f)
            return version_data
    except (FileNotFoundError, json.JSONDecodeError):
        # Default version info if file doesn't exist
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
        if not os.path.exists(BACKUP_DIR):
            os.makedirs(BACKUP_DIR)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_subdir = os.path.join(BACKUP_DIR, f"backup_{timestamp}")
        os.makedirs(backup_subdir)
        
        # Backup app.py
        if os.path.exists('app.py'):
            shutil.copy2('app.py', os.path.join(backup_subdir, 'app.py'))
        
        # Backup index.html
        if os.path.exists('index.html'):
            shutil.copy2('index.html', os.path.join(backup_subdir, 'index.html'))
        
        logger.info(f"Created backup in {backup_subdir}")
        return backup_subdir
        
    except Exception as e:
        logger.error(f"Failed to create backup: {e}")
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
                
                # Extract and save the files
                if app_py_member:
                    tar.extract(app_py_member, path=tempfile.gettempdir())
                    extracted_app_py = os.path.join(tempfile.gettempdir(), app_py_member.name)
                    shutil.move(extracted_app_py, 'app.py.new')
                    logger.info("Downloaded new app.py")
                
                if index_html_member:
                    tar.extract(index_html_member, path=tempfile.gettempdir())
                    extracted_index_html = os.path.join(tempfile.gettempdir(), index_html_member.name)
                    shutil.move(extracted_index_html, 'index.html.new')
                    logger.info("Downloaded new index.html")
            
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
        
        # Replace app.py if new version was downloaded
        if os.path.exists('app.py.new'):
            if os.path.exists('app.py'):
                os.replace('app.py.new', 'app.py')
            else:
                os.rename('app.py.new', 'app.py')
            updated_files.append('app.py')
            logger.info("Updated app.py")
        
        # Replace index.html if new version was downloaded
        if os.path.exists('index.html.new'):
            if os.path.exists('index.html'):
                os.replace('index.html.new', 'index.html')
            else:
                os.rename('index.html.new', 'index.html')
            updated_files.append('index.html')
            logger.info("Updated index.html")
        
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
        time.sleep(1)  # Brief pause to ensure message is sent
        
        # Restart the Python process
        restart_application()
        
    except Exception as e:
        logger.error(f"Error during scheduled restart: {e}")

def restart_application():
    """Restart the current Python application"""
    try:
        logger.info("Restarting application with updated code...")
        
        # Get the current Python executable and script arguments
        python_executable = sys.executable
        script_path = sys.argv[0]
        
        # Close any open resources gracefully
        if 'reader' in globals() and reader:
            try:
                reader.close()
            except:
                pass
        
        # Restart the process
        os.execv(python_executable, [python_executable] + sys.argv)
        
    except Exception as e:
        logger.error(f"Failed to restart application: {e}")
        logger.error("Manual restart required!")

def update_check_loop():
    """Background thread to periodically check for updates"""
    while True:
        try:
            perform_update()
        except Exception as e:
            logger.error(f"Error in update check loop: {e}")
        
        # Wait for next check
        time.sleep(UPDATE_CHECK_INTERVAL)

@socketio.on('check_for_updates')
def handle_check_for_updates():
    """Manual update check triggered by client"""
    logger.info("Manual update check requested")
    threading.Thread(target=perform_update, daemon=True).start()

@socketio.on('get_version_info')
def handle_get_version_info():
    """Send current version info to client"""
    version_info = get_current_version()
    socketio.emit('version_info', version_info)

if __name__ == '__main__':
    logger.info("Starting NFC Reader Application")
    
    # Show current version
    current_version = get_current_version()
    logger.info(f"Current version: {current_version['tag_name']}")
    
    # Start card monitoring thread (it will handle NFC reader initialization)
    monitoring_thread = threading.Thread(target=card_check_loop, daemon=True)
    monitoring_thread.start()
    logger.info("Card monitoring thread started")
    
    # Start auto-update monitoring thread
    update_thread = threading.Thread(target=update_check_loop, daemon=True)
    update_thread.start()
    logger.info("Auto-update monitoring thread started")

    # Start Flask-SocketIO server
    logger.info("Starting Flask server on http://0.0.0.0:5000")
    logger.info("Web interface available at: http://localhost:5000")
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True, debug=False)
