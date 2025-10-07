# MensaInfo NFC - Auto-Update System

This NFC card reader application now includes an automatic update system that allows you to update the server remotely by publishing GitHub releases.

## How the Auto-Update System Works

1. **Automatic Checks**: The server checks for new releases every hour (configurable)
2. **Version Tracking**: Current version is stored in `current_version.json`
3. **Backup System**: Creates backups in `backup/` directory before updating
4. **Remote Updates**: Downloads and applies updates from GitHub releases
5. **Visual Notifications**: Shows update notifications in the web interface
6. **Automatic Restart**: When `app.py` is updated, the server automatically restarts after a 10-second countdown

## Publishing Updates

To update your remote server:

1. **Make your changes** to `app.py` and/or `index.html` in your development environment
2. **Test your changes** locally
3. **Commit and push** your changes to the main branch
4. **Create a new release** on GitHub:
   - Go to your repository on GitHub
   - Click "Releases" → "Create a new release"
   - Tag version: `v1.0.1` (increment version number)
   - Release title: `Version 1.0.1 - Description of changes`
   - Add release notes describing what changed
   - Click "Publish release"

5. **Wait for auto-update**: The server will automatically detect and apply the update within an hour

## Manual Update Check

- Click on the version number in the web interface (top-left corner) to manually check for updates
- Or trigger via WebSocket: `socket.emit('check_for_updates')`

## Configuration

In `app.py`, you can modify these settings:

```python
GITHUB_REPO = "wandeltn/mensainfo-nfc"  # Your GitHub repository
UPDATE_CHECK_INTERVAL = 3600  # Check interval in seconds (1 hour)
RESTART_DELAY = 10  # Seconds to wait before restarting after app.py update
```

## Update Process

1. **Check**: Compares current version with latest GitHub release
2. **Backup**: Creates timestamped backup of current files
3. **Download**: Downloads release tarball from GitHub
4. **Extract**: Extracts `app.py` and `index.html` from the archive
5. **Apply**: Replaces current files with new versions
6. **Notify**: Sends notification to connected web clients
7. **Auto-Restart**: If `app.py` was updated, shows 10-second countdown and automatically restarts the server

## Files Updated

The system currently updates:

- `app.py` - Python Flask server (automatically restarts after 10-second countdown)
- `index.html` - Web interface (updates immediately, no restart needed)

## Safety Features

- **Automatic backups** before each update
- **Rollback capability** via backup files
- **Error handling** for failed downloads or invalid releases
- **Version validation** to prevent duplicate updates

## Troubleshooting

- **Check logs** for update status and any errors
- **Backup files** are stored in `backup/backup_YYYYMMDD_HHMMSS/`
- **Manual rollback**: Copy files from backup directory if needed
- **Network issues**: Updates require internet access to GitHub

## Current Version

The current version is displayed in the web interface and can be checked programmatically via the `/version` endpoint or WebSocket events.

## Automatic Restart Feature

When `app.py` is updated:

1. **Update Applied**: New `app.py` file is downloaded and replaced
2. **Countdown Notification**: Users see a 10-second countdown overlay
3. **Graceful Restart**: Server automatically restarts using `os.execv()`
4. **Auto-Reload**: Web interface automatically reloads after restart
5. **Zero Manual Intervention**: Completely hands-off update process

The restart delay can be configured by changing `RESTART_DELAY` in `app.py`.