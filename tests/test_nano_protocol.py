"""nano_protocol: checksummed lines encode and parse, and damage is rejected, never accepted."""

from __future__ import annotations

import pytest

from acoustic_analysis.io import nano_protocol as p


def test_encode_has_xor_checksum_and_newline():
    line = p.encode("BELT 55")
    assert line.endswith(b"\n")
    payload, _, tail = line.decode().strip().rpartition("*")
    assert payload == "BELT 55" and int(tail, 16) == p.checksum("BELT 55")
    assert p.checksum("AB") == ord("A") ^ ord("B")


def test_roundtrip_of_every_command():
    for raw, kind in ((p.encode_ping(7), "PING"), (p.encode_mode(True), "MODE"), (p.encode_hold(30), "HOLD"),
                      (p.encode_strike(True), "STRIKE"), (p.encode_up(), "UP"), (p.encode_retract(), "RETRACT"),
                      (p.encode_release(), "RELEASE"), (p.encode_tap_cycle(), "TAP")):
        payload, _, tail = raw.decode().strip().rpartition("*")
        assert payload.split()[0] == kind and int(tail, 16) == p.checksum(payload)


def test_values_are_clamped():
    assert p.encode_belt(250) == p.encode("BELT 100") and p.encode_belt(-5) == p.encode("BELT 0")
    assert p.encode_hold(999) == p.encode("HOLD 100")
    assert p.encode_ping(70000) == p.encode("PING 4464")        # wraps at 16 bits
    assert p.encode_mode(False) == p.encode("MODE 0") and p.encode_strike(False) == p.encode("STRIKE 0")


def test_encode_refuses_injection():
    with pytest.raises(ValueError):
        p.encode("BELT 5\nBELT 100")
    with pytest.raises(ValueError):
        p.encode("A*B")


def test_parse_tap_with_and_without_source():
    full = p.parse_line(p.encode("TAP 12 1 88 46678 0"))
    assert full == {"type": "tap", "seq": 12, "tile_present": True, "tof_mm": 88, "uptime_ms": 46678, "src": "tof"}
    old = p.parse_line(p.encode("TAP 3 0 140 1000"))
    assert old["tile_present"] is False and "src" not in old
    assert p.parse_line(p.encode("TAP 1 1 90 5 1"))["src"] == "manual"
    assert p.parse_line(p.encode("TAP 1 0 140 5 4"))["src"] == "rest"


def test_parse_ret_hello_pong_err():
    assert p.parse_line(p.encode("RET 5 1 1234")) == {"type": "ret", "seq": 5, "src": "manual", "uptime_ms": 1234}
    assert p.parse_line(p.encode("HELLO nano-fw-0.2")) == {"type": "hello", "fw": "nano-fw-0.2"}
    assert p.parse_line(p.encode("PONG 9")) == {"type": "pong", "n": 9}
    assert p.parse_line(p.encode("ERR TOF1 timeout")) == {"type": "err", "code": "TOF1", "text": "timeout"}


def test_parse_heartbeat_all_lengths():
    short = p.parse_line(p.encode("HB 5000 0 1 0"))
    assert short["uptime_ms"] == 5000 and short["tof1_ok"] is True and short["tof3_ok"] is False
    full = p.parse_line(p.encode("HB 5000 0 1 0 1 0 91 1 7 1500 0 30 1"))
    assert full["manual"] is True and full["retracted"] is False and full["tof1_mm"] == 91
    assert full["armed"] is True and full["state"] == 7 and full["left_ms"] == 1500
    assert full["hold_pct"] == 30 and full["up_wanted"] is True
    assert p.parse_line(p.encode("HB 5000 0 1 0 0 0 65535"))["tof1_mm"] is None   # no reading / out of range


def test_blank_line_is_none_and_bytes_are_accepted():
    assert p.parse_line("   \r\n") is None
    assert p.parse_line(p.encode("PONG 1"))["type"] == "pong"


@pytest.mark.parametrize("raw, why", [
    ("PONG 1", "no checksum"),
    ("PONG 1*ZZ", "not hex"),
    ("PONG 1*00", "mismatch"),
    ("PONG 1*A", "mismatch"),            # a one-digit checksum is not accepted even if its value matches
])
def test_damaged_lines_are_bad_not_accepted(raw, why):
    msg = p.parse_line(raw)
    assert msg["type"] == "bad" and why in msg["reason"]


def test_a_flipped_byte_never_becomes_another_command():
    good = p.encode("BELT 0").decode()
    flipped = good.replace("BELT 0", "BELT 9", 1)                # the failure this checksum exists to stop
    assert p.parse_line(flipped)["type"] == "bad"


def test_malformed_fields_are_bad():
    assert p.parse_line(p.encode("TAP 1 7 90 5"))["type"] == "bad"          # tile_present must be 0/1
    assert p.parse_line(p.encode("TAP 1 1 90 5 9"))["type"] == "bad"        # unknown source
    assert p.parse_line(p.encode("HB 1 2"))["type"] == "bad"
    assert p.parse_line(p.encode("RET 1 9 5"))["type"] == "bad"
    assert p.parse_line(p.encode("WHAT 1"))["type"] == "bad"
