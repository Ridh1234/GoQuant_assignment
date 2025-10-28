from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict


async def load_state(path: str) -> Dict[str, Any]:
    os.makedirs(path, exist_ok=True)
    file_path = os.path.join(path, "state.json")
    if not os.path.exists(file_path):
        return {"open_orders": {}, "recent_trades": {}}

    def _read():
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    return await asyncio.to_thread(_read)


async def save_state(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(path, exist_ok=True)
    file_path = os.path.join(path, "state.json")

    def _write():
        tmp = file_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, file_path)

    await asyncio.to_thread(_write)
