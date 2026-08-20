-- ============================================================
-- Migration 038: Per-task LLM review input mode
-- Run against SQL Server: PRIME on MISCPrdAdhocDB
-- Schema: Preprocessor
--
-- Migration 037 recorded WHICH prompt a review pass used. The input mode is the
-- other half of that record: the same prompt judges differently depending on
-- whether it sees one pair per call or one input row with all of its matches at
-- once, because in group mode the input row is described once and the model
-- cannot drift in how it reads that row between candidates.
--
--     GROUP  one call per input row, all its matches together   (default)
--     PAIR   one call per input/match pair
--
-- Mode is now a runtime choice against any prompt rather than a property of the
-- prompt file, so a stored verdict is only fully explained by the pair
-- (llm_prompt_version, llm_review_mode).
--
-- Backfill: every review that has already run did so per pair, since group mode
-- did not exist. Tasks that recorded a prompt version are stamped 'PAIR'; tasks
-- that never ran a review stay NULL and pick up the default on their first pass.
-- ============================================================

IF COL_LENGTH('[Preprocessor].[PreprocessorTask]', 'llm_review_mode') IS NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorTask]
        ADD [llm_review_mode] NVARCHAR(10) NULL
            CONSTRAINT [DF_PreprocessorTask_llm_review_mode] DEFAULT 'GROUP';
END;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.check_constraints WHERE name = 'CK_PreprocessorTask_llm_review_mode'
)
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorTask]
        ADD CONSTRAINT [CK_PreprocessorTask_llm_review_mode]
        CHECK ([llm_review_mode] IS NULL OR [llm_review_mode] IN ('PAIR', 'GROUP'));
END;
GO

-- Anything already reviewed ran one call per pair.
UPDATE [Preprocessor].[PreprocessorTask]
   SET [llm_review_mode] = 'PAIR'
 WHERE [llm_review_mode] IS NULL
   AND [llm_prompt_version] IS NOT NULL;
GO

PRINT 'Migration 038 complete: llm_review_mode on PreprocessorTask.';
GO
