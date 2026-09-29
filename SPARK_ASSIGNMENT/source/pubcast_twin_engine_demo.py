from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from pubcast_twin_engine_service import TwinEngineService, CameraTransition


class DummyBridge:
    def __init__(self) -> None:
        self.is_connected = True
        self.commands = []

    async def send_command(self, command, payload):
        self.commands.append((command, payload))


class DummyRenderer:
    async def health(self):
        return {"ok": True, "path": "dummy"}


async def main() -> None:
    bridge = DummyBridge()
    renderer = DummyRenderer()
    service = TwinEngineService(bridge=bridge, renderer=renderer)
    print(json.dumps(await service.startup(), indent=2))
    print(json.dumps(await service.set_scene("professional_studio"), indent=2))
    print(json.dumps(await service.activate_camera("closeup", transition=CameraTransition.DISSOLVE), indent=2))
    print(json.dumps(await service.update_camera_pose("closeup", position={"x": 1.25, "y": 1.8}), indent=2))
    await service.ingest_telemetry({"renderer_state": "ready"})
    print(json.dumps(service.health(), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
