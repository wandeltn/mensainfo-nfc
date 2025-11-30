#!/usr/bin/env python3
"""
acr122u_reader.py

Wrapper for the py-acr122u library (and compatible implementations) that
provides a small, robust API for reading UIDs and controlling buzzer/LED.

The code uses best-effort imports and method name fallbacks to support
several variants of the library API since names differ across libs.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Module-level cache for a successfully imported ACR122U-compatible module
_CACHED_LIB = None
# Track the last import attempt time and avoid repeated import attempts in tight loop
_LAST_IMPORT_ATTEMPT = 0
_IMPORT_RETRY_INTERVAL = 5  # seconds
_IMPORT_LOCK = None


class ACR122UWrapper:
    def __init__(self):
        self._lib = None
        self._device = None
        self._connected = False

    def _import_lib(self) -> bool:
        """Try to import a py-acr122u-compatible library under common names."""
        global _CACHED_LIB, _LAST_IMPORT_ATTEMPT, _IMPORT_LOCK
        import time
        # Lazy-initialize lock
        if _IMPORT_LOCK is None:
            import threading
            _IMPORT_LOCK = threading.Lock()
        # If we successfully cached a module, reuse it to avoid repeated imports/logging
        if _CACHED_LIB is not None and _CACHED_LIB is not False:
            self._lib = _CACHED_LIB
            return True
        # If we previously cached a negative result, avoid trying again too soon
        if _CACHED_LIB is False and (time.time() - _LAST_IMPORT_ATTEMPT) < _IMPORT_RETRY_INTERVAL:
            return False

        candidates = ['acr122u', 'py_acr122u', 'pyacr122u']
        # Only attempt to import a candidate if other recent attempts failed OR we haven't tried recently and lock to avoid race
        with _IMPORT_LOCK:
            _LAST_IMPORT_ATTEMPT = time.time()
            for name in candidates:
                try:
                    lib = __import__(name)
                    # Log the import only once – when we cache it
                    logger.info(f'Imported ACR122U library: {name}')
                    self._lib = lib
                    # Cache for subsequent wrapper instances
                    _CACHED_LIB = lib
                    return True
                except Exception:
                    continue
            # If we got here, import failed for all candidates; cache negative result to prevent spamming
            _CACHED_LIB = False
            return False
        

    def connect(self) -> bool:
        """Create/initialize a device handle to read tags."""
        if not self._import_lib():
            return False

        # Different libs expose different APIs: attempt to find one we can use
        try:
            lib = self._lib
            # common API: `lib.ACR122U()` or `lib.ACR122u()` or `lib.Reader()`
            if hasattr(lib, 'ACR122U'):
                self._device = lib.ACR122U()
            elif hasattr(lib, 'ACR122u'):
                self._device = lib.ACR122u()
            elif hasattr(lib, 'Reader'):
                self._device = lib.Reader()
            else:
                # Fallback: maybe library exposes a default instance or factory
                self._device = None

            # Call connect/open if exists
            if self._device is not None:
                if hasattr(self._device, 'open'):
                    self._device.open()
                if hasattr(self._device, 'connect'):
                    self._device.connect()
                self._connected = True
                return True
        except Exception as e:
            logger.debug(f'Failed to instantiate ACR122U device: {e}')
            self._device = None
            self._connected = False
            return False

    def close(self) -> None:
        try:
            if self._device is not None:
                if hasattr(self._device, 'close'):
                    self._device.close()
                if hasattr(self._device, 'disconnect'):
                    self._device.disconnect()
        except Exception:
            pass
        finally:
            self._device = None
            self._connected = False

    def get_uid(self) -> Optional[str]:
        """Attempt to get UID of a tag; return uppercase hex string or None.

        This method tries multiple method names commonly found in wrappers:
        - `read()` returning raw bytes
        - `get_uid()` returning bytes or hex
        - `transmit()` with GET UID command (APDU)
        """
        if not self._connected:
            if not self.connect():
                return None

        dev = self._device
        try:
            # 1) Common: read() or read_tag()
            if hasattr(dev, 'read'):
                res = dev.read()
                if res:
                    # res could be bytes or int list
                    try:
                        if isinstance(res, bytes):
                            return res.hex().upper()
                        elif isinstance(res, (list, tuple)):
                            return ''.join(f'{x:02X}' for x in res)
                    except Exception:
                        pass
            if hasattr(dev, 'read_tag'):
                res = dev.read_tag()
                if res:
                    if isinstance(res, bytes):
                        return res.hex().upper()
                    elif isinstance(res, (list, tuple)):
                        return ''.join(f'{x:02X}' for x in res)

            # 2) get_uid() method
            if hasattr(dev, 'get_uid'):
                res = dev.get_uid()
                if res:
                    if isinstance(res, str):
                        return res.upper()
                    if isinstance(res, bytes):
                        return res.hex().upper()
                    if isinstance(res, (list, tuple)):
                        return ''.join(f'{x:02X}' for x in res)

            # 3) APDU transmit (older approach) - some wrappers expose 'transmit'
            if hasattr(dev, 'transmit'):
                GET_UID = [0xFF, 0xCA, 0x00, 0x00, 0x00]
                try:
                    resp, sw1, sw2 = dev.transmit(GET_UID)
                    if sw1 == 0x90 and sw2 == 0x00 and resp:
                        return ''.join(f'{x:02X}' for x in resp)
                except Exception:
                    pass

            # 4) fallback: some wrappers expose `read_bytes` or `getid`
            for name in ('read_bytes', 'getid', 'uid'):
                if hasattr(dev, name):
                    res = getattr(dev, name)()
                    if res:
                        if isinstance(res, bytes):
                            return res.hex().upper()
                        elif isinstance(res, str):
                            return res.upper()
                        elif isinstance(res, (list, tuple)):
                            return ''.join(f'{x:02X}' for x in res)
        except Exception as e:
            logger.debug(f'ACR122U get_uid error: {e}')

        return None

    def set_beep(self, enable: bool) -> bool:
        """Enable/disable beep if supported by the wrapper.

        Returns True if an explicit call was made, False otherwise.
        """
        if not self._connected:
            self.connect()
        if self._device is None:
            return False
        try:
            # Try method `set_beep` or `set_buzzer` or `beep` or `set_led` fallback
            if hasattr(self._device, 'set_beep'):
                self._device.set_beep(bool(enable))
                return True
            if hasattr(self._device, 'set_buzzer'):
                self._device.set_buzzer(bool(enable))
                return True
            if hasattr(self._device, 'beep'):
                # Some APIs expect parameters: beep(duration) - try mute by passing 0
                try:
                    self._device.beep(0 if not enable else 1)
                    return True
                except Exception:
                    try:
                        self._device.beep(boolean(enable))
                        return True
                    except Exception:
                        pass
            # Some readers support GPIO or LED commands that might mute speaker
            if hasattr(self._device, 'set_led'):
                self._device.set_led(False)
                return True
        except Exception as e:
            logger.debug(f'set_beep failed: {e}')
        return False


def open_reader() -> Optional[ACR122UWrapper]:
    try:
        wrapper = ACR122UWrapper()
        if wrapper.connect():
            return wrapper
    except Exception as e:
        logger.debug(f'open_reader exception: {e}')
    return None


def discover_acr_readers():
    """Attempt to detect ACR122U readers by using `pyscard` scanners and checking the vendor string.

    Returns True if an ACR-like reader is attached.
    """
    try:
        from smartcard.System import readers as sc_readers
        r = sc_readers()
        for x in r:
            if 'ACR' in str(x).upper() or 'ACS' in str(x).upper():
                return True
    except Exception:
        pass
    return False
