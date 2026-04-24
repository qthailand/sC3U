# %%
"""

main.py
────────
Entry point — สร้าง QApplication, MainWindow, SerialController
แล้วเปิด event loop

โครงสร้าง Thread ทั้งหมด:
  ┌─────────────────────────────────────────────────────┐
  │  Main Thread (Qt GUI)                               │
  │   ├── MainWindow  (pure UI)                         │
  │   └── SerialController  (business logic)            │
  └──────────────────┬──────────────────────────────────┘
                     │ manages
     ┌───────────────┼────────────────┐
     ▼               ▼                ▼
  PortScannerThread  ReaderThread  WriterThread
  (one-shot scan)    (poll RX)     (queue TX)
"""

import sys

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QColor, QPalette

from ui.main_window import MainWindow
from core.serial_controller import SerialController


def _apply_dark_palette(app: QApplication) -> None:
    app.setStyle("Fusion")
    p = QPalette()
    p.setColor(QPalette.Window,          QColor(30, 30, 30))
    p.setColor(QPalette.WindowText,      QColor(212, 212, 212))
    p.setColor(QPalette.Base,            QColor(18, 18, 18))
    p.setColor(QPalette.AlternateBase,   QColor(45, 45, 45))
    p.setColor(QPalette.ToolTipBase,     QColor(0, 0, 0))
    p.setColor(QPalette.ToolTipText,     QColor(212, 212, 212))
    p.setColor(QPalette.Text,            QColor(212, 212, 212))
    p.setColor(QPalette.Button,          QColor(45, 45, 45))
    p.setColor(QPalette.ButtonText,      QColor(212, 212, 212))
    p.setColor(QPalette.BrightText,      QColor(255, 80, 80))
    p.setColor(QPalette.Highlight,       QColor(41, 128, 185))
    p.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    app.setPalette(p)


def main() -> int:
    app = QApplication(sys.argv)
    _apply_dark_palette(app)

    window = MainWindow()
    controller = SerialController()

    # ── Connect GUI events to core controller ───────────────────
    window.connect_requested.connect(controller.open)
    window.disconnect_requested.connect(controller.close)
    window.send_requested.connect(controller.send)
    window.refresh_requested.connect(controller.refresh)
    window.log_level_changed.connect(controller.set_log_level)

    # ── Connect core controller output to GUI ───────────────────
    controller.connected.connect(window.set_connected)
    controller.disconnected.connect(window.set_disconnected)
    controller.terminal_output.connect(window.append_terminal)
    controller.rx_updated.connect(window.update_rx)
    controller.tx_updated.connect(window.update_tx)
    controller.scanning_changed.connect(window.set_scanning)
    controller.ports_found.connect(window.populate_ports)
    controller.speed_value_changed.connect(window.set_speed_value)
    controller.stage_config_updated.connect(window.set_stage_config)

    # ── Trigger initial port scan ──────────────────────────────
    window.refresh_requested.emit()

    # ── Hook closeEvent → controller.shutdown() ────────────────
    original_close = window.closeEvent

    def _on_close(event):
        controller.shutdown()
        original_close(event)
    window.closeEvent = _on_close

    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
