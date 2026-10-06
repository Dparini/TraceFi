# Threat model

## Scope and trust boundaries

TraceFi collects local traces from caller instrumentation. The SDK and chosen
adapter code are trusted. Market feeds, retrieval records, tool outputs, agent
proposals, scenario files and browser-visible payloads are untrusted data. Local
filesystem owners and other processes with database access are outside the
integrity boundary. No real funds or private keys are needed by the examples.

Hashes cover redacted state and prove consistency only against a trusted
reference. They are not authentication, access control, a signature or proof of
financial correctness. Collection does not enforce the application's policy.

| Threat | Impact | Mitigation | Residual risk |
| --- | --- | --- | --- |
| Sensitive data leakage | Credentials or portfolio details exposed through logs and exports | Redact configured/default keys before hashing and storage; explicit `trace.secret`; exceptions stored by type only; new DB mode 0600; no server access logs | Free-text and unknown keys require caller redaction; authorized exports contain non-secret financial data; existing files retain their permissions |
| Private keys in traces | Financial account compromise | Default recursive private-key key matching, explicit wrappers, invariant tests across persisted database bytes | A key under an unknown field or embedded in an arbitrary string can leak; SDK does not scan all string contents |
| Prompt injection | Agent follows instructions embedded in retrieved metadata | Preserve source/content/suspicion metadata; classify suspicious input separately; deterministic demo treats metadata as data; reproducible snapshots | Observation is not a comprehensive prompt-injection defense; real adapters can obey malicious text |
| Trace tampering | False audit history or wrong replay state | Canonical SHA-256 component/combined/payload hashes; verify artifacts and spans on reads; atomic writes | An attacker able to rewrite payloads and all digests can forge history; deletion and freshness are not authenticated |
| Malicious agent output | Unsafe proposals, malformed fields, browser script injection | Deterministic proposal/policy checks in examples and evals; escape outputs in React/HTML; no execution during replay | Production callers must enforce policy; the SDK accepts JSON observations and does not independently validate every business constraint |
| Malicious tool output | Poisoned evidence or secrets in messages | Source metadata, redaction, safe serialization and escaped rendering; exceptions omit raw messages | Incorrect evidence may pass checks; sensitive free text and semantic attacks remain possible |
| Incorrect timestamps | Wrong apparent order or misleading freshness | UTC-aware normalized timestamps; naive Python datetime rejection; monotonic span durations; oracle age rules | Host clock and producer-provided freshness may be wrong; timestamp strings outside the recognized format are plain text; no trusted external time source or monotonic wall-time guarantee |
| Model non-determinism | Divergent replays and unreliable counterfactual attribution | Explicit adapters; full proposal diff; baseline reproduction checks; document one-run limits | One match is insufficient; temperature zero is not guaranteed determinism; statistical replay sampling is future work |
| Incomplete context | Misleading reproduction or missed failure | Record configurations, portfolio and retrieval contract; expose missing stages; refuse exact replay of redacted inputs | Instrumentation can omit hidden dependencies, code revisions, tool state or relevant evidence; no automatic completeness proof |
| Poisoned datasets | Biased regression conclusions, denial of service | Synthetic checked-in fixtures, deterministic CI, compare both agents on identical scenarios; no trace-driven code loading | User datasets can be misleading, large or deeply nested; JSON input size limits and provenance signatures are not implemented |
| False failure attribution | Wrong root-cause claims or misplaced confidence | Separate observed conditions from likely interpretations; multiple findings; unknown when evidence is missing; losses alone are insufficient | Rule coverage is incomplete; stale data may be irrelevant; sufficiency experiments cannot establish global causal truth |
| Local dashboard exposure | Another site or process reads financial traces | Bind 127.0.0.1; Host and Origin allowlists; no CORS; read-only GET API and experiments restricted to finite recorded financial inputs and the built-in deterministic adapter; CSP and no-store headers | Local processes, extensions and same-origin compromise can read data; dashboard has no authentication and must not be reverse-proxied publicly |
| Adapter code execution | Arbitrary local Python behavior | Adapter selected explicitly on CLI; never derived from trace metadata | `module:factory` executes trusted-by-user code; dependencies and Ollama server are separate trust boundaries |
| Process termination or storage failure | In-flight traces lost or application disrupted | Atomic final writes, explicit persistence errors | No streaming journal or retry queue; SDK can block on storage; callers must design failure handling |

## Operational guidance

Instrument only necessary data. Wrap unknown sensitive values before capture.
Do not store raw hidden reasoning transcripts. Keep the DB and exports private,
pin trusted adapter code and environments, and retain a digest outside the DB if
independent integrity comparison matters. Preserve original traces when analyzing
failures and distinguish synthetic injected faults from observed incidents.

Do not expose the dashboard outside loopback or rely on it as a multi-user audit
service. Do not feed actual signing keys into the observation context.

## Security verification

Tests assert secret sentinels never reach DB bytes, changed inputs change hashes,
reordered equivalent states hash identically, modified trace/span/artifact rows
fail verification, negative outcomes do not automatically become agent errors,
and HTML exports escape malicious content. These checks do not certify all
possible input paths or claim adversarial robustness.

The [2026-10-06 manual review](docs/SECURITY_REVIEW.md) records resolved
findings, their regression tests and remaining adapter, input and local-server
risks. See [API limits](docs/API.md#bounded-json-and-numeric-precision).
