"""
TOP Materiály - analýza nejnáročnějších a nejčastěji pickovaných materiálů.
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from modules.utils import t, CHART_LAYOUT, CHART_COLORS
from modules.safe_render import ErrorBoundary, validate_dataframe, safe_render


CHART_LAYOUT_LOCAL = dict(
    paper_bgcolor='rgba(0,0,0,0)',
    plot_bgcolor='rgba(0,0,0,0)',
    font=dict(color='#f8fafc', size=12, family="Inter, sans-serif"),
    margin=dict(l=0, r=0, t=40, b=0),
    legend=dict(orientation='h', yanchor='bottom', y=1.05, xanchor='left', x=0, bgcolor='rgba(0,0,0,0)'),
    hovermode="x unified"
)


@safe_render(fallback_message="⚠️ Chyba při vykreslování TOP Materiálů")
def render_top(df_pick):
    """Hlavní renderer TOP Materiálů."""
    def _t(cs, en):
        return en if st.session_state.get('lang', 'cs') == 'en' else cs

    if not validate_dataframe(df_pick, "Pick Report"):
        return

    st.markdown(
        f"<div class='section-header'>"
        f"<h3>🏆 {_t('Materiály (TOP)', 'Top Materials')}</h3>"
        f"<p>{_t('Přehled nejčastěji vychystávaných materiálů podle fyzické náročnosti a počtu zakázek.', 'Overview of the most frequently picked materials based on physical effort and TO count.')}</p>"
        f"</div>",
        unsafe_allow_html=True
    )

    if df_pick is None or df_pick.empty:
        st.info(_t("Žádná data nejsou k dispozici.", "No data available."))
        return

    # Bezpečná detekce sloupce pro zakázky (TO)
    to_col = 'Transfer Order Number' if 'Transfer Order Number' in df_pick.columns else 'Delivery'

    with ErrorBoundary("Agregace TOP Materiálů"):
        # 1) Agregace všech dat za materiály
        mat_agg = df_pick.groupby('Material', observed=True).agg(
            Moves=('Pohyby_Rukou', 'sum'),
            Exact=('Pohyby_Exact', 'sum'),
            Miss=('Pohyby_Loose_Miss', 'sum'),
            Qty=('Qty', 'sum'),
            TO_Count=(to_col, 'nunique'),
            Lines=('Material', 'count')
        ).reset_index()

        # Výpočet statistik kvality dat
        total_mats = len(mat_agg)
        exact_mats = int((mat_agg['Miss'] == 0).sum())
        est_mats = int((mat_agg['Miss'] > 0).sum())

        pct_exact = (exact_mats / total_mats * 100) if total_mats > 0 else 0
        pct_est = (est_mats / total_mats * 100) if total_mats > 0 else 0

        # Zobrazení statistik
        st.markdown(f"#### 📊 {_t('Kvalita dat a pokrytí materiálů', 'Data Quality and Material Coverage')}")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric(_t("Celkem unikátních materiálů", "Total Unique Materials"), f"{total_mats:,}")
        with c2:
            st.metric(
                _t("Přesná data z master dat", "Exact Data from Master"),
                f"{exact_mats:,}",
                delta=f"{pct_exact:.1f} %"
            )
        with c3:
            st.metric(
                _t("Vyžadující odhad", "Requiring Estimate"),
                f"{est_mats:,}",
                delta=f"-{pct_est:.1f} %",
                delta_color="inverse"
            )

        st.divider()

        # === 3 ZÁLOŽKY ===
        tab1, tab2, tab3 = st.tabs([
            f"💪 {_t('TOP 500: Podle pohybů', 'TOP 500: By Moves')}",
            f"📦 {_t('TOP 500: Podle zakázek (TO)', 'TOP 500: By TOs')}",
            f"⚠️ {_t('TOP 500: Odhady', 'TOP 500: Estimates')}"
        ])

        with tab1:
            _render_top_moves(mat_agg, _t)

        with tab2:
            _render_top_tos(mat_agg, _t)

        with tab3:
            _render_top_estimates(mat_agg, _t)


def _format_table(df):
    """Pomocná funkce pro formátování tabulky."""
    def _t(cs, en):
        return en if st.session_state.get('lang', 'cs') == 'en' else cs

    disp = df[['Material', 'Moves', 'TO_Count', 'Qty', 'Exact', 'Miss', 'Lines']].copy()
    disp.columns = [
        _t("Materiál", "Material"),
        _t("Celkem Pohybů", "Total Moves"),
        _t("Počet TO", "TO Count"),
        _t("Vychystáno kusů", "Picked Qty"),
        _t("Přesné pohyby", "Exact Moves"),
        _t("Odhady (Miss)", "Estimates (Miss)"),
        _t("Řádků v reportu", "Lines in Report")
    ]
    return disp


def _make_bar_chart(df, x_col, y_col, title, color='#3b82f6'):
    """Vytvoří bar chart s kategoriální osou X (prevence Plotly numeric parsing)."""
    fig = go.Figure()
    x_vals = df[x_col].astype(str)  # Force string for category axis
    fig.add_trace(go.Bar(
        x=x_vals, y=df[y_col],
        marker_color=color,
        text=df[y_col].apply(lambda x: f"{x:,.0f}"),
        textposition='auto',
        name=title,
    ))
    fig.update_layout(**CHART_LAYOUT_LOCAL)
    fig.update_layout(
        title=title,
        xaxis_title="Materiál", yaxis_title="",
        xaxis=dict(type='category')
    )
    return fig


def _render_top_moves(mat_agg, _t):
    """TOP 500 podle fyzických pohybů."""
    st.markdown(
        f"**{_t('Nejnáročnější materiály z hlediska fyzické práce.', 'Most demanding materials in terms of physical effort.')}**"
    )
    top_moves = mat_agg.sort_values('Moves', ascending=False).head(500)

    # Lokální statistika
    t1_len = len(top_moves)
    t1_exact = int((top_moves['Miss'] == 0).sum())
    t1_est = int((top_moves['Miss'] > 0).sum())
    p1_exact = (t1_exact / t1_len * 100) if t1_len > 0 else 0
    p1_est = (t1_est / t1_len * 100) if t1_len > 0 else 0

    cs1, cs2 = st.columns(2)
    cs1.success(f"✅ **{_t('Přesná data u tohoto TOP', 'Exact data in this TOP')} {t1_len}:** {t1_exact} ({p1_exact:.1f} %)")
    cs2.warning(f"⚠️ **{_t('Odhady u tohoto TOP', 'Estimates in this TOP')} {t1_len}:** {t1_est} ({p1_est:.1f} %)")

    col_t1, col_g1 = st.columns([1.1, 1])
    with col_t1:
        st.dataframe(_format_table(top_moves), use_container_width=True, hide_index=True)
    with col_g1:
        st.plotly_chart(
            _make_bar_chart(top_moves.head(15), 'Material', 'Moves',
                            _t("TOP 15 dle fyzických pohybů", "TOP 15 by Physical Moves"),
                            '#3b82f6'),
            use_container_width=True
        )


def _render_top_tos(mat_agg, _t):
    """TOP 500 podle počtu TO."""
    st.markdown(
        f"**{_t('Nejfrekventovanější materiály (nejvíce zastávek skladníka u regálu).', 'Most frequent materials.')}**"
    )
    top_tos = mat_agg.sort_values('TO_Count', ascending=False).head(500)

    t2_len = len(top_tos)
    t2_exact = int((top_tos['Miss'] == 0).sum())
    t2_est = int((top_tos['Miss'] > 0).sum())
    p2_exact = (t2_exact / t2_len * 100) if t2_len > 0 else 0
    p2_est = (t2_est / t2_len * 100) if t2_len > 0 else 0

    cs3, cs4 = st.columns(2)
    cs3.success(f"✅ **{_t('Přesná data u tohoto TOP', 'Exact data in this TOP')} {t2_len}:** {t2_exact} ({p2_exact:.1f} %)")
    cs4.warning(f"⚠️ **{_t('Odhady u tohoto TOP', 'Estimates in this TOP')} {t2_len}:** {t2_est} ({p2_est:.1f} %)")

    col_t2, col_g2 = st.columns([1.1, 1])
    with col_t2:
        st.dataframe(_format_table(top_tos), use_container_width=True, hide_index=True)
    with col_g2:
        st.plotly_chart(
            _make_bar_chart(top_tos.head(15), 'Material', 'TO_Count',
                            _t("TOP 15 dle počtu zakázek (TO)", "TOP 15 by Order Count"),
                            '#10b981'),
            use_container_width=True
        )


def _render_top_estimates(mat_agg, _t):
    """TOP 500 podle odhadovaných pohybů (chybějící master data)."""
    st.markdown(
        f"**{_t('Materiály, kterým chybí master data a systém jejich fyzickou náročnost odhaduje.', 'Materials missing master data whose effort is estimated.')}**"
    )

    est_df = mat_agg[mat_agg['Miss'] > 0].copy()
    if est_df.empty:
        st.success(_t(
            "Skvělá zpráva! Všechny vaše materiály mají perfektní master data.",
            "Great news! All your materials have perfect master data."
        ))
        return

    sort_opt = st.radio(
        _t("Seřadit žebříček podle:", "Sort ranking by:"),
        options=[
            _t("Počtu zakázek (TO_Count)", "Order Count (TO_Count)"),
            _t("Odhadnutých pohybů (Miss)", "Estimated Moves (Miss)")
        ],
        horizontal=True,
        key="top_estimates_sort"
    )

    if sort_opt == _t("Odhadnutých pohybů (Miss)", "Estimated Moves (Miss)"):
        top_est = est_df.sort_values('Miss', ascending=False).head(500)
        y_col_chart = 'Miss'
        chart_title = _t("TOP 15 chybějících dat (dle dopadu na pohyby)", "TOP 15 Missing Data (by impact)")
        chart_color = '#ef4444'
    else:
        top_est = est_df.sort_values('TO_Count', ascending=False).head(500)
        y_col_chart = 'TO_Count'
        chart_title = _t("TOP 15 chybějících dat (dle frekvence TO)", "TOP 15 Missing Data (by frequency)")
        chart_color = '#f59e0b'

    col_t3, col_g3 = st.columns([1.1, 1])
    with col_t3:
        st.dataframe(_format_table(top_est), use_container_width=True, hide_index=True)
    with col_g3:
        st.plotly_chart(
            _make_bar_chart(top_est.head(15), 'Material', y_col_chart, chart_title, chart_color),
            use_container_width=True
        )