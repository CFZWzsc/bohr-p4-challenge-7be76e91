# Runtime contract

Bohrium Playground Period 4 submission — challenge `challenge-7be76e91` (track: `experimental-design`).

This repository holds the complete skill package for the challenge: the skill
definition, its executable entry point and all supporting scripts. No precomputed
answers, private data or credentials are included.

## Skill

- Name: `aligned-candidate-plan-comparison`
- Summary: Use when an experimental-design case supplies several candidate or versioned experiment plans and asks which one to choose, why, and what is rejected; run scripts/run_skill.py to place all plans on one comparable matrix with explicit units, cost and time arithmetic, weighted scoring, rejection reasons and sensitivity.

## Contents

| File |
|------|
| `SKILL.md` |
| `scripts/run_skill.py` |
| `README.md` |

## How to run

```bash
python scripts/run_skill.py --case /input/case.json --output /app/output/result.json
```

The entry point is `SKILL.md`; input/output contracts, error handling and a minimal
usage example are documented there.

## Notes

- Pure Python standard library; no network access required.
- The result JSON keeps the input case id, the main results, per-item evidence,
  a run status and an uncertainty section.
