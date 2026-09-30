#!/usr/bin/env python3
"""Code quality benchmark: measures a git repository and writes an HTML scorecard plus JSON.

Read-only. Nothing is written inside the repository. Every value carries its source; a measure that
cannot be collected renders "no data" and is left out of the roll-up. Nothing is estimated.

usage: quality_report.py --repo DIR [--src "src lib"] [--base main] [--days 28] [--out DIR] [--skip-jscpd] [--no-gh]

Measures
  Delivery (git):     merges to the base branch per week; change failure rate (revert/hotfix/rollback
                      commits per merge); share of commits that are fixes
  Delivery (gh):      pull-request lead time, median and p90 (opened to merged); reviews per merged PR
  Code:               automated test cases and files; duplicated code (jscpd); high/critical
                      vulnerabilities (npm audit)
  Architecture (SIG): the eight SIG maintainability properties, 1 to 5 stars each, and the overall
Benchmarks quoted in the report: SIG median 3.0 stars, certified 4, top 5 percent at 5; DORA change
failure rate, elite cluster about 5 percent. State the unit when you compare: this counts failed merges.
"""
import json, os, subprocess, statistics, datetime, html as H, shutil, argparse, sys

ap = argparse.ArgumentParser()
ap.add_argument('--repo', required=True)
ap.add_argument('--src', default='src')
ap.add_argument('--base', default='')
ap.add_argument('--days', type=int, default=28)
ap.add_argument('--out', default='')
ap.add_argument('--skip-jscpd', action='store_true')
ap.add_argument('--no-gh', action='store_true')
A = ap.parse_args()
REPO = os.path.abspath(os.path.expanduser(A.repo)); NAME = os.path.basename(REPO)
OUT = os.path.abspath(A.out or os.path.join(os.getcwd(), 'quality-report')); os.makedirs(OUT, exist_ok=True)
today = datetime.date.today().isoformat(); HIST = f"{OUT}/history.json"

def sh(cmd, cwd=None, timeout=300):
    try: return subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True, timeout=timeout).stdout
    except Exception: return ""
def score(v, good, bad):
    if v is None: return None
    s = (v - bad) / (good - bad) * 100
    return max(0.0, min(100.0, round(s, 1)))
M = []
def add(section, name, value, unit, sc, source, note=""):
    M.append(dict(section=section, name=name, value=value, unit=unit, score=sc, source=source, note=note))

if not os.path.isdir(f"{REPO}/.git"): print(f"{REPO} is not a git repository"); sys.exit(1)
base = A.base or sh("git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null", REPO).strip().replace('origin/', '') or 'main'
since = f"--since='{A.days} days ago'"

# ---- delivery from git
m = [l for l in sh(f"git log {base} --merges {since} --format=%h", REPO).splitlines() if l]
subj = sh(f"git log {base} {since} --no-merges --format=%s", REPO).splitlines()
squash = not m and subj  # squash-merge repos have no merge commits; fall back to PR count via gh below
add('delivery', 'Merges to base per week', round(len(m) / (A.days / 7), 1) if m else None, '/wk', score(len(m) / (A.days / 7), 40, 5) if m else None, f'git log {base} --merges, {A.days} days', f"{len(m)} merge commits" if m else 'no merge commits on the base branch (squash merges?); see PRs merged below')
bad = [s for s in subj if any(k in s.lower() for k in ('revert', 'hotfix', 'rollback', 'roll back'))]
den = len(m)
cfr = round(100 * len(bad) / den, 1) if den else None
add('delivery', 'Change failure rate (revert, hotfix, rollback commits per merge)', cfr, '%', score(cfr, 0, 30), f'git log subjects, {A.days} days', f"{len(bad)} such commits over {den} merges" if den else f"{len(bad)} such commits; no merge denominator")
fixes = [s for s in subj if s.lower().startswith('fix')]
add('delivery', 'Fix commits share', round(100 * len(fixes) / len(subj), 1) if subj else None, '%', None, f'git log subjects, {A.days} days', f"{len(fixes)} of {len(subj)} non-merge commits start with fix; a count, not scored")

# ---- delivery from GitHub pull requests (optional)
if not A.no_gh and shutil.which('gh'):
    cutoff = (datetime.date.today() - datetime.timedelta(days=A.days)).isoformat()
    raw = sh(f"gh pr list --state merged --base {base} --limit 500 --json number,createdAt,mergedAt,reviews --search 'merged:>={cutoff}' 2>/dev/null", REPO, timeout=600)
    try:
        prs = json.loads(raw or '[]')
        lts = sorted((datetime.datetime.fromisoformat(p['mergedAt'].replace('Z','+00:00')) - datetime.datetime.fromisoformat(p['createdAt'].replace('Z','+00:00'))).total_seconds() / 86400 for p in prs if p.get('mergedAt'))
        if lts:
            med = round(statistics.median(lts), 1); p90 = round(lts[int(0.9 * (len(lts) - 1))], 1)
            add('delivery', 'PR lead time, median (opened to merged)', med, ' days', score(med, 1, 14), f'gh pr list, {A.days} days', f"{len(lts)} merged PRs; p90 {p90} days")
            add('delivery', 'PR lead time, p90', p90, ' days', score(p90, 3, 30), 'gh pr list', '')
            rev = sum(len(p.get('reviews') or []) for p in prs)
            add('delivery', 'Reviews per merged PR', round(rev / len(prs), 1), 'x', score(rev / len(prs), 4, 1), 'gh pr list (reviews)', f"{rev} review submissions on {len(prs)} PRs")
            if not m: add('delivery', 'PRs merged per week', round(len(prs) / (A.days / 7), 1), '/wk', score(len(prs) / (A.days / 7), 40, 5), 'gh pr list', f"{len(prs)} PRs merged into {base}")
        else: add('delivery', 'PR lead time, median (opened to merged)', None, ' days', None, 'gh pr list', 'no merged PRs in the window, or gh not authenticated')
    except Exception as e: add('delivery', 'PR lead time, median (opened to merged)', None, ' days', None, 'gh pr list', f'unavailable: {e}')
else: add('delivery', 'PR lead time, median (opened to merged)', None, ' days', None, 'gh', 'skipped (install and authenticate the GitHub CLI to collect PR lead time and reviews)')

# ---- code
tf = sh(f"find {A.src} -type f \\( -name '*.test.*' -o -name '*.spec.*' -o -path '*/__tests__/*' \\) -not -path '*/node_modules/*' 2>/dev/null | wc -l", REPO).strip()
tc = sh(f"grep -rhoE '^\\s*(it|test)\\(' --include='*.test.*' --include='*.spec.*' {A.src} 2>/dev/null | wc -l", REPO).strip()
add('code', 'Automated test cases', int(tc or 0), '', None, "grep it(/test( in *.test.* and *.spec.*", f"{tf} test files; a count, not scored")
if not A.skip_jscpd and shutil.which('npx'):
    tmp = f"/tmp/jscpd-{NAME}"
    out = sh(f"rm -rf {tmp}; npx --yes jscpd --silent --reporters json --output {tmp} --ignore '**/node_modules/**,**/dist/**,**/build/**,**/coverage/**,**/out/**,**/vendor/**' {A.src} >/dev/null 2>&1; cat {tmp}/jscpd-report.json 2>/dev/null", REPO, timeout=1800)
    try:
        j = json.loads(out); pct = round(float(j['statistics']['total']['percentage']), 1)
        add('code', 'Duplicated code', pct, '%', score(pct, 2, 12), f'jscpd ({A.src})', f"{j['statistics']['total']['clones']} clones, {j['statistics']['total']['lines']} lines scanned")
    except Exception: add('code', 'Duplicated code', None, '%', None, 'jscpd', 'not run (npx or jscpd unavailable, or timed out)')
else: add('code', 'Duplicated code', None, '%', None, 'jscpd', 'skipped')
if os.path.exists(f"{REPO}/package-lock.json"):
    aud = sh("npm audit --json --omit=dev 2>/dev/null", REPO, timeout=300)
    try:
        a = json.loads(aud); v = a.get('metadata', {}).get('vulnerabilities', {}); hc = int(v.get('high', 0)) + int(v.get('critical', 0))
        add('code', 'High or critical vulnerabilities open', hc, '', score(hc, 0, 5), 'npm audit --omit=dev', f"critical {v.get('critical',0)}, high {v.get('high',0)}, moderate {v.get('moderate',0)}, low {v.get('low',0)}")
    except Exception: add('code', 'High or critical vulnerabilities open', None, '', None, 'npm audit', 'audit failed')
else: add('code', 'High or critical vulnerabilities open', None, '', None, 'npm audit', 'no package-lock.json at the repo root')

# ---- architecture: SIG eight
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from sig_eight import compute as _sig
    dup = next((x['value'] for x in M if x['name'] == 'Duplicated code'), None)
    SIG = _sig(REPO, A.src, dup)
    for k, v in SIG.items():
        if k.startswith('_'): continue
        add('architecture', f'SIG {k.lower()}', v['stars'], ' star' if v['stars'] == 1 else ' stars', None if v['stars'] is None else round(v['stars'] * 20, 1), 'SIG model via eslint + import graph', f"{v['value']}; {v['note']}")
    add('architecture', 'SIG maintainability, overall', SIG.get('_overall'), ' stars', None if SIG.get('_overall') is None else round(SIG['_overall'] * 20, 1), 'mean of the eight', 'count-weighted approximation of the SIG/TUViT method; JavaScript and TypeScript only')
    json.dump(SIG, open(f"{OUT}/sig-{today}.json", 'w'), indent=1)
except Exception as e:
    add('architecture', 'SIG maintainability, overall', None, ' stars', None, 'sig_eight.py', f'failed: {e}')

# ---- roll-up and page
def sect(s):
    xs = [x['score'] for x in M if x['section'] == s and x['score'] is not None]; return round(statistics.mean(xs), 1) if xs else None
S = {s: sect(s) for s in ['delivery', 'code', 'architecture']}
hist = json.load(open(HIST)) if os.path.exists(HIST) else []
prev = next((h for h in reversed(hist) if h['date'] != today), None)
def pv(name): return next((x['value'] for x in prev['metrics'] if x['name'] == name), None) if prev else None
LOWER = {'Change failure rate (revert, hotfix, rollback commits per merge)', 'Fix commits share', 'Duplicated code', 'High or critical vulnerabilities open', 'PR lead time, median (opened to merged)', 'PR lead time, p90'}
def arrow(n, o, higher=True):
    if n is None or o is None: return '<span class=muted>no prior</span>'
    if n == o: return '<span class=muted>&#9679; 0</span>'
    good = (n > o) if higher else (n < o); cls = 'up' if good else 'down'; sym = '&#9650; ' if n > o else '&#9660; '
    return f'<span class={cls}>{sym}{round(n-o,1)}</span>'
entry = dict(date=today, sections=S, metrics=[{k: x[k] for k in ('section', 'name', 'value', 'unit', 'score', 'note')} for x in M])
hist = [h for h in hist if h['date'] != today] + [entry]
json.dump(hist, open(HIST, 'w'), indent=1); json.dump(entry, open(f"{OUT}/{today}.json", 'w'), indent=1)
def fmt(v, u):
    if v is None: return '<span class=muted>no data</span>'
    return (f"{v:,}" if isinstance(v, int) else f"{v}") + u
def tile(label, v, pvv, higher=True):
    return f"<div class=tile><div class=tl>{label}</div><div class=tv>{'no data' if v is None else v}</div><div class=td>{arrow(v, pvv, higher)}</div></div>"
SIGO = next((x['value'] for x in M if x['name'] == 'SIG maintainability, overall'), None)
CFR = next((x['value'] for x in M if x['name'].startswith('Change failure')), None)
DUP = next((x['value'] for x in M if x['name'] == 'Duplicated code'), None)
tiles = tile('SIG maintainability (median 3.0)', SIGO, pv('SIG maintainability, overall')) + tile('Change failure rate', CFR, pv('Change failure rate (revert, hotfix, rollback commits per merge)'), False) + tile('Duplication', DUP, pv('Duplicated code'), False) + ''.join(tile(k.title() + ' score', S[k], prev and prev['sections'].get(k)) for k in ['delivery', 'code', 'architecture'])
sec = ''
for s, title in [('delivery', 'Delivery'), ('code', 'Code'), ('architecture', 'Architecture (SIG eight)')]:
    rows = ''.join(f"<tr><td>{H.escape(x['name'])}</td><td class=n>{fmt(x['value'], x['unit'])}</td><td class=d>{arrow(x['value'], pv(x['name']), x['name'] not in LOWER)}</td><td class=n>{'—' if x['score'] is None else x['score']}</td><td class=muted>{H.escape(x['source'])}</td><td class=muted>{H.escape(x['note'])}</td></tr>" for x in M if x['section'] == s)
    sec += f"<h2>{title} <span class=muted>score {'no data' if S.get(s) is None else S[s]}</span></h2><table><tr><th>Measure</th><th class=n>Value</th><th class=d>Delta</th><th class=n>Score</th><th>Source</th><th>Note</th></tr>{rows}</table>"
trend = ''.join(f"<tr><td>{h['date']}</td>" + ''.join(f"<td class=n>{'—' if h['sections'].get(k) is None else h['sections'][k]}</td>" for k in ['delivery', 'code', 'architecture']) + "</tr>" for h in hist[-12:])
page = f"""<!doctype html><meta charset=utf-8><title>Code quality {NAME} {today}</title>
<style>
body{{font:14px/1.5 -apple-system,"Helvetica Neue",Helvetica,Arial,sans-serif;color:#1a1a1a;margin:0;padding:32px;max-width:1040px}}
h1{{font-size:24px;margin:0 0 4px}} h2{{font-size:13px;text-transform:uppercase;letter-spacing:.07em;color:#6b6b6b;margin:34px 0 8px;border-bottom:1px solid #e5e5e5;padding-bottom:6px}}
.sub{{color:#6b6b6b;margin:0 0 24px}} table{{border-collapse:collapse;width:100%;margin:0 0 8px}}
th,td{{text-align:left;padding:7px 10px;border-bottom:1px solid #eee;vertical-align:top}} th{{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#6b6b6b}}
.n,.d{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}} .muted{{color:#9a9a9a}} .up{{color:#2e7d4f}} .down{{color:#c0392b}}
.tiles{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:8px 0 8px}} .tile{{background:#f4f4f6;border-radius:8px;padding:14px 16px}}
.tl{{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#555}} .tv{{font-size:30px;font-weight:700;line-height:1.2}} .td{{font-size:12px}}
</style>
<h1>Code quality &mdash; {H.escape(NAME)} &mdash; {today}</h1>
<p class=sub>SIG maintainability is the mean of eight properties, 1 to 5 stars; the industry median is 3.0, certified systems score 4, the top 5 percent score 5. Change failure rate here counts revert, hotfix and rollback commits per merge (DORA counts failed deployments; its elite cluster is about 5 percent). Sources: {H.escape(REPO)} on {H.escape(base)}, {A.days} days. Read-only. Deltas are against the previous run in this output folder.</p>
<div class=tiles>{tiles}</div>
{sec}
<h2>Trend</h2><table><tr><th>Run</th><th class=n>Delivery</th><th class=n>Code</th><th class=n>Architecture</th></tr>{trend}</table>
<p class=muted>Every value is measured; nothing is estimated. Scores are linear bands stated in the script (0 to 100 per measure). "no data" rows are left out of the section score.</p>
"""
open(f"{OUT}/{today}.html", 'w').write(page); open(f"{OUT}/index.html", 'w').write(page)

# ---- plain-text summary for pasting
def val(name):
    x = next((x for x in M if x['name'] == name), None); return 'no data' if not x or x['value'] is None else f"{x['value']}{x['unit']}"
print(f"Code quality, {NAME}, {today}, {base}, last {A.days} days")
print(f"  SIG maintainability: {val('SIG maintainability, overall')} (median 3.0)")
for k in ['volume', 'duplication', 'unit size', 'unit complexity', 'unit interfacing', 'module coupling', 'component balance', 'component independence']:
    print(f"    {k}: {val('SIG ' + k)}")
print(f"  Change failure rate (per merge): {val('Change failure rate (revert, hotfix, rollback commits per merge)')}")
print(f"  Merges to base per week: {val('Merges to base per week')}")
print(f"  PR lead time median: {val('PR lead time, median (opened to merged)')}; reviews per merged PR: {val('Reviews per merged PR')}")
print(f"  Duplicated code: {val('Duplicated code')}; test cases: {val('Automated test cases')}; high/critical vulns: {val('High or critical vulnerabilities open')}")
print(f"  Report: {OUT}/index.html")
