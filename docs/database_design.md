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
| `operating_metrics` | `data/samples/508026_quarterly_operating_metrics.csv` | long-format 经营观测及其发布时间、来源和原口径备注 |
| `distributions` | `data/samples/508026_distributions.csv` | 除息日、每份分派和公告来源 |

运行 `python -m creit_quant.phase1_database` 会检查：

- 所有证券和资产键都能连接；
- 每个经营指标都已登记到指标字典；
- 数据单位与规范单位一致；
- 每条经营观测和分派都能连接到已登记公告；
- 报告发布日期不早于报告期末，分派公告不晚于除息日。
- 按资产类型核心要求生成“资产 × 季度 × 指标”覆盖矩阵；
- 为每条经营观测生成稳定 ID、来源文档 ID、生效区间和修订关系；
- 按任意历史日期恢复当时可见的 point-in-time 快照。

当前 508026 审计结果为 1 只证券、1 项底层资产、19 项规范指标、32 条经营观测、10 份来源文档和 2 条现金分派；10 份文档都已人工核验。

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

### 3. 分开原始候选、核验值和修订值

解析器输出不应直接覆盖正式面板。建议形成三层：

`raw candidate → reviewed observation → point-in-time snapshot`

当前构建层已生成 `observation_id`、`document_id`、`raw_value`、`raw_unit`、`valid_from`、`valid_to`、`supersedes_observation_id` 和 `quality_status`。下一步仍需在解析入库时增加 `normalization_rule`、页码、原始文本位置和复核记录。这样早期暂估电量被后续报告修订时，既能得到最新正确值，也能复现历史交易时点实际已知值。

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

### 6. 最后再升级存储引擎

当数据扩展到全市场、日频天气和多版本公告后，建议：

- CSV 继续作为小型人工维护参考表；
- Parquet 保存大规模观测面板；
- DuckDB 负责本地分析和质量检查；
- 不引入需要长期运维的数据库服务。

## 最近可执行里程碑

先完成全市场证券主表和公告覆盖清单，然后选取水电、高速公路、产业园／物流各 2—3 只 REIT，建立连续季度指标覆盖矩阵。只有在这一层稳定后，再扩大天气或宏观特征，能避免另类数据领先于基本面主表建设。
