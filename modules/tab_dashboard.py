"""
Dashboard & Queue Analysis - hlavní přehledová stránka.
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from modules.utils import t, QUEUE_DESC, CHART_LAYOUT, CHART_COLORS, apply_chart_defaults
from modules.safe_render import ErrorBoundary, validate_dataframe, safe_render


@safe_render(fallback_message="⚠️ Chyba při vykreslování Dashboardu")
def render_dashboard(df_pick, queue_count_col):
    """Hlavní vstupní dashboard."""
    def _t(cs, en):
        return en if st.session_state.get('lang', 'cs') == 'en' else cs

    if not validate_dataframe(df_pick, "Pick Report"):
        return None

    # === 1) KVALITA DAT ===
    _render_data_quality(df_pick, _t)

    # === 2) TABULKA PRŮMĚRNÉ NÁROČNOSTI ===
    disp_q = _render_queue_table(df_pick, queue_count_col, _t)

    # === 3) TREND GRAF ===
    _render_trend_chart(df_pick, queue_count_col, _t)

    return disp_q


def _render_data_quality(df_pick, _t):
    """Sekce: Spolehlivost dat a zdroje výpočtů."""
    st.markdown(
        f"<div class='section-header'>"
        f"<h3>{t('sec_ratio')}</h3>"
        f"<p>{t('ratio_desc')}</p>"
        f"</div>",
        unsafe_allow_html=True
    )

    with ErrorBoundary("Výpočet kvality dat"):
        total_moves = int(df_pick['Pohyby_Rukou'].sum())
        exact_moves = int(df_pick['Pohyby_Exact'].sum())
        miss_moves = int(df_pick['Pohyby_Loose_Miss'].sum())
        pct_exact = (exact_moves / total_moves * 100) if total_moves > 0 else 0
        pct_miss = (miss_moves / total_moves * 100) if total_moves > 0 else 0

        c1, c2, c3 = st.columns(3)
        c1.metric(t('ratio_moves'), f"{total_moves:,}")
        c2.metric(t('ratio_exact'), f"{exact_moves:,} ({pct_exact:.1f} %)")
        c3.metric(t('ratio_miss'), f"{miss_moves:,} ({pct_miss:.1f} %)")

        # Progress bary pro vizualizaci
        c1, c2 = st.columns(2)
        with c1:
            st.progress(pct_exact / 100, text=f"✅ {t('ratio_exact')}: {pct_exact:.1f} %")
        with c2:
            st.progress(pct_miss / 100, text=f"⚠️ {t('ratio_miss')}: {pct_miss:.1f} %")

    # === EXPANDER PRO MATERIÁLY S CHYBĚJÍCÍMI DATY ===
    with st.expander(t('exp_missing_data')):
        with ErrorBoundary("Tabulka chybějících dat"):
            miss_df = df_pick[df_pick['Pohyby_Loose_Miss'] > 0].groupby('Material', observed=True).agg(
                Odhad_Pohybu=('Pohyby_Loose_Miss', 'sum'),
                Kusu=('Qty', 'sum')
            ).reset_index().sort_values('Odhad_Pohybu', ascending=False)

            miss_df.columns = [_t("Materiál", "Material"),
                               _t("Odhadované pohyby (Miss)", "Estimated Moves (Miss)"),
                               _t("Kusů", "Quantity")]
            st.dataframe(miss_df, hide_index=True, width="stretch")


def _render_queue_table(df_pick, queue_count_col, _t):
    """Tabulka průměrné náročnosti dle Queue typu."""
    st.markdown(
        f"<div class='section-header'>"
        f"<h3>{t('sec_queue_title')}</h3>"
        f"</div>",
        unsafe_allow_html=True
    )

    with ErrorBoundary("Agregace Queue"):
        to_group = df_pick.groupby(queue_count_col, observed=True).agg(
            Queue=('Queue', 'first'),
            lokace_v_to=('Source Storage Bin', 'nunique'),
            kusy_v_to=('Qty', 'sum'),
            pohyby_v_to=('Pohyby_Rukou', 'sum'),
            exact_poh=('Pohyby_Exact', 'sum'),
            miss_poh=('Pohyby_Loose_Miss', 'sum'),
            pocet_mat=('Material', 'nunique'),
            Delivery=('Delivery', 'first')
        ).reset_index()

        # Split PI_PL a PI_PL_OE na Single/Mix
        queue_arr = to_group['Queue'].astype(str).str.strip().values
        num_mat_arr = to_group['pocet_mat'].values
        to_group['Queue_Split'] = [
            f"{q} (Single)" if q in ('PI_PL', 'PI_PL_OE') and nm <= 1
            else (f"{q} (Mix)" if q in ('PI_PL', 'PI_PL_OE') else q)
            for q, nm in zip(queue_arr, num_mat_arr)
        ]

        q_agg = to_group.groupby('Queue_Split', observed=True).agg(
            pocet_to=(queue_count_col, 'nunique'),
            zakazky=('Delivery', 'nunique'),
            lokace_celkem=('lokace_v_to', 'sum'),
            kusy_celkem=('kusy_v_to', 'sum'),
            pohyby_celkem=('pohyby_v_to', 'sum'),
            exact_celkem=('exact_poh', 'sum'),
            miss_celkem=('miss_poh', 'sum')
        ).reset_index()

        # Vypočtené metriky - vektorově
        q_agg['prum_lok_to'] = np.where(q_agg['pocet_to'] > 0, q_agg['lokace_celkem'] / q_agg['pocet_to'], 0)
        q_agg['prum_ks_to'] = np.where(q_agg['pocet_to'] > 0, q_agg['kusy_celkem'] / q_agg['pocet_to'], 0)
        q_agg['prum_poh_lok'] = np.where(q_agg['lokace_celkem'] > 0, q_agg['pohyby_celkem'] / q_agg['lokace_celkem'], 0)
        q_agg['prum_exact_lok'] = np.where(q_agg['lokace_celkem'] > 0, q_agg['exact_celkem'] / q_agg['lokace_celkem'], 0)
        q_agg['prum_miss_lok'] = np.where(q_agg['lokace_celkem'] > 0, q_agg['miss_celkem'] / q_agg['lokace_celkem'], 0)
        q_agg['pct_exact'] = np.where(q_agg['pohyby_celkem'] > 0, q_agg['exact_celkem'] / q_agg['pohyby_celkem'] * 100, 0)
        q_agg['pct_miss'] = np.where(q_agg['pohyby_celkem'] > 0, q_agg['miss_celkem'] / q_agg['pohyby_celkem'] * 100, 0)

        # Mapování popisků
        q_agg['Queue_Desc'] = q_agg['Queue_Split'].map(QUEUE_DESC).fillna(t('unknown'))

        disp_q = q_agg[[
            'Queue_Split', 'Queue_Desc', 'pocet_to', 'zakazky',
            'prum_lok_to', 'prum_ks_to', 'prum_poh_lok',
            'prum_exact_lok', 'pct_exact', 'prum_miss_lok', 'pct_miss'
        ]].copy()

        # České/anglické názvy sloupců
        c_loc_to = _t("Průměr lokací (zastávek) / TO", "Avg Locations (Stops) / TO")
        c_ks_to = _t("Průměr kusů / TO", "Avg Qty / TO")
        c_poh_lok = _t("Průměr pohybů na 1 lokaci", "Avg Moves per 1 Location")
        c_ex_lok = _t("Pohyby přesně / lok.", "Exact Moves / Loc")
        c_mi_lok = _t("Pohyby odhad / lok.", "Estimated Moves / Loc")
        c_pct_ex = _t("% Přesně", "% Exact")
        c_pct_mi = _t("% Odhad", "% Estimated")

        disp_q.columns = [
            "Queue", _t("Popis fronty", "Queue Description"),
            _t("Počet TO", "Total TOs"),
            _t("Zasažených zakázek", "Affected Orders"),
            c_loc_to, c_ks_to, c_poh_lok, c_ex_lok, c_pct_ex, c_mi_lok, c_pct_mi
        ]

        # Formátovaná tabulka
        try:
            styled_q = disp_q.style.format({
                c_loc_to: "{:.1f}", c_ks_to: "{:.1f}", c_poh_lok: "{:.2f}",
                c_ex_lok: "{:.2f}", c_mi_lok: "{:.2f}",
                c_pct_ex: "{:.1f}%", c_pct_mi: "{:.1f}%"
            })
        except Exception:
            styled_q = disp_q

        st.dataframe(styled_q, hide_index=True, width="stretch")
        return disp_q


def _render_trend_chart(df_pick, queue_count_col, _t):
    """Trendový graf náročnosti v čase podle Queue."""
    st.markdown(
        f"<div class='section-header'>"
        f"<h3>📈 {_t('Trend náročnosti v čase podle Queue', 'Effort Trend over Time by Queue')}</h3>"
        f"</div>",
        unsafe_allow_html=True
    )

    if 'Month' not in df_pick.columns:
        st.info(_t("Data neobsahují informace o měsíci.", "Data does not contain month information."))
        return

    with ErrorBoundary("Trend graf"):
        # Příprava dat - jednou, efektivně
        to_group = df_pick.groupby(queue_count_col, observed=True).agg(
            Queue_Split=('Queue', 'first'),
            lokace=('Source Storage Bin', 'nunique'),
            pohyby=('Pohyby_Rukou', 'sum')
        ).reset_index()

        # Split single/mix pro grafy (vektorově)
        def _split_q(row):
            q = str(row['Queue_Split']).strip()
            # Nemáme zde pocet_mat, takže jen podle názvu fronty - jednodušší verze
            return q
        to_group['Queue_Split_Graf'] = to_group.apply(_split_q, axis=1)

        q_split_map = to_group.set_index(queue_count_col)['Queue_Split_Graf'].to_dict()
        df_pick['Queue_Split_Graf'] = df_pick[queue_count_col].map(q_split_map).fillna(df_pick['Queue'])

        valid_queues = sorted([q for q in df_pick['Queue_Split_Graf'].dropna().unique() if q != 'N/A'])

        if not valid_queues:
            st.info(_t("Žádné validní fronty pro zobrazení grafu.", "No valid queues to display."))
            return

        selected_queues = st.multiselect(
            _t("Zvolte Queue pro zobrazení v grafu:", "Select Queue(s) to display:"),
            options=valid_queues,
            default=valid_queues[:3] if len(valid_queues) >= 3 else valid_queues,
            key="dash_trend_queues"
        )

        if not selected_queues:
            st.info(_t("Prosím vyberte alespoň jednu Queue.", "Please select at least one Queue."))
            return

        trend_df = df_pick[df_pick['Queue_Split_Graf'].isin(selected_queues)]

        # Agregace za (Month, TO)
        trend_to_group = trend_df.groupby(['Month', queue_count_col], observed=True).agg(
            Queue_Split=('Queue_Split_Graf', 'first'),
            lokace=('Source Storage Bin', 'nunique'),
            pohyby=('Pohyby_Rukou', 'sum')
        ).reset_index()

        trend_agg = trend_to_group.groupby(['Month', 'Queue_Split'], observed=True).agg(
            to_count=(queue_count_col, 'nunique'),
            loc_count=('lokace', 'sum'),
            moves_count=('pohyby', 'sum')
        ).reset_index()

        trend_agg['prum_poh_lok'] = np.where(
            trend_agg['loc_count'] > 0,
            trend_agg['moves_count'] / trend_agg['loc_count'], 0
        )

        fig = go.Figure()
        for i, q in enumerate(selected_queues):
            q_data = trend_agg[trend_agg['Queue_Split'] == q].sort_values('Month')
            if q_data.empty:
                continue
            color = CHART_COLORS[i % len(CHART_COLORS)]
            lbl_to = _t("(Počet TO)", "(TO Count)")
            lbl_mov = _t("(Pohybů/lokaci)", "(Moves/Loc)")

            fig.add_trace(go.Bar(
                x=q_data['Month'], y=q_data['to_count'],
                name=f"{q} {lbl_to}", marker_color=color, opacity=0.7, offsetgroup=i,
            ))
            fig.add_trace(go.Scatter(
                x=q_data['Month'], y=q_data['prum_poh_lok'],
                name=f"{q} {lbl_mov}", mode='lines+markers+text',
                text=q_data['prum_poh_lok'].round(1),
                textposition='top center', yaxis='y2',
                line=dict(color=color, width=3),
                marker=dict(symbol='diamond', size=8)
            ))

        fig.update_layout(
            **apply_chart_defaults(
                barmode='group',
                yaxis=dict(title=_t("Celkový počet TO", "Total TOs")),
                yaxis2=dict(title=_t("Průměr pohybů na lokaci", "Avg Moves per Location"),
                            side="right", overlaying="y", showgrid=False),
            )
        )
        st.plotly_chart(fig, width="stretch")