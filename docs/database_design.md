# 研究数据库设计

## 当前结论

下一阶段最值得投入的不是把 CSV 换成数据库服务器，而是先把数据关系、口径和版本规则固定下来。当前数据量很小，CSV + pandas 更便于审阅和版本控制；等全市场面板形成后，再无损迁移到 Parquet／DuckDB。

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
| `panel_quality_reviews` | `data/samples/panel_quality_reviews.csv` | 纵向面板来源的人工复核状态、日期和备注 |
| `panel_annual_reconciliations` | `data/samples/panel_annual_reconciliations.csv` | 季度聚合与正式年报的差异、原因和处理状态 |
| `distributions` | `data/samples/508026_distributions.csv` | 除息日、每份分派和公告来源 |

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

当前508026审计结果为1项底层资产、36条上市后季度观测、55条上市前观测、14份来源文档和2条现金分派；14份文档都已人工核验。另有4条水文关系和54季度固定ERA5天气。全局指标字典为29项，指标数量不等同于单只试点实际使用字段数。

全市场观察层已保存2026-08-28快照，共94只证券。该快照来自 AKShare／东方财富行情源，只表示该日被数据源观察到，不能直接提供真实上市日期或历史退市状态。当前人工核验覆盖层有9只，待复核分类仍单独保留。沪深官方公告目录共8,151条，覆盖全部94只证券，并发现覆盖81只的1,131条定期报告候选。候选目录不会自动升级为正式来源登记。数据库已有20条跨资产规范种子、39条能源横截面观测，以及508028、508096、180401合计307条能源纵向观测；三条面板实际使用的43份季度／年度来源都进入复核台账。尚未解析的报告保持元数据核验状态，缺失值没有估算填补。最新状态见 [数据库当前状态](database_status.md)。

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

当前131份已登记来源文档已经记录抓取时间、SHA-256、内容类型、字节数和抓取状态。更正关系字段已经实现并具备校验，但508026早期被更正的原始报告尚未找到，因此不能伪造一条父版本关系。

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

508026已经登记坝址以上1642平方公里集水区、九龙河和溪古水库关系，但没有公开流域多边形，因此当前ERA5快照仍只是电站点位代理。默认best-match天气曾出现跨期模型切换，正式快照现已固定`era5`；这解决模型一致性，不解决空间代表性。

### 6. 最后再升级存储引擎

当数据扩展到全市场、日频天气和多版本公告后，建议：

- CSV 继续作为小型人工维护参考表；
- Parquet 保存大规模观测面板；
- DuckDB 负责本地分析和质量检查；
- 不引入需要长期运维的数据库服务。

## 最近可执行里程碑

先完成全市场证券主表和公告覆盖清单，然后选取水电、高速公路、产业园／物流各 2—3 只 REIT，建立连续季度指标覆盖矩阵。只有在这一层稳定后，再扩大天气或宏观特征，能避免另类数据领先于基本面主表建设。
