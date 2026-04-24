import time
import SC3U.serialmanager

if __name__ == "__main__":
    # ── Quick test for SerialManager (without GUI) ───────────────────────────────
    with SC3U.serialmanager.SerialManager() as manager:
        print(manager.config)
        print(manager.is_connected)
        speed_ms = manager.get_speed_mm_s()
        manager.move_mm('X', 20)
        pos_ms = manager.get_position_mm('X')
        print(f"New Position: {pos_ms} mm")
        manager.home('X')
        manager.move_mm('Y', 20)
        pos_y = manager.get_position_mm('Y')
        print(f"Y Position: {pos_y} mm")
        manager.home('Y')
