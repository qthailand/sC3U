"""
core/serial_controller.py
──────────────────────────
Business-logic bridge between MainWindow (Qt signals/slots) and SerialManager.

Thread model:
  Main Thread (Qt GUI)
   └── SerialController
         ├── PortScannerThread  — one-shot scan comports
         ├── ReaderThread       — continuous RX poll → terminal_output
         └── WriterThread       — queue-based TX
"""

import logging
import queue
import threading
import time
from dataclasses import dataclass

from PyQt5.QtCore import QObject, pyqtSignal

from SC3U.serial_config import SerialConfig
from SC3U.serialmanager import SerialManager


@dataclass
class PortInfo:
    """DTO ที่ populate_ports() ของ MainWindow ต้องการ (.device / .description)"""
    device: str
    description: str


class SerialController(QObject):
    """
    รับ signals จาก MainWindow → สั่ง SerialManager
    ส่ง signals กลับ → อัปเดต UI
    """

    # ── Signals → MainWindow ───────────────────────────────────
    connected           = pyqtSignal(str, int)   # port, baudrate
    disconnected        = pyqtSignal()
    terminal_output     = pyqtSignal(str, str)   # text, color
    rx_updated          = pyqtSignal(int)
    tx_updated          = pyqtSignal(int)
    scanning_changed    = pyqtSignal(bool)
    ports_found         = pyqtSignal(list)
    speed_value_changed = pyqtSignal(str)         # raw controller value (0-255)
    stage_config_updated = pyqtSignal(object)     # StageConfig หลัง connect สำเร็จ

    def __init__(self, parent=None):
        super().__init__(parent)
        self._manager: SerialManager | None = None
        self._rx_total = 0
        self._tx_total = 0
        self._tx_queue: queue.Queue[bytes | None] = queue.Queue()
        self._stop_event = threading.Event()
        self._reader_thread: threading.Thread | None = None
        self._writer_thread: threading.Thread | None = None
        self._logger = logging.getLogger(__name__)

    # ══════════════════════════════════════════════════════════
    #  Public slots (connected from main.py)
    # ══════════════════════════════════════════════════════════
    @property
    def _config(self):
        """อ่าน config ปัจจุบันจาก SerialManager (ใช้ใน __main__.py)"""
        return self._manager.config if self._manager else SerialConfig.load(create_if_missing=True)

    def open(self, config_dict: dict) -> None:
        """เปิด serial port ตาม config_dict ที่ UI ส่งมา"""
        if self._manager:
            # ปิด silently — ไม่ emit disconnected เพื่อไม่ให้ UI flash
            self._cleanup()

        try:
            self._manager = SerialManager()          # โหลด settings.json อัตโนมัติ
            self._manager.reconfigure(config_dict)   # override ด้วยค่าจาก UI
            self._manager.connect()           # เปิด port + ตรวจสอบ controller ใน connect()
            self._manager.save_config()              # บันทึก port/baud ที่ใช้งานจริง
            self._rx_total = 0
            self._tx_total = 0
            self._stop_event.clear()
            self._tx_queue = queue.Queue()   # reset queue — ล้าง None sentinel จาก close ครั้งก่อน

            self._reader_thread = threading.Thread(
                target=self._reader_loop, name="ReaderThread", daemon=True
            )
            self._writer_thread = threading.Thread(
                target=self._writer_loop, name="WriterThread", daemon=True
            )
            self._reader_thread.start()
            self._writer_thread.start()

            self.connected.emit(self._manager.port, self._manager.baudrate)
            self.stage_config_updated.emit(self._manager.stage)
            self.terminal_output.emit(
                f"[Connected] {self._manager.port} @ {self._manager.baudrate} baud\n",
                "#27ae60",
            )
            self._logger.info("Connected to %s @ %d", self._manager.port, self._manager.baudrate)

        except Exception as exc:
            if self._manager:
                try:
                    self._manager.disconnect()
                except Exception:
                    pass
                self._manager = None
            self.terminal_output.emit(f"[ERROR] {exc}\n", "#e74c3c")
            self._logger.error("Connection failed: %s", exc)

    def close(self) -> None:
        """ปิด serial port และหยุด threads"""
        self._cleanup()
        self.disconnected.emit()
        self.terminal_output.emit("[Disconnected]\n", "#e67e22")
        self._logger.info("Disconnected")

    def send(self, data: bytes) -> None:
        """ใส่ data ลง TX queue (เรียกจาก main thread ได้ปลอดภัย)"""
        self._tx_queue.put(data)

    def refresh(self) -> None:
        """สแกน COM port แบบ non-blocking"""
        self.scanning_changed.emit(True)
        t = threading.Thread(target=self._scan_ports, name="PortScannerThread", daemon=True)
        t.start()

    def set_log_level(self, level: int) -> None:
        logging.getLogger().setLevel(level)

    def shutdown(self) -> None:
        """เรียกจาก closeEvent ของ MainWindow"""
        self.close()

    # ══════════════════════════════════════════════════════════
    #  Background threads
    # ══════════════════════════════════════════════════════════
    def _cleanup(self) -> None:
        """หยุด threads และปิด manager — ไม่ emit signals (ใช้ภายในเท่านั้น)"""
        self._stop_event.set()
        self._tx_queue.put(None)  # unblock writer thread

        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.0)
        self._reader_thread = None

        if self._writer_thread and self._writer_thread.is_alive():
            self._writer_thread.join(timeout=1.0)
        self._writer_thread = None

        if self._manager:
            try:
                self._manager.disconnect()
            except Exception:
                pass
            self._manager = None
    def _scan_ports(self) -> None:
        try:
            raw = SerialManager.scan_ports()   # กรอง CH340/CH341 เท่านั้น
            ports = [
                PortInfo(p["device"], p["description"] or p["device"])
                for p in raw
            ]
            self.ports_found.emit(ports)
        except Exception as exc:
            self._logger.error("Port scan failed: %s", exc)
        finally:
            self.scanning_changed.emit(False)

    def _reader_loop(self) -> None:
        """อ่าน RX ต่อเนื่อง → emit terminal_output และ parse speed response"""
        rx_buf = b""
        while not self._stop_event.is_set():
            try:
                conn = self._manager.connection if self._manager else None
                if not conn or not conn.is_open:
                    break
                waiting = conn.in_waiting
                if waiting:
                    chunk = conn.read(waiting)
                    self._rx_total += len(chunk)
                    self.terminal_output.emit(
                        chunk.decode("ascii", errors="replace"), "#d4d4d4"
                    )
                    self.rx_updated.emit(self._rx_total)

                    # parse speed response "V<number>" จากบรรทัดที่ controller ส่งมา
                    rx_buf += chunk
                    lines = rx_buf.split(b"\n")
                    rx_buf = lines[-1]
                    for line in lines[:-1]:
                        for token in line.decode("ascii", errors="replace").split():
                            # parse speed response "V<number>"
                            if token.startswith("V") and token[1:].isdigit():
                                self.speed_value_changed.emit(token[1:])
                            # parse ERR codes ตาม protocol spec
                            elif token in SerialManager.ERROR_CODES:
                                desc = SerialManager.ERROR_CODES[token]
                                self.terminal_output.emit(
                                    f"[{token}] {desc}\n", "#e74c3c"
                                )
                else:
                    time.sleep(0.01)

            except Exception as exc:
                if not self._stop_event.is_set():
                    self.terminal_output.emit(f"[RX ERROR] {exc}\n", "#e74c3c")
                    self._logger.error("Reader error: %s", exc)
                break

    def _writer_loop(self) -> None:
        """รอ bytes จาก TX queue แล้วเขียนลง serial"""
        while not self._stop_event.is_set():
            try:
                data = self._tx_queue.get(timeout=0.1)
                if data is None:
                    break
                conn = self._manager.connection if self._manager else None
                if conn and conn.is_open:
                    conn.write(data)
                    self._tx_total += len(data)
                    self.tx_updated.emit(self._tx_total)
            except queue.Empty:
                continue
            except Exception as exc:
                if not self._stop_event.is_set():
                    self.terminal_output.emit(f"[TX ERROR] {exc}\n", "#e74c3c")
                    self._logger.error("Writer error: %s", exc)
                break
