# Preprocessor server move — generated scripts

Moving schema `Preprocessor` from **MISCPrdAdhocDB \ PRIME** to
**YNBBSTVWP02\PROCDATASRVPROD**, split across three databases.

Everything here was generated from live source metadata on 2026-09-14.
Nothing in this folder reads or writes PRIME beyond `SELECT` — no source
object is dropped or altered by the move.

## Where things land

| Destination | Recovery | Tables | Holds |
|---|---|---|---|
| `Preprocessor.Preprocessor` | FULL | 25 | App state, small derived tables, reference data, `process_log` |
| `PLMPreprocessorShared.Preprocessor` | SIMPLE | 8 | Everything the nightly batch rebuilds (2.3 GB of churn) |
| `Preprocessor.ghx` | FULL | 1 | `CCXSyncContract` — already loaded by E0-ETL des2 |
| `Preprocessor.infor` | FULL | 5 | Migrated ahead of this work |

The split follows recovery model: `Preprocessor` is backed up in FULL, so the
tables that are truncated and reloaded every night live in the SIMPLE database
instead. No foreign key crosses the boundary — all 22 stay inside
`Preprocessor.Preprocessor`.

## Run order

| Script | Run against | Notes |
|---|---|---|
| `00_create_schemas.sql` | both | Creates `[Preprocessor]` in PLMPreprocessorShared |
| `10_tables_preprocessor.sql` | Preprocessor | 25 tables |
| `11_tables_shared_bulk.sql` | PLMPreprocessorShared | 8 tables |
| `procs/*.sql` | Preprocessor | 14 procedures, `CREATE OR ALTER` |
| *(bulk load)* | — | App state from PRIME, identity preserved |
| `20_indexes_preprocessor.sql` | Preprocessor | 32 indexes — after the load |
| `21_indexes_shared_bulk.sql` | PLMPreprocessorShared | 4 indexes — after the first batch |
| `30_foreign_keys.sql` | Preprocessor | 22 FKs — after the load |

Every script is idempotent: tables, indexes and FKs are guarded by existence
checks, and the procedures are `CREATE OR ALTER`.

## Reference rewrites applied to the procedures

57 substitutions across 14 procedures. All are name-only — a column-by-column
drift check against the new upstream tables found no differences, so no column
list or cast changed.

| | From | To | Count |
|---|---|---|---|
| A | `[DM_MONTYNT\dli2].*` | `PLMPreprocessorShared.infor.*` | 13 |
| B | `dbo.ZZZ_STAGING_..._DAILY` | `Contracts.dbo.<same>` | 2 |
| C | `Preprocessor.<bulk 8>` | `PLMPreprocessorShared.Preprocessor.*` | 35 |
| D | `Preprocessor.CCXSyncContract` | `ghx.CCXSyncContract` | 5 |
| E | `Preprocessor.Infor*` | `infor.*` | 2 |

Three upstream tables are renamed by rule A, which is easy to miss:
`INVENTORY_LOCATION` → `ITEM_LOCATION`, and both `MDM_*_INFOR` tables drop the
`_INFOR` suffix now that the `infor` schema carries it.

## Two things deliberately left alone

**`usp_RunPreprocessor_Batch` has no table references and needed no rewrite.**
It carries the literal `process_name` strings written to `process_log`, such as
`N'[Preprocessor].sp_RefreshCCXSyncedContractLine'`. The app's
`ccx_reload_watermark` query matches one of those literals exactly — it is the
guard that stops a task matching against stale `CCX_pkid` values. Re-qualifying
those strings for the new database would make the query return `NULL` with no
error anywhere.

**`procs/sp_RefreshInforSyncedContractLine.sql` is not deployed.** It writes to
`[Preprocessor].[InforSyncedContractLine]`, which does not exist anywhere in
PRIME. It has never run — `process_log` holds zero rows for it — and
`usp_RunPreprocessor_Batch` does not call it. The file is kept as a record. Note
that SQL Server's deferred name resolution means it *would* deploy cleanly and
only fail when executed.

## Not covered here

- The `des2` block in `E0-ETL/configs/post_processes/preprocessor.yaml`, which
  is what actually runs the nightly batch. All four gate loaders already report
  on des2.
- The `des2` block only. Application code was migrated on 2026-09-14: 35
  reference rewrites across 13 files (11 `[DM_MONTYNT\dli2]`, 24 bulk-table),
  plus three edits no find-and-replace reaches —

  | File | Why it needed hand editing |
  |---|---|
  | `config.py` | Two near-identical `DB_CONN_STRING` properties; consolidated onto the env-driven one so the connection is defined once |
  | `models.py` | `InforVendorLocation` rode on the `SCHEMA` constant; now `VendorLocation` under `INFOR_SCHEMA` |
  | `preprocess/routes.py` | `inspect().get_columns()` takes table and schema as separate arguments — set `schema="PLMPreprocessorShared.Preprocessor"`, which the MSSQL dialect reads as `database.schema` |

  Verified by compiling all 43 named queries against the new server (`SET
  NOEXEC ON` for the 8 using expanding `IN` lists): zero missing objects.
