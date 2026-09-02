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

### `prelisting_operating_metrics`

粒度：每项资产、实际覆盖期间和指标一行。主键：`symbol + asset_id + period_start + period_end + metric`。

`period_type`区分完整年度和`year_to_date`，禁止把2023年1—9月当作全年。`availability_class=pre_listing_disclosed_at_ipo`表示经营事实发生得更早，但市场直到招募说明书发布日期才可获取；回测只能从`publication_date`开始使用。

### `hydrology_mapping`

粒度：每个与底层资产有关的水文实体一行。`mapping_type`包括天气代理点、集水区、上游水库和河流。坐标、流域面积和调节库容各自保留来源精度；公开来源没有坐标或多边形时保持为空，不能凭地图目测填充。

### `weather_features`

粒度：每个天气点、自然季度和数据类型一行。当前508026快照使用`data_kind=ex_post_reanalysis_era5`，保存Open-Meteo返回的ERA5网格中心、模型参数、抓取日和完整日历覆盖。该表适合解释性研究，不包含forecast issue time，不能用于严格交易回测。

### `watershed_proxy_metadata`

粒度：每个自动划分候选流域一行。保存请求和吸附后的出水口、自动面积、官方披露面积、面积偏差、GeoJSON顶点数、SHA-256、来源、许可和质量状态。当前状态`experimental_area_mismatch`表示只能用于敏感性分析，不能冒充官方边界。

### `catchment_grid_weights`

粒度：候选流域内每个固定ERA5网格一行。`area_weight`由0.01度规则格点落入候选多边形后近似分配，1783个流域内落点映射为8个网格；权重必须为正且合计为1。构建时会从GeoJSON重算并逐格核对，该权重仍继承候选流域的不确定性。

### `catchment_weather_features`

粒度：每个候选流域和自然季度一行。`data_kind=ex_post_reanalysis_era5_area_weighted_candidate`明确表示它既是事后再分析，又依赖实验流域。当前覆盖8个网格和2013—2022年完整季度。

### `fixed_lead_weather_forecast`

粒度：每个天气点、自然季度、模型和固定提前期一行。当前使用`gfs_global`的`precipitation_previous_day1`，即每个有效小时取提前24小时的预测。`forecast_hours`必须等于季度日历小时数。模型运行仍有计算发布延迟，季度合计也只有到期末才完整可知。

### `asset_events`

粒度：每项会改变资产边界或经营可比性的事件一行。当前覆盖扩募购入资产、外部电网停机和电价机制变化。只知道月份而不知道具体日期时，必须保存`date_precision=month`，不能虚构日级起止时间。

### `panel_quality_reviews`

粒度：每条纵向面板实际使用的来源文档一行。主键：`panel_name + source_url`。

`single_pass`表示已逐期对照正式报告完成一次人工转录复核；`double_checked`表示又与独立维护的数据产品交叉核对。复核台账记录`reviewed_at`和备注，但不会自动改变来源文档的`verification_status`。独立双人复核尚未完成时，不能把`single_pass`包装成最终正确。

纵向面板的`source_note`还承担重要口径说明：交割后的短季度、只披露两位小数、暂估电费、整数利用小时以及税基均必须显式保留。单位换算只能改变尺度，不能恢复报告没有给出的精度。

### `panel_annual_reconciliations`

粒度：每项资产、财年和指标一行。主键：`symbol + asset_id + fiscal_year + metric`。

该表把同一财年的最新季度版本按`sum`或以结算电量／燃料用量加权的平均值重新聚合，再与正式年报值比较。状态分为：

- `exact`：季度聚合与年报一致；
- `within_rounding`：差异可以由季度报告的万千瓦时、0.01亿千瓦时、0.01亿元等披露精度解释；
- `annual_true_up`：年报相对季度暂估发生调整，但没有证据把差额可靠分配到某个季度。
- `basis_difference`：季度和年报使用同名指标，但定义、计量时点或结算基础不同，不能直接覆盖。

`annual_true_up`和`basis_difference`都不能直接覆盖任一季度。只有后续公告明确给出季度归属或统一口径时，才能新增对应的point-in-time修订版本。

### `distributions`

粒度：每只证券每个除息事件一行。主键：`symbol + ex_date`。

每份分派金额必须来自正式收益分配公告。公告日决定信息时点，除息日决定持有收益归属，两者不可混用。

### `energy_feature_definitions`

粒度：每只进入能源横截面的证券一行。定义主经营指标、聚合方式、稳定资产ID集合和同比滞后期。508096只登记两项首发光伏资产，避免扩募水电在2025Q4突然改变历史组合边界。

### `energy_point_in_time_features`

粒度：每只证券每个可同比季度一行。当前值和四季度前值都从当次公告日有效的观测版本读取，`current_observation_ids`和`lag_observation_ids`保存完整血缘。主要字段：

| 字段 | 含义 |
|---|---|
| `operating_yoy_pct` | 稳定资产范围主指标的四季度同比 |
| `expected_yoy_pct` | 该证券此前已经公布同比的扩展均值 |
| `operating_surprise_pct` | 同比减去历史预期；不是分析师一致预期 |
| `publication_date` | 当前季度所有登记资产指标均已公开的日期 |
| `lag_value_as_of_publication` | 当次公告日可见的四季度前版本值 |
| `lineage_quality_status` | 当前值与同比基数是否全部连接到已人工核验来源 |

### `energy_cross_section_signals`

粒度：每个季度每只符合条件的能源证券一行。只有至少3只证券拥有非空surprise时才形成横截面；`decision_date`取当季入选报告最晚发布日期，`selected=true`仅标记最高分证券，不包含空头。

### `phase2_market_snapshots`

能源证券快照粒度为每只证券每个交易日一行，使用东方财富后复权参数并保存抓取时间；932047快照来自中证指数官网，`index_kind=total_return`。后复权序列只能在保存的快照内复现，未来刷新可能因新增分派改变历史价格尺度，因此不得静默覆盖研究版本。

### `phase2_strategy_events`

粒度：每个季度横截面每只证券一行。组合持有期截至下一次再平衡；rank IC固定使用20个共同交易日的前瞻收益，避免公告间隔不同或最后一期尚未结束造成标签长度不一致。

## 数据产品

数据库构建命令会生成：

- `operating_observation_versions.csv`：完整版本历史；
- `core_metric_coverage.csv`：按资产类型核心要求生成的覆盖矩阵；
- `operating_observations_as_of.csv`：指定历史日期的可见信息快照。
- `508026_prelisting_operating_metrics.csv`：上市前年度／年初至今经营历史；
- `508026_hydrology_mapping.csv`：水文实体关系；
- `508026_quarterly_weather_reanalysis.csv`：固定ERA5季度天气快照；
- `508026_prelisting_annual_weather_panel.csv`：完整年度经营指标和点位天气连接表。
- `508026_watershed_candidate.geojson`及元数据：实验流域边界、指纹和质量状态；
- `508026_catchment_grid_weights.csv`：8个ERA5面积近似权重；
- `508026_quarterly_catchment_weather_reanalysis.csv`：候选流域季度天气；
- `508026_quarterly_weather_forecast_lead24.csv`：固定GFS提前24小时历史预报；
- `508026_annual_model_panel.csv`：年度经营与两种天气代理连接表；
- `508026_annual_model_predictions.csv`及汇总：严格扩展窗口解释模型结果。
- `phase2_energy_point_in_time_features.csv`：四只能源REIT的35条PIT同比特征；
- `phase2_energy_cross_section_signals.csv`：8个季度、28条横截面排名；
- `phase2_energy_strategy_events.csv`：固定20交易日前瞻收益及事件持有收益；
- `phase2_energy_strategy_summary.csv`：含佣金、现金收益和两个基准的组合汇总。

Phase 1数据库命令导出的文件属于可重复生成分析数据，默认不提交仓库。Phase 2四张小型派生表随真实行情快照提交，作为当前负结果的精确研究版本；都可以由`python -m creit_quant.phase2`离线重建。
