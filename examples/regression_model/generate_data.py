"""Generate synthetic regression data for demo/testing."""

from __future__ import annotations

import csv
import random
from pathlib import Path


def main(output_path: Path = Path("data.csv"), n_rows: int = 200, seed: int = 7) -> None:
    random.seed(seed)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.writer(file_obj)
        writer.writerow(["feature_income", "feature_utilization", "target_loss"])
        for _ in range(n_rows):
            income = random.uniform(35_000, 150_000)
            utilization = random.uniform(0.05, 0.95)
            noise = random.uniform(-500, 500)
            target = 0.003 * income + 2_000 * utilization + noise
            writer.writerow([round(income, 2), round(utilization, 4), round(target, 2)])


if __name__ == "__main__":
    main()
