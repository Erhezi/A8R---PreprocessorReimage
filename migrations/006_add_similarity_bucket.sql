-- ============================================================
-- Migration 006: Add similarity_bucket column to PreprocessorMatchResult
-- Run against SQL Server: PRIME on MISCPrdAdhocDB
-- ============================================================

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'Preprocessor'
      AND TABLE_NAME   = 'PreprocessorMatchResult'
      AND COLUMN_NAME  = 'similarity_bucket'
)
BEGIN
    ALTER TABLE [Preprocessor].PreprocessorMatchResult
        ADD similarity_bucket NVARCHAR(10) NULL;
END;
GO
