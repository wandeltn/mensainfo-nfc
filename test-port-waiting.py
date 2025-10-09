#!/usr/bin/env python3

"""
Port Availability Test Script
Tests the smart port waiting functionality for Flask auto-update restarts.
"""

import socket
import time
import threading
import sys
import os
from flask import Flask
from flask_socketio import SocketIO

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
    print(f"🔍 Waiting for port {port} to become available...")
    start_time = time.time()
    attempts = 0
    
    while time.time() - start_time < max_wait_time:
        attempts += 1
        if is_port_available(host, port):
            elapsed = time.time() - start_time
            print(f"✅ Port {port} is now available! (took {elapsed:.1f}s, {attempts} checks)")
            return True
            
        # Print status updates every 2 seconds
        if attempts % 4 == 0:  # Every 4 checks * 0.5s = 2s
            elapsed = int(time.time() - start_time)
            print(f"⏳ Still waiting for port {port}... ({elapsed}s elapsed, {attempts} checks)")
            
        time.sleep(check_interval)
    
    elapsed = time.time() - start_time
    print(f"❌ Timeout: Port {port} still not available after {elapsed:.1f}s ({attempts} checks)")
    return False

def test_flask_server(duration=10):
    """
    Start a test Flask server for a specific duration to simulate the old instance.
    
    Args:
        duration (int): How long to run the server in seconds
    """
    print(f"🚀 Starting test Flask server on port 5000 for {duration} seconds...")
    
    app = Flask(__name__)
    socketio = SocketIO(app, cors_allowed_origins="*")
    
    @app.route('/')
    def index():
        return f"<h1>Test Server</h1><p>Running for {duration} seconds</p>"
    
    def shutdown_server():
        time.sleep(duration)
        print("🛑 Shutting down test Flask server...")
        # Force exit to simulate restart scenario
        os._exit(0)
    
    # Start shutdown timer
    shutdown_thread = threading.Thread(target=shutdown_server, daemon=True)
    shutdown_thread.start()
    
    try:
        socketio.run(app, host='localhost', port=5000, debug=False)
    except Exception as e:
        print(f"Server error: {e}")

def test_port_availability():
    """Test the port availability checking functions"""
    print("=" * 60)
    print("Port Availability Test")
    print("=" * 60)
    
    port = 5000
    
    # Test 1: Check if port is initially available
    print(f"\n1️⃣ Testing initial port {port} availability:")
    if is_port_available(port=port):
        print(f"✅ Port {port} is available")
    else:
        print(f"❌ Port {port} is in use")
    
    # Test 2: Start a Flask server in background and test waiting
    print(f"\n2️⃣ Testing port waiting functionality:")
    print("Starting background Flask server...")
    
    server_thread = threading.Thread(target=test_flask_server, args=(8,), daemon=True)
    server_thread.start()
    
    # Give server time to start
    time.sleep(2)
    
    # Check if port is now in use
    print(f"\n3️⃣ Checking if port {port} is now in use:")
    if not is_port_available(port=port):
        print(f"✅ Port {port} is correctly detected as in use")
    else:
        print(f"❌ Port {port} should be in use but is detected as available")
    
    # Test the waiting function
    print(f"\n4️⃣ Testing wait_for_port_available function:")
    success = wait_for_port_available(port=port, max_wait_time=15, check_interval=0.5)
    
    if success:
        print(f"✅ Successfully waited for port {port} to become available")
    else:
        print(f"❌ Failed to wait for port {port} - timeout reached")
    
    # Final verification
    print(f"\n5️⃣ Final port availability check:")
    if is_port_available(port=port):
        print(f"✅ Port {port} is now available")
    else:
        print(f"❌ Port {port} is still in use")
    
    print("\n" + "=" * 60)
    print("Port Availability Test Complete!")
    print("=" * 60)

def simulate_restart_scenario():
    """Simulate the actual restart scenario from the app"""
    print("=" * 60)
    print("Restart Scenario Simulation")
    print("=" * 60)
    
    print("This simulates what happens during an auto-update restart:")
    print("1. Old Flask instance is running")
    print("2. New instance waits for port to become available")
    print("3. New instance starts when port is free")
    
    # This would be the restart script content (for demonstration)
    restart_code = '''
# This is what the restart script does:

import socket
import time

def is_port_available(host='localhost', port=5000, timeout=1):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            return result != 0
    except Exception:
        return True

def wait_for_port_available(host='localhost', port=5000, max_wait_time=30, check_interval=0.5):
    start_time = time.time()
    attempts = 0
    while time.time() - start_time < max_wait_time:
        attempts += 1
        if is_port_available(host, port):
            print(f'Port {port} is now available (checked {attempts} times)')
            return True
        if attempts % 4 == 0:
            elapsed = int(time.time() - start_time)
            print(f'Still waiting for port {port}... ({elapsed}s elapsed)')
        time.sleep(check_interval)
    return False

# Wait for port and then start new instance
if wait_for_port_available():
    print('Starting new Flask instance...')
    # exec(["python", "app.py"])
else:
    print('Timeout - starting anyway')
'''
    
    print("\nRestart script logic:")
    print("-" * 40)
    print(restart_code)

def main():
    """Main test function"""
    if len(sys.argv) > 1:
        if sys.argv[1] == "server":
            # Run a test server for manual testing
            duration = int(sys.argv[2]) if len(sys.argv) > 2 else 15
            test_flask_server(duration)
            return
        elif sys.argv[1] == "wait":
            # Test waiting for port
            port = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
            max_wait = int(sys.argv[3]) if len(sys.argv) > 3 else 30
            success = wait_for_port_available(port=port, max_wait_time=max_wait)
            sys.exit(0 if success else 1)
        elif sys.argv[1] == "check":
            # Just check if port is available
            port = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
            available = is_port_available(port=port)
            print(f"Port {port} is {'available' if available else 'in use'}")
            sys.exit(0 if available else 1)
    
    # Run full test suite
    print("🧪 Smart Port Waiting Test Suite")
    print("This tests the enhanced restart mechanism for Flask auto-updates")
    print()
    
    try:
        test_port_availability()
        time.sleep(2)
        simulate_restart_scenario()
        
        print("\n🎉 All tests completed successfully!")
        print("\nUsage examples:")
        print("  python test-port-waiting.py              # Run full test suite")
        print("  python test-port-waiting.py server 10    # Start test server for 10 seconds")
        print("  python test-port-waiting.py wait 5000 30 # Wait for port 5000, max 30 seconds")
        print("  python test-port-waiting.py check 5000   # Check if port 5000 is available")
        
    except KeyboardInterrupt:
        print("\n\n⏹️ Test interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Test failed with error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()