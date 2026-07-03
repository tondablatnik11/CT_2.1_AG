"""
Měsíční KPI - Dashboard pro sledování měsíčních cílů a KPI.

Zaměřeno na:
- Měsíční trendy v produktivitě
- Plnění cílů (TO, HU, kusů)
- Srovnání měsíců mezi sebou
- Heatmapy zátěže
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from modules.utils import t, CHART_LAYOUT, CHART_COLORS, safe_del, safe_hu
from modules.safe_render import ErrorBoundary, validate_dataframe

try:
    fast_render = st.fragment
except AttributeError:
    fast_render = lambda f: f


@fast_render
def render_monthly_kpi(df_pick, raw_vekp, raw_vepo):
    """Hlavní renderer pro Měsíční KPI záložku."""
    def _t(cs, en):
        return en if st.session_state.get('lang', 'cs') == 'en' else cs

    st.markdown(
        f"<div class='section-header'>"
        f"<h3>📅 {_t('Měsíční KPI & Cíle', 'Monthly KPI & Targets')}</h3>"
        f"<p>{_t('Sledování měsíčních cílů a trendů. Identifikace sezónnosti, plnění plánu a oblastí pro zlepšení.', 'Monthly target tracking and trend analysis. Identify seasonality, plan fulfillment, and improvement areas.')}</p>"
        f"</div>",
        unsafe_allow_html=True
    )

    if not validate_dataframe(df_pick, "Pick Report"):
        return

    # Zajistíme, že máme Month sloupec
    if 'Month' not in df_pick.columns:
        if 'Date' in df_pick.columns:
            df_pick = df_pick.copy()
            df_pick['Month'] = df_pick['Date'].dt.to_period('M').astype(str).replace('NaT', _t('Neznámé', 'Unknown'))
        else:
            st.warning(_t("Data neobsahují informace o měsíci.", "Data does not contain month information."))
            return

    # === KONFIGURACE CÍLŮ ===
    with st.expander(_t("🎯 Nastavit měsíční cíle", "🎯 Set monthly targets"), expanded=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            target_to = st.number_input(_t("Cíl: TO / měsíc", "Target: TOs / month"), min_value=0, value=5000, step=500)
        with c2:
            target_qty = st.number_input(_t("Cíl: Kusů / měsíc", "Target: Pcs / month"), min_value=0, value=100000, step=10000)
        with c3:
            target_moves = st.number_input(_t("Cíl: Pohybů / měsíc", "Target: Moves / month"), min_value=0, value=50000, step=5000)

    # === MĚSÍČNÍ AGREGACE ===
    with ErrorBoundary("Agregace měsíčních KPI"):
        # Určení sloupce pro unikátní zakázky
        to_col = 'Transfer Order Number' if 'Transfer Order Number' in df_pick.columns else 'Delivery'

        monthly_agg = df_pick.groupby('Month', observed=True).agg(
            total_to=(to_col, 'nunique'),
            total_orders=('Delivery', 'nunique'),
            total_qty=('Qty', 'sum'),
            total_moves=('Pohyby_Rukou', 'sum') if 'Pohyby_Rukou' in df_pick.columns else ('Qty', 'count'),
            total_exact=('Pohyby_Exact', 'sum') if 'Pohyby_Exact' in df_pick.columns else ('Qty', 'count'),
            total_miss=('Pohyby_Loose_Miss', 'sum') if 'Pohyby_Loose_Miss' in df_pick.columns else ('Qty', 'count'),
            total_materials=('Material', 'nunique'),
            total_locations=('Source Storage Bin', 'nunique'),
        ).reset_index().sort_values('Month')

        monthly_agg['pct_exact'] = np.where(
            monthly_agg['total_moves'] > 0,
            monthly_agg['total_exact'] / monthly_agg['total_moves'] * 100, 0
        )
        monthly_agg['avg_qty_per_to'] = np.where(
            monthly_agg['total_to'] > 0,
            monthly_agg['total_qty'] / monthly_agg['total_to'], 0
        )
        monthly_agg['avg_moves_per_loc'] = np.where(
            monthly_agg['total_locations'] > 0,
            monthly_agg['total_moves'] / monthly_agg['total_locations'], 0
        )

    # === HLAVNÍ METRIKY (poslední měsíc) ===
    if not monthly_agg.empty:
        latest = monthly_agg.iloc[-1]
        prev = monthly_agg.iloc[-2] if len(monthly_agg) > 1 else None

        st.markdown(f"### 📊 {_t('Poslední měsíc:', 'Latest month:')} **{latest['Month']}**")

        def _delta(curr, prev_val):
            if prev_val is None or pd.isna(prev_val) or prev_val == 0:
                return None
            return f"{(curr - prev_val) / prev_val * 100:+.1f}%"

        k1, k2, k3, k4 = st.columns(4)
        with k1:
            st.metric(
                _t("Celkem TO", "Total TOs"),
                f"{int(latest['total_to']):,}",
                delta=_delta(latest['total_to'], prev['total_to'] if prev is not None else None)
            )
        with k2:
            st.metric(
                _t("Celkem kusů", "Total Pieces"),
                f"{int(latest['total_qty']):,}",
                delta=_delta(latest['total_qty'], prev['total_qty'] if prev is not None else None)
            )
        with k3:
            st.metric(
                _t("Fyzických pohybů", "Physical Moves"),
                f"{int(latest['total_moves']):,}",
                delta=_delta(latest['total_moves'], prev['total_moves'] if prev is not None else None)
            )
        with k4:
            st.metric(
                _t("% Přesně", "% Exact"),
                f"{latest['pct_exact']:.1f}%",
                delta=_delta(latest['pct_exact'], prev['pct_exact'] if prev is not None else None)
            )

    st.divider()

    # === PLNĚNÍ CÍLŮ ===
    st.markdown(f"### 🎯 {_t('Plnění měsíčních cílů', 'Monthly Target Fulfillment')}")
    if not monthly_agg.empty:
        latest = monthly_agg.iloc[-1]
        target_data = [
            ("TO", int(latest['total_to']), target_to),
            ("Kusy", int(latest['total_qty']), target_qty),
            ("Pohyby", int(latest['total_moves']), target_moves),
        ]

        fig_target = go.Figure()
        for label, actual, target in target_data:
            pct = (actual / target * 100) if target > 0 else 0
            fig_target.add_trace(go.Bar(
                y=[label],
                x=[actual],
                name=label,
                orientation='h',
                marker_color='#10b981' if pct >= 100 else ('#f59e0b' if pct >= 75 else '#ef4444'),
                text=f"{actual:,} / {target:,} ({pct:.0f}%)",
                textposition='inside',
                hovertemplate=f"<b>{label}</b><br>Actual: {actual:,}<br>Target: {target:,}<br>Fulfillment: {pct:.1f}%<extra></extra>"
            ))

        fig_target.update_layout(
            **CHART_LAYOUT,
            title=_t("Aktuální plnění vs. cíl", "Current fulfillment vs. target"),
            xaxis_title=_t("Hodnota", "Value"),
            height=300,
            showlegend=False,
        )
        st.plotly_chart(fig_target, width="stretch")

    # === TRENDOVÝ GRAF ===
    st.divider()
    st.markdown(f"### 📈 {_t('Vývoj klíčových metrik v čase', 'Key Metrics Trend Over Time')}")

    if not monthly_agg.empty:
        # Multi-trace graf
        fig_trend = go.Figure()

        fig_trend.add_trace(go.Bar(
            x=monthly_agg['Month'],
            y=monthly_agg['total_to'],
            name=_t('Počet TO', 'Total TOs'),
            marker_color='#3b82f6',
            yaxis='y'
        ))
        fig_trend.add_trace(go.Scatter(
            x=monthly_agg['Month'],
            y=monthly_agg['avg_qty_per_to'],
            name=_t('Prům. kusů / TO', 'Avg Pcs / TO'),
            mode='lines+markers',
            marker_color='#f59e0b',
            line=dict(width=3),
            yaxis='y2'
        ))
        fig_trend.add_trace(go.Scatter(
            x=monthly_agg['Month'],
            y=monthly_agg['pct_exact'],
            name=_t('% Přesně', '% Exact'),
            mode='lines+markers',
            marker_color='#10b981',
            line=dict(width=3, dash='dot'),
            yaxis='y3'
        ))

        fig_trend.update_layout(
            **CHART_LAYOUT,
            yaxis=dict(title=_t('TO', 'TOs')),
            yaxis2=dict(title=_t('Kusy / TO', 'Pcs / TO'), overlaying='y', side='right', showgrid=False),
            yaxis3=dict(title=_t('% Přesně', '% Exact'), overlaying='y', side='right', position=0.92, showgrid=False, range=[0, 105]),
            title=None,
            height=450,
        )
        st.plotly_chart(fig_trend, width="stretch")

    # === HEATMAPA ZÁTĚŽE (Queue vs Month) ===
    st.divider()
    st.markdown(f"### 🔥 {_t('Heatmapa: Které fronty vás v kterém měsíci nejvíce zatěžují', 'Heatmap: Which queues load you most each month')}")

    if 'Queue' in df_pick.columns and 'Pohyby_Rukou' in df_pick.columns:
        with ErrorBoundary("Heatmapa Queue x Month"):
            heat_df = df_pick.groupby(['Month', 'Queue'], observed=True)['Pohyby_Rukou'].sum().reset_index()
            heat_pivot = heat_df.pivot(index='Queue', columns='Month', values='Pohyby_Rukou').fillna(0)

            # Top 15 queues podle celkové zátěže
            top_queues = heat_pivot.sum(axis=1).nlargest(15).index
            heat_pivot = heat_pivot.loc[top_queues]

            fig_heat = px.imshow(
                heat_pivot.values,
                x=heat_pivot.columns,
                y=heat_pivot.index,
                color_continuous_scale='Inferno',
                labels=dict(x=_t("Měsíc", "Month"), y=_t("Queue", "Queue"),
                            color=_t("Pohybů", "Moves")),
                aspect='auto',
            )
            fig_heat.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                height=max(400, len(top_queues) * 28),
            )
            st.plotly_chart(fig_heat, width="stretch")

    # === TOP MATERIÁLY V MĚSÍCI ===
    st.divider()
    st.markdown(f"### 🏆 {_t('TOP 10 Materiálů v posledním měsíci', 'TOP 10 Materials in Latest Month')}")

    if not monthly_agg.empty and 'Material' in df_pick.columns and 'Pohyby_Rukou' in df_pick.columns:
        latest_month = monthly_agg.iloc[-1]['Month']
        latest_pick = df_pick[df_pick['Month'] == latest_month]

        if not latest_pick.empty:
            top_mat = latest_pick.groupby('Material', observed=True).agg(
                moves=('Pohyby_Rukou', 'sum'),
                qty=('Qty', 'sum'),
                to_count=('Transfer Order Number' if 'Transfer Order Number' in latest_pick.columns else 'Delivery', 'nunique'),
            ).reset_index().sort_values('moves', ascending=False).head(10)

            top_mat.columns = [_t("Materiál", "Material"), _t("Pohybů", "Moves"),
                               _t("Kusů", "Pcs"), _t("Počet TO", "TO Count")]
            st.dataframe(top_mat, width="stretch", hide_index=True)
        else:
            st.info(_t("Žádná data v posledním měsíci.", "No data in latest month."))