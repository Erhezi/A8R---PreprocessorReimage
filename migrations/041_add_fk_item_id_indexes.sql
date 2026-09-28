-- ============================================================
-- Migration 041: single-column indexes on the item-level FK columns
-- that reference PreprocessorTaskItem.item_id.
-- Run against SQL Server: YNBBSTVWP02\PROCDATASRVPROD, database Preprocessor
-- Schema: Preprocessor
--
-- Deleting a TaskItem row makes SQL Server prove no child row still points
-- at it, once per FK, by looking up the FK column on its own. The task_id
-- filter on the DELETE plays no part in that check. Three FK columns had no
-- index led by that column:
--
--   PreprocessorMatchResult.input_item_id          (~420k rows)
--   PreprocessorTaskItemForDecision.input_item_id  (~395k rows)
--   PreprocessorPreCheckError.item_id              (~6k rows)
--
-- The (task_id, input_item_id) indexes from 040 / 022 cannot serve the check
-- because task_id leads. So every deleted item scanned both large tables,
-- even when the task-level cascade in delete_task() had already emptied them:
-- deleting a 788-item task (FBF8, 2026-09-25) ran at ~5 items/s and held the
-- request open for about three minutes. The same cost applies to
-- delete_items_for_task() on re-upload.
--
-- Standard Edition: no ONLINE builds, so each CREATE briefly blocks writes
-- to its table. A few seconds at current volumes.
-- ============================================================

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'ix_match_input_item'
      AND object_id = OBJECT_ID('[Preprocessor].[PreprocessorMatchResult]')
)
BEGIN
    CREATE INDEX [ix_match_input_item]
        ON [Preprocessor].[PreprocessorMatchResult] ([input_item_id]);
END;
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'IX_TaskItemForDecision_InputItem'
      AND object_id = OBJECT_ID('[Preprocessor].[PreprocessorTaskItemForDecision]')
)
BEGIN
    CREATE INDEX [IX_TaskItemForDecision_InputItem]
        ON [Preprocessor].[PreprocessorTaskItemForDecision] ([input_item_id]);
END;
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'ix_precheck_item'
      AND object_id = OBJECT_ID('[Preprocessor].[PreprocessorPreCheckError]')
)
BEGIN
    CREATE INDEX [ix_precheck_item]
        ON [Preprocessor].[PreprocessorPreCheckError] ([item_id]);
END;
GO
