"""从公募REIT收益分配公告文本提取实际DPU与场内除息日。"""

from __future__ import annotations

import re

import pandas as pd


DATE_PATTERN = re.compile(r"(20\d{2})\s*[年/\-.]\s*(\d{1,2})\s*[月/\-.]\s*(\d{1,2})\s*日?")


def _compact(text: str) -> str:
    return " ".join(text.split())


def _date(match: re.Match[str]) -> pd.Timestamp:
    return pd.Timestamp(
        year=int(match.group(1)), month=int(match.group(2)), day=int(match.group(3))
    )


def parse_distribution_text(text: str) -> dict[str, object]:
    """解析文字层；无法同时确认每10份方案和场内除息日时明确失败。"""

    compact = _compact(text)
    if not compact:
        raise ValueError("PDF没有可用文字层")
    scheme_text = ""
    for scheme in re.finditer(r"分红方案", compact, re.I):
        candidate = compact[scheme.end() : scheme.end() + 320]
        candidate = re.split(r"有关年度|注[：:]|二[、.]|2[、.]\s", candidate, maxsplit=1)[0]
        without_decimals = re.sub(r"(?<!\d)\d+\.\d+(?!\d)", "", candidate)
        normalized_unit = re.sub(r"\s+", "", without_decimals)
        if "元/10份" in normalized_unit and re.search(
            r"(?<!\d)\d+\.\d+(?!\d)", candidate
        ):
            scheme_text = candidate
            break
    if not scheme_text:
        raise ValueError("未找到本次分红方案")
    numbers = re.findall(r"(?<!\d)(\d+\.\d+)(?!\d)", scheme_text)
    if not numbers:
        raise ValueError("未找到每10份分红数值")
    disclosed = float(numbers[0].replace(",", ""))
    if not 0 < disclosed < 100:
        raise ValueError("每10份分红数值超出合理校验范围")

    label = re.search(r"除息日", compact)
    if label is None:
        raise ValueError("未找到除息日表格")
    window = compact[max(0, label.start() - 120) : label.end() + 360]
    window = re.split(r"现金红利发放日|分红对象", window, maxsplit=1)[0]
    after_label = re.search(r"场内[：:]?\s*" + DATE_PATTERN.pattern, window)
    before_label = re.search(DATE_PATTERN.pattern + r"\s*[（(]?\s*场内", window)
    if after_label is not None:
        date_match = re.search(DATE_PATTERN.pattern, after_label.group(0))
    elif before_label is not None:
        date_match = before_label
    else:
        date_match = None
    if date_match is not None:
        ex_date = _date(date_match)
    else:
        # PDF表格有时把两列交错为“日期（场 日期（场 内）外）”。场内除息日
        # 是表内较晚日期。列名可能出现在两项除息日期之后，因此优先读取
        # 标签前最近两列，避免误把随后交错出现的现金发放日期算入。
        preceding = compact[max(0, label.start() - 180) : label.start()]
        preceding_dates = sorted(
            set(_date(match) for match in DATE_PATTERN.finditer(preceding))
        )
        table_dates = (
            preceding_dates
            if len(preceding_dates) >= 2
            else sorted(set(_date(match) for match in DATE_PATTERN.finditer(window)))
        )
        if (
            not 2 <= len(table_dates) <= 3
            or (table_dates[-1] - table_dates[0]).days > 7
        ):
            raise ValueError("未确认场内除息日")
        ex_date = table_dates[-1]
    evidence = _compact(f"本次分红方案{scheme_text[:180]}；除息日{window[:220]}")
    return {
        "ex_date": ex_date,
        "dpu_per_unit": disclosed / 10,
        "disclosed_rmb_per_10_units": disclosed,
        "raw_text": evidence,
    }


def resolve_distribution_documents(documents: pd.DataFrame) -> pd.DataFrame:
    """把同代码同公告日的重复文档折叠为一个事件，拒绝数值冲突。"""

    required = {
        "announcement_id",
        "symbol",
        "publication_date",
        "title",
        "source_url",
        "ex_date",
        "dpu_per_unit",
        "disclosed_rmb_per_10_units",
        "raw_text",
    }
    missing = sorted(required.difference(documents.columns))
    if missing:
        raise ValueError(f"分派文档缺少字段: {missing}")
    frame = documents.copy()
    frame["publication_date"] = pd.to_datetime(
        frame["publication_date"], errors="raise", format="mixed"
    )
    frame["ex_date"] = pd.to_datetime(frame["ex_date"], errors="raise", format="mixed")
    if (frame["ex_date"] < frame["publication_date"]).any():
        raise ValueError("场内除息日不能早于公告日")
    rows: list[pd.Series] = []
    for key, group in frame.groupby(["symbol", "publication_date"], sort=True):
        facts = group[["ex_date", "dpu_per_unit"]].drop_duplicates()
        preferred = group.loc[group["title"].str.contains("以此为准|更正", na=False)]
        if len(facts) > 1 and preferred.empty:
            raise ValueError(f"同日分派公告事实冲突: {key}")
        chosen = (
            (preferred if not preferred.empty else group)
            .sort_values("announcement_id")
            .iloc[-1]
        )
        if not preferred.empty:
            preferred_facts = preferred[["ex_date", "dpu_per_unit"]].drop_duplicates()
            if len(preferred_facts) > 1:
                raise ValueError(f"同日修正分派公告仍有冲突: {key}")
        rows.append(chosen)
    result = pd.DataFrame(rows)
    result["verification_status"] = "machine_extracted_official_pdf"
    columns = [
        "symbol",
        "publication_date",
        "ex_date",
        "dpu_per_unit",
        "disclosed_rmb_per_10_units",
        "source_url",
        "verification_status",
        "raw_text",
    ]
    return (
        result[columns]
        .sort_values(["symbol", "publication_date"])
        .reset_index(drop=True)
    )
