# create task
fixed: 2026-04-20
- the vendor search is not working
- bring in vendor name on the side of the vendor ID (show as Vendor ID - Vendor Name (Vendor Location Name if exists))
- I have put all valid ERPVendorID under table [Preprocessor].PurchaseVendorLocation and made changes to the query under intake.sql, the table contains both the 0000000 version and the 0000000-B000 version, so the intake validation can just check against this table instead of having to split the logic to look at [DM_MONTYNT\dli2].MDM_SUPPLIER_NAME_INFOR. 
- if contract # matches, make sure the contract # show as exactly the matched contract # (not the one user type in, as they can mess up upper or lower case, extra spaces, etc.)
- ingested item SKU (vendor catalog number and manufacturer catalog number) should not get reduced. I see my leading zeros are getting stripped off, the reduced version should be stored in reduced columns for matching purpose, the original version should just be cleansed (remove spaces, upper cased)
- 'Contract Tier Description' in input file can be directly map to 'Tier Description' field when intake the upload.


# pre-check
fixed: 2026-04-20
- add precheck_mode 
- display precheck_mode on the UI under the the task header card (default to "Default")
- pre-checkfor duplications runs differently based on the precheck mode:
  - Default: on reduced manufacturer
  - Strict: on manufacturer part number
  - Explicit: on manufacturer part number + UOM

need check:
  - Distributor: on vendor part number (only offer this to distributor contract), trigger WARN if the reduced vendor part number is the same.
- the precheck on default will always be the first pass choice, only allow user to pick other mode when they offer to re-run precheck after seeing the result of default mode. once the new pre-check mode is selected and run, register that as the pre-check mode for the task and this could be used as a parameter in some subsequent steps.