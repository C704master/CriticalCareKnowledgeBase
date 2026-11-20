# 11 月 20 日实验源码

本目录保存本轮使用的 14 份 Python 源文件。目录结构保留实验阶段，便于把试点与正式运行对应起来。

| 阶段 | 阅读入口 |
|---|---|
| 三例九答 | [三组生成](run.py) |
| 固定病例比较证据名额与引用提示 | [预算试点](budget_study/run.py) · [引用规则复跑](citation_rule_r1/run.py) |
| 扩充预算试点与验收样张 | [四例](four_case_budget/experiment.py) · [新增五例](five_case_budget/experiment.py) · [一例三答样张](format_one/run.py) |
| 正式 30 例 | [选样、三日日档和截止点裁剪](formal30/prepare.py) · [查询、选段与三组生成](formal30/run.py) · [模型调用及断点记录](formal30/batch_transport.py) |
| 正式评阅与汇总 | [内容与依据初评](formal30/review.py) · [配对比较](formal30/pair.py) · [配对结果恢复](formal30/recover_pair.py) · [结果表生成](formal30/report.py) · [配对汇总](formal30/summary.py) |

这些是原研究工作区中的执行脚本。复跑依赖原项目目录、只读病例库、冻结的知识库与检索组件、本地环境配置及模型服务。公开仓库提供源码审阅和已发布的结果；患者输入、身份映射、请求正文和凭据保留在受控环境。
