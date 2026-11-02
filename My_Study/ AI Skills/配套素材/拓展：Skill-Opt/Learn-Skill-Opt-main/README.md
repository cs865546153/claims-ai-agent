# Learn-Skill-Opt

用一个小型产品说明问答，学习 SkillOpt 如何通过任务反馈改进技能文档。模型权重不变，最后产出一份 `best_skill.md`。

已准备好 **8 道训练题、4 道验证题、4 道测试题**，以及初始 Skill、运行配置和辅助命令。无需下载大型数据集，也不用修改上游训练代码。

**从这里开始：[完整分步教程](docs/product-qa-walkthrough.zh.md)。**

## 文件位置

| 位置 | 内容 |
|---|---|
| [docs/](docs/product-qa-walkthrough.zh.md) | 环境准备到最终使用的完整操作指南 |
| [data/product_qa/](data/product_qa/) | 已准备好的 train / val / test 题目和新问题 |
| [data/README.md](data/README.md) | 数据格式、评分方式和使用边界 |
| [skills/product_qa/initial_skill.md](skills/product_qa/initial_skill.md) | 初始技能文档 |
| [configs/product_qa.yaml](configs/product_qa.yaml) | 一轮、每批 4 题、每步最多 2 条编辑 |
| [.env.example](.env.example) | 模型服务配置模板 |
| [demo.py](demo.py) | 配置、本地检查、结果查看和新问题演示 |
| [docs/upstream-version.md](docs/upstream-version.md) | 上游版本、固定提交与安装替代方式 |

## 快速开始

进入本仓库根目录（本机文件夹也可以叫 `Skill-Opt-Demo`），使用 Python 3.10+：

```bash
test -d .venv || python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python demo.py check
```

这一步仅安装依赖和检查本地数据，不调用模型。已有相邻的同版本 `SkillOpt` 源码时，可以用 `python -m pip install -e ../SkillOpt` 替代 requirements 安装。

然后准备配置：

```bash
test -f .env || cp .env.example .env
```

打开 `.env`，填写服务商提供的 Base URL、模型 ID 和 API Key，再继续：

```bash
set -a
source .env
set +a
python demo.py configure
python demo.py probe
```

`probe` 会发送一次真实模型请求。接下来的评估和训练也会消耗所选服务的额度；数据量小并不代表只调用 16 次。也可按教程用不回显的方式临时输入 Key。

创建独立实验目录并执行完整过程：

```bash
mkdir -p outputs
export DEMO_RUN="$(mktemp -d outputs/run-XXXXXX)"
echo "$DEMO_RUN"

skillopt-eval --config configs/product_qa.local.yaml \
  --skill skills/product_qa/initial_skill.md --split train \
  --out_root "$DEMO_RUN/baseline_train"
python demo.py answers

skillopt-train --config configs/product_qa.local.yaml \
  --out_root "$DEMO_RUN/train"
python demo.py inspect

skillopt-eval --config configs/product_qa.local.yaml \
  --skill skills/product_qa/initial_skill.md --split valid_unseen \
  --out_root "$DEMO_RUN/test_initial"
skillopt-eval --config configs/product_qa.local.yaml \
  --skill "$DEMO_RUN/train/best_skill.md" --split valid_unseen \
  --out_root "$DEMO_RUN/test_best"
python demo.py compare
python demo.py ask
```

请按顺序执行，当前一步失败时先修复再继续。记住 `DEMO_RUN` 输出的目录；重开终端后重新加载配置并恢复该变量。查看结果也可以直接指定目录：`python demo.py inspect --run outputs/run-你的编号`。

每次换数据、模型或初始 Skill，都重新创建实验目录。上游会缓存已有输出，不要在旧目录里混跑不同实验。

## 怎样看结果

- `outputs/run-*/train/best_skill.md`：验证集选出的最佳 Skill。
- `outputs/run-*/train/history.json`：每步接受、拒绝或跳过的记录。
- `outputs/run-*/test_*/eval_summary.json`：独立测试集的评估分数。
- `python demo.py answers --folder test_best`：逐题查看最佳 Skill 的测试回答。

没有提升也可能是正常结果：模型原本已会做题，或修改未能严格提高验证分数。16 道合成题用于教学，不足以证明业务效果。`best_skill.md` 是指令文本，不会自动安装到其他 Agent。

## 离线验证

```bash
python demo.py check
python -m unittest discover -s tests -v
```

这些检查不调用模型，也不需要 API Key。它们验证配置与数据、帮助命令和本地配置的覆盖保护，不代表已经验证真实模型训练。

## 与上游的关系

训练与评估使用 [Microsoft SkillOpt](https://github.com/microsoft/SkillOpt)。本仓库提供学习材料、虚构题目和轻量辅助工具，不复制训练引擎。上游依赖锁定在 `requirements.txt` 的提交版本。

`.env`、本地模型配置、`.venv` 和实验输出均被 Git 忽略。示例文件中不包含真实账号、Key 或私人材料。
