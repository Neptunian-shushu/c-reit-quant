"""更新全市场 C-REIT universe 快照并生成待核验证券主表。"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from creit_quant.market import fetch_reit_universe
from creit_quant.master_data import (
    apply_security_overrides,
    build_security_master,
    build_universe_snapshot,
    classify_asset_type_candidates,
    load_universe_history,
    load_security_overrides,
    merge_universe_history,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HISTORY_PATH = ROOT / "data" / "snapshots" / "reit_universe_history.csv"


def main() -> None:
    """联网追加当日快照；重复运行同一内容不会产生重复行。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-date", default=date.today().isoformat())
    parser.add_argument("--history", default=str(DEFAULT_HISTORY_PATH))
    parser.add_argument("--master-out", help="可选证券观察主表输出路径")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="不联网，仅从已有快照重建证券观察主表",
    )
    args = parser.parse_args()

    history_path = Path(args.history)
    existing = load_universe_history(history_path) if history_path.exists() else None
    if args.offline:
        if existing is None:
            parser.error("--offline 需要已有 --history 文件")
        history = existing
        latest_date = history["snapshot_date"].max()
        snapshot = history.loc[history["snapshot_date"].eq(latest_date)].copy()
    else:
        snapshot = build_universe_snapshot(fetch_reit_universe(), args.snapshot_date)
        history = merge_universe_history(existing, snapshot)
        history_path.parent.mkdir(parents=True, exist_ok=True)
        history.to_csv(history_path, index=False)

    master = apply_security_overrides(
        classify_asset_type_candidates(build_security_master(history)),
        load_security_overrides(),
    )
    if args.master_out:
        master_path = Path(args.master_out)
        master_path.parent.mkdir(parents=True, exist_ok=True)
        master.to_csv(master_path, index=False)
    print(f"快照日期: {snapshot['snapshot_date'].max().date()}")
    print(f"当前观察到 C-REIT: {len(snapshot)} 只")
    print(f"历史快照: {history['snapshot_date'].nunique()} 日 / {len(history)} 行")
    print(f"名称待复核: {master['record_status'].eq('needs_name_review').sum()} 只")
    print(
        f"资产类型已人工核验 / 待复核: "
        f"{master['classification_status'].eq('human_verified').sum()} / "
        f"{master['classification_status'].eq('needs_human_review').sum()} 只"
    )


if __name__ == "__main__":
    main()
