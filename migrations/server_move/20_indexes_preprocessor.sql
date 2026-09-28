-- ============================================================
-- Non-clustered indexes
-- Generated from MISCPrdAdhocDB\PRIME [Preprocessor] on 2026-09-14.
-- Target database: Preprocessor
-- Idempotent: every object is guarded by an existence check.
-- ============================================================

-- Run AFTER the bulk load: building these on populated tables is faster.


IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'UX_OrganizationContractIDVendorERPID'
               AND object_id=OBJECT_ID(N'[Preprocessor].[CCXInforSyncedContractHeader]'))
CREATE UNIQUE NONCLUSTERED INDEX [UX_OrganizationContractIDVendorERPID] ON [Preprocessor].[CCXInforSyncedContractHeader] ([Organization], [ContractID], [ERPVendorID]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'IX_ContractDecision_Task'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorContractDecision]'))
CREATE NONCLUSTERED INDEX [IX_ContractDecision_Task] ON [Preprocessor].[PreprocessorContractDecision] ([task_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'UQ_ContractDecision_Scope'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorContractDecision]'))
CREATE UNIQUE NONCLUSTERED INDEX [UQ_ContractDecision_Scope] ON [Preprocessor].[PreprocessorContractDecision] ([task_id], [organization_eid], [contract_id], [erp_vendor_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_discitem_set'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorDiscoveryItem]'))
CREATE NONCLUSTERED INDEX [ix_discitem_set] ON [Preprocessor].[PreprocessorDiscoveryItem] ([set_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_discitem_set_reduced'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorDiscoveryItem]'))
CREATE NONCLUSTERED INDEX [ix_discitem_set_reduced] ON [Preprocessor].[PreprocessorDiscoveryItem] ([set_id], [reduced_sku]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_discmatch_item'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorDiscoveryMatch]'))
CREATE NONCLUSTERED INDEX [ix_discmatch_item] ON [Preprocessor].[PreprocessorDiscoveryMatch] ([discovery_item_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_discmatch_set'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorDiscoveryMatch]'))
CREATE NONCLUSTERED INDEX [ix_discmatch_set] ON [Preprocessor].[PreprocessorDiscoveryMatch] ([set_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_discmatch_set_llm'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorDiscoveryMatch]'))
CREATE NONCLUSTERED INDEX [ix_discmatch_set_llm] ON [Preprocessor].[PreprocessorDiscoveryMatch] ([set_id], [llm_status]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_discmatch_set_noun'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorDiscoveryMatch]'))
CREATE NONCLUSTERED INDEX [ix_discmatch_set_noun] ON [Preprocessor].[PreprocessorDiscoveryMatch] ([set_id], [llm_same_noun]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_discmatch_set_rank'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorDiscoveryMatch]'))
CREATE NONCLUSTERED INDEX [ix_discmatch_set_rank] ON [Preprocessor].[PreprocessorDiscoveryMatch] ([set_id], [rank_in_item]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'UQ_DiscoveryPrompt_key_version'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorDiscoveryPrompt]'))
CREATE UNIQUE NONCLUSTERED INDEX [UQ_DiscoveryPrompt_key_version] ON [Preprocessor].[PreprocessorDiscoveryPrompt] ([prompt_key], [version_no]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'UX_DiscoveryPrompt_active'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorDiscoveryPrompt]'))
CREATE UNIQUE NONCLUSTERED INDEX [UX_DiscoveryPrompt_active] ON [Preprocessor].[PreprocessorDiscoveryPrompt] ([prompt_key])
    WHERE ([is_active]=(1));
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_discset_created_by'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorDiscoverySet]'))
CREATE NONCLUSTERED INDEX [ix_discset_created_by] ON [Preprocessor].[PreprocessorDiscoverySet] ([created_by]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'IX_IMCheckResult_Task'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorIMCheckResult]'))
CREATE NONCLUSTERED INDEX [IX_IMCheckResult_Task] ON [Preprocessor].[PreprocessorIMCheckResult] ([task_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'IX_IMCheckResult_TaskCheck'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorIMCheckResult]'))
CREATE NONCLUSTERED INDEX [IX_IMCheckResult_TaskCheck] ON [Preprocessor].[PreprocessorIMCheckResult] ([task_id], [check_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'IX_IntegrityIssue_Task'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorIntegrityIssue]'))
CREATE NONCLUSTERED INDEX [IX_IntegrityIssue_Task] ON [Preprocessor].[PreprocessorIntegrityIssue] ([task_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'IX_IntegrityIssue_TaskCheck'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorIntegrityIssue]'))
CREATE NONCLUSTERED INDEX [IX_IntegrityIssue_TaskCheck] ON [Preprocessor].[PreprocessorIntegrityIssue] ([task_id], [check_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_preprocessoritemmatching_item_id'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorItemMatching]'))
CREATE NONCLUSTERED INDEX [ix_preprocessoritemmatching_item_id] ON [Preprocessor].[PreprocessorItemMatching] ([item_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_preprocessoritemmatching_task_id'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorItemMatching]'))
CREATE NONCLUSTERED INDEX [ix_preprocessoritemmatching_task_id] ON [Preprocessor].[PreprocessorItemMatching] ([task_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_match_contract_scope'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorMatchResult]'))
CREATE NONCLUSTERED INDEX [ix_match_contract_scope] ON [Preprocessor].[PreprocessorMatchResult] ([task_id], [contract_number], [organization_eid_matched], [erp_vendor_id_matched]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_match_task'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorMatchResult]'))
CREATE NONCLUSTERED INDEX [ix_match_task] ON [Preprocessor].[PreprocessorMatchResult] ([task_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_match_task_input_item'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorMatchResult]'))
CREATE NONCLUSTERED INDEX [ix_match_task_input_item] ON [Preprocessor].[PreprocessorMatchResult] ([task_id], [input_item_id])
    INCLUDE ([matched_source], [match_type], [ccx_pkid], [match_status], [similarity_bucket]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_precheck_task'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorPreCheckError]'))
CREATE NONCLUSTERED INDEX [ix_precheck_task] ON [Preprocessor].[PreprocessorPreCheckError] ([task_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'IX_PreprocessIssue_Item'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorPreprocessIssue]'))
CREATE NONCLUSTERED INDEX [IX_PreprocessIssue_Item] ON [Preprocessor].[PreprocessorPreprocessIssue] ([item_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'IX_PreprocessIssue_Open'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorPreprocessIssue]'))
CREATE NONCLUSTERED INDEX [IX_PreprocessIssue_Open] ON [Preprocessor].[PreprocessorPreprocessIssue] ([task_id], [resolved]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'IX_PreprocessIssue_Task'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorPreprocessIssue]'))
CREATE NONCLUSTERED INDEX [IX_PreprocessIssue_Task] ON [Preprocessor].[PreprocessorPreprocessIssue] ([task_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_preprocessor_task_parent_task_id'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorTask]'))
CREATE NONCLUSTERED INDEX [ix_preprocessor_task_parent_task_id] ON [Preprocessor].[PreprocessorTask] ([parent_task_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_taskitem_task_id'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorTaskItem]'))
CREATE NONCLUSTERED INDEX [ix_taskitem_task_id] ON [Preprocessor].[PreprocessorTaskItem] ([task_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'IX_TaskItemForDecision_Task'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorTaskItemForDecision]'))
CREATE NONCLUSTERED INDEX [IX_TaskItemForDecision_Task] ON [Preprocessor].[PreprocessorTaskItemForDecision] ([task_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'IX_TaskItemForDecision_TaskInput'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorTaskItemForDecision]'))
CREATE NONCLUSTERED INDEX [IX_TaskItemForDecision_TaskInput] ON [Preprocessor].[PreprocessorTaskItemForDecision] ([task_id], [input_item_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'UX_TaskItemForDecision_Match'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorTaskItemForDecision]'))
CREATE UNIQUE NONCLUSTERED INDEX [UX_TaskItemForDecision_Match] ON [Preprocessor].[PreprocessorTaskItemForDecision] ([match_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_statuslog_task'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorTaskStatusLog]'))
CREATE NONCLUSTERED INDEX [ix_statuslog_task] ON [Preprocessor].[PreprocessorTaskStatusLog] ([task_id]);
GO

-- ------------------------------------------------------------
-- Added 2026-09-28 (migration 041), not part of the PRIME snapshot:
-- single-column indexes on the FK columns referencing TaskItem.item_id,
-- so FK checks on TaskItem deletes seek instead of scanning.
-- ------------------------------------------------------------

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_match_input_item'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorMatchResult]'))
CREATE NONCLUSTERED INDEX [ix_match_input_item] ON [Preprocessor].[PreprocessorMatchResult] ([input_item_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'IX_TaskItemForDecision_InputItem'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorTaskItemForDecision]'))
CREATE NONCLUSTERED INDEX [IX_TaskItemForDecision_InputItem] ON [Preprocessor].[PreprocessorTaskItemForDecision] ([input_item_id]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'ix_precheck_item'
               AND object_id=OBJECT_ID(N'[Preprocessor].[PreprocessorPreCheckError]'))
CREATE NONCLUSTERED INDEX [ix_precheck_item] ON [Preprocessor].[PreprocessorPreCheckError] ([item_id]);
GO
