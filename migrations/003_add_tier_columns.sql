-- ============================================================
-- Migration 003: Add tier columns to PreprocessorTaskItem
-- Run against SQL Server: PRIME on MISCPrdAdhocDB
-- ============================================================

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'Preprocessor'
      AND TABLE_NAME   = 'PreprocessorTaskItem'
      AND COLUMN_NAME  = 'tier_description'
)
BEGIN
    ALTER TABLE [Preprocessor].PreprocessorTaskItem
        ADD tier_description NVARCHAR(255) NULL;
END;
GO

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'Preprocessor'
      AND TABLE_NAME   = 'PreprocessorTaskItem'
      AND COLUMN_NAME  = 'tier_level'
)
BEGIN
    ALTER TABLE [Preprocessor].PreprocessorTaskItem
        ADD tier_level NVARCHAR(50) NULL;
END;
GO
