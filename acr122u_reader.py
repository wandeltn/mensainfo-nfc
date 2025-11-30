#!/usr/bin/env python3
"""
acr122u_reader.py

Compatibility stub used when ACR122U wrapper was present earlier in the repo.
This module is intentionally minimal now and acts like a no-op wrapper to avoid
errors if still imported. It's recommended to remove calls to this module if you
do not use ACR122U-specific behavior.
"""
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class ACR122UWrapper:
    def __init__(self):
        self._connected = False

    def connect(self) -> bool:
        return False

    def close(self) -> None:
        pass

    def get_uid(self) -> Optional[str]:
        return None

    def set_beep(self, enable: bool) -> bool:
        return False


def open_reader() -> Optional[ACR122UWrapper]:
    return None


def discover_acr_readers():
    return False
