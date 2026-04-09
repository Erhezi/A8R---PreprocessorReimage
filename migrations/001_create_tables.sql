-- ============================================================
-- Migration script: Create new tables for restructured app
-- Run against SQL Server: PRIME on MISCPrdAdhocDB
-- Schema: Preprocessor
-- ============================================================

-- Ensure schema exists
IF NOT EXISTS (SELECT * FROM sys.schemas WHERE name = 'Preprocessor')
    EXEC('CREATE SCHEMA [Preprocessor]');
GO

-- 0. Users
IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'Preprocessor' AND TABLE_NAME = 'users')
BEGIN
    CREATE TABLE [Preprocessor].[users] (
        user_id          INT IDENTITY(1,1) NOT NULL,
        email            VARCHAR(255) NOT NULL,
        name             VARCHAR(120) NULL,
        user_role        VARCHAR(50) NOT NULL DEFAULT 'sourcing',
        pw_hash          VARCHAR(255) NOT NULL,
        is_active        BIT NOT NULL DEFAULT 1,
        created_at       DATETIME NOT NULL DEFAULT GETDATE(),
        last_login_at    DATETIME NULL,
        reset_code       VARCHAR(10) NULL,
        reset_code_expiry DATETIME NULL,
        approved_by      VARCHAR(255) NULL,
        approved_at      DATETIME NULL,
        disabled_by      VARCHAR(255) NULL,
        disabled_at      DATETIME NULL,
        CONSTRAINT PK_users PRIMARY KEY CLUSTERED (user_id ASC),
        CONSTRAINT UQ_users_email UNIQUE (email),
        CONSTRAINT CK_users_role CHECK (user_role IN ('sourcing', 'mdm', 'preprocessor'))
    );
END;
GO

-- 1. PreprocessorTask
IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'Preprocessor' AND TABLE_NAME = 'PreprocessorTask')
BEGIN
    CREATE TABLE [Preprocessor].PreprocessorTask (
        task_id          NCHAR(4) PRIMARY KEY,
        contract_number  NVARCHAR(100) NULL,
        vendor_id        NVARCHAR(20) NULL,
        purchase_from_loc NVARCHAR(50) NULL,
        process_type     NVARCHAR(20) NOT NULL,     -- MANUFACTURER | DISTRIBUTOR
        source_type      NVARCHAR(20) NOT NULL,      -- PREMIER | LOCAL
        organization     NVARCHAR(50) NOT NULL,
        oem_name         NVARCHAR(255) NULL,
        intention        NVARCHAR(10) NOT NULL,       -- EXPIRE | NEW | UPDATE | MIX
        mixed_intention  BIT DEFAULT 0,
        contract_start_date DATE NULL,
        contract_end_date   DATE NULL,
        notes            NVARCHAR(MAX) NULL,
        phase            NVARCHAR(30) NOT NULL DEFAULT 'INTAKE',
        status           NVARCHAR(50) NOT NULL DEFAULT 'DRAFT',
        created_by       NVARCHAR(120) NOT NULL,
        created_at       DATETIME2 DEFAULT GETDATE(),
        updated_at       DATETIME2 DEFAULT GETDATE()
    );
END;
GO

-- 2. PreprocessorTaskItem
IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'Preprocessor' AND TABLE_NAME = 'PreprocessorTaskItem')
BEGIN
    CREATE TABLE [Preprocessor].PreprocessorTaskItem (
        item_id              INT IDENTITY(1,1) PRIMARY KEY,
        task_id              NCHAR(4) NOT NULL REFERENCES [Preprocessor].PreprocessorTask(task_id),
        vendor_catalog_num   NVARCHAR(255) NULL,
        mfg_catalog_num      NVARCHAR(255) NOT NULL,
        description          NVARCHAR(MAX) NOT NULL,
        standardized_description NVARCHAR(MAX) NULL,
        uom                  NVARCHAR(50) NOT NULL,
        unit_price           DECIMAL(18,4) NOT NULL,
        qoe                  INT NOT NULL,
        intention            NVARCHAR(10) NULL,
        status               NVARCHAR(50) NOT NULL DEFAULT 'UPLOADED',
        error_message        NVARCHAR(MAX) NULL,
        source_dataset       NVARCHAR(10) NOT NULL DEFAULT 'INPUT',
        infor_item_number    NVARCHAR(50) NULL,
        contract_line_infor_item_number NVARCHAR(50) NULL,
        infor_sync_flag      NVARCHAR(20) NULL,
        reduced_mfg_num      NVARCHAR(255) NULL,
        reduced_vendor_num   NVARCHAR(255) NULL,
        created_at           DATETIME2 DEFAULT GETDATE(),
        updated_at           DATETIME2 DEFAULT GETDATE()
    );

    CREATE INDEX ix_taskitem_task_id ON [Preprocessor].PreprocessorTaskItem(task_id);
END;
GO

-- 3. PreprocessorPreCheckError
IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'Preprocessor' AND TABLE_NAME = 'PreprocessorPreCheckError')
BEGIN
    CREATE TABLE [Preprocessor].PreprocessorPreCheckError (
        error_id     INT IDENTITY(1,1) PRIMARY KEY,
        task_id      NCHAR(4) NOT NULL REFERENCES [Preprocessor].PreprocessorTask(task_id),
        item_id      INT NOT NULL REFERENCES [Preprocessor].PreprocessorTaskItem(item_id),
        phase        NVARCHAR(10) NOT NULL,    -- PC1 | PC2
        error_type   NVARCHAR(50) NOT NULL,
        error_detail NVARCHAR(MAX) NULL,
        resolved     BIT DEFAULT 0,
        resolved_by  NVARCHAR(120) NULL,
        resolved_at  DATETIME2 NULL,
        created_at   DATETIME2 DEFAULT GETDATE()
    );

    CREATE INDEX ix_precheck_task ON [Preprocessor].PreprocessorPreCheckError(task_id);
END;
GO

-- 4. PreprocessorMatchResult
IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'Preprocessor' AND TABLE_NAME = 'PreprocessorMatchResult')
BEGIN
    CREATE TABLE [Preprocessor].PreprocessorMatchResult (
        match_id        INT IDENTITY(1,1) PRIMARY KEY,
        task_id         NCHAR(4) NOT NULL REFERENCES [Preprocessor].PreprocessorTask(task_id),
        input_item_id   INT NOT NULL REFERENCES [Preprocessor].PreprocessorTaskItem(item_id),
        matched_source  NVARCHAR(20) NOT NULL,   -- CCX | INFOR_CL | INFOR_IM
        matched_item_ref NVARCHAR(255) NULL,
        similarity_score FLOAT NULL,
        bucket          NVARCHAR(10) NULL,        -- HIGH | MED | LOW
        match_status    NVARCHAR(20) NOT NULL DEFAULT 'PENDING',
        reviewed_by     NVARCHAR(120) NULL,
        reviewed_at     DATETIME2 NULL,
        created_at      DATETIME2 DEFAULT GETDATE()
    );

    CREATE INDEX ix_match_task ON [Preprocessor].PreprocessorMatchResult(task_id);
END;
GO

-- 5. PreprocessorTaskStatusLog
IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'Preprocessor' AND TABLE_NAME = 'PreprocessorTaskStatusLog')
BEGIN
    CREATE TABLE [Preprocessor].PreprocessorTaskStatusLog (
        log_id       INT IDENTITY(1,1) PRIMARY KEY,
        task_id      NCHAR(4) NOT NULL REFERENCES [Preprocessor].PreprocessorTask(task_id),
        old_phase    NVARCHAR(30) NULL,
        new_phase    NVARCHAR(30) NULL,
        old_status   NVARCHAR(50) NULL,
        new_status   NVARCHAR(50) NULL,
        changed_by   NVARCHAR(120) NULL,
        changed_at   DATETIME2 DEFAULT GETDATE(),
        notes        NVARCHAR(MAX) NULL
    );

    CREATE INDEX ix_statuslog_task ON [Preprocessor].PreprocessorTaskStatusLog(task_id);
END;
GO

PRINT 'Migration complete.';
