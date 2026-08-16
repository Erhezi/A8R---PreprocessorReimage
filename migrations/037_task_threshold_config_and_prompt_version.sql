-- ============================================================
-- Migration 037: Per-task similarity threshold config + LLM prompt version
-- Run against SQL Server: PRIME on MISCPrdAdhocDB
-- Schema: Preprocessor
--
-- HIGH/MED/LOW were fixed in code at 0.80/0.60. Where those cuts land is a
-- review-policy call, not a constant: raising HIGH and lowering MED trades
-- auto-accepts for LLM review volume, and the right trade differs by contract.
-- The thresholds are now named configurations picked per task before a run:
--
--     A  HIGH >= 0.80, MED >= 0.60   (the old fixed values)
--     B  HIGH >= 0.90, MED >= 0.45   (new default)
--     C  HIGH >= 0.95, MED >= 0.40
--
-- Both columns record what a run APPLIED, not what the UI currently shows, so a
-- stored similarity_bucket or LLM verdict can be read back against the settings
-- that produced it. Without them a task rerun under B is indistinguishable from
-- one scored under A, and every historical bucket becomes unreadable.
--
-- Backfill is deliberately narrow: only tasks that already have match results
-- ran under the old fixed thresholds, so only those are stamped 'A'. Tasks that
-- never scored stay NULL and pick up the default on their first run.
-- ============================================================

IF COL_LENGTH('[Preprocessor].[PreprocessorTask]', 'threshold_config') IS NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorTask]
        ADD [threshold_config] NVARCHAR(10) NULL
            CONSTRAINT [DF_PreprocessorTask_threshold_config] DEFAULT 'B';
END;
GO

IF COL_LENGTH('[Preprocessor].[PreprocessorTask]', 'llm_prompt_version') IS NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorTask]
        ADD [llm_prompt_version] NVARCHAR(60) NULL;
END;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.check_constraints WHERE name = 'CK_PreprocessorTask_threshold_config'
)
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorTask]
        ADD CONSTRAINT [CK_PreprocessorTask_threshold_config]
        CHECK ([threshold_config] IS NULL OR [threshold_config] IN ('A', 'B', 'C'));
END;
GO

-- Tasks with existing match results were scored under the old fixed 0.80/0.60.
UPDATE t
   SET t.[threshold_config] = 'A'
  FROM [Preprocessor].[PreprocessorTask] AS t
 WHERE t.[threshold_config] IS NULL
   AND EXISTS (
        SELECT 1
          FROM [Preprocessor].[PreprocessorMatchResult] AS m
         WHERE m.[task_id] = t.[task_id]
   );
GO

PRINT 'Migration 037 complete: threshold_config + llm_prompt_version on PreprocessorTask.';
GO
