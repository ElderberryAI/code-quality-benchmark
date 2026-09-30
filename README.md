# code-quality-benchmark

A read-only scorecard for a JavaScript or TypeScript repository: the eight SIG maintainability properties, change failure rate per merge, merges per week, PR lead time and reviews per PR, duplication, test count and open vulnerabilities, each with its source and the published benchmark next to it.

```bash
python3 scripts/quality_report.py --repo /path/to/your/repo --src "src"
open quality-report/index.html
```

See `SKILL.md` for the flags, the sources and the benchmarks. Use it as a Claude Code or Cowork skill (copy the folder into your skills directory) or run the scripts directly.

MIT. No data leaves your machine; the only network calls are `npx` fetching `eslint@9` and `jscpd`, and `gh` reading your own pull requests if you let it.
