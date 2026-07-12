"""Leak audit: gates every export. If any of these fail, the dataset must not
be committed or published. Run: .venv/bin/pytest tests -q"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "export"))
import schema  # noqa: E402

DATA = ROOT / "data"
TABLES = {
    "runs.parquet": schema.RUNS_COLUMNS,
    "iterations.parquet": schema.ITER_COLUMNS,
    "requests.parquet": schema.REQUESTS_COLUMNS,
}


def _existing_tables():
    return [(n, cols) for n, cols in TABLES.items() if (DATA / n).exists()]


def test_at_least_runs_table_exists():
    assert (DATA / "runs.parquet").exists(), "run export/build_dataset.py first"


@pytest.mark.parametrize("name,allowed", TABLES.items())
def test_columns_are_whitelisted(name, allowed):
    path = DATA / name
    if not path.exists():
        pytest.skip(f"{name} not built yet")
    df = pd.read_parquet(path)
    extra = set(df.columns) - set(allowed)
    assert not extra, f"{name} has non-whitelisted columns: {extra}"


@pytest.mark.parametrize("name,allowed", TABLES.items())
def test_no_forbidden_content_in_values(name, allowed):
    path = DATA / name
    if not path.exists():
        pytest.skip(f"{name} not built yet")
    df = pd.read_parquet(path)
    for col in df.columns:
        if df[col].dtype == object:
            for val in df[col].dropna().astype(str).unique():
                hit = schema.violates_forbidden(val)
                assert hit is None, f"{name}.{col} value {val!r} matches forbidden {hit}"


def test_no_forbidden_column_names():
    for name, _ in _existing_tables():
        df = pd.read_parquet(DATA / name)
        for col in df.columns:
            hit = schema.violates_forbidden(col)
            assert hit is None, f"{name} column name {col!r} matches forbidden {hit}"


def test_salt_and_map_are_gitignored_and_local():
    gitignore = (ROOT / ".gitignore").read_text()
    assert "salt.local" in gitignore
    assert "campaign_map.local" in gitignore


def test_cell_ids_are_opaque():
    if not (DATA / "runs.parquet").exists():
        pytest.skip("not built")
    df = pd.read_parquet(DATA / "runs.parquet")
    if "cell_id" in df.columns:
        pat = re.compile(r"^cell_[0-9a-f]{10}$")
        bad = [v for v in df["cell_id"].dropna().unique() if not pat.match(str(v))]
        assert not bad, f"non-opaque cell ids: {bad[:5]}"


def test_no_tracked_local_files():
    """salt.local / campaign_map.local must never be tracked by git."""
    if not (ROOT / ".git").exists():
        pytest.skip("repo not initialized")
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True)
    tracked = out.stdout
    assert "salt.local" not in tracked
    assert "campaign_map.local" not in tracked
