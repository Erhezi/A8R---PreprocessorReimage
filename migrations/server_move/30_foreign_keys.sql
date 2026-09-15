-- ============================================================
-- Foreign keys
-- Generated from MISCPrdAdhocDB\PRIME [Preprocessor] on 2026-09-14.
-- Target database: Preprocessor
-- Idempotent: every object is guarded by an existence check.
-- ============================================================

-- Run AFTER the bulk load.


IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_ContractDecision_Task')
ALTER TABLE [Preprocessor].[PreprocessorContractDecision] WITH CHECK ADD CONSTRAINT [FK_ContractDecision_Task]
    FOREIGN KEY ([task_id]) REFERENCES [Preprocessor].[PreprocessorTask] ([task_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_DiscoveryItem_set')
ALTER TABLE [Preprocessor].[PreprocessorDiscoveryItem] WITH CHECK ADD CONSTRAINT [FK_DiscoveryItem_set]
    FOREIGN KEY ([set_id]) REFERENCES [Preprocessor].[PreprocessorDiscoverySet] ([set_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_DiscoveryMatch_item')
ALTER TABLE [Preprocessor].[PreprocessorDiscoveryMatch] WITH CHECK ADD CONSTRAINT [FK_DiscoveryMatch_item]
    FOREIGN KEY ([discovery_item_id]) REFERENCES [Preprocessor].[PreprocessorDiscoveryItem] ([discovery_item_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_DiscoveryMatch_prompt')
ALTER TABLE [Preprocessor].[PreprocessorDiscoveryMatch] WITH CHECK ADD CONSTRAINT [FK_DiscoveryMatch_prompt]
    FOREIGN KEY ([llm_prompt_version_id]) REFERENCES [Preprocessor].[PreprocessorDiscoveryPrompt] ([prompt_version_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_DiscoveryMatch_set')
ALTER TABLE [Preprocessor].[PreprocessorDiscoveryMatch] WITH CHECK ADD CONSTRAINT [FK_DiscoveryMatch_set]
    FOREIGN KEY ([set_id]) REFERENCES [Preprocessor].[PreprocessorDiscoverySet] ([set_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_DiscoverySet_prompt')
ALTER TABLE [Preprocessor].[PreprocessorDiscoverySet] WITH CHECK ADD CONSTRAINT [FK_DiscoverySet_prompt]
    FOREIGN KEY ([active_prompt_version_id]) REFERENCES [Preprocessor].[PreprocessorDiscoveryPrompt] ([prompt_version_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_IMCheckResult_Task')
ALTER TABLE [Preprocessor].[PreprocessorIMCheckResult] WITH CHECK ADD CONSTRAINT [FK_IMCheckResult_Task]
    FOREIGN KEY ([task_id]) REFERENCES [Preprocessor].[PreprocessorTask] ([task_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_IntegrityIssue_Task')
ALTER TABLE [Preprocessor].[PreprocessorIntegrityIssue] WITH CHECK ADD CONSTRAINT [FK_IntegrityIssue_Task]
    FOREIGN KEY ([task_id]) REFERENCES [Preprocessor].[PreprocessorTask] ([task_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_PreprocessorItemMatching_item_id')
ALTER TABLE [Preprocessor].[PreprocessorItemMatching] WITH CHECK ADD CONSTRAINT [FK_PreprocessorItemMatching_item_id]
    FOREIGN KEY ([item_id]) REFERENCES [Preprocessor].[PreprocessorTaskItem] ([item_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_PreprocessorItemMatching_task_id')
ALTER TABLE [Preprocessor].[PreprocessorItemMatching] WITH CHECK ADD CONSTRAINT [FK_PreprocessorItemMatching_task_id]
    FOREIGN KEY ([task_id]) REFERENCES [Preprocessor].[PreprocessorTask] ([task_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name=N'FK__Preproces__input__1F11D038')
ALTER TABLE [Preprocessor].[PreprocessorMatchResult] WITH CHECK ADD CONSTRAINT [FK__Preproces__input__1F11D038]
    FOREIGN KEY ([input_item_id]) REFERENCES [Preprocessor].[PreprocessorTaskItem] ([item_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name=N'FK__Preproces__task___1E1DABFF')
ALTER TABLE [Preprocessor].[PreprocessorMatchResult] WITH CHECK ADD CONSTRAINT [FK__Preproces__task___1E1DABFF]
    FOREIGN KEY ([task_id]) REFERENCES [Preprocessor].[PreprocessorTask] ([task_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name=N'FK__Preproces__item___1958F6E2')
ALTER TABLE [Preprocessor].[PreprocessorPreCheckError] WITH CHECK ADD CONSTRAINT [FK__Preproces__item___1958F6E2]
    FOREIGN KEY ([item_id]) REFERENCES [Preprocessor].[PreprocessorTaskItem] ([item_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name=N'FK__Preproces__task___1864D2A9')
ALTER TABLE [Preprocessor].[PreprocessorPreCheckError] WITH CHECK ADD CONSTRAINT [FK__Preproces__task___1864D2A9]
    FOREIGN KEY ([task_id]) REFERENCES [Preprocessor].[PreprocessorTask] ([task_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_PreprocessIssue_Task')
ALTER TABLE [Preprocessor].[PreprocessorPreprocessIssue] WITH CHECK ADD CONSTRAINT [FK_PreprocessIssue_Task]
    FOREIGN KEY ([task_id]) REFERENCES [Preprocessor].[PreprocessorTask] ([task_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_PreprocessIssue_TaskItem')
ALTER TABLE [Preprocessor].[PreprocessorPreprocessIssue] WITH CHECK ADD CONSTRAINT [FK_PreprocessIssue_TaskItem]
    FOREIGN KEY ([item_id]) REFERENCES [Preprocessor].[PreprocessorTaskItem] ([item_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_PreprocessorTask_parent_task')
ALTER TABLE [Preprocessor].[PreprocessorTask] WITH CHECK ADD CONSTRAINT [FK_PreprocessorTask_parent_task]
    FOREIGN KEY ([parent_task_id]) REFERENCES [Preprocessor].[PreprocessorTask] ([task_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name=N'FK__Preproces__task___11B7D51A')
ALTER TABLE [Preprocessor].[PreprocessorTaskItem] WITH CHECK ADD CONSTRAINT [FK__Preproces__task___11B7D51A]
    FOREIGN KEY ([task_id]) REFERENCES [Preprocessor].[PreprocessorTask] ([task_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_TaskItemForDecision_MatchResult')
ALTER TABLE [Preprocessor].[PreprocessorTaskItemForDecision] WITH CHECK ADD CONSTRAINT [FK_TaskItemForDecision_MatchResult]
    FOREIGN KEY ([match_id]) REFERENCES [Preprocessor].[PreprocessorMatchResult] ([match_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_TaskItemForDecision_Task')
ALTER TABLE [Preprocessor].[PreprocessorTaskItemForDecision] WITH CHECK ADD CONSTRAINT [FK_TaskItemForDecision_Task]
    FOREIGN KEY ([task_id]) REFERENCES [Preprocessor].[PreprocessorTask] ([task_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name=N'FK_TaskItemForDecision_TaskItem')
ALTER TABLE [Preprocessor].[PreprocessorTaskItemForDecision] WITH CHECK ADD CONSTRAINT [FK_TaskItemForDecision_TaskItem]
    FOREIGN KEY ([input_item_id]) REFERENCES [Preprocessor].[PreprocessorTaskItem] ([item_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name=N'FK__Preproces__task___23D68555')
ALTER TABLE [Preprocessor].[PreprocessorTaskStatusLog] WITH CHECK ADD CONSTRAINT [FK__Preproces__task___23D68555]
    FOREIGN KEY ([task_id]) REFERENCES [Preprocessor].[PreprocessorTask] ([task_id]);
GO
