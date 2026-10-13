# Contributing

TraceFi focuses on observe → reproduce → compare → diagnose. Keep the local,
dependency-free Python runtime and SQLite architecture. Do not add real-money
execution, mandatory services or hidden chain-of-thought capture. Changes must
explain their effect on correctness or a demonstrated investigation workflow.

## Development and validation

Use Python 3.10+; CI checks 3.10, 3.12 and 3.14.

```bash
python -m pip install -e '.[dev]'
ruff check tracefi tests scripts examples benchmarks
ruff format --check tracefi tests scripts examples benchmarks
mypy tracefi
python -m pytest -q
HYPOTHESIS_PROFILE=stress python -m pytest -q tests/test_properties.py tests/test_release_hardening.py
python -m build
```

Normal Hypothesis checks use up to 200 examples; stress uses up to 2,000.
Finite domains may exhaust earlier. Test semantic invariants, not implementation
line counts. The mutation profile uses 40 examples to bound runtime.

```bash
python -m pip install -e '.[mutation]'
HYPOTHESIS_PROFILE=mutation mutmut run --max-children 4
mutmut results
```

Review surviving logic mutants; message-only mutations and equivalent changes
require explicit justification, not a blanket score target. Mutation scope covers
hashing, redaction/export, attribution/replay, boundary search and SQLite.
Historical results are preserved; [release validation](docs/RELEASE_VALIDATION.md)
identifies the actually exercised scope.

## Browser and packaging

```bash
cd dashboard
npm ci
npm audit
npm run build
cd ..
python -m pip install -e '.[ui]'
python -m playwright install chromium
python scripts/check_dashboard.py
python scripts/check_install.py
```

Commit rebuilt packaged web assets when frontend source changes; installed
wheels must work without Node or a CDN. `check_install.py` clones the committed
checkout, builds wheel/sdist, rebuilds the sdist, and tests wheel and editable
installs outside the source tree. Editable bootstrap downloads free build tools;
installed demos have no network requirement. Commit the intended changes before
using this clean-clone gate. Dist directories, local DBs, mutation caches and
virtual environments are ignored and must not be committed.

## Contracts and releases

Canonical format changes require an explicit version/migration design and
compatibility tests. Supported old traces must not be silently rewritten.
Instrument actual state and distinguish observed evidence, inferred explanation
and unknowns. Synthetic datasets must be labeled and run offline.

PRs should describe the trigger, resulting behavior, verification and material
limits. Never commit credentials, private traces or machine-specific settings.
Keep financial comparisons honest: proposed exposure/cost is not an executed
position, and counterfactual sensitivity is not causal proof.

Before tagging, run required checks, qualify clean installation and verify green
remote CI. A release must point to that validated commit and include measured
validation, installation instructions, assets/checksums and known limitations.
Do not overwrite published tags/releases or publish to PyPI without verified
package ownership and explicit publication authorization.
