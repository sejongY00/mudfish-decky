import asyncio
import logging
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "py_modules"))

import decky  # noqa: E402

from mudfish_decky import system  # noqa: E402
from mudfish_decky.client import MudfishClient  # noqa: E402
from mudfish_decky.controller import Controller  # noqa: E402
from mudfish_decky.relay import LoginRelay  # noqa: E402
from mudfish_decky.store import Store  # noqa: E402

RESUME_POLL_SECONDS = 2
LOGIN_RELAY_SECONDS = 300


class Plugin:
    controller = None

    def _get_controller(self) -> Controller:
        if self.controller is None:
            installed = system.find_mudfish()
            base = system.api_base(installed[1]) if installed else system.DEFAULT_API
            store = Store(os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json"))
            target = urllib.parse.urlsplit(base)
            self.controller = Controller(
                MudfishClient(base), system, store,
                relay_factory=lambda: LoginRelay(target=(target.hostname, target.port or 80), ttl=LOGIN_RELAY_SECONDS),
            )
        return self.controller

    async def start_login(self) -> dict:
        return await asyncio.to_thread(self._get_controller().start_login)

    async def stop_login(self) -> dict:
        return await asyncio.to_thread(self._get_controller().stop_login)

    async def get_state(self) -> dict:
        return await asyncio.to_thread(self._get_controller().state)

    async def connect(self) -> dict:
        return await asyncio.to_thread(self._get_controller().connect)

    async def disconnect(self) -> dict:
        return await asyncio.to_thread(self._get_controller().disconnect)

    async def set_node(self, choice: str) -> dict:
        return await asyncio.to_thread(self._get_controller().set_node, str(choice))

    async def list_nodes(self) -> list:
        return await asyncio.to_thread(self._get_controller().nodes)

    async def _main(self):
        log = logging.getLogger("mudfish_decky")
        log.setLevel(logging.INFO)
        for handler in decky.logger.handlers:
            log.addHandler(handler)
        controller = self._get_controller()
        # Bring up the idle launcher and sign in so nodes are listed. Never starts the tunnel.
        await asyncio.to_thread(controller.prepare)
        decky.logger.info("Mudfish VPN plugin loaded")
        # Watch for sleep/resume even while the panel is closed; a resumed tunnel is turned off.
        while True:
            try:
                await asyncio.to_thread(controller.check_resume, system.sleep_offset())
            except Exception as e:
                decky.logger.warning("resume check failed: %s", e)
            await asyncio.sleep(RESUME_POLL_SECONDS)

    async def _unload(self):
        await asyncio.to_thread(self._get_controller().shutdown)
        decky.logger.info("Mudfish VPN plugin unloaded")
