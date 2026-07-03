"""
Testy pro apply_chart_defaults - helper pro Plotly layout.

Pokrývá:
- Základní použití (bez overrides)
- Override xaxis/yaxis
- Více os (yaxis2, yaxis3)
- Zachování extra kwargs (title, height, barmode)
"""
import pytest

from modules.utils import apply_chart_defaults


class TestApplyChartDefaults:
    """Testy pro apply_chart_defaults() - chart layout helper."""

    def test_basic_kwargs(self):
        """Bez overrides - vrátí dict s xaxis/yaxis defaulty."""
        result = apply_chart_defaults()
        assert 'xaxis' in result
        assert 'yaxis' in result
        assert isinstance(result['xaxis'], dict)
        assert isinstance(result['yaxis'], dict)

    def test_title_passed_through(self):
        """title= se musí zachovat v result."""
        result = apply_chart_defaults(title="Můj graf", height=450)
        assert result['title'] == "Můj graf"
        assert result['height'] == 450

    def test_xaxis_override(self):
        """xaxis override se merguje s defaulty."""
        result = apply_chart_defaults(xaxis=dict(type='category'))
        assert result['xaxis']['type'] == 'category'
        assert result['xaxis']['showgrid'] == False  # default zachován

    def test_yaxis_override_preserves_defaults(self):
        """yaxis override zachovává defaulty."""
        result = apply_chart_defaults(yaxis=dict(title='Počet'))
        assert result['yaxis']['title'] == 'Počet'
        assert result['yaxis']['gridcolor'] == 'rgba(255, 255, 255, 0.05)'

    def test_multiple_axes(self):
        """yaxis2 a yaxis3 se přidávají."""
        result = apply_chart_defaults(
            yaxis=dict(title='Primární'),
            yaxis2=dict(title='Sekundární', side='right'),
            yaxis3=dict(title='Terciární', position=0.92),
        )
        assert result['yaxis']['title'] == 'Primární'
        assert result['yaxis2']['title'] == 'Sekundární'
        assert result['yaxis2']['side'] == 'right'
        assert result['yaxis3']['title'] == 'Terciární'

    def test_multiple_kwargs(self):
        """Více kwargs najednou - title, height, barmode."""
        result = apply_chart_defaults(
            title="Multi",
            height=600,
            barmode='group',
            xaxis=dict(type='category'),
        )
        assert result['title'] == "Multi"
        assert result['height'] == 600
        assert result['barmode'] == 'group'
        assert result['xaxis']['type'] == 'category'

    def test_does_not_mutate_input(self):
        """Funkce nesmí mutovat vstupní kwargs (žádný vedlejší efekt)."""
        overrides = {'title': 'Test', 'xaxis': {'type': 'category'}}
        apply_chart_defaults(**overrides)
        # overrides by měly být nezměněné
        assert 'xaxis' in overrides
        assert 'type' in overrides['xaxis']

    def test_real_world_monthly_kpi(self):
        """Reálný případ z tab_monthly_kpi.py - musí fungovat."""
        result = apply_chart_defaults(
            yaxis=dict(title='TO'),
            yaxis2=dict(title='Kusy / TO', overlaying='y', side='right', showgrid=False),
            yaxis3=dict(title='% Přesně', overlaying='y', side='right',
                       position=0.92, showgrid=False, range=[0, 105]),
            title=None,
            height=450,
        )
        assert result['yaxis']['title'] == 'TO'
        assert result['yaxis2']['title'] == 'Kusy / TO'
        assert result['yaxis3']['range'] == [0, 105]
        assert result['height'] == 450
        assert result['title'] is None

    def test_empty_dict_overrides_kept(self):
        """Prázdný dict jako override by měl být ignorován (nebo zachován)."""
        result = apply_chart_defaults(xaxis={}, yaxis={})
        # Měly by být prázdné, ne None
        assert result['xaxis'] == {}
        assert result['yaxis'] == {}


# ==========================================
# REGRESNÍ TESTY
# ==========================================
class TestRegressions:
    """Regrese - testy na chyby které se vyskytly v produkci."""

    def test_does_not_raise_missing_fig_error(self):
        """REGRESE: dříve vyhazovalo 'missing 1 required positional argument: fig'."""
        try:
            result = apply_chart_defaults(title="Test")
            assert result is not None
        except TypeError as e:
            if "missing" in str(e) and "positional" in str(e):
                pytest.fail(f"REGRESE: API se vrátilo ke staré verzi vyžadující fig: {e}")
            raise

    def test_kwargs_not_lost_after_pop(self):
        """REGRESE: dříve se title/height ztrácaly po .pop() na xaxis/yaxis."""
        # Toto je klíčový test - kwargs MUSÍ zůstat
        for kwargs in [
            {'title': 'A', 'height': 100},
            {'title': 'B', 'barmode': 'group', 'height': 200},
            {'xaxis': {'type': 'category'}, 'title': 'C', 'height': 300},
        ]:
            result = apply_chart_defaults(**kwargs)
            # Všechny extra kwargs musí být v resultu
            for key, val in kwargs.items():
                if key not in ('xaxis', 'yaxis', 'yaxis2', 'yaxis3'):
                    assert result[key] == val, \
                        f"Klíč {key}={val} se ztratil z result!"