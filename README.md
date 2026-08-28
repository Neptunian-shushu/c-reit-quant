# 中国公募 REITs 量化研究

本项目以“先验证数据，再建立模型”为原则，研究中国公募 REITs 是否适合结合市场行情、底层资产经营披露和另类数据开展系统化量化研究。

## 当前状态

**Phase 0：数据可得性验证已完成。** 公开数据总体足以支持项目继续推进。行情获取不是主要难点；真正有研究价值、也最耗工程工作的部分，是把不同 REIT、不同资产类型和不同格式公告中的经营指标，整理成来源可追溯、时间口径一致的历史面板。

**Phase 1：508026 水电试点已完成第一轮覆盖审计。** 仓库目前收录了 2024Q2 至 2026Q1 的 8 个连续季度、4 项核心经营指标：发电量、利用小时、结算电量和不含税结算电价。资产坐标和 Open-Meteo 季度天气连接管线也已建立。

现阶段结论是：水电试点的数据链路可行，但 8 个季度仍低于项目设置的 12 季度最小建模门槛，因此暂不拟合 nowcast 模型，也不报告缺乏统计意义的预测结果。

**探索性策略已经得到首个结果。** 策略严格保持纯多头：发电量同比为正时持有 508026，否则持有现金；932047 只作为业绩基准。按 10 万元本金、买卖双向各万一佣金、每笔最低 5 元、现金年化收益 1.5% 计算，2025-07-22 至 2026-08-27 策略收益约 **-5.36%**；同期 508026 含分派且扣除买入佣金为 **-6.42%**，932047 全收益基准为 **-12.35%**。策略略好于买入持有并显著好于基准，但只有 4 个事件，仍不能视为 alpha 证据。详见 [初步策略结果](docs/phase1_strategy_results.md)。

**研究数据库已建立第一版关系层。** 当前把证券、底层资产、指标定义、资产类型要求、公告来源、经营观测和现金分派拆成独立表，并能离线检查主外键、规范单位、公告时点和来源覆盖。经营观测可构建为带生效区间与修订链的 point-in-time 版本，并按指定历史日期生成当时可见快照。508026 现有 32 条经营观测都能追溯到已人工核验的来源文档。设计与扩展顺序见 [研究数据库设计](docs/database_design.md)，字段约定见 [数据字典](docs/data_dictionary.md)。

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
│   │   └── metric_definitions.csv
│   └── samples/
│       ├── phase0_operating_metrics.csv
│       ├── reit_master.csv
│       ├── 508026_asset_metadata.csv
│       ├── 508026_distributions.csv
│       ├── 508026_quarterly_operating_metrics.csv
│       └── 508026_source_documents.csv
├── docs/
│   ├── database_design.md
│   ├── data_dictionary.md
│   ├── data_availability.md
│   ├── phase0_findings.md
│   ├── phase1_hydropower_findings.md
│   ├── phase1_strategy_results.md
│   └── research_plan.md
├── scripts/
│   ├── run_phase0.py
│   ├── run_phase1.py
│   ├── run_phase1_database.py
│   └── run_phase1_strategy.py
├── src/creit_quant/
│   ├── database.py
│   ├── hydropower.py
│   ├── market.py
│   ├── phase0.py
│   ├── phase1.py
│   ├── phase1_database.py
│   ├── phase1_strategy.py
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
- 当前报告解析器只是关键词／正则候选提取框架，并未解决 PDF 版面、表格重建、OCR、单位统一和人工复核。
- Phase 0 样本证明经营数据存在，并不等于已有完整全市场历史面板。
- 508026 目前只有 8 个连续季度，尚不足以支持可靠的季度预测模型。
- 首个纯多头经营披露策略仅有 4 个同比事件；虽跑赢基准，但样本不足以证明 alpha。
- 当前天气映射是单一电站点位；正式水文模型需要上游流域边界、面雨量以及梯级调度等信息。
