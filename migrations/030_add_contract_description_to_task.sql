-- ============================================================
-- Migration 030: Contract description on PreprocessorTask.
--
-- Adds a single nullable [contract_description] column to the task
-- header. It is populated from the CCX synced contract table
-- ([Preprocessor].[CCXSyncedContractLineCnt].ContractDescription)
-- when a preprocessor / MDM user registers a verified CCX contract
-- number on the task via the task-list edit ("register contract #")
-- flow. Displayed as an optional column on the task list.
-- ============================================================

IF COL_LENGTH('Preprocessor.PreprocessorTask', 'contract_description') IS NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorTask]
        ADD [contract_description] VARCHAR(255) NULL;
END;
