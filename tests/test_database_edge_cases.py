"""
Edge case testy pro database.py - Parquet serializace a cache.

Pokrývá:
- _df_to_optimized_parquet - správně komprimuje data
- _df_from_parquet - správně čte data zpět (round-trip)
- Edge cases: prázdné DataFrames, sloupce s NaN, velké DataFrames
- Cache invalidation po clear_cache()
"""
import time
import numpy as np
import pandas as pd
import pytest

import database as db_module
from database import (
    _df_to_optimized_parquet,
    _df_from_parquet,
    clear_cache,
    load_from_db,
)


# ==========================================
# TESTY: _df_to_optimized_parquet
# ==========================================
class TestDfToOptimizedParquet:
    """Testy pro serializaci DataFrame -> Parquet bytes."""

    def test_returns_bytes(self):
        """Výstup musí být bytes."""
        df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        out = _df_to_optimized_parquet(df)
        assert isinstance(out, bytes)
        assert len(out) > 0

    def test_compression_active(self):
        """Výstup nesmí být větší než nekomprimovaný vstup - musí být aktivní komprese."""
        # Opakující se data jsou dobře komprimovatelná
        df = pd.DataFrame({
            "x": ["A"] * 1000,
            "y": [1] * 1000,
            "z": ["B"] * 1000,
        })
        compressed = _df_to_optimized_parquet(df)
        # Čistý opakující se text - komprimovaný by měl být výrazně menší než surový vstup
        raw_size = df.memory_usage(deep=True).sum()
        assert len(compressed) < raw_size

    def test_contains_parquet_magic(self):
        """Parquet soubor musí začínat magickými bytes 'PAR1'."""
        df = pd.DataFrame({"a": [1, 2, 3]})
        out = _df_to_optimized_parquet(df)
        # Parquet formát začíná i končí magic 'PAR1'
        assert out[:4] == b"PAR1"
        assert out[-4:] == b"PAR1"

    def test_various_dtypes(self):
        """Různé datové typy by měly projít bez chyby."""
        df = pd.DataFrame({
            "int_col": pd.array([1, 2, 3], dtype="int32"),
            "float_col": pd.array([1.1, 2.2, 3.3], dtype="float32"),
            "str_col": pd.array(["a", "b", "c"], dtype="object"),
            "bool_col": pd.array([True, False, True], dtype="bool"),
        })
        out = _df_to_optimized_parquet(df)
        assert isinstance(out, bytes)
        assert len(out) > 0

    def test_preserves_column_order(self):
        """Pořadí sloupců musí zůstat zachováno."""
        df = pd.DataFrame({
            "z_col": [1, 2],
            "a_col": [3, 4],
            "m_col": [5, 6],
        })
        out = _df_to_optimized_parquet(df)
        roundtripped = _df_from_parquet(out)
        assert list(roundtripped.columns) == ["z_col", "a_col", "m_col"]

    def test_no_index_persisted(self):
        """Index se neukládá (index=False)."""
        df = pd.DataFrame({"a": [1, 2, 3]}, index=[10, 20, 30])
        out = _df_to_optimized_parquet(df)
        rt = _df_from_parquet(out)
        # Index by měl být výchozí RangeIndex, ne [10, 20, 30]
        assert list(rt.index) == [0, 1, 2]


# ==========================================
# TESTY: _df_from_parquet
# ==========================================
class TestDfFromParquet:
    """Testy pro deserializaci Parquet bytes -> DataFrame."""

    def test_returns_dataframe(self):
        df = pd.DataFrame({"a": [1, 2, 3]})
        out = _df_to_optimized_parquet(df)
        rt = _df_from_parquet(out)
        assert isinstance(rt, pd.DataFrame)

    def test_roundtrip_basic(self):
        """Základní round-trip - data se vrátí identická."""
        df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        out = _df_to_optimized_parquet(df)
        rt = _df_from_parquet(out)
        pd.testing.assert_frame_equal(df, rt, check_dtype=False)

    def test_roundtrip_with_nan(self):
        """Round-trip zachová NaN hodnoty."""
        df = pd.DataFrame({"a": [1.0, np.nan, 3.0], "b": ["x", None, "z"]})
        out = _df_to_optimized_parquet(df)
        rt = _df_from_parquet(out)
        # Numerické NaN
        assert pd.isna(rt.loc[1, "a"])
        # Object None - může být None nebo NaN podle pyarrow
        assert pd.isna(rt.loc[1, "b"])

    def test_invalid_bytes_raises(self):
        """Neplatná data by měla vyhodit výjimku."""
        with pytest.raises(Exception):
            _df_from_parquet(b"NOT A PARQUET FILE")


# ==========================================
# TESTY: Edge cases
# ==========================================
class TestEdgeCases:
    """Edge case testy."""

    def test_empty_dataframe(self):
        """Prázdný DataFrame: _df_to_optimized_parquet vrací prázdné bytes, _df_from_parquet vrací prázdný DF.
        Skutečné chování: empty DF -> b'' (log warning) -> _df_from_parquet -> prázdný DF bez sloupců.
        """
        df = pd.DataFrame({"a": [], "b": []})
        out = _df_to_optimized_parquet(df)
        assert isinstance(out, bytes)
        # Prázdný vstup vrací prázdné bytes (kvůli ochraně před pádem pyarrow)
        assert len(out) == 0
        rt = _df_from_parquet(out)
        assert isinstance(rt, pd.DataFrame)
        assert len(rt) == 0

    def test_single_row(self):
        """DataFrame s jedním řádkem."""
        df = pd.DataFrame({"a": [42], "b": ["hello"]})
        out = _df_to_optimized_parquet(df)
        rt = _df_from_parquet(out)
        assert len(rt) == 1
        assert rt.loc[0, "a"] == 42

    def test_large_dataframe(self):
        """Velký DataFrame (50k řádků) by měl projít rychle."""
        n = 50_000
        df = pd.DataFrame({
            "id": np.arange(n),
            "value": np.random.randn(n),
            "category": np.random.choice(["A", "B", "C", "D"], n),
            "flag": np.random.choice([True, False], n),
        })
        start = time.time()
        out = _df_to_optimized_parquet(df)
        rt = _df_from_parquet(out)
        elapsed = time.time() - start
        assert len(rt) == n
        # Round-trip musí trvat < 5 sekund
        assert elapsed < 5.0, f"Round-trip trval {elapsed:.2f}s, > 5s"

    def test_dataframe_with_all_nan_column(self):
        """Sloupec se samými NaN hodnotami."""
        df = pd.DataFrame({
            "a": [1, 2, 3],
            "all_nan": [np.nan, np.nan, np.nan],
        })
        out = _df_to_optimized_parquet(df)
        rt = _df_from_parquet(out)
        assert rt["all_nan"].isna().all()

    def test_mixed_nan_values(self):
        """Sloupec se směsí NaN a reálných hodnot."""
        df = pd.DataFrame({
            "a": [1.0, np.nan, 3.0, np.nan, 5.0],
            "b": [np.nan, "x", np.nan, "y", np.nan],
        })
        out = _df_to_optimized_parquet(df)
        rt = _df_from_parquet(out)
        assert pd.isna(rt.loc[1, "a"])
        assert rt.loc[0, "a"] == 1.0
        assert rt.loc[4, "a"] == 5.0

    def test_unicode_strings(self):
        """Unicode (diakritika) by měla projít bez ztráty."""
        df = pd.DataFrame({
            "cs": ["Příliš žluťoučký kůň", "úpěl ďábelské ódy", "Test 123"],
        })
        out = _df_to_optimized_parquet(df)
        rt = _df_from_parquet(out)
        assert rt.loc[0, "cs"] == "Příliš žluťoučký kůň"
        assert rt.loc[1, "cs"] == "úpěl ďábelské ódy"

    def test_very_wide_dataframe(self):
        """Široký DataFrame (50 sloupců)."""
        data = {f"col_{i}": np.arange(10) for i in range(50)}
        df = pd.DataFrame(data)
        out = _df_to_optimized_parquet(df)
        rt = _df_from_parquet(out)
        assert rt.shape == (10, 50)
        assert list(rt.columns) == list(df.columns)

    def test_dataframe_with_datetime(self):
        """Datové typy datetime/timestamp."""
        df = pd.DataFrame({
            "dt": pd.to_datetime(["2024-01-01", "2024-06-15", "2025-12-31"]),
            "val": [1, 2, 3],
        })
        out = _df_to_optimized_parquet(df)
        rt = _df_from_parquet(out)
        assert len(rt) == 3
        assert pd.api.types.is_datetime64_any_dtype(rt["dt"])


# ==========================================
# TESTY: Cache invalidation
# ==========================================
class TestCacheInvalidation:
    """Testy pro cache clearing."""

    def test_clear_cache_no_supabase(self):
        """clear_cache() by měl projít i bez aktivního Supabase připojení."""
        # Nenastavujeme Supabase klienta - clear_cache by měl bezpečně projít
        try:
            clear_cache()
        except Exception as e:
            pytest.fail(f"clear_cache() vyhodil neočekávanou výjimku: {e}")

    def test_clear_cache_calls_load_clear(self, monkeypatch):
        """clear_cache() musí volat load_from_db.clear()."""
        cleared = {"load_called": False, "client_called": False}

        def fake_load_clear():
            cleared["load_called"] = True

        def fake_client_clear():
            cleared["client_called"] = True

        monkeypatch.setattr(db_module.load_from_db, "clear", fake_load_clear)
        monkeypatch.setattr(db_module.get_supabase_client, "clear", fake_client_clear)

        clear_cache()

        assert cleared["load_called"] is True
        assert cleared["client_called"] is True

    def test_clear_cache_handles_exception(self, monkeypatch):
        """Pokud clear selže, nesmí to celé spadnout (musí to lognout a pokračovat)."""

        def fake_load_clear():
            raise RuntimeError("simulovaná chyba")

        monkeypatch.setattr(db_module.load_from_db, "clear", fake_load_clear)

        # Nemělo by vyhodit výjimku - chyba se pouze zaloguje
        try:
            clear_cache()
        except RuntimeError:
            pytest.fail("clear_cache() by měl zachytit výjimku z .clear(), ne ji propagovat")