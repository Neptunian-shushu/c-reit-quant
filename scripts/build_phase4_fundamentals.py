"""从本地官方PDF文本抽取Phase 4基金指标快照。

原始PDF不入库。运行前需自行将公告转为保留布局的文本；脚本只接受交易所
公告目录中已登记的URL，并把机器抽取状态与原文证据一并写入CSV。
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd


SYMBOLS = {
    "180201",
    "180301",
    "180401",
    "508018",
    "508026",
    "508028",
    "508056",
    "508096",
}
DATE_PATTERN = r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"


def _compact(text: str) -> str:
    return " ".join(text.split())


def _number(value: str) -> float:
    return float(value.replace(",", ""))


def _iso_date(match: re.Match[str]) -> str:
    return (
        f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    )


def _catalog_lookup(
    catalog: pd.DataFrame, symbol: str, date: str, document_type: str
) -> pd.Series:
    date_column = (
        "period_end_candidate"
        if document_type != "distribution_announcement"
        else "publication_date"
    )
    rows = catalog.loc[
        catalog["symbol"].eq(symbol)
        & catalog[date_column].eq(date)
        & catalog["document_type_candidate"].eq(document_type)
    ]
    if len(rows) != 1:
        raise ValueError(f"公告目录无法唯一匹配 {symbol} {date} {document_type}: {len(rows)}")
    return rows.iloc[0]


def extract_quarterly_metrics(text_dir: Path, catalog: pd.DataFrame) -> pd.DataFrame:
    """抽取季度报告中的份额、当季可供分配金额及每份金额。"""

    rows: list[dict[str, object]] = []
    for path in sorted(text_dir.glob("*.txt")):
        symbol, period_end = path.stem.split("_", 1)
        if symbol not in SYMBOLS:
            continue
        text = _compact(path.read_text(encoding="utf-8", errors="ignore"))
        shares = re.search(r"报告期末基金份额总额\s+([\d,]+(?:\.\d+)?)\s*份", text)
        section = re.search(r"3\.3\.1\s*本报告期(?:及近三年)?的?可供分配金额(.+?)3\.3\.2", text)
        values = (
            None
            if section is None
            else re.search(
                r"本期\s+(-?[\d,]+(?:\.\d+)?)\s+(-?[\d.]+|-)", section.group(1)
            )
        )
        if shares is None or values is None or values.group(2) == "-":
            raise ValueError(f"季度报告字段抽取失败: {path.name}")
        source = _catalog_lookup(catalog, symbol, period_end, "quarterly_report")
        evidence = f"报告期末基金份额总额 {shares.group(1)} 份；本期可供分配金额 {values.group(1)}，单位可供分配金额 {values.group(2)}"
        for metric, value, unit in [
            ("fund_shares", _number(shares.group(1)), "shares"),
            ("distributable_amount_quarter", _number(values.group(1)), "RMB"),
            (
                "distributable_amount_per_unit_quarter",
                _number(values.group(2)),
                "RMB_per_unit",
            ),
        ]:
            rows.append(
                {
                    "symbol": symbol,
                    "period_end": period_end,
                    "publication_date": source["publication_date"],
                    "metric": metric,
                    "value": value,
                    "unit": unit,
                    "source_url": source["source_url"],
                    "document_type": "quarterly_report",
                    "verification_status": "machine_extracted_official_pdf",
                    "raw_text": evidence,
                }
            )
    return pd.DataFrame(rows)


def extract_annual_nav(text_dir: Path, catalog: pd.DataFrame) -> pd.DataFrame:
    """抽取年报明确披露的年末每份基金净值，不用估值倒推。"""

    rows: list[dict[str, object]] = []
    patterns = [
        r"报告截止日\s*\d{4}\s*年.*?基金份额净值(?:人民币)?\s*([\d.]+)\s*元",
        r"期末(?:不动产)?基金份额净\s*值\s*([\d.]+)",
        r"期末基金份额净\s+([\d.]+)\s+[\d.]+\s+[\d.]+\s+值",
    ]
    for path in sorted(text_dir.glob("*.txt")):
        symbol, period_end = path.stem.split("_", 1)
        if symbol not in SYMBOLS:
            continue
        text = _compact(path.read_text(encoding="utf-8", errors="ignore"))
        match = next(
            (found for pattern in patterns if (found := re.search(pattern, text))), None
        )
        if match is None:
            raise ValueError(f"年报NAV抽取失败: {path.name}")
        source = _catalog_lookup(catalog, symbol, period_end, "annual_report")
        value = _number(match.group(1))
        rows.append(
            {
                "symbol": symbol,
                "period_end": period_end,
                "publication_date": source["publication_date"],
                "metric": "nav_per_unit",
                "value": value,
                "unit": "RMB_per_unit",
                "source_url": source["source_url"],
                "document_type": "annual_report",
                "verification_status": "machine_extracted_official_pdf",
                "raw_text": f"报告截止日 {period_end}，基金份额净值 {value:.4f} 元",
            }
        )
    return pd.DataFrame(rows)


def extract_distributions(
    text_dir: Path, catalog: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """抽取实际分派公告；不可读的扫描PDF进入排除清单，绝不补值。"""

    rows: list[dict[str, object]] = []
    excluded: list[dict[str, object]] = []
    for path in sorted(text_dir.glob("*.txt")):
        symbol, publication_date = path.stem.split("_", 1)
        if symbol not in SYMBOLS:
            continue
        source = _catalog_lookup(
            catalog, symbol, publication_date, "distribution_announcement"
        )
        text = _compact(path.read_text(encoding="utf-8", errors="ignore"))
        dpu = re.search(r"本次(?:公募\s*REITs\s*)?分红方案.{0,100}?([0-9]+\.\d+)", text, re.I)
        ex_section = re.search(r"除息日(.{0,180}?)(?:现金红利发放日|分红对象)", text)
        if dpu is None or ex_section is None:
            excluded.append(
                {
                    "symbol": symbol,
                    "publication_date": publication_date,
                    "source_url": source["source_url"],
                    "reason": "PDF无可提取文字层或关键字段未匹配，未估算",
                }
            )
            continue
        disclosed = _number(dpu.group(1))
        window = ex_section.group(1)
        on_exchange = re.search(r"场内[：:]?\s*" + DATE_PATTERN, window)
        if on_exchange is None:
            on_exchange = re.search(DATE_PATTERN + r"\s*[（(]场\s*内", window)
        all_dates = list(re.finditer(DATE_PATTERN, window))
        if on_exchange is not None:
            ex_date = _iso_date(on_exchange)
        elif all_dates:
            # 少数深交所PDF把“场内/场外”拆到下一行；表格固定先列场内日期。
            ex_date = _iso_date(all_dates[0])
        else:
            raise ValueError(f"已抽取DPU但未抽取除息日: {path.name}")
        rows.append(
            {
                "symbol": symbol,
                "publication_date": publication_date,
                "ex_date": ex_date,
                "dpu_per_unit": disclosed / 10,
                "disclosed_rmb_per_10_units": disclosed,
                "source_url": source["source_url"],
                "verification_status": "machine_extracted_official_pdf",
                "raw_text": f"本次分红方案 {disclosed} 元/10份；场内除息日 {ex_date}",
            }
        )
    return pd.DataFrame(rows), pd.DataFrame(excluded)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quarterly-text-dir", type=Path, required=True)
    parser.add_argument("--annual-text-dir", type=Path, required=True)
    parser.add_argument("--distribution-text-dir", type=Path, required=True)
    parser.add_argument(
        "--catalog",
        type=Path,
        default=Path("data/snapshots/reit_announcement_catalog.csv"),
    )
    parser.add_argument(
        "--distribution-visual-overrides",
        type=Path,
        default=Path("data/reference/phase4_distribution_visual_overrides.csv"),
    )
    parser.add_argument("--out-dir", type=Path, default=Path("data/samples"))
    args = parser.parse_args()
    catalog = pd.read_csv(args.catalog, dtype=str)
    fundamentals = pd.concat(
        [
            extract_quarterly_metrics(args.quarterly_text_dir, catalog),
            extract_annual_nav(args.annual_text_dir, catalog),
        ],
        ignore_index=True,
    ).sort_values(["symbol", "period_end", "publication_date", "metric"])
    distributions, excluded = extract_distributions(args.distribution_text_dir, catalog)
    if args.distribution_visual_overrides.exists():
        overrides = pd.read_csv(
            args.distribution_visual_overrides, dtype={"symbol": str}
        )
        override_keys = set(zip(overrides["symbol"], overrides["publication_date"]))
        excluded_keys = set(zip(excluded["symbol"], excluded["publication_date"]))
        if not override_keys.issubset(excluded_keys):
            raise ValueError("视觉复核覆盖项必须来自本次自动抽取排除表")
        distributions = pd.concat([distributions, overrides], ignore_index=True)
        excluded = excluded.loc[
            ~excluded.apply(
                lambda row: (row["symbol"], row["publication_date"]) in override_keys,
                axis=1,
            )
        ]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    fundamentals.to_csv(args.out_dir / "phase4_fund_fundamentals.csv", index=False)
    distributions.sort_values(["symbol", "publication_date"]).to_csv(
        args.out_dir / "phase4_distributions.csv", index=False
    )
    excluded.sort_values(["symbol", "publication_date"]).to_csv(
        args.out_dir / "phase4_distribution_exclusions.csv", index=False
    )
    print(
        f"fundamentals={len(fundamentals)}, distributions={len(distributions)}, exclusions={len(excluded)}"
    )


if __name__ == "__main__":
    main()
