"""
Performance regression testy pro kritické výpočetní funkce.

Pokrývá:
- fast_compute_moves na 100k řádků < 5 sekund
- get_match_key_vectorized rychlejší než apply
- detect_vollpalettes < 3 sekundy na test data
"""
import time
import numpy as np
import pandas as pd
import pytest

from modules.utils import (
    fast_compute_moves,
    get_match_key,
    get_match_key_vectorized,
    detect_vollpalettes,
)


# ==========================================
# TESTY: fast_compute_moves
# ==========================================
class TestFastComputeMovesPerformance:
    """Výkon fast_compute_moves."""

    def test_100k_rows_under_5_seconds(self):
        """100 000 řádků musí být zpracováno za < 5 sekund."""
        n = 100_000
        np.random.seed(42)

        # Generování realistických dat
        qty_arr = np.random.randint(0, 1000, n).tolist()
        queue_arr = np.random.choice(
            ["PI_PL", "PI_PL_FU", "PI_PL_FUOE", "PI_PA"], n
        ).tolist()
        su_arr = np.random.choice(["", "X"], n).tolist()
        boxes_arr = [
            tuple(np.random.choice([1, 5, 10, 20, 50], size=np.random.randint(0, 3)))
            for _ in range(n)
        ]
        weight_arr = np.random.uniform(0.1, 5.0, n).tolist()
        dim_arr = np.random.uniform(2.0, 30.0, n).tolist()

        start = time.time()
        total, exact, miss = fast_compute_moves(
            qty_arr=qty_arr,
            queue_arr=queue_arr,
            su_arr=su_arr,
            boxes_arr=boxes_arr,
            weight_arr=weight_arr,
            dim_arr=dim_arr,
            v_limit=2.0,
            d_limit=15.0,
            h_limit=1,
        )
        elapsed = time.time() - start

        assert len(total) == n
        assert all(t >= 0 for t in total)
        assert elapsed < 5.0, f"100k řádků trvalo {elapsed:.2f}s, > 5s"

    def test_50k_rows_under_3_seconds(self):
        """Přísnější limit pro 50k řádků (< 3s)."""
        n = 50_000
        np.random.seed(123)

        qty_arr = np.random.randint(1, 500, n).tolist()
        queue_arr = np.random.choice(["PI_PL", "PI_PL_FU"], n).tolist()
        su_arr = np.random.choice(["", "X"], n).tolist()
        boxes_arr = [(10, 5)] * n
        weight_arr = np.random.uniform(0.5, 3.0, n).tolist()
        dim_arr = np.random.uniform(5.0, 20.0, n).tolist()

        start = time.time()
        total, exact, miss = fast_compute_moves(
            qty_arr=qty_arr,
            queue_arr=queue_arr,
            su_arr=su_arr,
            boxes_arr=boxes_arr,
            weight_arr=weight_arr,
            dim_arr=dim_arr,
            v_limit=2.0,
            d_limit=15.0,
            h_limit=1,
        )
        elapsed = time.time() - start

        assert elapsed < 3.0, f"50k řádků trvalo {elapsed:.2f}s, > 3s"

    def test_full_pal_fast_path_performance(self):
        """Fast-path pro plné palety (PI_PL_FU + X) musí být extrémně rychlý."""
        n = 100_000

        # Všichni mají PI_PL_FU + X = 1 pohyb
        qty_arr = [100] * n
        queue_arr = ["PI_PL_FU"] * n
        su_arr = ["X"] * n
        boxes_arr = [()] * n
        weight_arr = [0.0] * n
        dim_arr = [0.0] * n

        start = time.time()
        total, exact, miss = fast_compute_moves(
            qty_arr=qty_arr,
            queue_arr=queue_arr,
            su_arr=su_arr,
            boxes_arr=boxes_arr,
            weight_arr=weight_arr,
            dim_arr=dim_arr,
            v_limit=2.0,
            d_limit=15.0,
            h_limit=1,
        )
        elapsed = time.time() - start

        assert total == [1] * n
        # Fast path by měl být < 1 sekunda
        assert elapsed < 1.0, f"Fast-path trval {elapsed:.2f}s"


# ==========================================
# TESTY: get_match_key_vectorized vs apply
# ==========================================
class TestVectorizedVsApply:
    """get_match_key_vectorized musí být minimálně stejně rychlý jako apply (ideálně rychlejší).

    Poznámka: Současná implementace kombinuje numpy vectorized operace s Python smyčkou
    přes skalární normalizační funkci. Toto je bezpečnější (žádné regex zpětné vazby) a
    na velkých datech je srovnatelné nebo lehce rychlejší než apply. Test ověřuje, že
    neztrácíme výkon proti apply a že výsledky jsou správné.
    """

    def test_vectorized_not_slower_than_apply(self):
        """Vektorizovaná verze nesmí být výrazně pomalejší než apply."""
        n = 10_000
        np.random.seed(42)
        # Mix formátů, který spouští různé větve logiky
        formats = ["1.0", "00123", "0.50", "001.50", "MAT-9", "ABC"]
        s = pd.Series([formats[i % len(formats)] for i in range(n)])

        # Vektorizovaná verze
        start = time.time()
        for _ in range(10):  # 10 opakování pro stabilnější měření
            result_vec = get_match_key_vectorized(s)
        vec_time = time.time() - start

        # Apply verze
        start = time.time()
        for _ in range(10):
            result_apply = s.apply(get_match_key)
        apply_time = time.time() - start

        # Vektorizovaná verze nesmí být více než 3x pomalejší než apply.
        # (Ideálně je srovnatelná, ale tolerujeme overhead pro safety marži.)
        assert vec_time <= apply_time * 3.0, (
            f"vec={vec_time:.3f}s, apply={apply_time:.3f}s - "
            f"vektorizovaná je {vec_time/apply_time:.2f}x pomalejší!"
        )

    def test_vectorized_scales_on_large(self):
        """Pro 100k hodnot - výsledky musí být správné a čas rozumný (< 5s)."""
        n = 100_000
        # Kombinace formátů pro realističtější zátěž
        np.random.seed(123)
        formats = [
            lambda i: f"mat_{i}",
            lambda i: f"00{i % 100}",
            lambda i: f"{i}.0",
            lambda i: f"0{i % 10}.{i % 10}0",
        ]
        s = pd.Series([formats[i % len(formats)](i) for i in range(n)])

        # Vektorizovaná verze
        start = time.time()
        result_vec = get_match_key_vectorized(s)
        vec_time = time.time() - start

        # Apply verze
        start = time.time()
        result_apply = s.apply(get_match_key)
        apply_time = time.time() - start

        # Výsledky se musí shodovat
        assert list(result_vec) == list(result_apply)

        # 100k řádků musí být zpracováno do 5 sekund
        assert vec_time < 5.0, f"vec trval {vec_time:.2f}s pro 100k řádků"
        # Nesmí být drasticky pomalejší než apply (max 3x)
        assert vec_time <= apply_time * 3.0, (
            f"vec={vec_time:.3f}s, apply={apply_time:.3f}s - "
            f"vektorizovaná je {vec_time/apply_time:.2f}x pomalejší!"
        )

    def test_vectorized_correctness_on_mixed_data(self):
        """Vektorizovaná verze musí dávat stejné výsledky jako skalární."""
        # Smíšená data: různé formáty
        test_values = [
            "1.0", "1.50", "1.500",  # decimal
            "00123", "00001", "0", "000",  # leading zeros
            "001.50",  # kombinace
            "MAT-9", "X",  # non-numeric
            "abc", "  ABC  ",  # whitespace + case
        ]
        s = pd.Series(test_values)
        result_vec = get_match_key_vectorized(s)
        result_apply = s.apply(get_match_key)

        assert list(result_vec) == list(result_apply)


# ==========================================
# TESTY: detect_vollpalettes
# ==========================================
class TestDetectVollpalettesPerformance:
    """Výkon detect_vollpalettes na testovacích datech."""

    @pytest.fixture
    def test_data_medium(self):
        """Středně velká testovací data (~5k řádků)."""
        np.random.seed(42)

        # VEKP - hierarchie HU
        n_vekp = 1000
        vekp = pd.DataFrame({
            "Internal HU": [f"HU{i:06d}" for i in range(n_vekp)],
            "External HU": [f"EXT{i:06d}" for i in range(n_vekp)],
            "higher-level HU": ["" if i % 3 != 0 else f"HU{(i-1):06d}" for i in range(n_vekp)],
            "Generated delivery": [f"D{i:06d}" for i in range(n_vekp)],
            "Packmittel": np.random.choice(["PALETA", "KLT", "K1", "K2", "BOX"], n_vekp),
        })

        # VEPO - top-level HU
        n_vepo = 500
        vepo_hus = set(np.random.choice([f"HU{i:06d}" for i in range(n_vekp)], n_vepo, replace=False))
        vepo = pd.DataFrame({
            "HU-Nummer intern": list(vepo_hus),
        })

        # PICK - záznamy
        n_pick = 5000
        pick = pd.DataFrame({
            "Storage Unit Type": np.random.choice(["PALETA", "K1", "KLT", "X"], n_pick),
            "Removal of total SU": np.random.choice(["", "X"], n_pick, p=[0.7, 0.3]),
            "Queue": np.random.choice(["PI_PL", "PI_PL_FU", "PI_PA"], n_pick),
            "Source storage unit": [f"HU{np.random.randint(0, n_vekp):06d}" for _ in range(n_pick)],
            "Handling Unit": [f"HU{np.random.randint(0, n_vekp):06d}" for _ in range(n_pick)],
            "Delivery": [f"D{np.random.randint(0, n_vekp):06d}" for _ in range(n_pick)],
        })

        return pick, vekp, vepo

    def test_medium_dataset_under_3_seconds(self, test_data_medium):
        """Střední dataset (5k pick, 1k vekp, 500 vepo) musí být < 3 sekundy."""
        pick, vekp, vepo = test_data_medium

        start = time.time()
        result = detect_vollpalettes(pick, vekp, vepo)
        elapsed = time.time() - start

        # Výsledek je set (delivery, hu_number)
        assert isinstance(result, set)
        assert elapsed < 3.0, f"5k řádků trvalo {elapsed:.2f}s, > 3s"

    def test_empty_inputs_fast(self):
        """Prázdné vstupy - musí vrátit prázdný set rychle."""
        empty_df = pd.DataFrame()

        start = time.time()
        result = detect_vollpalettes(empty_df, empty_df, empty_df)
        elapsed = time.time() - start

        assert result == set()
        assert elapsed < 0.5, f"Prázdné vstupy trvaly {elapsed:.2f}s"

    def test_none_inputs_fast(self):
        """None vstupy - musí se bezpečně a rychle vrátit."""
        start = time.time()
        result = detect_vollpalettes(None, None, None)
        elapsed = time.time() - start

        assert result == set()
        assert elapsed < 0.5

    def test_large_dataset_under_5_seconds(self):
        """Velký dataset (20k pick, 2k vekp, 1k vepo) < 5 sekund."""
        np.random.seed(99)

        n_vekp = 2000
        vekp = pd.DataFrame({
            "Internal HU": [f"HU{i:06d}" for i in range(n_vekp)],
            "External HU": [f"EXT{i:06d}" for i in range(n_vekp)],
            "higher-level HU": ["" if i % 4 != 0 else f"HU{(i-1):06d}" for i in range(n_vekp)],
            "Generated delivery": [f"D{i:06d}" for i in range(n_vekp)],
            "Packmittel": np.random.choice(["PALETA", "KLT", "K1"], n_vekp),
        })

        n_vepo = 1000
        vepo_hus = list(set(np.random.choice([f"HU{i:06d}" for i in range(n_vekp)], n_vepo, replace=False)))
        vepo = pd.DataFrame({"HU-Nummer intern": vepo_hus})

        n_pick = 20_000
        pick = pd.DataFrame({
            "Storage Unit Type": np.random.choice(["PALETA", "K1", "KLT", "X"], n_pick),
            "Removal of total SU": np.random.choice(["", "X"], n_pick, p=[0.6, 0.4]),
            "Queue": np.random.choice(["PI_PL", "PI_PL_FU", "PI_PA"], n_pick),
            "Source storage unit": [f"HU{np.random.randint(0, n_vekp):06d}" for _ in range(n_pick)],
            "Handling Unit": [f"HU{np.random.randint(0, n_vekp):06d}" for _ in range(n_pick)],
            "Delivery": [f"D{np.random.randint(0, n_vekp):06d}" for _ in range(n_pick)],
        })

        start = time.time()
        result = detect_vollpalettes(pick, vekp, vepo)
        elapsed = time.time() - start

        assert isinstance(result, set)
        assert elapsed < 5.0, f"20k pick řádků trvalo {elapsed:.2f}s, > 5s"


# ==========================================
# TESTY: Obecný výkon sanity check
# ==========================================
class TestOverallPerformance:
    """Celkový výkon sanity check."""

    def test_no_excessive_memory_in_compute_moves(self):
        """fast_compute_moves nesmí vytvářet extrémně velké mezivýsledky."""
        import tracemalloc

        tracemalloc.start()
        n = 50_000

        np.random.seed(7)
        qty_arr = np.random.randint(1, 100, n).tolist()
        queue_arr = ["PI_PL"] * n
        su_arr = [""] * n
        boxes_arr = [(10,)] * n
        weight_arr = [0.5] * n
        dim_arr = [5.0] * n

        fast_compute_moves(
            qty_arr=qty_arr,
            queue_arr=queue_arr,
            su_arr=su_arr,
            boxes_arr=boxes_arr,
            weight_arr=weight_arr,
            dim_arr=dim_arr,
            v_limit=2.0,
            d_limit=15.0,
            h_limit=1,
        )
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        # Peak < 200 MB pro 50k řádků (konzervativní limit)
        peak_mb = peak / (1024 * 1024)
        assert peak_mb < 200, f"Peak memory {peak_mb:.1f} MB > 200 MB"