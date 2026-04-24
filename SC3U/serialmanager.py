"""
lib/serialmanager.py
─────────────────────
Library สำหรับสื่อสารกับ Motion Controller ผ่าน Serial Port
ทำงานเป็น Pure Library — ไม่มี Qt, ไม่มี print()
ทุก event ถูก log ผ่าน Python logging แทน

Public API:
    SerialManager(config?)       — สร้าง instance (โหลด settings.json อัตโนมัติ)
    .connect()                   — เปิด port
    .disconnect()                — ปิด port
    .reconfigure(dict)           — อัปเดต config ก่อน connect
    .save_config()               — บันทึกลง settings.json
    .stage                       — StageConfig (pulse/speed calculation)
    .scan_ports()                — list CH340/CH341 ports
    .check_connection()          — ตรวจ controller ตอบสนอง
    .get_speed() / .set_speed()        — อ่าน/ตั้งค่าความเร็ว (controller value 0-255)
    .get_speed_mm_s() / .set_speed_mm_s()  — อ่าน/ตั้งค่าความเร็ว (mm/s)
    .get_position() / .get_all_positions()         — อ่านตำแหน่ง (pulses)
    .get_position_mm() / .get_all_positions_mm()   — อ่านตำแหน่ง (mm)
    .move() / .move_to()         — เคลื่อนที่ (pulses)
    .move_mm() / .move_to_mm()   — เคลื่อนที่ (mm) — block จนเสร็จ คืน position (pulses)
    .wait_move_done()            — รอจนแกนหยุดนิ่ง (poll position)
    .home() / .home_all() / .get_home_status()
    .stop()
"""

import logging
import time
import serial
import serial.tools.list_ports
from typing import Optional

from SC3U.serial_config import SerialConfig

_log = logging.getLogger(__name__)



class SerialManager:
    """จัดการการสื่อสารผ่าน Serial Port สำหรับ Motion Controller"""

    AXES = {
        'X': 'X', 'Y': 'Y', 'Z': 'Z',
        'R': 'r', 'T1': 't', 'T2': 'T',
    }

    # ความหมายของ ERR code ตาม protocol spec
    ERROR_CODES: dict[str, str] = {
        "ERR1": "Communication error / invalid command sent / communication timeout",
        "ERR2": "Communication not established",
        "ERR3": "Invalid command",
        "ERR4": "Stop command received",
        "ERR5": "Limit switch triggered",
    }

    def __init__(self, config: SerialConfig | None = None):
        if config is None:
            config = SerialConfig.load(create_if_missing=True)
        self.config = config
        self.port = config.port or None
        self.baudrate = config.baudrate
        self.timeout = config.timeout
        self.connection: Optional[serial.Serial] = None
        self._moving_axes: set[str] = set()   # แกนที่กำลังเคลื่อนที่อยู่

    # ─────────────────────────────────────────
    # Port management
    # ─────────────────────────────────────────
    @staticmethod
    def scan_ports() -> list[dict]:
        """คืน list ของ CH340/CH341 ports ที่พบในระบบ"""
        raw = serial.tools.list_ports.comports()
        ports = []
        for p in sorted(raw, key=lambda x: x.device):
            desc = (p.description or "").upper()
            hwid  = (p.hwid or "").upper()
            if any(k in desc or k in hwid for k in ["CH340", "CH341"]):
                ports.append({
                    "device":      p.device,
                    "description": p.description,
                    "hwid":        p.hwid,
                })
        return ports

    def connect(self, port: str = None, baudrate: int = None, timeout: float = None) -> None:
        if port is None and self.port is None:
            ports = self.scan_ports()
            if not ports:
                raise RuntimeError("ไม่พบ CH340/CH341 port ในระบบ")
            port = ports[0]["device"]
            _log.info("Auto-select port: %s", port)

        self.port     = port or self.port
        self.baudrate = baudrate or self.baudrate
        self.timeout  = timeout if timeout is not None else self.timeout

        self.connection = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            bytesize=self.config.bytesize,
            parity=self.config.parity,
            stopbits=self.config.stopbits,
            timeout=self.timeout,
        )
        # sync กลับเข้า config
        self.config.port     = self.port
        self.config.baudrate = self.baudrate
        self.config.timeout  = self.timeout
        _log.info("Port opened: %s @ %d baud", self.port, self.baudrate)

        # ตรวจสอบว่า controller ตอบสนองจริง (ส่ง ?R → ต้องได้ OK ภายใน 200ms)
        if not self.check_connection():
            self.connection.close()
            self.connection = None
            raise ConnectionError(
                f"Controller ไม่ตอบสนอง — "
                f"กรุณาตรวจสอบว่าเครื่องเปิดอยู่และเชื่อมต่อกับ {self.port}"
            )
        _log.info("Controller verified OK: %s @ %d baud", self.port, self.baudrate)

    def disconnect(self) -> None:
        if self.connection and self.connection.is_open:
            self.connection.close()
            _log.info("Disconnected: %s", self.port)

    @property
    def is_connected(self) -> bool:
        return bool(self.connection and self.connection.is_open)

    def is_busy(self, axis: str | None = None) -> bool:
        """คืน True ถ้าแกนใดแกนหนึ่งกำลังเคลื่อนที่อยู่
        axis=None — ตรวจทุกแกน
        axis='X'  — ตรวจเฉพาะแกนนั้น
        """
        if axis is None:
            return bool(self._moving_axes)
        return self._resolve_axis(axis) in self._moving_axes

    # ─────────────────────────────────────────
    # Config helpers
    # ─────────────────────────────────────────
    @property
    def stage(self):
        """เข้าถึง StageConfig สำหรับคำนวณ pulse/speed"""
        return self.config.stage

    def reconfigure(self, d: dict) -> None:
        """
        อัปเดต config จาก dict ก่อนเรียก connect()
        รองรับ key: port, baudrate, bytesize, parity, stopbits, timeout
        """
        _PARITY   = {"None": "N", "Even": "E", "Odd": "O", "Mark": "M", "Space": "S",
                     "N": "N", "E": "E", "O": "O", "M": "M", "S": "S"}
        _STOPBITS = {"1": 1.0, "1.5": 1.5, "2": 2.0}

        if "port" in d:
            self.config.port = str(d["port"]).strip()
            self.port = self.config.port or None
        if "baudrate" in d:
            self.config.baudrate = int(d["baudrate"])
            self.baudrate = self.config.baudrate
        if "bytesize" in d:
            self.config.bytesize = int(d["bytesize"])
        if "parity" in d:
            self.config.parity = _PARITY.get(str(d["parity"]), self.config.parity)
        if "stopbits" in d:
            key = str(d["stopbits"])
            self.config.stopbits = _STOPBITS.get(key, float(key))
        if "timeout" in d:
            self.config.timeout = float(d["timeout"])
            self.timeout = self.config.timeout

    def save_config(self) -> None:
        """บันทึก config ปัจจุบันลง settings.json"""
        self.config.save()
        _log.debug("Config saved to %s", self.config.default_path())

    # ─────────────────────────────────────────
    # Low-level I/O
    # ─────────────────────────────────────────
    @staticmethod
    def _parse_error(response: str) -> str | None:
        """คืน ERR code ถ้า response มี ERR1–ERR5 มิฉะนั้นคืน None"""
        for token in response.split():
            if token in SerialManager.ERROR_CODES:
                return token
        return None

    def _raise_if_error(self, response: str, cmd: str) -> None:
        """ถ้า response มี ERR code → raise RuntimeError พร้อมคำอธิบาย"""
        err = self._parse_error(response)
        if err is not None:
            desc = self.ERROR_CODES[err]
            _log.error("Controller error for %r: %s — %s", cmd.strip(), err, desc)
            raise RuntimeError(f"{err}: {desc}")

    def _send(self, cmd: str) -> str:
        """ส่ง command และรับ response — raise ถ้าไม่ได้ connect หรือ motor กำลังทำงาน"""
        if not self.is_connected:
            raise ConnectionError("ยังไม่ได้เชื่อมต่อ Serial Port")
        if self._moving_axes:
            raise RuntimeError(
                f"Controller กำลังทำงานอยู่ (axes: {self._moving_axes}) — "
                f"รอจนเสร็จหรือเรียก wait_move_done() ก่อนส่ง command"
            )
        return self._send_raw(cmd)

    def _send_raw(self, cmd: str) -> str:
        """ส่ง command โดยไม่ตรวจ busy guard — ใช้ภายใน (wait_move_done, stop)

        Protocol (2 รูปแบบ):
          - Query  (?V, ?X, ?H, ...): echo+response รวม 1 line  → readline ครั้งเดียว
          - Command (X+N, VN, HXN, ...): echo (line 1) ผ่าน default timeout,
            OK (line 2) block ตลอดกาล (timeout=None) — controller ส่ง OK เมื่อเสร็จเสมอ
        """
        if not self.is_connected:
            raise ConnectionError("ยังไม่ได้เชื่อมต่อ Serial Port")
        _log.debug("TX: %r", cmd)
        _prev_timeout = self.connection.timeout
        try:
            self.connection.reset_input_buffer()
            self.connection.write(cmd.encode("ascii"))
            if cmd.startswith("?"):
                # Query — echo + response อยู่ใน line เดียวกัน
                response = self.connection.readline().decode("ascii", errors="replace").strip()
            else:
                # Command — line 1: echo, line 2: OK (block ตลอดกาล)
                echo = self.connection.readline().decode("ascii", errors="replace").strip()
                _log.debug("ECHO: %r", echo)
                self.connection.timeout = None   # block จนได้ OK
                response = self.connection.readline().decode("ascii", errors="replace").strip()
        finally:
            self.connection.timeout = _prev_timeout
        _log.debug("RX: %r", response)
        self._raise_if_error(response, cmd)
        return response

    def _expect_ok(self, cmd: str) -> bool:
        resp = self._send(cmd)
        ok = "OK" in resp
        if not ok:
            _log.warning("Expected OK for %r, got %r", cmd.strip(), resp)
        return ok

    # ─────────────────────────────────────────
    # (1) Connection check
    # ─────────────────────────────────────────
    def _ping(self) -> bool:
        """ส่ง ?R\\r แล้วรอ OK ภายใน 200ms — คืน True/False โดยไม่มี side-effect
        ใช้สำหรับ poll ขณะ motor วิ่ง (wait_move_done)
        """
        if not self.is_connected:
            return False
        _prev_timeout = self.connection.timeout
        try:
            self.connection.timeout = 0.2
            self.connection.reset_input_buffer()
            self.connection.write(b"?R\r")
            raw  = self.connection.readline()
            resp = raw.decode("ascii", errors="replace")
            return "?R" in resp and "OK" in resp
        except Exception:
            return False
        finally:
            self.connection.timeout = _prev_timeout

    def check_connection(self) -> bool:
        """
        ส่ง ?R\\r → ตรวจสอบว่า controller ตอบกลับ OK ภายใน 200ms (ตามสเปค)

        Side-effect:
          - OK  → คืน True (connection alive)
          - ไม่ได้ OK หรือ exception → ปิด port, reset state, คืน False
        """
        ok = self._ping()

        if ok:
            _log.info("Controller responded OK — connection alive")
        else:
            _log.warning("Controller did not respond — closing port")
            try:
                self.connection.close()
            except Exception:
                pass
            self.connection = None
            self._moving_axes.clear()
        return ok

    # ─────────────────────────────────────────
    # (2) Speed inquiry
    # ─────────────────────────────────────────
    def get_speed(self) -> int:
        """อ่านค่าความเร็วปัจจุบัน (0-255)"""
        resp = self._send("?V\r")
        for part in resp.split():
            if part.startswith("V") and part[1:].isdigit():
                return int(part[1:])
        raise ValueError(f"parse speed failed: {resp!r}")

    def get_speed_mm_s(self) -> float:
        """อ่านค่าความเร็วปัจจุบัน แปลงเป็น mm/s"""
        return self.stage.actual_speed_mm_s(self.get_speed())

    # ─────────────────────────────────────────
    # (3) Position inquiry
    # ─────────────────────────────────────────
    def get_position(self, axis: str) -> int:
        """อ่านตำแหน่งแกน (X/Y/Z/R/T1/T2) คืนค่าเป็น int"""
        ax = self._resolve_axis(axis)
        resp = self._send(f"?{ax}\r")
        for part in resp.split():
            if part.startswith(ax) or part.startswith(axis.upper()):
                sign   = -1 if "-" in part else 1
                number = int("".join(filter(str.isdigit, part)))
                return sign * number
        raise ValueError(f"parse position failed for {axis!r}: {resp!r}")

    def _get_position_raw(self, axis: str) -> int:
        """อ่านตำแหน่งแกน — bypass busy guard ใช้สำหรับ poll ใน wait_move_done()"""
        ax = self._resolve_axis(axis)
        resp = self._send_raw(f"?{ax}\r")
        for part in resp.split():
            if part.startswith(ax) or part.startswith(axis.upper()):
                sign   = -1 if "-" in part else 1
                number = int("".join(filter(str.isdigit, part)))
                return sign * number
        raise ValueError(f"parse position failed for {axis!r}: {resp!r}")

    def get_all_positions(self) -> dict[str, int]:
        """อ่านตำแหน่งทุกแกน คืนค่าเป็น pulses"""
        return {name: self.get_position(name) for name in self.AXES}

    def get_position_mm(self, axis: str) -> float:
        """อ่านตำแหน่งแกน คืนค่าเป็น mm"""
        pulses = self.get_position(axis)
        return self.stage.actual_displacement_um(pulses) / 1000.0

    def get_all_positions_mm(self) -> dict[str, float]:
        """อ่านตำแหน่งทุกแกน คืนค่าเป็น mm"""
        return {name: self.get_position_mm(name) for name in self.AXES}

    # ─────────────────────────────────────────
    # (4) Speed setting
    # ─────────────────────────────────────────
    def set_speed(self, speed: int) -> bool:
        """ตั้งค่าความเร็ว (0-255)"""
        if not 0 <= speed <= 255:
            raise ValueError(f"speed {speed} out of range 0-255")
        return self._expect_ok(f"V{speed}\r")

    def set_speed_mm_s(self, mm_s: float) -> bool:
        """ตั้งค่าความเร็วเป็น mm/s (แปลงเป็น controller value อัตโนมัติ)"""
        if mm_s <= 0:
            raise ValueError(f"speed must be > 0 mm/s, got {mm_s}")
        value = self.stage.speed_value_for_mm_s(mm_s)
        if not 0 <= value <= 255:
            raise ValueError(
                f"{mm_s} mm/s → value={value} out of range 0-255"
            )
        return self.set_speed(value)

    # ─────────────────────────────────────────
    # (5) Home
    # ─────────────────────────────────────────
    def home(self, axis: str, return_after: bool = False) -> bool:
        """สั่ง Home แกนที่ระบุ — block จน homing เสร็จ (controller ตอบ OK เมื่อจบ)"""
        ax   = self._resolve_axis(axis)
        mode = "1" if return_after else "0"
        return self._expect_ok(f"H{ax}{mode}\r")

    def home_all(self, return_after: bool = False) -> dict[str, bool]:
        """Home ทุกแกน"""
        return {name: self.home(name, return_after) for name in self.AXES}

    # ─────────────────────────────────────────
    # (6) Home status
    # ─────────────────────────────────────────
    def get_home_status(self) -> dict[str, bool]:
        """คืน dict {'X': bool, 'Y': bool, ...} สถานะ home แต่ละแกน"""
        resp = self._send("?H\r")
        for part in resp.split():
            if "ERR" in part:
                raise RuntimeError(
                    f"Controller returned {part!r} for ?H — "
                    "controller may still be homing or busy"
                )
            if part.startswith("H") and len(part) == 7:
                bits = part[1:]
                axes = list(self.AXES.keys())
                return {ax: (bits[i] == "1") for i, ax in enumerate(axes)}
        raise ValueError(f"parse home status failed: {resp!r}")

    # ─────────────────────────────────────────
    # (7) Motion
    # ─────────────────────────────────────────
    def move(self, axis: str, displacement: int) -> bool:
        """เคลื่อนที่ displacement pulses (+ หรือ -)"""
        ax        = self._resolve_axis(axis)
        direction = "+" if displacement >= 0 else "-"
        pulses    = abs(displacement)
        ok = self._expect_ok(f"{ax}{direction}{pulses}\r")
        if ok:
            self._moving_axes.add(ax)   # mark แกนว่ากำลังเคลื่อนที่
        return ok

    def move_mm(self, axis: str, mm: float) -> int:
        """เคลื่อนที่เป็น mm — block จนเสร็จ คืน position สุดท้าย (pulses)"""
        pulses = self.stage.pulse_number_for_mm(abs(mm))
        if pulses == 0:
            return self.get_position(axis)
        displacement = pulses if mm >= 0 else -pulses
        ok = self.move(axis, displacement)
        if not ok:
            raise RuntimeError(f"move_mm: controller did not accept command")
        return self.wait_move_done(axis)

    def move_to(self, axis: str, target: int) -> bool:
        """เคลื่อนที่ไปตำแหน่งเป้าหมาย pulse target (คำนวณ displacement อัตโนมัติ)"""
        current      = self.get_position(axis)
        displacement = target - current
        if displacement == 0:
            return True
        return self.move(axis, displacement)

    def move_to_mm(self, axis: str, target_mm: float) -> int:
        """เคลื่อนที่ไปตำแหน่งเป้าหมาย mm — block จนเสร็จ คืน position สุดท้าย (pulses)"""
        current_mm   = self.get_position_mm(axis)
        displacement = target_mm - current_mm
        if abs(displacement) < self.stage.pulse_equivalent_mm():
            return self.get_position(axis)   # น้อยกว่า 1 pulse ไม่ต้องเคลื่อนที่
        return self.move_mm(axis, displacement)

    # ─────────────────────────────────────────
    # (8) Stop
    # ─────────────────────────────────────────
    def stop(self) -> bool:
        """หยุดการเคลื่อนที่ทันที"""
        # stop ส่งได้เสมอ แม้ motor กำลังทำงาน — bypass busy guard
        if not self.is_connected:
            raise ConnectionError("ยังไม่ได้เชื่อมต่อ Serial Port")
        self.connection.reset_input_buffer()
        self.connection.write(b"S\r")
        resp = self.connection.readline().decode("ascii", errors="replace").strip()
        ok = "OK" in resp
        if ok:
            self._moving_axes.clear()   # clear ทุกแกน
        return ok

    # ─────────────────────────────────────────
    # (9) Wait for motion complete
    # ─────────────────────────────────────────
    def wait_move_done(
        self,
        axis: str,
        poll_interval: float = 0.05,
        timeout: float = 30.0,
    ) -> int:
        """Block จนกว่าการเคลื่อนที่จะเสร็จ

        เงื่อนไข "เสร็จ":
          1. controller ตอบ ?R → OK ได้ (not busy)
          2. อ่านค่า position ของแกนนั้นได้สำเร็จ

        Args:
            axis:          แกนที่รอ (X/Y/Z/R/T1/T2)
            poll_interval: ระยะห่างระหว่าง poll แต่ละรอบ (วินาที)
            timeout:       เวลาสูงสุดที่รอ (วินาที) ก่อน raise TimeoutError

        Returns:
            ตำแหน่งสุดท้ายของแกน (pulses)

        Raises:
            TimeoutError:    ถ้าเกิน timeout แล้วยังไม่เสร็จ
            ConnectionError: ถ้า port ถูกปิดระหว่างรอ
        """
        ax       = self._resolve_axis(axis)
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            time.sleep(poll_interval)

            # ตรวจ connection ยังอยู่ไหม — ถ้าหลุดออกทันที
            if not self._ping():
                self._moving_axes.discard(ax)
                raise ConnectionError(
                    f"wait_move_done: connection lost while waiting for axis {axis!r}"
                )

            # connection OK แต่ยังวิ่งอยู่ → position query จะ timeout/fail
            # เสร็จเมื่ออ่าน position สำเร็จ
            try:
                pos = self._get_position_raw(axis)
            except Exception:
                continue   # motor ยังวิ่ง — poll รอบถัดไป

            self._moving_axes.discard(ax)
            _log.debug("wait_move_done: %s done at %d pulses", axis, pos)
            return pos

        raise TimeoutError(
            f"wait_move_done: axis {axis!r} did not complete within {timeout:.1f}s"
        )

    # ─────────────────────────────────────────
    # Helper
    # ─────────────────────────────────────────
    def _resolve_axis(self, axis: str) -> str:
        key = axis.upper()
        if key not in self.AXES:
            raise ValueError(
                f"Invalid axis {axis!r}. Valid: {list(self.AXES.keys())}"
            )
        return self.AXES[key]

    # ─────────────────────────────────────────
    # Context Manager
    # ─────────────────────────────────────────
    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()

    def __repr__(self):
        status = "connected" if self.is_connected else "disconnected"
        return f"<SerialManager port={self.port!r} [{status}]>"
