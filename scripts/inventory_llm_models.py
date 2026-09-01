from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from velox.analysis.model_assessment import inventory_models, write_model_inventory
from velox.config import load_settings


def main() -> None:
    inventory = inventory_models(load_settings())
    path = write_model_inventory(inventory)
    print(f"Wrote model inventory to {path}")


if __name__ == "__main__":
    main()
