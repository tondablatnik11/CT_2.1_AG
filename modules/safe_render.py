"""
Centrální modul pro bezpečné vykreslování a error handling.

Poskytuje:
- @safe_render dekorátor pro ochranu celých tabů před pádem
- ErrorBoundary kontext pro zachycení výjimek v konkrétních sekcích
- Pomocné funkce pro user-friendly chybové zprávy
"""
import functools
import logging
import traceback
import pandas as pd
import streamlit as st
from typing import Callable, Any, Optional

logger = logging.getLogger("warehouse.safety")


def safe_render(fallback_message: Optional[str] = None, show_traceback: bool = False):
    """
    Dekorátor pro bezpečné vykreslení tab funkcí.
    Pokud render_* funkce vyhodí výjimku, zobrazí user-friendly zprávu
    místo pádu celé aplikace.

    Args:
        fallback_message: Vlastní chybová zpráva (default: generická)
        show_traceback: Zobrazit technický traceback (defaultně False, jen pro dev)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.exception(f"Chyba v {func.__name__}")
                tb = traceback.format_exc()

                # Zobrazíme vlastní nebo defaultní zprávu
                st.error(
                    fallback_message or
                    f"⚠️ **Nastala chyba při vykreslování záložky** `{func.__name__}`.\n\n"
                    f"**Typ chyby:** `{type(e).__name__}`\n\n"
                    f"**Detail:** {str(e)[:200]}"
                )

                # Vždy logujeme traceback
                with st.expander("🔧 Technické detaily (pro vývojáře)"):
                    st.code(tb, language="python")

                if show_traceback:
                    st.exception(e)

                return None
        return wrapper
    return decorator


class ErrorBoundary:
    """
    Context manager pro bezpečné provádění kódu v rámci jedné sekce.

    Použití:
        with ErrorBoundary("Výpočet dashboardu"):
            # riskantní kód
            ...
    """

    def __init__(self, section_name: str, level: str = "warning"):
        self.section_name = section_name
        self.level = level
        self._has_error = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self._has_error = True
            logger.exception(f"Chyba v sekci '{self.section_name}'")
            tb = traceback.format_exc()

            if self.level == "error":
                st.error(f"❌ **Chyba v sekci:** {self.section_name}")
            else:
                st.warning(f"⚠️ **Problém v sekci:** {self.section_name}")

            st.caption(f"`{exc_type.__name__}`: {str(exc_val)[:200]}")
            with st.expander("🔧 Technické detaily"):
                st.code(tb, language="python")

            # Potlačíme výjimku (return True), aby aplikace pokračovala
            return True
        return False


def show_no_data_warning(message: str = "Žádná data k zobrazení."):
    """Zobrazí standardizovanou info zprávu o prázdných datech."""
    st.info(f"ℹ️ {message}")


def show_loading_state(text: str = "Načítám data..."):
    """Vrátí context manager pro loading stav s try/except ochranou."""
    return st.spinner(text)


def validate_dataframe(df: Any, name: str = "data") -> bool:
    """
    Ověří, že DF existuje a není prázdný. Zobrazí warning pokud ne.
    Vrací True pokud data OK, False pokud chybí.
    """
    if df is None:
        st.warning(f"⚠️ **{name}**: Data nebyla načtena (None).")
        return False
    if hasattr(df, 'empty') and df.empty:
        st.warning(f"⚠️ **{name}**: Data jsou prázdná.")
        return False
    return True


def safe_get(df: pd.DataFrame, column: str, default=None):
    """Bezpečně získá sloupec z DataFrame, vrátí default pokud neexistuje."""
    if df is None or column not in df.columns:
        return default
    return df[column]


def safe_select_column(df: pd.DataFrame, *candidates: str) -> Optional[str]:
    """
    Najde první existující sloupec z kandidátů v DataFrame.
    Bezpečná alternativa k opakovaným next() výrazům.
    """
    if df is None or df.empty:
        return None
    return next((c for c in candidates if c in df.columns), None)


def safe_number_format(value, decimals: int = 0) -> str:
    """Formátuje číslo bezpečně (i pro None/NaN/string)."""
    try:
        if value is None:
            return "-"
        if isinstance(value, str):
            return value
        if pd.isna(value):
            return "-"
        if decimals == 0:
            return f"{int(value):,}".replace(",", " ")
        return f"{float(value):,.{decimals}f}".replace(",", " ")
    except (ValueError, TypeError):
        return str(value)