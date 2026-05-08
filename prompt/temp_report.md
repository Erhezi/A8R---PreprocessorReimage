v1.0 compatible report
# excel report
- name: dedup_output_to_review_[contract_id]_[vendor_id]_[date].xlsx
- description: excel report contains the matched results from preprocess, only report on CCX and ACCEPTED records, the report have several sheets:
  - quick_line_count: contains the total line count for each matched contract (per contract_id, vendor_id, organization), and the line count for the matched records (overlap between input and CCX ACCEPTED records)
  - dedup review sheets:
    - each sheet will named by the matched contract_id (if multiple contract under same contract_id, then add suffix _1, _2, etc)
      - each sheet will contains the matched records and the input records for reference for review, arrange them in this way:
        - Mfg Part Num | Vendor Part Num | Buyer Part Num | Description | Contract Price | UOM | QOE | Effective Date | Expiration Date | Contract ID | ERP Vendor ID | Organization | Action | Notes | Mfg Part Num (Input) | Vendor Part Num (Input) | Description (Input) | Contract Price (Input) | UOM (Input) | QOE (Input) | Contract ID (Input) | ERP Vendor ID (Input) | Organization (Input) | Infor Item # |
        - the "Action" column will be populated as "dup review" for all records in the sheet
        - the "Notes" column will be left blank for now
        - the Infor Item # is the the item master item number matched to input record, under column infor_item_num on table PreprocessorTaskItemForDecision
- style: header row with bold font
    - column header with yellow backround color for:
    Mfg Part Num | Vendor Part Num | Buyer Part Num | Description | Contract Price | UOM | QOE | Effective Date | Expiration Date | Contract ID | ERP Vendor ID | Organization | Action | Notes |
    - column header with light blue background color for:
    Mfg Part Num (Input) | Vendor Part Num (Input) | Description (Input) | Contract Price (Input) | UOM (Input) | QOE (Input) | Contract ID (Input) | ERP Vendor ID (Input) | Organization (Input) | Infor Item # |
- "Action" column real fill
  - take a look at the rule we defined for marking the matched records as 'keep', 'drop' or 'any' in dedup logic.
    when intention of the input line is UPDATE or NEW:
    - group 'SS' - set the "Action" as 'Same contract item, Update'
    - group 'DV' - set the "Action" as 'Buy from different vendor, keep both'
    - group 'ODO' - set the "Action" as 'Buy for different organization using same contract ID, review'
    - group 'TCCD' - set the "Action" as 'Consider only keep one record, review'
    - group 'CECCD' - set the "Action" as 'Buy for different organization using different contract, review'
    when intention of the input line is EXPIRE:
    - group 'SS' - set the "Action" as 'Same contract item, Update expiration date to expire'
    - group 'DV', 'ODO', 'TCCD', 'CECCD' - set the "Action" as 'Not affected by expiring the input line, keep the record'
- "Notes" column real fill
  - for group 'ODO' and intention 'UPDATE' or 'NEW':
    - if both input and matched organization are ME (none MHS type), set "Different member entity contract item, keep both and make sure the data elements are consistent with each other"
    - if either input or matched organization is MHS type, set "If not for tracking price difference between member entity and MHS, consider maintain only the MHS contract and remove the member entity contract entirely. Otherwise if price difference is desired, keep both and make sure the data elements are consistent with each other."
  - for group 'TCCD' and intention 'UPDATE' or 'NEW':
    - if the matched record has the same contract price as input line, set "Consider only keep one record, review"
      - if both input and matched are premier, set "both contracts have the same price, both are premier contract, keep both and ensure the data elements are consistent with each other"
      - if matched is premier and input is local, set "both contracts have the same price, but matched contract is premier while input contract is local, consider keep the matched record and drop the input line"
      - if matched is local and input is premier, set "both contracts have the same price, but input contract is premier while matched contract is local, consider keep the input record and drop the matched line"
      - if both matched and input are local, set "both contracts have the same price, both are local contract, review and keep only one record"
    - if the matched record has better contract price than input line (matched ea price < input ea price), set "contract [matched contract id] has better price, consider keep the matched record and drop the input line"
      - if both input an matched are premier contract, set "contract [matched contract id] has better price, both are premier contract, keep both and ensure the data elements are consistent with each other, consider setting priority based on price on Infor to default to the favorable pricing"
      - if matched is premier and input is local, set "contract [matched contract id] has better price, matched contract is premier while input contract is local, consider keep the matched record and drop the input line"
      - if matched is local and input is premier, set "contract [matched contract id] has better price, but input is premier contract, keep both and ensure the data elements are consistent with each other, consider setting priority based on price on Infor to default to the favorable pricing"
      - if both matched and input are local, set "contract [matched contract id] has better price, both are local contract, review and keep the matched record and drop the input line"
    - if the matched record has worse contract price than input line (matched ea price > input ea price), set "input contract has better price, consider keep the input line and drop the matched record"
      - if both input an matched are premier contract, set "input contract has better price, both are premier contract, keep both and ensure the data elements are consistent with each other, consider setting priority based on price on Infor to default to the favorable pricing"
      - if matched is premier and input is local, set "input contract has better price, but matched contract is premier while input contract is local, keep both and ensure the data elements are consistent with each other, consider setting priority based on price on Infor to default to the favorable pricing"
      - if matched is local and input is premier, set "input contract has better price, input contract is premier while matched contract is local, consider keep the input record and drop the matched line"
      - if both matched and input are local, set "input contract has better price, both are local contract, review and keep the input record and drop the matched line"
  - for group 'CECCD' and intention 'UPDATE' or 'NEW':
    - if the matched record has the same contract price as input line, set "Buy for different organization using different contract with same price, review organization and contract type to determine if both records are needed"
      depending on (matched organization, input organization) and (matched contract type, input contract type), we can have different notes:

      - (ME, ME) and (Premier, Premier), set "both contracts have the same price, but for different member entities, keep both and ensure the data elements are consistent with each other"
      - (ME, ME) and (Local, Local), set "both contracts have the same price, but for different member entities, keep both and ensure the data elements are consistent with each other"
      - (ME, ME) and (Local, Premier), set "both contracts have the same price, but for different member entities, keep both and ensure the data elements are consistent with each other"
      - (ME, ME) and (Premier, Local), set "both contracts have the same price, but for different member entities, keep both and ensure the data elements are consistent with each other"

      - (MHS, ME) and (Premier, Premier), set "both contracts have the same price, both are premier contract, keep both and ensure the data elements are consistent with each other"
      - (MHS, ME) and (Local, Local), set "both contracts have the same price, both are local contract, consider keep the matched MHS record and drop the input ME record"
      - (MHS, ME) and (Local, Premier), set "both contracts have the same price, but input ME contract is premier, keep both and ensure the data elements are consistent with each other"
      - (MHS, ME) and (Premier, Local), set "both contracts have the same price, input ME contract is local, consider keep the matched MHS record and drop the input ME record"

      - (ME, MHS) and (Premier, Premier), set "both contracts have the same price, both are premier contract, keep both and ensure the data elements are consistent with each other"
      - (ME, MHS) and (Local, Local), set "both contracts have the same price, both are local contract, consider keep the input MHS record and drop the matched ME record"
      - (ME, MHS) and (Local, Premier), set "both contracts have the same price, but matched MHS contract is premier, consider keep the input MHS record and drop the matched ME record"
      - (ME, MHS) and (Premier, Local), set "both contracts have the same price, matched MHS contract is local, keep both and ensure the data elements are consistent with each other"

    - if the matched record has better contract price than input line (matched ea price < input ea price), set "contract [matched contract id] has better price, review organization and contract type to determine if both records are needed"
      depending on (matched organization, input organization) and (matched contract type, input contract type), we can have different notes:

      - (ME, ME) and (Premier, Premier), set "contract [matched contract id] has better price, but for different member entities, keep both and ensure the data elements are consistent with each other, verfify that we truely have contract price difference between different member enetities for the item"
      - (ME, ME) and (Local, Local), set "contract [matched contract id] has better price, but for different member entities, keep both and ensure the data elements are consistent with each other, verfify that we truely have contract price difference between different member enetities for the item"
      - (ME, ME) and (Local, Premier), set "contract [matched contract id] has better price, but for different member entities, keep both and ensure the data elements are consistent with each other, verfify that we truely have contract price difference between different member enetities for the item"
      - (ME, ME) and (Premier, Local), set "contract [matched contract id] has better price, but for different member entities, keep both and ensure the data elements are consistent with each other, verfify that we truely have contract price difference between different member enetities for the item"

      - (MHS, ME) and (Premier, Premier), set "MHS contract [matched contract id] has better price, both are premier contract, keep both and ensure the data elements are consistent with each other, verify the price difference is due to member entity truely have to pay higher price than MHS for the item"
      - (MHS, ME) and (Local, Local), set "MHS contract [matched contract id] has better price, both are local contract, verify the price difference is due to member entity truely have to pay higher price than MHS for the item, otherwise consider keep the matched MHS record and drop the input ME record"
      - (MHS, ME) and (Local, Premier), set "MHS contract [matched contract id] has better price, but input ME contract is premier, keep both and ensure the data elements are consistent with each other, verify the price difference is due to member entity truely have to pay higher price than MHS for the item"
      - (MHS, ME) and (Premier, Local), set "MHS contract [matched contract id] has better price, verify the price difference is due to member entity truely have to pay higher price than MHS for the item, otherwise consider keep the matched MHS record and drop the input ME record"

      - (ME, MHS) and (Premier, Premier), set "member entity contract [matched contract id] has better price, both are premier contract, keep both and ensure the data elements are consistent with each other, verify the price difference is due to member entity truely have to pay lower price than MHS for the item"
      - (ME, MHS) and (Local, Local), set "member entity contract [matched contract id] has better price, both are local contract, verify the price difference is due to member entity truely have to pay lower price than MHS for the item, otherwise consider keep the input MHS record and drop the matched ME record"
      - (ME, MHS) and (Local, Premier), set "member entity contract [matched contract id] has better price, keep both and ensure the data elements are consistent with each other, verify the price difference is due to member entity truely have to pay lower price than MHS for the item, otherwise consider keep the input MHS record and drop the matched ME record"
      - (ME, MHS) and (Premier, Local), set "member entity contract [matched contract id] has better price, keep both and ensure the data elements are consistent with each other, verify the price difference is due to member entity truely have to pay lower price than MHS for the item"

    - if the matched record has worse contract price than input line (matched ea price > input ea price), set "input contract has better price, review organization and contract type to determine if both records are needed"
      depending on (matched organization, input organization) and (matched contract type, input contract type), we can have different notes:

      - (ME, ME) and (Premier, Premier), set "input contract has better price, but for different member entities, keep both and ensure the data elements are consistent with each other, verfify that we truely have contract price difference between different member enetities for the item"
      - (ME, ME) and (Local, Local), set "input contract has better price, but for different member entities, keep both and ensure the data elements are consistent with each other, verfify that we truely have contract price difference between different member enetities for the item"
      - (ME, ME) and (Local, Premier), set "input contract has better price, but for different member entities, keep both and ensure the data elements are consistent with each other, verfify that we truely have contract price difference between different member enetities for the item"
      - (ME, ME) and (Premier, Local), set "input contract has better price, but for different member entities, keep both and ensure the data elements are consistent with each other, verfify that we truely have contract price difference between different member enetities for the item"

      - (MHS, ME) and (Premier, Premier), set "input ME contract has better price, both are premier contract, keep both and ensure the data elements are consistent with each other, verify the price difference is due to member entity truely have to pay lower price than MHS for the item"
      - (MHS, ME) and (Local, Local), set "input ME contract has better price, both are local contract, verify the price difference is due to member entity truely have to pay lower price than MHS for the item, keep both and ensure the data elements are consistent with each other, otherwise consider keep the matched MHS record and drop the input ME record"
      - (MHS, ME) and (Local, Premier), set "input ME contract has better price, keep both and ensure the data elements are consistent with each other, verify the price difference is due to member entity truely have to pay lower price than MHS for the item"
      - (MHS, ME) and (Premier, Local), set "input ME contract has better price, keep both and ensure the data elements are consistent with each other, verify the price difference is due to member entity truely have to pay lower price than MHS for the item, otherwise consider keep the matched MHS record and drop the input ME record"

      - (ME, MHS) and (Premier, Premier), set "input MHS contract has better price, both are premier contract, keep both and ensure the data elements are consistent with each other, verify the price difference is due to member entity truely have to pay higher price than MHS for the item"
      - (ME, MHS) and (Local, Local), set "input MHS contract has better price, both are local contract, verify the price difference is due to member entity truely have to pay higher price than MHS for the item, otherwise consider keep the input MHS record and drop the matched ME record"
      - (ME, MHS) and (Local, Premier), set "input MHS contract has better price, keep both and ensure the data elements are consistent with each other, verify the price difference is due to member entity truely have to pay higher price than MHS for the item, otherwise consider keep the input MHS record and drop the matched ME record"
      - (ME, MHS) and (Premier, Local), set "input MHS contract has better price, keep both and ensure the data elements are consistent with each other, verify the price difference is due to member entity truely have to pay higher price than MHS for the item"


- sheet to add to this report:
  - dup review sheet view by input:
    - sheet name: view_by_input
    - this sheet will take all the input lines as the left set of columns, and left join to the matched CCX ACCEPTED records, the columns arrangement will be:
    - column header with light blue background:
    Mfg Part Num (Input) | Vendor Part Num (Input) | Buyer Part Num (Input) | Description (Input) | Contract Price (Input) | UOM (Input) | QOE (Input) | Effective Date (Input) | Expiration Date (Input) | Contract ID (Input) | ERP Vendor ID (Input) | Organization (Input) | Infor Item # | Infor Item BuyUOM Options| Valid BuyUOM (Y/N) | Input Ref |Dup Matched (Y/N) | Total Matched Lines |
    - column header with yellow background:
    Mfg Part Num | Vendor Part Num| Buyer Part Num | Description | Contract Price | UOM | QOE | Effective Date | Expiration Date | Contract ID | ERP Vendor ID | Organization |

    - the "Dup Matched (Y/N)" column will be populated with "Yes" if there is at least one matched CCX ACCEPTED record for this input line, otherwise "No"
    - the "Total Matched Lines" column will be populated with the total matched CCX ACCEPTED lines count for this input line
    - Input Ref column will be the input file row number that is under the column 'file_row' on PreprocessorTaskItem (should be easily obtained by task_id and input_item_id)
    - Infor Item BuyUOM Options column will be populated with the available buy UOM options for the matched Infor item, which can be obtained from the infor_item_uom_options column on PreprocessorItemMatching table using task_id, input_item_id (item_id) and the infor_item_num
    - Valid BuyUOM (Y/N) column will be populated with "Yes" if the input line UOM (Infor Mapped)*QOE is in the available buy UOM options for the matched Infor item, otherwise "No", highlilght the row if the the column marked as 'No'

- replacement contract special
  - when a matched contract is marked as 'to be replaced by input' in the dedup logic, the output tab for that specific contract(s) will take the same column arragement, but we will find the rest of the records that are on the same contract that did not match to input so we know if we use the input to 'replace' the old contract, what items are covered (matched) and what items are not covered (unmatched).
  - for unmatched records:
    - Action: Only seen on to-be replaced contract [contract_id]
    - Notes: check if the item is discontinued, or evaluate if we need put this to the new contract
    