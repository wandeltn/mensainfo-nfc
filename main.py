#!/usr/bin/env python3
from smartcard.System import readers
from smartcard.util import toHexString
from smartcard.Exceptions import NoCardException, CardConnectionException

try:
    r = readers()
    if len(r) == 0:
        print("NO_READERS")
        exit(1)
    
    conn = r[0].createConnection()
    try:
        conn.connect()
        GET_UID = [0xFF, 0xCA, 0x00, 0x00, 0x00]
        response, sw1, sw2 = conn.transmit(GET_UID)
        if sw1 == 0x90 and sw2 == 0x00:
            print(toHexString(response))
        else:
            print("ERROR")
    except NoCardException:
        print("NO_CARD")
    except CardConnectionException:
        print("CONNECT_ERROR")
    finally:
        try:
            conn.disconnect()
        except:
            pass
except Exception as e:
    print(f"EXCEPTION: {e}")
    exit(1)