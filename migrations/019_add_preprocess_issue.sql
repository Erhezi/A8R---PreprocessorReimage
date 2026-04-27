IF NOT EXISTS (
    SELECT 1 FROM sys.tables
    WHERE name = 'PreprocessorPreprocessIssue'
      AND SCHEMA_NAME(schema_id) = 'Preprocessor'
)
BEGIN
    CREATE TABLE [Preprocessor].[PreprocessorPreprocessIssue] (
        [issue_id]           INT IDENTITY(1,1) PRIMARY KEY,
        [task_id]            VARCHAR(4)   NOT NULL,
        [item_id]            INT          NOT NULL,
        [issue_type]         VARCHAR(40)  NOT NULL,   -- BUY_UOM_ERROR | MULTI_ITEM_ERROR
        [severity]           VARCHAR(10)  NOT NULL,   -- ERROR | WARN
        [detail]             NVARCHAR(MAX) NULL,      -- JSON payload
        [resolved]           BIT          NOT NULL DEFAULT 0,
        [resolved_by]        VARCHAR(120) NULL,
        [resolved_at]        DATETIME     NULL,
        [resolution_action]  VARCHAR(40)  NULL,       -- PICK_ITEM | NOTE | RECHECK_PASSED | IGNORE_EXPIRE
        [created_at]         DATETIME     NOT NULL DEFAULT GETDATE(),
        [updated_at]         DATETIME     NOT NULL DEFAULT GETDATE(),
        CONSTRAINT FK_PreprocessIssue_Task    FOREIGN KEY ([task_id])
            REFERENCES [Preprocessor].[PreprocessorTask]([task_id]),
        CONSTRAINT FK_PreprocessIssue_TaskItem FOREIGN KEY ([item_id])
            REFERENCES [Preprocessor].[PreprocessorTaskItem]([item_id])
    );

    CREATE INDEX IX_PreprocessIssue_Task ON [Preprocessor].[PreprocessorPreprocessIssue]([task_id]);
    CREATE INDEX IX_PreprocessIssue_Item ON [Preprocessor].[PreprocessorPreprocessIssue]([item_id]);
    CREATE INDEX IX_PreprocessIssue_Open ON [Preprocessor].[PreprocessorPreprocessIssue]([task_id], [resolved]);
END;
