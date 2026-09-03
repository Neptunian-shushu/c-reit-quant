# 中国公募 REITs 量化研究

本项目以“先验证数据，再建立模型”为原则，研究中国公募 REITs 是否适合结合市场行情、底层资产经营披露和另类数据开展系统化量化研究。

## 当前状态

**Phase 0：数据可得性验证已完成。** 公开数据总体足以支持项目继续推进。行情获取不是主要难点；真正有研究价值、也最耗工程工作的部分，是把不同 REIT、不同资产类型和不同格式公告中的经营指标，整理成来源可追溯、时间口径一致的历史面板。

**Phase 1：508026 水电研究闭环已完成。** 仓库除2024Q2至2026Q2的9个连续季度、4项核心经营指标外，已从上交所正式招募说明书回填2013—2022年10个完整年度及2023年1—9月共55条上市前经营观测。天气层同时包含固定ERA5点位再分析、基于MERIT候选流域8个网格的面积加权再分析，以及覆盖9个上市后季度、19,704个有效小时的固定GFS提前24小时历史预报。

Phase 1的结论不是“模型有效”，而是完成了可证伪的研究。2018—2022年扩展窗口样本外检验中，历史均值基线MAE为3,783.36万千瓦时；候选流域降水OLS为4,578.56万千瓦时，单点降水OLS为6,049.89万千瓦时，均未战胜均值。自动划分流域面积为1,930平方公里，较正式披露的1,642平方公里高17.54%，因此仍只能作为实验代理。季度可交易nowcast只有9期，明确判定为未就绪。

**Phase 2A：能源REIT point-in-time横截面基线已完成。** 508026、508028、508096和180401形成35条同口径同比特征及2024Q3—2026Q2共8个季度横截面。每期等待全部入选证券公告后，在下一个共同交易日收盘做多经营surprise最高的1只证券，不做空；按10万元、双向各万一、每笔最低5元和现金年化1.5%计算，截至2026-09-02组合净收益为 **-5.01%**，同期能源等权为 **+4.53%**，932047全收益指数为 **+0.68%**。固定20交易日前瞻收益的平均rank IC为 **-0.4875**，8期均未出现正rank IC。简单经营surprise没有形成alpha证据，详见[Phase 2能源横截面结论](docs/phase2_energy_findings.md)。

**Phase 2B与Phase 2整体研究范围已完成，但策略未达到部署条件。** 已冻结2021-06-21至2026-09-02共50,863行全市场后复权行情；94只当前universe中88只有真实历史，6只明确无历史。月频20日动量top 20%纯多头组合在双向各万一、每笔最低5元和现金年化1.5%下净收益 **+16.39%**，同期当前名单可交易等权 **+0.83%**、932047全收益 **+3.45%**。但平均20日rank IC仅0.0496、朴素t值1.075，而且只有一个历史universe快照；资产类型、DPU、NAV和国债vintage闸门也全部未通过。该结果只登记为新增样本待验证候选，详见[Phase 2最终结论](docs/phase2_findings.md)。

**Phase 3：跨资产经营数据库与公告事件研究已完成，但策略不部署。** 新增180201、508018两只高速及180301、508056两只物流的110条人工核验季度经营观测，并与四只能源REIT合成73条PIT同比特征。2024Q3—2026Q2共有8个至少含6只证券的横截面；每期做多经营surprise最高2只，在双向各万一、每笔最低5元和现金年化1.5%下净收益 **+11.38%**，当期合资格证券等权 **+2.11%**、932047全收益 **+0.68%**。但平均20日rank IC仅 **0.02**、8期仅3期为正，历史universe仍只有一个快照，因此只保留为新增样本验证候选。详见[Phase 3最终结论](docs/phase3_findings.md)。

**Phase 4：基金时点数据库与联合模型研究闭环已完成，但策略不部署。** 8只主样本新增343条基金指标、28条年末NAV、70次实际DPU和8,098行不复权行情。固定联合模型等权合成经营surprise、TTM DPU yield、NAV/price和20日含分派动量；top-2在2024-10-28至2026-09-02净收益 **+7.60%**，合资格等权 **+1.54%**、932047全收益 **+0.68%**。但平均20日rank IC仅 **0.025**，只有8期，且6份扫描分派公告、真实历史universe和前瞻样本外闸门未通过。详见[Phase 4结论](docs/phase4_findings.md)。

**探索性策略已按2026Q2数据重算。** 策略严格保持纯多头：发电量同比为正时持有508026，否则持有现金；932047只作为业绩基准。按10万元本金、买卖双向各万一佣金、每笔最低5元、现金年化收益1.5%计算，2025-07-22至2026-08-28策略收益约 **-8.40%**；同期508026含分派且扣除买入佣金为 **-5.83%**，932047全收益基准为 **-12.67%**。策略跑赢基准但落后买入持有，5个事件中只有2次仓位选择有利，进一步说明发电量同比符号本身不是可靠 alpha。详见 [初步策略结果](docs/phase1_strategy_results.md)。

**研究数据库已形成能源、高速、物流和基金时点层。** 2026-08-28快照观察到94只 C-REIT，沪深官方公告目录收录8,151条元数据并覆盖94／94只证券。四只能源与四只非能源REIT合计形成453条经营观测和73条跨资产PIT特征；Phase 4另形成343条基金指标和70次实际DPU。三套经营来源登记表共159行且均有SHA-256；基金时点层当前是正式PDF机器抽取，尚未冒充人工核验。仓库不保存原始PDF。详见[数据库当前状态](docs/database_status.md)、[Phase 4结论](docs/phase4_findings.md)和[数据字典](docs/data_dictionary.md)。

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
- 招募说明书披露的2013—2022年度上市前经营面板，并显式标记IPO披露可用时间；
- 五一桥水电站 1—5 号机组的资产元数据和公开坐标；
- 电站、坝址以上集水区、九龙河和溪古水库的水文关系；
- 固定ERA5模型的日频再分析天气向自然季度聚合；
- 带文件指纹和许可说明的MERIT候选流域、8个ERA5面积权重网格及完整年度天气；
- 固定GFS global、提前24小时的历史预报时点层；
- 经营指标与天气的季度连接；
- 2018—2022扩展窗口年度基线比较及可部署闸门。

Phase 1研究闭环已经完成，但没有通过可部署模型闸门。候选流域的面积误差、缺失的真实来水和水库调度、过短的上市后季度历史仍须在后续数据更新中解决。详见 [Phase 1 水电试点结论](docs/phase1_hydropower_findings.md)。

## Phase 2A：能源经营surprise横截面

当前横截面只使用稳定资产范围：508026五一桥水电、508028滨海北海上风电、508096两项首发光伏和180401东部燃气电厂。主指标分别采用发电量或结算电量；先计算四季度同比，再减去该证券此前已公布同比的扩展均值。四季度前值严格按当次公告日有效版本读取。

每期在全部入选证券报告公布后统一决策，下一个共同交易日收盘换仓，只持有最高surprise证券；能源等权组合和932047全收益指数用于比较。当前负结果说明该简单定义不值得继续调参，但PIT数据库、横截面事件和成本引擎可以复用于后续估值及更合理的经营预期研究。

## Phase 2B：全市场价格与流动性因子

对当前universe中有历史行情的88只证券构建20／60日动量、5日反转、成交额、Amihud非流动性、已实现波动率和四维组合。信号在周末／月末收盘后形成，下一交易日收盘建仓，只做多top组；932047仅为全收益基准。

20日动量的月频结果在top 10%／20%／30%和最低佣金敏感性下方向一致，但统计显著性和历史universe条件不足。Phase 2到此关闭，不继续在同一区间挑参。DPU、NAV和份额已在Phase 4的8只样本中补齐，后续只用新增季度复核固定候选。

## Phase 3：跨资产经营预期

稳定资产范围包括180201广河高速、508018嘉通高速、180301首发现代物流中心、508056扩募后十项物流资产，以及Phase 2的四只能源REIT。主指标采用车流量、出租率、发电量或结算电量；先计算四季度同比，再减去该证券此前已公布同比的扩展均值。

报告事件分别检验20／60交易日收益；季度组合等待至少6只证券报告到齐后，只做多surprise最高2只。当前正收益没有获得强rank IC或足够历史横截面支持，程序化闸门明确返回不可部署。后续只在新增季度复核固定规则。

## Phase 4：基金时点与联合模型

基金指标层严格区分季度“单位可供分配金额”和分派公告“实际DPU”。P/NAV与收益率估值使用不复权价格，总收益回测使用后复权价格。联合模型固定等权、纯多头top-2，不允许在旧区间继续优化权重。

Phase 4工程已完成，但`deployable=false`。从2026Q3起应前瞻冻结规则，至少追加4个新季度和12个月真实universe快照，再决定是否进入纸面跟踪。

## 快速开始

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

# Phase 0 数据可得性检查
python -m creit_quant.phase0
python -m creit_quant.phase0 --history-symbol 508026

# Phase 1 离线研究闭环、模型基线与部署闸门审计
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

# Phase 2能源PIT横截面；默认使用仓库中的真实行情快照
python -m creit_quant.phase2 \
  --out-dir data/processed/phase2_energy

# 联网刷新四只能源REIT后复权行情和932047官方全收益指数
python -m creit_quant.phase2 \
  --fetch-market \
  --replace-market-snapshot \
  --end-date 20260902

# Phase 2B离线重建全市场周／月频因子、纯多头回测和数据闸门
python -m creit_quant.phase2_market \
  --out-dir data/processed/phase2_market

# Phase 3离线重建跨资产PIT特征、公告事件和纯多头回测
python -m creit_quant.phase3 \
  --out-dir data/processed/phase3

# Phase 4离线重建基金时点联合信号、净成本回测和部署闸门
python -m creit_quant.phase4 \
  --out-dir data/processed/phase4

# 联网刷新全市场后复权行情；已有快照不会静默覆盖
python -m creit_quant.phase2_market \
  --fetch-market \
  --replace-market-snapshot \
  --end-date 20260902

# 联网获取固定ERA5再分析天气并生成本地连接面板
python -m creit_quant.phase1 \
  --fetch-weather \
  --weather-model era5 \
  --out data/processed/508026_hydropower_weather_panel.csv

# 联网重建固定GFS提前24小时历史预报季度快照
python -m creit_quant.phase1 \
  --fetch-fixed-lead \
  --fixed-lead-out data/processed/508026_weather_forecast_lead24.csv

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
│   │   ├── energy_feature_definitions.csv
│   │   ├── operating_feature_definitions.csv
│   │   ├── metric_definitions.csv
│   │   └── security_overrides.csv
│   ├── snapshots/
│   │   ├── phase2_932047_total_return.csv
│   │   ├── phase2_energy_adjusted_prices.csv
│   │   ├── phase2_full_market_adjusted_history.csv
│   │   ├── phase2_full_market_price_coverage.csv
│   │   ├── phase4_unadjusted_prices.csv
│   │   ├── reit_announcement_catalog.csv
│   │   └── reit_universe_history.csv
│   └── samples/
│       ├── phase0_operating_metrics.csv
│       ├── phase2_energy_cross_section_signals.csv
│       ├── phase2_energy_point_in_time_features.csv
│       ├── phase2_energy_strategy_events.csv
│       ├── phase2_energy_strategy_summary.csv
│       ├── phase2_market_factor_signals.csv
│       ├── phase2_market_factor_summary.csv
│       ├── phase2_market_factor_robustness.csv
│       ├── phase2_market_factor_selections.csv
│       ├── phase2_data_gates.csv
│       ├── phase3_asset_master.csv
│       ├── phase3_asset_events.csv
│       ├── phase3_operating_point_in_time_features.csv
│       ├── phase3_operating_cross_section_signals.csv
│       ├── phase3_announcement_event_study.csv
│       ├── phase3_strategy_summary.csv
│       ├── phase3_strategy_robustness.csv
│       ├── phase4_fund_fundamentals.csv
│       ├── phase4_distributions.csv
│       ├── phase4_joint_signals.csv
│       ├── phase4_strategy_summary.csv
│       ├── phase4_strategy_robustness.csv
│       ├── phase4_capacity.csv
│       ├── phase4_data_gates.csv
│       ├── 180201_quarterly_operating_metrics.csv
│       ├── 180301_quarterly_operating_metrics.csv
│       ├── 508018_quarterly_operating_metrics.csv
│       ├── 508056_quarterly_operating_metrics.csv
│       ├── reit_master.csv
│       ├── 508026_asset_metadata.csv
│       ├── 508026_distributions.csv
│       ├── 508026_hydrology_mapping.csv
│       ├── 508026_catchment_grid_weights.csv
│       ├── 508026_prelisting_operating_metrics.csv
│       ├── 508026_quarterly_catchment_weather_reanalysis.csv
│       ├── 508026_quarterly_operating_metrics.csv
│       ├── 508026_quarterly_weather_reanalysis.csv
│       ├── 508026_quarterly_weather_forecast_lead24.csv
│       ├── 508026_source_documents.csv
│       ├── 508026_watershed_candidate.geojson
│       ├── 508026_watershed_proxy_metadata.csv
│       ├── 508028_quarterly_operating_metrics.csv
│       ├── 508096_quarterly_operating_metrics.csv
│       ├── 180401_quarterly_operating_metrics.csv
│       ├── cross_asset_asset_master.csv
│       ├── cross_asset_operating_metrics.csv
│       ├── cross_asset_source_documents.csv
│       ├── energy_asset_master.csv
│       ├── energy_asset_events.csv
│       ├── energy_operating_metrics.csv
│       ├── energy_source_documents.csv
│       ├── panel_quality_reviews.csv
│       └── panel_annual_reconciliations.csv
├── docs/
│   ├── database_design.md
│   ├── database_status.md
│   ├── energy_database_findings.md
│   ├── data_dictionary.md
│   ├── data_availability.md
│   ├── phase0_findings.md
│   ├── phase1_hydropower_findings.md
│   ├── phase1_strategy_results.md
│   ├── phase2_energy_findings.md
│   ├── phase2_findings.md
│   ├── phase3_findings.md
│   ├── phase4_findings.md
│   └── research_plan.md
├── scripts/
│   ├── run_phase0.py
│   ├── run_phase1.py
│   ├── run_phase1_announcements.py
│   ├── run_phase1_database.py
│   ├── run_phase1_documents.py
│   ├── run_phase1_quality.py
│   ├── run_phase1_strategy.py
│   ├── run_phase1_universe.py
│   ├── run_phase2.py
│   ├── run_phase2_market.py
│   ├── run_phase3.py
│   ├── run_phase4.py
│   ├── build_phase4_fundamentals.py
│   └── fetch_phase4_unadjusted_prices.py
├── src/creit_quant/
│   ├── database.py
│   ├── announcements.py
│   ├── documents.py
│   ├── energy_research.py
│   ├── hydropower.py
│   ├── hydropower_model.py
│   ├── market.py
│   ├── market_factor_research.py
│   ├── operating_research.py
│   ├── master_data.py
│   ├── phase0.py
│   ├── phase1.py
│   ├── phase1_announcements.py
│   ├── phase1_database.py
│   ├── phase1_documents.py
│   ├── phase1_quality.py
│   ├── phase1_strategy.py
│   ├── phase1_universe.py
│   ├── phase2.py
│   ├── phase2_market.py
│   ├── phase3.py
│   ├── phase4.py
│   ├── phase4_research.py
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
- **固定提前期历史预报**：适合严格的可交易 nowcast 或回测；仍需考虑模型运行完成和发布延迟。

把再分析数据当成当时已知信息会产生 look-ahead bias（前视偏差）。未来的可交易研究必须保存公告发布时间、预测发布时间、有效时间和预测提前期。

## 已知限制

- AKShare 的 REIT 接口依赖非官方上游网页，字段和可用性可能变化。
- 当前全市场只有一个快照日，`first_observed_date` 不能当作上市日期；历史状态需持续追加快照。
- 全市场94只中仍有83只资产类型待人工核验；虽然81只已发现定期报告候选，目前只有8只进入正式来源登记和PIT研究，完成经营指标抽取的范围仍很小。当前纵向试点不等于全市场数据库已经完整。
- 当前报告解析器只是关键词／正则候选提取框架，并未解决 PDF 版面、表格重建、OCR、单位统一和人工复核。
- Phase 0 样本证明经营数据存在，并不等于已有完整全市场历史面板。
- Phase 1研究流程已经完成，但508026只有9个上市后连续季度，尚不足以支持可靠的季度预测模型。
- 纯多头经营披露策略只有5个同比事件，且落后508026买入持有，不支持稳定 alpha 假设。
- MERIT自动流域已经用于敏感性分析，但其1930平方公里面积较正式披露1642平方公里高17.54%，不能升级为官方边界；真实来水、溪古水库调度和检修仍缺失。
- 508028虽已有13季度发电量，但早期结算电量和利用小时缺失，报告内平均风速只有11期；508096在2024Q4前只稳定披露项目级结算电量和电价；180401在2024Q4前未形成完整发电指标表。早期转录仍待独立二次复核。
- 508096扩募水电的2025Q4观测只覆盖2025年12月27—31日，不能当作完整季度；光伏／水电按0.01亿千瓦时披露的数值也无法恢复更高精度。
- Phase 2全市场收益研究使用2026-08-28当前名单回看历史；仓库只有一个universe快照，结果存在幸存者偏差，不能作为部署证据。
- 当前94只证券中88只有历史行情，6只上游明确无历史；资产类型仅11只人工核验。DPU、NAV与基金份额时点面板只覆盖8只研究样本，尚未扩展到全市场。
- Phase 3跨资产结果只有8个季度，平均20日rank IC约0.02；正收益可能由少数持仓路径驱动，不构成可部署alpha证据。
- 508018早期通行费披露为不含税、后期标准表为含税清分口径，数据库没有强行拼接；PDF表格转录虽已逐项核验，仍应进行独立二次复核。
- Phase 4有6份508028分派公告为无文字层扫描PDF，已排除而非补值；413条基金指标／分派观测均待独立人工复核。联合模型只有8期且没有规则冻结后的前瞻样本外季度。
