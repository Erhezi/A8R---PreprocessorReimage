-- ============================================================
-- Migration 002: Add intake_mode column to PreprocessorTask
-- Run against SQL Server: PRIME on MISCPrdAdhocDB
-- ============================================================

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'Preprocessor'
      AND TABLE_NAME   = 'PreprocessorTask'
      AND COLUMN_NAME  = 'intake_mode'
)
BEGIN
    ALTER TABLE [Preprocessor].PreprocessorTask
        ADD intake_mode NVARCHAR(10) NOT NULL DEFAULT 'SINGLE';
END;
GO
