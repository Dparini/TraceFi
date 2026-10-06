# Contributing

TraceFi focuses on observe → reproduce → compare → diagnose. Contributions
must explain how they improve that workflow. Do not introduce real-money trading,
mandatory cloud services or internal chain-of-thought capture.

Use Python 3.10+ and keep the core dependency-free. Run
`python3 -m unittest discover -s tests -v`. Install a development checkout with
`python3 -m pip install -e .`. For dashboard edits, use Node 22+, `npm ci` and
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
