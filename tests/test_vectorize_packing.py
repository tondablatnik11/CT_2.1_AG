"""
Testy pro _vectorize_packing_times z app.py.

Pokrývá:
- Všechny formáty (decimal minuty, decimal hodiny, HH:MM:SS, HH:MM)
- Edge cases: prázdné hodnoty, NaN, None, nevalidní string
- Správnost pro HH:MM formát (1:30 = 90 minut, ne 1.5)
"""
import numpy as np
import pandas as pd
import pytest

from app import _vectorize_packing_times


# ==========================================
# TESTY: Decimal minuty (>= 1)
# ==========================================
class TestDecimalMinutes:
    """Decimal hodnoty >= 1 = minuty."""

    def test_simple_decimal(self):
        """5.5 = 5.5 minut."""
        s = pd.Series(["5.5"])
        result = _vectorize_packing_times(s)
        assert result.iloc[0] == pytest.approx(5.5)

    def test_integer_as_minutes(self):
        """30 = 30 minut (>= 1)."""
        s = pd.Series(["30"])
        result = _vectorize_packing_times(s)
        assert result.iloc[0] == 30.0

    def test_large_decimal(self):
        """123.4 = 123.4 minut."""
        s = pd.Series(["123.4"])
        result = _vectorize_packing_times(s)
        assert result.iloc[0] == pytest.approx(123.4)

    def test_multiple_decimal_values(self):
        s = pd.Series(["5.5", "30", "123.4", "60"])
        result = _vectorize_packing_times(s)
        assert result.iloc[0] == pytest.approx(5.5)
        assert result.iloc[1] == 30.0
        assert result.iloc[2] == pytest.approx(123.4)
        assert result.iloc[3] == 60.0


# ==========================================
# TESTY: Decimal hodiny (< 1) - konverze na minuty
# ==========================================
class TestDecimalHours:
    """Decimal hodnoty < 1 se konvertují na minuty (× 24 × 60)."""

    def test_half_day(self):
        """0.5 = 12 hodin = 720 minut."""
        s = pd.Series(["0.5"])
        result = _vectorize_packing_times(s)
        assert result.iloc[0] == 720.0

    def test_quarter_day(self):
        """0.25 = 6 hodin = 360 minut."""
        s = pd.Series(["0.25"])
        result = _vectorize_packing_times(s)
        assert result.iloc[0] == 360.0

    def test_small_decimal(self):
        """0.1 = 2.4 hodiny = 144 minut."""
        s = pd.Series(["0.1"])
        result = _vectorize_packing_times(s)
        assert result.iloc[0] == pytest.approx(144.0)

    def test_threshold_one(self):
        """Hraniční hodnota 1.0 - neměla by být brána jako hodiny."""
        s = pd.Series(["1.0"])
        result = _vectorize_packing_times(s)
        assert result.iloc[0] == 1.0


# ==========================================
# TESTY: HH:MM:SS formát
# ==========================================
class TestHMMSSFormat:
    """Formát HH:MM:SS - hodiny, minuty, sekundy."""

    def test_basic_hhmmss(self):
        """01:30:00 = 1*60 + 30 + 0/60 = 90 minut."""
        s = pd.Series(["01:30:00"])
        result = _vectorize_packing_times(s)
        assert result.iloc[0] == pytest.approx(90.0)

    def test_hhmmss_with_seconds(self):
        """02:15:30 = 135.5 minut."""
        s = pd.Series(["02:15:30"])
        result = _vectorize_packing_times(s)
        assert result.iloc[0] == pytest.approx(135.5)

    def test_zero_time(self):
        """00:00:00 = 0 minut."""
        s = pd.Series(["00:00:00"])
        result = _vectorize_packing_times(s)
        assert result.iloc[0] == 0.0

    def test_long_time(self):
        """10:00:00 = 600 minut."""
        s = pd.Series(["10:00:00"])
        result = _vectorize_packing_times(s)
        assert result.iloc[0] == pytest.approx(600.0)


# ==========================================
# TESTY: HH:MM formát - KRITICKÉ!
# ==========================================
class TestHHMMFormat:
    """Formát HH:MM - KRITICKÉ: 1:30 = 90 minut, ne 1.5!"""

    def test_one_thirty_is_90_minutes(self):
        """01:30 = 90 minut (1 hodina × 60 + 30 minut)."""
        s = pd.Series(["01:30"])
        result = _vectorize_packing_times(s)
        assert result.iloc[0] == 90.0, f"Očekáváno 90 minut, dostáno {result.iloc[0]}"

    def test_zero_forty_five(self):
        """00:45 = 45 minut."""
        s = pd.Series(["00:45"])
        result = _vectorize_packing_times(s)
        assert result.iloc[0] == 45.0

    def test_two_hours(self):
        """02:00 = 120 minut."""
        s = pd.Series(["02:00"])
        result = _vectorize_packing_times(s)
        assert result.iloc[0] == 120.0

    def test_zero_zero(self):
        """00:00 = 0 minut."""
        s = pd.Series(["00:00"])
        result = _vectorize_packing_times(s)
        assert result.iloc[0] == 0.0

    def test_single_digit_hour(self):
        """5:30 = 330 minut."""
        s = pd.Series(["5:30"])
        result = _vectorize_packing_times(s)
        assert result.iloc[0] == 330.0

    def test_ten_hours(self):
        """10:30 = 630 minut."""
        s = pd.Series(["10:30"])
        result = _vectorize_packing_times(s)
        assert result.iloc[0] == 630.0

    def test_hhmm_not_treated_as_decimal(self):
        """'01:30' NESMÍ být vyhodnoceno jako 1.5 (decimal hodiny)."""
        s = pd.Series(["01:30"])
        result = _vectorize_packing_times(s)
        # Pokud by to bylo 1.5, výsledek by byl 1.5 * 24 * 60 = 2160 minut
        # Správně musí být 90 minut
        assert result.iloc[0] != 2160.0
        assert result.iloc[0] == 90.0


# ==========================================
# TESTY: Edge cases - prázdné/None/NaN
# ==========================================
class TestEdgeCases:
    """Edge cases: prázdné hodnoty, NaN, None, nevalidní string."""

    def test_empty_string(self):
        """'' -> 0."""
        s = pd.Series([""])
        result = _vectorize_packing_times(s)
        assert result.iloc[0] == 0.0

    def test_nan_string(self):
        """'nan' -> 0."""
        s = pd.Series(["nan"])
        result = _vectorize_packing_times(s)
        assert result.iloc[0] == 0.0

    def test_none_string(self):
        """'None' -> 0."""
        s = pd.Series(["None"])
        result = _vectorize_packing_times(s)
        assert result.iloc[0] == 0.0

    def test_capital_nan(self):
        """'NaN' -> 0."""
        s = pd.Series(["NaN"])
        result = _vectorize_packing_times(s)
        assert result.iloc[0] == 0.0

    def test_invalid_string(self):
        """Neplatný string -> 0."""
        s = pd.Series(["neplatný text"])
        result = _vectorize_packing_times(s)
        assert result.iloc[0] == 0.0

    def test_whitespace_only(self):
        """Pouze mezery -> 0 (po stripu je prázdný)."""
        s = pd.Series(["   "])
        result = _vectorize_packing_times(s)
        assert result.iloc[0] == 0.0

    def test_mixed_valid_and_invalid(self):
        """Směs validních a nevalidních hodnot."""
        s = pd.Series(["30", "", "nan", "01:30", "None", "0.5"])
        result = _vectorize_packing_times(s)
        assert result.iloc[0] == 30.0
        assert result.iloc[1] == 0.0
        assert result.iloc[2] == 0.0
        assert result.iloc[3] == 90.0
        assert result.iloc[4] == 0.0
        assert result.iloc[5] == 720.0

    def test_python_none_value(self):
        """Python None v Series -> 0."""
        s = pd.Series([None])
        result = _vectorize_packing_times(s)
        assert result.iloc[0] == 0.0

    def test_numpy_nan_value(self):
        """numpy.nan v Series -> 0."""
        s = pd.Series([np.nan])
        result = _vectorize_packing_times(s)
        assert result.iloc[0] == 0.0

    def test_empty_series(self):
        """Prázdná Series -> prázdný výsledek."""
        s = pd.Series([], dtype=object)
        result = _vectorize_packing_times(s)
        assert len(result) == 0

    def test_malformed_time_string(self):
        """Neplatný formát času (špatný počet dvojteček) -> 0."""
        s = pd.Series(["1:2:3:4"])
        result = _vectorize_packing_times(s)
        assert result.iloc[0] == 0.0


# ==========================================
# TESTY: Výkon a integrita
# ==========================================
class TestPerformanceAndIntegrity:
    """Výkon a integrita výsledků."""

    def test_index_preserved(self):
        """Index Series musí být zachován."""
        s = pd.Series(["30", "01:30"], index=[10, 20])
        result = _vectorize_packing_times(s)
        assert list(result.index) == [10, 20]

    def test_all_formats_combined(self):
        """Všechny formáty v jedné Series - ověření správnosti všech větví."""
        s = pd.Series([
            "5.5",        # decimal minuty
            "30",         # celé minuty
            "0.5",        # decimal hodiny (< 1) -> 720
            "01:30:00",   # HH:MM:SS
            "01:30",      # HH:MM -> 90
            "",           # prázdné
            "nan",        # nevalidní
        ])
        result = _vectorize_packing_times(s)
        assert result.iloc[0] == pytest.approx(5.5)
        assert result.iloc[1] == 30.0
        assert result.iloc[2] == 720.0
        assert result.iloc[3] == pytest.approx(90.0)
        assert result.iloc[4] == 90.0  # HH:MM formát
        assert result.iloc[5] == 0.0
        assert result.iloc[6] == 0.0

    def test_large_series_performance(self):
        """10k řádků by mělo proběhnout rychle."""
        import time

        n = 10_000
        # Mix různých formátů
        formats = ["5.5", "30", "01:30", "02:15:30", "0.5", "10:00", ""]
        s = pd.Series([formats[i % len(formats)] for i in range(n)])

        start = time.time()
        result = _vectorize_packing_times(s)
        elapsed = time.time() - start

        assert len(result) == n
        # Vektorizovaná verze by měla být rychlá
        assert elapsed < 3.0, f"10k řádků trvalo {elapsed:.2f}s"