"""Fixtures shared by tests and the bench: real engine facts plus extra wall boxes (detours, sealed targets)."""
from .services import EngineServices


def box(name, x0, y0, x1, y1):
    return {"id": name, "min": [x0, y0], "max": [x1, y1], "height": 2.4}


class WalledServices(EngineServices):
    """``EngineServices`` whose movement contract also contains ``extra_boxes`` (the revision changes with them)."""

    def __init__(self, engine, extra_boxes):
        super().__init__(engine)
        self.extra = list(extra_boxes)

    def contract(self):
        base = super().contract()
        return {**base, "boxes": list(base["boxes"]) + self.extra, "revision": base["revision"] + f"+{len(self.extra)}"}

    def contract_revision(self):
        return self.contract()["revision"]
