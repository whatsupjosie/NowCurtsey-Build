"""
UnifiedBridge — Python side of the PubCast V3 C++ shared-memory bridge.

All offsets verified against bridge.h (V3.9-BULLETPROOF-DUAL-VOXEL-DX12)
and confirmed against the reference EngineBridgeClient implementation.

SharedMemoryHeader layout (alignas(64) struct):

  offset  0   uint32_t  magic              0x50554243 "PUBC"
  offset  4   uint32_t  version            300
  offset  8   float     engine_stress      Pete load 0.0–1.0
  offset 12   uint32_t  backlog            pending command count
  offset 16   uint64_t  engine_pulse       C++ heartbeat (increments every frame)
  offset 24   uint64_t  artist_pulse       Python heartbeat (we write here)
  offset 32   double    last_frame_delta   clamped frame delta from C++
  offset 40   uint32_t  head              C++ advances — Python must NOT write
  offset 44   uint32_t  tail              Python advances
  offset 48   uint8_t   padding[16]
  offset 64   CommandSlot queue[1024]     32 bytes per slot, 1024-slot ring

CommandSlot (32 bytes, little-endian):
  +0   uint32_t  type      1=SET_CAMERA 2=UPDATE_ENTITY 3=SET_VOXEL 4=TRIGGER_RIPPLE 99=SHUTDOWN
  +4   float     pos.x
  +8   float     pos.y
  +12  float     pos.z
  +16  float     rot.x
  +20  float     rot.y
  +24  float     rot.z
  +28  uint32_t  target_id
"""

import mmap
import struct
import time

# ── Protocol constants (must match bridge.h) ─────────────────────────────────
BRIDGE_NAME     = "Local\\PubCast_V3_Bridge"
BRIDGE_MAGIC    = 0x50554243
BRIDGE_VERSION  = 300
BRIDGE_SIZE     = 1024 * 1024 * 8   # 8MB — matches C++ exactly

# ── Header offsets ────────────────────────────────────────────────────────────
MAGIC_OFF         = 0
VERSION_OFF       = 4
STRESS_OFF        = 8
BACKLOG_OFF       = 12
ENGINE_PULSE_OFF  = 16
ARTIST_PULSE_OFF  = 24
DELTA_OFF         = 32
HEAD_OFF          = 40    # C++ owns this — never write it
TAIL_OFF          = 44    # Python owns this

# ── Queue constants ───────────────────────────────────────────────────────────
QUEUE_OFFSET  = 64
SLOT_SIZE     = 32
QUEUE_DEPTH   = 1024

# ── Command types ─────────────────────────────────────────────────────────────
CMD_NONE          = 0
CMD_SET_CAMERA    = 1
CMD_UPDATE_ENTITY = 2
CMD_SET_VOXEL     = 3
CMD_TRIGGER_RIPPLE = 4
CMD_SHUTDOWN      = 99

CMD_FMT = "<I fff fff I"   # little-endian, 32 bytes


class UnifiedBridge:
    """
    Python controller for the PubCast V3 shared-memory bridge.
    Retries connection until the C++ engine is up and magic is valid.
    """

    def __init__(self):
        self.shm = None
        self._connect()

    def _connect(self):
        print(f"Connecting to {BRIDGE_NAME}...")
        while self.shm is None:
            try:
                shm = mmap.mmap(
                    -1, BRIDGE_SIZE,
                    tagname=BRIDGE_NAME,
                    access=mmap.ACCESS_WRITE,
                )
                magic, version = struct.unpack_from("<II", shm, MAGIC_OFF)
                if magic != BRIDGE_MAGIC or version != BRIDGE_VERSION:
                    print(
                        f"  Waiting for valid engine signature… "
                        f"(magic={hex(magic)} version={version})"
                    )
                    shm.close()
                    time.sleep(1.0)
                else:
                    self.shm = shm
                    print("  Connected — bridge magic and version verified.")
            except Exception as exc:
                print(f"  Not ready yet ({exc}), retrying…")
                time.sleep(1.0)

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_metrics(self) -> dict:
        """Read Pete's live telemetry."""
        stress, backlog, engine_pulse = struct.unpack_from("<fIQ", self.shm, STRESS_OFF)
        delta = struct.unpack_from("<d", self.shm, DELTA_OFF)[0]
        return {
            "stress":        stress,
            "backlog":       backlog,
            "engine_pulse":  engine_pulse,
            "frame_delta":   delta,
        }

    # ── Write ─────────────────────────────────────────────────────────────────

    def ping(self, pulse: int):
        """Increment our heartbeat so C++ knows Python is alive."""
        struct.pack_into("<Q", self.shm, ARTIST_PULSE_OFF, pulse)

    def push_command(
        self,
        cmd_type: int,
        x: float = 0.0, y: float = 0.0, z: float = 0.0,
        rx: float = 0.0, ry: float = 0.0, rz: float = 0.0,
        target_id: int = 0,
    ) -> bool:
        """
        Write one CommandSlot into the ring buffer and advance tail.
        Returns False if the queue is full (back-pressure from Pete).
        """
        head, tail = struct.unpack_from("<II", self.shm, HEAD_OFF)

        # Sentinel full-check (matches reference implementation)
        if (tail + 1) % QUEUE_DEPTH == head % QUEUE_DEPTH:
            return False  # queue full — caller should back off

        slot_index = tail % QUEUE_DEPTH
        offset = QUEUE_OFFSET + slot_index * SLOT_SIZE
        payload = struct.pack(CMD_FMT, cmd_type, x, y, z, rx, ry, rz, target_id)
        self.shm[offset:offset + SLOT_SIZE] = payload

        # Advance tail — head belongs to C++, never touch it
        struct.pack_into("<I", self.shm, TAIL_OFF, tail + 1)
        return True

    # ── Convenience wrappers ──────────────────────────────────────────────────

    def send_camera(self, pos, rot) -> bool:
        return self.push_command(CMD_SET_CAMERA, *pos, *rot)

    def set_voxel(self, x: int, y: int, z: int, material_id: int) -> bool:
        return self.push_command(CMD_SET_VOXEL, float(x), float(y), float(z),
                                 target_id=material_id)

    def trigger_ripple(self, x: float, y: float, z: float) -> bool:
        return self.push_command(CMD_TRIGGER_RIPPLE, x, y, z)

    def shutdown_engine(self) -> bool:
        return self.push_command(CMD_SHUTDOWN)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self):
        if self.shm:
            self.shm.close()
            self.shm = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


if __name__ == "__main__":
    with UnifiedBridge() as bridge:
        # Place a 3-voxel column
        for vy in range(3):
            bridge.set_voxel(10, vy, 10, material_id=1)

        # Stream 120 camera frames
        pulse = 0
        for frame in range(120):
            pulse += 1
            bridge.ping(pulse)
            ok = bridge.send_camera(
                pos=(frame * 0.2, 5.0, -10.0),
                rot=(0.0, 0.0, 0.0),
            )
            m = bridge.get_metrics()
            print(
                f"Frame {frame:3d} | "
                f"engine_pulse={m['engine_pulse']:6d} | "
                f"stress={m['stress']:.1%} | "
                f"backlog={m['backlog']:3d} | "
                f"queued={ok}"
            )
            time.sleep(0.016)

        # Clean shutdown
        bridge.shutdown_engine()
        print("Shutdown sent.")
