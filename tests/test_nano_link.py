"""nano_link: the keep-alive, events, commands and recovery, against a scripted fake serial port."""

from __future__ import annotations

import threading
import time

import pytest

from acoustic_analysis.config import load_config
from acoustic_analysis.io import nano_protocol as p
from acoustic_analysis.io.nano_link import NanoLink


class FakeSerial:
    def __init__(self):
        self.rx = bytearray()
        self.written: list[bytes] = []
        self.closed = False
        self.fail_write = False
        self.fail_read = False
        self._lock = threading.Lock()

    def push(self, *lines: str):
        with self._lock:
            for ln in lines:
                self.rx.extend(p.encode(ln))

    def read(self, n=1):
        if self.fail_read:
            raise OSError("device disconnected")
        with self._lock:
            out, self.rx = bytes(self.rx[:n]), self.rx[n:]
        if not out:
            time.sleep(0.005)
        return out

    def write(self, data):
        if self.fail_write:
            raise OSError("port gone")
        self.written.append(bytes(data))

    def close(self):
        self.closed = True

    def sent(self):
        return [w.decode().strip().rpartition("*")[0] for w in self.written]


@pytest.fixture()
def link():
    cfg = load_config()
    ser = FakeSerial()
    lk = NanoLink(cfg, serial_factory=lambda port, baud: ser)
    lk._ser = ser                                  # connected, but no reader thread: tests drive feed()/tick()
    lk.fake = ser
    return lk


def _types(link):
    return [e["type"] for e in link.drain()]


def test_hello_heartbeat_and_link_state(link):
    link.feed(p.encode("HELLO nano-fw-0.2") + p.encode("HB 5000 0 1 0 1 0 91 1 7 1500 0 30 1"), now=100.0)
    snap = link.snapshot()
    assert snap["fw"] == "nano-fw-0.2" and snap["link_ok"] and snap["tof1_mm"] == 91
    assert snap["manual"] is True and snap["armed"] is True and snap["hold_pct"] == 30 and snap["uptime_ms"] == 5000
    assert _types(link) == ["link", "hello"]
    link.tick(100.5)
    assert link.link_ok
    link.tick(104.0)                                # no valid line for longer than stale_s
    assert not link.link_ok and _types(link) == ["link"]


def test_a_line_split_across_reads_is_not_lost(link):
    raw = p.encode("TAP 7 1 88 46678 0")
    link.feed(raw[:9], 1.0)
    assert link.drain() == []                       # half a line: nothing yet, nothing rejected
    assert link.counts["bad_lines"] == 0
    link.feed(raw[9:], 1.1)
    ev = [e for e in link.drain() if e["type"] == "tap"]
    assert len(ev) == 1 and ev[0]["seq"] == 7 and ev[0]["tile_present"] is True and ev[0]["src"] == "tof" and ev[0]["t"] == 1.1


def test_tap_and_ret_events_and_counts(link):
    link.feed(p.encode("RET 1 1 1000") + p.encode("TAP 1 0 140 1100 1"), 5.0)
    kinds = {e["type"]: e for e in link.drain()}
    assert kinds["ret"]["src"] == "manual" and kinds["tap"]["tile_present"] is False
    assert link.counts["rets"] == 1 and link.counts["taps"] == 1


def test_repeated_tap_is_ignored_and_gaps_are_counted(link):
    link.feed(p.encode("TAP 1 1 90 10 0") * 2 + p.encode("TAP 4 1 90 20 0"), 1.0)
    taps = [e for e in link.drain() if e["type"] == "tap"]
    assert [t["seq"] for t in taps] == [1, 4]       # the repeat was dropped
    assert link.counts["taps"] == 2 and link.counts["gaps"] == 2     # seq 2 and 3 never arrived
    link.feed(p.encode("TAP 65535 1 90 30 0") + p.encode("TAP 0 1 90 40 0"), 2.0)        # wraps without a gap
    assert link.counts["gaps"] == 2 + (65535 - 4 - 1)


def test_damaged_lines_are_counted_and_do_not_keep_the_link_alive(link):
    link.feed(b"TAP 1 1 90 10 0*00\n", 1.0)
    assert link.counts["bad_lines"] == 1 and not link.link_ok and link.drain() == []
    link.feed(b"x" * 600, 2.0)                      # no newline in 600 bytes: noise
    assert link.counts["bad_lines"] == 2


def test_keep_alive_ping_is_paced(link):
    link.tick(10.0)
    link.tick(10.2)                                 # too soon
    link.tick(10.6)
    assert link.fake.sent() == ["PING 1", "PING 2"]


def test_commands_write_the_right_lines(link):
    link.set_manual(True)
    link.arm(True)
    link.set_hold(40)
    link.retract()
    link.release()
    assert link.fake.sent() == ["MODE 1", "STRIKE 1", "HOLD 40", "RETRACT", "RELEASE"]


def test_strike_once_arms_in_manual_mode_then_taps(link):
    link.strike_once()
    assert link.fake.sent() == ["MODE 1", "STRIKE 1", "TAP"]


def test_request_tile_is_auto_mode_arm_and_up(link):
    link.request_tile()
    assert link.fake.sent() == ["MODE 0", "STRIKE 1", "UP"]


def test_after_a_watchdog_reset_the_operators_wishes_are_sent_again(link):
    link.strike_once()
    link.fake.written.clear()
    link.feed(p.encode("ERR WDOGRESET"), 3.0)
    assert link.fake.sent() == ["MODE 1", "STRIKE 1"]
    link.fake.written.clear()
    link.feed(p.encode("HELLO nano-fw-0.2"), 4.0)             # a reboot says the same
    assert link.fake.sent() == ["MODE 1", "STRIKE 1"]


def test_disarmed_striker_is_not_rearmed_after_a_reboot(link):
    link.arm(True)
    link.arm(False)
    link.fake.written.clear()
    link.feed(p.encode("HELLO nano-fw-0.2"), 4.0)
    assert "STRIKE 1" not in link.fake.sent()


def test_errors_become_events(link):
    link.feed(p.encode("ERR TOF1 timeout"), 1.0)
    e = [x for x in link.drain() if x["type"] == "err"][0]
    assert e["code"] == "TOF1" and e["text"] == "timeout" and link.counts["errors"] == 1


def test_write_failure_reports_and_drops_the_link(link):
    link.feed(p.encode("HELLO x"), 1.0)
    link.drain()
    link.fake.fail_write = True
    link.tick(5.0)
    kinds = _types(link)
    assert "err" in kinds and "link" in kinds and not link.link_ok


def test_commands_refuse_when_not_connected():
    lk = NanoLink(load_config(), serial_factory=lambda *a: FakeSerial())
    with pytest.raises(RuntimeError):
        lk.strike_once()


def test_connect_thread_receives_and_disconnect_inhibits_the_striker():
    cfg = load_config()
    ser = FakeSerial()
    lk = NanoLink(cfg, serial_factory=lambda port, baud: ser)
    lk.connect("COM9")
    assert lk.connected
    ser.push("HELLO nano-fw-0.2", "TAP 1 1 88 100 0")
    deadline = time.time() + 3
    got = []
    while time.time() < deadline and not any(e["type"] == "tap" for e in got):
        got += lk.drain()
        time.sleep(0.02)
    assert any(e["type"] == "tap" for e in got) and lk.snapshot()["taps"] == 1
    assert any(w.startswith(b"PING") for w in ser.written)    # the thread kept the watchdog fed
    lk.disconnect()
    assert ser.closed and not lk.connected
    assert ser.sent()[-1] == "STRIKE 0"                       # inhibited on the way out
    assert "disconnected" in _types(lk)
    lk.connect("COM9")                                        # can reconnect afterwards
    lk.disconnect()


def test_unplugged_cable_during_read_drops_the_link():
    ser = FakeSerial()
    lk = NanoLink(load_config(), serial_factory=lambda port, baud: ser)
    lk.connect("COM9")
    ser.push("HELLO x")
    time.sleep(0.15)
    ser.fail_read = True
    deadline = time.time() + 3
    got = []
    while time.time() < deadline and not any(e["type"] == "err" for e in got):
        got += lk.drain()
        time.sleep(0.02)
    assert any(e["type"] == "err" and e["code"] == "SERIAL" for e in got)
    assert not lk.link_ok
    lk.disconnect()
