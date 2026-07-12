"""Assemble the redacted telemetry dataset and DuckDB warehouse.

Reads the private research folders (read-only), routes everything through the
redaction contract in schema.py, and writes:
    data/runs.parquet, data/iterations.parquet, data/requests.parquet
    warehouse/telemetry.duckdb  (gitignored; rebuilt from parquet)

Source locations and parser modules come from export/sources.local.json
(gitignored; see sources.example.json for the shape). The per-source parsers
read the private research trees directly, so they are kept out of the public
repo along with the config; the contract that gates what leaves them is
schema.py plus the leak audit.

Run:  .venv/bin/python export/build_dataset.py
Then ALWAYS run the leak audit before committing:  .venv/bin/pytest tests -q
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import duckdb
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import schema  # noqa: E402

CONFIG = HERE / "sources.local.json"


def load_config() -> dict:
    if not CONFIG.exists():
        sys.exit(
            "export/sources.local.json not found.\n"
            "The committed parquet in data/ was built with it; rebuilding from "
            "scratch requires the private source trees. Copy "
            "export/sources.example.json and point it at them."
        )
    return json.loads(CONFIG.read_text())


def main() -> None:
    cfg = load_config()
    runs, iters = [], []
    for src in cfg["sources"]:
        mod = importlib.import_module(src["module"])
        df = mod.extract(src["root"])
        print(f"[{src['name']}] runs: {len(df)}")
        runs.append(df)
        if hasattr(mod, "extract_iterations"):
            di = mod.extract_iterations(src["root"])
            print(f"[{src['name']}] iterations: {len(di)}")
            iters.append(di)

    runs_df = pd.concat(runs, ignore_index=True).reindex(columns=schema.RUNS_COLUMNS)
    iters_df = (pd.concat(iters, ignore_index=True).reindex(columns=schema.ITER_COLUMNS)
                if iters else pd.DataFrame(columns=schema.ITER_COLUMNS))

    # Sanitize seed-family names (strips embedded parameters / verdict tokens).
    runs_df["seed_family"] = runs_df["seed_family"].map(schema.sanitize_seed_family)

    # Defensive dedupe: identical source records (e.g. stale worktree copies of
    # the research folders) hash to identical run_ids: keep the first.
    before = len(runs_df), len(iters_df)
    runs_df = runs_df.drop_duplicates(subset="run_id", keep="first").reset_index(drop=True)
    iters_df = iters_df.drop_duplicates(subset=["run_id", "step"], keep="first").reset_index(drop=True)
    dropped = (before[0] - len(runs_df), before[1] - len(iters_df))
    if any(dropped):
        print(f"deduped: {dropped[0]} duplicate runs, {dropped[1]} duplicate iteration rows")

    req_cfg = cfg["requests"]
    req_mod = importlib.import_module(req_cfg["module"])
    req_df = req_mod.extract(req_cfg["roots"]).reindex(columns=schema.REQUESTS_COLUMNS)

    data = ROOT / "data"
    data.mkdir(exist_ok=True)
    runs_df.to_parquet(data / "runs.parquet", index=False)
    iters_df.to_parquet(data / "iterations.parquet", index=False)
    req_df.to_parquet(data / "requests.parquet", index=False)
    print(f"TOTAL runs={len(runs_df)}  iterations={len(iters_df)}  requests={len(req_df)}")

    wh = ROOT / "warehouse"
    wh.mkdir(exist_ok=True)
    con = duckdb.connect(str(wh / "telemetry.duckdb"))
    for t in ("runs", "iterations", "requests"):
        con.execute(f"CREATE OR REPLACE TABLE {t} AS SELECT * FROM read_parquet('{data / (t + '.parquet')}')")
    n = con.execute("SELECT count(*) FROM runs").fetchone()[0]
    con.close()
    print(f"warehouse/telemetry.duckdb built ({n} runs)")
    print("NOW RUN THE LEAK AUDIT:  .venv/bin/pytest tests -q")


if __name__ == "__main__":
    main()
