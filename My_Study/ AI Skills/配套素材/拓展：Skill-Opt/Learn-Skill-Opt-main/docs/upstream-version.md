# 上游版本与安装

本学习项目使用 Microsoft SkillOpt，不包含或修改它的训练引擎。

- 上游仓库：https://github.com/microsoft/SkillOpt
- 固定提交：`fa4ca184573e42ec11472959dd57422381418096`
- 安装定义：[requirements.txt](../requirements.txt)
- Python：3.10 或以上。

默认执行 `python -m pip install -r requirements.txt`，由 pip 从固定提交安装源码包。需要 Git 和网络。不要单独安装 PyPI 的 `skillopt==0.2.0` 来替代，它未必包含本文使用的通用 `openai_compatible` 后端。

如果相邻目录已经有同版本的 SkillOpt 源码，可改用 `python -m pip install -e ../SkillOpt`。这会使用该目录的实时工作区内容；先用 `git -C ../SkillOpt rev-parse HEAD` 检查提交，且留意未提交的代码修改。

本仓库的 `configs/product_qa.yaml` 是自包含配置，不引用另一个仓库里的配置文件。上游通过安装后的 `skillopt-train` 和 `skillopt-eval` 命令运行。
