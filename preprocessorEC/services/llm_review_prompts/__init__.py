"""Versioned prompt catalog for :mod:`preprocessorEC.services.llm_review`.

Each ``*.md`` file in this folder is one prompt version: a small frontmatter
block of metadata, a ``## Use Scenarios`` section saying when the prompt is the
right tool, and fenced ``## System Prompt`` / ``## User Template`` blocks holding
the text actually sent to the model.

Keeping the text here rather than inline in ``llm_review.py`` means a prompt can
be revised, compared against its predecessor, or swapped without editing the code
that calls the API. Which version runs is a per-task choice made in the UI before
preprocessing, not a property of the folder. See ``README.md`` for the field list
and the steps to add a version.

Both the system prompt and the user template are Jinja, rendered with the input
mode in context. That is what lets one prompt version run either way: the parts
that genuinely differ between modes -- how the task is framed at the top and what
reply shape is demanded at the bottom -- sit behind ``{% if mode == 'GROUP' %}``,
while the judging rules between them are written once.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from jinja2.sandbox import SandboxedEnvironment

_DIR = Path(__file__).parent
_FENCE = "```"

_JINJA = SandboxedEnvironment(trim_blocks=True, lstrip_blocks=True, autoescape=False)

#: Prompt family used by the preprocess MED/LOW match review step.
PREPROCESS_REVIEW = "preprocess_review"

#: Applied when a task has recorded no prompt version.
DEFAULT_PROMPT_NAME = "preprocess_review_v2"

#: Input modes. ``PAIR`` sends one (input row, matched row) comparison per call.
#: ``GROUP`` sends one input row with all of its matches per call, so the input is
#: described to the model once instead of once per candidate and a row with six
#: matches costs one call instead of six. The two demand different reply shapes,
#: which is why the mode reaches the prompt text rather than only the caller.
MODES = ("PAIR", "GROUP")

#: Applied when a task has recorded no input mode.
DEFAULT_MODE = "GROUP"

#: Long form for tooltips and help text; short form for the two-way UI toggle.
MODE_LABELS = {
    "GROUP": "Per input — one call per input row, judging all of its matches together",
    "PAIR": "Per pair — one call per input/match pair",
}

MODE_SHORT_LABELS = {"GROUP": "Per input", "PAIR": "Per pair"}


def resolve_mode(mode: str | None = None) -> str:
    """Normalise an input mode, falling back to the default.

    Accepts ``None``, lower case, or an unknown value so a task row written before
    this setting existed still runs rather than raising.
    """
    key = str(mode or "").strip().upper()
    return key if key in MODES else DEFAULT_MODE


def mode_options() -> list[dict]:
    """Input modes as UI-ready dicts, default first."""
    return [
        {
            "key": key,
            "label": MODE_LABELS[key],
            "short_label": MODE_SHORT_LABELS[key],
            "is_default": key == DEFAULT_MODE,
        }
        for key in sorted(MODES, key=lambda m: m != DEFAULT_MODE)
    ]


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
    def modes(self) -> tuple[str, ...]:
        """Input modes this prompt's text is written to handle."""
        declared = [
            part.strip().upper()
            for part in str(self.meta.get("modes", "")).split(",")
            if part.strip()
        ]
        return tuple(m for m in MODES if m in declared) or MODES

    @property
    def default_mode(self) -> str:
        """Mode to preselect for this prompt."""
        declared = resolve_mode(self.meta.get("default_mode"))
        return declared if declared in self.modes else self.modes[0]

    def supports(self, mode: str) -> bool:
        return resolve_mode(mode) in self.modes

    @property
    def best_for(self) -> str:
        """One-line summary of the fit; the long form is ``use_scenarios``."""
        return self.meta.get("best_for", "")

    def render_system(self, mode: str | None = None) -> str:
        """System message for one input mode."""
        return _JINJA.from_string(self.system_prompt).render(mode=resolve_mode(mode))

    def render_user(self, mode: str | None = None, **context) -> str:
        """User message for one input mode."""
        return _JINJA.from_string(self.user_template).render(
            mode=resolve_mode(mode), **context
        )

    def to_dict(self, mode: str | None = None) -> dict:
        """Content for the prompt-viewer modal.

        ``system_prompt`` and ``user_template`` come back rendered for *mode*, so
        the modal shows what would actually be sent rather than the Jinja source
        with both branches in it.
        """
        mode = resolve_mode(mode)
        return {
            "name": self.name,
            "key": self.key,
            "label": self.label,
            "version": self.version,
            "status": self.status,
            "mode": mode,
            "modes": list(self.modes),
            "default_mode": self.default_mode,
            "best_for": self.best_for,
            "use_scenarios": self.use_scenarios,
            "system_prompt": self.render_system(mode),
            "user_template": self.user_template,
        }


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
    declared = [p.strip().upper() for p in str(meta.get("modes", "")).split(",") if p.strip()]
    unknown = [m for m in declared if m not in MODES]
    if unknown:
        raise ValueError(f"{path.name}: unknown mode(s) {unknown}; valid: {list(MODES)}")
    if not declared:
        raise ValueError(f"{path.name}: frontmatter must declare 'modes' (e.g. 'PAIR, GROUP')")
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


def available(key: str = PREPROCESS_REVIEW) -> list[ReviewPrompt]:
    """Selectable prompts in a family, oldest version first.

    Only ``status: active`` files are offered — retiring a version removes it
    from the picker without deleting the text a past task was judged under.
    """
    return sorted(
        (p for p in _catalog().values() if p.key == key and p.status == "active"),
        key=lambda p: p.version,
    )


def names(key: str = PREPROCESS_REVIEW) -> list[str]:
    """Valid selection values, for validating a request."""
    return [p.name for p in available(key)]


def load(name: str) -> ReviewPrompt:
    """Load one prompt by file stem, e.g. ``preprocess_review_v1``.

    Loads retired versions too, so a task stamped with an old version can still
    show the text its verdicts were judged under.
    """
    try:
        return _catalog()[name]
    except KeyError:
        known = ", ".join(sorted(_catalog())) or "(none)"
        raise KeyError(f"unknown review prompt {name!r}; available: {known}") from None


def resolve(selection: str | None = None, key: str = PREPROCESS_REVIEW) -> ReviewPrompt:
    """Turn a user selection into a prompt.

    ``None`` or empty means "no preference" and yields the default. Anything else
    must name a real prompt — a file stem (``preprocess_review_v2``) or a bare
    version (``v2``, ``2``). An unrecognised value raises KeyError rather than
    quietly falling back, so a typo in a scripted call cannot silently rejudge a
    task under the wrong prompt.
    """
    raw = str(selection or "").strip()
    if not raw:
        return load(DEFAULT_PROMPT_NAME)

    catalog = _catalog()
    if raw in catalog:
        return catalog[raw]

    digits = raw[1:] if raw[:1].lower() == "v" else raw
    if digits.isdigit():
        wanted = int(digits)
        for prompt in available(key):
            if prompt.version == wanted:
                return prompt

    raise KeyError(
        f"unknown review prompt {selection!r}; available: {', '.join(names(key)) or '(none)'}"
    )


def options(key: str = PREPROCESS_REVIEW) -> list[dict]:
    """Selectable prompts as UI-ready dicts (no prompt text)."""
    return [
        {
            "name": p.name,
            "label": p.label,
            "version": p.version,
            "modes": list(p.modes),
            "default_mode": p.default_mode,
            "best_for": p.best_for,
            "is_default": p.name == DEFAULT_PROMPT_NAME,
        }
        for p in available(key)
    ]
