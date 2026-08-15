"""Quick Discovery — LLM item comparison with versioned prompts.

Differences from ``llm_review``, which judges contract-load matches:

* The prompt is a database row, not a module constant, so a preprocessor can
  edit it in the UI. Every judged match records the version that judged it.
* Verdicts are SAME / DIFFERENT / UNCERTAIN. Discovery has no UOM, QOE, or
  price, so the packaging rules of the contract-load prompt do not apply.
* Work is dispatched concurrently over a thread pool, with one shared client.

Two prompt modes, chosen by the active version's ``prompt_mode``:

* PAIR sends one (input line, contract line) comparison per call.
* GROUP sends one input line with all of its candidate contract lines in a
  single call and reads back one result per candidate. The input side is then
  described once instead of once per pair, which is what stops the core-product
  noun drifting between a line's own candidates.

Both modes stay live: a prompt version records which shape it was written for,
so older versions keep rendering the way they were judged under.

Framework-agnostic: worker threads never touch ``current_app``. The caller
snapshots config into plain values and passes them in.
"""

from __future__ import annotations

import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from jinja2 import TemplateError
from jinja2.sandbox import SandboxedEnvironment

from ..common.utils import ny_now
from ..db import discovery_repo

logger = logging.getLogger(__name__)

VERDICTS = ("SAME", "DIFFERENT", "UNCERTAIN")

# Unit separator for the dedupe hash: a delimiter that cannot occur in
# cleansed text, so ("AB", "C") and ("A", "BC") can never collide.
_HASH_SEP = chr(31)

PROMPT_MODES = ("PAIR", "GROUP")
DEFAULT_PROMPT_MODE = "PAIR"

# One line's candidates per call. The observed maximum is 11, so this only
# bounds a pathological set; a line with more is split across calls, and the
# noun can differ between those chunks.
MAX_CANDIDATES_PER_CALL = 20

# Variables a prompt author may reference in user_template. Surfaced in the
# editor UI so the available context is discoverable.
TEMPLATE_VARIABLES = (
    "input_sku",
    "input_description",
    "input_supplier",
    "matched_sku",
    "matched_description",
    "matched_vendor_name",
    "matched_manufacturer_name",
    "sku_exact",
    "matched_on",
    "desc_similarity",
)

# GROUP templates describe the input once and loop over ``candidates``. Each
# entry carries the same matched_* fields a PAIR template gets, plus ``index``,
# the 1-based number the model must key its results to.
GROUP_TEMPLATE_VARIABLES = (
    "input_sku",
    "input_description",
    "input_supplier",
    "candidate_count",
    "candidates[].index",
    "candidates[].matched_sku",
    "candidates[].matched_description",
    "candidates[].matched_vendor_name",
    "candidates[].matched_manufacturer_name",
    "candidates[].sku_exact",
    "candidates[].matched_on",
    "candidates[].desc_similarity",
)


def variables_for_mode(mode: str) -> tuple:
    return GROUP_TEMPLATE_VARIABLES if _norm_mode(mode) == "GROUP" else TEMPLATE_VARIABLES


def _norm_mode(mode) -> str:
    value = str(mode or "").strip().upper()
    return value if value in PROMPT_MODES else DEFAULT_PROMPT_MODE

# Sandboxed so a prompt edit can't reach into Python internals. Prompts are
# preprocessor-gated, but the template is still user input rendered server-side.
_JINJA = SandboxedEnvironment(trim_blocks=True, lstrip_blocks=True, autoescape=False)


class PromptRenderError(ValueError):
    """A prompt template failed to render; the run stops rather than sending junk."""


def render_user_prompt(user_template: str, pair: dict) -> str:
    """Render one comparison pair through the versioned user template."""
    context = {
        "input_sku": pair.get("input_sku") or "",
        "input_description": pair.get("input_description") or "",
        "input_supplier": pair.get("input_supplier") or "",
        "matched_sku": pair.get("matched_sku") or "",
        "matched_description": pair.get("matched_description") or "",
        "matched_vendor_name": pair.get("matched_vendor_name") or "",
        "matched_manufacturer_name": pair.get("matched_manufacturer_name") or "",
        "sku_exact": "Yes" if pair.get("sku_exact") else "No",
        "matched_on": (
            "reduced manufacturer part number"
            if pair.get("matched_on") == "REDUCED_MFG"
            else "reduced vendor part number"
        ),
        "desc_similarity": round(float(pair.get("desc_similarity") or 0.0), 3),
    }
    try:
        return _JINJA.from_string(user_template).render(**context)
    except TemplateError as exc:
        raise PromptRenderError(f"Prompt template failed to render: {exc}") from exc


def _candidate_context(candidate: dict, index: int) -> dict:
    """One entry of the ``candidates`` list a GROUP template loops over."""
    return {
        "index": index,
        "matched_sku": candidate.get("matched_sku") or "",
        "matched_description": candidate.get("matched_description") or "",
        "matched_vendor_name": candidate.get("matched_vendor_name") or "",
        "matched_manufacturer_name": candidate.get("matched_manufacturer_name") or "",
        "sku_exact": "Yes" if candidate.get("sku_exact") else "No",
        "matched_on": (
            "reduced manufacturer part number"
            if candidate.get("matched_on") == "REDUCED_MFG"
            else "reduced vendor part number"
        ),
        "desc_similarity": round(float(candidate.get("desc_similarity") or 0.0), 3),
    }


def render_group_prompt(user_template: str, group: dict, candidates: list[dict]) -> str:
    """Render one input line plus its candidate contract lines."""
    context = {
        "input_sku": group.get("input_sku") or "",
        "input_description": group.get("input_description") or "",
        "input_supplier": group.get("input_supplier") or "",
        "candidate_count": len(candidates),
        "candidates": [
            _candidate_context(candidate, i) for i, candidate in enumerate(candidates, 1)
        ],
    }
    try:
        return _JINJA.from_string(user_template).render(**context)
    except TemplateError as exc:
        raise PromptRenderError(f"Prompt template failed to render: {exc}") from exc


# Distinct per side, so validation can tell "rendered the input" apart from
# "rendered the contract line" — a template that drops one still renders the
# other, and the two texts must not be confusable.
_SAMPLE_INPUT_TEXT = "SAMPLE INPUT DESCRIPTION"
_SAMPLE_MATCHED_TEXT = "SAMPLE MATCHED DESCRIPTION"

_SAMPLE_PAIR = {
    "input_sku": "SAMPLE-1",
    "input_description": _SAMPLE_INPUT_TEXT,
    "input_supplier": "SAMPLE SUPPLIER",
    "matched_sku": "SAMPLE-1",
    "matched_description": _SAMPLE_MATCHED_TEXT,
    "matched_vendor_name": "SAMPLE VENDOR",
    "matched_manufacturer_name": "SAMPLE MANUFACTURER",
    "sku_exact": True,
    "matched_on": "REDUCED_MFG",
    "desc_similarity": 0.9,
}


def validate_template(system_prompt: str, user_template: str, mode: str = DEFAULT_PROMPT_MODE) -> None:
    """Reject a prompt edit that can't render, before it becomes the active version.

    Rendering alone is not enough of a test. Jinja's default undefined iterates
    as empty and prints as blank rather than raising, so a template written for
    the other mode renders cleanly and silently drops half the comparison — a
    grouped template saved as PAIR loses the contract line, and a pair template
    saved as GROUP loses every candidate. Either way the model is asked to
    compare something against nothing, and answers anyway.

    So each mode renders against its own sample and then asserts the text it
    should have produced is actually there.
    """
    if not (system_prompt or "").strip():
        raise PromptRenderError("System prompt cannot be empty.")
    if not (user_template or "").strip():
        raise PromptRenderError("User template cannot be empty.")

    if _norm_mode(mode) == "GROUP":
        # Digit-free sentinels: the rendered text carries numbers of its own
        # (candidate_count, similarity, sample SKUs), so a probe containing a
        # digit could not be told apart from those.
        probes = [
            dict(_SAMPLE_PAIR, matched_description=f"SAMPLE CANDIDATE {name}")
            for name in ("ALPHA", "BETA")
        ]
        rendered = render_group_prompt(user_template, _SAMPLE_PAIR, probes)
        found = sum(1 for p in probes if p["matched_description"] in rendered)
        if found < len(probes):
            raise PromptRenderError(
                "A grouped template must render every candidate — loop over "
                "`candidates` and print each one's `matched_description`. This "
                f"template rendered {found} of {len(probes)} sample candidates."
            )
        # Checked against the source, not the render: every index the loop can
        # emit is a small integer that also occurs elsewhere in the output, so
        # searching the rendered text for one would find it either way.
        # `loop.index` is equivalent to `c.index` and satisfies this too.
        if ".index" not in user_template:
            raise PromptRenderError(
                "A grouped template must print each candidate's `index` — that "
                "number is how each reply is matched back to a contract line. "
                "Add {{ c.index }} inside the loop."
            )
    else:
        rendered = render_user_prompt(user_template, _SAMPLE_PAIR)
        if _SAMPLE_MATCHED_TEXT not in rendered:
            raise PromptRenderError(
                "A pair template must render the matched contract line — print "
                "`matched_description`. A template written for grouped sending "
                "will do this: its candidates loop renders as nothing here."
            )

    if _SAMPLE_INPUT_TEXT not in rendered:
        raise PromptRenderError(
            "The template must render the input item — print `input_description`."
        )


def _payload_hash(pair: dict) -> str:
    """Identity of a comparison, ignoring which row asked for it.

    Duplicate SKUs across an uploaded file produce identical comparisons; hashing
    lets one API call answer all of them.
    """
    parts = [
        pair.get("input_description") or "",
        pair.get("input_supplier") or "",
        pair.get("matched_description") or "",
        pair.get("matched_vendor_name") or "",
        pair.get("matched_manufacturer_name") or "",
        pair.get("matched_sku") or "",
        pair.get("input_sku") or "",
        "1" if pair.get("sku_exact") else "0",
        pair.get("matched_on") or "",
    ]
    return hashlib.sha256(_HASH_SEP.join(parts).encode("utf-8")).hexdigest()


def _parse_yes_no(value) -> Optional[bool]:
    """Yes/No (or a JSON bool) to a tri-state; anything else is unknown.

    A prompt version that predates the core-noun output simply omits the field,
    which lands here as None rather than as a false negative.
    """
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in ("yes", "y", "true", "1", "same"):
        return True
    if text in ("no", "n", "false", "0", "different"):
        return False
    return None


def _parse_verdict(data: dict) -> dict:
    """One judgement object to stored fields. Anything odd becomes UNCERTAIN."""
    verdict = str(data.get("verdict", "") or "").strip().upper()
    if verdict not in VERDICTS:
        verdict = "UNCERTAIN"

    try:
        confidence = int(data.get("confidence", 0) or 0)
    except (TypeError, ValueError):
        confidence = 0
    confidence = max(0, min(100, confidence))

    reason = str(data.get("reason", "") or "").strip()
    return {
        "verdict": verdict,
        "confidence": confidence,
        "reason": reason[:1000],
        "same_noun": _parse_yes_no(data.get("same_noun")),
        "input_noun": (str(data.get("input_noun") or "").strip() or None),
        "matched_noun": (str(data.get("matched_noun") or "").strip() or None),
    }


def _parse_response(content: str) -> dict:
    """Parse a single-judgement JSON reply (PAIR mode)."""
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        data = None
    if not isinstance(data, dict):
        return {
            "verdict": "UNCERTAIN",
            "confidence": 0,
            "reason": "LLM response was not valid JSON.",
            "same_noun": None,
            "input_noun": None,
            "matched_noun": None,
        }
    return _parse_verdict(data)


def _chat(client, *, model, temperature, max_tokens, system_prompt, user_content):
    """One API call. Returns (content, error) — errors are data, never raised,
    so one bad call cannot take down the rest of a slice."""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            max_completion_tokens=max_tokens,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content, None
    except Exception as exc:  # noqa: BLE001 — surfaced per row, not raised
        logger.error("Discovery LLM call failed: %s", exc)
        return None, f"{exc.__class__.__name__}: {exc}"[:500]


def _failed(error: str) -> dict:
    """The shape every consumer expects when a judgement did not happen."""
    return {
        "verdict": None,
        "confidence": None,
        "reason": None,
        "same_noun": None,
        "input_noun": None,
        "matched_noun": None,
        "error": error,
    }


def _judge_one(client, *, model, temperature, max_tokens, system_prompt, user_content) -> dict:
    """PAIR mode: one comparison per call."""
    content, error = _chat(
        client, model=model, temperature=temperature, max_tokens=max_tokens,
        system_prompt=system_prompt, user_content=user_content,
    )
    if error is not None:
        return _failed(error)
    parsed = _parse_response(content)
    parsed["error"] = None
    return parsed


def _parse_group_response(content: str, count: int) -> list[dict]:
    """Split one grouped reply into ``count`` per-candidate results.

    Results are keyed by the candidate number the prompt asked for rather than
    by position, because a model that drops or reorders an entry would otherwise
    shift every verdict after it onto the wrong contract line. A candidate the
    model said nothing about comes back as an error, not as a guess.
    """
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return [_failed("LLM response was not valid JSON.") for _ in range(count)]

    if not isinstance(data, dict):
        return [_failed("LLM response was not a JSON object.") for _ in range(count)]

    input_noun = (str(data.get("input_noun") or "").strip() or None)

    by_index: dict[int, dict] = {}
    results = data.get("results")
    if isinstance(results, list):
        for position, entry in enumerate(results, 1):
            if not isinstance(entry, dict):
                continue
            try:
                # Fall back to position only when the key is absent entirely;
                # a present-but-unparseable key is a real misalignment.
                index = int(entry.get("candidate", position))
            except (TypeError, ValueError):
                continue
            by_index.setdefault(index, entry)

    out = []
    for index in range(1, count + 1):
        entry = by_index.get(index)
        if entry is None:
            out.append(_failed(
                f"LLM returned no result for candidate {index} of {count}."
            ))
            continue
        parsed = _parse_verdict(entry)
        # The input side is described once for the whole group, so every
        # candidate inherits the same noun — that is the point of grouping.
        parsed["input_noun"] = input_noun or parsed.get("input_noun")
        parsed["error"] = None
        out.append(parsed)
    return out


def _judge_group(
    client, *, model, temperature, max_tokens, system_prompt, user_content, count
) -> list[dict]:
    """GROUP mode: one input line and all its candidates per call."""
    content, error = _chat(
        client, model=model, temperature=temperature, max_tokens=max_tokens,
        system_prompt=system_prompt, user_content=user_content,
    )
    if error is not None:
        return [_failed(error) for _ in range(count)]
    return _parse_group_response(content, count)


def judge_pairs(
    pairs: list[dict],
    *,
    client,
    prompt: dict,
    model: str,
    temperature: float,
    max_tokens: int,
    max_workers: int = 8,
) -> list[dict]:
    """Judge many pairs concurrently; returns DiscoveryMatch update dicts.

    Identical comparisons are collapsed to one API call and the verdict is fanned
    back out, so a file with repeated SKUs doesn't pay twice.
    """
    if not pairs:
        return []

    system_prompt = prompt["system_prompt"]
    user_template = prompt["user_template"]
    prompt_version_id = prompt["prompt_version_id"]

    # Render first: a broken template should fail the whole run loudly rather
    # than burn tokens on the pairs that happen to render.
    rendered: dict[str, str] = {}
    pair_hashes: list[str] = []
    for pair in pairs:
        key = _payload_hash(pair)
        pair_hashes.append(key)
        if key not in rendered:
            rendered[key] = render_user_prompt(user_template, pair)

    unique_keys = list(rendered)
    verdicts: dict[str, dict] = {}

    if client is None:
        unavailable = {
            "verdict": None,
            "confidence": None,
            "reason": None,
            "same_noun": None,
            "input_noun": None,
            "matched_noun": None,
            "error": "LLM unavailable — OPENAI_API_KEY is not configured.",
        }
        verdicts = {key: unavailable for key in unique_keys}
    else:
        workers = max(1, min(int(max_workers), len(unique_keys)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(
                lambda key: _judge_one(
                    client,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    system_prompt=system_prompt,
                    user_content=rendered[key],
                ),
                unique_keys,
            ))
        verdicts = dict(zip(unique_keys, results))

    now = ny_now()
    updates = [
        _update_row(pair["discovery_match_id"], verdicts[key], prompt_version_id, now)
        for pair, key in zip(pairs, pair_hashes)
    ]

    if len(unique_keys) < len(pairs):
        logger.info(
            "Discovery LLM slice: %d pair(s) collapsed to %d unique comparison(s).",
            len(pairs), len(unique_keys),
        )
    return updates


def _update_row(match_id: int, result: dict, prompt_version_id: int, now) -> dict:
    """One DiscoveryMatch update dict. Shared by both prompt modes."""
    failed = result.get("error") is not None
    input_noun = result.get("input_noun") or None
    matched_noun = result.get("matched_noun") or None
    return {
        "discovery_match_id": match_id,
        "llm_status": "ERROR" if failed else "DONE",
        "llm_verdict": result.get("verdict"),
        "llm_confidence": result.get("confidence"),
        "llm_reason": result.get("reason"),
        "llm_same_noun": result.get("same_noun"),
        # Column is NVARCHAR(120); a chatty model shouldn't fail the write.
        "llm_input_noun": input_noun and input_noun[:120],
        "llm_matched_noun": matched_noun and matched_noun[:120],
        "llm_error": result.get("error"),
        "llm_prompt_version_id": prompt_version_id,
        "llm_reviewed_at": now,
    }


def _group_max_tokens(base: int, count: int) -> int:
    """A grouped reply carries one judgement per candidate, so the ceiling has
    to grow with the group or the JSON is truncated and the whole call is lost."""
    return max(int(base), min(8000, 260 * count + 300))


def judge_items(
    groups: list[dict],
    *,
    client,
    prompt: dict,
    model: str,
    temperature: float,
    max_tokens: int,
    max_workers: int = 8,
) -> list[dict]:
    """GROUP mode: one call per input line, fanned back out to its candidates.

    A line with more candidates than ``MAX_CANDIDATES_PER_CALL`` is split into
    several calls, so a pathological set cannot produce one enormous request.
    """
    if not groups:
        return []

    system_prompt = prompt["system_prompt"]
    user_template = prompt["user_template"]
    prompt_version_id = prompt["prompt_version_id"]

    # (group, candidate slice) units of work. Rendering first means a broken
    # template fails the run loudly rather than burning tokens on what parses.
    units = []
    for group in groups:
        candidates = group.get("candidates") or []
        for start in range(0, len(candidates), MAX_CANDIDATES_PER_CALL):
            chunk = candidates[start:start + MAX_CANDIDATES_PER_CALL]
            units.append({
                "chunk": chunk,
                "content": render_group_prompt(user_template, group, chunk),
            })

    if client is None:
        results = [
            [_failed("LLM unavailable — OPENAI_API_KEY is not configured.")] * len(u["chunk"])
            for u in units
        ]
    else:
        workers = max(1, min(int(max_workers), len(units)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(
                lambda unit: _judge_group(
                    client,
                    model=model,
                    temperature=temperature,
                    max_tokens=_group_max_tokens(max_tokens, len(unit["chunk"])),
                    system_prompt=system_prompt,
                    user_content=unit["content"],
                    count=len(unit["chunk"]),
                ),
                units,
            ))

    now = ny_now()
    updates = []
    for unit, verdicts in zip(units, results):
        for candidate, result in zip(unit["chunk"], verdicts):
            updates.append(
                _update_row(candidate["discovery_match_id"], result, prompt_version_id, now)
            )

    logger.info(
        "Discovery LLM slice: %d line(s) judged in %d call(s) covering %d pair(s).",
        len(groups), len(units), len(updates),
    )
    return updates


def run_slice(
    set_id: int,
    *,
    client,
    prompt: dict,
    model: str,
    temperature: float,
    max_tokens: int,
    slice_size: int,
    max_workers: int,
) -> dict:
    """Claim, judge, and persist one slice of pending work.

    The browser calls this repeatedly until ``remaining`` reaches zero. Claiming
    is atomic, so an interrupted run just resumes on the next call and two open
    tabs can't judge the same row twice.

    ``slice_size`` counts pairs under PAIR and input lines under GROUP, since
    those are the units each mode sends. ``processed`` and ``remaining`` stay in
    pairs either way, so the progress bar means the same thing in both modes.
    """
    # GROUP claims whole input lines: a line split across two slices would be
    # described to the model twice, which is exactly the drift grouping removes.
    grouped = _norm_mode(prompt.get("prompt_mode")) == "GROUP"
    match_ids = (
        discovery_repo.claim_llm_slice_by_item(set_id, slice_size)
        if grouped
        else discovery_repo.claim_llm_slice(set_id, slice_size)
    )
    if not match_ids:
        remaining = discovery_repo.count_llm_remaining(set_id)
        if remaining == 0:
            discovery_repo.update_set(set_id, status="LLM_COMPLETE")
        return {"processed": 0, "remaining": remaining, "done": remaining == 0}

    try:
        if grouped:
            updates = judge_items(
                discovery_repo.get_items_for_llm(match_ids),
                client=client,
                prompt=prompt,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                max_workers=max_workers,
            )
        else:
            updates = judge_pairs(
                discovery_repo.get_matches_for_llm(match_ids),
                client=client,
                prompt=prompt,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                max_workers=max_workers,
            )
    except PromptRenderError:
        # Hand the claimed rows back so a fixed template can retry them.
        discovery_repo.save_llm_verdicts([
            {"discovery_match_id": mid, "llm_status": "PENDING"} for mid in match_ids
        ])
        raise

    discovery_repo.save_llm_verdicts(updates)
    discovery_repo.update_set(set_id, active_prompt_version_id=prompt["prompt_version_id"])

    remaining = discovery_repo.count_llm_remaining(set_id)
    discovery_repo.update_set(
        set_id, status="LLM_COMPLETE" if remaining == 0 else "LLM_RUNNING"
    )

    errors = sum(1 for u in updates if u["llm_status"] == "ERROR")
    return {
        "processed": len(updates),
        "errors": errors,
        "remaining": remaining,
        "done": remaining == 0,
    }


def get_active_prompt_dict(prompt_key: str = "ITEM_COMPARE") -> Optional[dict]:
    """Active prompt as a plain dict — safe to hand to worker threads."""
    row = discovery_repo.get_active_prompt(prompt_key)
    if row is None:
        return None
    return {
        "prompt_version_id": row.prompt_version_id,
        "prompt_key": row.prompt_key,
        "version_no": row.version_no,
        "prompt_mode": _norm_mode(getattr(row, "prompt_mode", None)),
        "system_prompt": row.system_prompt,
        "user_template": row.user_template,
        "model": row.model,
        "temperature": row.temperature,
    }


def resolve_model_settings(prompt: dict, config_settings: dict) -> dict:
    """A prompt version may pin its own model/temperature; otherwise use config."""
    return {
        "model": prompt.get("model") or config_settings.get("model"),
        "temperature": (
            prompt["temperature"]
            if prompt.get("temperature") is not None
            else config_settings.get("temperature", 0.0)
        ),
        "max_tokens": config_settings.get("max_tokens", 1024),
    }
