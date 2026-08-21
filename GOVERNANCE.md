# Governance

Agent Reliability Lab is maintainer-led. Maintainers review changes through pull
requests, apply the same evidence and artifact-integrity gates to their own work, and
make release decisions in the public repository except for embargoed security matters.

## Decision principles

1. Safety and credential boundaries override convenience.
2. Frozen artifacts and negative results are not rewritten.
3. Code, tests, public evidence, and claim wording must agree.
4. Stable Protocol compatibility is preferred over historical package migration.
5. A provider study requires explicit authorization, frozen cost/data scope, and a
   preregistered evidence plan; normal CI and review never execute it.

Routine changes are accepted by maintainer review. Changes to evidence schemas,
estimands, readiness gates, security boundaries, or governance require a documented
rationale, compatibility analysis, and at least one maintainer approval. A maintainer
with a material conflict should recuse from the final decision.

Release authority, current maintainers, and succession expectations are listed in
[MAINTAINERS.md](./MAINTAINERS.md). Governance amendments use normal pull requests and
must not retroactively change a study contract or claim state.
