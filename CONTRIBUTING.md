# Contributing

TraceFi focuses on observe → reproduce → compare → diagnose. Contributions
must explain how they improve that workflow. Do not introduce real-money trading,
mandatory cloud services or internal chain-of-thought capture.

Use Python 3.10+ and keep the core dependency-free. Run
`python3 -m pytest -q`, `ruff check tracefi tests scripts examples`,
`ruff format --check tracefi tests scripts examples` and `mypy tracefi`.
Install a development checkout with `python3 -m pip install -e ".[dev]"`.
For property stress tests set `HYPOTHESIS_PROFILE=stress`; normal CI uses 200
examples per property and stress uses 2,000 (finite domains can exhaust early).
Mutation testing: install `.[mutation]`, then run
`HYPOTHESIS_PROFILE=mutation mutmut run --max-children 4` and `mutmut results`.
Inspect surviving mutations; do not use the score as a correctness claim.
Run `python3 scripts/check_install.py` from a committed checkout with wheel
build tooling installed to verify a clean clone and isolated wheel installation.
New features are temporarily frozen; changes should resolve documented defects
or improve tests, security, documentation and validation. For dashboard edits, use Node 22+, `npm ci` and
`npm run build` in `dashboard/`, and commit the rebuilt packaged assets.

Test invariants and observable behavior: independent snapshots, stable hashes,
credential exclusion, integrity failure, honest unknown classification, replay
and counterfactual consistency. Synthetic scenarios must run offline and label
fault injection explicitly. Avoid tests that only mirror implementation lines.

Changes to canonicalization or persisted trace contracts require a version
change, migration design and compatibility tests. Distinguish observed facts,
likely attribution and untested assumptions in code, reports and documentation.

Pull requests should describe the trigger, resulting behavior, verification and
material limitations. Do not include keys, private traces or actual account data.
For security issues, avoid posting sensitive reproduction data publicly.
