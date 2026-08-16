# LLM review prompts

Versioned prompts for `preprocessorEC.services.llm_review`, the step that judges
MED/LOW similarity matches against CCX contract lines and Infor residue.

One markdown file per prompt version. `llm_review.py` loads the active version of
the `preprocess_review` family at import time, so revising a prompt or rolling
back to an earlier one is a change here, not in the calling code.

> Quick Discovery prompts are **not** here — those live in the database table
> `Preprocessor.PreprocessorDiscoveryPrompt` and are seeded by migrations, because
> they are edited and activated from the UI at runtime.

## Catalog

| File | Label | Key | Status | Best for |
| --- | --- | --- | --- | --- |
| `preprocess_review_v1.md` | Preprocess Review v1 | `preprocess_review` | active | Product identity and packaging judged together — same product, different packaging is a different item. |

## File format

```markdown
---
key: preprocess_review          # prompt family; versions of one job share a key
label: Preprocess Review v1     # human-readable name
version: 1                      # integer, unique within the key
status: active                  # active | retired | draft
mode: PAIR                      # PAIR = one input line vs one match line
response_format: json_object    # what the API call asks for
output_schema: {...}            # shape llm_review._parse_response expects
best_for: <one line>            # short form of the section below
---

## Use Scenarios

When this prompt is the right tool, and when it is not. Say what the prompt
optimizes for and which downstream system makes that the right trade-off, so a
future reader can tell whether a new job fits it or needs its own version.
Cover both good fit and poor fit.

## System Prompt

​```text
<sent as the system message>
​```

## User Template

​```text
<sent as the user message; {placeholders} are str.format fields>
​```
```

`## Use Scenarios`, `## System Prompt`, and `## User Template` are all required —
the loader raises on a file that is missing one. Placeholders in the user template
must match the keyword arguments in `llm_review._build_messages`.

## Adding a version

1. Copy the current active file to `<key>_v<n+1>.md`; bump `version` and `label`.
2. Edit the prompt text and rewrite `## Use Scenarios` to say what changed about
   the fit — that section is the reason to pick this version over the last one.
3. Set the new file to `status: active` and the previous one to `status: retired`.
   `active()` takes the highest-version active file in the family, so a rollback
   is just flipping those two values back.
4. Add a row to the catalog table above.

## Loading

```python
from preprocessorEC.services.llm_review_prompts import active, available, load

prompt = active("preprocess_review")   # highest-version active file in the family
prompt.system_prompt                   # str, verbatim from the fenced block
prompt.user_template.format(...)       # str.format placeholders
prompt.use_scenarios                   # the section text, for docs or a picker UI

load("preprocess_review_v1")           # a specific version, e.g. to A/B compare
available()                            # every prompt, sorted by key then version
```
