import json
import os
from loguru import logger


class StateManager:

    def __init__(self, filepath="state.json"):
        self.filepath = filepath

        # file exist nahi hai to create karo
        if not os.path.exists(self.filepath):
            self._save({})

    def _save(self, data: dict):
        with open(self.filepath, "w") as f:
            json.dump(data, f, indent=4)

    def load(self) -> dict:
        try:
            with open(self.filepath, "r") as f:
                return json.load(f)
        except:
            return {}

    def set_position(self, signal):
        data = {
            "in_position": True,
            "pair": signal.pair,
            "direction": signal.direction,
            "entry_price": signal.entry_price,
            "stop_loss": signal.stop_loss
        }

        self._save(data)
        logger.info("📌 State saved (position open)")

    def clear(self):
        self._save({})
        logger.info("🧹 State cleared")

    def in_position(self) -> bool:
        data = self.load()
        return data.get("in_position", False)