#!/usr/bin/env python3
"""SIG maintainability model, eight system properties, computed read-only from a JavaScript/TypeScript repo.

Count-weighted approximation of the SIG/TUViT risk-profile method: unit-level properties use function
counts per risk band (the published method weights by lines in units); thresholds follow the published
2016 SIG model. Tools: eslint@9 (complexity, max-lines-per-function, max-params) and jscpd, both via npx.
Components are the second-level directories under the source roots you pass in.

usage: sig_eight.py REPO "src dirs" [duplication_pct]
Output: JSON, property -> {stars, value, note}; "_overall" is the mean of the stars.
"""
import os, re, json, subprocess, collections, statistics, sys

IGNORE = ('node_modules', '/dist', '/build', '/coverage', '/out', '__tests__', '/tests', '/test', '/vendor', '/.next')

def sh(cmd, cwd, timeout=900):
    try: return subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True, timeout=timeout).stdout
    except Exception: return ""

def eslint_msgs(repo, dirs, rule):
    ign = ' '.join(f"--ignore-pattern '**/{p.strip('/')}/**'" for p in ('node_modules','dist','build','coverage','out','vendor','.next'))
    out = sh(f"npx --yes eslint@9 --no-config-lookup --no-inline-config {ign} --ignore-pattern '**/*.test.*' --ignore-pattern '**/*.spec.*' --rule '{rule}' --format json {dirs} 2>/dev/null", repo)
    i = out.find('[')
    if i < 0: return None
    try: d = json.loads(out[i:])
    except Exception: return None
    return [m for f in d for m in f.get('messages', []) if m.get('ruleId')]

def stars_from_profile(mod, high, vhigh, T):
    """T: (moderate, high, very_high) maximum percentages for 5, 4, 3, 2 stars."""
    for s, (tm, th, tv) in zip([5, 4, 3, 2], T):
        if mod <= tm and high <= th and vhigh <= tv: return s
    return 1

def src_files(repo, dirs):
    files = []
    for d in dirs.split():
        for root, _, fs in os.walk(os.path.join(repo, d)):
            if any(x in root for x in IGNORE): continue
            for f in fs:
                if re.search(r'\.(js|jsx|mjs|cjs|ts|tsx)$', f) and not re.search(r'\.(test|spec|d)\.', f): files.append(os.path.join(root, f))
    return files

def compute(repo, dirs, dup_pct=None):
    R = {}
    files = src_files(repo, dirs)
    loc = {}
    for f in files:
        try: loc[f] = sum(1 for l in open(f, errors='ignore') if l.strip() and not l.strip().startswith('//'))
        except Exception: loc[f] = 0
    total = sum(loc.values())
    # 1 volume (published thresholds in KLOC, Java-equivalent)
    s = 5 if total < 66000 else 4 if total < 246000 else 3 if total < 665000 else 2 if total < 1310000 else 1
    R['Volume'] = dict(stars=s, value=f"{total:,} LOC", note=f"{len(files)} source files, tests excluded")
    # 2 duplication
    if dup_pct is not None:
        s = 5 if dup_pct <= 3 else 4 if dup_pct <= 5 else 3 if dup_pct <= 10 else 2 if dup_pct <= 20 else 1
        R['Duplication'] = dict(stars=s, value=f"{dup_pct}%", note="jscpd, clones of 6+ lines")
    else: R['Duplication'] = dict(stars=None, value="no data", note="jscpd not run")
    # 3 to 5: unit size, unit complexity, unit interfacing via eslint
    allf = eslint_msgs(repo, dirs, 'max-lines-per-function:[warn,{"max":0}]')
    nfun = len(allf) if allf else 0
    def pct(n): return round(100 * n / nfun, 1) if nfun else None
    if nfun:
        e15 = len(eslint_msgs(repo, dirs, 'max-lines-per-function:[warn,{"max":15,"skipBlankLines":true,"skipComments":true}]') or [])
        e30 = len(eslint_msgs(repo, dirs, 'max-lines-per-function:[warn,{"max":30,"skipBlankLines":true,"skipComments":true}]') or [])
        e60 = len(eslint_msgs(repo, dirs, 'max-lines-per-function:[warn,{"max":60,"skipBlankLines":true,"skipComments":true}]') or [])
        mod, high, vh = pct(e15 - e30), pct(e30 - e60), pct(e60)
        T = [(19.5, 10.9, 3.9), (26.0, 15.5, 6.5), (34.1, 22.2, 11.0), (45.9, 31.4, 18.1)]
        R['Unit size'] = dict(stars=stars_from_profile(mod, high, vh, T), value=f"{pct(e30)}%", note=f"functions over 30 lines; {nfun:,} functions; bands >15 {mod}% >30 {high}% >60 {vh}%")
        c5 = len(eslint_msgs(repo, dirs, 'complexity:[warn,5]') or []); c10 = len(eslint_msgs(repo, dirs, 'complexity:[warn,10]') or []); c25 = len(eslint_msgs(repo, dirs, 'complexity:[warn,25]') or [])
        mod, high, vh = pct(c5 - c10), pct(c10 - c25), pct(c25)
        T = [(25.0, 0.0, 0.0), (30.0, 5.0, 0.0), (40.0, 10.0, 0.0), (50.0, 15.0, 5.0)]
        R['Unit complexity'] = dict(stars=stars_from_profile(mod, high, vh, T), value=f"{pct(c10)}%", note=f"functions over cyclomatic 10; bands >5 {mod}% >10 {high}% >25 {vh}%")
        p2 = len(eslint_msgs(repo, dirs, 'max-params:[warn,2]') or []); p4 = len(eslint_msgs(repo, dirs, 'max-params:[warn,4]') or []); p6 = len(eslint_msgs(repo, dirs, 'max-params:[warn,6]') or [])
        mod, high, vh = pct(p2 - p4), pct(p4 - p6), pct(p6)
        T = [(12.1, 5.4, 2.2), (14.9, 7.2, 3.1), (17.7, 10.2, 4.8), (25.2, 15.3, 9.1)]
        R['Unit interfacing'] = dict(stars=stars_from_profile(mod, high, vh, T), value=f"{pct(p4)}%", note=f"functions with over 4 parameters; bands >2 {mod}% >4 {high}% >6 {vh}%")
    else:
        for k in ('Unit size', 'Unit complexity', 'Unit interfacing'): R[k] = dict(stars=None, value="no data", note="eslint did not run (is npx available?)")
    # 6 module coupling: fan-in per module from relative imports
    imp = re.compile(r"""(?:from\s+|require\()\s*['"](\.[^'"]+)['"]""")
    fan_in = collections.Counter(); comp_of = {}
    def comp(f):
        rel = os.path.relpath(f, repo).split(os.sep)
        return '/'.join(rel[:2]) if len(rel) > 2 else rel[0]
    edges = []
    for f in files:
        comp_of[f] = comp(f)
        try: txt = open(f, errors='ignore').read()
        except Exception: continue
        for m in imp.finditer(txt):
            tgt = os.path.normpath(os.path.join(os.path.dirname(f), m.group(1)))
            cands = [tgt] + [tgt + e for e in ('.js', '.jsx', '.mjs', '.cjs', '.ts', '.tsx', '/index.js', '/index.jsx', '/index.ts', '/index.tsx')]
            t = next((c for c in cands if c in loc), None)
            if t: fan_in[t] += 1; edges.append((f, t))
    def w(fs): return sum(loc[x] for x in fs)
    mod = round(100 * w([f for f in files if 10 < fan_in[f] <= 20]) / total, 1) if total else None
    high = round(100 * w([f for f in files if 20 < fan_in[f] <= 50]) / total, 1) if total else None
    vh = round(100 * w([f for f in files if fan_in[f] > 50]) / total, 1) if total else None
    T = [(6.6, 1.5, 0.7), (8.9, 3.8, 1.7), (13.6, 6.0, 3.4), (18.7, 11.4, 6.4)]
    R['Module coupling'] = dict(stars=stars_from_profile(mod or 0, high or 0, vh or 0, T), value=f"{round((mod or 0)+(high or 0)+(vh or 0),1)}%", note=f"LOC in modules with fan-in over 10; bands 11-20 {mod}% 21-50 {high}% >50 {vh}%")
    # 7 component balance: 1 minus Gini of component size
    csize = collections.Counter()
    for f in files: csize[comp_of[f]] += loc[f]
    sizes = sorted(v for v in csize.values() if v > 0); n = len(sizes)
    if n > 1:
        cum = sum((i + 1) * v for i, v in enumerate(sizes)); gini = (2 * cum) / (n * sum(sizes)) - (n + 1) / n
        bal = round(1 - gini, 2)
    else: bal = None
    s = None if bal is None else 5 if bal >= 0.9 else 4 if bal >= 0.7 else 3 if bal >= 0.5 else 2 if bal >= 0.3 else 1
    R['Component balance'] = dict(stars=s, value=f"{bal}", note=f"1 minus Gini of size across {n} components (second-level directories)")
    # 8 component independence: share of LOC not imported across a component boundary
    interface = set(t for f, t in edges if comp_of.get(f) != comp_of.get(t))
    hidden = round(100 * w([f for f in files if f not in interface]) / total, 1) if total else None
    s = None if hidden is None else 5 if hidden >= 95 else 4 if hidden >= 90 else 3 if hidden >= 80 else 2 if hidden >= 70 else 1
    R['Component independence'] = dict(stars=s, value=f"{hidden}%", note="LOC not imported across a component boundary")
    st = [v['stars'] for v in R.values() if v['stars']]
    R['_overall'] = round(statistics.mean(st), 1) if st else None
    return R

if __name__ == '__main__':
    if len(sys.argv) < 3: print(__doc__); sys.exit(1)
    print(json.dumps(compute(os.path.expanduser(sys.argv[1]), sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else None), indent=1))
