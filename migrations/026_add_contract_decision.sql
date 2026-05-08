-- ============================================================
-- Migration 026: per-contract reviewer decision (tri-state).
--
-- Today the per-contract Include/Exclude toggle on the preprocess
-- review page is derived: it flips every CCX match under a
-- (contract_id, organization_eid, erp_vendor_id) key to ACCEPTED or
-- REJECTED. There is no separate persisted record of the decision.
--
-- This migration adds a third state, REPLACE ("mark repl."), used at
-- export time to also append the un-matched lines from the matched
-- CCX contract to the per-contract review sheet -- so a reviewer can
-- see what items would still need coverage if the input replaces the
-- existing contract. Persisting the decision here (rather than
-- deriving it from match statuses) is required because REPLACE looks
-- the same as INCLUDE at the match level.
-- ============================================================

IF NOT EXISTS (
    SELECT 1 FROM sys.tables
    WHERE name = 'PreprocessorContractDecision'
      AND SCHEMA_NAME(schema_id) = 'Preprocessor'
)
BEGIN
    CREATE TABLE [Preprocessor].[PreprocessorContractDecision] (
        [decision_id]      INT IDENTITY(1,1) PRIMARY KEY,
        [task_id]          NCHAR(4)     NOT NULL,
        [organization_eid] VARCHAR(10)  NOT NULL,
        [contract_id]      VARCHAR(100) NOT NULL,
        [erp_vendor_id]    VARCHAR(20)  NOT NULL,
        [decision]         VARCHAR(10)  NOT NULL,            -- INCLUDE | EXCLUDE | REPLACE
        [decided_by]       VARCHAR(120) NOT NULL,
        [decided_at]       DATETIME     NOT NULL DEFAULT GETDATE(),
        CONSTRAINT FK_ContractDecision_Task
            FOREIGN KEY ([task_id])
            REFERENCES [Preprocessor].[PreprocessorTask]([task_id]),
        CONSTRAINT UQ_ContractDecision_Scope
            UNIQUE ([task_id], [organization_eid], [contract_id], [erp_vendor_id])
    );

    CREATE INDEX IX_ContractDecision_Task
        ON [Preprocessor].[PreprocessorContractDecision]([task_id]);
END;
