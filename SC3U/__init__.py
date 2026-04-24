"""
SC3U/
────
Motion Controller Serial Library — ใช้งานเหมือน DLL
import จากที่นี่เพียงจุดเดียว ไม่ว่าจะเป็น GUI / CLI / script

Usage:
    from SC3U import SerialManager
    with SerialManager() as ctrl:
        ctrl.move("X", 5000)
"""

from SC3U.serial_config import SerialConfig, StageConfig
from SC3U.serialmanager import SerialManager

__all__ = ["SerialManager", "SerialConfig", "StageConfig"]
