-- ============================================================
-- Migration 043: review decision on Source 4 item matches.
-- Run against SQL Server: YNBBSTVWP02\PROCDATASRVPROD, database Preprocessor
-- Schema: Preprocessor
--
-- Source 4 matches an input item to MDM_ITEM by manufacturer part number
-- alone, so the pairing can be a coincidence across manufacturers. Each
-- Source 4 candidate is now its own row on PreprocessorItemMatching with a
-- decision: an LLM compares the two descriptions (SAME -> ACCEPTED,
-- DIFFERENT -> REJECTED) and a reviewer can flip it on the Item Matching
-- Results table. Only ACCEPTED candidates label the input item; REJECTED and
-- PENDING rows stay as the record of what was proposed.
--
-- Rows from Sources 1-3 keep [mfg_only] = 0 and a NULL [match_status]; they
-- are always linked, as before.
-- ============================================================

IF COL_LENGTH('Preprocessor.PreprocessorItemMatching', 'mfg_only') IS NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorItemMatching]
        ADD [mfg_only] BIT NOT NULL
            CONSTRAINT [DF_PreprocessorItemMatching_mfg_only] DEFAULT 0;
END;
GO

IF COL_LENGTH('Preprocessor.PreprocessorItemMatching', 'match_status') IS NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorItemMatching]
        ADD [match_status] VARCHAR(20) NULL;   -- PENDING | ACCEPTED | REJECTED (Source 4 rows only)
END;
GO

IF COL_LENGTH('Preprocessor.PreprocessorItemMatching', 'llm_verdict') IS NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorItemMatching]
        ADD [llm_verdict] VARCHAR(10) NULL;    -- SAME | DIFFERENT
END;
GO

IF COL_LENGTH('Preprocessor.PreprocessorItemMatching', 'llm_reason') IS NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorItemMatching]
        ADD [llm_reason] VARCHAR(1000) NULL;
END;
GO

IF COL_LENGTH('Preprocessor.PreprocessorItemMatching', 'reviewed_by') IS NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorItemMatching]
        ADD [reviewed_by] VARCHAR(120) NULL;
END;
GO

IF COL_LENGTH('Preprocessor.PreprocessorItemMatching', 'reviewed_at') IS NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorItemMatching]
        ADD [reviewed_at] DATETIME NULL;
END;
GO
