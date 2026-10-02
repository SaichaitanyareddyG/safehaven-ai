#!/usr/bin/env python3
"""Save a band's recorded tuning session to a text file.

    ~/.platformio/penv/bin/python tools/capture_recording.py session.txt

Sends `rec stop` then `rec dump` over USB and writes everything between
"REC MARKERS" and "REC END" to the file, for native/replay_recording. Opens the
port with DTR/RTS released — asserting them holds the ESP32-S3 in reset.
"""

import sys
import time

import serial
import serial.tools.list_ports


def main() -> int:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    ports = [p.device for p in serial.tools.list_ports.comports() if p.vid == 0x303A]
    if not ports:
        sys.exit("band not connected")
    s = serial.Serial()
    s.port, s.baudrate, s.timeout, s.dtr, s.rts = ports[0], 115200, 0.5, False, False
    s.open()
    time.sleep(0.5)
    s.reset_input_buffer()
    s.write(b"rec stop\n")
    time.sleep(1)
    s.reset_input_buffer()
    s.write(b"rec dump\n")
    buf, idle = b"", 0
    while b"REC END" not in buf and idle < 20:
        chunk = s.read(65536)
        buf += chunk
        idle = 0 if chunk else idle + 1
    text = buf.decode(errors="replace")
    start = text.find("REC MARKERS")
    if start < 0 or "REC END" not in text:
        sys.exit("no complete recording received")
    out = text[start : text.find("REC END") + len("REC END")]
    open(sys.argv[1], "w").write(out + "\n")
    lines = out.count("\n")
    print(f"saved {sys.argv[1]} ({lines} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
