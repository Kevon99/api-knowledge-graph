"""Metricas de calidad del motor de reglas contra un golden dataset (SAD 8.9).

Ejecuta el catalogo contra el grafo real (Neo4j) para un import y compara las
alertas emitidas contra una etiqueta de referencia (golden). Calcula precision,
recall y F1 por regla.

Uso:
    python -m akg.rules.metrics <import_id> --golden dev/golden_v1.json

Formato del golden:
    {
      "R-IDOR-001": ["/users/{id}/orders", ...],   # patrones que DEBEN alertar
      "R-IDOR-004": [...],
      "R-AUTH-001": [...]
    }
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections import defaultdict

from akg.rules import get_rules, run_rules


def load_golden(path: str) -> dict[str, list[str]]:
    with open(path) as fh:
        return json.load(fh)


def evaluate(golden: dict[str, list[str]], alerts: list) -> dict[str, dict]:
    """Por regla: tp/fp/fn y metricas."""
    by_rule: dict[str, dict] = defaultdict(
        lambda: {"tp": 0, "fp": 0, "fn": 0, "found": set(), "expected": set()}
    )
    for rid, patterns in golden.items():
        by_rule[rid]["expected"] = set(patterns)

    for a in alerts:
        acc = by_rule[a.rule.rule_id]
        fields = (a.evidence or {}).get("fields") or {}
        pattern = fields.get("pattern") or ""
        acc["found"].add(pattern)
        if pattern in acc["expected"]:
            acc["tp"] += 1
        else:
            acc["fp"] += 1
        acc["found"].add(pattern)

    report: dict[str, dict] = {}
    for rid, acc in by_rule.items():
        acc["fn"] = len(acc["expected"] - acc["found"])
        tp, fp, fn = acc["tp"], acc["fp"], acc["fn"]
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        report[rid] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
            "fp_ratio": round(fp / (tp + fp) * 100, 1) if (tp + fp) else None,
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("import_id", type=str, help="import a evaluar")
    parser.add_argument("--golden", required=True, help="ruta al golden dataset JSON")
    args = parser.parse_args()

    from engine.graph.repository import graph_repo

    golden = load_golden(args.golden)
    alerts = run_rules(get_rules(), uuid.UUID(args.import_id), graph_repo)
    report = evaluate(golden, alerts)

    header = f"{'regla':<12} {'tp':>3} {'fp':>3} {'fn':>3} {'prec':>6} {'rec':>6} {'f1':>6} {'fp%':>6}"
    print(header)
    print("-" * len(header))
    fp_total = tp_total = fn_total = 0
    for rid, m in sorted(report.items()):
        fp_total += m["fp"]
        tp_total += m["tp"]
        fn_total += m["fn"]
        print(
            f"{rid:<12} {m['tp']:>3} {m['fp']:>3} {m['fn']:>3} "
            f"{m['precision']:>6.3f} {m['recall']:>6.3f} {m['f1']:>6.3f} "
            f"{str(m['fp_ratio']):>6}"
        )
    total_prec = tp_total / (tp_total + fp_total) if (tp_total + fp_total) else 0.0
    total_rec = tp_total / (tp_total + fn_total) if (tp_total + fn_total) else 0.0
    print("-" * len(header))
    print(f"TOTAL precision={total_prec:.3f} recall={total_rec:.3f}")
    if fp_total and (tp_total + fp_total) and fp_total / (tp_total + fp_total) > 0.20:
        print(">> criterio NO cumplido: falsos positivos > 20%")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
