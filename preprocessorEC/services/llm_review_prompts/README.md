# LLM review prompts

Versioned prompts for `preprocessorEC.services.llm_review`, the step that judges
MED/LOW similarity matches against CCX contract lines and Infor residue.

One markdown file per prompt version. Which version runs is a **per-task choice**
made in the Run Pipeline card before preprocessing — every `status: active` file
appears in that dropdown, and the version a run applied is recorded on
`PreprocessorTask.llm_prompt_version`. Adding, revising, or retiring a prompt is
a change here, not in the calling code.

> Quick Discovery prompts are **not** here — those live in the database table
> `Preprocessor.PreprocessorDiscoveryPrompt` and are seeded by migrations, because
> they are edited and activated from the UI at runtime.

## Catalog

| File | Label | Modes | Status | Best for |
| --- | --- | --- | --- | --- |
| `preprocess_review_v1.md` | Preprocess Review v1 — supplier-role-aware, packaging aware | PAIR, GROUP | active | Supplier-aware product identity and packaging judged together — same product, different packaging is a different item. |
| `preprocess_review_v2.md` | Preprocess Review v2 — supplier-role-aware, ignore packaging | PAIR, GROUP | active | Product identity alone — packaging variants count as the same item; supplier role determines how catalog-number matches are weighed. Default. |

## Input modes

The input mode is a **runtime choice**, picked in the Run Pipeline card
independently of the prompt version and recorded on
`PreprocessorTask.llm_review_mode`. GROUP is the default. A prompt lists the modes
its text handles in `modes:`; the picker offers only those.

| | GROUP (default) | PAIR |
| --- | --- | --- |
| Per call | one input row + all its matches | one (input row, matched row) |
| Reply | `{"results": [...]}`, one entry per candidate | one verdict object |
| Cost | one call per input row | one call per match |
| Why | the input row is described once, so its matches are judged against a single reading of it | isolates one verdict; easier to debug |

Both the system prompt and the user template are Jinja, rendered with `mode` in
context. Write the judging rules once and put only the parts that genuinely
differ — the framing at the top and the reply schema at the bottom — behind
`{% if mode == 'GROUP' %}`.

GROUP replies are read back by the `candidate` number, not by position: a model
that drops or reorders an entry would otherwise shift every later verdict onto
the wrong contract line. A candidate the model says nothing about comes back
PENDING rather than a guess.

## File format

```markdown
---
key: preprocess_review          # prompt family; versions of one job share a key
label: Preprocess Review v1     # human-readable name
version: 1                      # integer, unique within the key
status: active                  # active | retired | draft
modes: PAIR, GROUP              # input modes this text handles (required)
default_mode: GROUP             # which to preselect for this prompt
response_format: json_object    # what the API call asks for
best_for: <one line>            # short form of the section below, shown in the UI
---

## Use Scenarios

When this prompt is the right tool, and when it is not. Say what the prompt
optimizes for and which downstream system makes that the right trade-off, so a
future reader can tell whether a new job fits it or needs its own version.
Cover both good fit and poor fit.

## System Prompt

​```text
<sent as the system message; Jinja, with `mode` in context>
​```

## User Template

​```text
<sent as the user message; Jinja, with `mode` in context>
​```
```

`## Use Scenarios`, `## System Prompt`, and `## User Template` are all required —
the loader raises on a file missing one, on an unknown mode, and on a file that
declares no `modes`. Variables in the user template come from
`llm_review._pair_context`, plus `mode`, `candidate_count`, and `candidates`
(each entry carrying the same `match_*` fields and an `index`). Under PAIR the
flat `match_*` variables describe the single match being judged; under GROUP loop
`candidates`. Source records continue to use the existing `vendor` and
`vendor_catalog_num` fields; the prompt labels them `Supplier` and
`Supplier Catalog #`. `input_supplier_type` and `match_supplier_type` are normalized to
`MANUFACTURER`, `DISTRIBUTOR`, or `UNKNOWN`.

V1 also sends application-calculated `input_ea_price` and `match_ea_price`
(raw Contract Price / QOE), plus `qoe_ratio`, `contract_price_ratio`, and
`ea_price_ratio`. Every ratio is matched/input and is computed separately for
each candidate from current raw fields, using decimal arithmetic before display
to eight significant digits. Invalid operands or zero denominators render as
`unavailable`; zero prices remain valid numerators, while QOE must be positive.
These are arithmetic evidence, not automatic decisions. V2 omits all packaging
fields, including these derived values.

V2 starts with supplier context and both raw SKUs, then uses descriptions for
support and clear conflicts. It tolerates ordinary formatting/leading-zero and
description variants; packaging-only suffixes do not change product identity.
Known unrelated manufacturer catalogs are REJECT even with matching reduced
numbers. Possible equivalents or uncertain lineage are PENDING, without
inventing M&A history. Material differences matter only when they clearly
conflict on a product-defining attribute. Exception: confirmed same supplier
plus both exact, non-placeholder SKUs routes description-only size/material/type
conflicts to PENDING for catalog verification. Reduced-SKU equality does not
qualify, and packaging-only differences remain ACCEPT. Its examples cover these
boundaries.

V1 weighs raw contract prices above EA prices derived from potentially incorrect
QOE. For the same distributor catalog, an exact complete supplier number and
equal/close positive raw prices support ACCEPT despite UOM/QOE inconsistencies.
Clear proportional quantity/price scaling or explicit different sale-unit pack
counts still support REJECT. The prompt flags suspect metadata without inventing
the correct count; it does not change the source fields.
The roughly +/-30% close-price guideline is not an ACCEPT cutoff. Across
suppliers (including manufacturer/distributor comparisons), price gaps alone
do not block ACCEPT when product and packaging are established. Unresolved
packaging still requires review; actual packaging variants still REJECT.

## V1 packaging regression reference

The compact V1 system prompt keeps five contrasting examples for GPT-5.6 Luna.
The reported cases below remain evaluation references instead of repeated prompt
examples. These are expected outcomes, not results of a live model evaluation.
Each row describes a Medline distributor comparison with established physical
product identity; prices are raw contract prices, not calculated EA prices.
For a live evaluation, include the full source descriptions and supplier roles
and check both PAIR and GROUP modes without changing the saved match decisions.

| Match ID | Mfg # (both) | Input supplier #; UOM/QOE/price | Matched supplier #; UOM/QOE/price | Expected | Decisive evidence |
| --- | --- | --- | --- | --- | --- |
| 649412 | 309695 | B-D309695; CS/100/108.68 | B-D309695Z; BX/25/27.17 | REJECT | Quantity and price scale 4x; supplier suffix differs. |
| 649534 | 2B7127 | BHL2B7127; CS/4/41.95 | BHL2B7127H; BG/1/10.49 | REJECT | Case/bag quantity and price scale about 4x. |
| 653620 | 2C8419 | BHL2C8419H; EA/1/3.59 | BHL2C8419; CA/48/172.21 | REJECT | Each/case quantity and price scale about 48x. |
| 654205 | 30416-025 | BXT30416025Z; BX/10/8.66 | BXT30416025; CA/100/86.64 | REJECT | Quantity and price scale about 10x, not a decimal error. |
| 657083 | 22853 | KDL22853; CS/600/53.00 | KDL22853; CA/200/53.00 | ACCEPT | Identical full supplier number and raw price; likely QOE error. |

## Adding a version

1. Copy the closest existing file to `<key>_v<n+1>.md`; bump `version` and `label`.
2. Edit the prompt text and rewrite `## Use Scenarios` to say when this version is
   the right pick over the others — that section is what the picker's viewer shows.
3. Cover both branches of every `{% if mode == 'GROUP' %}` you touch, and render
   the file in both modes before trusting it — a missing branch silently sends the
   wrong reply schema.
4. Leave `status: active` so it appears in the dropdown. To take a version out of
   circulation set `status: retired`; the file stays loadable, so a task stamped
   with it can still show what its verdicts were judged under.
5. To change which version is preselected, update `DEFAULT_PROMPT_NAME` in
   `__init__.py`; for the default input mode, `DEFAULT_MODE`.
6. Add a row to the catalog table above.

## Loading

```python
from preprocessorEC.services import llm_review_prompts as prompts

prompts.resolve()                      # the default (DEFAULT_PROMPT_NAME)
prompts.resolve("v1")                  # by version; also "preprocess_review_v1"
prompts.load("preprocess_review_v1")   # by file stem, retired versions included
prompts.available()                    # selectable prompts, oldest version first
prompts.names()                        # valid selection values, for validation
prompts.options()                      # UI-ready dicts, no prompt text
prompts.resolve_mode("pair")           # normalise a mode; unknown -> DEFAULT_MODE
prompts.mode_options()                 # input modes for the picker

prompt.modes                           # modes this prompt handles
prompt.supports("PAIR")                # is this mode available here?
prompt.render_system("GROUP")          # system message for one mode
prompt.render_user("GROUP", **ctx)     # user message for one mode
prompt.to_dict("GROUP")                # content rendered for the viewer modal
```

`resolve()` falls back to the default only for `None`/empty. A non-empty value
that names no prompt raises `KeyError`, so a typo in a scripted call cannot
silently rejudge a task under the wrong prompt.
