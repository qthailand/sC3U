"""
ui/main_window.py
──────────────────
Main Window — ประกอบ widget ต่าง ๆ เข้าด้วยกัน
ไม่มี business logic ใด ๆ ของ serial / thread อยู่ในนี้
ทุกอย่างโยนให้ SerialController จัดการผ่าน signal/slot
"""

import logging
import datetime

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QTextEdit, QLineEdit,
    QGroupBox, QGridLayout, QSplitter, QStatusBar, QCheckBox,
    QRadioButton, QButtonGroup,
)
from PyQt5.QtCore import Qt, QDateTime, pyqtSignal
from PyQt5.QtGui import QColor, QTextCursor, QFont, QPalette
from SC3U.serial_config import SerialConfig


class MainWindow(QMainWindow):
    """
    Pure UI class — ไม่รู้จัก serial หรือ thread
    ส่ง request ออกผ่าน signals, รับผลผ่าน public methods/slots
    """

    # ── Signals (GUI → Controller) ─────────────────────────────
    connect_requested    = pyqtSignal(dict)   # config dict
    disconnect_requested = pyqtSignal()
    send_requested       = pyqtSignal(bytes)  # raw bytes พร้อมส่ง
    refresh_requested    = pyqtSignal()
    log_level_changed    = pyqtSignal(int)    # logging level int

    # ── Signal รับ log จาก QtLogHandler (int level, str msg) ──
    log_signal = pyqtSignal(int, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyQt5 Serial Monitor  |  Multi-Thread Edition")
        self.resize(1080, 720)
        # โหลด StageConfig จาก settings ทันทีที่เปิด UI
        # (set_stage_config จะ override อีกครั้งหลัง connect สำเร็จ)
        self._stage_config = SerialConfig.load(create_if_missing=True).stage
        self._build_ui()
        self.log_signal.connect(self._append_log)

    # ══════════════════════════════════════════════════════════
    #  Build UI
    # ══════════════════════════════════════════════════════════
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        root.addWidget(self._build_config_group())
        root.addWidget(self._build_stage_control_group())
        root.addWidget(self._build_splitter(), stretch=1)

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._lbl_rx = QLabel("RX: 0 B")
        self._lbl_tx = QLabel("TX: 0 B")
        self._status_bar.addPermanentWidget(self._lbl_rx)
        self._status_bar.addPermanentWidget(self._lbl_tx)
        self.set_status("Disconnected", connected=False)

    # ── Config Group ───────────────────────────────────────────
    def _build_config_group(self) -> QGroupBox:
        grp = QGroupBox("Serial Port Configuration")
        g = QGridLayout(grp)

        g.addWidget(QLabel("Port:"), 0, 0)
        self.combo_port = QComboBox()
        self.combo_port.setMinimumWidth(140)
        g.addWidget(self.combo_port, 0, 1)

        self._btn_refresh = QPushButton("⟳ Refresh")
        self._btn_refresh.clicked.connect(self.refresh_requested)
        g.addWidget(self._btn_refresh, 0, 2)

        self._btn_connect = QPushButton("🔌 Connect")
        self._btn_connect.setMinimumWidth(110)
        self._btn_connect.clicked.connect(self._on_connect_clicked)
        self._style_btn_connect(connected=False)
        g.addWidget(self._btn_connect, 0, 3, 2, 1)

        return grp

    def _build_stage_control_group(self) -> QGroupBox:
        grp = QGroupBox("Stage XYZ Control")
        g = QGridLayout(grp)
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(6)

        btn_speed = QPushButton("Query Speed")
        btn_speed.clicked.connect(self._on_cmd_speed_inquiry)
        g.addWidget(btn_speed, 0, 0)

        btn_stop = QPushButton("Stop")
        btn_stop.clicked.connect(self._on_cmd_stop)
        g.addWidget(btn_stop, 0, 1)

        g.addWidget(QLabel("Position inquiry:"), 1, 0)
        pos_layout = QHBoxLayout()
        for axis in ["X", "Y", "Z", "r", "t", "T"]:
            btn = QPushButton(axis)
            btn.clicked.connect(lambda _, a=axis: self._on_cmd_position_inquiry(a))
            pos_layout.addWidget(btn)
        g.addLayout(pos_layout, 1, 1, 1, 4)

        g.addWidget(QLabel("Set speed (mm/s):"), 2, 0)
        self.edit_speed = QLineEdit()
        self.edit_speed.setFixedWidth(80)
        self.edit_speed.setPlaceholderText("mm/s")
        g.addWidget(self.edit_speed, 2, 1)
        btn_set_speed = QPushButton("Set Speed")
        btn_set_speed.clicked.connect(self._on_cmd_set_speed)
        g.addWidget(btn_set_speed, 2, 2, 1, 2)

        g.addWidget(QLabel("Origin mode:"), 3, 0)
        self.combo_origin_mode = QComboBox()
        self.combo_origin_mode.addItems(["0", "1"])
        g.addWidget(self.combo_origin_mode, 3, 1)

        for index, axis in enumerate(["X", "Y", "Z", "r", "t", "T"]):
            btn = QPushButton(axis)
            btn.clicked.connect(lambda _, a=axis: self._on_cmd_origin(a))
            g.addWidget(btn, 4 + index // 3, index % 3)

        g.addWidget(QLabel("Move axis:"), 6, 0, 1, 5)

        g.addWidget(QLabel("Axis"), 7, 0)
        g.addWidget(QLabel("Direction"), 7, 1)
        g.addWidget(QLabel("Distance (μm)"), 7, 2)
        g.addWidget(QLabel("Go"), 7, 3)

        self._move_step_edits = {}
        self._move_dir_groups = {}

        for row, axis in enumerate(["X", "Y", "Z"], start=8):
            g.addWidget(QLabel(axis), row, 0)

            dir_group = QButtonGroup(self)
            r_plus = QRadioButton("+")
            r_minus = QRadioButton("-")
            r_plus.setChecked(True)
            dir_group.addButton(r_plus)
            dir_group.addButton(r_minus)
            radio_layout = QHBoxLayout()
            radio_layout.addWidget(r_plus)
            radio_layout.addWidget(r_minus)
            container = QWidget()
            container.setLayout(radio_layout)
            g.addWidget(container, row, 1)
            self._move_dir_groups[axis] = dir_group

            edit_step = QLineEdit()
            edit_step.setFixedWidth(80)
            edit_step.setPlaceholderText("μm")
            edit_step.setText("1000")
            g.addWidget(edit_step, row, 2)
            self._move_step_edits[axis] = edit_step

            btn_move = QPushButton("Move")
            btn_move.clicked.connect(lambda _, a=axis: self._on_cmd_move_axis(a))
            g.addWidget(btn_move, row, 3)

        return grp

    # ── Splitter (Terminal | Logger) ───────────────────────────
    def _build_splitter(self) -> QSplitter:
        sp = QSplitter(Qt.Horizontal)
        sp.addWidget(self._build_terminal_panel())
        sp.addWidget(self._build_logger_panel())
        sp.setSizes([580, 480])
        return sp

    def _build_terminal_panel(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)

        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("📡 Terminal"))
        self.chk_hex_rx = QCheckBox("HEX RX")
        self.chk_timestamp = QCheckBox("Timestamp")
        self.chk_timestamp.setChecked(True)
        hdr.addWidget(self.chk_hex_rx)
        hdr.addWidget(self.chk_timestamp)
        hdr.addStretch()
        btn_clr = QPushButton("Clear")
        btn_clr.clicked.connect(self.clear_terminal)
        hdr.addWidget(btn_clr)
        lay.addLayout(hdr)

        self.terminal = QTextEdit()
        self.terminal.setReadOnly(True)
        self.terminal.setFont(QFont("Consolas", 9))
        self.terminal.setStyleSheet(
            "background:#1e1e1e; color:#d4d4d4; border:1px solid #444;"
        )
        lay.addWidget(self.terminal)

        # Send bar
        send = QHBoxLayout()
        self.edit_send = QLineEdit()
        self.edit_send.setPlaceholderText("Type message to send…")
        self.edit_send.returnPressed.connect(self._on_send)
        send.addWidget(self.edit_send)
        self.chk_hex_tx = QCheckBox("HEX TX")
        send.addWidget(self.chk_hex_tx)
        self.chk_crlf = QCheckBox("CR+LF")
        self.chk_crlf.setChecked(True)
        send.addWidget(self.chk_crlf)
        btn_send = QPushButton("Send ▶")
        btn_send.setStyleSheet(
            "QPushButton{background:#2980b9;color:white;font-weight:bold;"
            "border-radius:4px;padding:5px 12px;}"
            "QPushButton:hover{background:#3498db;}"
        )
        btn_send.clicked.connect(self._on_send)
        send.addWidget(btn_send)
        lay.addLayout(send)
        return w

    def _build_logger_panel(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)

        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("🪵 Logger"))
        hdr.addStretch()
        self.combo_log_level = QComboBox()
        self.combo_log_level.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.combo_log_level.currentTextChanged.connect(
            lambda s: self.log_level_changed.emit(getattr(logging, s, logging.DEBUG))
        )
        hdr.addWidget(QLabel("Level:"))
        hdr.addWidget(self.combo_log_level)
        btn_clr = QPushButton("Clear")
        btn_clr.clicked.connect(self.clear_log)
        hdr.addWidget(btn_clr)
        lay.addLayout(hdr)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Consolas", 8))
        self.log_view.setStyleSheet(
            "background:#0d0d0d; color:#a8a8a8; border:1px solid #333;"
        )
        lay.addWidget(self.log_view)

        # Manual log test buttons
        dbg = QHBoxLayout()
        for lvl, col in [
            ("DEBUG",   "#888"),
            ("INFO",    "#27ae60"),
            ("WARNING", "#e67e22"),
            ("ERROR",   "#e74c3c"),
        ]:
            btn = QPushButton(lvl)
            btn.setStyleSheet(
                f"QPushButton{{color:{col};border:1px solid {col};"
                f"border-radius:3px;padding:3px 8px;}}"
                f"QPushButton:hover{{background:{col}22;}}"
            )
            btn.clicked.connect(
                lambda _, l=lvl: self._manual_log(l)
            )
            dbg.addWidget(btn)
        lay.addLayout(dbg)
        return w

    # ══════════════════════════════════════════════════════════
    #  Internal Slots (UI events → emit signals)
    # ══════════════════════════════════════════════════════════
    def _on_connect_clicked(self):
        if self._btn_connect.property("connected"):
            self.disconnect_requested.emit()
        else:
            port = self.combo_port.currentData() or ""
            if not port:
                self.append_terminal("[ERROR] No port selected — please refresh and select a port\n", "#e74c3c")
                return
            cfg = {
                "port":     port,
                "baudrate": 9600,
                "bytesize": 8,
                "parity":   "None",
                "stopbits": "1",
            }
            self.connect_requested.emit(cfg)

    def _on_send(self):
        text = self.edit_send.text().strip()
        if not text:
            return
        try:
            if self.chk_hex_tx.isChecked():
                raw = bytes.fromhex(text.replace(" ", ""))
            else:
                raw = text.encode("utf-8")
                if self.chk_crlf.isChecked():
                    raw += b"\r\n"
            self.send_requested.emit(raw)
            self.edit_send.clear()
        except ValueError:
            self.append_terminal("[ERROR] Invalid HEX string\n", "#e74c3c")

    def _send_stage_command(self, command: str) -> None:
        raw = command.encode("ascii")
        self.send_requested.emit(raw)

    def _on_cmd_speed_inquiry(self) -> None:
        self._send_stage_command("?V\r")

    def _on_cmd_position_inquiry(self, axis: str) -> None:
        self._send_stage_command(f"?{axis}\r")

    def _on_cmd_set_speed(self) -> None:
        value = self.edit_speed.text().strip()
        try:
            mm_s = float(value)
        except ValueError:
            self.append_terminal("[ERROR] Speed must be a number in mm/s\n", "#e74c3c")
            return

        if mm_s <= 0:
            self.append_terminal("[ERROR] Speed must be greater than 0 mm/s\n", "#e74c3c")
            return

        if self._stage_config is None:
            self.append_terminal("[ERROR] Stage config not available\n", "#e74c3c")
            return

        speed_value = self._stage_config.speed_value_for_mm_s(mm_s)
        if speed_value < 0 or speed_value > 255:
            self.append_terminal("[ERROR] Converted speed value out of range (0-255)\n", "#e74c3c")
            return

        self.append_terminal(
            f"[INFO] Set speed {mm_s:.3f} mm/s => controller value {speed_value}\n",
            "#a9cce3"
        )
        self._send_stage_command(f"V{speed_value}\r")

    def _on_cmd_origin(self, axis: str) -> None:
        mode = self.combo_origin_mode.currentText()
        self._send_stage_command(f"H{axis}{mode}\r")

    def _on_cmd_move_axis(self, axis: str) -> None:
        dir_group = self._move_dir_groups.get(axis)
        if dir_group is None:
            return

        direction = None
        for btn in dir_group.buttons():
            if btn.isChecked():
                direction = btn.text()
                break

        value_text = self._move_step_edits[axis].text().strip()
        try:
            um_value = float(value_text)
        except ValueError:
            self.append_terminal("[ERROR] Move distance must be a number in μm\n", "#e74c3c")
            return

        if um_value <= 0:
            self.append_terminal("[ERROR] Move distance must be greater than 0\n", "#e74c3c")
            return

        if self._stage_config is None:
            self.append_terminal("[ERROR] Stage config not available\n", "#e74c3c")
            return

        pulses = self._stage_config.pulse_number_for_um(um_value)
        if pulses <= 0:
            self.append_terminal("[ERROR] Calculated pulse count is invalid\n", "#e74c3c")
            return

        self.append_terminal(
            f"[INFO] {axis} move {um_value} μm => {pulses} pulses\n",
            "#a9cce3"
        )
        self._send_stage_command(f"{axis}{direction}{pulses}\r")

    def _on_cmd_stop(self) -> None:
        self._send_stage_command("S\r")

    def _manual_log(self, level: str):
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        logging.getLogger("Manual").log(
            getattr(logging, level),
            f"Test {level} fired at {ts}"
        )

    # ══════════════════════════════════════════════════════════
    #  Public Methods (called by Controller)
    # ══════════════════════════════════════════════════════════
    def populate_ports(self, port_infos: list) -> None:
        """เติม ComboBox port จาก PortInfo list"""
        self.combo_port.clear()
        if port_infos:
            for p in port_infos:
                self.combo_port.addItem(
                    f"{p.device}  ({p.description})", p.device
                )
        else:
            self.combo_port.addItem("No ports found")

    def set_connected(self, port: str, baud: int) -> None:
        self._btn_connect.setProperty("connected", True)
        self._btn_connect.setText("⛔ Disconnect")
        self._style_btn_connect(connected=True)
        self.set_status(f"Connected  {port} @ {baud}", connected=True)

    def set_disconnected(self) -> None:
        self._btn_connect.setProperty("connected", False)
        self._btn_connect.setText("🔌 Connect")
        self._style_btn_connect(connected=False)
        self.set_status("Disconnected", connected=False)

    def update_rx(self, total_bytes: int) -> None:
        self._lbl_rx.setText(f"RX: {total_bytes} B")

    def update_tx(self, total_bytes: int) -> None:
        self._lbl_tx.setText(f"TX: {total_bytes} B")

    def set_stage_config(self, stage_cfg) -> None:
        """รับ StageConfig จาก SerialController หลัง connect สำเร็จ"""
        self._stage_config = stage_cfg

    def set_speed_value(self, raw_value: str) -> None:
        """รับ raw controller value (0-255) แปลงเป็น mm/s ก่อนแสดงใน field"""
        if not raw_value:
            return
        try:
            value = int(raw_value)
            if self._stage_config is not None:
                mm_s = self._stage_config.actual_speed_mm_s(value)
                self.edit_speed.setText(f"{mm_s:.3f}")
            else:
                self.edit_speed.setText(raw_value)
        except ValueError:
            self.edit_speed.setText(raw_value)

    def append_terminal(self, text: str, color: str = "#d4d4d4") -> None:
        cur = self.terminal.textCursor()
        cur.movePosition(QTextCursor.End)
        self.terminal.setTextCursor(cur)

        if self.chk_timestamp.isChecked():
            ts = QDateTime.currentDateTime().toString("[hh:mm:ss.zzz] ")
            self.terminal.setTextColor(QColor("#555"))
            self.terminal.insertPlainText(ts)

        self.terminal.setTextColor(QColor(color))
        self.terminal.insertPlainText(text)
        self.terminal.ensureCursorVisible()

    def clear_terminal(self) -> None:
        self.terminal.clear()

    def clear_log(self) -> None:
        self.log_view.clear()

    def set_status(self, msg: str, connected: bool) -> None:
        color = "#27ae60" if connected else "#e74c3c"
        self._status_bar.setStyleSheet(f"color:{color};")
        self._status_bar.showMessage(f"● {msg}")

    def set_scanning(self, scanning: bool) -> None:
        self._btn_refresh.setEnabled(not scanning)
        self._btn_refresh.setText("Scanning…" if scanning else "⟳ Refresh")

    # ── Logger slot ────────────────────────────────────────────
    def _append_log(self, level: int, msg: str) -> None:
        color_map = {
            logging.DEBUG:    "#707070",
            logging.INFO:     "#27ae60",
            logging.WARNING:  "#e67e22",
            logging.ERROR:    "#e74c3c",
            logging.CRITICAL: "#ff4444",
        }
        color = color_map.get(level, "#a0a0a0")
        cur = self.log_view.textCursor()
        cur.movePosition(QTextCursor.End)
        self.log_view.setTextCursor(cur)
        self.log_view.setTextColor(QColor(color))
        self.log_view.insertPlainText(msg + "\n")
        self.log_view.ensureCursorVisible()

    # ── Style helpers ──────────────────────────────────────────
    def _style_btn_connect(self, connected: bool) -> None:
        if connected:
            self._btn_connect.setStyleSheet(
                "QPushButton{background:#c0392b;color:white;font-weight:bold;"
                "border-radius:4px;padding:6px;}"
                "QPushButton:hover{background:#e74c3c;}"
            )
        else:
            self._btn_connect.setStyleSheet(
                "QPushButton{background:#27ae60;color:white;font-weight:bold;"
                "border-radius:4px;padding:6px;}"
                "QPushButton:hover{background:#2ecc71;}"
            )
