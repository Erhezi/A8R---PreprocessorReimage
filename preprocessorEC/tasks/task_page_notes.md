# Task Landing Page — Design Notes

Notes on how the task list landing page (`/tasks/`) is built, so the next
person (or the next me) knows why it looks the way it does.

## Pagination / search / filtering are CLIENT-SIDE

**Decision:** The landing page fetches the *entire* task set in one request and
does search, filtering, column toggling, and pagination in the browser. There is
no server-side paging query.

### How it works
- `GET /api/tasks?limit=10000` returns every task as JSON (`tasks/routes.py :: api_list_tasks`).
- `task_list.html` stores that in a module-level `allTasks` array (`fetchTasks()`).
- Every interaction re-renders from that array — no re-fetch:
  - **Search box** — case-insensitive substring match across all text columns
    (task id, contract #, vendor id/name, purchase-from, type, org, OEM,
    intention, phase, status, Wrike id, owner, notes, and the Infor
    contract-manufacturer code + name).
  - **Phase / Status** dropdowns — exact-match filters, stack with search.
  - **Columns** dropdown — checkbox toggles for the optional Manufacturer, OEM
    Name and Notes columns (default hidden). Pure show/hide via the `d-none` class.
  - **Pagination** — 20 rows per page, computed with `Array.slice`.
- **Refresh** re-pulls from the server; deleting a task also re-pulls.

### Why client-side
- The page already fetched-and-rendered the whole list in JS, so this was the
  smallest change and added no new endpoints.
- Combined filtering + paging is trivial and instant when the data is already
  in memory — no round-trips per keystroke or page turn.
- Expected scale is hundreds to low-thousands of tasks. The `limit` is capped at
  10000 server-side, which covers that comfortably.

### When to revisit (switch to server-side)
If the task table grows past a few thousand rows, the single fetch and in-memory
filter will start to feel heavy. At that point move to server-side pagination:
`WHERE` clauses for the filters, a `COUNT(*)` for the total, and
`OFFSET … FETCH NEXT` for the page window, with the front-end sending
`page` / `page_size` / `search` params instead of pulling everything.

## Table columns
Fixed columns: ID, Contract #, Vendor, Type, Org, Intention, Phase, Status,
Wrike ID, Owner, Updated, (delete action).

Optional columns (off by default, toggled via the **Columns** dropdown):
- **Manufacturer** — `contract_manufacturer_infor` + `contract_manufacturer_name_infor`
  rendered as `code - name`.
- **OEM Name** — the `oem_name` field.
- **Notes** — the free-text `notes` field.

Optional `<th>`/`<td>` cells are always in the DOM tagged with
`col-manufacturer` / `col-oem` / `col-notes` classes; `applyColumnVisibility()`
toggles `d-none` on them so the header and body stay in sync across re-renders.
