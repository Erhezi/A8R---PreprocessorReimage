-- ============================================================
-- Migration 023: per-side decision columns on the dedup workspace.
--
-- Phase 4C UI lets the user keep/drop the INPUT side and each
-- MATCHED side independently. The original [dedup_decision] column
-- (a single VARCHAR(20) per row) cannot represent both sides, so we
-- add dedicated columns and leave the original alone for now — the
-- finalize gate in 4F will derive a composite from these two.
-- ============================================================

IF COL_LENGTH('Preprocessor.PreprocessorTaskItemForDecision', 'input_decision') IS NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorTaskItemForDecision]
        ADD [input_decision] VARCHAR(10) NULL;       -- keep | drop
END;

IF COL_LENGTH('Preprocessor.PreprocessorTaskItemForDecision', 'matched_decision') IS NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorTaskItemForDecision]
        ADD [matched_decision] VARCHAR(10) NULL;     -- keep | drop
END;
