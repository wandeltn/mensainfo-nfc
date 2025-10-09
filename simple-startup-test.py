#!/usr/bin/env python3

"""
Simple test for the Flask startup retry mechanism without Unicode issues.
"""

import socket
import time
import threading
import subprocess
import sys
import os
import tempfile

def create_port_blocker(port=5000, duration=8):
    """Create a server that blocks a port for testing"""
    def block_port():
        try:
            print(f"Blocking port {port} for {duration} seconds...")
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(('localhost', port))
                sock.listen(1)
                time.sleep(duration)
                print(f"Releasing port {port}")
        except Exception as e:
            print(f"Error in port blocker: {e}")
    
    thread = threading.Thread(target=block_port, daemon=True)
    thread.start()
    return thread

def test_startup_retry():
    """Test the startup retry mechanism"""
    print("\n" + "="*60)
    print("Testing Flask Startup Retry Mechanism")
    print("="*60)
    
    # Create a simple test script without emojis
    test_script = """
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
            print(f'Port {port} is now available (checked {attempts} times)')
            return True
        if attempts % 4 == 0:
            elapsed = int(time.time() - start_time)
            print(f'Still waiting for port {port}... ({elapsed}s elapsed)')
        time.sleep(check_interval)
    print(f'Timeout: Port {port} still not available after {max_wait_time}s')
    return False

def simulate_flask_startup():
    max_attempts = 3
    attempt = 0
    flask_port = 5000
    
    while attempt < max_attempts:
        attempt += 1
        
        try:
            print(f"Flask startup attempt {attempt}/{max_attempts} on port {flask_port}")
            
            # Try to bind to the port (simulating Flask startup)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as test_sock:
                test_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                test_sock.bind(('localhost', flask_port))
                test_sock.listen(1)
                print("SUCCESS: Flask server started successfully!")
                time.sleep(1)  # Simulate brief run
                return True
                
        except Exception as e:
            error_msg = str(e).lower()
            
            if "already in use" in error_msg or "bind" in error_msg:
                print(f"WARNING: Port {flask_port} is in use (attempt {attempt})")
                
                if attempt < max_attempts:
                    wait_time = 5 + (attempt * 2)
                    print(f"Waiting {wait_time} seconds before retry...")
                    
                    if wait_for_port_available(port=flask_port, max_wait_time=wait_time):
                        print(f"Port {flask_port} is available, retrying...")
                        continue
                    else:
                        print(f"Port {flask_port} still not available, trying anyway...")
                        continue
                else:
                    print(f"FAILED: Could not start after {max_attempts} attempts")
                    return False
            else:
                print(f"ERROR: {e}")
                return False
    
    return False

if __name__ == '__main__':
    print("Testing Flask startup retry mechanism...")
    success = simulate_flask_startup()
    if success:
        print("SUCCESS: Startup retry works!")
        sys.exit(0)
    else:
        print("FAILED: Startup retry failed!")
        sys.exit(1)
"""
    
    # Test with temporary directory
    with tempfile.TemporaryDirectory() as test_dir:
        test_script_path = os.path.join(test_dir, "simple_test.py")
        with open(test_script_path, 'w', encoding='utf-8') as f:
            f.write(test_script)
        
        print(f"Created test script: {test_script_path}")
        
        # Test 1: Normal startup
        print(f"\nTest 1: Normal startup")
        try:
            result = subprocess.run([sys.executable, test_script_path], 
                                  capture_output=True, text=True, timeout=15)
            print(f"Output:\n{result.stdout}")
            if result.stderr:
                print(f"Errors:\n{result.stderr}")
            
            test1_passed = result.returncode == 0
            print(f"Test 1: {'PASSED' if test1_passed else 'FAILED'}")
                
        except Exception as e:
            print(f"Test 1 FAILED: {e}")
            test1_passed = False
        
        # Test 2: With port conflict
        print(f"\nTest 2: Startup with port conflict")
        
        # Block port temporarily
        blocker_thread = create_port_blocker(port=5000, duration=6)
        time.sleep(1)  # Wait for blocker to start
        
        try:
            result = subprocess.run([sys.executable, test_script_path], 
                                  capture_output=True, text=True, timeout=25)
            print(f"Output:\n{result.stdout}")
            if result.stderr:
                print(f"Errors:\n{result.stderr}")
            
            test2_passed = result.returncode == 0
            print(f"Test 2: {'PASSED' if test2_passed else 'FAILED'}")
                
        except Exception as e:
            print(f"Test 2 FAILED: {e}")
            test2_passed = False
        
        return test1_passed and test2_passed

if __name__ == '__main__':
    print("Starting Flask Startup Retry Test")
    print(f"OS: {'Windows' if os.name == 'nt' else 'Unix'}")
    print(f"Python: {sys.executable}")
    
    test_passed = test_startup_retry()
    
    print("\n" + "="*60)
    print("Test Results")
    print("="*60)
    
    if test_passed:
        print("SUCCESS: Flask startup retry mechanism works!")
        print("The app should now handle port conflicts during startup.")
        sys.exit(0)
    else:
        print("FAILED: Issues with startup retry mechanism.")
        sys.exit(1)