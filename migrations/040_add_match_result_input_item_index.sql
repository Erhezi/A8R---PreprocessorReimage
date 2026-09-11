-- ============================================================
-- Migration 040: composite index on PreprocessorMatchResult to
-- scope the cascade re-aggregation to one input item.
-- Run against SQL Server: PRIME on MISCPrdAdhocDB
-- Schema: Preprocessor
--
-- Deciding a match re-aggregates the INFOR_CL/CASCADE rows that hang off the
-- CCX rows it touched. That lookup used to filter only on
-- (task_id, matched_source, match_type), and neither matched_source nor
-- match_type is indexed — so ix_match_task narrowed the seek to the task and
-- nothing more. Under READ COMMITTED the engine takes a shared lock on every
-- row it reads before the residual predicate discards it, so a query that
-- wanted a few hundred cascade rows locked every match row in the task,
-- while the same transaction already held an X lock on the row being
-- decided. Two concurrent decisions on one task therefore each held a row
-- the other's scan had to read: a lock cycle, and error 1205 for whichever
-- side SQL Server picked as victim.
--
-- update_match_decisions() now scopes both the cascade lookup and its CCX
-- source lookup by input_item_id, which is correct because a cascade row's
-- lineage never crosses input rows (CASCADE rows are built per
-- (input_item_id, infor_pkid) in preprocess_service). This index is what
-- makes that scoping actually shrink the lock footprint: without it the
-- input_item_id filter is a residual predicate applied after locking, and
-- the scan — and the deadlock — stay exactly as they were.
--
-- Also serves the other per-item paths on this table:
-- update_match_input_ea_price, get_match_results(input_item_id=...) and the
-- cascade source lookup in reaggregate_cascade_statuses.
-- ============================================================

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'ix_match_task_input_item'
      AND object_id = OBJECT_ID('[Preprocessor].[PreprocessorMatchResult]')
)
BEGIN
    CREATE INDEX [ix_match_task_input_item]
        ON [Preprocessor].[PreprocessorMatchResult] (
            [task_id],
            [input_item_id]
        )
        INCLUDE (
            [matched_source],
            [match_type],
            [ccx_pkid],
            [match_status],
            [similarity_bucket]
        );
END;
GO
