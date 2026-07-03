"""
Testy pro modules/safe_render.py - error handling dekorátory.

Pokrývá:
- @safe_render dekorátor
- ErrorBoundary context manager
- validate_dataframe helper
"""
import pytest
import pandas as pd
import streamlit as st

from modules.safe_render import (
    safe_render,
    ErrorBoundary,
    validate_dataframe,
    show_no_data_warning,
    safe_select_column,
    safe_number_format,
)


class TestSafeRenderDecorator:
    """Testy pro @safe_render dekorátor."""

    def test_no_error_passes_through(self):
        """Bez výjimky - výsledek se vrátí normálně."""
        @safe_render()
        def good_function():
            return "OK"

        result = good_function()
        assert result == "OK"

    def test_error_caught_with_default_message(self):
        """S výjimkou - zobrazí fallback_message (v testu nekontrolujeme UI)."""
        @safe_render(fallback_message="Test fallback")
        def bad_function():
            raise ValueError("Test error")

        # Funkce nesmí vyhodit výjimku
        result = bad_function()
        assert result is None  # Při chybě vrací None

    def test_error_with_args(self):
        """Dekorátor propouští argumenty."""
        @safe_render()
        def multiply(a, b):
            return a * b

        result = multiply(3, 4)
        assert result == 12

    def test_error_with_kwargs(self):
        """Dekorátor propouští kwargs."""
        @safe_render()
        def greet(name="World"):
            return f"Hello, {name}!"

        result = greet(name="Alice")
        assert result == "Hello, Alice!"

    def test_preserves_function_metadata(self):
        """functools.wraps zachová název a docstring."""
        @safe_render()
        def my_function():
            """My docstring."""
            return 42

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "My docstring."


class TestErrorBoundary:
    """Testy pro ErrorBoundary context manager."""

    def test_no_error(self):
        """Bez výjimky - normální průchod."""
        with ErrorBoundary("test"):
            x = 1 + 1
        assert x == 2

    def test_error_caught(self):
        """S výjimkou - chyba se zachytí."""
        try:
            with ErrorBoundary("test_section"):
                raise ValueError("test error")
            assert True  # Pokud se dostaneme sem, je to OK
        except ValueError:
            pytest.fail("ErrorBoundary měl zachytit ValueError")

    def test_returns_none_state(self):
        """Po chybě lze zjistit stav."""
        boundary = ErrorBoundary("test")
        with boundary:
            raise RuntimeError("oops")
        assert boundary._has_error is True


class TestValidateDataframe:
    """Testy pro validate_dataframe helper."""

    def test_valid_dataframe(self):
        """Validní DF -> True (bez warningu)."""
        df = pd.DataFrame({"a": [1, 2, 3]})
        # V testu nekontrolujeme UI výstup, jen nepřítomnost False
        result = validate_dataframe(df, "test")
        assert result is True

    def test_none_dataframe(self):
        """None -> False."""
        result = validate_dataframe(None, "test")
        assert result is False

    def test_empty_dataframe(self):
        """Prázdný DF -> False."""
        df = pd.DataFrame()
        result = validate_dataframe(df, "test")
        assert result is False

    def test_empty_dataframe_with_columns(self):
        """DF se sloupci ale bez řádků -> False."""
        df = pd.DataFrame(columns=["a", "b"])
        result = validate_dataframe(df, "test")
        assert result is False


class TestSafeSelectColumn:
    """Testy pro safe_select_column."""

    def test_column_exists(self):
        df = pd.DataFrame({"a": [1], "b": [2]})
        assert safe_select_column(df, "a", "b", "c") == "a"

    def test_column_not_exists(self):
        df = pd.DataFrame({"a": [1]})
        assert safe_select_column(df, "x", "y", "z") is None

    def test_empty_df(self):
        assert safe_select_column(pd.DataFrame(), "a") is None

    def test_none_df(self):
        assert safe_select_column(None, "a") is None


class TestSafeNumberFormat:
    """Testy pro safe_number_format."""

    def test_integer(self):
        result = safe_number_format(1234567)
        assert "1 234 567" in result  # CZ locale oddělovač

    def test_float(self):
        result = safe_number_format(1234.56, decimals=2)
        assert "1 234" in result

    def test_none(self):
        assert safe_number_format(None) == "-"

    def test_nan(self):
        import math
        assert safe_number_format(math.nan) == "-"

    def test_string_passthrough(self):
        assert safe_number_format("custom") == "custom"


# ==========================================
# INTEGRAČNÍ TESTY
# ==========================================
class TestIntegration:
    """Integrační testy kombinující dekorátory a helpers."""

    def test_safe_render_with_validate(self):
        """Kombinace safe_render + validate_dataframe."""

        @safe_render()
        def render_section(df):
            if not validate_dataframe(df, "test"):
                return None
            return df.shape[0]

        # Prázdný DF
        result = render_section(pd.DataFrame())
        assert result is None

        # Validní DF
        result = render_section(pd.DataFrame({"a": [1, 2, 3]}))
        assert result == 3

    def test_multiple_decorators_compose(self):
        """safe_render chrání vnořené chyby."""

        @safe_render()
        def outer():
            @safe_render()
            def inner():
                raise RuntimeError("inner error")
            return inner()

        # Vnější dekorátor chytí i chybu z vnitřního
        result = outer()
        assert result is None