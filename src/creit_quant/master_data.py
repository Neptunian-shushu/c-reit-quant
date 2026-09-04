"""C-REIT 全市场证券快照、增量历史和待核验分类工具。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OVERRIDES_PATH = ROOT / "data" / "reference" / "security_overrides.csv"
DEFAULT_LISTING_OVERRIDES_PATH = (
    ROOT / "data" / "reference" / "listing_date_overrides.csv"
)

LISTING_COLUMNS = [
    "symbol",
    "listing_date",
    "publication_date",
    "exchange",
    "source_url",
    "evidence_method",
    "verification_status",
    "raw_text",
]

TRADABLE_UNIVERSE_COLUMNS = [
    "snapshot_date",
    "symbol",
    "name",
    "exchange",
    "listing_date",
    "source_url",
    "membership_method",
    "verification_status",
]

UNIVERSE_COLUMNS = [
    "snapshot_date",
    "symbol",
    "name",
    "exchange",
    "source_name",
    "source_url",
    "record_status",
]

ASSET_TYPE_RULES = [
    ("data_center", ("数据中心",)),
    ("rental_housing", ("租赁住房", "保障房", "安居", "有巢", "宽庭")),
    ("toll_road", ("高速", "交控", "交投", "隧道")),
    ("logistics", ("仓储", "物流", "普洛斯", "安博")),
    ("industrial_park", ("产业园", "产园", "高科", "科创", "软件园", "光谷", "智造")),
    ("retail", ("消费", "商业", "奥莱", "市场", "百联", "印力", "凯德", "物美")),
    ("renewable", ("清洁能源", "新能源", "光伏", "风电")),
    ("heating", ("供热",)),
    ("water", ("水务", "水利")),
]


def _exchange_from_symbol(symbol: str) -> str:
    if symbol.startswith("508"):
        return "SSE"
    if symbol.startswith(("180", "181")):
        return "SZSE"
    return "UNKNOWN"


def build_universe_snapshot(
    universe: pd.DataFrame,
    snapshot_date: str | pd.Timestamp,
    *,
    source_name: str = "AKShare/Eastmoney",
    source_url: str = "https://quote.eastmoney.com/center/gridlist.html#fund_reits_all",
) -> pd.DataFrame:
    """把实时行情表转换为不含价格的、可长期追加的证券存在性快照。"""

    missing = sorted({"symbol", "name"}.difference(universe.columns))
    if missing:
        raise ValueError(f"universe 缺少字段: {missing}")
    frame = universe[["symbol", "name"]].copy()
    frame["symbol"] = frame["symbol"].astype(str).str.zfill(6)
    if not frame["symbol"].str.fullmatch(r"\d{6}").all():
        raise ValueError("universe symbol 必须是六位数字")
    if frame["symbol"].duplicated().any():
        raise ValueError("同一 universe 快照内 symbol 不能重复")
    frame["name"] = frame["name"].astype("string").str.strip()
    if frame["name"].isna().any() or frame["name"].eq("").any():
        raise ValueError("universe name 不能为空")
    frame.insert(0, "snapshot_date", pd.Timestamp(snapshot_date).normalize())
    frame["exchange"] = frame["symbol"].map(_exchange_from_symbol)
    frame["source_name"] = source_name
    frame["source_url"] = source_url
    needs_review = frame["name"].str.endswith("...") | ~frame["name"].str.contains(
        "REIT", case=False
    )
    frame["record_status"] = needs_review.map(
        {True: "needs_name_review", False: "source_observed"}
    )
    return frame[UNIVERSE_COLUMNS].sort_values("symbol").reset_index(drop=True)


def merge_universe_history(
    existing: pd.DataFrame | None, new_snapshot: pd.DataFrame
) -> pd.DataFrame:
    """幂等合并历史快照；同日同代码内容冲突时拒绝静默覆盖。"""

    new = new_snapshot[UNIVERSE_COLUMNS].copy()
    new["snapshot_date"] = pd.to_datetime(new["snapshot_date"], errors="raise")
    if existing is None or existing.empty:
        return new.sort_values(["snapshot_date", "symbol"]).reset_index(drop=True)
    old = existing[UNIVERSE_COLUMNS].copy()
    old["snapshot_date"] = pd.to_datetime(old["snapshot_date"], errors="raise")
    keys = ["snapshot_date", "symbol"]
    overlap = old.merge(new, on=keys, how="inner", suffixes=("_old", "_new"))
    compare_columns = [column for column in UNIVERSE_COLUMNS if column not in keys]
    conflicts = pd.Series(False, index=overlap.index)
    for column in compare_columns:
        conflicts |= (
            overlap[f"{column}_old"].fillna("").ne(overlap[f"{column}_new"].fillna(""))
        )
    if conflicts.any():
        raise ValueError("同日 universe 快照与已有记录冲突")
    combined = pd.concat([old, new], ignore_index=True).drop_duplicates(
        keys, keep="first"
    )
    return combined.sort_values(keys).reset_index(drop=True)


def load_universe_history(path: str | Path) -> pd.DataFrame:
    """读取并校验全市场证券存在性快照历史。"""

    frame = pd.read_csv(path, dtype={"symbol": str})
    missing = sorted(set(UNIVERSE_COLUMNS).difference(frame.columns))
    if missing:
        raise ValueError(f"universe history 缺少字段: {missing}")
    frame = frame[UNIVERSE_COLUMNS].copy()
    frame["snapshot_date"] = pd.to_datetime(frame["snapshot_date"], errors="raise")
    if frame.duplicated(["snapshot_date", "symbol"]).any():
        raise ValueError("universe history 同日代码重复")
    return frame.sort_values(["snapshot_date", "symbol"]).reset_index(drop=True)


def build_security_master(history: pd.DataFrame) -> pd.DataFrame:
    """从快照历史生成证券观察主表，不把首次观察日误称为上市日。"""

    if history.empty:
        raise ValueError("universe history 不能为空")
    frame = history.copy()
    frame["snapshot_date"] = pd.to_datetime(frame["snapshot_date"], errors="raise")
    latest_date = frame["snapshot_date"].max()
    latest_names = (
        frame.sort_values(["snapshot_date", "symbol"])
        .groupby("symbol", as_index=False)
        .tail(1)[["symbol", "name", "exchange", "record_status"]]
    )
    dates = frame.groupby("symbol", as_index=False)["snapshot_date"].agg(
        first_observed_date="min", last_observed_date="max"
    )
    master = dates.merge(latest_names, on="symbol", validate="one_to_one")
    master["present_in_latest_snapshot"] = master["last_observed_date"].eq(latest_date)
    return (
        master[
            [
                "symbol",
                "name",
                "exchange",
                "first_observed_date",
                "last_observed_date",
                "present_in_latest_snapshot",
                "record_status",
            ]
        ]
        .sort_values("symbol")
        .reset_index(drop=True)
    )


def classify_asset_type_candidates(master: pd.DataFrame) -> pd.DataFrame:
    """按名称生成待人工复核的资产类型候选，不把规则结果标成已核验事实。"""

    result = master.copy()

    def classify(name: str) -> str:
        for asset_type, keywords in ASSET_TYPE_RULES:
            if any(keyword in name for keyword in keywords):
                return asset_type
        return "unknown"

    result["candidate_asset_type"] = result["name"].astype(str).map(classify)
    result["classification_method"] = "keyword_rule"
    result["classification_status"] = "needs_human_review"
    return result


def load_security_overrides(
    path: str | Path = DEFAULT_OVERRIDES_PATH,
) -> pd.DataFrame:
    """读取已经一手来源人工核验的证券名称与资产类型覆盖层。"""

    frame = pd.read_csv(path, dtype={"symbol": str})
    required = {
        "symbol",
        "official_name",
        "asset_type",
        "verification_status",
        "source_url",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"证券核验覆盖层缺少字段: {missing}")
    if (
        frame["symbol"].duplicated().any()
        or not frame["symbol"].str.fullmatch(r"\d{6}").all()
    ):
        raise ValueError("证券核验覆盖层 symbol 必须是唯一六位数字")
    if not frame["verification_status"].eq("human_verified").all():
        raise ValueError("证券核验覆盖层只允许 human_verified 记录")
    return frame


def apply_security_overrides(
    candidates: pd.DataFrame, overrides: pd.DataFrame
) -> pd.DataFrame:
    """用一手来源核验值覆盖行情简称和规则分类，并保留核验来源。"""

    unknown = sorted(set(overrides["symbol"]).difference(candidates["symbol"]))
    if unknown:
        raise ValueError(f"证券核验覆盖层包含 universe 中不存在的代码: {unknown}")
    result = candidates.merge(
        overrides,
        on="symbol",
        how="left",
        validate="one_to_one",
    )
    verified = result["verification_status"].eq("human_verified")
    result.loc[verified, "name"] = result.loc[verified, "official_name"]
    result.loc[verified, "candidate_asset_type"] = result.loc[verified, "asset_type"]
    result.loc[verified, "classification_method"] = "official_source_manual_review"
    result.loc[verified, "classification_status"] = "human_verified"
    result.loc[verified, "record_status"] = "human_verified"
    return result.drop(columns=["official_name", "asset_type", "verification_status"])


def extract_official_listing_records(
    catalog: pd.DataFrame,
    overrides: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """从交易所公告标题提取首发上市日，并合并显式人工覆盖。

    仅接受“上市交易提示性公告”，排除扩募及“公告书提示性公告”。公告日
    即实际上市交易日。扫描型公告书等无法由标题确认的例外必须放入覆盖表，
    不能用行情首日静默替代。
    """

    required = {"symbol", "publication_date", "title", "source_url", "exchange"}
    missing = sorted(required.difference(catalog.columns))
    if missing:
        raise ValueError(f"公告目录缺少上市记录字段: {missing}")
    frame = catalog.copy()
    frame["symbol"] = frame["symbol"].astype(str).str.zfill(6)
    frame["publication_date"] = pd.to_datetime(
        frame["publication_date"], errors="raise"
    )
    title = frame["title"].fillna("").astype(str)
    selected = frame.loc[
        title.str.contains("上市交易提示性公告") & ~title.str.contains("公告书提示性公告|扩募")
    ].copy()
    if selected["symbol"].duplicated().any():
        duplicated = sorted(
            selected.loc[selected["symbol"].duplicated(), "symbol"].unique()
        )
        raise ValueError(f"同一证券存在多条首发上市提示公告: {duplicated}")
    records = pd.DataFrame(
        {
            "symbol": selected["symbol"],
            "listing_date": selected["publication_date"],
            "publication_date": selected["publication_date"],
            "exchange": selected["exchange"],
            "source_url": selected["source_url"],
            "evidence_method": "official_listing_notice_title",
            "verification_status": "official_metadata_verified",
            "raw_text": selected["title"],
        }
    )
    if overrides is not None and not overrides.empty:
        absent = sorted(set(LISTING_COLUMNS).difference(overrides.columns))
        if absent:
            raise ValueError(f"上市日覆盖表缺少字段: {absent}")
        manual = overrides[LISTING_COLUMNS].copy()
        manual["symbol"] = manual["symbol"].astype(str).str.zfill(6)
        for column in ["listing_date", "publication_date"]:
            manual[column] = pd.to_datetime(manual[column], errors="raise")
        if (
            not manual["verification_status"]
            .isin({"visual_verified_official_pdf", "human_verified"})
            .all()
        ):
            raise ValueError("上市日覆盖项必须经过正式PDF视觉或人工核验")
        overlap = sorted(set(records["symbol"]).intersection(manual["symbol"]))
        if overlap:
            raise ValueError(f"上市日覆盖项与自动提取重复: {overlap}")
        records = pd.concat([records, manual], ignore_index=True)
    if records["symbol"].duplicated().any():
        raise ValueError("上市记录 symbol 必须唯一")
    if (records["listing_date"] < records["publication_date"]).any():
        raise ValueError("上市日期不能早于证据公告日")
    return records[LISTING_COLUMNS].sort_values("symbol").reset_index(drop=True)


def load_listing_date_overrides(
    path: str | Path = DEFAULT_LISTING_OVERRIDES_PATH,
) -> pd.DataFrame:
    """读取无法由公告标题自动确认的上市日视觉复核覆盖表。"""

    return pd.read_csv(path, dtype={"symbol": str})


def build_month_end_tradable_universe(
    listings: pd.DataFrame,
    latest_snapshot: pd.DataFrame,
    *,
    as_of_date: str | pd.Timestamp,
) -> pd.DataFrame:
    """按正式上市日重建已完成月末的可交易C-REIT成员面板。

    本函数只处理上市成员关系，不推断退市日。调用方应先确认公告目录不存在
    未处理的终止上市事件。未上市但出现在实时行情源中的产品不会进入面板。
    """

    missing = sorted(
        {"symbol", "listing_date", "source_url", "verification_status"}.difference(
            listings.columns
        )
    )
    if missing:
        raise ValueError(f"上市记录缺少字段: {missing}")
    if latest_snapshot.duplicated("symbol").any():
        raise ValueError("最新universe快照 symbol 重复")
    end = pd.Timestamp(as_of_date).normalize()
    completed_month_end = end if end.is_month_end else end - pd.offsets.MonthEnd(1)
    start = pd.to_datetime(listings["listing_date"], errors="raise").min()
    month_ends = pd.date_range(start=start, end=completed_month_end, freq="ME")
    names = latest_snapshot[["symbol", "name", "exchange"]].copy()
    names["symbol"] = names["symbol"].astype(str).str.zfill(6)
    unknown = sorted(set(listings["symbol"]).difference(names["symbol"]))
    if unknown:
        raise ValueError(f"上市记录包含最新观察名单外证券，需先核查退市状态: {unknown}")
    source = listings.merge(
        names, on="symbol", suffixes=("", "_snapshot"), validate="one_to_one"
    )
    if (source["exchange"] != source["exchange_snapshot"]).any():
        raise ValueError("上市公告交易所与证券快照交易所不一致")
    rows: list[pd.DataFrame] = []
    for snapshot_date in month_ends:
        members = source.loc[
            pd.to_datetime(source["listing_date"]).le(snapshot_date)
        ].copy()
        members.insert(0, "snapshot_date", snapshot_date)
        members["membership_method"] = "official_listing_date_reconstruction"
        rows.append(members)
    if not rows:
        return pd.DataFrame(columns=TRADABLE_UNIVERSE_COLUMNS)
    result = pd.concat(rows, ignore_index=True)
    return (
        result[TRADABLE_UNIVERSE_COLUMNS]
        .sort_values(["snapshot_date", "symbol"])
        .reset_index(drop=True)
    )
