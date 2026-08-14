-- ============================================================
-- Migration 032: Quick Discovery
-- Run against SQL Server: PRIME on MISCPrdAdhocDB
-- Schema: Preprocessor
--
-- Quick Discovery is a lightweight, task-free lookup: upload SKU +
-- Description (+ optional Supplier), match against CCX contract lines using
-- the same reduced-part-number logic as the preprocessor, rank locally, then
-- ask an LLM which pairs are genuinely the same item.
--
-- Four tables:
--   PreprocessorDiscoverySet     one row per upload
--   PreprocessorDiscoveryItem    one row per uploaded line
--   PreprocessorDiscoveryMatch   one row per (input line, CCX line)
--   PreprocessorDiscoveryPrompt  immutable versioned LLM prompts
-- ============================================================

-- 1. Prompts (created first — DiscoverySet and DiscoveryMatch reference it)
IF OBJECT_ID('[Preprocessor].[PreprocessorDiscoveryPrompt]', 'U') IS NULL
BEGIN
    CREATE TABLE [Preprocessor].[PreprocessorDiscoveryPrompt] (
        [prompt_version_id] INT IDENTITY(1,1) NOT NULL,
        [prompt_key]        NVARCHAR(50)  NOT NULL CONSTRAINT [DF_DiscoveryPrompt_key] DEFAULT 'ITEM_COMPARE',
        [version_no]        INT           NOT NULL,
        [system_prompt]     NVARCHAR(MAX) NOT NULL,
        [user_template]     NVARCHAR(MAX) NOT NULL,
        -- NULL falls back to the app's configured OPENAI_MODEL / LLM_TEMPERATURE.
        [model]             NVARCHAR(100) NULL,
        [temperature]       FLOAT         NULL,
        [is_active]         BIT           NOT NULL CONSTRAINT [DF_DiscoveryPrompt_is_active] DEFAULT 0,
        [notes]             NVARCHAR(500) NULL,
        [created_by]        NVARCHAR(120) NOT NULL,
        [created_at]        DATETIME2     NOT NULL CONSTRAINT [DF_DiscoveryPrompt_created_at] DEFAULT GETDATE(),
        CONSTRAINT [PK_PreprocessorDiscoveryPrompt] PRIMARY KEY CLUSTERED ([prompt_version_id] ASC),
        CONSTRAINT [UQ_DiscoveryPrompt_key_version] UNIQUE ([prompt_key], [version_no])
    );

    -- At most one active version per prompt_key, enforced by the database
    -- rather than by application discipline.
    CREATE UNIQUE INDEX [UX_DiscoveryPrompt_active]
        ON [Preprocessor].[PreprocessorDiscoveryPrompt] ([prompt_key])
        WHERE [is_active] = 1;
END;
GO

-- 2. Set — one row per uploaded file
IF OBJECT_ID('[Preprocessor].[PreprocessorDiscoverySet]', 'U') IS NULL
BEGIN
    CREATE TABLE [Preprocessor].[PreprocessorDiscoverySet] (
        [set_id]                   INT IDENTITY(1,1) NOT NULL,
        [set_name]                 NVARCHAR(200) NULL,
        [source_filename]          NVARCHAR(255) NULL,
        -- MFG | VENDOR | EITHER — how the uploaded SKU should be interpreted.
        [match_mode]               NVARCHAR(10)  NOT NULL CONSTRAINT [DF_DiscoverySet_mode] DEFAULT 'EITHER',
        -- MHS sees every organization; kept as a column so a narrower scope can
        -- be offered later without a migration.
        [org_eid]                  NVARCHAR(10)  NOT NULL CONSTRAINT [DF_DiscoverySet_org] DEFAULT '105188574',
        [row_count]                INT           NOT NULL CONSTRAINT [DF_DiscoverySet_rows] DEFAULT 0,
        [match_count]              INT           NOT NULL CONSTRAINT [DF_DiscoverySet_matches] DEFAULT 0,
        [has_supplier]             BIT           NOT NULL CONSTRAINT [DF_DiscoverySet_supplier] DEFAULT 0,
        -- UPLOADED | MATCHING | MATCHED | LLM_RUNNING | LLM_COMPLETE
        [status]                   NVARCHAR(30)  NOT NULL CONSTRAINT [DF_DiscoverySet_status] DEFAULT 'UPLOADED',
        [active_prompt_version_id] INT           NULL,
        [created_by]               NVARCHAR(120) NOT NULL,
        [created_at]               DATETIME2     NOT NULL CONSTRAINT [DF_DiscoverySet_created_at] DEFAULT GETDATE(),
        [updated_at]               DATETIME2     NOT NULL CONSTRAINT [DF_DiscoverySet_updated_at] DEFAULT GETDATE(),
        CONSTRAINT [PK_PreprocessorDiscoverySet] PRIMARY KEY CLUSTERED ([set_id] ASC),
        CONSTRAINT [CK_DiscoverySet_mode] CHECK ([match_mode] IN ('MFG', 'VENDOR', 'EITHER')),
        CONSTRAINT [FK_DiscoverySet_prompt] FOREIGN KEY ([active_prompt_version_id])
            REFERENCES [Preprocessor].[PreprocessorDiscoveryPrompt]([prompt_version_id])
    );

    CREATE INDEX [ix_discset_created_by] ON [Preprocessor].[PreprocessorDiscoverySet]([created_by]);
END;
GO

-- 3. Item — one row per uploaded line
IF OBJECT_ID('[Preprocessor].[PreprocessorDiscoveryItem]', 'U') IS NULL
BEGIN
    CREATE TABLE [Preprocessor].[PreprocessorDiscoveryItem] (
        [discovery_item_id] INT IDENTITY(1,1) NOT NULL,
        [set_id]            INT           NOT NULL,
        [file_row]          INT           NULL,
        -- sku_raw is exactly what the user uploaded; sku_input is clean_text()'d;
        -- reduced_sku is reduce_catalog_number() and is the only one matched on.
        [sku_raw]           NVARCHAR(255) NULL,
        [sku_input]         NVARCHAR(255) NOT NULL,
        [reduced_sku]       NVARCHAR(255) NULL,
        [description_input] NVARCHAR(MAX) NOT NULL,
        [supplier_input]    NVARCHAR(255) NULL,
        [match_count]       INT           NOT NULL CONSTRAINT [DF_DiscoveryItem_matches] DEFAULT 0,
        [created_at]        DATETIME2     NOT NULL CONSTRAINT [DF_DiscoveryItem_created_at] DEFAULT GETDATE(),
        CONSTRAINT [PK_PreprocessorDiscoveryItem] PRIMARY KEY CLUSTERED ([discovery_item_id] ASC),
        CONSTRAINT [FK_DiscoveryItem_set] FOREIGN KEY ([set_id])
            REFERENCES [Preprocessor].[PreprocessorDiscoverySet]([set_id])
    );

    CREATE INDEX [ix_discitem_set] ON [Preprocessor].[PreprocessorDiscoveryItem]([set_id]);
    CREATE INDEX [ix_discitem_set_reduced] ON [Preprocessor].[PreprocessorDiscoveryItem]([set_id], [reduced_sku]);
END;
GO

-- 4. Match — one row per (input line, CCX contract line)
IF OBJECT_ID('[Preprocessor].[PreprocessorDiscoveryMatch]', 'U') IS NULL
BEGIN
    CREATE TABLE [Preprocessor].[PreprocessorDiscoveryMatch] (
        [discovery_match_id] INT IDENTITY(1,1) NOT NULL,
        [set_id]             INT NOT NULL,
        [discovery_item_id]  INT NOT NULL,

        -- CCX_pkid is a surrogate the daily reload re-issues. Stored for
        -- debugging only; never join on it across requests. The six business-key
        -- columns below are the stable identity.
        [ccx_pkid]           INT NULL,

        -- REDUCED_MFG | REDUCED_VPN — which reduced column produced the hit.
        [matched_on]         NVARCHAR(20) NOT NULL,
        -- Cleansed input SKU equals the raw matched number on the matching side.
        [sku_exact]          BIT   NOT NULL CONSTRAINT [DF_DiscoveryMatch_exact] DEFAULT 0,
        [desc_similarity]    FLOAT NULL,
        [rank_in_item]       INT   NULL,

        -- CCX business key (UX_CCXSyncedCL_ItemPerRN) + display snapshot
        [organization_eid_matched]      NVARCHAR(10)  NULL,
        [organization_matched]          NVARCHAR(100) NULL,
        [contract_id_matched]           NVARCHAR(100) NULL,
        [erp_vendor_id_matched]         NVARCHAR(20)  NULL,
        [mfg_catalog_num_matched]       NVARCHAR(255) NULL,
        [uom_matched]                   NVARCHAR(10)  NULL,
        [uom_to_match_infor_matched]    NVARCHAR(10)  NULL,
        [vendor_catalog_num_matched]    NVARCHAR(255) NULL,
        [description_matched]           NVARCHAR(500) NULL,
        [qoe_matched]                   INT           NULL,
        [unit_price_matched]            DECIMAL(18,4) NULL,
        [contract_description]          NVARCHAR(500) NULL,
        [vendor_name_matched]           NVARCHAR(255) NULL,
        [mfg_name_matched]              NVARCHAR(255) NULL,
        [contract_manufacturer_matched] NVARCHAR(10)  NULL,

        -- LLM judgement. llm_status drives the chunked runner: rows are claimed
        -- PENDING -> IN_PROGRESS atomically so concurrent tabs can't double-bill.
        [llm_status]            NVARCHAR(15)  NOT NULL CONSTRAINT [DF_DiscoveryMatch_llm_status] DEFAULT 'NONE',
        [llm_verdict]           NVARCHAR(10)  NULL,
        [llm_confidence]        INT           NULL,
        [llm_reason]            NVARCHAR(1000) NULL,
        [llm_prompt_version_id] INT           NULL,
        [llm_reviewed_at]       DATETIME2     NULL,
        [llm_error]             NVARCHAR(500) NULL,

        [created_at] DATETIME2 NOT NULL CONSTRAINT [DF_DiscoveryMatch_created_at] DEFAULT GETDATE(),

        CONSTRAINT [PK_PreprocessorDiscoveryMatch] PRIMARY KEY CLUSTERED ([discovery_match_id] ASC),
        CONSTRAINT [CK_DiscoveryMatch_on] CHECK ([matched_on] IN ('REDUCED_MFG', 'REDUCED_VPN')),
        CONSTRAINT [CK_DiscoveryMatch_llm_status] CHECK ([llm_status] IN ('NONE', 'PENDING', 'IN_PROGRESS', 'DONE', 'ERROR')),
        CONSTRAINT [CK_DiscoveryMatch_verdict] CHECK ([llm_verdict] IS NULL OR [llm_verdict] IN ('SAME', 'DIFFERENT', 'UNCERTAIN')),
        CONSTRAINT [FK_DiscoveryMatch_set] FOREIGN KEY ([set_id])
            REFERENCES [Preprocessor].[PreprocessorDiscoverySet]([set_id]),
        CONSTRAINT [FK_DiscoveryMatch_item] FOREIGN KEY ([discovery_item_id])
            REFERENCES [Preprocessor].[PreprocessorDiscoveryItem]([discovery_item_id]),
        CONSTRAINT [FK_DiscoveryMatch_prompt] FOREIGN KEY ([llm_prompt_version_id])
            REFERENCES [Preprocessor].[PreprocessorDiscoveryPrompt]([prompt_version_id])
    );

    CREATE INDEX [ix_discmatch_set] ON [Preprocessor].[PreprocessorDiscoveryMatch]([set_id]);
    CREATE INDEX [ix_discmatch_item] ON [Preprocessor].[PreprocessorDiscoveryMatch]([discovery_item_id]);
    -- Drives slice claiming and the progress denominator.
    CREATE INDEX [ix_discmatch_set_llm] ON [Preprocessor].[PreprocessorDiscoveryMatch]([set_id], [llm_status]);
    -- Drives the default results ordering (best match per input line first).
    CREATE INDEX [ix_discmatch_set_rank] ON [Preprocessor].[PreprocessorDiscoveryMatch]([set_id], [rank_in_item]);
END;
GO

-- 5. Seed prompt version 1
IF NOT EXISTS (
    SELECT 1 FROM [Preprocessor].[PreprocessorDiscoveryPrompt]
    WHERE [prompt_key] = 'ITEM_COMPARE'
)
BEGIN
    INSERT INTO [Preprocessor].[PreprocessorDiscoveryPrompt]
        ([prompt_key], [version_no], [is_active], [created_by], [notes], [system_prompt], [user_template])
    VALUES (
        'ITEM_COMPARE',
        1,
        1,
        'system',
        'Seeded with migration 032.',
N'You are an expert hospital supply-chain analyst. You are given two item
records and must decide whether they describe the SAME physical product.

You will receive, for each side, a catalog/SKU number and an item description.
Supplier names may also be present: the input side may carry a supplier, and
the matched side carries the contract vendor name and the manufacturer name.

Unlike a contract-loading review, you are NOT judging packaging, unit of
measure, price, or quantity-of-each. Those fields are not supplied. Judge
product identity only: is this the same physical product?

Decide between three verdicts:
- SAME: the two records identify the same physical product. Minor wording,
  abbreviation, or word-order differences are expected and are not a reason to
  reject. Differing pack sizes are NOT a reason to reject on their own, because
  packaging is out of scope here.
- DIFFERENT: the records identify different products. Use this when the
  descriptions disagree on something product-defining -- product type, size or
  gauge, material or formulation, sterile vs non-sterile, latex vs latex-free,
  or intended clinical use -- or when the suppliers indicate competing branded
  equivalents with no shared manufacturer identity.
- UNCERTAIN: the evidence is genuinely balanced, or a description is too sparse
  or generic to tell. Prefer a decisive verdict when the evidence leans; reserve
  UNCERTAIN for real deadlocks.

How to weigh the evidence:
1. Descriptions carry the most weight. Compare product type, size/dimension,
   gauge, material, formulation, sterility, and intended use.
2. An exact SKU match (flagged for you) is strong corroboration when the
   descriptions also agree. It is NOT sufficient on its own -- short or generic
   numbers such as 10, 100, 0001, ABC, or N/A collide by coincidence.
3. When the SKU matched only after normalization (punctuation, case, and
   leading zeros removed), treat it as moderate evidence, not proof.
4. Suppliers: treat vendor names as compatible when they are the same company,
   a parent/subsidiary, merged or acquired entities, or a manufacturer and a
   distributor of the same product. Use corporate relationships only when they
   are widely known and you are confident -- never invent one. An unknown
   relationship is neutral, not negative. Two well-known manufacturers that
   directly compete in the category, with no shared manufacturer part number,
   point to DIFFERENT.
5. A vendor catalog number legitimately differs between distributors selling
   the same product. Do not treat that as evidence of a different product.

Keep the reason to one sentence naming the decisive evidence.

Respond with a JSON object and nothing else:
{"verdict": "SAME" | "DIFFERENT" | "UNCERTAIN", "confidence": 0-100, "reason": "<one sentence>"}',
N'INPUT item:
  SKU: {{ input_sku }}
  Description: {{ input_description }}
{% if input_supplier %}
  Supplier: {{ input_supplier }}
{% endif %}

MATCHED contract line:
  SKU: {{ matched_sku }}
  Description: {{ matched_description }}
{% if matched_vendor_name %}
  Contract vendor: {{ matched_vendor_name }}
{% endif %}
{% if matched_manufacturer_name %}
  Manufacturer: {{ matched_manufacturer_name }}
{% endif %}

Matching context:
  Matched on: {{ matched_on }}
  SKU exactly equal: {{ sku_exact }}

Are these the same physical product?'
    );
END;
GO

PRINT 'Migration 032 complete.';
