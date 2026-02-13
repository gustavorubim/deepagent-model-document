"""Train a tiny regression model with closed-form least squares."""

from __future__ import annotations

import csv
import json
from pathlib import Path


def fit_linear_regression(data_path: Path) -> dict[str, float]:
    rows = list(_read_rows(data_path))
    x1 = [row[0] for row in rows]
    x2 = [row[1] for row in rows]
    y = [row[2] for row in rows]

    # Simplified independent-feature fit for demo purposes.
    beta_income = _covariance(x1, y) / _variance(x1)
    beta_utilization = _covariance(x2, y) / _variance(x2)
    intercept = _mean(y) - beta_income * _mean(x1) - beta_utilization * _mean(x2)
    return {
        "intercept": round(intercept, 6),
        "beta_income": round(beta_income, 9),
        "beta_utilization": round(beta_utilization, 9),
    }


def save_model(model: dict[str, float], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(model, indent=2) + "\n", encoding="utf-8")


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


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _variance(values: list[float]) -> float:
    avg = _mean(values)
    return sum((value - avg) ** 2 for value in values) / len(values)


def _covariance(first: list[float], second: list[float]) -> float:
    avg_first = _mean(first)
    avg_second = _mean(second)
    return sum(
        (x - avg_first) * (y - avg_second) for x, y in zip(first, second, strict=True)
    ) / len(first)


def main() -> None:
    data_path = Path("data.csv")
    model_path = Path("results/model.json")
    model = fit_linear_regression(data_path)
    save_model(model, model_path)


if __name__ == "__main__":
    main()
