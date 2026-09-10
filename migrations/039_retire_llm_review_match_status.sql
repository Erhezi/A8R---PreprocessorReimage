-- ============================================================
-- Migration 039: Retire the LLM_REVIEW match_status sentinel
-- Run against SQL Server: PRIME on MISCPrdAdhocDB
-- Schema: Preprocessor
--
-- An LLM verdict of "undecided" used to write match_status = 'LLM_REVIEW'
-- rather than 'PENDING'. That existed as a loop guard: every LLM batch picks
-- its candidates with match_status = 'PENDING', so writing PENDING back would
-- have re-sent the same rows the LLM had just declined to decide, once per
-- click, forever.
--
-- The cost was a fourth status value the rest of the app never agreed on. The
-- contract-summary counts and the cascade rollup treated LLM_REVIEW as pending;
-- the match-list filter and count_pending_matches compared for equality against
-- 'PENDING' and did not. So those rows could not be filtered to in the UI (no
-- dropdown option, and the Pending option missed them), the finalize button
-- stayed disabled citing matches the user could not locate, and "Send PENDING
-- to LLM" advertised a count it would then review zero of.
--
-- The loop guard now lives on reviewed_by instead: a batch skips any PENDING
-- row already stamped reviewed_by = 'LLM' (see _awaiting_llm_review in
-- preprocess_service.py). No information is lost — reviewed_by, llm_confidence
-- and llm_reason already recorded that the LLM had seen the row, and the UI
-- surfaces them as the status badge tooltip. Marking a row Pending by hand
-- stamps the user as reviewed_by, which re-qualifies it for the LLM on purpose.
--
-- Backfill: collapse existing LLM_REVIEW rows to PENDING. They are undecided
-- rows that were already reviewed by the LLM, so reviewed_by is already 'LLM'
-- on them and the new guard keeps them out of the next batch exactly as the
-- sentinel did. Reads stay tolerant of the old value so an unmigrated
-- environment still blocks finalize rather than advancing undecided rows.
-- ============================================================

UPDATE [Preprocessor].[PreprocessorMatchResult]
   SET [match_status] = 'PENDING'
 WHERE UPPER([match_status]) = 'LLM_REVIEW';
GO

PRINT 'Migration 039 complete: LLM_REVIEW match_status collapsed to PENDING.';
GO
