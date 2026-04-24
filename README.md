# sC3U — Serial Motion Controller Utility

โปรแกรมสำหรับควบคุม Motion Controller ผ่าน Serial Port (CH340/CH341)  
รองรับทั้งโหมด **GUI (PyQt5)** และ **Command-Line Interface (CLI)** รวมทั้ง **สามารถใช้ SC3U ได้โดยตรง**

---

## สารบัญ

- [ความต้องการของระบบ](#ความต้องการของระบบ)
- [การติดตั้ง](#การติดตั้ง)
- [การใช้งาน](#การใช้งาน)
  - [GUI Mode](#gui-mode)
  - [CLI Mode](#cli-mode)
- [คำสั่ง CLI](#คำสั่ง-cli)
- [การตั้งค่า (settings.json)](#การตั้งค่า-settingsjson)
- [โครงสร้างโปรเจกต์](#โครงสร้างโปรเจกต์)
- [สถาปัตยกรรม Thread](#สถาปัตยกรรม-thread)
- [Error Codes](#error-codes)

---

## ความต้องการของระบบ

- Python 3.10+
- รองรับอุปกรณ์ **Motion Controllers** ของ **OPTIC FOCUS** เชื่อมต่อผ่าน CH340 หรือ CH341 USB-to-Serial 

---

## การติดตั้ง

```bash
pip install -r requirements.txt
```

dependencies:
- `pyserial >= 3.5`
- `PyQt5 >= 5.15` **(ต้องการเฉพาะ GUI mode)**

---

## การใช้งาน

### GUI Mode

เปิดหน้าต่างควบคุมแบบ Graphical:

```bash
python main.py
# หรือ
python -m sC3U
```

**ฟีเจอร์ GUI:**
- เลือก Serial Port และตั้งค่า Baudrate
- Auto-detect CH340/CH341 ports (ปุ่ม ⟳ Refresh)
- ควบคุมแกน X / Y / Z (Move, Home, Position inquiry)
- ตั้งค่าความเร็วหน่วย mm/s
- Terminal แสดงข้อมูล RX/TX แบบ real-time พร้อม timestamp
- รองรับการส่งข้อมูลแบบ HEX และ CR+LF
- Logger panel พร้อมตัวกรอง log level
- Dark theme

### CLI Mode

เปิด interactive REPL สำหรับควบคุมผ่าน command line:

```bash
python -m cli.client
python -m cli.client --port COM3
python -m cli.client --port COM3 --baudrate 9600
python -m cli.client --debug
```

| Option | Short | คำอธิบาย |
|--------|-------|----------|
| `--port` | `-p` | Serial port เช่น `COM3`, `/dev/ttyUSB0` |
| `--baudrate` | `-b` | Baudrate (ค่า default อ่านจาก settings.json) |
| `--debug` | `-d` | เปิด debug logging |

---

## คำสั่ง CLI

หลังเปิดโปรแกรมจะแสดง prompt `ctrl>` สามารถพิมพ์คำสั่งได้ดังนี้:

### Connection

| คำสั่ง | คำอธิบาย |
|--------|----------|
| `ports` | แสดง CH340/CH341 ports ที่พบในระบบ |
| `connect [PORT] [BAUD]` | เชื่อมต่อ (default: ค่าจาก settings.json) |
| `disconnect` | ตัดการเชื่อมต่อ |
| `status` | แสดงสถานะการเชื่อมต่อปัจจุบัน |
| `check` | ส่ง `?R` เพื่อตรวจสอบ controller |

### Speed

| คำสั่ง | คำอธิบาย |
|--------|----------|
| `speed` | อ่านความเร็วปัจจุบัน (controller value + mm/s) |
| `set-speed <mm/s>` | ตั้งความเร็วเป็น mm/s |

### Position

| คำสั่ง | คำอธิบาย |
|--------|----------|
| `pos` | อ่านตำแหน่งทุกแกน |
| `pos <AXIS>` | อ่านตำแหน่งแกนเดียว (X/Y/Z/R/T1/T2) |

### Motion

| คำสั่ง | คำอธิบาย |
|--------|----------|
| `move <AXIS> <μm> [+/-]` | เคลื่อนที่ระยะ μm (default ทิศทาง +) |
| `move-to <AXIS> <pulses>` | เคลื่อนที่ไปตำแหน่ง pulse target |
| `home <AXIS> [return]` | Home แกน (เพิ่ม `return` เพื่อกลับหลัง home) |
| `home-all` | Home ทุกแกน |
| `home-status` | ตรวจสถานะ home ของทุกแกน |
| `stop` | หยุดฉุกเฉิน |

### Config

| คำสั่ง | คำอธิบาย |
|--------|----------|
| `config` | แสดง configuration ปัจจุบัน |
| `save` | บันทึก config ลง settings.json |

### Other

| คำสั่ง | คำอธิบาย |
|--------|----------|
| `debug` | Toggle debug logging on/off |
| `help` | แสดงคำสั่งทั้งหมด |
| `exit` / `quit` | ออกจากโปรแกรม |

**ตัวอย่างการใช้งาน:**
```
ctrl> connect COM6 9600
ctrl> pos
ctrl> move X 500 +
ctrl> set-speed 1.5
ctrl> home X return
ctrl> stop
ctrl> disconnect
```

---

## การตั้งค่า (settings.json)

ไฟล์ `settings.json` เก็บค่า default ของ Serial Port และ Stage parameters  
โปรแกรมจะสร้างไฟล์นี้อัตโนมัติหากยังไม่มี

```json
{
  "port": "COM6",
  "baudrate": 9600,
  "bytesize": 8,
  "parity": "N",
  "stopbits": 1.0,
  "timeout": 0.2,
  "stage": {
    "pitch": 0.75,
    "subdivision": 1,
    "microstep": 8,
    "stepper_angle": 1.8
  }
}
```

| Field | คำอธิบาย |
|-------|----------|
| `port` | Serial port เช่น `COM6`, `/dev/ttyUSB0` |
| `baudrate` | Baudrate (ค่าปกติ 9600) |
| `bytesize` | Data bits (5/6/7/8) |
| `parity` | Parity: `N`=None, `E`=Even, `O`=Odd, `M`=Mark, `S`=Space |
| `stopbits` | Stop bits: 1, 1.5, หรือ 2 |
| `timeout` | Serial read timeout (วินาที) |
| `stage.pitch` | Lead screw pitch (mm/rev) |
| `stage.subdivision` | Subdivision ของ driver (1 ถึง microstep) |
| `stage.microstep` | Microstep สูงสุดของ driver |
| `stage.stepper_angle` | Step angle ของ stepper motor (องศา) |

> **หมายเหตุ:** Pulse equivalent = `pitch / (360 / stepper_angle × subdivision)` mm/pulse

---

## โครงสร้างโปรเจกต์

```
sC3U/
├── main.py                  # Entry point สำหรับ GUI mode
├── __main__.py              # Entry point สำหรับ python -m sC3U (CLI mode)
├── settings.json            # Serial port & stage configuration
├── requirements.txt
│
├── SC3U/                    # Core library (ไม่มี Qt dependency)
│   ├── serialmanager.py     # SerialManager — API หลักสำหรับ motion controller
│   └── serial_config.py     # SerialConfig + StageConfig dataclasses
│
├── core/
│   └── serial_controller.py # Qt bridge: SerialController (QObject, signals/slots)
│
├── ui/
│   └── main_window.py       # MainWindow — PyQt5 GUI (pure UI, ไม่มี serial logic)
│
└── cli/
    └── client.py            # MotionCLI — interactive REPL สำหรับ command line
```

---

## สถาปัตยกรรม Thread

```
Main Thread (Qt GUI)
 ├── MainWindow         — pure UI, ส่ง/รับ signals
 └── SerialController   — business logic bridge
       ├── PortScannerThread  — one-shot scan comports
       ├── ReaderThread       — poll RX ต่อเนื่อง → emit terminal_output
       └── WriterThread       — queue-based TX
```

- **MainWindow** และ **SerialController** อยู่บน main thread (Qt GUI thread)
- **ReaderThread** อ่านข้อมูลจาก serial port ต่อเนื่อง และ emit signal กลับไปที่ UI
- **WriterThread** รับ bytes จาก TX queue แล้วเขียนลง serial port
- **PortScannerThread** สแกนหา COM port แบบ non-blocking

---

## Error Codes

| Code | ความหมาย |
|------|----------|
| `ERR1` | Communication error / invalid command / communication timeout |
| `ERR2` | Communication not established |
| `ERR3` | Invalid command |
| `ERR4` | Stop command received |
| `ERR5` | Limit switch triggered |
