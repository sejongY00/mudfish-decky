"""Plugin settings persisted as JSON."""
import json
import os


class Store:
    def __init__(self, path: str):
        self.path = path

    def load(self) -> dict:
        try:
            with open(self.path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def save(self, data: dict) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, self.path)

    def update(self, **changes) -> dict:
        data = self.load()
        data.update(changes)
        self.save(data)
        return data
