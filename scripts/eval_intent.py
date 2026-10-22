"""意图路由评测：准确率、混淆矩阵、兜底率、影子一致性与延迟。

用法（仓库根目录）：
  python -m scripts.eval_intent --engine jev --data data/intent_golden.jsonl
  python -m scripts.eval_intent --engine shadow --limit 20
  python -m scripts.eval_intent --engine jev --translate

密钥只从环境变量/.env 读取，报告不会写入 JEV_API_KEY。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from claims_platform.intent.contracts import IntentRequest, Turn
from claims_platform.intent.factory import PRESETS, IntentConfig, build_intent_classifier
from claims_platform.intent.registry import DomainRegistry
from settings import Settings

load_dotenv(Path(".env"), override=False)

DEFAULT_DATA = Path("data/intent_golden.jsonl")
DEFAULT_REPORT = Path(".data/intent_eval.json")


def load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"评测数据不存在：{path}")
    rows: list[dict[str, Any]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no} 不是合法 JSON") from exc
        missing = [key for key in ("message", "domain", "intent") if not row.get(key)]
        if missing:
            raise ValueError(f"{path}:{line_no} 缺少字段：{', '.join(missing)}")
        rows.append(row)
    return rows


def validate_labels(rows: list[dict[str, Any]], registry: DomainRegistry) -> None:
    for index, row in enumerate(rows, 1):
        manifest = registry.get(str(row["domain"]))
        if manifest.intent(str(row["intent"])) is None:
            raise ValueError(f"第 {index} 行意图不在领域 {manifest.name} 中：{row['intent']}")


async def evaluate(
    rows: list[dict[str, Any]], classifier: Any, concurrency: int
) -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def run_one(row: dict[str, Any]) -> dict[str, Any]:
        async with semaphore:
            history = [Turn(**turn) for turn in row.get("history", [])]
            request = IntentRequest(
                message=str(row["message"]),
                history=history,
                active_domain=row.get("active_domain"),
            )
            started = time.monotonic()
            try:
                decision = await classifier.classify(request)
            except Exception as exc:  # noqa: BLE001 - 评测需要记录失败样本
                return {
                    "id": row.get("id"),
                    "lang": row.get("lang", "unknown"),
                    "expected_domain": row["domain"],
                    "expected_intent": row["intent"],
                    "error": type(exc).__name__,
                    "detail": str(exc)[:300],
                    "latency_ms": int((time.monotonic() - started) * 1000),
                }
            return {
                "id": row.get("id"),
                "lang": row.get("lang", "unknown"),
                "expected_domain": row["domain"],
                "expected_intent": row["intent"],
                "pred_domain": decision.domain,
                "pred_intent": decision.intent,
                "confidence": decision.confidence,
                "margin": decision.margin,
                "engine": decision.engine,
                "fallback_used": decision.fallback_used,
                "needs_clarification": decision.needs_clarification,
                "warnings": decision.warnings,
                "shadow": decision.shadow,
                "latency_ms": decision.latency_ms,
            }

    return await asyncio.gather(*(run_one(row) for row in rows))


def _percentile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * ratio
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    errors = [item for item in results if "error" in item]
    ok = [item for item in results if "error" not in item]
    domain_correct = sum(item["pred_domain"] == item["expected_domain"] for item in ok)
    intent_correct = sum(item["pred_intent"] == item["expected_intent"] for item in ok)
    joint_correct = sum(
        item["pred_domain"] == item["expected_domain"]
        and item["pred_intent"] == item["expected_intent"]
        for item in ok
    )
    latencies = [float(item["latency_ms"]) for item in ok if item.get("latency_ms") is not None]

    per_domain: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "joint_correct": 0})
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    warnings: Counter[str] = Counter()
    for item in ok:
        expected = item["expected_domain"]
        per_domain[expected]["total"] += 1
        per_domain[expected]["joint_correct"] += int(
            item["pred_domain"] == expected and item["pred_intent"] == item["expected_intent"]
        )
        confusion[expected][item["pred_domain"]] += 1
        warnings.update(item.get("warnings") or [])

    by_lang: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "success": 0, "joint_correct": 0, "errors": 0}
    )
    for item in results:
        bucket = by_lang[item.get("lang", "unknown")]
        bucket["total"] += 1
        if "error" in item:
            bucket["errors"] += 1
            continue
        bucket["success"] += 1
        bucket["joint_correct"] += int(
            item["pred_domain"] == item["expected_domain"]
            and item["pred_intent"] == item["expected_intent"]
        )

    shadow_rows = [item for item in ok if item.get("shadow")]
    shadow_joint = sum(
        item["shadow"]["domain"] == item["expected_domain"]
        and item["shadow"]["intent"] == item["expected_intent"]
        for item in shadow_rows
    )
    shadow_agreement = sum(bool(item["shadow"].get("agreement")) for item in shadow_rows)

    return {
        "total": total,
        "success": len(ok),
        "errors": len(errors),
        "coverage": round(len(ok) / total, 4) if total else 0.0,
        "joint_accuracy": round(joint_correct / len(ok), 4) if ok else 0.0,
        "effective_accuracy": round(joint_correct / total, 4) if total else 0.0,
        "domain_accuracy": round(domain_correct / len(ok), 4) if ok else 0.0,
        "intent_accuracy": round(intent_correct / len(ok), 4) if ok else 0.0,
        "fallback_rate": round(
            sum(bool(item.get("fallback_used")) for item in ok) / len(ok), 4
        ) if ok else 0.0,
        "clarification_rate": round(
            sum(bool(item.get("needs_clarification")) for item in ok) / len(ok), 4
        ) if ok else 0.0,
        "latency_ms_p50": round(_percentile(latencies, 0.5), 1) if latencies else None,
        "latency_ms_p95": round(_percentile(latencies, 0.95), 1) if latencies else None,
        "shadow_total": len(shadow_rows),
        "shadow_joint_accuracy": round(shadow_joint / len(shadow_rows), 4) if shadow_rows else None,
        "shadow_agreement_rate": round(
            shadow_agreement / len(shadow_rows), 4
        ) if shadow_rows else None,
        "per_domain": {key: dict(value) for key, value in per_domain.items()},
        "by_lang": {key: dict(value) for key, value in by_lang.items()},
        "confusion": {key: dict(value) for key, value in confusion.items()},
        "warnings": dict(warnings),
    }


def print_summary(summary: dict[str, Any], results: list[dict[str, Any]], show_errors: bool) -> None:
    print(f"样本：{summary['total']}  成功：{summary['success']}  失败：{summary['errors']}")
    print(
        "联合准确率：{:.3f}  有效准确率（含失败）：{:.3f}  领域：{:.3f}  意图：{:.3f}".format(
            summary["joint_accuracy"],
            summary["effective_accuracy"],
            summary["domain_accuracy"],
            summary["intent_accuracy"],
        )
    )
    print(
        "兜底率：{:.3f}  澄清率：{:.3f}  延迟 P50/P95：{} / {} ms".format(
            summary["fallback_rate"],
            summary["clarification_rate"],
            summary["latency_ms_p50"],
            summary["latency_ms_p95"],
        )
    )
    if summary["shadow_total"]:
        print(
            "影子：{} 条，联合准确率 {:.3f}，与主路由一致率 {:.3f}".format(
                summary["shadow_total"],
                summary["shadow_joint_accuracy"] or 0.0,
                summary["shadow_agreement_rate"] or 0.0,
            )
        )
    print("按语言：")
    for lang, bucket in sorted(summary["by_lang"].items()):
        success = bucket["success"] or 1
        print(
            f"  {lang}: 联合准确率 {bucket['joint_correct'] / success:.3f}"
            f"（n={bucket['total']}，错误 {bucket['errors']}）"
        )
    print("领域混淆矩阵：")
    for expected, bucket in sorted(summary["confusion"].items()):
        detail = "，".join(f"{pred}={count}" for pred, count in sorted(bucket.items()))
        print(f"  {expected} -> {detail}")
    if summary["warnings"]:
        print("警告：", json.dumps(summary["warnings"], ensure_ascii=False))
    if show_errors:
        print("失败/误路由样本：")
        for item in results:
            if "error" in item:
                print(f"  [{item.get('id')}] ERROR {item['error']}: {item['detail']}")
            elif (
                item["pred_domain"] != item["expected_domain"]
                or item["pred_intent"] != item["expected_intent"]
            ):
                print(
                    f"  [{item.get('id')}] 期望 {item['expected_domain']}/{item['expected_intent']}"
                    f" -> 预测 {item['pred_domain']}/{item['pred_intent']}"
                    f"（confidence={item['confidence']:.3f}）"
                )


async def run_all(rows: list[dict[str, Any]], classifier: Any, concurrency: int) -> list[dict[str, Any]]:
    try:
        return await evaluate(rows, classifier, concurrency)
    finally:
        await classifier.aclose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="意图路由评测")
    parser.add_argument("--data", default=str(DEFAULT_DATA), help="JSONL 评测数据")
    parser.add_argument("--engine", choices=sorted(PRESETS), help="覆盖 INTENT_ENGINE 预设")
    parser.add_argument("--translate", action="store_true", help="JEV 调用前翻译成英文")
    parser.add_argument("--limit", type=int, help="只跑前 N 条")
    parser.add_argument("--concurrency", type=int, default=4, help="并发数")
    parser.add_argument("--report", default=str(DEFAULT_REPORT), help="JSON 报告输出路径")
    parser.add_argument("--min-accuracy", type=float, help="低于该有效准确率时返回非零退出码")
    parser.add_argument("--show-errors", action="store_true", help="打印失败与误路由样本")
    args = parser.parse_args(argv)

    rows = load_rows(Path(args.data))
    if args.limit:
        rows = rows[: args.limit]
    registry = DomainRegistry.default()
    try:
        validate_labels(rows, registry)
    except (KeyError, ValueError) as exc:
        print(f"评测数据无效：{exc}", file=sys.stderr)
        return 2

    config = IntentConfig.from_settings(Settings())
    if args.engine:
        preset = PRESETS[args.engine]
        config = replace(
            config,
            primary=preset["primary"],
            fallback=preset["fallback"],
            shadow=preset["shadow"],
        )
    if args.translate:
        config = replace(config, translate_to_english=True)

    try:
        classifier = build_intent_classifier(config, registry=registry)
        results = asyncio.run(run_all(rows, classifier, args.concurrency))
    except Exception as exc:  # noqa: BLE001 - CLI 需要友好错误
        print(f"评测失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    summary = summarize(results)
    print_summary(summary, results, args.show_errors)
    report = {
        "config": {
            "engine": args.engine or "settings",
            "primary": config.primary,
            "fallback": config.fallback,
            "shadow": config.shadow,
            "translate_to_english": config.translate_to_english,
            "confidence_threshold": config.confidence_threshold,
            "margin_threshold": config.margin_threshold,
            "has_jev_key": bool(config.jev_api_key),
        },
        "summary": summary,
        "results": results,
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告：{report_path}")

    if args.min_accuracy is not None and summary["effective_accuracy"] < args.min_accuracy:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
