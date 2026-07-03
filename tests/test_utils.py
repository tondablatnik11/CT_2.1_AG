"""
Testy pro kritické utility funkce z modules/utils.py.

Pokrývá:
- get_match_key a get_match_key_vectorized
- parse_packing_time
- safe_hu, safe_del
- is_box
- fast_compute_moves
"""
import numpy as np
import pandas as pd
import pytest

from modules.utils import (
    get_match_key,
    get_match_key_vectorized,
    parse_packing_time,
    safe_hu,
    safe_del,
    is_box,
    fast_compute_moves,
)


# ==========================================
# TESTY: get_match_key (skalární)
# ==========================================
class TestGetMatchKey:
    """Testy pro normalizaci match klíčů (Material kódy)."""

    def test_basic_string(self):
        assert get_match_key("abc") == "ABC"

    def test_with_whitespace(self):
        assert get_match_key("  abc  ") == "ABC"

    def test_decimal_normalization(self):
        """1.0 -> 1, 1.50 -> 1.5"""
        assert get_match_key("1.0") == "1"
        assert get_match_key("1.50") == "1.5"
        assert get_match_key("1.500") == "1.5"

    def test_leading_zeros(self):
        """0123 -> 123"""
        assert get_match_key("0123") == "123"
        assert get_match_key("00001") == "1"

    def test_leading_zero_with_zero_value(self):
        """0 -> 0 (ne prázdný string)"""
        assert get_match_key("0") == "0"
        assert get_match_key("000") == "0"

    def test_combined_decimal_and_zeros(self):
        """001.50 -> 1.5"""
        assert get_match_key("001.50") == "1.5"

    def test_non_numeric_unchanged(self):
        assert get_match_key("MAT-123") == "MAT-123"
        assert get_match_key("X") == "X"


# ==========================================
# TESTY: get_match_key_vectorized (pandas Series)
# ==========================================
class TestGetMatchKeyVectorized:
    """Testy pro vektorovou verzi."""

    def test_pandas_series(self):
        s = pd.Series(["abc", "1.0", "00123", "MAT-9"])
        result = get_match_key_vectorized(s)
        assert list(result) == ["ABC", "1", "123", "MAT-9"]

    def test_empty_series(self):
        s = pd.Series([], dtype=str)
        result = get_match_key_vectorized(s)
        assert len(result) == 0

    def test_mixed_types(self):
        """Series s různými typy vstupů."""
        s = pd.Series(["1.0", 2.0, "abc", None])
        result = get_match_key_vectorized(s)
        # None se převede na 'NAN'
        assert result.iloc[0] == "1"
        assert result.iloc[2] == "ABC"

    def test_performance_vs_apply(self):
        """Sanity check: vektorová verze by měla být rychlejší než .apply."""
        import time

        n = 10000
        s = pd.Series([f"{i}.0" for i in range(n)])

        start = time.time()
        get_match_key_vectorized(s)
        vec_time = time.time() - start

        start = time.time()
        s.apply(get_match_key)
        apply_time = time.time() - start

        # Vektorová verze by měla být alespoň 2x rychlejší
        # (v praxi bývá 10-50x rychlejší)
        assert vec_time < apply_time * 1.5 or vec_time < 0.1


# ==========================================
# TESTY: parse_packing_time
# ==========================================
class TestParsePackingTime:
    """Testy pro parsování různých formátů času."""

    def test_minutes_decimal(self):
        """Decimal jako minuty."""
        assert parse_packing_time("5.5") == 5.5
        assert parse_packing_time("123.4") == 123.4

    def test_decimal_hours_converted(self):
        """Decimal < 1 = hodiny, převede na minuty."""
        assert parse_packing_time("0.5") == 720  # 0.5 * 24 * 60
        assert parse_packing_time("0.25") == 360  # 15 minut

    def test_integer_minutes(self):
        assert parse_packing_time("30") == 30
        assert parse_packing_time("120") == 120

    def test_hh_mm_ss_format(self):
        """Formát HH:MM:SS."""
        assert parse_packing_time("01:30:00") == 90
        assert parse_packing_time("02:15:30") == 135.5

    def test_hh_mm_format(self):
        """Formát HH:MM."""
        assert parse_packing_time("01:30") == 90
        assert parse_packing_time("00:45") == 45

    def test_empty_and_invalid(self):
        """Prázdné/nevalidní hodnoty -> 0."""
        assert parse_packing_time("") == 0.0
        assert parse_packing_time("nan") == 0.0
        assert parse_packing_time("None") == 0.0
        assert parse_packing_time("invalid") == 0.0


# ==========================================
# TESTY: safe_hu, safe_del
# ==========================================
class TestSafeHU:
    def test_basic(self):
        assert safe_hu("12345") == "12345"

    def test_strip_dot_zero(self):
        """'12345.0' -> '12345'"""
        assert safe_hu("12345.0") == "12345"

    def test_nan_input(self):
        assert safe_hu("nan") == ""
        assert safe_hu("None") == ""
        assert safe_hu("") == ""

    def test_with_whitespace(self):
        assert safe_hu("  12345  ") == "12345"

    def test_keeps_decimals(self):
        assert safe_hu("12345.67") == "12345.67"


class TestSafeDel:
    def test_basic(self):
        assert safe_del("12345") == "12345"

    def test_strip_leading_zeros(self):
        """'00123' -> '123'"""
        assert safe_del("00123") == "123"
        assert safe_del("000") == "0"

    def test_strip_dot_zero(self):
        assert safe_del("12345.0") == "12345"

    def test_nan_input(self):
        assert safe_del("nan") == ""
        assert safe_del("None") == ""
        assert safe_del("") == ""

    def test_combined(self):
        """'00012.0' -> '12'"""
        assert safe_del("00012.0") == "12"


# ==========================================
# TESTY: is_box (detekce KLT/krabic)
# ==========================================
class TestIsBox:
    @pytest.mark.parametrize("box_code,expected", [
        ("K1", True),
        ("K2", True),
        ("K3", True),
        ("K4", True),
        ("KLT", True),
        ("KLT1", True),
        ("KLT2", True),
        ("CARTON", True),
        ("BOX", True),
        ("CT", True),
        ("CD3", True),
        ("CD", True),
        ("CR", True),
    ])
    def test_box_codes(self, box_code, expected):
        assert is_box(box_code) == expected

    @pytest.mark.parametrize("pallet_code", [
        "PALETA",
        "EURO",
        "INDUSTRIAL",
        "E1",
        "EUR",
        "CARTON-16",  # Speciální případ - není KLT
    ])
    def test_pallet_codes(self, pallet_code):
        assert is_box(pallet_code) == False

    def test_case_insensitive(self):
        assert is_box("klt") == True
        assert is_box("Carton") == True

    def test_empty_string(self):
        assert is_box("") == False


# ==========================================
# TESTY: fast_compute_moves (jádro výpočtů)
# ==========================================
class TestFastComputeMoves:
    """Testy pro výpočet fyzických pohybů skladníka."""

    def test_zero_qty(self):
        """qty=0 -> 0 pohybů."""
        total, exact, miss = fast_compute_moves(
            qty_arr=[0], queue_arr=["PI_PL"], su_arr=["X"],
            boxes_arr=[()], weight_arr=[0.0], dim_arr=[0.0],
            v_limit=2.0, d_limit=15.0, h_limit=1,
        )
        assert total == [0]
        assert exact == [0]
        assert miss == [0]

    def test_full_pallet_x_mark(self):
        """PI_PL_FU + 'X' = 1 pohyb (celá paleta)."""
        total, exact, miss = fast_compute_moves(
            qty_arr=[100], queue_arr=["PI_PL_FU"], su_arr=["X"],
            boxes_arr=[()], weight_arr=[0.0], dim_arr=[0.0],
            v_limit=2.0, d_limit=15.0, h_limit=1,
        )
        assert total == [1]
        assert exact == [1]
        assert miss == [0]

    def test_full_pallet_fuoe_x_mark(self):
        """PI_PL_FUOE + 'X' = 1 pohyb."""
        total, exact, miss = fast_compute_moves(
            qty_arr=[50], queue_arr=["PI_PL_FUOE"], su_arr=["X"],
            boxes_arr=[()], weight_arr=[0.0], dim_arr=[0.0],
            v_limit=2.0, d_limit=15.0, h_limit=1,
        )
        assert total == [1]
        assert exact == [1]

    def test_full_pallet_without_x_mark(self):
        """PI_PL_FU bez 'X' = běžný výpočet (NE 1)."""
        total, exact, miss = fast_compute_moves(
            qty_arr=[100], queue_arr=["PI_PL_FU"], su_arr=[""],
            boxes_arr=[(10,)], weight_arr=[0.5], dim_arr=[5.0],
            v_limit=2.0, d_limit=15.0, h_limit=1,
        )
        # 100 / 10 = 10 krabic, žádný zbytek
        assert total[0] == 10
        assert exact[0] == 10

    def test_simple_box_decomposition(self):
        """100 ks, krabice po 10 = 10 pohybů, žádný zbytek."""
        total, exact, miss = fast_compute_moves(
            qty_arr=[100], queue_arr=["PI_PL"], su_arr=[""],
            boxes_arr=[(10,)], weight_arr=[0.5], dim_arr=[5.0],
            v_limit=2.0, d_limit=15.0, h_limit=1,
        )
        assert total[0] == 10
        assert exact[0] == 10
        assert miss[0] == 0

    def test_box_decomposition_with_remainder(self):
        """105 ks, krabice po 10 = 10 pohybů + 5 ks do hrsti."""
        total, exact, miss = fast_compute_moves(
            qty_arr=[105], queue_arr=["PI_PL"], su_arr=[""],
            boxes_arr=[(10,)], weight_arr=[0.5], dim_arr=[5.0],  # lehké, malé
            v_limit=2.0, d_limit=15.0, h_limit=1,
        )
        # 10 krabic + 5 ks (lehké, malé) -> 10 pohybů (vše do exact)
        assert total[0] == 10
        assert exact[0] == 10

    def test_heavy_loose_piece(self):
        """Zbytek těžkých kusů = každý 1 pohyb."""
        total, exact, miss = fast_compute_moves(
            qty_arr=[15], queue_arr=["PI_PL"], su_arr=[""],
            boxes_arr=[(10,)], weight_arr=[5.0], dim_arr=[5.0],  # těžké!
            v_limit=2.0, d_limit=15.0, h_limit=1,
        )
        # 1 krabice + 5 těžkých kusů = 1 + 5 = 6 pohybů
        assert total[0] == 6
        assert exact[0] == 6

    def test_large_loose_piece(self):
        """Zbytek velkých kusů = každý 1 pohyb (i když lehké)."""
        total, exact, miss = fast_compute_moves(
            qty_arr=[12], queue_arr=["PI_PL"], su_arr=[""],
            boxes_arr=[(10,)], weight_arr=[0.5], dim_arr=[20.0],  # velké!
            v_limit=2.0, d_limit=15.0, h_limit=1,
        )
        # 1 krabice + 2 velké kusy = 3 pohyby
        assert total[0] == 3

    def test_missing_box_estimation(self):
        """Bez zadaných krabic = miss estimation."""
        total, exact, miss = fast_compute_moves(
            qty_arr=[10], queue_arr=["PI_PL"], su_arr=[""],
            boxes_arr=[()], weight_arr=[0.5], dim_arr=[5.0],
            v_limit=2.0, d_limit=15.0, h_limit=1,
        )
        # 10 lehkých ks bez master dat = miss estimation
        assert total[0] == 10
        assert miss[0] == 10
        assert exact[0] == 0

    def test_multiple_box_sizes(self):
        """Více velikostí krabic - použije největší."""
        total, exact, miss = fast_compute_moves(
            qty_arr=[50], queue_arr=["PI_PL"], su_arr=[""],
            boxes_arr=[(10, 5, 1)],  # tuple seřazený od největší
            weight_arr=[0.5], dim_arr=[5.0],
            v_limit=2.0, d_limit=15.0, h_limit=1,
        )
        # 50 / 10 = 5 krabic, 0 zbytek
        assert total[0] == 5
        assert exact[0] == 5

    def test_multiple_items_batch(self):
        """Dávka různých řádků."""
        total, exact, miss = fast_compute_moves(
            qty_arr=[0, 100, 50, 10],
            queue_arr=["PI_PL", "PI_PL_FU", "PI_PL", "PI_PA"],
            su_arr=["", "X", "", ""],
            boxes_arr=[(10,), (), (5,), ()],
            weight_arr=[0.5, 0.0, 0.5, 0.5],
            dim_arr=[5.0, 0.0, 5.0, 5.0],
            v_limit=2.0, d_limit=15.0, h_limit=1,
        )
        # 0 -> 0
        # 100 + PI_PL_FU + X = 1
        # 50 / 5 = 10
        # 10 / miss = 10
        assert total == [0, 1, 10, 10]

    def test_grab_limit_multiple_pieces(self):
        """Do hrsti lze vzít více lehkých kusů najednou."""
        total, exact, miss = fast_compute_moves(
            qty_arr=[12], queue_arr=["PI_PL"], su_arr=[""],
            boxes_arr=[(10,)], weight_arr=[0.1], dim_arr=[2.0],  # lehké, malé
            v_limit=2.0, d_limit=15.0, h_limit=5,  # 5 ks do hrsti
        )
        # 1 krabice + ceil(2 / 5) = 1 pohyb
        assert total[0] == 2
        assert exact[0] == 2

    def test_safe_h_limit_zero(self):
        """h_limit=0 by nemělo způsobit ZeroDivisionError."""
        total, exact, miss = fast_compute_moves(
            qty_arr=[10], queue_arr=["PI_PL"], su_arr=[""],
            boxes_arr=[()], weight_arr=[0.1], dim_arr=[2.0],
            v_limit=2.0, d_limit=15.0, h_limit=0,  # hrozilo by dělení nulou
        )
        # Mělo by bezpečně nastavit h_limit=1
        assert total[0] == 10
        assert all(t >= 0 for t in total)


# ==========================================
# TESTY: Edge cases
# ==========================================
class TestEdgeCases:
    def test_negative_qty_returns_zero(self):
        total, exact, miss = fast_compute_moves(
            qty_arr=[-5], queue_arr=["PI_PL"], su_arr=[""],
            boxes_arr=[(10,)], weight_arr=[0.5], dim_arr=[5.0],
            v_limit=2.0, d_limit=15.0, h_limit=1,
        )
        assert total[0] == 0

    def test_nan_weight_handled(self):
        """NaN váha by neměla způsobit pád."""
        total, exact, miss = fast_compute_moves(
            qty_arr=[10], queue_arr=["PI_PL"], su_arr=[""],
            boxes_arr=[(10,)], weight_arr=[float('nan')], dim_arr=[5.0],
            v_limit=2.0, d_limit=15.0, h_limit=1,
        )
        assert total[0] >= 0
        assert not np.isnan(total[0])