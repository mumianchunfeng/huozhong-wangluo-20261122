# 阶段二 · 关系引擎

把客观情形翻译成「实体 + 关系边」的建模层。上层勘比闭环、下层算力调度，都读这一层的产物。

## 三条纪律

1. **零模型依赖**：只用 sqlite3 + 标准库。关系抽取可以换人、换模型，但关系一旦落库，语义与约束必须是确定的。
2. **写入即校验**：任何边不符合该关系类型的约束，写库前拒掉，事务回滚，磁盘不留痕。
3. **只存指针不存正文**：`evidence` 字段只写材料出处（文件 + 页码/条款号），不把原文吞进图谱。

## 目录

```
阶段二-关系引擎/
├── relation_engine.py          # 引擎本体（建模、约束、查询、复检）
├── rules/relations.default.json # 18 类关系 + 约束（数据驱动，可整体替换）
├── data/demo.db                # 冒烟演示库（3 实体 1 边，可弃）
├── tests/test_engine.py        # 18 个用例
└── README.md
```

## 用法

```bash
python3 relation_engine.py init       --db data/graph.db
python3 relation_engine.py init-types --db data/graph.db      # 注册 18 类关系
python3 relation_engine.py add-entity --db data/graph.db --id E1 --kind 法人 --label "某公司"
python3 relation_engine.py add-edge   --db data/graph.db --src E1 --dst E2 --rtype ownership --weight 0.6 --evidence "材料A p12"
python3 relation_engine.py types      --db data/graph.db       # 看已注册关系及约束
python3 relation_engine.py show       --db data/graph.db --entity E1
python3 relation_engine.py path       --db data/graph.db --src E1 --dst E3
python3 relation_engine.py check      --db data/graph.db       # 全库不变量复检
python3 relation_engine.py stats      --db data/graph.db
```

写入被拒时退出码为 `2`，并打印具体是哪条约束、卡在哪里。

## 实体类别

`自然人 / 法人 / 非法人组织 / 公共主体 / 资产 / 资源 / 任务 / 节点 / 其他`。类别非法直接拒，防止"什么都往图谱里塞"。

## 18 类关系与约束（占位种子）

| 关系码 | 中文 | 约束 |
|---|---|---|
| supply_demand | 供需 | — |
| ownership | 权属 | 目标侧唯一（共有按 weight 记份额） |
| compensation | 补偿 | 须伴随 harm（同向同对） |
| priority | 优先级 | 不得成环 |
| trust | 信任 | — |
| risk | 风险 | — |
| exclusion | 排他 | 目标侧唯一（份额同理） |
| mutual_aid | 互助 | — |
| arbitrage | 套利 | — |
| mortgage | 抵押 | 不得成环 |
| transfer | 流转 | — |
| constraint | 约束 | — |
| privilege | 特权 | — |
| harm | 损害 | — |
| benefit | 收益 | — |
| allocation | 分配 | 目标侧唯一（份额同理） |
| guarantee | 担保 | 不得成环 |
| inheritance | 继承 | 不得成环 |

> **这 18 个码是搭建期骨架，不是你的法定关系体系。** 换成你自有那套关系界定时，只改 `rules/relations.default.json` 再跑一次 `init-types`，引擎的约束执行器一行不用动。我没有替你编法域定义，只给了机制。

约束只有四种原语，全部数据驱动：

- `unique_incoming`：目标侧唯一；`unless_weight` 允许份额共存（权重合计按你自己口径校验，引擎不擅自定义上限）
- `unique_outgoing`：源侧唯一
- `acyclic`：该关系不得成环（优先级、抵押、担保、继承属此类）
- `requires`：必须伴随另一关系（补偿须有对应损害）

出现未知约束类型时引擎**直接报错拒绝**，不"未知就放过"。

## 复检机制（关键）

`check` 不信 API，直接扫全库已有边重跑约束。原因是：**真实脏数据很少从 API 进来，多半是从别处灌进来的**（别的脚本、旧库迁移、人工改库）。所以 `check` 用 DFS 找环、用同侧比对找重复独占，把绕过 API 的历史违规也抓出来。

## 实测

```
Ran 18 tests in 0.404s
OK
```

覆盖：独占冲突、份额共存、先独占后份额被拒、优先级成环、补偿缺损害、补偿错配、自环、未注册类型、不存在实体、重复实体、非法类别、双向邻域、路径命中/不命中、过期边不可见、SQL 直插重复独占被抓、SQL 直插成环被抓、好数据零告警。

## 边界

- 本层**不判断对错，只判断结构**。"这条补偿合理吗"是勘比闭环的事；"这条补偿有没有对应损害、同一标的有没有两个权利人"才是本层的事。
- 份额是否合计为 1，引擎不强制。你的口径可能是按份、按比例、按金额，硬编码成 1 会错。留给上层校验。
- 图谱是**中期资产（忆档）**，会随案件滚动重建；它不进恒久层。

## 与阶段三的接口

勘比闭环读图谱时只调三样：`neighbors`（看某主体的全部关系面）、`path`（看两个主体之间是怎么牵连上的）、`violations`（看这盘数据本身有没有硬伤）。**先把结构洗千净，再谈价值判断。**
