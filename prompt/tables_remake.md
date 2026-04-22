# will show the create table statement so we know the columns and types for our uses.

### Newly Make [Preprocessor] schema series:

all the table listed below are for 'read-only' and is updated and maintained in daily batch job, the program should not try to alter the data in these tables.
# 1. tables useful in preprocess module
`[Preprocessor].[CCXInforSyncedContractHeader]` -- the header level contract information for the set of contracts that are 'supposed' to be synced between CCX and Infor. It doesn't contain any line level informations. ~1200 records. In this reimage design, we will recognize per contract as per OrganizationEID (or Organization) + ContractID + ERPVendorID (or Vendor from CCX line side since it doens't necessarily always have the ERPVendorID labeled) combination. 

CREATE TABLE [Preprocessor].[CCXInforSyncedContractHeader](
	[RN] [int] NOT NULL,
	[RN_check] [int] NULL,
	[Organization] [varchar](100) NOT NULL,
	[OrganizationEID] [varchar](10) NULL,
	[Manufacturer] [varchar](255) NOT NULL,
	[Vendor] [varchar](255) NOT NULL,
	[ContractProcessType] [varchar](12) NOT NULL,
	[ContractID] [varchar](100) NOT NULL,
	[ERPVendorID] [varchar](20) NULL,
	[ContractSourceType] [varchar](20) NOT NULL,
	[DC_contractRefID] [int] NULL,
	[InforCompanyEID] [varchar](10) NULL,
	[rs_CCXH] [datetime] NULL,
	[ManufacturerEID] [varchar](50) NULL,
	[ContractStartDate] [date] NULL,
	[ContractEndDate] [date] NULL,
	[DC_TierLevel] [int] NULL,
	[rs_CCXL] [date] NULL,
	[OrganizationEID_Infor] [varchar](10) NULL,
	[ContractID_Infor] [varchar](100) NULL,
	[ERPVendorID_Infor] [varchar](20) NULL,
	[ContractManufacturer_Infor] [varchar](10) NULL,
	[ManufacturerName_Infor] [varchar](255) NULL,
	[ManufacturerEID_Infor] [varchar](20) NULL,
	[ContractStartDate_Infor] [date] NULL,
	[ContractEndDate_Infor] [date] NULL,
	[Contract_Infor] [varchar](10) NULL,
	[rs_Infor] [datetime] NULL,
 CONSTRAINT [PK_InforSyncedContractHeader] PRIMARY KEY CLUSTERED 
(
	[RN] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON) ON [PRIMARY],
 CONSTRAINT [UX_OrganizationContractIDVendorERPID] UNIQUE NONCLUSTERED 
(
	[Organization] ASC,
	[ContractID] ASC,
	[ERPVendorID] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON) ON [PRIMARY]
) ON [PRIMARY]

`[Preprocessor].[CCXSyncedContractLine]` -- CCX Contract line, contains all available CCX line items, because when CCX interface contract to Infor, it automatically change UOM to Infor convention (e.g. CS to CA, PG to PK), so the column UOMtoMatchInfor_CCX is created to capture the UOM after the conversion, so we can use that column to match with Infor side UOM. ~615k records. For dup matching, we generally will start from here since the process currently is from INPUT -> PREPROCESS -> CCX -> Infor.
There are will be new rules in this reimage design since previously we don't distinguish the contract 'Organization' (which hospital or entity is holding a given contract) and we generally ignore the factor that there are chances that the same contract ID could exist under different organization and vendor (though we only have a few of those cases). So when we identify duplicates and review them, we will consider Organization in this logic:
if the input contract is under organization '105188574'('Montefiore Health System (INFOR)'), we will look for duplicates for all organization since this is the whole system-wide contract, otherwise, we will only look for duplicates under the same organization + '105188574' combination since the member specific contract should only need to be compared with the system-wide contract and the contract under the same organization, but not necessary to compare with other organization since they are not related.

CREATE TABLE [Preprocessor].[CCXSyncedContractLine](
	[RN] [int] NOT NULL,
	[Organization] [varchar](100) NOT NULL,
	[OrganizationEID] [varchar](10) NULL,
	[ContractID] [varchar](100) NOT NULL,
	[Manufacturer] [varchar](255) NOT NULL,
	[Vendor] [varchar](255) NOT NULL,
	[ERPVendorID] [varchar](20) NULL,
	[ContractStartDate] [date] NULL,
	[ContractEndDate] [date] NULL,
	[ContractManufacturer_Infor] [varchar](10) NULL,
	[ManufacturerName_Infor] [varchar](255) NULL,
	[ContractStartDate_Infor] [date] NULL,
	[ContractEndDate_Infor] [date] NULL,
	[Contract_Infor] [varchar](10) NULL,
	[CCX_pkid] [int] NOT NULL,
	[TierLevel] [varchar](255) NULL,
	[TierDescription] [varchar](500) NULL,
	[ManufacturerNumber_CCX] [varchar](255) NOT NULL,
	[VendorItem_CCX] [varchar](255) NULL,
	[UOM_CCX] [varchar](10) NOT NULL,
	[QOE_CCX] [int] NULL,
	[ContractPrice_CCX] [decimal](18, 4) NULL,
	[EffectiveDate_CCX] [date] NULL,
	[ExpirationDate_CCX] [date] NULL,
	[ItemDescription_CCX] [varchar](500) NULL,
	[CK] [int] NULL,
	[RK] [int] NULL,
	[UOMtoMatchInfor_CCX] [varchar](10) NULL,
	[reduced_mfg_num_ccx] [varchar](100) NULL,
	[reduced_vendor_num_ccx] [varchar](100) NULL,
 CONSTRAINT [PK_CCXSyncedContractLINE] PRIMARY KEY CLUSTERED 
(
	[CCX_pkid] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON) ON [PRIMARY],
 CONSTRAINT [UX_CCXSyncedCL_ItemPerRN] UNIQUE NONCLUSTERED 
(
	[OrganizationEID] ASC,
	[ContractID] ASC,
	[ERPVendorID] ASC,
	[ManufacturerNumber_CCX] ASC,
	[UOM_CCX] ASC,
	[UOMtoMatchInfor_CCX] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON) ON [PRIMARY]
) ON [PRIMARY]


`[Preprocessor].[CCXSyncedContractLineCnt]` -- table contains count per contract for CCX, also included the contract description in case we need that. Manufacturer and Vendor are names that used by CCX. (not necessarily the same as the names used in Infor). ~1200 records, we only care about those 'CCX synced' contracts.

CREATE TABLE [Preprocessor].[CCXSyncedContractLineCnt](
	[OrganizationEID] [varchar](10) NOT NULL,
	[Organization] [varchar](100) NOT NULL,
	[ContractID] [varchar](100) NOT NULL,
	[ContractManufacturer_Infor] [varchar](10) NULL,
	[Manufacturer] [varchar](255) NOT NULL,
	[ERPVendorID] [varchar](20) NOT NULL,
	[VendorID] [varchar](7) NULL,
	[Vendor] [varchar](255) NOT NULL,
	[LineCnt_CCX] [int] NULL,
	[ContractDescription] [varchar](255) NULL,
 CONSTRAINT [PK_CCXSyncedContractLineCnt] PRIMARY KEY CLUSTERED 
(
	[OrganizationEID] ASC,
	[ContractID] ASC,
	[ERPVendorID] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON) ON [PRIMARY]
) ON [PRIMARY]


`[Preprocessor].[InforActiveCLRefCCXSyncedCL]` -- this contains all Infor active contract line prejoined to reference CCX line when possible (it can be matched to 0, 1, or multiple CCX lines). if the CCX_pkid is null, then that means the infor line only exists on ERP side, not the CCX side. when we try to make duplication detection, once the correponding CCX line is identified as true-positive or true-negative duplication, then all the related infor lines with refernce to the same CCX lines will automatically be marked as true-positive or true-negative, but if CCX_pkid is null, and by SKU matching we identified it is a 'potential duplicate' line for input row(s), then we will need to review the infor line itself to determine if it is true-positive or true-negative. ~604k records.
if we take the distinct columns above 'Infor_pkid', those are all the active contract lines in Infor system. 

CREATE TABLE [Preprocessor].[InforActiveCLRefCCXSyncedCL](
	[OrganizationEID] [varchar](10) NULL,
	[Organization] [varchar](100) NULL,
	[ContractID] [varchar](100) NOT NULL,
	[ContractName_Infor] [varchar](255) NOT NULL,
	[ContractManufacturer_Infor] [varchar](10) NULL,
	[ERPVendorID_Infor] [varchar](20) NULL,
	[VendorID_Infor] [varchar](10) NULL,
	[VendorItem_Infor] [varchar](100) NULL,
	[ContractLineManufacturer_Infor] [varchar](10) NULL,
	[ManufacturerNumber_Infor] [varchar](100) NULL,
	[UOM_Infor] [varchar](10) NULL,
	[QOE_Infor] [int] NULL,
	[ContractPrice_Infor] [decimal](18, 4) NULL,
	[EffectiveDate_Infor] [date] NULL,
	[ExpirationDate_Infor] [date] NULL,
	[ContractStartDate_Infor] [date] NULL,
	[ContractEndDate_Infor] [date] NULL,
	[ItemType] [varchar](20) NULL,
	[ItemNumber] [varchar](100) NULL,
	[Item] [varchar](100) NULL,
	[Contract] [varchar](10) NOT NULL,
	[ContractLine] [varchar](20) NOT NULL,
	[Infor_pkid] [varchar](31) NOT NULL,
	[matched_ccx_line_seq] [varchar](6) NOT NULL,
	[total_matched_ccx_line] [int] NULL,
	[CCXCurrentSyncFlag] [varchar](3) NULL,
	[reduced_mfg_num_infor] [varchar](100) NULL,
	[reduced_vendor_num_infor] [varchar](100) NULL,
	[JoinSyncType] [varchar](40) NULL,
	[CCX_pkid] [int] NULL,
	[ManufacturerNumber_CCX] [varchar](255) NULL,
	[VendorItem_CCX] [varchar](255) NULL,
	[UOM_CCX] [varchar](10) NULL,
	[UOMtoMatchInfor_CCX] [varchar](10) NULL,
	[QOE_CCX] [int] NULL,
	[ContractPrice_CCX] [decimal](18, 4) NULL,
	[ItemDescription_Infor] [varchar](500) NULL,
	[ItemDescription_CCX] [varchar](500) NULL,
 CONSTRAINT [PK_InforActiveCLmCCXSyncedCL] PRIMARY KEY CLUSTERED 
(
	[Infor_pkid] ASC,
	[matched_ccx_line_seq] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON) ON [PRIMARY]
) ON [PRIMARY]


`[Preprocessor].[InforActiveContractLineCnt]` -- the count of active contract lines in Infor per contract, included contract description. ~1200 records.

CREATE TABLE [Preprocessor].[InforActiveContractLineCnt](
	[OrganizationEID] [varchar](10) NOT NULL,
	[Organization] [varchar](100) NULL,
	[ContractID] [varchar](100) NOT NULL,
	[ContractManufacturer_Infor] [varchar](10) NULL,
	[ManufacturerName_Infor] [varchar](255) NULL,
	[ERPVendorID_Infor] [varchar](20) NOT NULL,
	[VendorID_Infor] [varchar](10) NULL,
	[VendorName_Infor] [varchar](255) NULL,
	[LineCnt_Infor] [int] NULL,
	[ContractDescription_Infor] [varchar](255) NOT NULL,
 CONSTRAINT [PK_InforActiveContractLineCnt] PRIMARY KEY CLUSTERED 
(
	[OrganizationEID] ASC,
	[ContractID] ASC,
	[ERPVendorID_Infor] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON) ON [PRIMARY]
) ON [PRIMARY]



`[Preprocessor].[CCXInforMatchedLink]` -- just a quick reference table extracted from the above InforActiveCLRefCCXSyncedCL table with CCX_pkid is not null to show the direct link between Infor line and CCX line, we can clearly see that Infor_pkid to CCX_pkid is a many to many relationship. ~600K records.
Typically if the same CCX_pkid appears in multiple records, that usually means the CCX side UOM has been changed and there might be a timing issue for the UOM change to be reflected on Infor side. Normally if for a given contract we see a 1-1 relations then those are usually 'good records' that all synced between CCX and Infor.
Since the CCX_pkid is just a surrogate key and it actually changes every time when we archive the CCX table and reload the data, so it is a fungible key and we can not rely on it to 'back-locate' anything. The true unique CCX identifier is:
OrganizationEID + ContractID + ERPVendorID + ManufacturerNumber_CCX + UOM_CCX combination, which is also the combination we use for duplication detection on CCX side. To make things easier to track, UOMtoMatchInfor_CCX should also be included.

CREATE TABLE [Preprocessor].[CCXInforMatchedLink](
	[Infor_pkid] [varchar](31) NOT NULL,
	[matched_ccx_line_seq] [varchar](6) NOT NULL,
	[CCX_pkid] [int] NOT NULL
) ON [PRIMARY]


# 2. tables that are kind of 'master data' that we may need to use in the program
`[Preprocessor].[PurchaseVendorLocation]` -- table contains the Infor standard vendor name and purchase from location name for each ERPVendorID. for ERPVendorID that the same as VendorID (without the -'Bxxx' part), PurchaseFromName will be NULL.

CREATE TABLE [Preprocessor].[PurchaseVendorLocation](
	[ERPVendorID] [varchar](20) NOT NULL,
	[VendorName] [varchar](255) NULL,
	[PurchaseFromName] [varchar](255) NULL,
	[Active] [varchar](10) NOT NULL,
 CONSTRAINT [PK_PurchaseVendorLocation] PRIMARY KEY CLUSTERED 
(
	[ERPVendorID] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON) ON [PRIMARY]
) ON [PRIMARY]


`[DM_MONTYNT\dli2].[MDM_EDI_SUB_UOM]` -- table help to translate the ccx/input side of UOM into infor side of UOM, the LawsonValue is the UOM value we use in Infor, ExternalValue is the UOM value received from CCX or input, if the UOM is not in ExternalValue column, then simply keep the input UOM.
CREATE TABLE [DM_MONTYNT\dli2].[MDM_EDI_SUB_UOM](
	[EDIListName] [varchar](100) NOT NULL,
	[LawsonValue] [varchar](10) NOT NULL,
	[ExternalValue] [varchar](10) NOT NULL,
	[LastUpdateDate] [date] NOT NULL,
 CONSTRAINT [PK_uom] PRIMARY KEY CLUSTERED 
(
	[LawsonValue] ASC,
	[ExternalValue] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON) ON [PRIMARY]
) ON [PRIMARY]


`[DM_MONTYNT\dli2].[MDM_MANUFACTURER_NAME_INFOR]`  -- join on Manufacturer or ContractManufacturer to get the standard manufacturer name on Infor side. ~1000 records.

CREATE TABLE [DM_MONTYNT\dli2].[MDM_MANUFACTURER_NAME_INFOR](
	[Manufacturer] [varchar](10) NOT NULL,
	[ManufacturerEID] [varchar](20) NOT NULL,
	[ManufacturerName] [varchar](255) NOT NULL,
	[Active] [varchar](5) NOT NULL,
	[LastUpdated] [date] NOT NULL,
 CONSTRAINT [PK_MFG] PRIMARY KEY CLUSTERED 
(
	[Manufacturer] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON) ON [PRIMARY]
) ON [PRIMARY]


`[DM_MONTYNT\dli2].[MDM_VENDORITEM]`  -- important Infor side data integrity check table, once true-positive lines are linked, we will use Vendor + VendorItem to locate the Item for input record on this table. 
We mostly will only need Item, ItemDescription, Vendor, VendorName, VendorItem, Manufacturer, ManufacturerNumber, VendorBuyUOM, VendorBuyUOM.UOMConversion, DefaultBuyUOM, DefaultBuyUOMMultiplier, UseAsDefault, Active columns for our data integrity check, other columns are not necessary for the logic. ~20K records.
On Infor side, checking logic includes: 
1) for the same Item + Vendor + Manufacturer + ManufacturerNumber, normally we are expecting the same VendorItem, when the different VendorItem exists for the same Item + Vendor combination, one of the VendorItem need to be marked as 'Yes' under 'UseAsDefault', otherwise the system will be confused on which VendorItem to use when automating PO creation.
2) for the same Item + Vendor + Manufacturer + ManufacturerNumber + UOM, the VendorBuyUOM.UOMConversion should be the same, otherwise it triggers data integrity issue.
3) for the same Vendor + VendorItem, the UOM and UOMConversion should be the same, otherwise it also triggers data integrity issue.
4) for the same Vendor + VendorItem, the Manufacturer + ManufacturerNumber + UOM should be the same, otherwise it also triggers data integrity issue.
5) for the same Item + Vendor + UOM, the VendorItem should be the same, otherwise it also triggers data integrity issue.
6) for a given Vendor + VendorItem, we need check if it is active or not, if it is 'No' for 'Active' column, it triggers 'vendor item not active' error.

CREATE TABLE [DM_MONTYNT\dli2].[MDM_VENDORITEM](
	[Item] [varchar](20) NOT NULL,
	[ItemDescription] [varchar](255) NULL,
	[Vendor] [varchar](20) NOT NULL,
	[VendorName] [varchar](100) NOT NULL,
	[VendorItem] [varchar](100) NOT NULL,
	[Manufacturer] [varchar](10) NULL,
	[ManufacturerNumber] [varchar](100) NULL,
	[VendorBuyUOM] [varchar](10) NULL,
	[VendorBuyUOM.UOMConversion] [numeric](10, 4) NULL,
	[DefaultBuyUOM] [varchar](10) NULL,
	[DefaultBuyUOMMultiplier] [numeric](10, 4) NULL,
	[UNSPSCCode] [varchar](20) NULL,
	[UNSPSCCodeDescription] [varchar](255) NULL,
	[CommodityCode] [varchar](20) NULL,
	[CommodityCodeDescription] [varchar](255) NULL,
	[MajorPurchasingClass] [varchar](10) NULL,
	[MajorPurchasingClassDescription] [varchar](255) NULL,
	[MinorPurchasingClass] [varchar](10) NULL,
	[MinorPurchasingClassDescription] [varchar](255) NULL,
	[UseAsDefault] [varchar](10) NULL,
	[Active] [varchar](10) NULL,
	[MajorPPEClass] [varchar](20) NULL,
	[MajorInventoryClass] [varchar](20) NULL,
	[OnContractDisplay] [varchar](20) NULL,
	[ContractRef1] [varchar](10) NULL,
	[ContractRef2] [varchar](10) NULL,
	[create stamp] [datetime] NOT NULL,
	[update stamp] [datetime] NOT NULL,
	[LastUpdateDate] [date] NOT NULL,
 CONSTRAINT [PK_VendorItem] PRIMARY KEY CLUSTERED 
(
	[Item] ASC,
	[Vendor] ASC,
	[VendorItem] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON) ON [PRIMARY]
) ON [PRIMARY]


`[DM_MONTYNT\dli2].[MDM_ITEM]` -- important Infor side data integrity check table, once true-positive lines are linked, we will use Item to locate the Item for input record on this table, or use Manufacturer (4-digit code) + ManufacturerNumber to locate the Item for input record on this table. We will mostly use the columns of Item, Description, Manufacturer, ManufacturerNumber, DefaultBuyUOM, DefaultBuyUOMMultiplier, Active for our data integrity check, other columns are not necessary for the logic. ~13K records.
checking logic includes:
1) Item is Active or not, if it is 'No' for 'Active' column, it triggers 'item not active' error.
2) For the same Item, Manufacturer + ManufacturerNumber must be the same, and when cross check with VendorItem table, the same Item also has to have the same Manufacturer + ManufacturerNumber, otherwise it triggers data integrity issue.

CREATE TABLE [DM_MONTYNT\dli2].[MDM_ITEM](
	[Item] [varchar](10) NOT NULL,
	[Active] [varchar](5) NOT NULL,
	[ConsignCode] [varchar](20) NULL,
	[Consignment] [varchar](5) NOT NULL,
	[CriticalItem] [varchar](5) NOT NULL,
	[DefaultBuyUOM] [varchar](10) NULL,
	[DefaultBuyUOMMultiplier] [int] NULL,
	[DefaultInventoryTransactionUOM] [varchar](10) NULL,
	[DefaultInventoryTransactionUOMMultiplier] [int] NULL,
	[StockUOM] [varchar](10) NULL,
	[Description] [varchar](500) NOT NULL,
	[Description3] [varchar](1000) NOT NULL,
	[Discontinued] [varchar](5) NOT NULL,
	[GenericName] [varchar](500) NULL,
	[Implantable] [varchar](5) NOT NULL,
	[Reusable] [varchar](5) NOT NULL,
	[Sterile] [varchar](5) NOT NULL,
	[GTINForStockUOM] [varchar](20) NULL,
	[ItemGTINsRel.Active] [varchar](5) NULL,
	[HCPCSCode] [varchar](80) NULL,
	[ItemDescriptionAbbreviation] [varchar](20) NULL,
	[CommodityCode] [varchar](40) NULL,
	[CommodityCode.CcDescription] [varchar](500) NULL,
	[MMAHSPrimaryDI] [varchar](40) NULL,
	[MajorInventoryClass] [varchar](40) NULL,
	[MajorPPEClass] [varchar](40) NULL,
	[MajorPurchasingClass] [varchar](40) NULL,
	[MajorPurchasingClass.Description] [varchar](500) NULL,
	[MinorInventoryClass] [varchar](40) NULL,
	[MinorPPEClass] [varchar](40) NULL,
	[MinorPurchasingClass] [varchar](40) NULL,
	[Manufacturer] [varchar](40) NOT NULL,
	[ManufacturerDescription] [varchar](500) NOT NULL,
	[ManufacturerNumber] [varchar](255) NOT NULL,
	[ReportDate] [date] NOT NULL,
 CONSTRAINT [PK_item] PRIMARY KEY CLUSTERED 
(
	[Item] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON) ON [PRIMARY]
) ON [PRIMARY]


`[DM_MONTYNT\dli2].[MDM_ITEMUOM]` -- Infor side data integreity check after 'Item' is labeled per input row, since the input will be contract data, so we need to make sure after we translate the input UOM use the MDM_EDI_SUB_UOM table, the UOM is valid for buying for the item on Infor side (ValidFroBuying in ('Valid', 'Default')), We should only need Item, UOM, UOMConversion, ValidForBuying fields. ~25K records.

CREATE TABLE [DM_MONTYNT\dli2].[MDM_ITEMUOM](
	[Item] [varchar](20) NOT NULL,
	[ItemGroup] [varchar](5) NOT NULL,
	[UOM] [varchar](10) NOT NULL,
	[TrackedIn] [varchar](5) NOT NULL,
	[UOMConversion] [numeric](10, 4) NOT NULL,
	[ValidForBuying] [varchar](20) NOT NULL,
	[ValidForInventoryTransaction] [varchar](20) NOT NULL,
	[ValidForSellPrice] [varchar](20) NOT NULL,
	[ValidForSelling] [varchar](20) NOT NULL,
	[PackingWeight] [numeric](18, 4) NULL,
	[PackingVolume] [numeric](18, 4) NULL,
	[Item.Active] [varchar](5) NOT NULL,
	[ItemDescription] [varchar](255) NULL,
	[Item.OnContract] [varchar](20) NULL,
	[Item.UNSPSCCode] [varchar](20) NULL,
	[Item.IssueAccount] [varchar](10) NULL,
	[create stamp] [datetime] NOT NULL,
	[update stamp] [datetime] NOT NULL,
 CONSTRAINT [PK_ItemUOM] PRIMARY KEY CLUSTERED 
(
	[Item] ASC,
	[UOM] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON) ON [PRIMARY]
) ON [PRIMARY]


`[DM_MONTYNT\dli2].[MDM_ITEMGTIN]`  -- check for GTIN, not all Item have GTIN, this table is only about ~3K records, and we will only need to check Item + UOM and see if this is Active. If the Item + UOM did not exist on this table, there is no need to do the GTIN check.

CREATE TABLE [DM_MONTYNT\dli2].[MDM_ITEMGTIN](
	[Item] [varchar](10) NOT NULL,
	[Manufacturer] [varchar](10) NULL,
	[ManufacturerNumber] [varchar](100) NULL,
	[UOM] [varchar](5) NOT NULL,
	[UOMConversion] [numeric](10, 4) NOT NULL,
	[Active] [varchar](5) NOT NULL,
	[GTINStructure] [varchar](20) NULL,
	[ItemGTIN] [varchar](20) NOT NULL,
	[ParentGTIN] [varchar](20) NULL,
	[create stamp] [datetime] NOT NULL,
	[update stamp] [datetime] NOT NULL,
 CONSTRAINT [PK_ItemGTIN] PRIMARY KEY CLUSTERED 
(
	[ItemGTIN] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON) ON [PRIMARY]
) ON [PRIMARY]


- Summary on Infor logic:
1) Infor recognize item by:
- Vendor + VendorItem AND/OR
- Manufacturer + ManufacturerNumber + UOM
2) On VendorItem:
- same Item --> same Manufacturer + ManufacturerNumber, but can have different VendorBuyUOM as long as it is registered on ItemUOM, for the same UOM, the VendorBuyUOM.UOMConversion should be the same.
- Furthermore, different Item + UOM could be purchased from different Vendor, but for the same Vendor, if multiple VendorItem exist for the same Item + UOM, one of the VendorItem has to be marked as 'UseAsDefault' = 'Yes', otherwise it triggers data integrity issue.
3) On Item:
- same Item should always have the same Manufacturer + ManufacturerNumber combination, and only one Manufacturer + ManufacturerNumber combination is allowed per Item. So basically Infor do not allow the same Item to be sourced from different manfuacturer or within same manufacturer but changed in manufacturer number. 
- It assume Item can have different UOM, but will be reference under singular ManufactuerNumber (SKU), which in some real life cases can be a problem since manufacturer could have different SKUs for the same item with different UOM. The design suggests that Infor use Item to handle different UOM, and VendorItem further resovles on which vendor to purchase from.


`[Preprocessor].[DistributorGroup]` -- a small manually maintained table to group distributors by their ERPVendorID, since we have cases that the same vendor (e.g. Medline) has multiple ERPVendorID account so we can set up different contract and pay them differently. But when we run the scoring, for type C we would like to define the same vendor as if they are in the same Group on this table.
CREATE TABLE [Preprocessor].[DistributorGroup](
	[ERPVendorID] [varchar](20) NOT NULL,
	[VendorName] [varchar](100) NULL,
	[Group] [int] NOT NULL,
	[EditBy] [varchar](40) NOT NULL,
	[EditDate] [date] NOT NULL,
 CONSTRAINT [PK_DistributorGroup] PRIMARY KEY CLUSTERED 
(
	[ERPVendorID] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON) ON [PRIMARY]
) ON [PRIMARY]
GO

# 3. tables for reporting or related to reporting
`[Preprocessor].[InforItemReplenishFrom]` -- a table that support the Item replenish from checks.
