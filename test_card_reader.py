#!/usr/bin/env python3
"""
Simple test script to validate the NFC card reader flow used by the application.

This script will:
- Import the NFC helper functions from `app.py` (safe import - does not start the server)
- Optionally test `main.py` and `libnfc.py` readers if available
- Loop N times attempting to read a UID and report results
- Clean up readers at the end

Run example:
  python test_card_reader.py --attempts 20 --interval 0.5
"""

import argparse
import time
import sys
import logging

# Logging similar to app
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def try_import_app_helpers():
    try:
        import app
        return app
    except Exception as e:
        logger.error(f"Failed to import app: {e}")
        return None


def try_import_main_reader():
    try:
        import main
        return main
    except Exception as e:
        logger.debug(f"Could not import main reader implementation: {e}")
        return None


def try_import_libnfc_reader():
    try:
        import libnfc
        return libnfc
    except Exception as e:
        logger.debug(f"Could not import libnfc reader implementation: {e}")
        return None


def main_run(args):
    appmod = try_import_app_helpers()
    mainmod = try_import_main_reader()
    libnfcmod = try_import_libnfc_reader()

    if appmod is None:
        logger.error("Aborting: app module not importable")
        sys.exit(1)

    # Test reading availability
    ok = False
    try:
        ok = appmod.test_nfc_reader_availability()
    except Exception as e:
        logger.warning(f"test_nfc_reader_availability() raised exception: {e}")

    logger.info(f"NFC reader available (app.test_nfc_reader_availability): {ok}")

    if args.attempts <= 0:
        logger.info("No attempts requested; exiting")
        return 0

    found_any = False
    start_time = time.time()

    for attempt in range(1, args.attempts + 1):
        try:
            uid = appmod.try_connect_and_get_uid()
            if uid:
                # Print human-readable UID
                logger.info(f"Attempt {attempt}/{args.attempts}: UID read: {uid}")
                found_any = True
            else:
                logger.info(f"Attempt {attempt}/{args.attempts}: No card present")
        except Exception as e:
            logger.error(f"Attempt {attempt} error: {e}")

        # Optionally check alternative readers (main.py and libnfc.py) without interfering
        if mainmod and hasattr(mainmod, 'read_card_once'):
            try:
                # Some main.py variants use different function names; this is a best effort
                res = None
                try:
                    res = mainmod.read_card_once()
                except Exception:
                    # try a generic name used in some impls
                    if hasattr(mainmod, 'try_read_uid'):
                        res = mainmod.try_read_uid()
                if res:
                    logger.info(f"Attempt {attempt}: main.py read: {res}")
                else:
                    logger.debug(f"Attempt {attempt}: main.py did not read card")
            except Exception as e:
                logger.debug(f"Attempt {attempt} main.py read error: {e}")

        if libnfcmod and hasattr(libnfcmod, 'on_connect_read_uid'):
            try:
                # libnfc variants sometimes expect callback flows - do a safe probe only
                res = None
                if hasattr(libnfcmod, 'read_uid_once'):
                    try:
                        res = libnfcmod.read_uid_once()
                    except Exception:
                        res = None
                if res:
                    logger.info(f"Attempt {attempt}: libnfc reader returned: {res}")
            except Exception as e:
                logger.debug(f"Attempt {attempt} libnfc read error: {e}")

        time.sleep(args.interval)

    total_elapsed = time.time() - start_time
    logger.info(f"Finished {args.attempts} attempts in {total_elapsed:.1f}s; found any: {found_any}")

    # Cleanup
    try:
        appmod.cleanup_nfc_reader()
    except Exception as e:
        logger.debug(f"Error while trying to cleanup readers: {e}")

    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Simple test harness for NFC reader functions')
    parser.add_argument('--attempts', type=int, default=10, help='Number of read attempts (default 10)')
    parser.add_argument('--interval', type=float, default=0.5, help='Interval between attempts in seconds (default 0.5)')
    parser.add_argument('--verbose', action='store_true', help='Enable debug-level output')
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    sys.exit(main_run(args))
