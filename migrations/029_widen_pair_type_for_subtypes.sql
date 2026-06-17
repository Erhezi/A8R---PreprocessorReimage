-- ============================================================
-- Migration 029: Widen pair_type from VARCHAR(1) to VARCHAR(2)
-- to support A/B sub-typing introduced in scoring.
--
-- Type A (same contract) and Type B (same manufacturer) pairs are
-- now split by MFN equality (see services/scoring.refine_pair_type):
--     A1 / B1 — MFN matches exactly (exact-MFN weighting; no description)
--     A2 / B2 — MFN differs (description similarity folded into the score)
-- Types C and D remain single-character. Existing 'A'/'B'/'C'/'D' rows
-- stay valid; reporting can group by LEFT(pair_type, 1).
--
-- Applies to both tables that carry pair_type:
--     PreprocessorMatchResult
--     PreprocessorTaskItemForDecision
-- ============================================================

IF EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('Preprocessor.PreprocessorMatchResult')
      AND name = 'pair_type'
      AND max_length < 2
)
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorMatchResult]
        ALTER COLUMN [pair_type] VARCHAR(2) NULL;
END;

IF EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('Preprocessor.PreprocessorTaskItemForDecision')
      AND name = 'pair_type'
      AND max_length < 2
)
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorTaskItemForDecision]
        ALTER COLUMN [pair_type] VARCHAR(2) NULL;
END;
