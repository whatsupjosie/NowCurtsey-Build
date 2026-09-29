from __future__ import annotations

import asyncio
import unittest

from pubcast_twin_engine_service import CameraTransition, TwinEngineMode, TwinEngineService


class DummyBridge:
    def __init__(self, connected=True):
        self.is_connected = connected
        self.commands = []

    def connect(self):
        return self.is_connected

    async def send_command(self, command, payload):
        self.commands.append((command, payload))


class DummyRenderer:
    async def health(self):
        return {"ok": True}


class TwinEngineServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_ready(self):
        service = TwinEngineService(bridge=DummyBridge(), renderer=DummyRenderer())
        health = await service.startup()
        self.assertEqual(health["mode"], TwinEngineMode.READY.value)
        self.assertEqual(health["camera_count"], 4)

    async def test_activate_camera_sends_command(self):
        bridge = DummyBridge()
        service = TwinEngineService(bridge=bridge, renderer=DummyRenderer())
        await service.startup()
        payload = await service.activate_camera("closeup", transition=CameraTransition.DISSOLVE)
        self.assertTrue(payload["active"])
        self.assertEqual(payload["transition"], CameraTransition.DISSOLVE.value)
        self.assertEqual(bridge.commands[-1][0], "ACTIVATE_CAMERA")

    async def test_disconnected_mode_is_honest(self):
        service = TwinEngineService()
        health = await service.startup()
        self.assertEqual(health["mode"], TwinEngineMode.DISCONNECTED.value)
        self.assertFalse(health["bridge_connected"])
        self.assertTrue(any("Bridge unavailable" in note for note in health["startup_notes"]))


if __name__ == "__main__":
    unittest.main()
