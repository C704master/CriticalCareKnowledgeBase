# 11 月 1—19 日材料覆盖核对

目录按实验批次整理。74 个目录是盘点范围，不代表 74 个批次均具备公开的逐次调用记录。

|实验|结果与格式|实际运行记录|
|---|---|---|
|月初路由、参数分发、检索摸底|[早期说明](00-early-and-acceptance.md)和逐子问题计数|[子问题检索表](../results/early-subquestion-retrieval.csv)；未逐批发布请求级台账|
|49 子问题重排|[固定候选后的排序评测](02-ranking.md)|[49 次候选相关性评审](../results/rerank-review-calls.csv)，记录的是评审调用，非向量计算次数|
|10 例完整问题 Agent-loop|[指标与停止情况](01-agent-loop.md)|[30 次规划和评审调用](../results/agent-loop-calls.csv)，含试点和续跑|
|旧 30 题、90 份回答|[结果](03-answers.md)、[运行配置及系统提示词快照](../protocols/abc30/)|[213 次调用尝试](../results/abc-call-attempts.csv)、[90 份答案级指标](../results/abc-runs.csv)，另见原件目录中的 286 行检索记录|
|90 份回答的来源核查|[逐答案结果](../results/claim-support.csv)、[方法及评审提示词](../originals/README.md)|[731 次评审尝试](../results/claim-review-attempts.csv)，含校准、失败、取消、重试，与生成台账分开|
|三日建档与提示词迭代|[v4—v10 的输入输出格式和各版原文](05-prompt-history.md)|[9 次对照生成](../results/prompt-v4-v10-runs.csv)；其他较早试跑见原件目录的阶段运行核对表|
|新 30 个压缩病例|[计划](../plans/archive30.md)|尚未批量执行|

表格来自保存的记录。未回传的用量保留空白；各表行单位不同。患者正文、含原文的完整请求和响应继续保存在本地。其余目录目前以[盘点清单](../inventory.csv)为入口，未逐目录确认全部版本和运行记录已发布。

11 月 11 日十二题固定流程、12 日十二题三组回归与 CMB-Clin 独立对照的结果和台账已补列于[首页逐日索引](../README.md)。
