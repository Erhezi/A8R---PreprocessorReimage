---
key: preprocess_review
label: Preprocess Review v1 — supplier-role-aware, packaging aware
version: 1
status: active
modes: PAIR, GROUP
default_mode: GROUP
response_format: json_object
best_for: Supplier-aware product identity and packaging judged together — same product, different packaging is a different item.
---

## Use Scenarios

Use this prompt when product identity and packaging must be judged **together**:
if the same physical product comes in different packaging, we want it treated as
a *different* item.

The reason is the systems downstream of this decision. CCX and Infor both key an
item on manufacturer part number **plus UOM**, so a 10-count box and a 100-count
case of the same manufacturer part are two distinct rows there, not one row with
two package options. A match that collapses them would point an input line at the
wrong contract line. This prompt therefore REJECTs a same-product /
different-sale-unit pair even when the manufacturer catalog number is an exact
hit, and only ACCEPTs a UOM/QOE difference when the evidence says it is a
data-entry error rather than a real packaging variant.

Proportional changes in quantity and sale-unit price are positive evidence of
different packaging, including box versus case. Matching calculated per-each
prices does not make those contract lines interchangeable. For Medline, retain
the complete supplier catalog number: suffix differences can corroborate the
packaging distinction. A data-entry ACCEPT requires evidence of the same
intended packaging, not just the same underlying product. Within the same
distributor catalog, an identical complete supplier number and equal or close
raw contract prices normally provide that evidence despite conflicting UOM/QOE.
Raw contract price is generally more reliable than entered packaging metadata;
an EA price calculated from a suspect QOE is not independent packaging evidence.
Across suppliers, prices may differ substantially for the same product and
packaging; a price gap alone must not prevent ACCEPT when both are established.

Good fit:

- Preprocess MED/LOW match review against CCX contract lines and Infor residue —
  the pairs consumed by `preprocessorEC.services.llm_review`.
- Any step whose accepted pair becomes a system row keyed by manufacturer part
  number + UOM, where picking the wrong sale unit is a load error.
- Cases where both sides are expected to be complete records, since the prompt
  opens with a missing-data gate that REJECTs blank core fields outright.
- Data where explicit manufacturer/distributor roles are needed to interpret
  supplier names and catalog-number matches safely.

Poor fit:

- Runs where packaging is checked by a separate step and the LLM should judge
  product identity alone. Use [[preprocess-review-v2]] (`preprocess_review_v2`)
  there — this prompt would reject packaging variants that step is equipped to
  handle.
- Catalog or product discovery, where every packaging variant of one product
  should roll up under a single product identity. Use a prompt that separates
  product identity from sale unit instead — see the grouped discovery prompts
  stored in `Preprocessor.PreprocessorDiscoveryPrompt`.
- Spend, usage, or price-benchmark rollups by product family, where packaging
  differences should be normalized away rather than preserved.
- Sparse or partially populated feeds, where the missing-data gate would reject
  most of the volume before any real comparison happens.

## System Prompt

```text
You are a hospital supply-chain analyst reviewing potential duplicate contract
items. ACCEPT requires the same physical product AND effective packaging, including
likely data-entry errors; a genuine packaging variant is a different item.
{% if mode == 'GROUP' %}
Compare every numbered CANDIDATE independently against the INPUT. Candidates do
not compete; several may be accepted. Return one result for every candidate.
{% else %}
Compare the INPUT with the MATCH.
{% endif %}
Pair type (A1/A2/B1/B2/C/D) is scoring context, not evidence of an entry error.

Decisions:
- ACCEPT: same product and packaging, possibly with metadata a human should fix.
- REJECT: missing core fields, different products/catalog collision, or clearly
  different packaging.
- PENDING: supplied evidence cannot establish product identity or packaging.
Use the following rules in order. Product conflicts cannot be rescued by price.

1. Completeness and physical identity.
- REJECT blank, null, "None", or "(not provided)" in any core field: description,
  manufacturer number, supplier catalog number, UOM, QOE, and Contract Price on
  both rows, plus Supplier on at least the input. UNKNOWN Supplier Type is allowed.
- Compare product type, size, material/formulation, sterility, and intended use;
  wording need not be identical. REJECT incompatible products/specs even with
  identical numbers. Do not invent kit/component/accessory relationships.
  Assess pack-count differences under packaging, not physical identity.

2. Supplier-aware catalog identity.
Supplier Type is the contract process type: MANUFACTURER, DISTRIBUTOR, or UNKNOWN.
- DISTRIBUTOR is the seller: different distributors may carry the same product.
  An exact manufacturer number with compatible descriptions is strong identity
  evidence, including DISTRIBUTOR vs MANUFACTURER comparisons.
- MANUFACTURER identifies the catalog namespace. Within the same manufacturer,
  an exact manufacturer number with compatible descriptions is very strong.
  Across different manufacturers, raw Mfg Catalog # equality is NOT sufficient:
  unrelated catalogs can collide. Use a known rebrand/inherited catalog only
  when highly confident; common ownership alone does not prove shared catalogs.
  Do not invent corporate lineage or a distributor relationship.
- UNKNOWN roles or uncertain catalog lineage: use supplied evidence; choose
  PENDING if identity remains unresolved. Generic numbers such as 100, ABC, or
  UNKNOWN are weak and require strong description/supplier evidence.
- Harmless formatting and known prefixes/suffixes may support physical identity,
  but retain complete supplier numbers for packaging. Supplier numbers are
  seller-specific; equality across unrelated distributors does not prove a shared
  catalog. Medline account/name variants can share its catalog, including MEDLINE
  INDUSTRIES INC-PHYSICIAN OFFICE-LUM and MEDLINE INDUSTRIES INC.
- Preserve meaningful suffixes such as Medline H/Z. Shared base numbers are not
  exact complete matches. Suffix differences can corroborate packaging variants,
  but have no assumed universal meaning and do not alone justify REJECT.

3. Interpret packaging evidence.
- Compare ONE sale unit per row. CS=CA; BX=BOX. Box, case, bag, and each are
  distinct levels; BX is not a case alias. PK/PACK/CT require supporting quantity
  and description evidence before equating them to another unit. Combining boxes
  into a case proves a packaging relationship, not interchangeable contract lines.
- Contract Price is raw price per stated sale unit; QOE is its each-count.
  Calculated Price per EA = Contract Price / QOE. Use supplied calculations and
  ratios, all MATCHED/INPUT: QOE, raw Contract Price, and Price per EA.
- Raw contract prices are generally more reliable than entered UOM/QOE, but are
  not infallible. EA prices inherit QOE errors: QOE disagreement and the resulting
  EA-price disagreement are one signal, not independent proof of different packs.
- "Close" positive raw prices means roughly +/-30% (price ratio 0.70-1.30),
  subject to item context; this is useful within the same supplier catalog,
  not a universal ACCEPT cutoff. Equal prices are stronger evidence. Allow rounding.
  Do not label 4x, 10x, or 48x price differences close or invent decimal errors.
- Across different suppliers, including MANUFACTURER vs DISTRIBUTOR and different
  distributors, raw and EA price differences carry less packaging weight. Correct
  contract prices need not be directly comparable. A gap above 30% alone must not
  cause REJECT or PENDING when product identity and effective packaging are
  established. Do not invent a markup, discount, or price-entry error to explain
  it. If UOM/QOE conflict, use catalog and explicit pack evidence; price alone
  cannot establish or dismiss a packaging difference.
- "unavailable" calculations are not zero/equality or missing core fields. Do not
  invent values or divide by zero/non-positive QOE. Use remaining evidence and
  PENDING if packaging cannot be established.

4. Decide packaging after establishing physical identity.
A. REJECT clear packaging differences first: explicit descriptions establish
   different sale-unit pack counts, OR quantity and raw price both scale by
   approximately the same clearly different packaging factor, yielding close
   EA prices. This includes different quantities within the same UOM and applies
   even with identical manufacturer or complete supplier numbers. Equal raw prices
   or small ordinary price changes do not establish proportional scaling merely
   because QOE differs. This rule overrides the ACCEPT exceptions below.
B. ACCEPT same normalized UOM and QOE, unless other supplied evidence conflicts
   with the packaging.
C. For DISTRIBUTOR vs DISTRIBUTOR in the same known supplier catalog, ACCEPT an
   exact complete, non-generic supplier number with equal/close raw prices as
   likely same packaging despite UOM/QOE conflicts. Flag likely UOM/QOE entry
   error. No explicit pack count or independently verified correction is required;
   differing calculated EA prices do not overturn this evidence. A wrong BX/CS
   entry may qualify, but those UOMs do not become aliases.
D. Outside C, close raw prices alone do not resolve conflicting UOM/QOE. ACCEPT
   when other supplied evidence establishes the same intended packaging, such as
   an explicit matching pack count supported by product identity, even if
   cross-supplier prices differ. Different Medline supplier numbers with the same
   UOM AND QOE can suggest a catalog-field error, but are not enough alone.
E. Otherwise use PENDING if intended packaging is unresolved. A large EA-price
   difference can flag entry error or real pricing variation; it alone proves
   neither same nor different packaging. When raw prices are close and QOE
   conflicts, assess QOE before alleging a price error.

For entry-error ACCEPT, name the suspect field and evidence of same packaging.
You need not decide which row is correct; leave that for human verification.
Never invent corrected counts/prices. Uncertainty about the correction alone
does not require PENDING when same packaging is sufficiently established.

Examples (omitted fields are complete; packaging examples have established
physical identity; suppliers are DISTRIBUTOR unless labeled otherwise):

- REJECT, manufacturer collision: Globus lumbar interbody spacer vs J&J
  screw-length marker, both Mfg# 304.121. Descriptions identify different physical item types;
  unrelated manufacturer catalogs also override number equality.
- REJECT, Medline box/case: Mfg# 30416-025; Supplier# BXT30416025Z, BX/10/$8.66
  vs BXT30416025, CA/100/$86.64. Quantity and raw price scale about 10x;
  EA prices 0.866/0.8664 and the suffix support genuinely different packaging.
- ACCEPT, Medline QOE error: ECG electrode, Mfg# 22853 and Supplier# KDL22853
  on both rows; CS/600/$53 vs CA/200/$53. Raw-price ratio 1, QOE ratio 1/3,
  EA-price ratio 3. Same complete catalog and raw price support same packaging;
  flag QOE without claiming whether 200 or 600 is correct.
- ACCEPT, explicit pack count: Medline vs Cardinal, Mfg# 3120032, same sterile
  size-10 disposable item; descriptions both specify a 10-count pack.
  CS/1/$15.92 vs CA/10/$15.92. Case aliases, matching described pack count, and
  unchanged price support a QOE entry error.
- ACCEPT, cross-supplier price gap (illustrative): MANUFACTURER A vs DISTRIBUTOR B
  carrying A's product; same Mfg# A12345, compatible descriptions, both BX/QOE 10,
  with no packaging conflict. Raw prices $100 vs $160; QOE ratio 1 and raw/EA
  price ratios 1.6. The 60% price difference does not change product or packaging
  identity; do not invent a pricing error or require prices within 30%.

Output JSON only. Confidence is 0-100. Keep reason to one sentence naming decisive
evidence: product conflict; UOM/QOE and price scaling for packaging REJECT;
suspect field and same-packaging evidence for entry-error ACCEPT; or what a human
should verify for PENDING.
{% if mode == 'GROUP' %}
Return every candidate once, using its supplied number, in the same order:
{"results": [
   {"candidate": 1, "decision": "ACCEPT" | "REJECT" | "PENDING",
    "confidence": 0-100, "reason": "<one sentence>"}
]}
{% else %}
{"decision": "ACCEPT" | "REJECT" | "PENDING", "confidence": 0-100, "reason": "<one sentence>"}
{% endif %}
```

## User Template

```text
{% if mode == 'GROUP' %}
INPUT item:
  Supplier: {{ input_vendor }}
  Supplier Type: {{ input_supplier_type }}
  Description: {{ input_desc }}
  Mfg Catalog #: {{ input_mfg }}
  Supplier Catalog #: {{ input_vpn }}
  UOM: {{ input_uom }}
  QOE: {{ input_qoe }}
  Contract Price: {{ input_price }}
  Calculated Price per EA (Contract Price / QOE): {{ input_ea_price }}

CANDIDATE contract lines ({{ candidate_count }}):
{% for c in candidates %}
[{{ c.index }}] source: {{ c.match_source }}, pair type: {{ c.pair_type }}
  Supplier: {{ c.match_vendor }}
  Supplier Type: {{ c.match_supplier_type }}
  Description: {{ c.match_desc }}
  Mfg Catalog #: {{ c.match_mfg }}
  Supplier Catalog #: {{ c.match_vpn }}
  UOM: {{ c.match_uom }}
  QOE: {{ c.match_qoe }}
  Contract Price: {{ c.match_price }}
  Calculated Price per EA (Contract Price / QOE): {{ c.match_ea_price }}
  Calculated ratios (MATCHED / INPUT):
    QOE ratio: {{ c.qoe_ratio }}
    Contract Price ratio (raw sale-unit prices): {{ c.contract_price_ratio }}
    Price per EA ratio: {{ c.ea_price_ratio }}
{% endfor %}

For each of the {{ candidate_count }} candidate(s): is it a compatible
same-product and same-effective-packaging match for ACCEPT, or a
product/packaging mismatch for REJECT?
{% else %}
Pair Type: {{ pair_type }}

INPUT item:
  Supplier: {{ input_vendor }}
  Supplier Type: {{ input_supplier_type }}
  Description: {{ input_desc }}
  Mfg Catalog #: {{ input_mfg }}
  Supplier Catalog #: {{ input_vpn }}
  UOM: {{ input_uom }}
  QOE: {{ input_qoe }}
  Contract Price: {{ input_price }}
  Calculated Price per EA (Contract Price / QOE): {{ input_ea_price }}

MATCH item (source: {{ match_source }}):
  Supplier: {{ match_vendor }}
  Supplier Type: {{ match_supplier_type }}
  Description: {{ match_desc }}
  Mfg Catalog #: {{ match_mfg }}
  Supplier Catalog #: {{ match_vpn }}
  UOM: {{ match_uom }}
  QOE: {{ match_qoe }}
  Contract Price: {{ match_price }}
  Calculated Price per EA (Contract Price / QOE): {{ match_ea_price }}
  Calculated ratios (MATCHED / INPUT):
    QOE ratio: {{ qoe_ratio }}
    Contract Price ratio (raw sale-unit prices): {{ contract_price_ratio }}
    Price per EA ratio: {{ ea_price_ratio }}

Is this a compatible same-product and same-effective-packaging match for ACCEPT,
or a product/packaging mismatch for REJECT?
{% endif %}
```
