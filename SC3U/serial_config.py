"""
lib/serial_config.py
─────────────────────
Dataclass เก็บค่า config ของ Serial Port และ StageConfig
เป็น pure data layer — ไม่มี Qt, ไม่มี side-effect
"""

from dataclasses import dataclass, field
import json
import serial
from pathlib import Path


@dataclass
class StageConfig:
    pitch:         float = 0.75
    subdivision:   int   = 2
    microstep:     int   = 8
    stepper_angle: float = 1.8

    def to_dict(self) -> dict:
        return {
            "pitch":         self.pitch,
            "subdivision":   self.subdivision,
            "microstep":     self.microstep,
            "stepper_angle": self.stepper_angle,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "StageConfig":
        return cls(
            pitch=float(raw.get("pitch", 0.75)),
            subdivision=int(raw.get("subdivision", 2)),
            microstep=int(raw.get("microstep", 8)),
            stepper_angle=float(raw.get("stepper_angle", 1.8)),
        )

    def pulse_equivalent_mm(self) -> float:
        """มิลลิเมตรต่อ 1 pulse
        = pitch / (full_steps_per_rev × subdivision)
        = pitch × stepper_angle / (360 × subdivision)
        subdivision ต้องอยู่ในช่วง 1 ถึง microstep (max)
        """
        if not (1 <= self.subdivision <= self.microstep):
            raise ValueError(
                f"subdivision={self.subdivision} ต้องอยู่ระหว่าง 1 ถึง microstep={self.microstep}"
            )
        full_steps = 360.0 / self.stepper_angle
        return self.pitch / (full_steps * self.subdivision)

    def pulse_number_for_mm(self, mm: float) -> int:
        return round(mm / self.pulse_equivalent_mm())

    def pulse_number_for_um(self, um: float) -> int:
        return self.pulse_number_for_mm(um * 0.001)

    def actual_displacement_um(self, pulses: int) -> float:
        return self.pulse_equivalent_mm() * pulses * 1000

    def actual_speed_mm_s(self, speed_value: int) -> float:
        """แปลง controller speed value (0-255) → mm/s"""
        return ((speed_value + 1) * 22000.0 * self.pulse_equivalent_mm()) / 720.0

    def speed_value_for_mm_s(self, mm_s: float) -> int:
        """แปลง mm/s → controller speed value (0-255)"""
        value = (mm_s * 720.0) / (22000.0 * self.pulse_equivalent_mm()) - 1.0
        return max(0, int(round(value)))


@dataclass
class SerialConfig:
    port:      str   = ""
    baudrate:  int   = 9600
    bytesize:  int   = serial.EIGHTBITS      # 5/6/7/8
    parity:    str   = serial.PARITY_NONE    # N/E/O/M/S
    stopbits:  float = serial.STOPBITS_ONE   # 1/1.5/2
    timeout:   float = 0.2                   # seconds (ต้องรอ motion controller)
    stage:     StageConfig = field(default_factory=StageConfig)

    PARITY_MAP: dict = field(default_factory=lambda: {
        "None":  serial.PARITY_NONE,
        "Even":  serial.PARITY_EVEN,
        "Odd":   serial.PARITY_ODD,
        "Mark":  serial.PARITY_MARK,
        "Space": serial.PARITY_SPACE,
    })

    STOPBITS_MAP: dict = field(default_factory=lambda: {
        "1":   serial.STOPBITS_ONE,
        "1.5": serial.STOPBITS_ONE_POINT_FIVE,
        "2":   serial.STOPBITS_TWO,
    })

    def __repr__(self) -> str:
        return (
            f"SerialConfig(port={self.port!r}, baud={self.baudrate}, "
            f"bits={self.bytesize}, parity={self.parity!r}, stop={self.stopbits})"
        )

    def to_dict(self) -> dict:
        return {
            "port":     self.port,
            "baudrate": self.baudrate,
            "bytesize": self.bytesize,
            "parity":   self.parity,
            "stopbits": self.stopbits,
            "timeout":  self.timeout,
            "stage":    self.stage.to_dict(),
        }

    @classmethod
    def default_path(cls) -> Path:
        """settings.json อยู่ที่ project root (parent ของ lib/)"""
        return Path(__file__).resolve().parent.parent / "settings.json"

    @classmethod
    def load(cls, path: str | Path | None = None, create_if_missing: bool = False) -> "SerialConfig":
        if path is None:
            path = cls.default_path()
        else:
            path = Path(path)

        if not path.exists():
            cfg = cls()
            if create_if_missing:
                cfg.save(path)
            return cfg

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            cfg = cls()
            if create_if_missing:
                cfg.save(path)
            return cfg

        kwargs: dict = {}
        for key, cast in [
            ("port",     str),
            ("baudrate", int),
            ("bytesize", int),
            ("parity",   str),
            ("stopbits", float),
            ("timeout",  float),
        ]:
            if key in raw:
                kwargs[key] = cast(raw[key])

        cfg = cls(**kwargs)
        if "stage" in raw and isinstance(raw["stage"], dict):
            cfg.stage = StageConfig.from_dict(raw["stage"])
        if create_if_missing:
            cfg.save(path)
        return cfg

    def save(self, path: str | Path | None = None) -> None:
        if path is None:
            path = self.default_path()
        else:
            path = Path(path)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
