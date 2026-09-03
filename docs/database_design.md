# 研究数据库设计

## 当前结论

下一阶段最值得投入的不是把 CSV 换成数据库服务器，而是先把数据关系、口径和版本规则固定下来。当前数据量很小，CSV + pandas 更便于审阅和版本控制；等全市场面板形成后，再无损迁移到 Parquet／DuckDB。Phase 4已增加基金份额、季度可供分配金额、年末NAV、实际DPU和不复权估值价格时点层。

第一版关系层已经覆盖：

| 逻辑表 | 当前文件 | 作用 |
|---|---|---|
| `reit_master` | `data/samples/reit_master.csv` | 证券代码、名称、交易所、上市日、资产类型和状态 |
| `asset_master` | `data/samples/508026_asset_metadata.csv` | 底层资产、容量、位置、坐标来源和天气映射说明 |
| `metric_definitions` | `data/reference/metric_definitions.csv` | 跨资产类型的规范指标名、单位和频率 |
| `asset_type_metric_requirements` | `data/reference/asset_type_metric_requirements.csv` | 各资产类型的核心与可选指标要求 |
| `source_documents` | `data/samples/508026_source_documents.csv` | 公告类型、报告期、发布日期、URL 和核验状态 |
| `announcement_catalog` | `data/snapshots/reit_announcement_catalog.csv` | 沪深交易所官方公告元数据和规则分类候选，不等同于已核验来源 |
| `operating_metrics` | `data/samples/508026_quarterly_operating_metrics.csv` | long-format 经营观测及其发布时间、来源和原口径备注 |
| `prelisting_operating_metrics` | `data/samples/508026_prelisting_operating_metrics.csv` | IPO材料披露的年度／年初至今历史，保留真实公开可用日 |
| `hydrology_mapping` | `data/samples/508026_hydrology_mapping.csv` | 电站、集水区、河流和上游调节水库关系及来源精度 |
| `weather_features` | `data/samples/508026_quarterly_weather_reanalysis.csv` | 固定ERA5模型的点位季度再分析天气，不是历史预报 |
| `watershed_proxy` | `data/samples/508026_watershed_candidate.geojson` | MERIT自动候选流域；保存指纹、许可和面积误差，不能冒充官方边界 |
| `catchment_grid_weights` | `data/samples/508026_catchment_grid_weights.csv` | 候选流域映射到8个ERA5网格的面积近似权重 |
| `catchment_weather_features` | `data/samples/508026_quarterly_catchment_weather_reanalysis.csv` | 候选流域2013—2022面积加权再分析天气 |
| `fixed_lead_weather_forecast` | `data/samples/508026_quarterly_weather_forecast_lead24.csv` | GFS global固定提前24小时历史预报时点层 |
| `panel_quality_reviews` | `data/samples/panel_quality_reviews.csv` | 纵向面板来源的人工复核状态、日期和备注 |
| `panel_annual_reconciliations` | `data/samples/panel_annual_reconciliations.csv` | 季度聚合与正式年报的差异、原因和处理状态 |
| `distributions` | `data/samples/508026_distributions.csv` | 除息日、每份分派和公告来源 |
| `energy_feature_definitions` | `data/reference/energy_feature_definitions.csv` | 证券主指标、稳定资产范围和同比口径 |
| `energy_point_in_time_features` | `data/samples/phase2_energy_point_in_time_features.csv` | 公告日可见版本生成的同比及经营surprise |
| `energy_cross_section_signals` | `data/samples/phase2_energy_cross_section_signals.csv` | 等待当季报告到齐后的纯多头排名 |
| `operating_feature_definitions` | `data/reference/operating_feature_definitions.csv` | 八只证券的主指标、稳定资产范围和同比口径 |
| `phase3_asset_master` | `data/samples/phase3_asset_master.csv` | 两项高速和两项物流的稳定研究资产范围 |
| `phase3_asset_events` | `data/samples/phase3_asset_events.csv` | 物流扩募及其已知日期精度 |
| `phase3_operating_features` | `data/samples/phase3_operating_point_in_time_features.csv` | 跨能源、高速、物流的PIT同比与经营surprise |
| `phase3_announcement_events` | `data/samples/phase3_announcement_event_study.csv` | 真实公告日后的20／60交易日收益与基准超额收益 |
| `phase2_market_snapshots` | `data/snapshots/phase2_*.csv` | 带来源和抓取时点的个券后复权及官方全收益指数 |

能源扩面另使用`energy_asset_master.csv`、`energy_operating_metrics.csv`和`energy_source_documents.csv`；508028、508096和180401的连续时间序列分别单独维护，避免把单期横截面种子误认为完整历史面板。

运行 `python -m creit_quant.phase1_database` 会检查：

- 所有证券和资产键都能连接；
- 每个经营指标都已登记到指标字典；
- 数据单位与规范单位一致；
- 每条经营观测和分派都能连接到已登记公告；
- 报告发布日期不早于报告期末，分派公告不晚于除息日。
- 按资产类型核心要求生成“资产 × 季度 × 指标”覆盖矩阵；
- 为每条经营观测生成稳定 ID、来源文档 ID、生效区间和修订关系；
- 按任意历史日期恢复当时可见的 point-in-time 快照。

当前508026审计结果为1项底层资产、36条上市后季度观测、55条上市前观测、14份来源文档和2条现金分派；14份文档都已人工核验。另有4条水文关系、54季度固定ERA5点位天气、40季度候选流域天气和9季度固定提前期预报。全局指标字典为29项，指标数量不等同于单只试点实际使用字段数。

全市场观察层已保存2026-08-28快照，共94只证券。该快照来自 AKShare／东方财富行情源，只表示该日被数据源观察到，不能直接提供真实上市日期或历史退市状态。当前人工核验覆盖层有11只，待复核分类仍单独保留。沪深官方公告目录共8,151条，覆盖全部94只证券，并发现覆盖81只的1,131条定期报告候选。候选目录不会自动升级为正式来源登记。数据库除能源纵向面板外，已新增两只高速和两只物流共110条季度观测；Phase 4又为8只主样本新增343条基金指标和70次实际分派。机器抽取与人工核验状态严格分开，缺失值没有估算填补。最新状态见 [数据库当前状态](database_status.md)。

## 数据库完善优先级

### 1. 先做全市场主数据

建立全市场 `reit_master` 和 `asset_master`，保留上市、扩募、资产购入／出售、基金更名和终止上市的生效日期。不能用今天的证券或资产清单回填历史，否则会产生幸存者偏差和资产边界错配。

### 2. 建立公告登记与血缘

每份定期报告、临时公告和收益分配公告应先进入 `source_documents`，再提取数字。后续增加：

- 抓取时间和文件哈希；
- 原公告、补充公告、更正稿之间的替代关系；
- PDF 页码／表格位置；
- 解析器版本和人工核验人／时间。

仓库不提交大型 PDF，但应保存官方 URL、哈希和结构化提取证据，保证数据可复核。

当前公告发现层已经同时接入上交所基金公告接口和深交所 REIT 信息披露接口。目录记录一律标记为 `unreviewed`；分类规则会排除摘要、审计／评估报告、提示性公告和更正公告，并把更正稿单独标记。人工确认报告身份和口径后，才可写入 `source_documents`。

当前三套来源登记表共159行，已经记录抓取时间、SHA-256、内容类型、字节数和抓取状态。Phase 3新增的28份深交所季度报告均完成指标人工核验；更正关系字段已经实现并具备校验，但508026早期被更正的原始报告尚未找到，因此不能伪造一条父版本关系。

### 3. 分开原始候选、核验值和修订值

解析器输出不应直接覆盖正式面板。建议形成三层：

`raw candidate → reviewed observation → point-in-time snapshot`

当前构建层已生成 `observation_id`、`document_id`、`raw_value`、`raw_unit`、`valid_from`、`valid_to`、`supersedes_observation_id` 和 `quality_status`，并新增来源级面板复核台账。下一步仍需在解析入库时增加 `normalization_rule`、结构化页码／表格位置和独立复核人字段。这样早期暂估电量被后续报告修订时，既能得到最新正确值，也能复现历史交易时点实际已知值。

### 4. 做指标覆盖矩阵

按“证券 × 报告期 × 指标”生成覆盖审计，区分未披露、不可比、未解析和真正缺失。先把三类资产做深：

- 水电／新能源：发电量、利用小时、结算电量、电价；
- 高速公路：总车流、客车／货车流量、通行费收入；
- 产业园／物流：出租率、可出租面积、租金和收缴率。

覆盖矩阵会直接告诉我们哪些标的适合时间序列研究，哪些指标适合横截面研究。

当前可以运行：

```bash
python -m creit_quant.phase1_database \
  --out-dir data/processed/phase1_database \
  --as-of 2025-07-31
```

该命令离线生成完整观测版本表、核心指标覆盖表，以及指定日期当时可见的观测快照。输出属于可再生数据产品，默认不提交 Git。

### 5. 加强地理与另类数据连接

资产表不能只有一个经纬度。水电需要上游流域多边形和梯级关系；高速公路需要路段与收费站；园区和物流需要园区边界。天气表还应保存数据类型、网格／站点、预测发布时间、有效时间、提前期和数据版本，明确区分再分析与历史预报。

508026已经登记坝址以上1642平方公里集水区、九龙河和溪古水库关系。MERIT自动划分候选流域及8网格面积权重已加入研究层，但1930平方公里自动面积较正式披露高17.54%，所以状态固定为实验代理。默认best-match天气曾出现跨期模型切换，长期快照固定`era5`；可交易时点层另用`gfs_global`的`_previous_day1`固定24小时时距。前者解决长期一致性，后者解决固定提前期，两者都没有解决准确流域边界和水库调度。

### 6. 最后再升级存储引擎

当数据扩展到全市场、日频天气和多版本公告后，建议：

- CSV 继续作为小型人工维护参考表；
- Parquet 保存大规模观测面板；
- DuckDB 负责本地分析和质量检查；
- 不引入需要长期运维的数据库服务。

## Phase 3之后的可执行里程碑

能源、两只高速和两只物流的PIT横截面已经证明版本血缘、扩募边界、公告后交易日期与市场行情可以连接。Phase 2的P/NAV和分派收益率仍因数据闸门失败没有强行计算。下一步继续数据库优先：

1. 为四只能源REIT补齐正式分派表并与后复权收益交叉验证；
2. 在全市场主表加入基金份额、市值、NAV、分派和扩募生效历史；
3. 对Phase 3的110条非能源观测执行独立二次复核，并增加PDF页码／表格定位字段；
4. 连续保存至少12个月末universe快照，并建立历史上市／终止／扩募状态；
5. 完成后再在新增样本测试分派收益率、P/NAV、月频20日动量及经营surprise的联合排序。
