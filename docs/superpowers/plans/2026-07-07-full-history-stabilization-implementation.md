# Full-History Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stabilize the Streamlit/Supabase Warehouse Control Tower for full-history data without changing business formulas.

**Architecture:** Add formula/golden tests first, then make behavior-preserving P0 fixes for cache invalidation, admin security, Supabase error classification, lazy export, Billing dependency, and duplicate Vollpalette computation. Performance work must preserve exact outputs under the new tests; storage redesign is introduced as a compatibility layer, not as a destructive migration.

**Tech Stack:** Python 3.12, Streamlit, pandas, NumPy, pyarrow Parquet, Supabase Storage, pytest, pytest-cov, ruff advisory.

## Global Constraints

- Full-history default must remain preserved.
- Do not change Billing, movement, Vollpalette, MARM, date, or KPI business semantics unless a task explicitly adds a failing test showing the current behavior is a bug and the user approves the behavior change.
- Every behavior-preserving optimization must keep row-level or aggregate parity in tests.
- Prefer small, focused helper functions and minimal diffs over broad restructuring of `app.py`.
- Do not read or write real production Supabase data in tests; use synthetic pandas DataFrames and monkeypatches.
- Admin zone must fail closed: no `admin123` default.
- Supabase 401/403/429/config errors must not be treated as missing files.
- Excel export must be generated only after explicit user action.
- Push only after tests, compileall, runtime smoke, and code-review fixes are complete.

---

## File Structure

- Modify `app.py`
  - Admin password handling, global cache invalidation, Billing result provider, lazy Excel export, one-pass Vollpalette handoff, safe session state cleanup.
- Modify `database.py`
  - Supabase error classification, retry behavior, public helpers for transient/auth/not-found distinction, optional safer upload staging hook.
- Modify `modules/tab_billing.py`
  - Extract reusable `compute_billing_result(...)`, keep `render_billing(...)` as UI wrapper, make cache key stable and independent of tab order.
- Modify `modules/utils.py`
  - Keep existing formula logic; only optimize after golden tests. If changing `fast_compute_moves`, preserve return type compatibility (`list[int], list[int], list[int]`).
- Modify `modules/tab_packing.py`, `modules/tab_fu_compare.py`, `modules/tab_board.py` only if needed to consume central Billing output safely.
- Create `tests/test_formula_golden.py`
  - Golden tests for movement, Vollpalette, Billing, MARM dedupe, and date normalization risks.
- Create `tests/test_app_stability.py`
  - Tests for app-level cache clearing, admin password fail-closed behavior, lazy export, and Billing provider tab-order independence.
- Modify `tests/test_datalayer.py`
  - Supabase error classification tests for 404 vs 400/401/403/429.
- Modify `tests/test_database_edge_cases.py`
  - MARM dedupe and cache invalidation tests.
- Modify `tests/test_performance_regression.py`
  - Add moderate full-history synthetic tests that are stable in CI.
- Modify `README.md`
  - Document full-history stabilization, admin secret requirement, refresh/export behavior, and verification commands.

---

### Task 1: Formula Golden Baseline

**Files:**
- Create: `tests/test_formula_golden.py`
- Modify: `tests/test_utils.py` only if existing utility assertions need a small fixture import; prefer no change.

**Interfaces:**
- Consumes: `modules.utils.fast_compute_moves(...)`, `modules.utils.detect_vollpalettes(...)`, `database._dedupe_by_table(...)`, `modules.tab_billing.cached_billing_logic_v28(...)`.
- Produces: Regression fixtures that later tasks must keep green.

- [ ] **Step 1: Write movement golden tests**

Create `tests/test_formula_golden.py` with the initial imports and movement tests:

```python
"""Golden regression tests for formula-critical business logic.

These tests intentionally use tiny synthetic datasets. They protect formulas
before performance/stability refactors so optimizations cannot silently change
billing, movement, Vollpalette, or MARM behavior.
"""
import pandas as pd

from database import _dedupe_by_table
from modules.tab_billing import cached_billing_logic_v28
from modules.utils import detect_vollpalettes, fast_compute_moves


def test_fast_compute_moves_mixed_formula_golden():
    total, exact, miss = fast_compute_moves(
        qty_arr=[0, 100, 105, 12, 10, 7],
        queue_arr=["PI_PL", "PI_PL_FU", "PI_PL", "PI_PL", "PI_PL", "PI_PL"],
        su_arr=["", "X", "", "", "", ""],
        boxes_arr=[(10,), (), (10,), (10,), (), (5, 2)],
        weight_arr=[0.5, 0.0, 0.5, 0.5, 0.5, 3.0],
        dim_arr=[5.0, 0.0, 5.0, 20.0, 5.0, 5.0],
        v_limit=2.0,
        d_limit=15.0,
        h_limit=5,
    )

    assert total == [0, 1, 11, 3, 2, 2]
    assert exact == [0, 1, 11, 3, 0, 2]
    assert miss == [0, 0, 0, 0, 2, 0]
```

- [ ] **Step 2: Run movement golden test**

Run:

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/test_formula_golden.py::test_fast_compute_moves_mixed_formula_golden -v
```

Expected: PASS. If it fails, do not change formulas; correct the expected values only after manually recalculating from the current implementation.

- [ ] **Step 3: Add Vollpalette golden test**

Append this test to `tests/test_formula_golden.py`:

```python

def test_detect_vollpalettes_delivery_hu_golden():
    df_vekp = pd.DataFrame({
        "Internal HU": ["100", "101", "102", "103"],
        "External HU": ["EXT100", "EXT101", "EXT102", "EXT103"],
        "higher-level HU": ["", "100", "", ""],
        "Generated delivery": ["000500", "000500", "000501", "000502"],
        "Packmittel": ["PALETA", "KLT", "PALETA", "CARTON"],
    })
    df_vepo = pd.DataFrame({
        "Internal HU": ["100", "101", "102", "103"],
        "Material": ["MAT-A", "MAT-B", "MAT-C", "MAT-D"],
    })
    df_pick = pd.DataFrame({
        "Delivery": ["000500", "000500", "000501", "000502", "000503"],
        "Removal of total SU": ["X", "X", "X", "X", ""],
        "Storage Unit Type": ["PALETA", "KLT", "PALETA", "CARTON", "PALETA"],
        "Queue": ["PI_PL_FU", "PI_PL_FU", "PI_PL_FU", "PI_PL_FU", "PI_PL_FU"],
        "Source storage unit": ["EXT100", "EXT101", "EXT102", "EXT103", "EXT404"],
        "Handling Unit": ["EXT100", "EXT101", "EXT102", "EXT103", "EXT404"],
    })

    result = detect_vollpalettes(df_pick, df_vekp, df_vepo)

    assert result == {("500", "EXT100"), ("500", "100"), ("501", "EXT102"), ("501", "102")}
```

- [ ] **Step 4: Run Vollpalette golden test**

Run:

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/test_formula_golden.py::test_detect_vollpalettes_delivery_hu_golden -v
```

Expected: PASS.

- [ ] **Step 5: Add MARM dedupe golden test**

Append this test:

```python

def test_raw_marm_dedupe_preserves_material_and_alternative_unit_rows():
    df = pd.DataFrame({
        "Material": ["MAT1", "MAT1", "MAT1", "MAT2"],
        "Alternative Unit of Measure": ["ST", "KAR", "KAR", "ST"],
        "Numerator": [1, 10, 20, 1],
    })

    result = _dedupe_by_table(df, "raw_marm")

    assert len(result) == 3
    assert set(zip(result["Material"], result["Alternative Unit of Measure"])) == {
        ("MAT1", "ST"),
        ("MAT1", "KAR"),
        ("MAT2", "ST"),
    }
    assert result.loc[
        (result["Material"] == "MAT1") & (result["Alternative Unit of Measure"] == "KAR"),
        "Numerator",
    ].iloc[0] == 20
```

This test is expected to FAIL before Task 2 because current dedupe drops by `Material` only.

- [ ] **Step 6: Run MARM golden test and confirm failure**

Run:

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/test_formula_golden.py::test_raw_marm_dedupe_preserves_material_and_alternative_unit_rows -v
```

Expected: FAIL because `raw_marm` currently dedupes only by `Material`. Keep the failure for Task 2.

- [ ] **Step 7: Add Billing smoke golden test with monkeypatched side loaders**

Append this test:

```python

def test_cached_billing_logic_returns_stable_columns_for_minimal_inputs(monkeypatch):
    import modules.tab_billing as billing_module

    monkeypatch.setattr(billing_module, "load_from_db", lambda name: None)

    df_pick = pd.DataFrame({
        "Delivery": ["000500", "000500"],
        "Material": ["MAT-A", "MAT-B"],
        "Queue": ["PI_PL_FU", "PI_PL"],
        "Handling Unit": ["EXT100", "EXT200"],
        "Source storage unit": ["EXT100", "EXT200"],
        "Pohyby_Rukou": [1, 3],
        "Month": ["2026-07", "2026-07"],
    })
    df_vekp = pd.DataFrame({
        "Internal HU": ["100", "200"],
        "External HU": ["EXT100", "EXT200"],
        "Generated delivery": ["000500", "000500"],
        "higher-level HU": ["", ""],
        "Created On": ["2026-07-01", "2026-07-01"],
    })
    df_vepo = pd.DataFrame({
        "Internal HU": ["100", "200"],
        "Material": ["MAT-A", "MAT-B"],
    })
    df_cats = pd.DataFrame({
        "Delivery": ["000500"],
        "Kategorie": ["N"],
        "Art": [""],
    })

    billing_df, hu_details = cached_billing_logic_v28(
        df_pick,
        df_vekp,
        df_vepo,
        df_cats,
        "Transfer Order Number",
        {("500", "EXT100"), ("500", "100")},
    )

    assert isinstance(billing_df, pd.DataFrame)
    assert isinstance(hu_details, pd.DataFrame)
    assert {"Clean_Del", "pocet_hu", "pocet_to", "Bilance", "TO_navic"}.issubset(billing_df.columns)
    assert billing_df["Clean_Del"].astype(str).str.contains("500").any()
```

- [ ] **Step 8: Run complete formula golden file**

Run:

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/test_formula_golden.py -v --tb=short
```

Expected: all tests PASS except the MARM dedupe test from Step 5. That single failure is the TDD driver for Task 2.

- [ ] **Step 9: Commit golden baseline**

Only commit if the only failing test is the expected MARM dedupe test. Use:

```bash
git add tests/test_formula_golden.py
git commit -m "test: add formula golden baseline" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Fix MARM Dedupe Without Changing Other Tables

**Files:**
- Modify: `database.py:367-420`
- Modify: `tests/test_datalayer.py:149-159`
- Modify: `tests/test_formula_golden.py`

**Interfaces:**
- Consumes: `database._dedupe_by_table(df: pd.DataFrame, name: str) -> pd.DataFrame`.
- Produces: `raw_marm` dedupe key `['Material', 'Alternative Unit of Measure']` when both columns exist; `raw_manual` keeps current `['Material']` behavior.

- [ ] **Step 1: Update existing raw_marm unit test expectation**

In `tests/test_datalayer.py`, replace `test_raw_marm_dedupe` with:

```python
    def test_raw_marm_dedupe(self):
        from database import _dedupe_by_table
        import pandas as pd

        df = pd.DataFrame({
            'Material': ['MAT1', 'MAT1', 'MAT1', 'MAT2'],
            'Alternative Unit of Measure': ['ST', 'KAR', 'KAR', 'ST'],
            'Value': [1, 2, 3, 4],
        })
        result = _dedupe_by_table(df, 'raw_marm')
        # MAT1/ST, MAT1/KAR (keep last), MAT2/ST
        assert len(result) == 3
        assert result.loc[
            (result['Material'] == 'MAT1') & (result['Alternative Unit of Measure'] == 'KAR'),
            'Value',
        ].iloc[0] == 3
```

- [ ] **Step 2: Run targeted tests and confirm failure**

Run:

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/test_datalayer.py::TestDedupeByTable::test_raw_marm_dedupe tests/test_formula_golden.py::test_raw_marm_dedupe_preserves_material_and_alternative_unit_rows -v
```

Expected: FAIL because implementation still dedupes by `Material` only.

- [ ] **Step 3: Implement exact MARM dedupe key**

In `database.py`, replace:

```python
        elif name in ['raw_marm', 'raw_manual'] and 'Material' in df.columns:
            df = df.drop_duplicates(subset=['Material'], keep='last')
```

with:

```python
        elif name == 'raw_marm' and 'Material' in df.columns:
            if 'Alternative Unit of Measure' in df.columns:
                df = df.drop_duplicates(
                    subset=['Material', 'Alternative Unit of Measure'],
                    keep='last',
                )
            else:
                df = df.drop_duplicates(subset=['Material'], keep='last')
        elif name == 'raw_manual' and 'Material' in df.columns:
            df = df.drop_duplicates(subset=['Material'], keep='last')
```

- [ ] **Step 4: Run targeted tests**

Run:

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/test_datalayer.py::TestDedupeByTable::test_raw_marm_dedupe tests/test_formula_golden.py::test_raw_marm_dedupe_preserves_material_and_alternative_unit_rows -v
```

Expected: PASS.

- [ ] **Step 5: Run database/formula tests**

Run:

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/test_datalayer.py tests/test_database_edge_cases.py tests/test_formula_golden.py -v --tb=short
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add database.py tests/test_datalayer.py tests/test_formula_golden.py
git commit -m "fix: preserve MARM alternative units during dedupe" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Supabase Error Classification and Retry Safety

**Files:**
- Modify: `database.py:112-172`, `database.py:423-477`
- Modify: `tests/test_datalayer.py`

**Interfaces:**
- Produces: `_is_not_found_error(exc: Exception) -> bool` returns True only for 404/not_found object absence.
- Produces: `_is_non_retryable_client_error(exc: Exception) -> bool` returns True for 400/401/403/429/rate-limit.
- Produces: `_retry_operation(...)` fast-fails both not-found and non-retryable client errors, but only `load_from_db` maps not-found to `None`.

- [ ] **Step 1: Add classification tests**

Append to `tests/test_datalayer.py`:

```python

class TestClientErrorClassification:
    """Auth/config/rate-limit errors must not look like missing files."""

    @pytest.mark.parametrize("text", [
        "{'statusCode': 400, 'error': bad_request}",
        "{'statusCode': 401, 'error': unauthorized}",
        "{'statusCode': 403, 'error': forbidden}",
        "{'statusCode': 429, 'error': too_many_requests}",
        "429 too many requests",
        "rate limit exceeded",
    ])
    def test_client_errors_are_not_not_found(self, text):
        from database import _is_not_found_error
        assert _is_not_found_error(Exception(text)) is False

    @pytest.mark.parametrize("text", [
        "{'statusCode': 400, 'error': bad_request}",
        "{'statusCode': 401, 'error': unauthorized}",
        "{'statusCode': 403, 'error': forbidden}",
        "{'statusCode': 429, 'error': too_many_requests}",
        "429 too many requests",
        "rate limit exceeded",
    ])
    def test_client_errors_are_non_retryable(self, text):
        from database import _is_non_retryable_client_error
        assert _is_non_retryable_client_error(Exception(text)) is True

    def test_404_is_not_found_and_non_retryable(self):
        from database import _is_non_retryable_client_error, _is_not_found_error
        exc = Exception("{'statusCode': 404, 'error': not_found}")
        assert _is_not_found_error(exc) is True
        assert _is_non_retryable_client_error(exc) is True
```

- [ ] **Step 2: Run classification tests and confirm import failure**

Run:

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/test_datalayer.py::TestClientErrorClassification -v
```

Expected: FAIL because `_is_non_retryable_client_error` does not exist and `_is_not_found_error` currently matches 400/401/403/429.

- [ ] **Step 3: Implement classification helpers**

In `database.py`, replace `_is_not_found_error` with:

```python
def _error_text(exc: Exception) -> str:
    """Lowercase text representation for Supabase exception classification."""
    return str(exc).lower()


def _is_not_found_error(exc: Exception) -> bool:
    """Detect only object-not-found / 404 errors from Supabase Storage."""
    exc_str = _error_text(exc)
    return any(marker in exc_str for marker in [
        'statuscode": 404',
        'status_code": 404',
        'statuscode: 404',
        'httpstatuscode": 404',
        '404 not found',
        'object not found',
        'not_found',
    ])


def _is_non_retryable_client_error(exc: Exception) -> bool:
    """Detect client/config/rate-limit errors that should fail fast, not retry."""
    if _is_not_found_error(exc):
        return True
    exc_str = _error_text(exc)
    return any(marker in exc_str for marker in [
        'statuscode": 400', 'status_code": 400', 'statuscode: 400', '400 bad request',
        'statuscode": 401', 'status_code": 401', 'statuscode: 401', '401 unauthorized',
        'statuscode": 403', 'status_code": 403', 'statuscode: 403', '403 forbidden',
        'statuscode": 429', 'status_code": 429', 'statuscode: 429',
        '429 too many requests', 'rate limit', 'too many requests',
    ])
```

- [ ] **Step 4: Update retry fast-fail branch**

In `_retry_operation`, replace:

```python
            if _is_not_found_error(e):
                logger.debug(f"Soubor neexistuje (404) při '{op_name}': {e}")
                raise
```

with:

```python
            if _is_non_retryable_client_error(e):
                logger.debug(f"Neretriovatelná Supabase chyba při '{op_name}': {e}")
                raise
```

- [ ] **Step 5: Update `load_from_db` non-404 message**

In `load_from_db`, keep this branch:

```python
            if _is_not_found_error(dl_err):
                logger.debug(f"Soubor {file_path} neexistuje v Supabase (404)")
                return None
```

After it, replace the generic warning with:

```python
            if _is_non_retryable_client_error(dl_err):
                logger.error(
                    f"Supabase klientská/config chyba při stahování {file_path}: "
                    f"{type(dl_err).__name__}: {dl_err}"
                )
            else:
                logger.warning(
                    f"Chyba při stahování {file_path}: "
                    f"{type(dl_err).__name__}: {dl_err}"
                )
            return None
```

- [ ] **Step 6: Run datalayer tests**

Run:

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/test_datalayer.py -v --tb=short
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add database.py tests/test_datalayer.py
git commit -m "fix: classify Supabase client errors safely" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: App-Level Cache Invalidation and Admin Fail-Closed

**Files:**
- Modify: `app.py:58-66`, `app.py:635-868`, `app.py:1372-1381`, `app.py:1541-1585`
- Create: `tests/test_app_stability.py`

**Interfaces:**
- Produces: `_get_admin_password() -> Optional[str]` returns `None` when not configured.
- Produces: `clear_all_caches() -> None` clears database cache, app cached loaders, and session derived keys.
- Produces: `_is_admin_configured() -> bool` returns whether Admin Zone can accept a password.

- [ ] **Step 1: Write admin fail-closed tests**

Create `tests/test_app_stability.py`:

```python
"""App-level stability tests for cache, admin, export, and tab-order behavior."""
import importlib.util
from pathlib import Path
import sys
import types

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_PATH = PROJECT_ROOT / "app.py"


class DummyContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class DummyProgress:
    def progress(self, *args, **kwargs):
        return None

    def empty(self):
        return None


class DummyStreamlit(types.SimpleNamespace):
    def __init__(self):
        super().__init__()
        self.session_state = {}
        self.secrets = {}
        self.errors = []
        self.warnings = []
        self.download_calls = []

    def cache_data(self, *args, **kwargs):
        def decorator(func):
            func.clear = lambda: None
            return func
        return decorator

    def cache_resource(self, *args, **kwargs):
        def decorator(func):
            func.clear = lambda: None
            return func
        return decorator

    def set_page_config(self, *args, **kwargs):
        return None

    def markdown(self, *args, **kwargs):
        return None

    def error(self, message):
        self.errors.append(message)

    def warning(self, message):
        self.warnings.append(message)

    def info(self, *args, **kwargs):
        return None

    def text_input(self, *args, **kwargs):
        return ""

    def button(self, *args, **kwargs):
        return False

    def checkbox(self, *args, **kwargs):
        return False

    def file_uploader(self, *args, **kwargs):
        return []

    def spinner(self, *args, **kwargs):
        return DummyContext()

    def columns(self, spec):
        count = len(spec) if isinstance(spec, list) else int(spec)
        return [DummyContext() for _ in range(count)]

    def progress(self, *args, **kwargs):
        return DummyProgress()

    def divider(self):
        return None

    def download_button(self, *args, **kwargs):
        self.download_calls.append((args, kwargs))
        return False

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def load_app_module(monkeypatch, fake_st=None):
    fake_st = fake_st or DummyStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    monkeypatch.setitem(sys.modules, "streamlit_option_menu", types.SimpleNamespace(option_menu=lambda *a, **k: ""))
    monkeypatch.setitem(sys.modules, "plotly.express", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "plotly.graph_objects", types.SimpleNamespace())
    spec = importlib.util.spec_from_file_location("app_under_test", APP_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module, fake_st


def test_get_admin_password_returns_none_without_secret(monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    module, _fake_st = load_app_module(monkeypatch)

    assert module._get_admin_password() is None


def test_get_admin_password_reads_env(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "strong-secret")
    module, _fake_st = load_app_module(monkeypatch)

    assert module._get_admin_password() == "strong-secret"
```

- [ ] **Step 2: Run admin tests and confirm failure**

Run:

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/test_app_stability.py::test_get_admin_password_returns_none_without_secret tests/test_app_stability.py::test_get_admin_password_reads_env -v
```

Expected: first test FAIL because `_get_admin_password()` currently returns `admin123`.

- [ ] **Step 3: Change admin password helper**

In `app.py`, replace `_get_admin_password` with:

```python
def _get_admin_password() -> Optional[str]:
    """Admin password from st.secrets or ADMIN_PASSWORD env var.

    Returns None when not configured. Admin Zone must fail closed rather than
    using a public default password.
    """
    try:
        if hasattr(st, "secrets") and "ADMIN_PASSWORD" in st.secrets:
            value = str(st.secrets["ADMIN_PASSWORD"]).strip()
            return value or None
    except Exception:
        pass
    value = os.environ.get("ADMIN_PASSWORD", "").strip()
    return value or None


def _is_admin_configured() -> bool:
    """Whether Admin Zone can accept uploads in this environment."""
    return _get_admin_password() is not None
```

- [ ] **Step 4: Make Admin Zone fail closed**

In `_render_admin_zone`, after `st.info(...)` and before `st.text_input(...)`, insert:

```python
    expected_password = _get_admin_password()
    if expected_password is None:
        st.warning(_t(
            "🔐 Admin zóna je uzamčená: nastavte `ADMIN_PASSWORD` ve Streamlit secrets nebo env vars.",
            "🔐 Admin Zone is locked: set `ADMIN_PASSWORD` in Streamlit secrets or env vars.",
        ))
        return
```

Then replace:

```python
    if admin_pwd and admin_pwd == _get_admin_password():
```

with:

```python
    if admin_pwd and admin_pwd == expected_password:
```

- [ ] **Step 5: Run admin tests**

Run:

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/test_app_stability.py::test_get_admin_password_returns_none_without_secret tests/test_app_stability.py::test_get_admin_password_reads_env -v
```

Expected: PASS.

- [ ] **Step 6: Add cache invalidation test**

Append to `tests/test_app_stability.py`:

```python

def test_clear_all_caches_clears_app_loaders_and_session(monkeypatch):
    module, fake_st = load_app_module(monkeypatch)
    called = []

    def mark(name):
        return lambda: called.append(name)

    monkeypatch.setattr(module, "clear_cache", mark("database.clear_cache"))
    for name in [
        "_load_pick_processed",
        "_load_queue_and_dates",
        "_load_manual_boxes",
        "_load_marm_master",
        "_load_oe_processed",
        "_load_cats_processed",
        "_load_aus_data",
        "_load_pick_enriched",
    ]:
        getattr(module, name).clear = mark(name)

    fake_st.session_state.update({
        "billing_df": pd.DataFrame({"x": [1]}),
        "debug_hu_details": pd.DataFrame({"x": [1]}),
        "_billing_cache": {"hash": 1},
        "data_dict": {"df_pick": pd.DataFrame({"x": [1]})},
        "voll_set": {("1", "HU1")},
        "sidebar_stats": {"rows": "1"},
        "lang": "cs",
    })

    module.clear_all_caches()

    assert "database.clear_cache" in called
    assert "_load_pick_processed" in called
    assert "_load_pick_enriched" in called
    for key in ["billing_df", "debug_hu_details", "_billing_cache", "data_dict", "voll_set", "sidebar_stats"]:
        assert key not in fake_st.session_state
    assert fake_st.session_state["lang"] == "cs"
```

- [ ] **Step 7: Run cache test and confirm failure**

Run:

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/test_app_stability.py::test_clear_all_caches_clears_app_loaders_and_session -v
```

Expected: FAIL because `clear_all_caches` does not exist.

- [ ] **Step 8: Implement `clear_all_caches`**

In `app.py`, after `_load_pick_enriched`, add:

```python
APP_CACHE_LOADERS = (
    _load_pick_processed,
    _load_queue_and_dates,
    _load_manual_boxes,
    _load_marm_master,
    _load_oe_processed,
    _load_cats_processed,
    _load_aus_data,
    _load_pick_enriched,
)

DERIVED_SESSION_KEYS = (
    "billing_df",
    "debug_hu_details",
    "_billing_cache",
    "data_dict",
    "voll_set",
    "sidebar_stats",
    "pipeline_start_ts",
    "_header_last_status",
)


def clear_all_caches() -> None:
    """Clear database, app-level Streamlit caches, and derived session state."""
    try:
        clear_cache()
    except Exception as exc:
        logger.debug(f"database.clear_cache selhal při clear_all_caches: {exc}")

    for loader in APP_CACHE_LOADERS:
        clear_fn = getattr(loader, "clear", None)
        if clear_fn is None:
            continue
        try:
            clear_fn()
        except Exception as exc:
            logger.debug(f"Cache clear selhal pro {getattr(loader, '__name__', loader)}: {exc}")

    for key in DERIVED_SESSION_KEYS:
        try:
            st.session_state.pop(key, None)
        except Exception as exc:
            logger.debug(f"Session key {key} nešel odstranit: {exc}")
```

- [ ] **Step 9: Use `clear_all_caches` in refresh/upload**

In `_render_app_header_bar`, replace:

```python
            clear_cache()
```

with:

```python
            clear_all_caches()
```

In `_render_admin_zone`, replace:

```python
                clear_cache()
```

with:

```python
                clear_all_caches()
```

- [ ] **Step 10: Run app stability tests**

Run:

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/test_app_stability.py -v --tb=short
```

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add app.py tests/test_app_stability.py
git commit -m "fix: fail closed admin and clear app caches" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: One-Pass Vollpalette Handoff

**Files:**
- Modify: `app.py:868-988`
- Modify: `tests/test_app_stability.py`

**Interfaces:**
- Produces: `_load_pick_enriched(use_marm: bool) -> Optional[Tuple[pd.DataFrame, Set[Tuple[str, str]]]]` or a lightweight dict, but preserve external `build_data_dict(...)` shape.
- `build_data_dict(use_marm: bool) -> Optional[Dict[str, Any]]` still returns keys `df_pick`, `voll_set`, `df_vekp`, `df_vepo`, etc.

- [ ] **Step 1: Add test that `build_data_dict` reuses enriched Vollpalette set**

Append to `tests/test_app_stability.py`:

```python

def test_build_data_dict_reuses_voll_set_from_enriched_loader(monkeypatch):
    module, _fake_st = load_app_module(monkeypatch)
    calls = {"detect": 0}

    df_pick = pd.DataFrame({
        "Delivery": ["000500"],
        "Transfer Order Number": ["TO1"],
        "Material": ["MAT1"],
        "Queue": ["PI_PL_FU"],
        "Removal of total SU": ["X"],
        "Box_Sizes_List": [()],
        "Piece_Weight_KG": [0.0],
        "Piece_Max_Dim_CM": [0.0],
    })
    expected_voll = {("500", "HU1")}

    monkeypatch.setattr(module, "_load_pick_enriched", lambda use_marm: (df_pick, expected_voll))
    monkeypatch.setattr(module, "load_from_db", lambda name: pd.DataFrame({"x": [1]}) if name in {"raw_vekp", "raw_vepo"} else None)
    monkeypatch.setattr(module, "_load_oe_processed", lambda: None)
    monkeypatch.setattr(module, "_load_cats_processed", lambda: None)
    monkeypatch.setattr(module, "_load_aus_data", lambda: {})
    monkeypatch.setattr(module, "_load_manual_boxes", lambda: {})
    monkeypatch.setattr(module, "_load_marm_master", lambda: ({}, {}, {}))

    def fake_detect(*args, **kwargs):
        calls["detect"] += 1
        return expected_voll

    monkeypatch.setattr(module, "detect_vollpalettes", fake_detect)

    result = module.build_data_dict(use_marm=True)

    assert result["voll_set"] == expected_voll
    assert calls["detect"] == 0
```

- [ ] **Step 2: Run test and confirm failure**

Run:

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/test_app_stability.py::test_build_data_dict_reuses_voll_set_from_enriched_loader -v
```

Expected: FAIL because `_load_pick_enriched` currently returns only `df_pick` and `build_data_dict` recomputes `detect_vollpalettes`.

- [ ] **Step 3: Change `_load_pick_enriched` return**

In `app.py`, change the function annotation and docstring:

```python
@st.cache_data(show_spinner=False, ttl=300)
def _load_pick_enriched(use_marm: bool) -> Optional[Tuple[pd.DataFrame, Set[Tuple[str, str]]]]:
    """df_pick with Queue, dates, Vollpalette set and box mapping."""
```

At the end of `_load_pick_enriched`, replace:

```python
    return df_pick
```

with:

```python
    return df_pick, voll_set
```

- [ ] **Step 4: Update `build_data_dict` to unwrap tuple and stop duplicate detection**

Replace the start of `build_data_dict`:

```python
    df_pick = _load_pick_enriched(use_marm)
    if df_pick is None or df_pick.empty:
```

with:

```python
    enriched = _load_pick_enriched(use_marm)
    if enriched is None:
        logger.warning("df_pick je prázdný - databáze neinicializovaná")
        return None
    df_pick, voll_set = enriched
    if df_pick is None or df_pick.empty:
```

Then remove this block entirely:

```python
    with ErrorBoundary("Detekce Vollpalet", level="warning"):
        voll_set = detect_vollpalettes(df_pick, df_vekp_raw, df_vepo_raw)
```

Keep loading `df_vekp_raw` and `df_vepo_raw` for Billing/Admins/Audit.

- [ ] **Step 5: Run targeted test**

Run:

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/test_app_stability.py::test_build_data_dict_reuses_voll_set_from_enriched_loader -v
```

Expected: PASS.

- [ ] **Step 6: Run formula/app tests**

Run:

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/test_formula_golden.py tests/test_app_stability.py -v --tb=short
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app.py tests/test_app_stability.py
git commit -m "perf: reuse Vollpalette detection result" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: Central Billing Provider for Tab-Order Independence

**Files:**
- Modify: `modules/tab_billing.py:20-24`, `modules/tab_billing.py:541-632`
- Modify: `app.py:1730-1808`, `app.py:1837-1847`
- Modify: `tests/test_app_stability.py`

**Interfaces:**
- Produces: `modules.tab_billing.make_billing_cache_key(df_pick, df_vekp, df_vepo, df_cats, queue_count_col, voll_set) -> tuple`.
- Produces: `modules.tab_billing.compute_billing_result(df_pick, df_vekp, df_vepo, df_cats, queue_count_col, voll_set=None) -> tuple[pd.DataFrame, pd.DataFrame]`.
- `render_billing(...)` consumes `compute_billing_result` and still returns `billing_df`.
- `app.py` produces `_get_or_compute_billing(df_pick, data_dict) -> tuple[pd.DataFrame, pd.DataFrame]`.

- [ ] **Step 1: Add provider tests**

Append to `tests/test_app_stability.py`:

```python

def test_get_or_compute_billing_populates_session_without_billing_tab(monkeypatch):
    module, fake_st = load_app_module(monkeypatch)
    billing_df = pd.DataFrame({"Clean_Del": ["500"], "Bilance": [0]})
    hu_details = pd.DataFrame({"Clean_Del": ["500"], "HU": ["HU1"]})

    fake_billing_module = types.SimpleNamespace(
        compute_billing_result=lambda *args, **kwargs: (billing_df, hu_details)
    )
    monkeypatch.setitem(sys.modules, "modules.tab_billing", fake_billing_module)

    df_pick = pd.DataFrame({"Delivery": ["000500"]})
    data_dict = {
        "df_vekp": pd.DataFrame({"x": [1]}),
        "df_vepo": pd.DataFrame({"x": [1]}),
        "df_cats": pd.DataFrame({"x": [1]}),
        "queue_count_col": "Delivery",
        "voll_set": {("500", "HU1")},
    }

    got_billing, got_details = module._get_or_compute_billing(df_pick, data_dict)

    pd.testing.assert_frame_equal(got_billing, billing_df)
    pd.testing.assert_frame_equal(got_details, hu_details)
    pd.testing.assert_frame_equal(fake_st.session_state["billing_df"], billing_df)
    pd.testing.assert_frame_equal(fake_st.session_state["debug_hu_details"], hu_details)
```

- [ ] **Step 2: Run provider test and confirm failure**

Run:

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/test_app_stability.py::test_get_or_compute_billing_populates_session_without_billing_tab -v
```

Expected: FAIL because `_get_or_compute_billing` does not exist.

- [ ] **Step 3: Add Billing cache key and compute provider**

In `modules/tab_billing.py`, below `fast_render`, add:

```python
def make_billing_cache_key(df_pick, df_vekp, df_vepo, df_cats, queue_count_col, voll_set):
    """Stable lightweight key for session-level Billing memoization."""
    try:
        return (
            id(df_pick), len(df_pick) if df_pick is not None else 0,
            id(df_vekp), len(df_vekp) if df_vekp is not None else 0,
            id(df_vepo), len(df_vepo) if df_vepo is not None else 0,
            id(df_cats), len(df_cats) if df_cats is not None else 0,
            queue_count_col,
            len(voll_set) if voll_set else 0,
            hash(frozenset(voll_set)) if voll_set else 0,
        )
    except Exception:
        return None


def compute_billing_result(df_pick, df_vekp, df_vepo, df_cats, queue_count_col, voll_set=None):
    """Compute or retrieve Billing result without requiring the Billing tab UI."""
    voll_set = voll_set or st.session_state.get('voll_set', set()) or set()
    input_hash = make_billing_cache_key(df_pick, df_vekp, df_vepo, df_cats, queue_count_col, voll_set)
    cached = st.session_state.get('_billing_cache')
    if cached and input_hash is not None and cached.get('hash') == input_hash:
        logger.info("Billing cache HIT - provider")
        return cached['billing_df'], cached['hu_details']

    logger.info("Billing cache MISS - provider")
    billing_df, df_hu_details = cached_billing_logic_v28(
        df_pick, df_vekp, df_vepo, df_cats, queue_count_col, voll_set
    )
    if input_hash is not None:
        st.session_state['_billing_cache'] = {
            'hash': input_hash,
            'billing_df': billing_df,
            'hu_details': df_hu_details,
        }
    return billing_df, df_hu_details
```

- [ ] **Step 4: Refactor `render_billing` to use provider**

In `render_billing`, replace the manual `input_hash` / `cached` / `cached_billing_logic_v28` block from the `voll_set = ...` line through the `except Exception as e:` block with:

```python
        voll_set = st.session_state.get('voll_set', set()) or set()
        try:
            billing_df, df_hu_details = compute_billing_result(
                df_pick, df_vekp, df_vepo, df_cats, queue_count_col, voll_set
            )
        except Exception as e:
            st.error(f"❌ Kritická chyba v Billing Logic: {e}")
            import traceback
            with st.expander("🔧 Detaily"):
                st.code(traceback.format_exc(), language="python")
            return pd.DataFrame()
```

Keep the month filter and session assignments after the provider call.

- [ ] **Step 5: Add app provider**

In `app.py`, before `_route_to_page`, add:

```python
def _get_or_compute_billing(df_pick: pd.DataFrame, data_dict: dict) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Return Billing result for tabs that need it before Billing tab is visited."""
    from modules.tab_billing import compute_billing_result

    billing_df, hu_details = compute_billing_result(
        df_pick,
        data_dict.get('df_vekp'),
        data_dict.get('df_vepo'),
        data_dict.get('df_cats'),
        data_dict.get('queue_count_col', 'Delivery'),
        data_dict.get('voll_set') or st.session_state.get('voll_set', set()) or set(),
    )
    st.session_state['billing_df'] = billing_df
    st.session_state['debug_hu_details'] = hu_details
    return billing_df, hu_details
```

- [ ] **Step 6: Use provider for dependent tabs**

In `_route_to_page`, replace FU Compare route with:

```python
        _t("Porovnání (FU vs SAP)", "Compare (FU vs SAP)"):
            lambda: _safe_render_fu_compare(df_pick, data_dict),
```

Replace Packing route with:

```python
        _t("Balení (Packing)", "Packing"):
            lambda: _safe_render_packing(df_pick, data_dict),
```

Replace Board route with:

```python
        _t("Nástěnka (Tisk grafů)", "Notice Board (Print)"):
            lambda: _safe_render_board(df_pick, data_dict),
```

Add wrappers near `_safe_render_billing`:

```python
def _safe_render_fu_compare(df_pick, data_dict):
    try:
        billing_df, _hu_details = _get_or_compute_billing(df_pick, data_dict)
        _safe_render_tab(
            "fu_compare", "render_fu_compare",
            df_pick, billing_df, data_dict.get('voll_set'), data_dict['queue_count_col'],
        )
    except Exception as e:
        logger.exception("Chyba ve FU Compare")
        st.error(f"⚠️ Chyba v Porovnání FU vs SAP: {e}")


def _safe_render_packing(df_pick, data_dict):
    try:
        billing_df, _hu_details = _get_or_compute_billing(df_pick, data_dict)
        _safe_render_tab("packing", "render_packing", billing_df, data_dict['df_oe'])
    except Exception as e:
        logger.exception("Chyba v Packing")
        st.error(f"⚠️ Chyba v Balení: {e}")


def _safe_render_board(df_pick, data_dict):
    try:
        billing_df, _hu_details = _get_or_compute_billing(df_pick, data_dict)
        _safe_render_tab("board", "render_board", df_pick, billing_df)
    except Exception as e:
        logger.exception("Chyba v Notice Board")
        st.error(f"⚠️ Chyba v Nástěnce: {e}")
```

- [ ] **Step 7: Run app stability provider test**

Run:

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/test_app_stability.py::test_get_or_compute_billing_populates_session_without_billing_tab -v
```

Expected: PASS.

- [ ] **Step 8: Run Billing/formula/app tests**

Run:

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/test_formula_golden.py tests/test_app_stability.py -v --tb=short
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add app.py modules/tab_billing.py tests/test_app_stability.py
git commit -m "fix: compute Billing for dependent tabs" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: Lazy Excel Export

**Files:**
- Modify: `app.py:1203-1205`, `app.py:1853-1910`
- Modify: `tests/test_app_stability.py`

**Interfaces:**
- Produces: `_build_excel_export_bytes(df_pick: pd.DataFrame, data_dict: dict) -> bytes`.
- `_render_excel_export(df_pick, data_dict)` displays a prepare button and calls `_build_excel_export_bytes` only when clicked.

- [ ] **Step 1: Add lazy export test**

Append to `tests/test_app_stability.py`:

```python

def test_render_excel_export_does_not_build_workbook_before_click(monkeypatch):
    module, fake_st = load_app_module(monkeypatch)
    built = {"count": 0}

    def fake_build(df_pick, data_dict):
        built["count"] += 1
        return b"xlsx-bytes"

    monkeypatch.setattr(module, "_build_excel_export_bytes", fake_build, raising=False)
    fake_st.button = lambda *args, **kwargs: False

    module._render_excel_export(pd.DataFrame({"Material": ["A"]}), {"num_removed_admins": 0})

    assert built["count"] == 0
    assert fake_st.download_calls == []


def test_render_excel_export_builds_after_click(monkeypatch):
    module, fake_st = load_app_module(monkeypatch)
    built = {"count": 0}

    def fake_build(df_pick, data_dict):
        built["count"] += 1
        return b"xlsx-bytes"

    monkeypatch.setattr(module, "_build_excel_export_bytes", fake_build, raising=False)
    fake_st.button = lambda *args, **kwargs: True

    module._render_excel_export(pd.DataFrame({"Material": ["A"]}), {"num_removed_admins": 0})

    assert built["count"] == 1
    assert len(fake_st.download_calls) == 1
```

- [ ] **Step 2: Run export tests and confirm failure**

Run:

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/test_app_stability.py::test_render_excel_export_does_not_build_workbook_before_click tests/test_app_stability.py::test_render_excel_export_builds_after_click -v
```

Expected: FAIL because `_render_excel_export` currently builds immediately.

- [ ] **Step 3: Extract workbook builder**

Replace `_render_excel_export` with two functions:

```python
def _build_excel_export_bytes(df_pick: pd.DataFrame, data_dict: dict) -> bytes:
    """Build complete Excel report bytes. Expensive: call only on explicit user action."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        limits = st.session_state.get('algorithm_limits', {})
        pd.DataFrame({
            "Parameter": ["Weight Limit", "Dim Limit", "Grab limit", "Admins Excluded"],
            "Value": [f"{limits.get('vaha', 2.0)} kg",
                      f"{limits.get('rozmer', 15.0)} cm",
                      f"{limits.get('hrst', 1)} pcs",
                      data_dict['num_removed_admins']]
        }).to_excel(writer, index=False, sheet_name='Settings')

        if 'Pohyby_Rukou' in df_pick.columns and not df_pick.empty:
            mat_summary = df_pick.groupby('Material', observed=True).agg(
                Moves=('Pohyby_Rukou', 'sum'),
                Qty=('Qty', 'sum'),
                Exact=('Pohyby_Exact', 'sum'),
                Estimates=('Pohyby_Loose_Miss', 'sum'),
                Lines=('Material', 'count')
            ).reset_index().sort_values('Moves', ascending=False)
            mat_summary.to_excel(writer, index=False, sheet_name='Material_Totals')

            try:
                queue_col = 'Queue'
                df_pal_exp = df_pick[
                    df_pick[queue_col].astype(str).str.upper().isin(['PI_PL', 'PI_PL_OE'])
                ].groupby('Delivery', observed=True).agg(
                    num_materials=('Material', 'nunique'),
                    material=('Material', 'first'),
                    total_qty=('Qty', 'sum'),
                    total_moves=('Pohyby_Rukou', 'sum'),
                    exact_moves=('Pohyby_Exact', 'sum'),
                    estimated_moves=('Pohyby_Loose_Miss', 'sum'),
                    order_weight=('Celkova_Vaha_KG', 'sum'),
                    max_dim=('Piece_Max_Dim_CM', 'first')
                ).reset_index()
                df_pal_single = df_pal_exp[df_pal_exp['num_materials'] == 1].copy()
                if not df_pal_single.empty:
                    df_pal_single.to_excel(writer, index=False, sheet_name='Single_Material_Orders')
            except Exception as e:
                logger.warning(f"Export pallet orders selhal: {e}")
    return buffer.getvalue()


def _render_excel_export(df_pick: pd.DataFrame, data_dict: dict):
    """Render lazy Excel export controls without building workbook on every rerun."""
    st.info(_t(
        "Excel export se připraví až po kliknutí, aby běžné přepínání záložek nezatěžovalo paměť.",
        "Excel export is prepared only after clicking, so normal tab navigation does not use extra memory.",
    ))
    if not st.button(_t("📦 Připravit Excel export", "📦 Prepare Excel export"), key="prepare_excel_export"):
        return

    try:
        with st.spinner(_t("Připravuji Excel export...", "Preparing Excel export...")):
            export_bytes = _build_excel_export_bytes(df_pick, data_dict)
        st.download_button(
            label=_t("⬇️ Stáhnout kompletní Excel report", "⬇️ Download Complete Excel Report"),
            data=export_bytes,
            file_name=f"Warehouse_Control_Tower_{time.strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            width="stretch"
        )
    except Exception as e:
        logger.exception("Chyba při generování Excel exportu")
        st.warning(f"⚠️ Excel export selhal: {e}")
```

- [ ] **Step 4: Run export tests**

Run:

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/test_app_stability.py::test_render_excel_export_does_not_build_workbook_before_click tests/test_app_stability.py::test_render_excel_export_builds_after_click -v
```

Expected: PASS.

- [ ] **Step 5: Run app tests**

Run:

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/test_app_stability.py -v --tb=short
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_app_stability.py
git commit -m "perf: build Excel export on demand" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: Formula-Preserving Movement Performance Cleanup

**Files:**
- Modify: `modules/utils.py:388-489`
- Modify: `tests/test_performance_regression.py`

**Interfaces:**
- `fast_compute_moves(...)` keeps the same public signature and returns `tuple[list[int], list[int], list[int]]`.
- Internal implementation may return arrays temporarily but must convert to lists before returning.

- [ ] **Step 1: Add parity and performance test for repeated box tuples**

Append to `tests/test_performance_regression.py`:

```python

def test_fast_compute_moves_repeated_box_tuples_200k_under_4_seconds():
    n = 200_000
    qty_arr = [105, 12, 10, 7] * (n // 4)
    queue_arr = ["PI_PL", "PI_PL", "PI_PL", "PI_PL"] * (n // 4)
    su_arr = ["", "", "", ""] * (n // 4)
    boxes_arr = [(10,), (10,), (), (5, 2)] * (n // 4)
    weight_arr = [0.5, 0.5, 0.5, 3.0] * (n // 4)
    dim_arr = [5.0, 20.0, 5.0, 5.0] * (n // 4)

    start = time.time()
    total, exact, miss = fast_compute_moves(
        qty_arr, queue_arr, su_arr, boxes_arr, weight_arr, dim_arr, 2.0, 15.0, 5
    )
    elapsed = time.time() - start

    assert total[:8] == [11, 3, 2, 2, 11, 3, 2, 2]
    assert exact[:8] == [11, 3, 0, 2, 11, 3, 0, 2]
    assert miss[:8] == [0, 0, 2, 0, 0, 0, 2, 0]
    assert elapsed < 4.0, f"200k repeated tuple rows took {elapsed:.2f}s"
```

- [ ] **Step 2: Run performance test baseline**

Run:

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/test_performance_regression.py::test_fast_compute_moves_repeated_box_tuples_200k_under_4_seconds -v
```

Expected: PASS or FAIL depending on machine. If PASS, still implement only low-risk cleanup; if FAIL, use it as performance driver.

- [ ] **Step 3: Apply low-risk return conversion cleanup**

In `fast_compute_moves`, replace early return:

```python
    if not other_mask.any():
        return total.tolist(), exact.tolist(), miss.tolist()
```

Keep it as-is for compatibility.

Then add this small helper above `fast_compute_moves`:

```python
def _normalize_box_tuple(boxes) -> Tuple[int, ...]:
    """Normalize box sizes to a positive >1 integer tuple for movement calculation."""
    if not isinstance(boxes, (list, tuple)):
        return ()
    return tuple(int(b) for b in boxes if b and b > 1)
```

Inside the row loop replace:

```python
        boxes = boxes_arr[idx] if boxes_arr[idx] is not None else ()

        if not isinstance(boxes, (list, tuple)):
            boxes = ()

        real_boxes = tuple(b for b in boxes if b and b > 1)
```

with:

```python
        boxes = boxes_arr[idx] if boxes_arr[idx] is not None else ()
        real_boxes = _normalize_box_tuple(boxes)
```

This is a readability cleanup; do not add caching yet unless tests show performance regression.

- [ ] **Step 4: Run formula and performance tests**

Run:

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/test_utils.py tests/test_formula_golden.py tests/test_performance_regression.py -v --tb=short
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add modules/utils.py tests/test_performance_regression.py
git commit -m "perf: guard movement formula performance" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 9: Documentation and Operator Runbook

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-07-07-full-history-stabilization-design.md` only if implementation changes the plan materially.

**Interfaces:**
- Produces documented commands and behavior for full-history default, Admin password, refresh, lazy export, and verification.

- [ ] **Step 1: Add README section**

Add this section near deployment/setup instructions in `README.md`:

````markdown
## Stability notes for full-history mode

The app intentionally opens in full-history mode. To keep that stable as more
monthly SAP data is appended:

- Admin uploads require `ADMIN_PASSWORD`; there is no default password.
- Use the header **Refresh** button after uploads to clear database, app, Billing,
  and derived session caches.
- Excel export is generated only after clicking **Prepare Excel export**. Normal
  tab navigation does not build an `.xlsx` workbook in memory.
- Supabase 401/403/429/configuration errors are treated as operational errors,
  not as empty data.
- Formula-critical logic is protected by golden tests in `tests/test_formula_golden.py`.

Local verification before pushing:

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests -v --tb=short
PYTHONIOENCODING=utf-8 python -m pytest tests --cov=modules --cov=database --cov-report=term --cov-report=xml -v
PYTHONIOENCODING=utf-8 python -m compileall -q app.py database.py modules tests
streamlit run app.py --server.headless true --server.port 8501
```
````

- [ ] **Step 2: Run docs-adjacent checks**

Run:

```bash
PYTHONIOENCODING=utf-8 python -m compileall -q app.py database.py modules tests
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add README.md docs/superpowers/specs/2026-07-07-full-history-stabilization-design.md
git commit -m "docs: document full-history stability operations" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

If the spec file did not change, omit it from `git add`.

---

### Task 10: Full Verification, Reviews, and Push

**Files:**
- No planned source edits unless review findings require fixes.
- May modify any touched file to address verified review findings.

**Interfaces:**
- Produces a branch pushed to GitHub: `stabilize-full-history-performance`.

- [ ] **Step 1: Run complete unit suite**

Run:

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests -v --tb=short
```

Expected: PASS.

- [ ] **Step 2: Run coverage gate**

Run:

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests --cov=modules --cov=database --cov-report=term --cov-report=xml -v
```

Expected: PASS. Do not fail the task solely on coverage percentage unless CI has an explicit threshold; record the percentage.

- [ ] **Step 3: Run compileall**

Run:

```bash
PYTHONIOENCODING=utf-8 python -m compileall -q app.py database.py modules tests
```

Expected: PASS with no output.

- [ ] **Step 4: Run runtime smoke**

Run in background:

```bash
streamlit run app.py --server.headless true --server.port 8501
```

Then verify health:

```bash
python - <<'PY'
import urllib.request
print(urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=10).read().decode())
PY
```

Expected: health response contains `ok` or HTTP 200 body. Stop the Streamlit process after the check.

- [ ] **Step 5: Run mandatory code review agents**

Because this is a Python project and code was modified, run:

- `ecc:python-reviewer` on the current diff.
- `ecc:code-reviewer` on the current diff.
- `ecc:performance-optimizer` if performance-sensitive code changed.
- `ecc:security-reviewer` because Admin/Supabase auth handling changed.

Required outcome: fix confirmed findings or explicitly record why a finding is not applicable.

- [ ] **Step 6: Run final git checks**

Run:

```bash
git status --short
git log --oneline -5
```

Expected: clean or only intentional uncommitted review fixes before final commit.

- [ ] **Step 7: Commit review fixes if any**

If review fixes changed files:

```bash
git add app.py database.py modules tests README.md docs
git commit -m "fix: address stabilization review findings" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

- [ ] **Step 8: Push branch**

Run:

```bash
git push -u origin stabilize-full-history-performance
```

Expected: branch pushed successfully.

- [ ] **Step 9: Report final status**

Report:

- branch name,
- commits created,
- tests and smoke commands run with result,
- review agents run and findings status,
- any skipped items or known risks.

---

## Self-Review

- Spec coverage: formula baseline, P0 stability, error handling, cache invalidation, lazy export, tab-order Billing, performance guards, documentation, review, and push are covered.
- Storage redesign: intentionally not implemented in this first plan as a destructive migration. The plan stabilizes current monolithic storage and documents the chunk/manifest direction; a separate plan should implement storage migration after these gates pass.
- Placeholder scan: no TBD/TODO placeholders; code snippets and commands are concrete.
- Type consistency: public signatures remain stable except `_load_pick_enriched`, which is internal and unwrapped immediately in `build_data_dict`; external `build_data_dict` shape stays stable.
