-- ============================================================
-- Migration 004: Add file_row column to PreprocessorTaskItem
-- Run against SQL Server: PRIME on MISCPrdAdhocDB
-- ============================================================

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'Preprocessor'
      AND TABLE_NAME   = 'PreprocessorTaskItem'
      AND COLUMN_NAME  = 'file_row'
)
BEGIN
    ALTER TABLE [Preprocessor].PreprocessorTaskItem
        ADD file_row INT NULL;
END;
GO
