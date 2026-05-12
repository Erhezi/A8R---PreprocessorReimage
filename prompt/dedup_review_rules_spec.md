# Dedup Review — Action & Notes Rules

Authoritative rules for the **Action** and **Notes** columns of the per-contract
"dedup review" sheets in the `dedup_output_to_review_<contract>_<vendor>_<date>.xlsx`
workbook. Implementation lives in
[preprocessorEC/services/dedup_review_rules.py](../preprocessorEC/services/dedup_review_rules.py)
and is consumed by `_matched_row_dict` in
[preprocessorEC/services/dedup_review_export.py](../preprocessorEC/services/dedup_review_export.py).

The doc is structured as three anchors that all describe the same logic:
**(1)** an inputs/constants section, **(2)** decision tables (the source of
truth — copy/paste-able and unambiguous for both humans and AI), and
**(3)** a worked-example block. If they ever disagree, the tables win.

---

## 1. Inputs

Each pair = one row from `PreprocessorTaskItemForDecision` (CCX side, ACCEPTED).
Symbols used in the tables below:

| Symbol | Source field | Domain |
|---|---|---|
| `group` | `resolution_grouping` | `SS` \| `DV` \| `ODO` \| `TCCD` \| `CECCD` |
| `intent` | `task_intention` | `UPDATE` \| `NEW` \| `EXPIRE` (MIX → snapshotted as one of these per row) |
| `mt_p` | `matched_contract_source_type == 'PREMIER'` | bool |
| `in_p` | `input_contract_source_type == 'PREMIER'` | bool |
| `mt_org` | `org_type(organization_eid_matched)` | `MHS` \| `ME` |
| `in_org` | `org_type(organization_eid_input)` | `MHS` \| `ME` |
| `ea_mt` | `ea_price_matched` | float \| null |
| `ea_in` | `ea_price_input` | float \| null |
| `cid` | `contract_id_matched` | string |

## 2. Constants and derived values

- **MHS organization EID** (single MHS instance): `"105188574"`. Anything else → `ME`.
  - `org_type(eid) = "MHS" if eid.strip() == "105188574" else "ME"`
- **EA price tolerance**: prices are equal when `abs(ea_in - ea_mt) < 0.0001`.
- **Price relation `pr`** (`ea_in`, `ea_mt` → `EQ` | `MT_BETTER` | `IN_BETTER`):
  - if either side is `null` → `EQ` (don't fabricate a "better price" claim).
  - else if `abs(ea_mt - ea_in) < 0.0001` → `EQ`
  - else if `ea_mt < ea_in` → `MT_BETTER`
  - else → `IN_BETTER`
- **Intention normalization**: any `intent` not in `{UPDATE, NEW, EXPIRE}`
  is treated as `UPDATE` (defensive — populator shouldn't emit anything else).
- **(MHS, MHS) under CECCD is impossible** by definition: CECCD requires
  different organizations, and MHS is a single org. The CECCD tables omit
  this case.

## 3. Action column

One row per (`group`, `intent`). UPDATE and NEW always share the same value.

| group | intent ∈ {UPDATE, NEW} | intent = EXPIRE |
|---|---|---|
| SS | `Same contract item, Update` | `Same contract item, Update expiration date to expire` |
| DV | `Buy from different vendor, keep both` | `Not affected by expiring the input line, keep the record` |
| ODO | `Buy for different organization using same contract ID, review` | `Not affected by expiring the input line, keep the record` |
| TCCD | `Consider only keep one record, review` | `Not affected by expiring the input line, keep the record` |
| CECCD | `Buy for different organization using different contract, review` | `Not affected by expiring the input line, keep the record` |

## 4. Notes column

**Rule of relevance:** Notes is empty unless `group ∈ {ODO, TCCD, CECCD}` **and**
`intent ∈ {UPDATE, NEW}`. SS and DV are always empty. Any EXPIRE row is empty.

### 4.1 ODO (same contract + vendor, different org)

Two cases only — price doesn't enter:

| (mt_org, in_org) | Notes |
|---|---|
| (ME, ME) | `Different member entity contract item, keep both and make sure the data elements are consistent with each other` |
| any combo with MHS | `If not for tracking price difference between member entity and MHS, consider maintain only the MHS contract and remove the member entity contract entirely. Otherwise if price difference is desired, keep both and make sure the data elements are consistent with each other.` |

### 4.2 TCCD (same org + vendor, different contract)

| pr | (mt_p, in_p) | Notes |
|---|---|---|
| EQ | (P, P) | `both contracts have the same price, both are premier contract, keep both and ensure the data elements are consistent with each other` |
| EQ | (P, L) | `both contracts have the same price, but matched contract is premier while input contract is local, consider keep the matched record and drop the input line` |
| EQ | (L, P) | `both contracts have the same price, but input contract is premier while matched contract is local, consider keep the input record and drop the matched line` |
| EQ | (L, L) | `both contracts have the same price, both are local contract, review and keep only one record` |
| MT_BETTER | (P, P) | `contract {cid} has better price, both are premier contract, go back to Premier to make a custom tier on the input contract reflecting the desirable lower price of contract {cid}` |
| MT_BETTER | (P, L) | `contract {cid} has better price, matched contract is premier while input contract is local, consider keep the matched record and drop the input line` |
| MT_BETTER | (L, P) | `contract {cid} has better price, but input is premier contract, go back to Premier to make a custom tier on the input contract reflecting the desirable lower price of matched contract {cid}` |
| MT_BETTER | (L, L) | `contract {cid} has better price, both are local contract, review and keep the matched record and drop the input line` |
| IN_BETTER | (P, P) | `input contract has better price, both are premier contract, go back to Premier to make a custom tier on matched contract {cid} reflecting the desirable lower price of the input contract` |
| IN_BETTER | (P, L) | `input contract has better price, but matched contract is premier while input contract is local, go back to Premier to make a custom tier on matched contract {cid} reflecting the desirable lower price of the input contract` |
| IN_BETTER | (L, P) | `input contract has better price, input contract is premier while matched contract is local, consider keep the input record and drop the matched line` |
| IN_BETTER | (L, L) | `input contract has better price, both are local contract, review and keep the input record and drop the matched line` |

**Underlying logic.** Prefer the lower-price contract. Override with the
"premier cannot be dropped" constraint: when the side that would be dropped
is premier, go back to Premier to negotiate a custom tier on the premier
contract that reflects the desirable lower price (2026 May Policy Guidance,
may change).

### 4.3 CECCD (different org, different contract)

Three org sub-cases. **(MHS, MHS) is impossible** (single MHS org).

#### 4.3.1 (mt_org, in_org) = (ME, ME)

Source-type quadrant doesn't change the message: keep both, ensure data
elements consistent, and (when prices differ) verify the price gap is real.

| pr | Notes |
|---|---|
| EQ | `both contracts have the same price, but for different member entities, keep both and ensure the data elements are consistent with each other` |
| MT_BETTER | `contract {cid} has better price, but for different member entities, keep both and ensure the data elements are consistent with each other, verfify that we truely have contract price difference between different member enetities for the item` |
| IN_BETTER | `input contract has better price, but for different member entities, keep both and ensure the data elements are consistent with each other, verfify that we truely have contract price difference between different member enetities for the item` |

#### 4.3.2 (mt_org, in_org) = (MHS, ME)

| pr | (mt_p, in_p) | Notes |
|---|---|---|
| EQ | (P, P) | `both contracts have the same price, both are premier contract, keep both and ensure the data elements are consistent with each other` |
| EQ | (L, L) | `both contracts have the same price, both are local contract, consider keep the matched MHS record and drop the input ME record` |
| EQ | (L, P) | `both contracts have the same price, but input ME contract is premier, keep both and ensure the data elements are consistent with each other` |
| EQ | (P, L) | `both contracts have the same price, input ME contract is local, consider keep the matched MHS record and drop the input ME record` |
| MT_BETTER | (P, P) | `MHS contract {cid} has better price, both are premier contract, verify the price difference is due to member entity truely have to pay higher price than MHS for the item, otherwise go back to Premier to make a custom tier on the input ME contract reflecting the desirable lower price of MHS contract {cid}` |
| MT_BETTER | (L, L) | `MHS contract {cid} has better price, both are local contract, verify the price difference is due to member entity truely have to pay higher price than MHS for the item, otherwise consider keep the matched MHS record and drop the input ME record` |
| MT_BETTER | (L, P) | `MHS contract {cid} has better price, but input ME contract is premier, verify the price difference is due to member entity truely have to pay higher price than MHS for the item, otherwise go back to Premier to make a custom tier on the input ME contract reflecting the desirable lower price of MHS contract {cid}` |
| MT_BETTER | (P, L) | `MHS contract {cid} has better price, verify the price difference is due to member entity truely have to pay higher price than MHS for the item, otherwise consider keep the matched MHS record and drop the input ME record` |
| IN_BETTER | (P, P) | `input ME contract has better price, both are premier contract, keep both and ensure the data elements are consistent with each other, verify the price difference is due to member entity truely have to pay lower price than MHS for the item` |
| IN_BETTER | (L, L) | `input ME contract has better price, both are local contract, verify the price difference is due to member entity truely have to pay lower price than MHS for the item, keep both and ensure the data elements are consistent with each other, otherwise consider keep the matched MHS record and drop the input ME record` |
| IN_BETTER | (L, P) | `input ME contract has better price, keep both and ensure the data elements are consistent with each other, verify the price difference is due to member entity truely have to pay lower price than MHS for the item` |
| IN_BETTER | (P, L) | `input ME contract has better price, keep both and ensure the data elements are consistent with each other, verify the price difference is due to member entity truely have to pay lower price than MHS for the item, otherwise consider keep the matched MHS record and drop the input ME record` |

#### 4.3.3 (mt_org, in_org) = (ME, MHS)

| pr | (mt_p, in_p) | Notes |
|---|---|---|
| EQ | (P, P) | `both contracts have the same price, both are premier contract, keep both and ensure the data elements are consistent with each other` |
| EQ | (L, L) | `both contracts have the same price, both are local contract, consider keep the input MHS record and drop the matched ME record` |
| EQ | (L, P) | `both contracts have the same price, but matched MHS contract is premier, consider keep the input MHS record and drop the matched ME record` |
| EQ | (P, L) | `both contracts have the same price, matched MHS contract is local, keep both and ensure the data elements are consistent with each other` |
| MT_BETTER | (P, P) | `member entity contract {cid} has better price, both are premier contract, keep both and ensure the data elements are consistent with each other, verify the price difference is due to member entity truely have to pay lower price than MHS for the item` |
| MT_BETTER | (L, L) | `member entity contract {cid} has better price, both are local contract, verify the price difference is due to member entity truely have to pay lower price than MHS for the item, otherwise consider keep the input MHS record and drop the matched ME record` |
| MT_BETTER | (L, P) | `member entity contract {cid} has better price, keep both and ensure the data elements are consistent with each other, verify the price difference is due to member entity truely have to pay lower price than MHS for the item, otherwise consider keep the input MHS record and drop the matched ME record` |
| MT_BETTER | (P, L) | `member entity contract {cid} has better price, keep both and ensure the data elements are consistent with each other, verify the price difference is due to member entity truely have to pay lower price than MHS for the item` |
| IN_BETTER | (P, P) | `input MHS contract has better price, both are premier contract, verify the price difference is due to member entity truely have to pay higher price than MHS for the item, otherwise go back to Premier to make a custom tier on matched ME contract {cid} reflecting the desirable lower price of the input MHS contract` |
| IN_BETTER | (L, L) | `input MHS contract has better price, both are local contract, verify the price difference is due to member entity truely have to pay higher price than MHS for the item, otherwise consider keep the input MHS record and drop the matched ME record` |
| IN_BETTER | (L, P) | `input MHS contract has better price, keep both and ensure the data elements are consistent with each other, verify the price difference is due to member entity truely have to pay higher price than MHS for the item, otherwise consider keep the input MHS record and drop the matched ME record` |
| IN_BETTER | (P, L) | `input MHS contract has better price, but matched ME contract is premier, verify the price difference is due to member entity truely have to pay higher price than MHS for the item, otherwise go back to Premier to make a custom tier on matched ME contract {cid} reflecting the desirable lower price of the input MHS contract` |

**Underlying logic.**
- (ME, ME): always keep both — different member entities legitimately have different lines.
- (MHS, ME) / (ME, MHS): prefer the MHS record when prices match. Override with the "premier cannot be dropped" constraint. When prices differ, the spec recommends *first verifying* whether the ME-side price gap is real before falling back to drop-ME logic. If verification finds the gap shouldn't exist and the ME side that would be dropped is premier, the May 2026 Policy Guidance replaces the old "keep both + Infor priority" advice with "go back to Premier to make a custom tier on the ME contract reflecting the desirable lower price" (may change in the future). Equal-price premier-protected cases stay on keep-both with data integrity, since there is no lower price to negotiate.

## 5. Worked examples

| Scenario | Inputs | Action | Notes |
|---|---|---|---|
| SS UPDATE — direct dup | `group=SS, intent=UPDATE` | `Same contract item, Update` | _empty_ |
| DV NEW | `group=DV, intent=NEW` | `Buy from different vendor, keep both` | _empty_ |
| ODO MHS-side | `group=ODO, intent=UPDATE, mt_org=MHS, in_org=ME` | `Buy for different organization using same contract ID, review` | `If not for tracking price difference between...` |
| TCCD same price both premier | `group=TCCD, intent=UPDATE, mt_p=T, in_p=T, ea_mt≈ea_in` | `Consider only keep one record, review` | `both contracts have the same price, both are premier contract, keep both and ensure the data elements are consistent with each other` |
| TCCD matched better, input premier | `group=TCCD, intent=UPDATE, ea_mt < ea_in, mt_p=F, in_p=T, cid='C123'` | `Consider only keep one record, review` | `contract C123 has better price, but input is premier contract, go back to Premier to make a custom tier on the input contract reflecting the desirable lower price of matched contract C123` |
| CECCD (MHS,ME) input ME better, both local | `group=CECCD, intent=UPDATE, mt_org=MHS, in_org=ME, mt_p=F, in_p=F, ea_in < ea_mt` | `Buy for different organization using different contract, review` | `input ME contract has better price, both are local contract, verify the price difference is due to...` (drop ME otherwise) |
| Any EXPIRE non-SS | `group∈{DV,ODO,TCCD,CECCD}, intent=EXPIRE` | `Not affected by expiring the input line, keep the record` | _empty_ |

## 6. Edge cases

- **Missing prices** (`ea_mt` or `ea_in` is null): `pr` defaults to `EQ`. The
  reviewer will see no "better price" claim and can act on the missing data
  during review.
- **Missing source_type**: treated as non-premier (`Local`). Conservative —
  premier protection only kicks in when explicitly recorded.
- **Missing organization_eid**: `org_type` returns `ME` (anything that isn't
  the MHS EID). MHS rules don't fire without the explicit MHS EID.
- **Missing/unknown `group`**: Action and Notes both blank. Defensive only —
  the workspace populator always assigns a group.
- **TCCD same-price both-local** (line 38 in temp_report.md): the rule
  intentionally defers to the reviewer ("review and keep only one record")
  rather than picking a side. To be revisited when business rules give a
  default.
