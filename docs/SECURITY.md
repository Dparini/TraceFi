# Security model and reporting

TraceFi is a local observation library, not a sandbox or financial policy
executor. Caller instrumentation and explicitly chosen adapter code are trusted.
Market data, tool results, model outputs and browser-visible strings are untrusted.
The [threat model](../THREAT_MODEL.md) records impacts, mitigations and residual risks.

## Credentials and private data

Default recursive keys: `api_key`, `private_key`, `authorization`, `password`,
`secret`, `access_token`, `refresh_token`. Matching ignores case, hyphens and
underscores. Custom keys extend defaults; structural/control keys are rejected.
Use `collector.secret(value)` for sensitive values under unknown names or within
arrays. It is a wrapper, not a decorator.

Redaction occurs before canonicalization, hashes, persistence and public reports.
Hashes deliberately cover stored redacted data; secret-dependent exact replay is
unavailable. Exception messages are omitted from traces and sanitized on the CLI.
Free-text credentials, sensitive dictionary keys, external adapter printing and
application logs cannot be automatically recognized or controlled. Wrap or remove
those values before capture. Authorized exports still contain non-secret portfolio data.

## Files, storage and HTTP

New SQLite files and exports are mode 0600 on POSIX. Existing database permissions
are preserved. Final-path database symlinks are refused; exports use a private
same-directory temporary file followed by atomic create-if-absent publication.
Existing filenames, including symlinks, are never overwritten. Parent directories
must be trusted; no race-proof guarantee against another local filesystem owner
is asserted. Process termination can leave an unlinked temporary export or lose
an in-flight trace; there is no streaming durability claim.

SQLite writes are transactional; reads verify trace/component/combined hashes,
indexed metadata, spans, parent graphs and artifact references. No pickle,
eval-based deserialization or trace-selected Python imports are used. Plain hashes
are not authenticated: a writer able to rewrite all data and hashes can forge history.

The dashboard listens on 127.0.0.1, validates single Host/Origin headers, sends no
CORS allowance, and serves bounded allowlisted counterfactual computations using
only synthetic built-in adapters. There are no data-mutation endpoints. React
renders text/JSON, HTML exports escape content and text reports escape control
characters. This is not an authenticated multi-user server; local programs and
extensions can access allowed local data. Do not publicly reverse-proxy it.

JSON, numbers, timestamps and datasets have [explicit limits](API.md). Total DB
size, HTTP concurrency, arbitrary adapter execution time and filesystem directory
traversal work are not globally bounded. Local denial of service remains possible.

## Models and dependencies

`module:factory` executes reviewed local Python with normal process permissions;
TraceFi cannot guarantee side-effect-free behavior for third-party code. Built-ins
perform no financial transactions. Optional Ollama is loopback-only, disables
proxies/redirects and strictly bounds response parsing; live model output quality
is not qualified. Neither temperature zero nor two matching calls proves determinism.

The core has no third-party runtime Python dependencies. Frontend dependencies
and optional development tools are separately audited. The release review found
no known npm vulnerabilities and corrected a pip tooling advisory by updating to
26.2.1, after which the local Python dependency audit passed. Advisory databases
change: this dated observation is not an ongoing security assurance.

## Responsible reports

Do not post private traces, keys or account data in public issues. Report a
reproducible issue with synthetic data and affected version through the repository's
available private security-reporting channel when enabled; otherwise contact the
maintainer using their published GitHub contact method before sharing sensitive
exploit details. No unconfigured email or reporting capability is promised.

See [release validation](RELEASE_VALIDATION.md), [release notes](RELEASE_NOTES.md),
and [limitations](LIMITATIONS.md). No certification or formal verification is claimed.
