## Plan: Contract Atlas Flask App Restructuring (LangGraph-Ready)

Restructure the Flask app using a **4-layer architecture** (Routes → Services → State Machine → Repositories) that works as a Flask app now and maps directly to LangGraph + FastAPI + React later. JSON APIs from day one. SQLite for session + working state. Full service layer so business logic is framework-agnostic.

### Architecture: 4-Layer Design

```
Routes (Flask blueprints now → FastAPI routers later)
  Thin HTTP layer. Returns JSON. Jinja templates consume via fetch().
     ↓
Services (pure Python, no Flask imports)
  All business logic. One service per phase.
  Later: become LangGraph node implementations.
     ↓
State Machine (explicit phase transitions)
  TaskStateMachine: INTAKE → IDENTITY → PREPROCESS → DEDUP → EXPORT → MONITORING
  Later: becomes LangGraph StateGraph with same nodes.
     ↓
Repositories (data access)
  SQL Server: permanent records. SQLite: working state + sessions.
  .sql files loaded by repo layer. Stay identical in future stack.
```

**Why this maps to LangGraph:**
- `TaskStateMachine` transitions → `StateGraph` edges
- `TaskState` TypedDict → LangGraph `State` (same shape)
- Service functions → node implementations (already right granularity)
- Human review points (MDM, contract review) → `interrupt()` calls
- SQLite `workstate.db` → `SqliteSaver` checkpointer

### SQLite Design

- **`instance/session.db`** — Flask-Session storage (ephemeral, can wipe on restart)
- **`instance/workstate.db`** — Per-task intermediate state:
  - `task_working_state`: task_id, phase, `state_json` (serialized `TaskState` dict)
  - `match_candidates`: task_id, input_item_id, matched_ref, similarity_score, bucket, decision
  - `review_queue`: task_id, review_type, payload_json, status
  - The `state_json` column stores the exact dict that becomes LangGraph State later

### New Directory Skeleton

```
preprocessorEC/
├── __init__.py              # App factory (updated)
├── config.py                # + SQLite paths
├── models.py                # SQLAlchemy: Task, TaskItem, PreCheckError, MatchResult, User
├── state.py                 # TaskState TypedDict + TaskStateMachine
│
├── db/                      # Repository layer
│   ├── engine.py            # SQL Server + SQLite engines
│   ├── sql_loader.py        # load_query() → reads .sql files
│   ├── task_repo.py         # ORM CRUD
│   └── workstate_repo.py    # SQLite working state (save/load TaskState)
│
├── services/                # Business logic (framework-agnostic)
│   ├── intake_service.py    # PC1
│   ├── identity_service.py  # PC2, Nuvia, vendor
│   ├── preprocess_service.py # SKU matching, similarity, IM matching
│   ├── dedup_service.py     # Simulation, integrity
│   ├── export_service.py
│   └── monitoring_service.py
│
├── tasks/                   # Landing page (JSON APIs + Jinja)
├── intake/                  # Phase 1
├── identity/                # Phase 2
├── preprocess/              # Phase 3 (unified dup + IM matching)
├── dedup/                   # Phase 4 (stub)
├── export/                  # Phase 5
├── monitoring/              # Phase 6 (stub)
├── auth/, admin/            # Keep
├── common/                  # Slimmed: session config + shared utils only
├── instance/                # SQLite dbs (gitignored)
│   ├── session.db
│   └── workstate.db
└── ...
```

### Steps

**Phase A — Foundation** *(must complete first, Steps 1-3 parallel)*

1. **SQLAlchemy models** (`models.py`) — Task, TaskItem, PreCheckError, MatchResult, TaskStatusLog
2. **TaskState + StateMachine** (`state.py`) — TypedDict (future LangGraph State) + transition logic with guards
3. **Data access layer** (`db/`) — SQL Server + SQLite engines, `sql_loader.py`, `task_repo.py`, `workstate_repo.py`
4. **Services layer** (`services/`) — All service files with function signatures. Pure Python. *(depends on 1-3)*
5. **Tasks module + app factory** — JSON APIs for task CRUD, landing page. Update `__init__.py`: new blueprints, SQLite init, no StepManager. *(depends on 1-4)*

**Phase B — Intake & Identity**

6. **Intake** (`intake/`) — JSON APIs, implement `intake_service.py` (extract from `file_processing` + `common/utils`). *(depends on A)*
7. **Identity** (`identity/`) — JSON APIs, implement `identity_service.py`. *(parallel with 6)*

**Phase C — Preprocess Core**

8. **Preprocess** (`preprocess/`) — Implement `preprocess_service.py` (extract from `duplicate_detection` + `item_matching`). Unified dup + IM matching. *(depends on B)*

**Phase D — Downstream (stubs)**

9. **Dedup** — extract `change_simulation` logic *(depends on 8)*
10. **Export** — move `data_export` + formatters *(depends on 9)*
11. **Monitoring** — stub *(depends on 10)*

**Phase E — Cleanup**

12. **Remove old modules**, slim `common/`
13. **Frontend** — task-centric nav, all pages use `fetch()` for JSON APIs *(parallel with backend)*

### Key Decisions

- **JSON APIs from day one** — Jinja templates call them via `fetch()`. React replaces Jinja later without touching APIs.
- **Services are framework-agnostic** — no Flask imports. Same functions become LangGraph nodes.
- **TaskState TypedDict = future LangGraph State** — designed now for 1:1 mapping.
- **SQLite `workstate.db`** replaces filesystem sessions for intermediate data. Maps to `SqliteSaver` checkpointer later.
- **SQL Server** stays for permanent records (tasks, items, match results).
- Soft role enforcement, phases 4-6 are stubs, deployment unchanged.

### Future Migration Path

1. **FastAPI**: Replace `routes.py` files with FastAPI routers. Services + repos untouched. ~1 day/module.
2. **React**: Build components calling same `/api/` endpoints. Delete Jinja templates.
3. **LangGraph**: `TaskStateMachine` → `StateGraph`. Services → node implementations. Human reviews → `interrupt()`. `workstate.db` → `SqliteSaver`.
4. **Nuvia removal**: Replace `identity_service.apply_standardized_descriptions()` with LLM-based implementation. No route changes.

**Every seam in the 4-layer architecture is a future swap point.** Services don't know about Flask. State machine doesn't know about HTTP. Repos don't know about the UI.