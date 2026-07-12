# hpc-cost-analytics

**Pricing scientific HPC runs before launch: cost analytics on 2,127 solver runs
from my own research computing.**

Two years of production telemetry from three research codebases (a continuum
Hartree-Fock solver and two lattice mean-field solvers), assembled into a DuckDB
warehouse, audited, and used to build a run-cost model and two scheduling policies:
calibrated walltime requests and cheap-first seed ordering.

## Findings at a glance

- **44% of the flagship source's 508 wall-hours** went to runs that never converged.
  That waste is the motivation for predicting cost and convergence risk up front.
- Median run cost scales like **grid_k^6.4**: per-iteration work, not extra iterations.
- **Split honesty:** the same model scores R2 = 0.82 under a random CV split and 0.21
  under leave-campaign-out. The gap is leakage, measured. All reported numbers use the
  honest split.
- Typical prediction error is **2.8x pooled** (2.5x on the dominant source), with a
  per-fold range of 1.4x to 18x. It is reported as a range because the pooled number
  flatters.
- **Conformal walltime requests:** 95% empirical coverage at 4.6x the point prediction,
  against the 17x median blanket cushion in my actual sbatch requests. Cold-start
  campaigns honestly need ~100x, so the tight policy is scoped to run types with history.
- Seed families span roughly **30x in median cost** within one source, checked within
  single campaigns to rule out campaign confounding.

## Notebooks

| # | notebook | contents |
|---|----------|----------|
| 1 | [01_data_quality_and_eda](notebooks/01_data_quality_and_eda.ipynb) | the audit (structural missingness, censored runs, apportioned wall-times, a join trap) with decisions recorded inline, and the EDA that motivates the model |
| 2 | [02_cost_model_and_walltime](notebooks/02_cost_model_and_walltime.ipynb) | leakage-aware evaluation, gradient-boosted cost model vs a ridge baseline, permutation importance on held-out campaigns, conformal walltime policy |

Part 3 (planned) replays both policies against the recorded launch history to attach
wall-hours saved to each.

## Data and confidentiality

The research behind this telemetry is unpublished, so the exported dataset contains
**solver telemetry only**: iteration counts, residual magnitudes, wall-clock, solver
settings, grid sizes, seed-family names, machine ids. Physics payloads are dropped at
parse time, physical cell coordinates are replaced by salted opaque ids, and campaign
names are anonymized.

This is enforced, not promised: a leak-audit test suite gates every export (column
whitelists, forbidden-pattern scans over all string values, opaque-id checks, git
hygiene checks) and runs in CI on every push. The per-source parsers read the private
research trees directly, so they stay out of the public repo; what is public is the
redaction contract ([export/schema.py](export/schema.py)), the config-driven builder,
and the audit itself ([tests/test_leak_audit.py](tests/test_leak_audit.py)).

## Layout

- `data/` the redacted parquet tables (runs, iterations, requests); the committed
  artifact everything else reads
- `notebooks/` the analysis
- `export/` redaction contract and dataset builder (parsers and source paths are
  local-only)
- `tests/` the leak audit
- `warehouse/` DuckDB build, regenerated from parquet, not committed

## Reproduce

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest tests -q            # leak audit over the committed parquet
jupyter notebook           # notebooks read data/*.parquet directly
```

Rebuilding `data/` from scratch requires the private source trees plus
`export/sources.local.json` (see `sources.example.json` for the shape). Everything
else, including both notebooks, runs from the committed parquet.

## License

MIT.
