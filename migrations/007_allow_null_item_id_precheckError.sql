-- Migration 007: Allow NULL item_id on PreprocessorPreCheckError
-- Supports header-level pre-check errors (not tied to a specific TaskItem).
-- The ORM model already declares item_id as nullable=True; this aligns the DB.

ALTER TABLE [Preprocessor].[PreprocessorPreCheckError]
    ALTER COLUMN item_id INT NULL;
