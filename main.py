"""PREDICTABLE - a chase game where the enemy learns how you move.

Run on desktop:   python main.py
Build for web:    pygbag .     (see README.md)

The main loop is `async` so the same code runs natively and in the browser
(pygbag compiles it to WebAssembly and needs to yield to the browser each frame).
"""

import asyncio

# pygbag scans main.py for imports to decide which WebAssembly packages to
# load, so pygame must be imported here even though game/ is what uses it.
import pygame  # noqa: F401

from game.app import App


async def main():
    app = App()
    while app.running:
        app.frame()
        await asyncio.sleep(0)
    app.quit()


asyncio.run(main())
