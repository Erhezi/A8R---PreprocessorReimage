-- ============================================================
-- Migration 022: Phase 4 dedup workspace.
--
-- 1. Create [Preprocessor].[PreprocessorTaskItemForDecision] —
--    a per-(input_item, accepted_match) workspace populated on
--    PREPROCESS -> DEDUP advance. Carries decisions, edits,
--    resolution-strategy classification and default actions.
-- 2. Add [llm_warning] column to PreprocessorMatchResult as a
--    placeholder for forthcoming LLM-side warning payloads.
-- ============================================================

IF NOT EXISTS (
    SELECT 1 FROM sys.tables
    WHERE name = 'PreprocessorTaskItemForDecision'
      AND SCHEMA_NAME(schema_id) = 'Preprocessor'
)
BEGIN
    CREATE TABLE [Preprocessor].[PreprocessorTaskItemForDecision] (
        [dedup_id]                       INT IDENTITY(1,1) PRIMARY KEY,

        -- Lineage to source rows
        [match_id]                       INT          NOT NULL,
        [task_id]                        NCHAR(4)   NOT NULL,
        [input_item_id]                  INT          NOT NULL,

        -- Carried from PreprocessorMatchResult
        [matched_source]                 VARCHAR(20)  NOT NULL,    -- CCX | INFOR_CL
        [match_status]                   VARCHAR(20)  NOT NULL,
        [similarity_bucket]              VARCHAR(10)  NULL,
        [similarity_score]               FLOAT        NULL,
        [contract_id_matched]            VARCHAR(100) NULL,
        [erp_vendor_id_matched]          VARCHAR(20)  NULL,
        [organization_eid_matched]       VARCHAR(10)  NULL,
        [organization_matched]           VARCHAR(100) NULL,
        [manufacturer_number_matched]    VARCHAR(255) NULL,
        [vendor_item_matched]            VARCHAR(255) NULL,
        [uom_matched]                    VARCHAR(10)  NULL,
        [uom_to_match_infor_matched]     VARCHAR(10)  NULL,
        [qoe_matched]                    INT          NULL,
        [contract_price_matched]         NUMERIC(18,4) NULL,
        [ea_price_matched]               FLOAT        NULL,        -- renamed from match_ea_price
        [item_desc_matched]              VARCHAR(500) NULL,
        [infor_pkids_matched]            VARCHAR(255) NULL,
        [infor_pkid]                     VARCHAR(31)  NULL,
        [infor_item_matched]             VARCHAR(20)  NULL,        -- resolved via InforActiveCLRefCCXSyncedCL.Item
        [match_type]                     VARCHAR(20)  NULL,
        [pair_type]                      VARCHAR(1)   NULL,
        [llm_reason]                     NVARCHAR(MAX) NULL,
        [llm_warning]                    NVARCHAR(MAX) NULL,

        -- Carried from PreprocessorTask + PreprocessorTaskItem (input side)
        [task_intention]                 VARCHAR(10)  NULL,
        [contract_id_input]              VARCHAR(100) NULL,
        [erp_vendor_id_input]            VARCHAR(20)  NULL,
        [organization_eid_input]         VARCHAR(10)  NULL,
        [organization_input]             VARCHAR(100) NULL,
        [manufacturer_number_input]      VARCHAR(255) NULL,
        [vendor_item_input]              VARCHAR(255) NULL,
        [uom_input]                      VARCHAR(50)  NULL,
        [uom_to_match_infor_input]       VARCHAR(10)  NULL,
        [qoe_input]                      INT          NULL,
        [contract_price_input]           NUMERIC(18,4) NULL,
        [ea_price_input]                 FLOAT        NULL,
        [item_description_input]         NVARCHAR(MAX) NULL,
        [infor_item_number]              VARCHAR(20)  NOT NULL DEFAULT '',  -- '' if input row has no item master link

        -- Carried from CCXInforSyncedContractHeader (both sides)
        [matched_contract_source_type]   VARCHAR(20)  NULL,
        [matched_contract_process_type]  VARCHAR(20)  NULL,
        [input_contract_source_type]     VARCHAR(20)  NULL,
        [input_contract_process_type]    VARCHAR(20)  NULL,

        -- Decision/audit
        [dedup_decision]                 VARCHAR(20)  NULL,        -- input_keep|input_drop|matched_keep|matched_drop or composite (decided in 4C UI)
        [dedup_decided_by]               VARCHAR(120) NULL,
        [created_at]                     DATETIME     NOT NULL DEFAULT GETDATE(),
        [dedup_decided_at]               DATETIME     NULL,

        -- Editing
        [editable]                       BIT          NOT NULL DEFAULT 1,
        [edits]                          NVARCHAR(MAX) NULL,        -- JSON: list of {side, field, original, current}

        -- Resolution strategy
        [resolution_grouping]            VARCHAR(10)  NULL,         -- SS | DV | ODO | TCCD | CECCD
        [default_action_input]           VARCHAR(10)  NULL,         -- keep | drop | any
        [default_action_matched]         VARCHAR(10)  NULL,
        [dedup_sort]                     INT          NULL,

        CONSTRAINT FK_TaskItemForDecision_Task
            FOREIGN KEY ([task_id])
            REFERENCES [Preprocessor].[PreprocessorTask]([task_id]),
        CONSTRAINT FK_TaskItemForDecision_TaskItem
            FOREIGN KEY ([input_item_id])
            REFERENCES [Preprocessor].[PreprocessorTaskItem]([item_id]),
        CONSTRAINT FK_TaskItemForDecision_MatchResult
            FOREIGN KEY ([match_id])
            REFERENCES [Preprocessor].[PreprocessorMatchResult]([match_id])
    );

    CREATE UNIQUE INDEX UX_TaskItemForDecision_Match
        ON [Preprocessor].[PreprocessorTaskItemForDecision]([match_id]);
    CREATE INDEX IX_TaskItemForDecision_Task
        ON [Preprocessor].[PreprocessorTaskItemForDecision]([task_id]);
    CREATE INDEX IX_TaskItemForDecision_TaskInput
        ON [Preprocessor].[PreprocessorTaskItemForDecision]([task_id], [input_item_id]);
END;

-- llm_warning placeholder on PreprocessorMatchResult so populator and any
-- future LLM pass can write warnings before the dedicated workspace row is
-- materialized.
IF COL_LENGTH('Preprocessor.PreprocessorMatchResult', 'llm_warning') IS NULL
BEGIN
    ALTER TABLE [Preprocessor].[PreprocessorMatchResult]
        ADD [llm_warning] NVARCHAR(MAX) NULL;
END;
