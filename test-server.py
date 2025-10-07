#!/usr/bin/env python3
"""
Test server for simulating WebSocket events without NFC hardware.
Run this instead of app.py to test the visual feedback system.
"""

from flask import Flask, Response
from flask_socketio import SocketIO
import threading
import time
import random

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# Read the actual HTML file
def get_html_content():
    try:
        with open('index.html', 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>Error: index.html not found</h1>"

@app.route('/')
def index():
    return Response(get_html_content(), mimetype='text/html')

@app.route('/fetch_html')
def fetch_html():
    return Response(get_html_content(), mimetype='text/html')

def simulate_events():
    """Simulate various WebSocket events for testing"""
    time.sleep(2)  # Wait for initial connection
    
    # Simulate connection established
    print("Simulating: WebSocket connected")
    
    # Wait a bit, then simulate card events
    time.sleep(3)
    
    events_sequence = [
        ("reload", "Simulating card detection (reload)"),
        ("card_success", "Simulating successful card authorization"),
        ("card_unauthorized", "Simulating unauthorized card"),
        ("reload", "Simulating another card detection"),
    ]
    
    for event, description in events_sequence:
        print(f"Sending: {description}")
        if event == "card_success":
            socketio.emit('card_success', {'message': 'Test card authorized'})
        elif event == "card_unauthorized":
            socketio.emit('card_unauthorized', {'message': 'Test card rejected'})
        elif event == "reload":
            socketio.emit('reload')
        
        # Random delay between events (3-8 seconds)
        time.sleep(random.uniform(3, 8))

def interactive_test():
    """Interactive testing - send events based on user input"""
    time.sleep(2)
    print("\n=== Interactive WebSocket Event Tester ===")
    print("Commands:")
    print("  1 or success - Send card_success event")
    print("  2 or error - Send card_unauthorized event") 
    print("  3 or reload - Send reload event")
    print("  4 or disconnect - Simulate disconnect")
    print("  5 or auto - Start automatic event simulation")
    print("  6 or timeout - Test connection timeout (stop server for 15s)")
    print("  q or quit - Exit")
    print("==========================================\n")
    
    while True:
        try:
            cmd = input("Enter command: ").strip().lower()
            
            if cmd in ['q', 'quit']:
                break
            elif cmd in ['1', 'success']:
                print("Sending card_success event")
                socketio.emit('card_success', {'message': 'Manual test - card authorized'})
            elif cmd in ['2', 'error']:
                print("Sending card_unauthorized event")
                socketio.emit('card_unauthorized', {'message': 'Manual test - card rejected'})
            elif cmd in ['3', 'reload']:
                print("Sending reload event")
                socketio.emit('reload')
            elif cmd in ['4', 'disconnect']:
                print("Note: Disconnect is handled by browser, not server")
                print("Try closing/refreshing the browser tab to see disconnect event")
            elif cmd in ['5', 'auto']:
                print("Starting automatic event simulation...")
                threading.Thread(target=simulate_events, daemon=True).start()
            elif cmd in ['6', 'timeout']:
                print("Testing connection timeout - server will pause for 15 seconds...")
                print("Watch the browser for connection failure effects!")
                socketio.stop()
                time.sleep(15)
                print("Resuming server...")
            else:
                print("Unknown command. Try 1, 2, 3, 4, 5, 6, or q")
                
        except KeyboardInterrupt:
            print("\nExiting...")
            break
        except EOFError:
            break

@socketio.on('connect')
def handle_connect():
    print(f"Client connected")

@socketio.on('disconnect')
def handle_disconnect():
    print(f"Client disconnected")

if __name__ == '__main__':
    print("Starting NFC Test Server...")
    print("Open http://localhost:5000 in your browser")
    print("The server will start interactive testing mode in 2 seconds...")
    
    # Start interactive testing in a separate thread
    threading.Thread(target=interactive_test, daemon=True).start()
    
    # Run the Flask-SocketIO server
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True, debug=False)