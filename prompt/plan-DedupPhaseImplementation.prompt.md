**Plan**

The cleanest implementation is to treat Dedup as a DEDUP-phase review screen backed by the accepted CCX match rows you already generate in preprocess. The existing preprocess finalize flow already advances tasks into DEDUP through preprocess_service.py and is already called from preprocess.html, so this plan focuses on exposing the Dedup entry, replacing the stub page, and adding persistent row-level decisions.

1. Preserve and verify the current PREPROCESS → DEDUP transition rather than redesigning it. If any gap appears in testing, fix only that gap.
2. Add persistence for dedup decisions on match rows, not task items. Your requirement is per selected row, and the page is based on accepted CCX match rows, so the right storage point is models.py on `MatchResult`, with a new migration to add `dedup_decision`, `dedup_decided_by`, and `dedup_decided_at`.
3. Extend repository/service logic in task_repo.py and dedup_service.py to:
   - fetch only `matched_source=CCX` and `match_status=ACCEPTED`
   - bulk update selected `match_id`s to `UPLOAD`, `EXPIRE`, or `KEEP_AS_IS`
4. Replace the stub endpoints in routes.py with a minimal first slice:
   - a GET API for dedup rows for one task
   - a POST API for bulk decision updates
5. Add the new task-details action in task_detail.html so the `Dedup` button appears only when `task.phase === "DEDUP"`, matching the current Identity/Preprocess pattern.
6. Replace the stub UI in dedup.html with a simplified table derived from the preprocess matched-results view:
   - show only ACCEPTED CCX rows
   - no REJECTED rows
   - no INFOR_CL rows
   - checkbox selection plus three bulk actions: Upload, Expire, Keep As Is
   - show the saved dedup decision on each row
7. Validate end to end:
   - finalize preprocess and confirm the task lands in DEDUP
   - confirm the task-details Dedup button appears
   - confirm the Dedup page loads only accepted CCX rows
   - confirm each bulk action persists and reloads correctly

**Anchors**

The main implementation anchors are task_detail.html, routes.py, dedup.html, dedup_service.py, task_repo.py, and models.py.

**Scope decisions**

Included in this plan are the DEDUP task-details entry, the simplified Dedup page, persistent per-row dedup decisions, and verification of the preprocess-to-dedup transition. Excluded for now are broader Phase 4 simulation/integrity features and any export redesign unless implementation reveals a hard dependency.

I saved this plan into the session plan file as well. If this matches your intent, the next step is implementation; if you want, I can still tighten one part before handoff:
1. Keep the Dedup table minimal and narrower than preprocess
2. Add a small contract/vendor filter bar on day one
3. Include a Dedup finalize action in the same slice