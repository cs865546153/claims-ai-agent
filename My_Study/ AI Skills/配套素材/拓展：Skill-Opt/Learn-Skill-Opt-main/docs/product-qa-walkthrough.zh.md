# SkillOpt 实操指南：让 AI 根据产品说明回答问题

这份指南沿用“产品说明问答”的小例子，带你完成一次真实的 Skill 优化：准备题目、测初始表现、训练、检查修改、独立测试，再把生成的 Skill 用在新问题上。

**你要观察的是：同一个模型，换了一份技能文档，回答是否更可靠。** SkillOpt 修改 Markdown 指令，不修改模型权重。

本仓库调用 Microsoft SkillOpt 固定源码版本中的 `searchqa` 适配器，装入自己编写的虚构题目。不需要下载 SearchQA 数据集，也不需要编写新的适配器。配置里的 `searchqa` 是复用的执行和评分流程名称，不代表我们在复现官方 SearchQA 成绩。

## 0. 先看完整路线

```text
读取仓库自带的初始 Skill 和 16 道题
        ↓
用初始 Skill 回答训练题，查看错误
        ↓
SkillOpt：做题 → 反思 → 合并建议 → 筛选修改 → 改 Skill → 验证
        ↓
保存验证集表现最好的 best_skill.md
        ↓
在相同测试题上比较初始 Skill 和 best_skill.md
        ↓
带着 best_skill.md 回答一个新问题
```

本例的设置：

| 项目 | 设置 |
|---|---|
| 任务 | 从产品说明中提取答案，区分版本、地区和缺失信息 |
| 训练集 | 8 题，给优化模型提供改进线索 |
| 验证集 | 4 题，决定候选修改是否被接受 |
| 测试集 | 4 题，训练结束后比较新旧 Skill |
| 模型 | 初次实验让目标模型和优化模型使用同一个模型 |
| 训练量 | 1 轮，每批 4 题，共 2 次优化步骤 |
| 评分 | 提取 `<answer>` 标签内的答案，与预设答案做规范化后的精确匹配 |

真实模型可能一开始就全部答对，也可能提出无效修改。**本例用于观察完整流程，不保证分数一定提升。** 4 道验证题的分数只能以 25 个百分点跳变；这些同类模板题只适合教学，不能证明业务泛化效果。

## 1. 安装运行环境

所有命令在这个 **Learn-Skill-Opt 学习仓库的根目录**执行。你的本地文件夹可以叫 `Skill-Opt-Demo`，不影响 GitHub 仓库名称。适用于 macOS / Linux 的 bash 或 zsh；需要 Python 3.10+ 和 Git。

数据、配置、初始 Skill 都已随仓库准备好，不需要进入上游 SkillOpt 文件夹执行教程。

```bash
python3 --version
test -d .venv || python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python demo.py check
```

`requirements.txt` 固定了核对过的上游提交，从源码安装。看到 `本地检查通过；没有调用模型。` 后继续。

如果相邻目录已有同版本的 `SkillOpt` 源码，可以将安装命令替换为 `python -m pip install -e ../SkillOpt`。版本和安装区别见 [上游版本说明](upstream-version.md)。本例不需要 WebUI、Sleep，也不需要下载 SearchQA 数据集。

## 2. 配置模型服务

本例使用项目内置的 `openai_compatible` 后端。你需要一个支持 Chat Completions 协议、允许普通文本输出的服务，以及可用的模型名称和 API Key。

这里有两个角色：

- **目标模型**：读取产品说明和 Skill，回答题目。
- **优化模型**：阅读任务记录与得分，为 Skill 提出修改。

先让两个角色共用一个服务和模型，减少配置量。之后可以分别配置。

复制环境配置模板。已有 `.env` 时保留原文件：

```bash
test -f .env || cp .env.example .env
```

用编辑器打开 `.env`，填写真实的 `OPENAI_COMPATIBLE_BASE_URL` 和 `OPENAI_COMPATIBLE_MODEL`。Base URL 以服务商要求为准，不要填网页聊天地址或自行追加 `/chat/completions`。API Key 可以填写在本地 `.env`，也可以保持为空，稍后用不回显的方式输入。

加载当前终端的配置：

```bash
set -a
source .env
set +a
```

如果没有把 Key 写进 `.env`，执行下面命令输入：

```bash
export OPENAI_COMPATIBLE_API_KEY="$(python -c 'import getpass; print(getpass.getpass("API Key（输入不回显）: "))')"
```

输入时不显示字符是正常的。不需要认证的本地服务可直接回车。`.env`、生成的 `*.local.yaml` 和运行输出都已加入 `.gitignore`；不要把真实 Key 写入共享 YAML 或示例数据。

真实服务需支持当前后端发送的 `max_tokens` 参数。已有 `TARGET_OPENAI_COMPATIBLE_*` / `OPTIMIZER_OPENAI_COMPATIBLE_*` 变量会覆盖共享设置，曾配置过其他服务时请留意。

**费用提示：** 第 5 步以后的连通性检查、评估、训练和新问题演示会调用所选模型服务。训练还包含反思、合并、筛选和验证，调用数多于题目数；题目数和 token 上限都不是费用硬上限。

重新打开终端后，需要重新激活 `.venv`、加载 `.env`，并恢复后文的 `DEMO_RUN`。辅助脚本不会自动加载 `.env`。

## 3. 认识已准备好的文件，生成本地模型配置

文件已经准备好：

```text
Learn-Skill-Opt/              # 本机也可以叫 Skill-Opt-Demo
├── README.md
├── demo.py                   # 检查、查看结果、调用新 Skill 的辅助工具
├── requirements.txt          # 固定版本的 SkillOpt 源码依赖
├── .env.example
├── docs/
│   └── product-qa-walkthrough.zh.md
├── configs/
│   └── product_qa.yaml       # 可共享的实验参数
├── skills/product_qa/
│   └── initial_skill.md
└── data/product_qa/
    ├── train/items.json      # 8 道训练题
    ├── val/items.json        # 4 道验证题
    ├── test/items.json       # 4 道测试题
    └── practice.json         # 训练结束后的新问题
```

根据第 2 步导出的模型 ID 生成本地配置：

```bash
python demo.py configure
```

这会生成 `configs/product_qa.local.yaml`，继承共享配置，并明确设置目标模型和优化模型。它不包含 API Key。

这些产品和数字均为虚构。训练、验证、测试使用不同产品与数值；每段资料都含旧版数字和海外规则作为干扰。[数据说明](../data/README.md)介绍了文件结构。

你可以先阅读 [训练题](../data/product_qa/train/items.json) 和 [初始 Skill](../skills/product_qa/initial_skill.md)。`answers` 可以包含多个预先认可的等价答案。目标模型只收到 Skill、问题和 context，标准答案留给评分程序；训练题的评分和任务记录随后会提供给优化模型。

关键参数位于 [共享配置](../configs/product_qa.yaml)：

| 参数 | 本例数值 | 含义 |
|---|---|---|
| `train.num_epochs` | 1 | 训练一轮 |
| `train.batch_size` | 4 | 每批 4 道题，共 2 次优化步骤 |
| `optimizer.learning_rate` | 2 | 每步最多选择 2 条编辑 |
| `evaluation.use_gate` | true | 验证分数严格提升才接受 |
| `evaluation.eval_test` | false | 训练时不自动测试，之后手动比较 |
| `evaluation.test_env_num` | 0 | 独立评估时读取指定 split 的全部题目 |
| `env.workers` | 1 | 一次并发执行 1 个任务 |

跨轮慢更新和元技能均已关闭，以便专注基本循环。`learning_rate` 是编辑条数预算，不是神经网络的权重更新步长。

## 4. 先做不花模型费用的检查

这一步检查配置继承、数据读取、题目 ID 和答案格式，不发送模型请求。

```bash
python demo.py check
```

这里的命令行名称容易混淆：

| 数据文件夹 | 评估命令中的 `--split` | 用途 |
|---|---|---|
| `train/` | `train` | 训练题 |
| `val/` | `valid_seen` | 验证题，决定是否接受修改 |
| `test/` | `valid_unseen` | 测试题，最终对比 |

`valid_seen` 在本例中仍是与训练题分开的验证集，名称不是说它参与了训练反思。

## 5. 检查模型连通性

下面只调用目标模型一次。返回 `OK` 或类似短回复后再继续。

```bash
python demo.py probe
```

如果出现认证、模型不存在或接口错误，先修好这一步。本文未单独测试优化角色，因为配置中两个角色使用相同模型和后端。

## 6. 测量初始 Skill 的表现

先生成一个本次实验专属的目录，避免复用旧结果缓存：

```bash
mkdir -p outputs
export DEMO_RUN="$(mktemp -d outputs/run-XXXXXX)"
echo "$DEMO_RUN"
```

记下输出路径。后续命令都使用它；中途换终端时，把 `DEMO_RUN` 重新设为这个路径，而不是再创建一个空目录。

先评估 **训练集**，了解初始 Skill 在哪些地方出错：

```bash
skillopt-eval \
  --config configs/product_qa.local.yaml \
  --skill skills/product_qa/initial_skill.md \
  --split train \
  --out_root "$DEMO_RUN/baseline_train"
```

终端会显示 `hard`、`soft` 和题目数。这里重点看 `hard`：例如 `0.75` 表示 8 题中有 6 题精确匹配。内置的 `soft` 是按空格分词的 F1，不是中文语义相似度，所以本例不拿它作为接受修改的依据。

逐题查看回答：

```bash
python demo.py answers
```

观察模型是否混淆年份和地区、是否把“没写”理解为“不支持”。若 `agent_ok` 为 false，先解决接口问题；不能把调用失败当作 Skill 能力不足。

若全部答对，可以继续跑一次看流程，但应预期最终 Skill 可能保持原样。不要为了制造提升故意写错初始 Skill。

## 7. 启动一次真实训练

```bash
skillopt-train \
  --config configs/product_qa.local.yaml \
  --out_root "$DEMO_RUN/train"
```

这一步调用真实模型。程序先测初始 Skill 在验证集上的得分，再执行两次优化步骤。终端中的阶段可以这样理解：

| 日志阶段 | 实际发生的事情 |
|---|---|
| `ROLLOUT` | 目标模型带着当前 Skill 做训练题 |
| `REFLECT` | 优化模型阅读回答过程和得分，提出改进建议 |
| `AGGREGATE` | 合并修改建议 |
| `SELECT` | 在每步编辑预算内筛选建议 |
| `UPDATE` | 将建议应用到 Skill，生成候选文档 |
| `EVALUATE` | 在验证集上评分，决定接受还是拒绝 |

有时没有可用建议，步骤会提前跳过，未必每次都完整执行六阶段。

本例启用默认的严格提升门槛：验证分数必须高于当前分数才接受，打平也拒绝。候选 Skill 看起来更详细，并不意味着一定更有效。

训练结束后应该生成：

```text
$DEMO_RUN/train/
├── best_skill.md
├── config.json
├── history.json
├── summary.json
├── selection_eval_baseline/
├── skills/
└── steps/
    ├── step_0001/
    └── step_0002/
```

`best_skill.md` 是验证集选出的最佳版本。若没有修改被接受，它可以与初始 Skill 完全相同。

## 8. 查看 Skill 到底改了什么

先打开文件：

```bash
cat "$DEMO_RUN/train/best_skill.md"
```

再用下面命令同时查看文档差异和每步决策：

```bash
python demo.py inspect
```

常见动作：

| `action` | 含义 |
|---|---|
| `accept_new_best` | 候选通过验证，并成为新的最佳版本 |
| `accept` | 候选优于当前版本，被接受 |
| `reject` | 候选没有严格提高验证分数 |
| `skip_no_patches` | 没有生成可用的修改建议 |

你可能看到“先确认地区和年份”“资料没提及就回答文档未说明”等规则。**这只是可能的修改方向，不是预设训练结果。** 本例的答题约定已经放在 context 中，优化主要可能发生在执行这些约定的策略上。

如果想追踪一次修改，打开对应 `steps/step_XXXX/`：

- `rollout/results.jsonl`：这批训练题的回答和得分。
- `rollout/predictions/<题目 ID>/conversation.json`：供反思使用的任务记录。
- `patches/`：反思产生的建议。
- `candidate_skill.md`：有候选修改时生成的文档，可能最终被拒绝。
- `step_record.json`：该步得分和接受／拒绝记录。

有些步骤会提前跳过，因此不一定拥有所有文件。应使用 `best_skill.md` 继续测试，不能把最后一个候选自动当作最佳版本。

## 9. 在独立测试集上比较新旧 Skill

到这里才使用测试题。分别评估初始 Skill 和最终选出的 Skill：

```bash
skillopt-eval \
  --config configs/product_qa.local.yaml \
  --skill skills/product_qa/initial_skill.md \
  --split valid_unseen \
  --out_root "$DEMO_RUN/test_initial"

skillopt-eval \
  --config configs/product_qa.local.yaml \
  --skill "$DEMO_RUN/train/best_skill.md" \
  --split valid_unseen \
  --out_root "$DEMO_RUN/test_best"
```

打印对比：

```bash
python demo.py compare
```

判断结果时，同时看分数与原始回答：

- **测试分数提高**：这次实验出现改善，但样本太少，还需要更多独立题目确认。
- **测试分数相同**：可能原本就会，也可能新规则对这些题没有帮助。
- **验证提高、测试下降**：可能对验证题过拟合，也可能有生成波动；验证门槛并不保证测试提升。
- **文字意思正确但判错**：检查输出格式和预设等价答案。这是精确匹配评分的限制。

不要根据这 4 道测试题反复改 Skill 或补答案后，再把它们当作“没见过的测试题”。需要继续调整时，另准备新的最终测试集。

## 10. 用优化后的 Skill 回答新问题

接下来只调用目标模型，不再调用优化模型。为了与训练条件保持一致，继续复用本项目 SearchQA 的提示词包装函数。

```bash
python demo.py ask
```

本题的正确答案是 `<answer>32</answer>`；以模型实际回复为准。可以执行 `python demo.py ask --question "白帆笔记专业版是否支持离线使用？"`，预期是 `<answer>文档未说明</answer>`。示例材料在 `data/product_qa/practice.json`。

这就是生成文件的实际用法：**把技能文本放进目标模型的指令，再提供新任务。** 不需要在每次回答时重新执行优化。

注意，本例的 `best_skill.md` 是研究训练产物，不会自动注册成 Codex 或 Claude Code 的原生技能。若要迁移到其他 Agent，还需要适配该 Agent 的技能格式和任务包装，并重新验证效果。

## 11. 出现问题时，按这一顺序排查

| 现象 | 优先检查 |
|---|---|
| `No module named ...` | 是否激活 `.venv`，是否执行过 `pip install -r requirements.txt` |
| 第 3 步提示本地配置已存在 | 相同模型无需重建；有意换模型时使用 `configure --replace` |
| 401 / 403 | Key 是否正确、是否具有该模型的权限 |
| 404 / model not found | Base URL 和模型 ID 是否正确 |
| 不支持 `max_tokens` | 服务协议或模型不兼容当前后端的请求参数 |
| 429 | 服务额度或速率限制；本例已将并发设置为 1 |
| 回复为空或 JSON 建议不完整 | 模型可能耗尽输出预算；检查服务的推理／输出设置，必要时提高 token 上限 |
| `skip_no_patches` | 查看反思输出是否解析失败、是否有任务记录、是否确实没有可用建议 |
| 所有修改都 `reject` | 验证分数没有严格提升；先看初始分数是否已满分 |
| `DEMO_RUN` 不存在 | 换终端后重新导出之前记下的实验路径 |
| 改了 Skill 却看不到新结果 | 旧输出目录可能缓存了回答；为新实验创建新目录 |

模型名称写在第 3 步生成的 `configs/product_qa.local.yaml` 中。改变环境变量之后，运行 `python demo.py configure --replace` 会覆盖该本地文件里的模型设置，再为新实验创建输出目录；共享配置保持不变。也可以在训练／评估命令中追加：

```text
--cfg-options model.target=新的模型ID model.optimizer=新的模型ID
```

同一次对比的初始和最佳 Skill 必须使用相同的目标模型、服务设置和测试题。

若要做第二次完整实验，重新执行第 6 步的 `mktemp` 命令获得新 `DEMO_RUN`，再重复评估和训练。不要往已有的输出目录里放一套不同的数据或 Skill；SearchQA 的执行流程会按题目 ID 复用已有结果。

## 12. 完成检查与下一步

- [ ] 我知道目标模型和优化模型分别做什么。
- [ ] 我读过仓库中的 8 / 4 / 4 道题，并通过本地读取检查。
- [ ] 我看过至少一道题的实际回答、标准答案和得分。
- [ ] 我完成了训练，找到 `best_skill.md` 和 `history.json`。
- [ ] 我知道哪次修改被接受或拒绝，以及对应的验证分数。
- [ ] 我在同一测试集上比较了初始和最佳 Skill。
- [ ] 我用生成的 Skill 回答了一个新的问题。

完成这些步骤，就已经跑过一次真实的“执行任务—反馈—修改技能—验证—复用”流程。

之后可把虚构题换成你自己的产品文档问答。优先加入实际遇到的错误类型，提前固定评分规则和数据划分，再扩大样本；不要一开始就增加很多轮训练。

这份指南也可以逐步与 Codex 配合：例如“我做到第 5 步，报错如下，请先定位原因”或“这是第 8 步的差异和日志，帮我解释为什么拒绝修改”。贴日志时不要包含 API Key。

## 参考与验证范围

- [安装与模型认证](https://github.com/microsoft/SkillOpt/blob/fa4ca184573e42ec11472959dd57422381418096/docs/guide/installation.md)
- [训练循环](https://github.com/microsoft/SkillOpt/blob/fa4ca184573e42ec11472959dd57422381418096/docs/guide/training-loop.md)
- [命令行参数](https://github.com/microsoft/SkillOpt/blob/fa4ca184573e42ec11472959dd57422381418096/docs/reference/cli.md)
- [自定义任务接口](https://github.com/microsoft/SkillOpt/blob/fa4ca184573e42ec11472959dd57422381418096/docs/guide/new-benchmark.md)

本仓库基于固定的上游源码提交整理。数据加载、配置解析和辅助脚本可通过离线检查；真实模型服务的连通性、接口兼容性及训练提升，以实际执行结果为准，不预设分数上涨。
