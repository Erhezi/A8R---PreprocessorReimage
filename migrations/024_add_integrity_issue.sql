-- ============================================================
-- Migration 024: Phase 4D integrity-issue store.
--
-- Captures violations found by the post-dedup integrity validator.
-- Rows are ephemeral — the validator clears every row for the task
-- before each run, then re-inserts. There is no per-row resolution
-- workflow; the user resolves issues by editing field values and
-- re-running the validator.
-- ============================================================

IF NOT EXISTS (
    SELECT 1 FROM sys.tables
    WHERE name = 'PreprocessorIntegrityIssue'
      AND SCHEMA_NAME(schema_id) = 'Preprocessor'
)
BEGIN
    CREATE TABLE [Preprocessor].[PreprocessorIntegrityIssue] (
        [issue_id]    INT IDENTITY(1,1) PRIMARY KEY,
        [task_id]     NCHAR(4)     NOT NULL,
        [check_id]    INT          NOT NULL,            -- 1 | 2 | 3
        [severity]    VARCHAR(10)  NOT NULL DEFAULT 'ERROR',
        [group_keys]  NVARCHAR(MAX) NULL,                -- JSON: keys that define the violating group
        [affected]    NVARCHAR(MAX) NULL,                -- JSON: list of {dedup_id, side, value}
        [detail]      NVARCHAR(MAX) NULL,                -- human-readable description
        [created_at]  DATETIME     NOT NULL DEFAULT GETDATE(),
        CONSTRAINT FK_IntegrityIssue_Task
            FOREIGN KEY ([task_id])
            REFERENCES [Preprocessor].[PreprocessorTask]([task_id])
    );

    CREATE INDEX IX_IntegrityIssue_Task
        ON [Preprocessor].[PreprocessorIntegrityIssue]([task_id]);
    CREATE INDEX IX_IntegrityIssue_TaskCheck
        ON [Preprocessor].[PreprocessorIntegrityIssue]([task_id], [check_id]);
END;
