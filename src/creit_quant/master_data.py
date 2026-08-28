"""C-REIT 全市场证券快照、增量历史和待核验分类工具。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OVERRIDES_PATH = ROOT / "data" / "reference" / "security_overrides.csv"

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
        conflicts |= overlap[f"{column}_old"].fillna("").ne(
            overlap[f"{column}_new"].fillna("")
        )
    if conflicts.any():
        raise ValueError("同日 universe 快照与已有记录冲突")
    combined = pd.concat([old, new], ignore_index=True).drop_duplicates(keys, keep="first")
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
    return master[
        [
            "symbol",
            "name",
            "exchange",
            "first_observed_date",
            "last_observed_date",
            "present_in_latest_snapshot",
            "record_status",
        ]
    ].sort_values("symbol").reset_index(drop=True)


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
    required = {"symbol", "official_name", "asset_type", "verification_status", "source_url"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"证券核验覆盖层缺少字段: {missing}")
    if frame["symbol"].duplicated().any() or not frame["symbol"].str.fullmatch(r"\d{6}").all():
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
