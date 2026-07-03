# 🏢 Warehouse Control Tower

End-to-End analytická aplikace pro skladové hospodářství (Hellmann logistika).

## 🎯 Co aplikace dělá

- **Analyzuje fyzické pohyby** skladníků (počítá pohyby z krabic, kusů, palet)
- **Koreluje pickování s fakturací** (porovnává skutečnou práci vs. účtování)
- **Detekuje Vollpalety** (palety které prošly skladem nezměněny)
- **Vizualizuje KPI** v reálném čase (denní, měsíční, roční trendy)
- **Generuje reporty** pro Power BI a Excel export

## 🛠 Tech Stack

- **Frontend:** Streamlit 1.58+ (Python)
- **Backend:** Supabase Storage (Parquet soubory)
- **Data:** Pick Report, VEKP/VEPO, MARM, OE-Times, LIKP, LX03, LT10
- **Vizualizace:** Plotly
- **Výpočty:** Pandas + NumPy

## 📁 Struktura projektu

```
CT_2.1_AG/
├── app.py                      # Hlavní entry point
├── database.py                 # Supabase I/O + retry logika
├── requirements.txt            # Runtime závislosti (pinned)
├── requirements-dev.txt        # Dev/test závislosti
├── pyproject.toml              # Ruff konfigurace
├── pytest.ini                  # Pytest konfigurace
├── .github/
│   └── workflows/
│       ├── ci.yml              # Hlavní CI/CD pipeline
│       └── tests.yml           # Test runner
├── tests/                      # Unit testy (pytest)
│   ├── conftest.py
│   ├── test_utils.py           # 40+ testů pro výpočetní jádro
│   ├── test_safe_render.py     # Testy pro error handling
│   ├── test_chart_layout.py    # Testy pro Plotly helper
│   └── test_datalayer.py       # Testy pro database.py
└── modules/
    ├── utils.py                # Výpočetní jádro (fast_compute_moves, ...)
    ├── safe_render.py          # @safe_render, ErrorBoundary
    └── tab_*.py                # 13 specializovaných záložek
```

## 🚀 Spuštění lokálně

```bash
# Instalace závislostí
pip install -r requirements-dev.txt

# Spuštění aplikace
streamlit run app.py

# Spuštění testů
pytest tests/

# Lint
ruff check modules/ database.py app.py
```

## 🧪 Testy

Projekt má **40+ unit testů** pokrývajících kritické funkce:

```bash
pytest tests/ -v
```

### Pokrytí testy:
- ✅ `fast_compute_moves` — výpočet fyzických pohybů
- ✅ `detect_vollpalettes` — detekce celých palet
- ✅ `parse_packing_time` — parsování časů
- ✅ `get_match_key` — normalizace match klíčů
- ✅ `safe_hu`, `safe_del` — čištění identifikátorů
- ✅ `is_box` — detekce KLT/box vs paleta
- ✅ `apply_chart_defaults` — Plotly layout helper
- ✅ `@safe_render` dekorátor
- ✅ `ErrorBoundary` context manager
- ✅ `_is_not_found_error` — Supabase 404 detekce
- ✅ `_retry_operation` — retry logika
- ✅ `_dedupe_by_table` — dedupikace podle tabulky

## 📊 Statistiky projektu

| Metrika | Hodnota |
|---------|---------|
| Python souborů | 18 |
| Řádků kódu | ~6 500 |
| Testovacích souborů | 6 |
| Unit testů | 40+ |
| CI/CD workflow | ✅ GitHub Actions |
| Type hints | 🔄 Postupně přidávány |

## 🔄 CI/CD Pipeline

Každý push do `main` spustí:

1. **Syntax Check** - validace všech .py souborů
2. **Unit Tests** - pytest s coverage reportem
3. **Import Check** - ověření že všechny moduly a kritické funkce jsou importovatelné
4. **Lint** - ruff kontrola kódu
5. **Stats** - přehled velikosti projektu

## 🔑 Bezpečnost

- Heslo Admin zóny: `admin123` (změnit v `app.py`)
- Streamlit secrets obsahují Supabase klíče
- Žádné credentials v gitu - viz `.gitignore`

## 📝 Licence

Interní projekt - Hellmann Logistics Czech Republic.