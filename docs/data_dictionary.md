# 研究数据库数据字典

## 基本原则

- 每张表只有一个明确粒度；
- 证券与底层资产分开，避免扩募后资产边界混乱；
- 指标值必须连接到来源文档；
- `period_end` 表示经营归属期，`publication_date`／`valid_from` 表示市场何时能够知道；
- 更正值新增版本，不能覆盖旧版本；
- 原始单位与规范单位同时保留，禁止无法追溯的静默换算。

## 主数据表

### `reit_master`

粒度：每只上市证券一行。主键：`symbol`。

核心字段包括证券名称、交易所、上市日期、资产类型、管理人、状态和正式来源。未来增加状态生效区间、基金更名和扩募事件。

### `asset_master`

粒度：每项底层资产一行。主键：`symbol + asset_id`。

资产必须独立于证券存在。地理字段除了经纬度，还应逐步加入点、线、面类型以及流域、收费路段或园区边界的版本。

## 参考表

### `metric_definitions`

粒度：每个规范指标一行。主键：`metric`。

`canonical_unit` 是正式面板单位；`asset_scope` 表示适用资产类型；`expected_frequency` 表示预期披露频率。同名但税基、范围或计算方法不同的指标必须拆分，不能强行合并。

### `asset_type_metric_requirements`

粒度：每个资产类型与规范指标组合一行。主键：`asset_type + metric`。

`requirement_level`：

- `core`：构成该资产类型基础面板的最低要求；
- `optional`：有研究价值，但不应因缺失而直接否定样本。

## 来源与事实表

### `source_documents`

粒度：每份正式公告或报告一行。主键：`document_id`，`source_url` 也必须唯一。

当前记录证券、文档类型、报告期、发布日期、URL 和核验状态。下一步增加抓取时间、文件哈希、更正关系、解析器版本和人工复核信息。

### `operating_metrics`

原始维护表粒度：每项资产、报告期、指标和来源版本一行。

自然键：`symbol + asset_id + period_end + metric`。当同一自然键出现后续更正时，它不是重复行，而是新版本。

核心字段：

| 字段 | 含义 |
|---|---|
| `value`, `unit` | 标准化数值与单位 |
| `raw_value`, `raw_unit` | 公告原始值与单位 |
| `document_id` | 来源公告外键 |
| `observation_id` | 单个观测版本的唯一标识 |
| `valid_from` | 该版本进入公开信息集的日期 |
| `valid_to` | 被新版本替代的日期；当前版本为空 |
| `supersedes_observation_id` | 新版本所替代的旧版本 |
| `quality_status` | 已核验或未核验状态 |

历史快照使用半开区间：`valid_from <= as_of < valid_to`。因此在更正公告发布当天，快照切换到新版本。

### `distributions`

粒度：每只证券每个除息事件一行。主键：`symbol + ex_date`。

每份分派金额必须来自正式收益分配公告。公告日决定信息时点，除息日决定持有收益归属，两者不可混用。

## 数据产品

数据库构建命令会生成：

- `operating_observation_versions.csv`：完整版本历史；
- `core_metric_coverage.csv`：按资产类型核心要求生成的覆盖矩阵；
- `operating_observations_as_of.csv`：指定历史日期的可见信息快照。

这些文件属于可重复生成的分析数据，不作为人工维护源表，也不提交仓库。
