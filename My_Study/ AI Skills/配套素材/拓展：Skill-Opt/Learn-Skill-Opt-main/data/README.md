# 示例数据

`product_qa/` 是教程使用的虚构产品说明问答，数据已经准备好，不需要下载。

| 文件 | 数量 | 用途 |
|---|---:|---|
| `product_qa/train/items.json` | 8 | 执行任务、反思和生成修改 |
| `product_qa/val/items.json` | 4 | 验证门槛，选择 Skill |
| `product_qa/test/items.json` | 4 | 训练完成后的独立对比 |
| `product_qa/practice.json` | 1 | 带着生成的 Skill 回答新问题 |

每道题包含 `id`、`question`、`context`、`answers`。`answers` 是预先认可的答案列表，评分时读取，不发给回答题目的目标模型。practice 的 `expected_answer` 只供人检查。

任务覆盖免费版数量、旧版数字干扰、缺失功能信息和导出格式。各 split 使用不同产品与数字，但共享题型模板，只适合学习流程，不能据此宣称泛化能力。

评分先提取 `<answer>...</answer>`，再作规范化的精确匹配。`hard` 是准确率；`soft` 的 F1 按空格分词，不是中文语义评分。改答案别名、题目或模型后，用新的输出目录重新实验。
