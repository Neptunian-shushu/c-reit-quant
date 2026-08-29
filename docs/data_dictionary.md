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

能源数据中特别区分：`grid_connected_electricity`（上网电量）、`settled_electricity`（结算电量）、`settlement_revenue`（结算电费）和`electricity_revenue`（项目公司发电／售电收入）。含税结算电费不能与财务报表不含税收入合并；含税电价也不能自行换算成不含税电价。

### `asset_type_metric_requirements`

粒度：每个资产类型与规范指标组合一行。主键：`asset_type + metric`。

`requirement_level`：

- `core`：构成该资产类型基础面板的最低要求；
- `optional`：有研究价值，但不应因缺失而直接否定样本。

## 来源与事实表

### `source_documents`

粒度：每份正式公告或报告一行。主键：`document_id`，`source_url` 也必须唯一。

当前记录证券、文档类型、报告期、发布日期、URL、核验状态、抓取时间、SHA-256、内容类型、字节数、抓取状态、解析器版本和更正关系。`supersedes_document_id` 只能指向同一证券更早发布的已登记公告。仓库不保存大型 PDF。

`verification_status` 当前主要分两级：

- `metadata_verified`：已确认是交易所官方定期报告，并完成内容哈希，但尚未逐项核验经营数字；
- `human_verified`：报告中的目标指标、单位、期间和原文位置已经人工核验，可以作为正式经营观测来源。

从公告目录提升报告时默认只能进入 `metadata_verified`，不能因为成功下载或正则命中就自动升级为 `human_verified`。

### `universe_history`

粒度：每个快照日每只被行情源观察到的证券一行。主键：`snapshot_date + symbol`。

`first_observed_date` 仅表示数据库第一次看到该证券，绝不能改名为或替代 `listing_date`。同日重复抓取内容相同则幂等；内容冲突会报错，禁止静默覆盖。

### `security_overrides`

粒度：每只已通过一手来源人工核验的证券一行。主键：`symbol`。

行情简称和关键词分类只是候选。只有覆盖层中的 `human_verified` 记录才能升级正式名称和资产类型，并必须保存一手来源 URL。

### `announcement_catalog`

粒度：每份交易所公告元数据一行。主键：`announcement_id`，`source_url` 也必须唯一。

`document_type_candidate` 和 `period_end_candidate` 是规则分类结果，`catalog_status=unreviewed` 表示尚未人工确认。该表只负责“发现”，不能直接作为经营观测的正式证据。沪深目录采用相同字段，保留交易所、原标题、发布日期和官方文件 URL；同一公告 ID 内容变化时拒绝静默覆盖。

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

### `asset_events`

粒度：每项会改变资产边界或经营可比性的事件一行。当前覆盖扩募购入资产、外部电网停机和电价机制变化。只知道月份而不知道具体日期时，必须保存`date_precision=month`，不能虚构日级起止时间。

### `panel_quality_reviews`

粒度：每条纵向面板实际使用的来源文档一行。主键：`panel_name + source_url`。

`single_pass`表示已逐期对照正式报告完成一次人工转录复核；`double_checked`表示又与独立维护的数据产品交叉核对。复核台账记录`reviewed_at`和备注，但不会自动改变来源文档的`verification_status`。独立双人复核尚未完成时，不能把`single_pass`包装成最终正确。

纵向面板的`source_note`还承担重要口径说明：交割后的短季度、只披露两位小数、暂估电费、整数利用小时以及税基均必须显式保留。单位换算只能改变尺度，不能恢复报告没有给出的精度。

### `distributions`

粒度：每只证券每个除息事件一行。主键：`symbol + ex_date`。

每份分派金额必须来自正式收益分配公告。公告日决定信息时点，除息日决定持有收益归属，两者不可混用。

## 数据产品

数据库构建命令会生成：

- `operating_observation_versions.csv`：完整版本历史；
- `core_metric_coverage.csv`：按资产类型核心要求生成的覆盖矩阵；
- `operating_observations_as_of.csv`：指定历史日期的可见信息快照。

这些文件属于可重复生成的分析数据，不作为人工维护源表，也不提交仓库。
