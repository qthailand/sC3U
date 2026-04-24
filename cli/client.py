"""
cli/client.py
──────────────
Command-line client สำหรับ Motion Controller
ใช้งาน SerialManager โดยตรง — ไม่มี Qt

Usage:
    python -m cli.client
    python -m cli.client --port COM3 --baudrate 9600
    python -m cli.client --help
"""

import argparse
import logging
import sys
from typing import Optional

from SC3U import SerialManager

# ── Logging setup ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.WARNING,
    format="[%(levelname)s] %(name)s: %(message)s",
)
_log = logging.getLogger("cli")

# ── Color helpers (ANSI) ───────────────────────────────────────
_GREEN  = "\033[92m"
_YELLOW = "\033[93m"
_RED    = "\033[91m"
_CYAN   = "\033[96m"
_RESET  = "\033[0m"
_BOLD   = "\033[1m"

def _ok(msg):    print(f"{_GREEN}✔ {msg}{_RESET}")
def _err(msg):   print(f"{_RED}✘ {msg}{_RESET}")
def _info(msg):  print(f"{_CYAN}{msg}{_RESET}")
def _warn(msg):  print(f"{_YELLOW}⚠ {msg}{_RESET}")


HELP_TEXT = f"""{_BOLD}Motion Controller CLI{_RESET}
─────────────────────────────────────────────────
{_CYAN}Connection{_RESET}
  ports                         — แสดง CH340/CH341 ports ที่พบ
  connect [PORT] [BAUD]         — เชื่อมต่อ (default: settings.json)
  disconnect                    — ตัดการเชื่อมต่อ
  status                        — แสดงสถานะปัจจุบัน
  check                         — ส่ง ?R ตรวจ controller

{_CYAN}Speed{_RESET}
  speed                         — อ่านความเร็วปัจจุบัน (controller value)
  set-speed <mm/s>              — ตั้งความเร็ว (mm/s)

{_CYAN}Position{_RESET}
  pos                           — อ่านตำแหน่งทุกแกน
  pos <AXIS>                    — อ่านตำแหน่งแกนเดียว (X/Y/Z/R/T1/T2)

{_CYAN}Motion{_RESET}
  move <AXIS> <μm> [+/-]        — เคลื่อนที่ μm (default +)
  move-to <AXIS> <pulses>       — เคลื่อนที่ไปตำแหน่ง pulse target
  home <AXIS> [return]          — Home แกน (return=กลับหลัง home)
  home-all                      — Home ทุกแกน
  home-status                   — ตรวจสถานะ home
  stop                          — หยุดฉุกเฉิน

{_CYAN}Config{_RESET}
  config                        — แสดง config ปัจจุบัน
  save                          — บันทึก config ลง settings.json

{_CYAN}Other{_RESET}
  debug                         — เปิด/ปิด debug logging
  help                          — แสดงคำสั่งทั้งหมด
  exit / quit                   — ออก
─────────────────────────────────────────────────"""


class MotionCLI:
    def __init__(self, port: Optional[str] = None, baudrate: Optional[int] = None):
        self._ctrl = SerialManager()
        if port:
            self._ctrl.reconfigure({"port": port})
        if baudrate:
            self._ctrl.reconfigure({"baudrate": baudrate})
        self._debug_on = False

    # ─────────────────────────────────────────
    # REPL
    # ─────────────────────────────────────────
    def run(self) -> None:
        _info("Motion Controller CLI  (type 'help' for commands)")
        _info(f"Config: {self._ctrl.config}")
        print()

        while True:
            try:
                raw = input(f"{_BOLD}ctrl>{_RESET} ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                self._cmd_disconnect()
                break

            if not raw:
                continue

            parts = raw.split()
            cmd   = parts[0].lower()
            args  = parts[1:]

            try:
                self._dispatch(cmd, args)
            except ConnectionError as e:
                _err(f"Not connected: {e}")
            except ValueError as e:
                _err(f"Invalid value: {e}")
            except RuntimeError as e:
                _err(str(e))
            except Exception as e:
                _err(f"Error: {e}")
                _log.exception("Unhandled error in command %r", cmd)

    def _dispatch(self, cmd: str, args: list[str]) -> None:
        match cmd:
            # Connection
            case "ports":          self._cmd_ports()
            case "connect":        self._cmd_connect(args)
            case "disconnect":     self._cmd_disconnect()
            case "status":         self._cmd_status()
            case "check":          self._cmd_check()
            # Speed
            case "speed":          self._cmd_speed()
            case "set-speed":      self._cmd_set_speed(args)
            # Position
            case "pos":            self._cmd_pos(args)
            # Motion
            case "move":           self._cmd_move(args)
            case "move-to":        self._cmd_move_to(args)
            case "home":           self._cmd_home(args)
            case "home-all":       self._cmd_home_all()
            case "home-status":    self._cmd_home_status()
            case "stop":           self._cmd_stop()
            # Config
            case "config":         self._cmd_config()
            case "save":           self._cmd_save()
            # Other
            case "debug":          self._cmd_toggle_debug()
            case "help":           print(HELP_TEXT)
            case "exit" | "quit":  self._cmd_disconnect(); sys.exit(0)
            case _:
                _warn(f"Unknown command {cmd!r}  (type 'help')")

    # ─────────────────────────────────────────
    # Commands
    # ─────────────────────────────────────────
    def _cmd_ports(self):
        ports = SerialManager.scan_ports()
        if not ports:
            _warn("No CH340/CH341 ports found")
            return
        for p in ports:
            _ok(f"{p['device']:10}  {p['description']}")

    def _cmd_connect(self, args: list[str]):
        if self._ctrl.is_connected:
            _warn("Already connected. Disconnect first.")
            return
        if len(args) >= 1:
            self._ctrl.reconfigure({"port": args[0]})
        if len(args) >= 2:
            self._ctrl.reconfigure({"baudrate": args[1]})
        self._ctrl.connect()
        _ok(f"Connected to {self._ctrl.port} @ {self._ctrl.baudrate} baud")

    def _cmd_disconnect(self):
        if self._ctrl.is_connected:
            self._ctrl.disconnect()
            _ok("Disconnected")

    def _cmd_status(self):
        if self._ctrl.is_connected:
            _ok(f"Connected  |  {self._ctrl.port} @ {self._ctrl.baudrate} baud")
        else:
            _warn("Disconnected")

    def _cmd_check(self):
        ok = self._ctrl.check_connection()
        if ok:
            _ok("Controller responded OK")
        else:
            _err("Controller did not respond")

    def _cmd_speed(self):
        v    = self._ctrl.get_speed()
        mm_s = self._ctrl.stage.actual_speed_mm_s(v)
        _info(f"Speed: value={v}  ({mm_s:.3f} mm/s)")

    def _cmd_set_speed(self, args: list[str]):
        if not args:
            _err("Usage: set-speed <mm/s>")
            return
        mm_s = float(args[0])
        v    = self._ctrl.stage.speed_value_for_mm_s(mm_s)
        if not 0 <= v <= 255:
            _err(f"Calculated value {v} out of range 0-255")
            return
        ok = self._ctrl.set_speed(v)
        if ok:
            _ok(f"Speed set to {mm_s:.3f} mm/s  (value={v})")
        else:
            _err("Controller did not acknowledge")

    def _cmd_pos(self, args: list[str]):
        if args:
            axis = args[0].upper()
            pos  = self._ctrl.get_position(axis)
            um   = self._ctrl.stage.actual_displacement_um(abs(pos))
            sign = "-" if pos < 0 else "+"
            _info(f"{axis}: {pos:+d} pulses  ({sign}{um:.1f} μm)")
        else:
            positions = self._ctrl.get_all_positions()
            for axis, pos in positions.items():
                um   = self._ctrl.stage.actual_displacement_um(abs(pos))
                sign = "-" if pos < 0 else "+"
                _info(f"  {axis:3}: {pos:+8d} pulses  ({sign}{um:.1f} μm)")

    def _cmd_move(self, args: list[str]):
        # move <AXIS> <μm> [+/-]
        if len(args) < 2:
            _err("Usage: move <AXIS> <μm> [+/-]")
            return
        axis    = args[0].upper()
        um      = float(args[1])
        direction = args[2] if len(args) >= 3 else "+"
        pulses  = self._ctrl.stage.pulse_number_for_um(um)
        if direction == "-":
            pulses = -pulses
        if pulses == 0:
            _warn("Calculated pulse count is 0")
            return
        ok = self._ctrl.move(axis, pulses)
        if ok:
            _ok(f"Move {axis} {direction}{um} μm  ({pulses:+d} pulses)")
        else:
            _err("Controller did not acknowledge")

    def _cmd_move_to(self, args: list[str]):
        if len(args) < 2:
            _err("Usage: move-to <AXIS> <pulse_target>")
            return
        axis   = args[0].upper()
        target = int(args[1])
        ok     = self._ctrl.move_to(axis, target)
        if ok:
            _ok(f"Move {axis} to {target} pulses")
        else:
            _err("Controller did not acknowledge")

    def _cmd_home(self, args: list[str]):
        if not args:
            _err("Usage: home <AXIS> [return]")
            return
        axis         = args[0].upper()
        return_after = len(args) >= 2 and args[1].lower() == "return"
        ok = self._ctrl.home(axis, return_after)
        if ok:
            _ok(f"Home {axis}  (return_after={return_after})")
        else:
            _err("Controller did not acknowledge")

    def _cmd_home_all(self):
        results = self._ctrl.home_all()
        for axis, ok in results.items():
            ((_ok if ok else _err))(f"Home {axis}: {'OK' if ok else 'FAIL'}")

    def _cmd_home_status(self):
        status = self._ctrl.get_home_status()
        for axis, homed in status.items():
            mark = _GREEN + "✔" + _RESET if homed else _YELLOW + "–" + _RESET
            print(f"  {axis:3}: {mark}  {'homed' if homed else 'not homed'}")

    def _cmd_stop(self):
        ok = self._ctrl.stop()
        if ok:
            _ok("STOP sent")
        else:
            _err("Controller did not acknowledge STOP")

    def _cmd_config(self):
        cfg = self._ctrl.config
        _info(f"Port:       {cfg.port or '(not set)'}")
        _info(f"Baudrate:   {cfg.baudrate}")
        _info(f"Bytesize:   {cfg.bytesize}")
        _info(f"Parity:     {cfg.parity}")
        _info(f"Stopbits:   {cfg.stopbits}")
        _info(f"Timeout:    {cfg.timeout} s")
        _info(f"Stage:")
        _info(f"  pitch:       {cfg.stage.pitch} mm")
        _info(f"  subdivision: {cfg.stage.subdivision}")
        _info(f"  microstep:   {cfg.stage.microstep}")
        _info(f"  pulse/mm:    {cfg.stage.pulse_equivalent_mm():.6f}")

    def _cmd_save(self):
        self._ctrl.save_config()
        _ok(f"Config saved to {self._ctrl.config.default_path()}")

    def _cmd_toggle_debug(self):
        self._debug_on = not self._debug_on
        level = logging.DEBUG if self._debug_on else logging.WARNING
        logging.getLogger("lib").setLevel(level)
        logging.getLogger("cli").setLevel(level)
        state = "ON" if self._debug_on else "OFF"
        _info(f"Debug logging: {state}")


# ── Entry point ───────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Motion Controller CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--port",     "-p", help="Serial port (e.g. COM3)")
    parser.add_argument("--baudrate", "-b", type=int, help="Baudrate (default from settings.json)")
    parser.add_argument("--debug",    "-d", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger("lib").setLevel(logging.DEBUG)
        logging.getLogger("cli").setLevel(logging.DEBUG)

    cli = MotionCLI(port=args.port, baudrate=args.baudrate)
    cli.run()


if __name__ == "__main__":
    main()
