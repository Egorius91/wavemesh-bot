# CI dependency cache and obsolete PR work

Related: wavevpn-saas#322. Four existing Python workflows request setup-python's pip download cache keyed from requirements.txt and Python/runner identity. They still install requirements in a fresh job and run every existing command. A cache hit is not an installed environment, an audit result, or permission to skip a test. No config.py, database, credential, workspace or virtual environment is cached. Existing action pins and dependency constraints are unchanged.

Dependencies are not fully pinned in requirements.txt. This change does not claim reproducible dependency resolution or fix that separate issue; installation and pip-audit remain live, including on cache hits. Do not cache a successful audit/test outcome. Measure normal later cache hits; do not create empty commits or rerun green jobs just to warm caches. No new workflow/job or scheduled cost check is introduced. Small source guards join the existing unittest discovery in Quality checks.

Concurrency groups include the workflow, event and PR/ref. Only obsolete runs of that same PR may be cancelled; main work and different suites/PRs are isolated. Pending/cancelled work is never CI proof. Existing trigger sets are preserved (payment-return remains PR-only, the other three also run on main). CodeQL and full-history secret scanning are unchanged. The legacy and SaaS payment-mode suites remain separate with their existing state/configuration boundaries.

Rollback: revert the isolated workflow cache/concurrency change. Cache misses remain valid and install everything normally; no blanket cache purge, billing, protection, database, runtime or deployment change is required. This public repository's standard-runner execution time is not an account dollar-saving claim.
