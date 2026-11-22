"""Save the best score and run history.

Desktop: a small JSON file next to the game.
Browser (pygbag / WebAssembly): the browser's localStorage.
Saving must never crash the game, so every operation is wrapped.
"""

import json
import os
import sys

KEY = "predictable_save_v1"
DESKTOP_FILE = os.path.join(os.path.expanduser("~"), ".predictable_save.json")
DEFAULT = {"best": 0, "runs": [], "types": []}


def _web_storage():
    if sys.platform != "emscripten":
        return None
    try:
        import platform  # pygbag replaces this module with its browser bridge
        return platform.window.localStorage
    except Exception:
        return None


def load() -> dict:
    try:
        store = _web_storage()
        if store is not None:
            raw = store.getItem(KEY)
        elif os.path.exists(DESKTOP_FILE):
            with open(DESKTOP_FILE, "r", encoding="utf-8") as fh:
                raw = fh.read()
        else:
            raw = None
        data = json.loads(raw) if raw else {}
        return {"best": int(data.get("best", 0)), "runs": list(data.get("runs", []))[-50:],
                "types": [t for t in data.get("types", []) if isinstance(t, str)]}
    except Exception:
        return {"best": 0, "runs": [], "types": []}


def save(data: dict):
    try:
        raw = json.dumps({"best": data.get("best", 0), "runs": data.get("runs", [])[-50:],
                          "types": data.get("types", [])})
        store = _web_storage()
        if store is not None:
            store.setItem(KEY, raw)
        else:
            with open(DESKTOP_FILE, "w", encoding="utf-8") as fh:
                fh.write(raw)
    except Exception:
        pass
