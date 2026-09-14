-- common.sql: Shared queries used across modules
-- All queries use :param named parameter style for SQLAlchemy text()

-- name: get_vendor_names_by_erp_ids
-- Batch lookup of VendorName by ERPVendorID. Used for LLM review prompts so
-- the model sees vendor *names* on both sides of a match pair instead of bare
-- IDs. Returns one row per distinct ERPVendorID found in PurchaseVendorLocation.
SELECT ERPVendorID, MAX(VendorName) AS VendorName
FROM [Preprocessor].[PurchaseVendorLocation]
WHERE ERPVendorID IN :erp_vendor_ids
GROUP BY ERPVendorID;

-- name: ccx_reload_watermark
-- When the CCX line table was last rebuilt, plus how many rebuilds happened
-- after the caller-supplied cutoff.
--
-- sp_RefreshCCXSyncedContractLine does a TRUNCATE + INSERT, so every run
-- re-issues CCX_pkid for every row. A task whose SKU matching predates the last
-- run is holding pkids that no longer identify anything.
--
-- Watch this proc specifically, NOT sp_MakeInforActiveCLRefCCXSyncedCL. The
-- latter runs about a minute later in the same nightly chain, so a task that
-- matched inside that window would look fresh while its pkids were already dead.
--
-- Note for editors: never write a bind-parameter name into these comment lines.
-- sql_loader keeps all but the first comment line, and SQLAlchemy text() scans
-- the whole string, so a colon-prefixed word in a comment becomes a real bind.
SELECT
    MAX(exec_end) AS last_reload,
    SUM(CASE WHEN :since IS NULL OR exec_end > :since THEN 1 ELSE 0 END) AS reloads_since
FROM [Preprocessor].[process_log]
WHERE process_name = '[Preprocessor].sp_RefreshCCXSyncedContractLine'
  AND status = 'Success';
