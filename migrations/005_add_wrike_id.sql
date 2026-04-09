-- ============================================================
-- Migration 005: Add wrike_id column to PreprocessorTask
-- Run against SQL Server: PRIME on MISCPrdAdhocDB
-- ============================================================

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'Preprocessor'
      AND TABLE_NAME   = 'PreprocessorTask'
      AND COLUMN_NAME  = 'wrike_id'
)
BEGIN
    ALTER TABLE [Preprocessor].PreprocessorTask
        ADD wrike_id NVARCHAR(10) NULL;
END;
GO
