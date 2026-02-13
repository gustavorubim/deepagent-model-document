"""Evaluate demo regression model metrics."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path


def evaluate(data_path: Path, model_path: Path) -> dict[str, float]:
    rows = _read_rows(data_path)
    model = json.loads(model_path.read_text(encoding="utf-8"))
    predictions = [
        model["intercept"] + model["beta_income"] * income + model["beta_utilization"] * utilization
        for income, utilization, _ in rows
    ]
    targets = [target for _, _, target in rows]

    errors = [prediction - target for prediction, target in zip(predictions, targets, strict=True)]
    mae = sum(abs(err) for err in errors) / len(errors)
    rmse = math.sqrt(sum(err**2 for err in errors) / len(errors))

    target_mean = sum(targets) / len(targets)
    ss_tot = sum((target - target_mean) ** 2 for target in targets)
    ss_res = sum((target - prediction) ** 2 for target, prediction in zip(targets, predictions, strict=True))
    r2 = 1 - (ss_res / ss_tot)

    return {"mae": round(mae, 4), "rmse": round(rmse, 4), "r2": round(r2, 4)}


def _read_rows(data_path: Path) -> list[tuple[float, float, float]]:
    with data_path.open(encoding="utf-8") as file_obj:
        reader = csv.DictReader(file_obj)
        return [
            (
                float(row["feature_income"]),
                float(row["feature_utilization"]),
                float(row["target_loss"]),
            )
            for row in reader
        ]


def main() -> None:
    metrics = evaluate(Path("data.csv"), Path("results/model.json"))
    Path("results").mkdir(parents=True, exist_ok=True)
    Path("results/metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
