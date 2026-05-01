-- ============================================================
-- Migration 025: Phase 4E item-master (IM) check log.
--
-- Stores warnings raised when post-dedup decisions touch item-master
-- items: dropping an existing IM line (sole coverage / affected
-- locations) or adding a new line whose vendor doesn't align with the
-- contracted location's replenishment vendor.
--
-- Treated as WARN-only on the finalize gate, but every row is persisted
-- so it can be exported and sent to MDM with the rest of the task.
-- Wiped & rewritten on every IM-check run.
-- ============================================================

IF NOT EXISTS (
    SELECT 1 FROM sys.tables
    WHERE name = 'PreprocessorIMCheckResult'
      AND SCHEMA_NAME(schema_id) = 'Preprocessor'
)
BEGIN
    CREATE TABLE [Preprocessor].[PreprocessorIMCheckResult] (
        [result_id]      INT IDENTITY(1,1) PRIMARY KEY,
        [task_id]        NCHAR(4)     NOT NULL,
        [check_id]       INT          NOT NULL,           -- 1 | 2 | 3
        [check_code]     VARCHAR(40)  NOT NULL,           -- SOLE_COVERAGE | AFFECTED_LOCATION | VENDOR_LOCATION_ALIGNMENT
        [dedup_id]       INT          NULL,
        [input_item_id]  INT          NULL,
        [severity]       VARCHAR(10)  NOT NULL DEFAULT 'WARN',
        [subject]        NVARCHAR(MAX) NULL,               -- JSON: keys that uniquely identify the subject row
        [detail]         NVARCHAR(MAX) NULL,               -- human-readable description
        [created_at]     DATETIME     NOT NULL DEFAULT GETDATE(),
        CONSTRAINT FK_IMCheckResult_Task
            FOREIGN KEY ([task_id])
            REFERENCES [Preprocessor].[PreprocessorTask]([task_id])
    );

    CREATE INDEX IX_IMCheckResult_Task
        ON [Preprocessor].[PreprocessorIMCheckResult]([task_id]);
    CREATE INDEX IX_IMCheckResult_TaskCheck
        ON [Preprocessor].[PreprocessorIMCheckResult]([task_id], [check_id]);
END;
