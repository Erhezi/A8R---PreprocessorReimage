-- ============================================================
-- Migration 027: Edit tracking on PreprocessorTaskItem.
--
-- Adds:
--   - 6 original_* snapshot columns capturing post-PC1 cleaned
--     baseline values for the fields users are allowed to edit
--     in Phase 1 (MPN, VPN, description, UOM, QOE, unit price).
--   - 1 edits NVARCHAR(MAX) audit column (JSON list of per-edit
--     records: {field, original, current, edited_by, edited_at}).
--
-- The snapshots are populated once by run_precheck on the FIRST
-- PC1 pass that touches a given INPUT-sourced item, and never
-- overwritten afterwards. Downstream CCX export compares current
-- vs original to decide between an in-place UPDATE and an
-- EXPIRE+INSERT split (MPN or UOM change triggers split).
-- ============================================================

IF COL_LENGTH('Preprocessor.PreprocessorTaskItem', 'original_mfg_catalog_num') IS NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorTaskItem]
        ADD [original_mfg_catalog_num] VARCHAR(255) NULL;
END;

IF COL_LENGTH('Preprocessor.PreprocessorTaskItem', 'original_vendor_catalog_num') IS NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorTaskItem]
        ADD [original_vendor_catalog_num] VARCHAR(255) NULL;
END;

IF COL_LENGTH('Preprocessor.PreprocessorTaskItem', 'original_description') IS NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorTaskItem]
        ADD [original_description] NVARCHAR(MAX) NULL;
END;

IF COL_LENGTH('Preprocessor.PreprocessorTaskItem', 'original_uom') IS NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorTaskItem]
        ADD [original_uom] VARCHAR(50) NULL;
END;

IF COL_LENGTH('Preprocessor.PreprocessorTaskItem', 'original_qoe') IS NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorTaskItem]
        ADD [original_qoe] INT NULL;
END;

IF COL_LENGTH('Preprocessor.PreprocessorTaskItem', 'original_unit_price') IS NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorTaskItem]
        ADD [original_unit_price] NUMERIC(18, 4) NULL;
END;

IF COL_LENGTH('Preprocessor.PreprocessorTaskItem', 'edits') IS NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorTaskItem]
        ADD [edits] NVARCHAR(MAX) NULL;
END;
