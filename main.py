import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "py_modules"))

import decky  # noqa: E402


class Plugin:
    async def _main(self):
        decky.logger.info("Mudfish VPN plugin loaded")

    async def _unload(self):
        decky.logger.info("Mudfish VPN plugin unloaded")
