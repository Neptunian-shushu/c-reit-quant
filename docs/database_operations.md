# 数据库维护流程

## 日常顺序

1. 追加当日实时universe快照；同日冲突会拒绝覆盖。
2. 增量更新沪深交易所公告目录。默认从每只证券最后公告日前7日开始，吸收迟到公告和修订。
3. 重建上市证据、已完成月末成员、Phase 4来源清单和独立复核队列。
4. 重建全市场资产类型证据、证券覆盖表和文档解析队列。
5. 增量抓取分派公告及年报基金事实；响应只在内存中转换，文档审计可断点恢复。
6. 仅对缺少哈希的官方URL联网计算SHA-256；响应不写入仓库。
7. 解析新报告后运行全量测试和各阶段离线重建。

```bash
python -m creit_quant.phase1_universe
python -m creit_quant.phase1_announcements
python -m creit_quant.phase4_database --fetch-missing-hashes
python -m creit_quant.full_market_distributions
python -m creit_quant.full_market_fundamentals
python -m creit_quant.phase4_database
python -m pytest -q
python -m creit_quant.phase4 --out-dir data/samples
```

分派程序默认复用`full_market_distribution_document_audit.csv`中的成功结果，只重试失败公告。上游限流时可先停止联网，并用以下命令验证事件表可离线重建：

```bash
python -m creit_quant.full_market_distributions --rebuild-from-audit
python -m creit_quant.full_market_fundamentals --rebuild-from-audit
```

年报程序依赖系统`pdftotext`（Poppler）。它只提取报告期末基金份额和账面每份NAV，显式排除公允价值参考净值。`--retry-parse-failures`只重试失败的上交所年报；深交所403应等待冷却或上游恢复后再重试。

`needs_ocr_or_visual_review`不得自动补值。`fetch_or_parse_failed`先区分HTTP限流和规则失败；深交所403应在冷却后增量重试，不得改用未经核验的二手数字。

## 独立复核

`phase4_verification_queue.csv`、`full_market_distribution_verification_queue.csv`和`full_market_annual_fundamentals_verification_queue.csv`按观测保存稳定SHA-256 ID。复核人只修改`review_status`、`reviewed_by`、`reviewed_at`和`review_notes`：

- `pending_independent_review`：尚未独立核对；
- `confirmed`：与正式公告一致；
- `rejected`：存在错误，需要修订解析结果。

`confirmed`或`rejected`必须同时填写复核人和带时区时间。重新生成队列时，ID未变化的复核结果会保留；原始值、单位、日期或URL变化会生成新ID，避免旧复核结论错误继承。

## 历史成员限制

当前历史成员由交易所正式上市日期回溯重建，并确认目录中没有终止上市、退市或摘牌公告。它优于把当前名单直接回填历史，但仍是事后重建层。项目应继续保存同期月末快照；若出现终止上市候选，维护程序会停止，必须先登记终止日期后再扩展成员面板。

## 前瞻研究

Phase 4规则冻结在`phase4_research_freeze.yaml`。2026Q3起的新季度只有在报告公开且决策日晚于冻结时点时才计入前瞻季度。禁止看到新结果后修改既有权重、持仓数、成本或基准定义；任何新模型都必须使用新的研究ID另行登记。
