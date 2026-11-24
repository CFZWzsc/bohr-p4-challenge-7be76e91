# Runtime contract

Bohrium Playground Period 4 submission — challenge `challenge-7be76e91` (track: `experimental-design`).

This repository holds the complete skill package for the challenge: the skill
definition, its executable pipeline and all supporting documents. No precomputed
answers, private data or credentials are included.

## Skill

- Name: `aligned-candidate-plan-comparison`
- Summary: Use when an experimental-design case supplies several candidate or versioned experiment plans and asks which one to choose, why, and what would change the choice; parses case.json and material files, places all plans on one comparable matrix with explicit units, cost/time arithmetic, feasibility levels, weighted scoring, missing-data accounting, sensitivity and cell-level locators.

## Contents

| File |
|------|
| `SKILL.md` |
| `assets/policy.json` |
| `examples/demo-case/case.json` |
| `examples/demo-case/materials/costs.csv` |
| `examples/demo-case/materials/time_and_risk.md` |
| `examples/quickstart.md` |
| `references/comparison-fields.md` |
| `references/costing-and-feasibility.md` |
| `references/recommendation-and-sensitivity.md` |
| `scripts/run_skill.py` |
| `scripts/sk_entry.py` |
| `README.md` |

## How to run

```bash
python scripts/sk_entry.py --input /input --work /app/work --out /app/output
```

A single deterministic pass reads `/input`, computes the deliverable and writes a
contract-complete `/app/output/result.json` plus the human-readable review files
described in `SKILL.md`. The same input always produces byte-identical output; no
network access is used, and fields the materials cannot support are reported
explicitly instead of being left empty.

## Notes

- Pure Python standard library; no network access required.
- Every claim is anchored to paragraph-level evidence; unknown items are reported
  in `uncertainty` instead of being fabricated.
