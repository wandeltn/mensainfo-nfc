#!/usr/bin/env python3

# --- Existing NFC code ---
from py122u import nfc

# reader will be instantiated in main
reader = None


# --- Flask server to fetch and serve HTML ---

from flask import Flask, Response
import requests
from flask_socketio import SocketIO
import threading
import time

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

url = "https://mensacheck.n-s-w.info"
headers = {
    'Content-Type': 'application/x-www-form-urlencoded'
}

html_site = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Document</title>
    <script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
    <script>
        // Injected JS: WebSocket reload
        try {
            const socket = io('ws://' + window.location.hostname + ':5000');
            socket.on('reload', () => {
                window.location.reload();
            });

            socket.on('card_success', (msg) => {
                console.log(msg);
            });

            socket.on('connect', () => {
                console.log('WebSocket connected');
            });

            socket.on('disconnect', () => {
                console.log('WebSocket disconnected');
            });

            socket.on('card_unauthorized', (msg) => {
                console.error('Card unauthorized:', msg);
            });
        } catch (e) {console.error(e);}
        // End injected JS
    </script>
</head>
<body>
    <h1>Hello World</h1>
</body>
</html>
"""

def try_connect_and_get_uid():
    try:
        reader.connect()
        arr = reader.get_uid()
        if arr:
            result = ''.join(f'{x:02X}' for x in arr)
            return result
        else:
            return None
    except Exception as e:
        print(f"Error reading UID: {e}")
        return None


@app.route('/fetch_html')
def fetch_html():
    return Response(html_site, mimetype='text/html')

last_uid = None
def card_check_loop():
    global last_uid
    while True:
        uid = try_connect_and_get_uid()
        if uid:
            if uid != last_uid:
                last_uid = uid
                print(f"New card detected: {uid}")
                socketio.emit('reload')
        else:
            if last_uid is not None:
                print("Card removed")
                last_uid = None
                socketio.emit('reload')
        time.sleep(2)  # Check every 2 seconds
    global reader
if __name__ == '__main__':
    try:
        reader = nfc.Reader()
        threading.Thread(target=card_check_loop, daemon=True).start()
    except Exception as e:
        print(f"Failed to initialize NFC reader: {e} \nMake sure the NFC reader is connected and try again.")

    # reader = nfc.Reader()
    # You can change the interval here if needed, e.g., card_check_loop(sleep_interval=5)
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)
