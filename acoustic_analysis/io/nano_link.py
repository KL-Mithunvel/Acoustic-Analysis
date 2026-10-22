"""USB-serial link to the striker Nano.

``NanoLink`` keeps the Nano's watchdog fed (a PING every ``ping_s``), turns its lines into
events for the GUI (``tap``, ``ret``, ``hello``, ``err``, ``link``) and sends it commands.

The logic is pure and clocked from outside: ``feed(bytes, now)`` takes whatever arrived and
processes only *complete* lines (a read that times out half way through a line must not lose a
``TAP`` - the checksum would reject both halves), ``tick(now)`` sends the keep-alive and notices a
silent link. A thin thread (``start``) just reads bytes and calls those two. The port is anything
with ``read(n)`` / ``write(b)`` / ``close()``, so the whole thing is tested with a scripted fake;
``pyserial`` is imported only when a real port is opened.

The Nano resets when the port opens (DTR), so its driver inputs float for a moment: keep clear of
the striker while connecting.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Callable

from . import nano_protocol as proto

Clock = Callable[[], float]


def open_pyserial(port: str, baud: int):
    import serial  # lazy: only needed where a Nano is attached

    return serial.Serial(port, baudrate=baud, timeout=0.1, write_timeout=1.0)


def serial_ports(cfg: dict) -> list[dict]:
    """Serial ports now present: ``{device, description, vid, candidate}`` (candidate = a USB chip a Nano uses)."""
    from serial.tools import list_ports

    vids = {v.upper() for v in cfg["striker"]["usb_vids"]}
    out = []
    for p in sorted(list_ports.comports(), key=lambda p: p.device):
        vid = f"{p.vid:04X}" if p.vid is not None else None
        out.append({"device": p.device, "description": p.description or "", "vid": vid,
                    "candidate": bool(vid and vid in vids)})
    return out


class NanoLink:
    def __init__(self, cfg: dict, serial_factory: Callable[[str, int], object] = open_pyserial,
                 clock: Clock = time.time):
        s = cfg["striker"]
        self._baud, self._ping_s, self._stale_s = int(s["baud"]), float(s["ping_s"]), float(s["stale_s"])
        self._open, self._clock = serial_factory, clock
        self._ser = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._buf = bytearray()
        self.events: queue.Queue = queue.Queue()
        self._reset_state()

    def _reset_state(self) -> None:
        self._ping_n = 0
        self._last_ping = 0.0
        self._last_rx: float | None = None
        self._link_up = False
        self._last_seq: int | None = None
        self._want_armed = False            # what the operator asked for; re-sent after a watchdog trip
        self._want_manual: bool | None = None
        self.state: dict = {"fw": None, "uptime_ms": None, "tof1_mm": None, "tof1_ok": None, "manual": None,
                            "retracted": None, "armed": None, "hold_pct": None, "up_wanted": None, "nano_state": None}
        self.counts = {"taps": 0, "rets": 0, "gaps": 0, "bad_lines": 0, "errors": 0}

    # ------------------------------------------------------------------ connection
    @property
    def connected(self) -> bool:
        return self._ser is not None

    def connect(self, port: str) -> None:
        if self._ser is not None:
            raise RuntimeError("already connected")
        self._reset_state()
        self._buf.clear()
        self._ser = self._open(port, self._baud)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="nano-link", daemon=True)
        self._thread.start()
        self._emit("connected", port=port)

    def disconnect(self) -> None:
        """Inhibit the striker, then close. (The Nano's own watchdog covers a crash; this covers a click.)"""
        if self._ser is None:
            return
        try:
            self._write(proto.encode_strike(False))
        except Exception:  # noqa: BLE001 - closing anyway
            pass
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)
        try:
            self._ser.close()
        except Exception:  # noqa: BLE001
            pass
        self._ser, self._thread = None, None
        self._link_up = False
        self._emit("disconnected")

    def _run(self) -> None:
        while not self._stop.is_set():
            ser = self._ser
            if ser is None:
                break
            try:
                data = ser.read(max(getattr(ser, "in_waiting", 0), 1))
            except Exception as exc:  # noqa: BLE001 - unplugged cable etc.
                self._emit("err", code="SERIAL", text=f"read failed: {exc}")
                self._link_lost()
                break
            now = self._clock()
            if data:
                self.feed(data, now)
            self.tick(now)

    # ------------------------------------------------------------------ the pure core
    def feed(self, data: bytes, now: float) -> None:
        """Bytes that arrived. Complete lines are processed; a trailing partial line waits for its end."""
        self._buf.extend(data)
        while True:
            i = self._buf.find(b"\n")
            if i < 0:
                break
            line = bytes(self._buf[:i])
            del self._buf[: i + 1]
            self.handle_line(line, now)
        if len(self._buf) > 512:            # no newline in 512 bytes is noise, not a protocol line
            self._buf.clear()
            self.counts["bad_lines"] += 1

    def handle_line(self, raw: bytes | str, now: float) -> None:
        msg = proto.parse_line(raw)
        if msg is None:
            return
        if msg["type"] == "bad":
            self.counts["bad_lines"] += 1     # a damaged line is counted and ignored: it does not prove the link is alive
            return
        self._last_rx = now
        self._set_link(True, now)
        kind = msg["type"]
        if kind == "hello":
            self._last_seq = None
            self.state["fw"] = msg["fw"]
            self._emit("hello", fw=msg["fw"], t=now)
            self._restore_wishes()            # a rebooted Nano starts inhibited: say again what was asked
        elif kind == "hb":
            self._on_heartbeat(msg)
        elif kind == "tap":
            if self._last_seq is not None and msg["seq"] == self._last_seq:
                return                         # the same line repeated is allowed by the protocol and ignored
            self.counts["taps"] += 1
            if self._last_seq is not None and msg["seq"] != (self._last_seq + 1) % 65536:
                self.counts["gaps"] += (msg["seq"] - self._last_seq - 1) % 65536
            self._last_seq = msg["seq"]
            self._emit("tap", t=now, **{k: v for k, v in msg.items() if k != "type"})
        elif kind == "ret":
            self.counts["rets"] += 1
            self._emit("ret", t=now, **{k: v for k, v in msg.items() if k != "type"})
        elif kind == "err":
            self.counts["errors"] += 1
            self._emit("err", t=now, code=msg["code"], text=msg["text"])
            if msg["code"] == "WDOGRESET":      # the Nano's watchdog tripped and has just recovered: re-arm
                self._restore_wishes()
        # PONG only proves the link; nothing to do

    def tick(self, now: float) -> None:
        if self._ser is not None and now - self._last_ping >= self._ping_s:
            self._last_ping = now
            self._ping_n += 1
            try:
                self._write(proto.encode_ping(self._ping_n))
            except Exception as exc:  # noqa: BLE001
                self._emit("err", code="SERIAL", text=f"write failed: {exc}")
                self._link_lost()
                return
        if self._link_up and self._last_rx is not None and now - self._last_rx > self._stale_s:
            self._set_link(False, now)

    def _on_heartbeat(self, hb: dict) -> None:
        st = self.state
        st["uptime_ms"] = hb["uptime_ms"]
        st["tof1_ok"] = hb["tof1_ok"]
        for k in ("manual", "retracted", "tof1_mm", "armed", "hold_pct", "up_wanted"):
            if k in hb:
                st[k] = hb[k]
        if "state" in hb:
            st["nano_state"] = hb["state"]

    def _set_link(self, up: bool, now: float) -> None:
        if up != self._link_up:
            self._link_up = up
            self._emit("link", up=up, t=now)

    def _link_lost(self) -> None:
        self._set_link(False, self._clock())

    def _restore_wishes(self) -> None:
        try:
            if self._want_manual is not None:
                self._write(proto.encode_mode(self._want_manual))
            if self._want_armed:
                self._write(proto.encode_strike(True))
        except Exception:  # noqa: BLE001 - the next tick reports a dead port
            pass

    # ------------------------------------------------------------------ commands
    def _write(self, data: bytes) -> None:
        ser = self._ser
        if ser is None:
            raise RuntimeError("not connected")
        with self._lock:
            ser.write(data)

    def set_manual(self, manual: bool) -> None:
        self._want_manual = manual
        self._write(proto.encode_mode(manual))

    def arm(self, armed: bool) -> None:
        """Allow / inhibit the striker. Disarming also forgets the wish, so a reboot cannot re-arm it."""
        self._want_armed = armed
        self._write(proto.encode_strike(armed))

    def strike_once(self) -> None:
        """Manual strike: make sure it is armed and in manual mode, then one retract-hold-release cycle."""
        self.set_manual(True)
        self.arm(True)
        self._write(proto.encode_tap_cycle())

    def request_tile(self) -> None:
        """Auto mode: a tile is coming - raise the striker; the ToF sees the tile and it strikes ~2 s later."""
        self.set_manual(False)
        self.arm(True)
        self._write(proto.encode_up())

    def retract(self) -> None:
        self._write(proto.encode_retract())

    def release(self) -> None:
        self._write(proto.encode_release())

    def set_hold(self, percent: float) -> None:
        self._write(proto.encode_hold(percent))

    # ------------------------------------------------------------------ for the GUI
    @property
    def link_ok(self) -> bool:
        return self._link_up

    def _emit(self, kind: str, **fields) -> None:
        self.events.put({"type": kind, **fields})

    def drain(self) -> list[dict]:
        out = []
        try:
            while True:
                out.append(self.events.get_nowait())
        except queue.Empty:
            pass
        return out

    def snapshot(self) -> dict:
        return {"connected": self.connected, "link_ok": self._link_up, **self.state, **self.counts}
