"""Small helpers for the tutorial; training stays in the upstream SkillOpt CLI."""
from __future__ import annotations

import argparse
import difflib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "configs/product_qa.yaml"
LOCAL_CONFIG = ROOT / "configs/product_qa.local.yaml"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def config():
    from skillopt.config import flatten_config, load_config

    return flatten_config(load_config(str(LOCAL_CONFIG if LOCAL_CONFIG.exists() else TEMPLATE)))


def configure(replace: bool = False):
    import yaml

    model = os.environ.get("OPENAI_COMPATIBLE_MODEL", "").strip()
    if not model or model == "YOUR_MODEL_ID" or "替换" in model:
        raise ValueError("先填写并导出 OPENAI_COMPATIBLE_MODEL。")
    # 分别读取角色专属模型名，未设置时回退到通用值。
    target_model = os.environ.get("TARGET_OPENAI_COMPATIBLE_MODEL", "").strip() or model
    optimizer_model = os.environ.get("OPTIMIZER_OPENAI_COMPATIBLE_MODEL", "").strip() or model
    # Only model names go into this generated file, never API credentials.
    content = yaml.safe_dump({
        "_base_": "product_qa.yaml",
        "model": {"target": target_model, "optimizer": optimizer_model},
    }, allow_unicode=True, sort_keys=False)
    if LOCAL_CONFIG.exists():
        if LOCAL_CONFIG.read_text(encoding="utf-8") == content:
            print("本地配置已是当前模型，无需修改。")
            return
        if not replace:
            raise ValueError("本地配置已存在；如需覆盖模型设置，执行 configure --replace。")
    LOCAL_CONFIG.write_text(content, encoding="utf-8")
    print("已生成 configs/product_qa.local.yaml（不含 API Key）。")


def check():
    from scripts.train import get_adapter
    from skillopt.envs.searchqa.evaluator import evaluate

    cfg = config()
    if not Path(cfg["skill_init"]).is_file():
        raise ValueError("找不到初始 Skill。")
    adapter = get_adapter(cfg)
    adapter.setup(cfg)
    seen = set()
    for split, expected in [("train", 8), ("valid_seen", 4), ("valid_unseen", 4)]:
        items = adapter.build_eval_env(0, split, 42)
        if len(items) != expected:
            raise ValueError(f"{split} 应有 {expected} 题，实际 {len(items)}。")
        for item in items:
            if not isinstance(item["id"], str) or item["id"] in seen:
                raise ValueError("题目 ID 不是字符串或有重复。")
            if Path(item["id"]).name != item["id"] or item["id"] in {".", ".."}:
                raise ValueError("题目 ID 必须可以安全用作文件夹名。")
            seen.add(item["id"])
            if not item["question"] or not item["context"] or not item["answers"]:
                raise ValueError(f"题目缺少内容：{item['id']}")
            for answer in item["answers"]:
                if not isinstance(answer, str) or not answer.strip():
                    raise ValueError(f"答案不能为空：{item['id']}")
                if evaluate(f"<answer>{answer}</answer>", item["answers"])["em"] != 1:
                    raise ValueError(f"答案未通过评分检查：{item['id']}")
        print(f"{split}: {len(items)} 题，OK")
    practice = read_json(ROOT / "data/product_qa/practice.json")
    if not all(practice.get(key) for key in ("context", "question", "expected_answer")):
        raise ValueError("新问题示例不完整。")
    print("本地检查通过；没有调用模型。")


def target():
    # Validate first, then import the backend so it sees the current environment.
    cfg = config()
    if cfg["target_model"] == "YOUR_MODEL_ID":
        raise ValueError("请先运行 python demo.py configure。")
    endpoint = (os.environ.get("TARGET_OPENAI_COMPATIBLE_BASE_URL")
                or os.environ.get("OPENAI_COMPATIBLE_BASE_URL", ""))
    if not endpoint.startswith(("http://", "https://")) or ".example" in endpoint:
        raise ValueError("请填写真实的 OPENAI_COMPATIBLE_BASE_URL 并导出环境变量。")
    from skillopt.model import chat_target, set_target_backend, set_target_deployment

    set_target_backend(cfg["target_backend"])
    set_target_deployment(cfg["target_model"])
    return chat_target


def run_path(value: str | None) -> Path:
    value = value or os.environ.get("DEMO_RUN")
    if not value:
        raise ValueError("请设置 DEMO_RUN 或传入 --run outputs/你的实验目录。")
    path = Path(value).resolve()
    if not path.is_dir():
        raise ValueError("实验目录不存在，请检查 --run 或 DEMO_RUN。")
    return path


def inspect(run: Path):
    before = (ROOT / "skills/product_qa/initial_skill.md").read_text(encoding="utf-8")
    after = (run / "train/best_skill.md").read_text(encoding="utf-8")
    diff = "".join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile="initial_skill.md", tofile="best_skill.md",
    ))
    print(diff or "最佳 Skill 与初始版本相同。")
    for row in read_json(run / "train/history.json"):
        print({key: row.get(key) for key in (
            "step", "action", "candidate_gate_score", "current_score", "best_score"
        )})
    summary = read_json(run / "train/summary.json")
    print("初始验证分数：", summary["baseline_selection_hard"])
    print("最佳验证分数：", summary["best_selection_hard"])


def answers(run: Path, folder: str):
    folder_path = run / folder
    print(json.dumps(read_json(folder_path / "eval_summary.json"), ensure_ascii=False, indent=2))
    for line in (folder_path / "results.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        print("\n题目：", row["question"])
        print("回答：", row["predicted_answer"])
        print("标准：", row.get("gold_answers", row.get("gold_answer")))
        print("得分：", row["hard"], "调用成功：", row.get("agent_ok"))
        if row.get("fail_reason"):
            print("失败原因：", row["fail_reason"])


def compare(run: Path):
    initial = read_json(run / "test_initial/eval_summary.json")
    best = read_json(run / "test_best/eval_summary.json")
    if initial["n_items"] != best["n_items"] or initial["split"] != best["split"]:
        raise ValueError("两次评估的 split 或题目数量不一致。")
    print(f"题目数：{initial['n_items']}，split：{initial['split']}")
    print(f"初始 Skill：{initial['hard']:.0%}")
    print(f"最佳 Skill：{best['hard']:.0%}")
    print(f"变化：{(best['hard'] - initial['hard']) * 100:+.0f} 个百分点")


def main():
    parser = argparse.ArgumentParser(description="产品说明问答教程辅助工具")
    parser.add_argument("action", choices=["check", "configure", "probe", "answers", "inspect", "compare", "ask"])
    parser.add_argument("--run", help="实验目录；默认读取 DEMO_RUN")
    parser.add_argument("--folder", choices=["baseline_train", "test_initial", "test_best"], default="baseline_train")
    parser.add_argument("--question", help="ask 使用的新问题；默认读取 practice.json")
    parser.add_argument("--replace", action="store_true", help="覆盖已生成的本地模型配置")
    args = parser.parse_args()
    os.chdir(ROOT)
    if args.action == "check":
        check()
    elif args.action == "configure":
        configure(args.replace)
    elif args.action == "probe":
        reply, usage = target()(system="请简短回答。", user="只回复 OK。", max_completion_tokens=128, retries=1)
        if not reply.strip():
            raise ValueError("服务返回空文本，请检查模型类型和输出 token 上限。")
        print("模型回复：", reply)
        print("用量：", usage)
    else:
        run = run_path(args.run)
        if args.action == "inspect":
            inspect(run)
        elif args.action == "answers":
            answers(run, args.folder)
        elif args.action == "compare":
            compare(run)
        else:
            from skillopt.envs.searchqa.rollout import _build_system, _build_user

            skill = (run / "train/best_skill.md").read_text(encoding="utf-8")
            item = read_json(ROOT / "data/product_qa/practice.json")
            reply, usage = target()(
                system=_build_system(skill),
                user=_build_user(args.question or item["question"], item["context"]),
                max_completion_tokens=2048, retries=1,
            )
            print(reply)
            print("用量：", usage)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, FileNotFoundError, KeyError, ModuleNotFoundError) as error:
        raise SystemExit(f"未完成：{error}") from None
