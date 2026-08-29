# 中国公募 REITs 量化研究

本项目以“先验证数据，再建立模型”为原则，研究中国公募 REITs 是否适合结合市场行情、底层资产经营披露和另类数据开展系统化量化研究。

## 当前状态

**Phase 0：数据可得性验证已完成。** 公开数据总体足以支持项目继续推进。行情获取不是主要难点；真正有研究价值、也最耗工程工作的部分，是把不同 REIT、不同资产类型和不同格式公告中的经营指标，整理成来源可追溯、时间口径一致的历史面板。

**Phase 1：508026 水电试点已完成最新季度更新。** 仓库目前收录了2024Q2至2026Q2的9个连续季度、4项核心经营指标：发电量、利用小时、结算电量和不含税结算电价。资产坐标和 Open-Meteo 季度天气连接管线也已建立。

现阶段结论是：水电试点的数据链路可行，但9个季度仍低于项目设置的12季度最小建模门槛，因此暂不拟合 nowcast 模型，也不报告缺乏统计意义的预测结果。

**探索性策略已按2026Q2数据重算。** 策略严格保持纯多头：发电量同比为正时持有508026，否则持有现金；932047只作为业绩基准。按10万元本金、买卖双向各万一佣金、每笔最低5元、现金年化收益1.5%计算，2025-07-22至2026-08-28策略收益约 **-8.40%**；同期508026含分派且扣除买入佣金为 **-5.83%**，932047全收益基准为 **-12.67%**。策略跑赢基准但落后买入持有，5个事件中只有2次仓位选择有利，进一步说明发电量同比符号本身不是可靠 alpha。详见 [初步策略结果](docs/phase1_strategy_results.md)。

**研究数据库已进入主线建设。** 2026-08-28的 AKShare／东方财富快照观察到94只 C-REIT，其中9只证券名称和资产类型已有一手来源人工核验。沪深官方公告目录已收录8,151条元数据，覆盖94／94只证券。当前508026有36条连续季度经营观测；三类资产规范种子有20条真实观测。新增能源扩面覆盖3只REIT、6项底层资产和39条2026Q2经营观测；508028海上风电另形成2023Q2—2026Q2连续13季度、86条经营观测。正式登记来源文档增至128份且均已计算 SHA-256，其中能源类61份。仓库不保存原始 PDF。详见 [数据库当前状态](docs/database_status.md)、[能源扩面结论](docs/energy_database_findings.md)、[研究数据库设计](docs/database_design.md)和[数据字典](docs/data_dictionary.md)。

## 核心研究问题

1. C-REIT 市场是否已经足以支持一定规模的横截面研究？
2. DPU、出租率、车流量、发电量、租金和 NOI 等指标能否形成稳定历史面板？
3. 天气、节假日、物流、消费和区域宏观数据能否改善经营现金流或 DPU 预测？
4. 基本面和另类数据的“超预期”部分是否能预测 REIT 后续收益？

## 数据可得性结论

| 数据 | 状态 | 主要判断 |
|---|---|---|
| REIT 行情、成交量 | 绿色 | AKShare 可获取，但上游网页接口稳定性需要监控 |
| 交易所公告、定期报告 | 绿色 | 公开且可追溯，PDF 表格仍需解析和人工复核 |
| 天气、宏观数据 | 绿色 | 可编程获取；严格回测必须保存信息时点 |
| 标准化经营基本面 | 黄色 | 数据真实存在，但名称、单位、期间和资产口径不统一 |
| 高速公路历史交通 | 黄色 | 报告内有实际数据，免费外部资产级长历史较弱 |
| 区域级、资产级另类数据 | 黄色 | 需要资产地理信息和合理的空间聚合方法 |
| 免费历史商场客流、移动定位 | 红色／可选 | 通常为商业或专有数据，不作为首个 MVP 前提 |

更完整的审计见 [Phase 0 研究结论](docs/phase0_findings.md) 和 [数据可得性清单](docs/data_availability.md)。

## Phase 1：水电试点 508026

当前试点链路为：

`降雨 → 来水／水文 → 发电量 → 结算电量 → 收入 → 可供分配现金流／DPU`

已实现：

- 经公开定期报告逐条核验的季度 long-format 经营指标；
- 五一桥水电站 1—5 号机组的资产元数据和公开坐标；
- 日频再分析天气向自然季度聚合；
- 经营指标与天气的季度连接；
- 连续性、核心字段完整性和最小样本量检查。

当前点位降雨只能用于验证数据管线，不能替代上游流域面雨量、真实来水量、梯级调度和检修等变量。详见 [Phase 1 水电试点结论](docs/phase1_hydropower_findings.md)。

## 快速开始

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

# Phase 0 数据可得性检查
python -m creit_quant.phase0
python -m creit_quant.phase0 --history-symbol 508026

# Phase 1 离线季度覆盖审计
python -m creit_quant.phase1

# Phase 1 研究数据库关系与来源审计
python -m creit_quant.phase1_database

# 联网追加当日全市场 universe 快照
python -m creit_quant.phase1_universe

# 上游不可用时，从已保存快照离线重建待复核主表
python -m creit_quant.phase1_universe \
  --offline \
  --master-out data/processed/security_master_review.csv

# 联网更新沪深交易所官方公告候选目录；失败时不会伪造记录
python -m creit_quant.phase1_announcements

# 不联网，按最新分类规则重算已有公告目录
python -m creit_quant.phase1_announcements --offline

# 生成全市场公告覆盖和数据库质量队列
python -m creit_quant.phase1_quality \
  --out-dir data/processed/phase1_quality

# 仅补抓缺少哈希的公告；不保存 PDF
python -m creit_quant.phase1_documents --write

# 登记扩面试点的定期报告并计算哈希；未解析报告保持元数据核验状态
python -m creit_quant.phase1_documents \
  --registry data/samples/cross_asset_source_documents.csv \
  --discover-catalog data/snapshots/reit_announcement_catalog.csv \
  --symbols 508018 508056 \
  --write

# 登记能源标的报告序列并计算哈希
python -m creit_quant.phase1_documents \
  --registry data/samples/energy_source_documents.csv \
  --discover-catalog data/snapshots/reit_announcement_catalog.csv \
  --symbols 508028 508096 180401 \
  --write

# 导出规范版本表、核心指标覆盖表和 2025-07-31 历史快照
python -m creit_quant.phase1_database \
  --out-dir data/processed/phase1_database \
  --as-of 2025-07-31

# Phase 1 探索性发电量披露策略（需要联网行情）
python -m creit_quant.phase1_strategy \
  --end-date 20260828 \
  --capital 100000 \
  --commission-rate 0.0001 \
  --minimum-commission 5 \
  --cash-yield 0.015

# 联网获取再分析天气并生成本地连接面板
python -m creit_quant.phase1 \
  --fetch-weather \
  --out data/processed/508026_hydropower_weather_panel.csv

pytest
```

## 项目结构

```text
c-reit-quant/
├── configs/
│   └── data_sources.yaml
├── data/
│   ├── reference/
│   │   ├── asset_type_metric_requirements.csv
│   │   ├── metric_definitions.csv
│   │   └── security_overrides.csv
│   ├── snapshots/
│   │   ├── reit_announcement_catalog.csv
│   │   └── reit_universe_history.csv
│   └── samples/
│       ├── phase0_operating_metrics.csv
│       ├── reit_master.csv
│       ├── 508026_asset_metadata.csv
│       ├── 508026_distributions.csv
│       ├── 508026_quarterly_operating_metrics.csv
│       ├── 508026_source_documents.csv
│       ├── 508028_quarterly_operating_metrics.csv
│       ├── cross_asset_asset_master.csv
│       ├── cross_asset_operating_metrics.csv
│       ├── cross_asset_source_documents.csv
│       ├── energy_asset_master.csv
│       ├── energy_asset_events.csv
│       ├── energy_operating_metrics.csv
│       └── energy_source_documents.csv
├── docs/
│   ├── database_design.md
│   ├── database_status.md
│   ├── energy_database_findings.md
│   ├── data_dictionary.md
│   ├── data_availability.md
│   ├── phase0_findings.md
│   ├── phase1_hydropower_findings.md
│   ├── phase1_strategy_results.md
│   └── research_plan.md
├── scripts/
│   ├── run_phase0.py
│   ├── run_phase1.py
│   ├── run_phase1_announcements.py
│   ├── run_phase1_database.py
│   ├── run_phase1_documents.py
│   ├── run_phase1_quality.py
│   ├── run_phase1_strategy.py
│   └── run_phase1_universe.py
├── src/creit_quant/
│   ├── database.py
│   ├── announcements.py
│   ├── documents.py
│   ├── hydropower.py
│   ├── market.py
│   ├── master_data.py
│   ├── phase0.py
│   ├── phase1.py
│   ├── phase1_announcements.py
│   ├── phase1_database.py
│   ├── phase1_documents.py
│   ├── phase1_quality.py
│   ├── phase1_strategy.py
│   ├── phase1_universe.py
│   ├── quality.py
│   ├── report_parser.py
│   ├── schema.py
│   ├── strategy.py
│   └── weather.py
├── tests/
├── pyproject.toml
└── README.md
```

## 最重要的回测规则

必须区分：

- **事后再分析天气（reanalysis）**：适合解释已经实现的经营结果；
- **历史交易时点真实可得的天气预报**：适合严格的可交易 nowcast 或回测。

把再分析数据当成当时已知信息会产生 look-ahead bias（前视偏差）。未来的可交易研究必须保存公告发布时间、预测发布时间、有效时间和预测提前期。

## 已知限制

- AKShare 的 REIT 接口依赖非官方上游网页，字段和可用性可能变化。
- 当前全市场只有一个快照日，`first_observed_date` 不能当作上市日期；历史状态需持续追加快照。
- 全市场 94 只中仍有 85 只资产类型待人工核验；虽然81只已发现定期报告候选，目前只有6只进入正式来源登记，完成经营指标抽取的范围仍很小。
- 当前报告解析器只是关键词／正则候选提取框架，并未解决 PDF 版面、表格重建、OCR、单位统一和人工复核。
- Phase 0 样本证明经营数据存在，并不等于已有完整全市场历史面板。
- 508026目前只有9个连续季度，尚不足以支持可靠的季度预测模型。
- 纯多头经营披露策略只有5个同比事件，且落后508026买入持有，不支持稳定 alpha 假设。
- 当前天气映射是单一电站点位；正式水文模型需要上游流域边界、面雨量以及梯级调度等信息。
- 508028虽已有13季度发电量，但早期结算电量和利用小时缺失，报告内平均风速只有11期；早期转录仍待独立二次复核。
