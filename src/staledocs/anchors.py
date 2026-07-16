"""Anchor extraction and liveness verification (detection layer L2).

Docs naturally quote code: function names, CLI flags, config keys, paths.
Those quotes are the cheapest deterministic tripwire we have — extract every
code-looking inline span from the doc and verify it still exists on the code
side. No AST, no language awareness: the doc is parsed, the code is only
grepped, which is what keeps the tool language-agnostic and lets a finding
point at the exact doc line that rotted.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .config import AnchorRule

_FENCE_RE = re.compile(r"^\s*(```|~~~)")
# inline code spans; double-backtick spans are matched first
_SPAN_RE = re.compile(r"``([^`\n]+)``|`([^`\n]+)`")

_CAMEL_RE = re.compile(r"[a-z][A-Z]")
_UPPER_SNAKE_RE = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)+$")
_NUMBERLIKE_RE = re.compile(r"^[\d\s.,:%+\-*/=<>()]+$")
_CODE_PUNCT = set("_./:-()[]<>=$@")


# a doc declares a not-built-yet reference as `planned:path/to/thing`.
# Declaration, not silence: pending markers stay visible as their own class
# in every report, and a marker whose path has landed is flagged for removal
PLANNED_PREFIX = "planned:"


@dataclass
class Anchor:
    doc: str
    line: int
    token: str
    path_like: bool
    doc_dir: str = ""
    planned: bool = False


@dataclass
class AnchorFinding:
    doc: str
    line: int
    token: str
    scope: str  # "pair" | "repo"
    planned: str = ""  # "" (a normal finding) | "pending" | "resolved"
    # pair-scope identifier misses only: where the token actually lives when
    # the wider repo still has it. The finding stays red — a same-named
    # survivor elsewhere must never soften a rename signal — but the triage
    # gets the evidence: cross-pair reference vs true rot at a glance
    hint: str = ""


def _looks_like_code(token: str, min_length: int) -> bool:
    if len(token) < min_length:
        return False
    if any(ch.isspace() for ch in token):
        return False
    if _NUMBERLIKE_RE.match(token):
        return False
    # `<placeholder>` notation is documentation convention, not a greppable
    # anchor (`docs/<name>.md`, `--flag <value>`); skip rather than false-flag
    if "<" in token or ">" in token:
        return False
    # machine-absolute paths (`~/.config/...`, `/usr/bin/...`), shell
    # variables (`$HOME/...`), and URLs live outside the repo — unverifiable
    if token.startswith(("~", "/", "$")) or "://" in token:
        return False
    # sample-output tokens (`7d:53%`, `ctx:███ 35%`): digits dominating the
    # letters, or block-element art — renderings, not identifiers
    letters = sum(ch.isalpha() for ch in token)
    digits = sum(ch.isdigit() for ch in token)
    if digits > letters:
        return False
    if any(ch in "█░▓▒" for ch in token):
        return False
    if token.startswith("--") or token.startswith("-") and len(token) > 2:
        return True
    if any(ch in _CODE_PUNCT for ch in token):
        return True
    if _CAMEL_RE.search(token):
        return True
    return bool(_UPPER_SNAKE_RE.match(token))


def _is_path_like(token: str) -> bool:
    if "://" in token:  # URL, not a repo path
        return False
    # call/assignment notation whose right side happens to contain a slash —
    # `exp(−d/λ)`, `VAR=/usr/bin/tool` — is an identifier, not a path: the
    # reference promises the bare-identifier fallback for these notations,
    # and the path branch must not capture them first. A real path never has
    # `(` or `=` before its first `/`.
    for sep in ("(", "="):
        if sep in token and ("/" not in token or token.index(sep) < token.index("/")):
            return False
    # `@scope/pkg` (and `@scope/pkg/subpath`) is a package specifier, not a
    # repo path — it verifies as an identifier instead: import statements
    # quote the specifier verbatim, so the grep checks that the dependency
    # the doc names is actually used by the paired code
    if token.startswith("@") and "/" in token:
        return False
    return "/" in token.strip("/") or token.startswith("./")



def extract(doc: str, text: str, rule: AnchorRule) -> list[Anchor]:
    """Code-looking inline spans with their 1-indexed doc line numbers."""
    anchors: list[Anchor] = []
    in_fence = False
    fence_marker = ""
    # two-stage ignore: exact match first (an entry always suppresses its own
    # literal token, glob metacharacters included), then fnmatch for entries
    # that carry glob characters — `research/*` covers ten sections in one
    # line instead of ten
    ignore_exact = set(rule.ignore)
    ignore_globs = [p for p in rule.ignore if any(ch in p for ch in "*?[")]

    def _token_ignored(token: str) -> bool:
        if token in ignore_exact:
            return True
        return any(fnmatch.fnmatchcase(token, p) for p in ignore_globs)
    for lineno, line in enumerate(text.splitlines(), start=1):
        fence = _FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
            continue
        if in_fence and not rule.include_fenced:
            continue
        for m in _SPAN_RE.finditer(line):
            token = (m.group(1) or m.group(2) or "").strip()
            planned = token.startswith(PLANNED_PREFIX)
            if planned:
                token = token[len(PLANNED_PREFIX):].strip()
            if not token or _token_ignored(token):
                continue
            if not planned and not _looks_like_code(token, rule.min_length):
                continue
            doc_dir = doc.rsplit("/", 1)[0] if "/" in doc else ""
            anchors.append(
                Anchor(
                    doc=doc,
                    line=lineno,
                    token=token,
                    path_like=_is_path_like(token),
                    doc_dir=doc_dir,
                    planned=planned,
                )
            )
    return anchors


_BRACE_GROUP_RE = re.compile(r"\{([^{}]*,[^{}]*)\}")


def expand_braces(token: str) -> list[str]:
    """Shell-style brace expansion: `bridge/{diag,logger}.cjs` -> both members.

    Docs use this shorthand constantly and each member is a real path claim,
    so verification expands before resolving and reports only the members
    that are missing. A brace without a comma (`{directive}` notation) is
    not a set and stays literal.
    """
    m = _BRACE_GROUP_RE.search(token)
    if not m:
        return [token]
    head, tail = token[: m.start()], token[m.end():]
    out: list[str] = []
    for part in m.group(1).split(","):
        out.extend(expand_braces(head + part.strip() + tail))
    return out


def _normalize_path_token(token: str) -> str:
    token = token.strip()
    for prefix in ("./",):
        if token.startswith(prefix):
            token = token[len(prefix):]
    return token.strip("/")


def _path_exists(
    token: str,
    all_files: set[str],
    all_dirs: set[str],
    path_roots: list[str] | None = None,
    doc_dir: str = "",
) -> bool:
    candidates = _path_candidates(token, path_roots, doc_dir)
    for cand in candidates:
        if cand in all_files or cand in all_dirs:
            return True
        if any(ch in cand for ch in "*?["):
            from . import globs

            if any(globs.matches(cand, f) for f in all_files):
                return True
    return False


def _path_candidates(
    token: str, path_roots: list[str] | None, doc_dir: str = ""
) -> list[str]:
    norm = _normalize_path_token(token)
    if not norm:
        return []
    cands = [norm] + [f"{r.strip('/')}/{norm}" for r in (path_roots or [])]
    # markdown-relative references (`../protocol/streams.md`, `launchd/x.plist`)
    # resolve against the doc's own directory
    if doc_dir:
        from posixpath import normpath

        rel = normpath(f"{doc_dir}/{token.strip()}")
        if not rel.startswith(".."):
            cands.append(rel.strip("/"))
    return cands


def _resolve_path(
    token: str,
    all_files: set[str],
    all_dirs: set[str],
    path_roots: list[str] | None = None,
    doc_dir: str = "",
) -> str | None:
    """The first candidate that names a tracked file (not a dir), or None."""
    for cand in _path_candidates(token, path_roots, doc_dir):
        if cand in all_files:
            return cand
    return None


class CodeIndex:
    """Lazy substring index over a set of files (content loaded once)."""

    def __init__(self, repo_root: Path, files: list[str]):
        self._repo_root = repo_root
        self._files = files
        self._blob: str | None = None

    def _load(self) -> str:
        if self._blob is None:
            parts: list[str] = []
            for rel in self._files:
                try:
                    parts.append(
                        (self._repo_root / rel).read_text(encoding="utf-8", errors="ignore")
                    )
                except OSError:
                    continue
            self._blob = "\n".join(parts)
        return self._blob

    def contains(self, token: str) -> bool:
        return token in self._load()

    def locate(self, token: str) -> str | None:
        """The first file containing the token — evidence for a hint, so a
        finding can say where a pair-missing identifier actually lives."""
        if token not in self._load():
            return None
        for rel in self._files:
            try:
                text = (self._repo_root / rel).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if token in text:
                return rel
        return None


@dataclass
class AnchorStatus:
    """Per-doc arming picture: how much of the doc the baseline covers."""

    doc: str
    armed: int = 0            # baseline claims still present in the doc
    unarmed: int = 0          # tokens in the doc that are not claims (yet)
    baseline_missing: bool = False
    unarmed_tokens: list[str] = field(default_factory=list)


@dataclass
class ResolveCtx:
    """Everything resolution needs, shared by record() and verify() so the
    two can never drift apart."""

    repo_root: Path
    pair_index: CodeIndex | None
    repo_index: CodeIndex
    all_files: set[str]
    all_dirs: set[str]
    path_roots: list[str] | None = None
    check_ignored: Callable[[list[str]], set[str]] | None = None
    branch_prefixes: list[str] | None = None
    _suffix_map: dict[str, list[str]] | None = None
    _basenames: set[str] | None = None

    def suffix_map(self) -> dict[str, list[str]]:
        if self._suffix_map is None:
            m: dict[str, list[str]] = {}
            for f in self.all_files:
                m.setdefault(f.rsplit("/", 1)[-1], []).append(f)
            self._suffix_map = m
        return self._suffix_map

    def basenames(self) -> set[str]:
        if self._basenames is None:
            self._basenames = {f.rsplit("/", 1)[-1] for f in self.all_files}
        return self._basenames

    def ignored(self, token: str, doc_dir: str = "") -> bool:
        if self.check_ignored is None:
            return False
        cands = _path_candidates(token, self.path_roots, doc_dir)
        return bool(cands) and bool(self.check_ignored(cands))


def _suffix_exists(token: str, ctx: ResolveCtx) -> bool:
    """Docs quote paths relative to their own subtree (`core/Foo.ts` inside a
    module) — a multi-segment token that is the tail of exactly some tracked
    path resolves. Same anywhere-match philosophy path anchors already have."""
    norm = _normalize_path_token(token)
    if "/" not in norm or any(ch in norm for ch in "*?["):
        return False
    base = norm.rsplit("/", 1)[-1]
    return any(f.endswith("/" + norm) for f in ctx.suffix_map().get(base, ()))


def _member_resolves(member: str, doc_dir: str, ctx: ResolveCtx) -> bool:
    """One path claim (a brace member or a whole path token)."""
    if _path_exists(member, ctx.all_files, ctx.all_dirs, ctx.path_roots, doc_dir):
        return True
    if _suffix_exists(member, ctx):
        return True
    return ctx.ignored(member, doc_dir)


def _identifier_resolves(token: str, doc_dir: str, ctx: ResolveCtx) -> bool:
    """One identifier claim: file tree first (a bare filename is a path
    reference without a slash), then the paired code only — searching the
    whole repo would let a same-named survivor elsewhere mask a rename."""
    if _path_exists(token, ctx.all_files, ctx.all_dirs, ctx.path_roots, doc_dir):
        return True
    # a dotted slashless token is a filename claim (`Foo.ts`, `README.ja.md`)
    # when any tracked file carries that basename
    if "." in token and token in ctx.basenames():
        return True
    if any(ch in token for ch in "*?[") and "/" not in token:
        from . import globs

        if any(globs.matches(token, b) for b in ctx.basenames()):
            return True
    index = ctx.pair_index if ctx.pair_index is not None else ctx.repo_index
    if index.contains(token):
        return True
    bare = _bare(token)
    if bare != token and len(bare) >= 2 and index.contains(bare):
        return True
    if "." in bare:
        tail = bare.rsplit(".", 1)[-1]
        if len(tail) >= 2 and index.contains(tail):
            return True
    return ctx.ignored(token, doc_dir)


def _claims(anchor: Anchor, ctx: ResolveCtx) -> list[tuple[str, bool]]:
    """(claim_key, resolves_now) for one anchor.

    Path tokens expand braces first — each member is its own claim, so a
    baseline can arm the members that existed and stay silent on the rest.
    A quoted branch name (`feature/dark-mode`) is never a claim.
    """
    token = anchor.token
    if "::" in token and "." in token.partition("::")[0]:
        path_part, _, symbol = token.partition("::")
        if ctx.ignored(path_part, anchor.doc_dir):
            return [(token, True)]
        resolved = _resolve_path(
            path_part, ctx.all_files, ctx.all_dirs, ctx.path_roots, anchor.doc_dir
        )
        ok = resolved is not None and (
            not symbol or CodeIndex(ctx.repo_root, [resolved]).contains(_bare(symbol))
        )
        return [(token, ok)]
    if anchor.path_like:
        out: list[tuple[str, bool]] = []
        for member in expand_braces(token):
            resolves = _member_resolves(member, anchor.doc_dir, ctx)
            first_seg = member.strip("/").split("/", 1)[0]
            if not resolves and ctx.branch_prefixes and first_seg in ctx.branch_prefixes:
                continue  # quoted branch name — not a claim
            out.append((member, resolves))
        return out
    return [(token, _identifier_resolves(token, anchor.doc_dir, ctx))]


def record(anchors: list[Anchor], ctx: ResolveCtx) -> list[str]:
    """The claims that resolve right now — the set an ack arms.

    Only proven claims enter the baseline: a token that does not resolve is
    prose, a flag, history, or a plan — not a promise the repo ever kept, so
    it can never red. `planned:` markers are declarations, never baseline.
    """
    out: set[str] = set()
    for anchor in anchors:
        if anchor.planned:
            continue
        for key, ok in _claims(anchor, ctx):
            if ok:
                out.add(key)
    return sorted(out)


def verify(
    doc: str,
    anchors: list[Anchor],
    baseline: set[str] | None,
    ctx: ResolveCtx,
) -> tuple[list[AnchorFinding], AnchorStatus]:
    """Findings for armed claims that no longer resolve.

    A claim is armed when the last ack proved it resolved (`baseline`). An
    armed claim that stops resolving is provable drift — it existed, now it
    does not. Tokens outside the baseline are unarmed: counted, never red
    (the count keeps the blind spot visible; the next ack arms whatever
    resolves by then). `baseline` None = the doc was never anchor-acked —
    everything is unarmed and the doc reports baseline_missing.

    `planned:` markers bypass the baseline: pending ones report every run,
    landed ones are flagged for marker removal.
    """
    findings: list[AnchorFinding] = []
    status = AnchorStatus(doc=doc, baseline_missing=baseline is None)

    for anchor in anchors:
        token = anchor.token
        if anchor.planned:
            landed = _member_resolves(token, anchor.doc_dir, ctx)
            findings.append(
                AnchorFinding(
                    doc=doc,
                    line=anchor.line,
                    token=token,
                    scope="repo",
                    planned="resolved" if landed else "pending",
                )
            )
            continue
        for key, ok in _claims(anchor, ctx):
            if baseline is None or key not in baseline:
                status.unarmed += 1
                status.unarmed_tokens.append(key)
                continue
            status.armed += 1
            if ok:
                continue
            scope = "pair" if (ctx.pair_index is not None and not anchor.path_like) else "repo"
            hint = ""
            if scope == "pair":
                # still red — a same-named survivor elsewhere must never
                # soften a rename signal — but the finding names where the
                # identifier lives, so cross-pair vs rot is decidable
                bare = _bare(token)
                tail = bare.rsplit(".", 1)[-1] if "." in bare else ""
                for cand in (token, bare if len(bare) >= 2 else "", tail if len(tail) >= 2 else ""):
                    rel = ctx.repo_index.locate(cand) if cand else None
                    if rel is not None:
                        hint = (
                            f"exists in {rel} — cross-pair reference? widen the "
                            "pair's code, or quote the path instead"
                        )
                        break
            findings.append(
                AnchorFinding(doc=doc, line=anchor.line, token=key, scope=scope, hint=hint)
            )
    status.unarmed_tokens = sorted(set(status.unarmed_tokens))
    return findings, status


def _bare(token: str) -> str:
    """Strip call/assignment/subscript/glob notation down to the identifier.

    `truncate()` / `is_viewed(sid)` -> the name before `(`;
    `viewMode='terminal'` -> the name before `=`;
    `loading[sid]` / `content[]` -> the name before `[`;
    `system_*` -> the prefix before the glob char.
    """
    for sep in ("(", "=", "[", "*", "?"):
        if sep in token:
            token = token.split(sep, 1)[0]
    return token.strip()


def dirs_of(files: set[str]) -> set[str]:
    dirs: set[str] = set()
    for f in files:
        parts = f.split("/")
        for i in range(1, len(parts)):
            dirs.add("/".join(parts[:i]))
    return dirs


@dataclass
class DocMentions:
    """What a doc talks about, per its own anchors.

    - path_files: repo file -> doc lines whose path-like anchors resolve to it
    - idents: bare identifier token -> doc lines quoting it
    - total_anchors: every anchor extracted, resolvable or not — zero means
      the doc gives the grader nothing to work with
    """

    path_files: dict[str, list[int]] = field(default_factory=dict)
    idents: dict[str, list[int]] = field(default_factory=dict)
    total_anchors: int = 0


def doc_mention_index(
    repo_root: Path,
    doc: str,
    rule: AnchorRule,
    all_files: set[str],
    all_dirs: set[str],
    path_roots: list[str] | None = None,
) -> DocMentions:
    """Build the doc's mention index for the anchor-graded L1.

    A pair break is RED only when a changed file is one the doc actually
    mentions — by path anchor (file granularity), or because the change's
    added/removed lines contain a quoted identifier (line granularity).
    Everything else downgrades to AMBER.
    """
    mentions = DocMentions()
    try:
        text = (repo_root / doc).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return mentions

    def _mention(rel: str, line: int) -> None:
        mentions.path_files.setdefault(rel, []).append(line)

    for anchor in extract(doc, text, rule):
        token = anchor.token
        mentions.total_anchors += 1
        if "::" in token and "." in token.partition("::")[0]:
            resolved = _resolve_path(
                token.partition("::")[0], all_files, all_dirs, path_roots, anchor.doc_dir
            )
            if resolved:
                _mention(resolved, anchor.line)
            continue
        if anchor.path_like:
            for cand in _path_candidates(token, path_roots, anchor.doc_dir):
                if cand in all_files:
                    _mention(cand, anchor.line)
                elif cand in all_dirs:
                    prefix = cand.rstrip("/") + "/"
                    for f in all_files:
                        if f.startswith(prefix):
                            _mention(f, anchor.line)
                elif any(ch in cand for ch in "*?["):
                    from . import globs

                    for f in all_files:
                        if globs.matches(cand, f):
                            _mention(f, anchor.line)
            continue
        resolved = _resolve_path(token, all_files, all_dirs, path_roots, anchor.doc_dir)
        if resolved:
            _mention(resolved, anchor.line)
            continue
        bare = _bare(token)
        if len(bare) >= 3:
            mentions.idents.setdefault(bare, []).append(anchor.line)
    return mentions
