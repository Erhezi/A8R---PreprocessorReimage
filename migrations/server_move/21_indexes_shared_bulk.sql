-- ============================================================
-- Non-clustered indexes
-- Generated from MISCPrdAdhocDB\PRIME [Preprocessor] on 2026-09-14.
-- Target database: PLMPreprocessorShared
-- Idempotent: every object is guarded by an existence check.
-- ============================================================

-- Run AFTER the bulk load: building these on populated tables is faster.


IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'IX_OrganizationContractIDVendor'
               AND object_id=OBJECT_ID(N'[Preprocessor].[CCXContractLineDeduped]'))
CREATE NONCLUSTERED INDEX [IX_OrganizationContractIDVendor] ON [Preprocessor].[CCXContractLineDeduped] ([ORGANIZATION_NAME], [CONTRACT_NUMBER], [VENDOR_NAME])
    INCLUDE ([ORGANIZATION_EID]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'UX_Item_per_OrgContractVendor'
               AND object_id=OBJECT_ID(N'[Preprocessor].[CCXContractLineDeduped]'))
CREATE UNIQUE NONCLUSTERED INDEX [UX_Item_per_OrgContractVendor] ON [Preprocessor].[CCXContractLineDeduped] ([ORGANIZATION_NAME], [VENDOR_NAME], [CONTRACT_NUMBER], [TierLevel], [ManufacturerNumber_CCX], [UOM_CCX]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'IX_CCX_InforMatch'
               AND object_id=OBJECT_ID(N'[Preprocessor].[CCXSyncedContractLine]'))
CREATE NONCLUSTERED INDEX [IX_CCX_InforMatch] ON [Preprocessor].[CCXSyncedContractLine] ([OrganizationEID], [ContractID], [ManufacturerNumber_CCX], [UOMtoMatchInfor_CCX])
    INCLUDE ([ERPVendorID]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'UX_CCXSyncedCL_ItemPerRN'
               AND object_id=OBJECT_ID(N'[Preprocessor].[CCXSyncedContractLine]'))
CREATE UNIQUE NONCLUSTERED INDEX [UX_CCXSyncedCL_ItemPerRN] ON [Preprocessor].[CCXSyncedContractLine] ([OrganizationEID], [ContractID], [ERPVendorID], [ManufacturerNumber_CCX], [UOM_CCX], [UOMtoMatchInfor_CCX]);
GO
