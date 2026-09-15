-- ============================================================
-- Schemas required by the move
-- Generated from MISCPrdAdhocDB\PRIME [Preprocessor] on 2026-09-14.
-- Target database: see each block
-- Idempotent: every object is guarded by an existence check.
-- ============================================================

-- === Run against PLMPreprocessorShared ===========================
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = N'Preprocessor')
    EXEC(N'CREATE SCHEMA [Preprocessor]');
GO

-- === Run against Preprocessor ====================================
-- [ghx]   already exists - CCXSyncContract is loaded into it by E0-ETL.
-- [infor] already exists - 5 tables migrated ahead of this work.
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = N'Preprocessor')
    EXEC(N'CREATE SCHEMA [Preprocessor]');
GO
