"""
Testy pro database.py - Supabase Storage wrapper.

Pokrývá:
- _is_not_found_error detekce
- _retry_operation chování (bez skutečného Supabase)
- _dedupe_by_table logika
"""
import pytest
from unittest.mock import MagicMock, patch

# Mockujeme Supabase před importem database
import sys
from unittest.mock import MagicMock
supabase_mock = MagicMock()
sys.modules['supabase'] = MagicMock()
sys.modules['supabase'].create_client = lambda url, key: MagicMock()


class TestIsNotFoundError:
    """Testy pro detekci 404 chyb."""

    def test_statuscode_404(self):
        from database import _is_not_found_error
        exc = Exception("{'statusCode': 404, 'error': not_found}")
        assert _is_not_found_error(exc) is True

    def test_not_found_keyword(self):
        from database import _is_not_found_error
        exc = Exception("Object not found")
        assert _is_not_found_error(exc) is True

    def test_error_not_found_value(self):
        from database import _is_not_found_error
        exc = Exception('"error": "not_found"')
        assert _is_not_found_error(exc) is True

    def test_normal_error_not_matched(self):
        from database import _is_not_found_error
        exc = Exception("Connection timeout")
        assert _is_not_found_error(exc) is False

    def test_other_status_code(self):
        from database import _is_not_found_error
        exc = Exception("{'statusCode': 500, 'error': internal_server_error}")
        assert _is_not_found_error(exc) is False


class TestRetryOperation:
    """Testy pro retry logiku (bez skutečného Supabase)."""

    def test_success_first_try(self):
        """Úspěch na první pokus - žádný retry."""
        from database import _retry_operation

        call_count = [0]

        def op():
            call_count[0] += 1
            return "OK"

        result = _retry_operation(op)
        assert result == "OK"
        assert call_count[0] == 1

    def test_404_no_retry(self):
        """404 Not Found - OKAMŽITĚ bez retry."""
        from database import _retry_operation, _is_not_found_error

        call_count = [0]

        def op_404():
            call_count[0] += 1
            raise Exception("{'statusCode': 404, 'error': not_found}")

        with pytest.raises(Exception):
            _retry_operation(op_404)

        # DŮLEŽITÉ: 404 se NESMÍ retryovat - jen 1 pokus
        assert call_count[0] == 1

    def test_other_error_retries(self):
        """Jiná chyba - 3 pokusy s backoff."""
        from database import _retry_operation
        import time

        call_count = [0]

        def op_fails():
            call_count[0] += 1
            raise ConnectionError("Network timeout")

        start = time.time()
        with pytest.raises(ConnectionError):
            _retry_operation(op_fails, max_retries=3)
        elapsed = time.time() - start

        # Měly by být 3 pokusy + 2 backoff pauzy (1s + 2s = 3s)
        assert call_count[0] == 3
        # Tolerance kvůli rychlosti
        assert elapsed >= 2.5, f"Backoff příliš krátký: {elapsed:.2f}s"

    def test_success_after_retries(self):
        """Úspěch po několika pokusech."""
        from database import _retry_operation

        call_count = [0]

        def op_flaky():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ConnectionError("Flaky")
            return "OK"

        result = _retry_operation(op_flaky, max_retries=3)
        assert result == "OK"
        assert call_count[0] == 3


class TestDedupeByTable:
    """Testy pro dedupikační logiku podle typu tabulky."""

    def test_raw_pick_dedupe(self):
        from database import _dedupe_by_table
        import pandas as pd

        df = pd.DataFrame({
            'Transfer Order Number': ['1', '1', '1', '2'],
            'Material': ['A', 'A', 'B', 'C'],
            'Confirmation date': ['2025-01-01', '2025-01-01', '2025-01-01', '2025-01-02'],
            'Confirmation time': ['10:00', '10:00', '11:00', '12:00'],
        })
        result = _dedupe_by_table(df, 'raw_pick')
        # Mělo by být 3 řádky (1+2 duplikát, 2, 3)
        assert len(result) == 3

    def test_raw_vekp_dedupe(self):
        from database import _dedupe_by_table
        import pandas as pd

        df = pd.DataFrame({
            'Handling Unit': ['HU1', 'HU1', 'HU2', 'HU3'],
            'Other': ['a', 'b', 'c', 'd'],
        })
        result = _dedupe_by_table(df, 'raw_vekp')
        # HU1 se deduplikuje (keep last)
        assert len(result) == 3

    def test_raw_marm_dedupe(self):
        from database import _dedupe_by_table
        import pandas as pd

        df = pd.DataFrame({
            'Material': ['MAT1', 'MAT1', 'MAT2'],
            'Value': [1, 2, 3],
        })
        result = _dedupe_by_table(df, 'raw_marm')
        assert len(result) == 2

    def test_unknown_table_fallback(self):
        """Neznámý typ - obecná dedupikace."""
        from database import _dedupe_by_table
        import pandas as pd

        df = pd.DataFrame({
            'A': [1, 1, 2, 2, 3],
            'B': ['x', 'x', 'y', 'y', 'z'],
        })
        result = _dedupe_by_table(df, 'unknown_table_xyz')
        # keep last = 3 unikátní řádky
        assert len(result) == 3

    def test_empty_dataframe(self):
        from database import _dedupe_by_table
        import pandas as pd

        df = pd.DataFrame()
        result = _dedupe_by_table(df, 'raw_pick')
        assert len(result) == 0