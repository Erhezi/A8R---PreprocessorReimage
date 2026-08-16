"""Versioned prompt catalog for :mod:`preprocessorEC.services.llm_review`.

Each ``*.md`` file in this folder is one prompt version: a small frontmatter
block of metadata, a ``## Use Scenarios`` section saying when the prompt is the
right tool, and fenced ``## System Prompt`` / ``## User Template`` blocks holding
the text actually sent to the model.

Keeping the text here rather than inline in ``llm_review.py`` means a prompt can
be revised, compared against its predecessor, or rolled back by flipping
``status``, without editing the code that calls the API. See ``README.md`` for the
field list and the steps to add a version.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).parent
_FENCE = "```"

#: Prompt family used by the preprocess MED/LOW match review step.
PREPROCESS_REVIEW = "preprocess_review"


@dataclass(frozen=True)
class ReviewPrompt:
    """One versioned prompt, parsed from a markdown file in this folder."""

    name: str
    key: str
    label: str
    version: int
    status: str
    use_scenarios: str
    system_prompt: str
    user_template: str
    meta: dict = field(default_factory=dict, repr=False)

    @property
    def mode(self) -> str:
        """``PAIR`` (one input line vs one match line) or ``GROUP``."""
        return self.meta.get("mode", "PAIR")

    @property
    def best_for(self) -> str:
        """One-line summary of the fit; the long form is ``use_scenarios``."""
        return self.meta.get("best_for", "")


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split leading ``---`` delimited ``key: value`` lines from the body."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    meta: dict[str, str] = {}
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return meta, "\n".join(lines[idx + 1 :])
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        raw_key, sep, value = line.partition(":")
        if sep:
            meta[raw_key.strip()] = value.strip()
    raise ValueError("frontmatter block is not closed by '---'")


def _section(body: str, heading: str) -> str:
    """Return the text under ``## <heading>`` up to the next ``## `` heading."""
    wanted = f"## {heading}".casefold()
    collected: list[str] = []
    inside = False
    for line in body.splitlines():
        if line.startswith("## "):
            if inside:
                break
            inside = line.strip().casefold() == wanted
            continue
        if inside:
            collected.append(line)
    if not inside and not collected:
        raise ValueError(f"missing '## {heading}' section")
    return "\n".join(collected).strip()


def _fenced(section_body: str, heading: str) -> str:
    """Return the first fenced code block in *section_body*, verbatim."""
    collected: list[str] = []
    inside = False
    for line in section_body.splitlines():
        if line.startswith(_FENCE):
            if inside:
                return "\n".join(collected)
            inside = True
            continue
        if inside:
            collected.append(line)
    raise ValueError(f"'## {heading}' has no closed ``` code block")


def _parse(path: Path) -> ReviewPrompt:
    meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
    missing = {"key", "label", "version"} - meta.keys()
    if missing:
        raise ValueError(f"{path.name}: missing frontmatter field(s) {sorted(missing)}")
    return ReviewPrompt(
        name=path.stem,
        key=meta["key"],
        label=meta["label"],
        version=int(meta["version"]),
        status=meta.get("status", "draft"),
        use_scenarios=_section(body, "Use Scenarios"),
        system_prompt=_fenced(_section(body, "System Prompt"), "System Prompt"),
        user_template=_fenced(_section(body, "User Template"), "User Template"),
        meta=meta,
    )


@lru_cache(maxsize=1)
def _catalog() -> dict[str, ReviewPrompt]:
    prompts = {}
    for path in sorted(_DIR.glob("*.md")):
        if path.stem.casefold() == "readme":
            continue
        prompt = _parse(path)
        prompts[prompt.name] = prompt
    return prompts


def available() -> list[ReviewPrompt]:
    """Every prompt in the folder, sorted by family key then version."""
    return sorted(_catalog().values(), key=lambda p: (p.key, p.version))


def load(name: str) -> ReviewPrompt:
    """Load one prompt by file stem, e.g. ``preprocess_review_v1``."""
    try:
        return _catalog()[name]
    except KeyError:
        known = ", ".join(sorted(_catalog())) or "(none)"
        raise KeyError(f"unknown review prompt {name!r}; available: {known}") from None


def active(key: str = PREPROCESS_REVIEW) -> ReviewPrompt:
    """Highest-version prompt marked ``status: active`` within a family *key*."""
    candidates = [p for p in _catalog().values() if p.key == key and p.status == "active"]
    if not candidates:
        raise RuntimeError(f"no active review prompt for key {key!r} in {_DIR}")
    return max(candidates, key=lambda p: p.version)
