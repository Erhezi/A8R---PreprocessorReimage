-- ============================================================
-- Migration 028: composite index on PreprocessorMatchResult to
-- support the per-contract decision bulk update path.
--
-- submit_contract_decision() filters MatchResult by
-- (task_id, contract_number, organization_eid_matched,
--  erp_vendor_id_matched) when applying INCLUDE/EXCLUDE/REPLACE
-- to every match under a contract scope. Without this index the
-- UPDATE scans every match row for the task.
--
-- Also covers the cascade re-aggregation step which loads CCX +
-- INFOR_CL/CASCADE rows scoped by (task_id, matched_source,
-- input_item_id) — that path already benefits from the existing
-- ix_match_task_id, but the new composite gives the optimizer a
-- much tighter seek when the toggle path is hot.
-- ============================================================

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'ix_match_contract_scope'
      AND object_id = OBJECT_ID('[Preprocessor].[PreprocessorMatchResult]')
)
BEGIN
    CREATE INDEX [ix_match_contract_scope]
        ON [Preprocessor].[PreprocessorMatchResult] (
            [task_id],
            [contract_number],
            [organization_eid_matched],
            [erp_vendor_id_matched]
        );
END;
