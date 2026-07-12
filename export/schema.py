"""Redaction boundary for the HPC cost-analytics case study.

Every parser MUST build rows through this module. The design rule: the public
dataset contains solver TELEMETRY only. All physics payloads (energies,
magnetization, chemical potentials, topology, verdicts) are dropped at parse
time; physically identifying cell coordinates are replaced by salted opaque
ids. The leak-audit tests in tests/test_leak_audit.py enforce this contract on
the exported parquet files.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

# --------------------------------------------------------------------------
# Column whitelists: the ONLY columns allowed in the exported tables.
# --------------------------------------------------------------------------
RUNS_COLUMNS = [
    "run_id",           # opaque unique id
    "source",           # parser family: lattice_scf | lattice_scf_v2 | continuum_scf
    "campaign",         # anonymized campaign code (campaign_A, campaign_B, ...)
    "cell_id",          # salted hash of the physical cell coordinates
    "machine",          # laptop | perlmutter | azure | unknown
    "seed_family",      # seed/texture family name (public vocabulary)
    "seed_origin",      # warm | cold | analytic | unknown
    "mixing",           # pulay | linear | unknown
    "tol",              # convergence tolerance (solver setting)
    "max_iter",         # iteration budget
    "workers",          # process/thread count
    "grid_k",           # k-grid size (kappa_nk / nk)
    "grid_twist",       # twist-grid size
    "basis_nharm",      # basis / harmonic count where applicable
    "beta",             # inverse-temperature solver setting
    "n_iter",           # iterations used
    "converged",        # bool
    "status",           # ok | max_iter | limit_cycle | error | unknown
    "wall_minutes",     # wall-clock cost
    "final_residual",   # final self-consistency residual (magnitude only)
    "has_trace",        # bool: residual history exported to iterations table
    "file_mtime",       # ISO date of the source record (coarse, day-level)
]
ITER_COLUMNS = ["run_id", "step", "residual"]
REQUESTS_COLUMNS = [
    "request_id", "campaign", "machine", "requested_walltime_min",
    "nodes", "cores", "partition",
]

# --------------------------------------------------------------------------
# Forbidden content: belt-and-suspenders on top of the whitelists.
# Applied by the leak audit to column NAMES and to string VALUES.
# --------------------------------------------------------------------------
FORBIDDEN_PATTERNS = [
    r"energy", r"helmholtz", r"free_energy", r"(^|_)[EF](_|$)",
    r"magnet", r"M_scf", r"M_seed", r"mu_scf", r"(^|_)mu(_|$)",
    r"chern", r"sigma_xy", r"berg", r"(^|_)bl(_|$)", r"chirality",
    r"verdict", r"winner", r"(^|_)gap", r"plateau", r"topolog",
    r"overlap", r"q_star", r"(^|_)chi(_|$)", r"dominant_q", r"basin",
    r"band_edge", r"pair_gap", r"texture_overlap",
    # identity / infrastructure leaks
    r"pscratch", r"/Users/", r"wenqin",
]
# Site-specific patterns (raw tokens found in manual review of the private
# repos) live in forbidden_extra.local.json, gitignored: the public contract
# should not itself enumerate the private vocabulary it redacts.
_EXTRA_PATH = Path(__file__).parent / "forbidden_extra.local.json"
if _EXTRA_PATH.exists():
    FORBIDDEN_PATTERNS = FORBIDDEN_PATTERNS + json.loads(_EXTRA_PATH.read_text())
FORBIDDEN_RE = [re.compile(p, re.IGNORECASE) for p in FORBIDDEN_PATTERNS]


def violates_forbidden(text: str) -> str | None:
    """Return the first matching forbidden pattern, or None."""
    for rx in FORBIDDEN_RE:
        if rx.search(str(text)):
            return rx.pattern
    return None


# --------------------------------------------------------------------------
# Salted anonymization. The salt lives in export/salt.local (gitignored);
# without it the opaque ids cannot be brute-forced back to low-entropy
# physical coordinates.
# --------------------------------------------------------------------------
_SALT_PATH = Path(__file__).parent / "salt.local"
_MAP_PATH = Path(__file__).parent / "campaign_map.local.json"


def _salt() -> str:
    if not _SALT_PATH.exists():
        import secrets
        _SALT_PATH.write_text(secrets.token_hex(32))
    return _SALT_PATH.read_text().strip()


def cell_id(**coords) -> str:
    """Opaque, stable id for a physical cell. Pass the raw coordinates as
    kwargs; ONLY the salted hash leaves this function."""
    key = "|".join(f"{k}={coords[k]}" for k in sorted(coords))
    return "cell_" + hashlib.sha256((_salt() + key).encode()).hexdigest()[:10]


def campaign_code(raw_name: str) -> str:
    """Anonymize a campaign/experiment name to campaign_01, campaign_02, ...
    The raw->code mapping persists locally (gitignored) for reproducibility.

    Numeric codes: the original letter scheme (campaign_A, ...) produced
    campaign_E / campaign_F, which collide with the forbidden pattern
    (^|_)[EF](_|$), and degraded into punctuation past 26 campaigns."""
    mapping = json.loads(_MAP_PATH.read_text()) if _MAP_PATH.exists() else {}
    if raw_name not in mapping:
        mapping[raw_name] = f"campaign_{len(mapping) + 1:02d}"
        _MAP_PATH.write_text(json.dumps(mapping, indent=1, sort_keys=True))
    return mapping[raw_name]


def run_id(source: str, raw_key: str) -> str:
    return f"{source}_" + hashlib.sha256((_salt() + raw_key).encode()).hexdigest()[:12]


# --------------------------------------------------------------------------
# Seed-family sanitization: family NAMES must not embed cell coordinates,
# amplitudes, wavevectors, verdict vocabulary, or winding labels. The concrete
# rewrite map and strip patterns reference raw private names, so they live in
# family_rewrites.local.json (gitignored); without it, names pass through.
# --------------------------------------------------------------------------
_REWRITES_PATH = Path(__file__).parent / "family_rewrites.local.json"
_FAMILY_REWRITES: dict = {}
_FAMILY_STRIP: list = []
if _REWRITES_PATH.exists():
    _cfg = json.loads(_REWRITES_PATH.read_text())
    _FAMILY_REWRITES = _cfg.get("rewrites", {})
    _FAMILY_STRIP = [re.compile(p) for p in _cfg.get("strip", [])]


def sanitize_seed_family(name):
    """Strip parameter tokens / verdict vocabulary from a seed-family name."""
    if name is None or (isinstance(name, float)):
        return None
    name = _FAMILY_REWRITES.get(str(name), str(name))
    for rx in _FAMILY_STRIP:
        name = rx.sub("", name)
    return name or "unknown"
