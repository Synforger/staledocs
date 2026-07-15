"""staledocs — deterministic drift detection between code and docs.

The detection path is 100% deterministic (git blob hashes, commit topology,
anchor grepping). Semantic reconciliation is intentionally out of scope: the
tool reports *that* and *where* a doc/code pair broke coherence, and leaves
the judgement call (fix the doc, fix the code, or ack as-is) to a human or an
AI agent consuming the JSON report.
"""

__version__ = "1.2.0"
