---
name: code-quality-benchmark
description: "Measure a JavaScript or TypeScript repository against published quality benchmarks and write an HTML scorecard: the eight SIG maintainability properties (1 to 5 stars, industry median 3.0), change failure rate per merge, merges per week, pull-request lead time and reviews per PR, duplication, test count, open vulnerabilities. Read-only, no estimates, every value carries its source. Triggers: \"/code-quality-benchmark\", \"benchmark this codebase\", \"SIG rating\", \"quality scorecard\", \"how maintainable is this repo\"."
---

# Code quality benchmark

Point it at a repository and run it. It writes `quality-report/index.html` (plus a JSON file per run and a `history.json` so the next run shows deltas) and prints a plain-text summary you can paste anywhere.

Everything is measured from the repository and its git history. Nothing is written inside the repository. A measure that cannot be collected shows "no data" and is left out of the roll-up.

## Run it

```bash
python3 scripts/quality_report.py --repo /path/to/your/repo --src "src"
open quality-report/index.html
```

Requirements: Python 3.9 or newer, git, and `npx` (Node 18 or newer). The SIG and duplication collectors fetch `eslint@9` and `jscpd` through `npx --yes`; the first run downloads them. For pull-request lead time and reviews per PR, install the GitHub CLI and run `gh auth login` first; without it those two rows read "no data".

The run takes 2 to 10 minutes on a 200k-line repository. Most of it is jscpd and the eslint passes.

## What to customize

| Flag | Default | Set it when |
|---|---|---|
| `--src "dir dir"` | `src` | your source lives elsewhere: `--src "server client"`, `--src "packages/api/src packages/web/src"`. Space-separated, relative to the repo root. Tests, `dist`, `build`, `coverage`, `node_modules` and `vendor` are skipped automatically. |
| `--base BRANCH` | the remote default branch | merges land somewhere other than `origin/HEAD` (for example `develop`). |
| `--days N` | `28` | you want a longer or shorter window for the git and PR measures. |
| `--out DIR` | `./quality-report` | you want the report and history somewhere else. Keep the same folder run to run so the deltas work. |
| `--skip-jscpd` | off | jscpd is too slow on your repository. Duplication then reads "no data" and the SIG duplication property is left out. |
| `--no-gh` | off | you do not want the script to call the GitHub CLI. |

Components for the two SIG component properties are the second-level directories under the source roots you pass (`server/routes`, `client/src`, and so on). If your repository is structured differently, pass the roots that make your components second-level, or read those two rows as approximate.

## What it measures, and against what

| Measure | Source | Benchmark quoted on the page |
|---|---|---|
| SIG maintainability, eight properties: volume, duplication, unit size, unit complexity, unit interfacing, module coupling, component balance, component independence | `eslint@9` rules `max-lines-per-function`, `complexity`, `max-params` at the published SIG risk bands; `jscpd`; a relative-import graph | Median code base 3.0 stars; certified 4; top 5 percent at 5 |
| Change failure rate | revert, hotfix and rollback commit subjects per merge commit on the base branch | DORA's elite cluster is about 5 percent. DORA counts failed deployments; this counts failed merges. Say which unit you are quoting. |
| Merges to base per week | `git log --merges` | DORA elite deploys on demand; a typical team deploys weekly to monthly |
| PR lead time, median and p90 | `gh pr list`, opened to merged | DORA measures commit to production; this is opened to merged |
| Reviews per merged PR | `gh pr list` review submissions | A typical PR gets a single reviewer |
| Duplicated code | `jscpd`, clones of 6 or more lines | SIG: 5 stars under 3 percent, 4 under 5, 3 under 10 |
| Automated test cases | `it(` and `test(` in test files | a count, not scored |
| High or critical vulnerabilities | `npm audit --omit=dev` | zero |

The SIG collector is a count-weighted approximation of the SIG/TUViT method (the published method weights unit-level risk by lines of code; this weights by function count) with the published 2016 thresholds. It measures JavaScript and TypeScript only. It is not a SIG certification. Say "measured with SIG's published model" when you quote it.

Squash-merge repositories have no merge commits on the base branch. The script then reports PRs merged per week from the GitHub CLI and uses that as the change-failure denominator where it can; otherwise the change failure row shows the count with no rate.

## Publishing a result

Quote the value, the date, the window and the branch. Publish the weak properties with the strong ones; a scorecard that shows only the green rows is not a scorecard. Run it weekly into the same output folder and the page shows the delta.

## Files

- `scripts/quality_report.py`: the collector and the HTML renderer
- `scripts/sig_eight.py`: the SIG model on its own; `python3 scripts/sig_eight.py REPO "src" [duplication_pct]` prints the eight properties as JSON
