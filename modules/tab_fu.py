"""
Full Pallets (FU) - Analýza efektivity celých palet.
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from modules.utils import t, safe_del, safe_hu, is_box, CHART_COLORS
from modules.safe_render import ErrorBoundary, validate_dataframe, safe_render


@safe_render(fallback_message="⚠️ Chyba při vykreslování analýzy celých palet")
def render_fu(df_pick, queue_count_col):
    """Hlavní renderer pro záložku Full Pallets (FU)."""
    def _t(cs, en):
        return en if st.session_state.get('lang', 'cs') == 'en' else cs

    if not validate_dataframe(df_pick, "Pick Report"):
        return

    st.markdown(
        f"<div class='section-header'>"
        f"<h3>🏭 {t('fu_title')}</h3>"
        f"<p>{t('fu_desc')}</p>"
        f"</div>",
        unsafe_allow_html=True
    )

    # Filtrovat pouze FU fronty
    fu_df = df_pick[df_pick['Queue'].astype(str).str.upper().isin(['PI_PL_FU', 'PI_PL_FUOE'])].copy()

    if fu_df.empty:
        st.info(_t("V datech chybí záznamy pro fronty PI_PL_FU nebo PI_PL_FUOE.",
                   "No data found for PI_PL_FU or PI_PL_FUOE queues."))
        return

    c_su = 'Storage Unit Type' if 'Storage Unit Type' in fu_df.columns \
        else ('Type' if 'Type' in fu_df.columns else None)

    # Vektorová klasifikace: je to KLT/box nebo paleta?
    if c_su:
        fu_df['Is_KLT'] = fu_df[c_su].astype(str).apply(is_box)
    else:
        fu_df['Is_KLT'] = False

    fu_df['Typ_Obalu'] = np.where(
        fu_df['Is_KLT'],
        _t('Krabice / KLT', 'Box / KLT'),
        _t('Paleta', 'Pallet')
    )

    # === 1) MĚSÍČNÍ PODÍL PALET VS KARTONŮ ===
    _render_monthly_su_breakdown(fu_df, c_su, _t)

    # === 2) ANALÝZA EFEKTIVITY PŘEBALOVÁNÍ ===
    _render_vollpalette_analysis(df_pick, fu_df, c_su, queue_count_col, _t)

    # === 3) X-RAY KONKRÉTNÍ ZAKÁZKY ===
    _render_xray_audit(fu_df, c_su, queue_count_col, _t)


def _render_monthly_su_breakdown(fu_df, c_su, _t):
    """Měsíční přehled typů obalů (paleta vs krabice)."""
    if not c_su:
        return

    st.markdown(f"### 🏷️ {_t('Měsíční podíl pickovaných Palet vs. Krabic', 'Monthly Share of Picked Pallets vs. Boxes')}")

    with ErrorBoundary("Měsíční breakdown SU"):
        su_agg = fu_df.groupby([c_su, 'Typ_Obalu'], observed=True).agg(
            lines=('Material', 'count'),
            tos=('Transfer Order Number' if 'Transfer Order Number' in fu_df.columns else 'Delivery', 'nunique'),
            qty=('Qty', 'sum')
        ).reset_index().sort_values('tos', ascending=False)

        su_agg.columns = [
            _t("Kód obalu (SAP)", "Pack Code (SAP)"),
            _t("Skupina obalu", "Pack Group"),
            _t("Pickovací řádky", "Pick Lines"),
            _t("Počet TO", "Total TOs"),
            _t("Množství (ks)", "Quantity (pcs)")
        ]

        col_su1, col_su2 = st.columns([1, 1.8])
        with col_su1:
            st.dataframe(su_agg, use_container_width=True, hide_index=True)

        with col_su2:
            if 'Month' in fu_df.columns:
                to_col = 'Transfer Order Number' if 'Transfer Order Number' in fu_df.columns else 'Delivery'
                trend_su = fu_df.groupby(['Month', 'Typ_Obalu'], observed=True)[to_col].nunique().reset_index()
                trend_su_pivot = trend_su.pivot(index='Month', columns='Typ_Obalu', values=to_col).fillna(0)

                pal_lbl = _t('Paleta', 'Pallet')
                klt_lbl = _t('Krabice / KLT', 'Box / KLT')

                if pal_lbl not in trend_su_pivot.columns:
                    trend_su_pivot[pal_lbl] = 0
                if klt_lbl not in trend_su_pivot.columns:
                    trend_su_pivot[klt_lbl] = 0

                trend_su_pivot['Celkem'] = trend_su_pivot[pal_lbl] + trend_su_pivot[klt_lbl]
                trend_su_pivot['Palety_pct'] = np.where(
                    trend_su_pivot['Celkem'] > 0,
                    (trend_su_pivot[pal_lbl] / trend_su_pivot['Celkem']) * 100, 0
                )
                trend_su_pivot = trend_su_pivot.reset_index().sort_values('Month')

                fig_su = go.Figure()
                fig_su.add_trace(go.Bar(
                    x=trend_su_pivot['Month'], y=trend_su_pivot[pal_lbl],
                    name=_t('Palety (TO)', 'Pallets (TO)'),
                    marker_color='#3b82f6', text=trend_su_pivot[pal_lbl], textposition='auto'
                ))
                fig_su.add_trace(go.Bar(
                    x=trend_su_pivot['Month'], y=trend_su_pivot[klt_lbl],
                    name=_t('Krabice (TO)', 'Boxes (TO)'),
                    marker_color='#f59e0b', text=trend_su_pivot[klt_lbl], textposition='auto'
                ))
                fig_su.add_trace(go.Scatter(
                    x=trend_su_pivot['Month'], y=trend_su_pivot['Palety_pct'],
                    name=_t('Podíl palet (%)', 'Pallet Share (%)'),
                    yaxis='y2', mode='lines+markers+text',
                    text=trend_su_pivot['Palety_pct'].round(1).astype(str) + '%',
                    textposition='top center',
                    line=dict(color='#10b981', width=3),
                    marker=dict(symbol='circle', size=8)
                ))

                fig_su.update_layout(
                    barmode='group',
                    yaxis=dict(title=_t("Počet TO", "Number of TOs")),
                    yaxis2=dict(title=_t("Podíl palet (%)", "Pallet Share (%)"),
                                side="right", overlaying="y", showgrid=False, range=[0, 115]),
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    margin=dict(t=20, b=10, l=10, r=10),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                )
                st.plotly_chart(fig_su, use_container_width=True)


def _render_vollpalette_analysis(df_pick, fu_df, c_su, queue_count_col, _t):
    """Analýza efektivity Vollpalet - porovnání s billing engine."""
    st.divider()
    st.markdown(f"### 📦 {_t('Efektivita: Přímé balení bez přebalování (Vollpalette)',
                              'Efficiency: Direct Packing without Repacking (Vollpalette)')}")

    voll_set = st.session_state.get('voll_set', set())
    if not voll_set:
        st.warning(_t("⚠️ Centrální mozek pro Vollpalety nemá žádná data (zkontrolujte VEKP/VEPO).",
                       "⚠️ Central brain for Vollpallets has no data."))

    with ErrorBoundary("Vollpalette analýza"):
        # Vektorová příprava HU klíčů (numpy-safe)
        hu_ext = fu_df.get('Handling Unit', pd.Series([''] * len(fu_df))).fillna('').astype(str).apply(safe_hu)
        ssu = fu_df.get('Source storage unit', pd.Series([''] * len(fu_df))).fillna('').astype(str).apply(safe_hu)

        # Určení HU pro každý řádek (vektorově)
        pick_hu = np.where(
            (ssu.values != '') & (hu_ext.values != '') & (ssu.values == hu_ext.values),
            ssu.values,
            np.where(ssu.values != '', ssu.values, hu_ext.values)
        )
        fu_df = fu_df.copy()
        fu_df['_pick_hu'] = pick_hu
        fu_df['_clean_del'] = fu_df['Delivery'].apply(safe_del)
        fu_df['Has_X'] = fu_df['Removal of total SU'].astype(str).str.strip().str.upper() == 'X'

        # Detekce Vollpalette - vektorově s předem připraveným set
        # Pro rychlost převedeme set na dict pro O(1) lookup
        voll_dict = {}
        for d, h in voll_set:
            voll_dict.setdefault(d, set()).add(h)

        def _is_voll(row):
            d = row['_clean_del']
            hu = row['_pick_hu']
            return d in voll_dict and hu in voll_dict[d]

        fu_df['Neprebalovano'] = fu_df.apply(_is_voll, axis=1)

        # === KATEGORIE ZAKÁZEK ===
        fu_df_pallets = fu_df[~fu_df['Is_KLT']].copy()
        ignored_klt_count = int(fu_df[fu_df['Is_KLT']][queue_count_col].nunique())

        # Queue skupiny pro celou delivery - vektorově pomocí groupby
        df_scan = df_pick.copy()
        df_scan['_clean_del'] = df_scan['Delivery'].apply(safe_del)
        df_scan['_q_upper'] = df_scan['Queue'].astype(str).str.upper()

        # Jedno agregace za delivery
        del_queues = df_scan.groupby('_clean_del', observed=True)['_q_upper'].apply(set).to_dict()

        pure_fu_combo_dels = {d for d, qs in del_queues.items() if qs.issubset({'PI_PL_FU', 'PI_PL_FUOE'})}
        only_fu_strict_dels = {d for d, qs in del_queues.items() if qs == {'PI_PL_FU'}}
        only_fuoe_strict_dels = {d for d, qs in del_queues.items() if qs == {'PI_PL_FUOE'}}

        df_pure_combo = fu_df_pallets[fu_df_pallets['_clean_del'].isin(pure_fu_combo_dels)].copy()
        df_only_fu = fu_df_pallets[fu_df_pallets['_clean_del'].isin(only_fu_strict_dels)].copy()
        df_only_fuoe = fu_df_pallets[fu_df_pallets['_clean_del'].isin(only_fuoe_strict_dels)].copy()

        # TABS pro různé kategorie
        tabs = st.tabs([
            _t("🎯 Čisté FU + FUOE", "🎯 Pure FU + FUOE"),
            _t("📦 Pouze PI_PL_FU", "📦 Only PI_PL_FU"),
            _t("🌍 Pouze PI_PL_FUOE", "🌍 Only PI_PL_FUOE")
        ])

        with tabs[0]:
            st.markdown(_t("Analýza **čistých paletových zakázek**.", "Analysis of **pure pallet orders**."))
            _render_efficiency_view(df_pure_combo, queue_count_col, _t,
                                    is_pure=True, label=_t("Čisté FU/FUOE", "Pure FU/FUOE"))

        with tabs[1]:
            st.markdown(_t("Analýza zakázek **pouze PI_PL_FU**.", "Orders with **exclusively PI_PL_FU**."))
            _render_efficiency_view(df_only_fu, queue_count_col, _t,
                                    is_pure=True, label=_t("Pouze FU", "Only FU"))

        with tabs[2]:
            st.markdown(_t("Analýza zakázek **pouze PI_PL_FUOE**.", "Orders with **exclusively PI_PL_FUOE**."))
            _render_efficiency_view(df_only_fuoe, queue_count_col, _t,
                                    is_pure=True, label=_t("Pouze FUOE", "Only FUOE"))


def _render_efficiency_view(df_view, queue_count_col, _t, is_pure=False, label=""):
    """Detailní pohled na efektivitu - tabulka + grafy + X-Ray seznamy."""
    if df_view.empty:
        st.info(_t(f"V této kategorii ({label}) nebyly nalezeny žádné záznamy.",
                   f"No records found in this category ({label})."))
        return

    # === MĚSÍČNÍ TREND ===
    if 'Month' in df_view.columns:
        with ErrorBoundary("Trend graf efektivity"):
            trend_df = df_view[df_view['Has_X']].groupby(['Month', 'Neprebalovano'], observed=True)[queue_count_col].nunique().reset_index()
            trend_pivot = trend_df.pivot(index='Month', columns='Neprebalovano', values=queue_count_col).fillna(0)

            if True not in trend_pivot.columns:
                trend_pivot[True] = 0
            if False not in trend_pivot.columns:
                trend_pivot[False] = 0

            trend_pivot['Celkem_X'] = trend_pivot[True] + trend_pivot[False]
            trend_pivot['Uspesnost_pct'] = np.where(
                trend_pivot['Celkem_X'] > 0,
                (trend_pivot[True] / trend_pivot['Celkem_X']) * 100, 0
            )
            trend_pivot = trend_pivot.reset_index().sort_values('Month')

            st.markdown(f"#### 📈 {_t('Měsíční trend odbavení celých palet', 'Monthly Trend of Full Pallet Processing')}")

            fig_bar = go.Figure()
            fig_bar.add_trace(go.Bar(
                x=trend_pivot['Month'], y=trend_pivot[True],
                name=_t('Nepřebalováno (Ziskové)', 'Not Repacked (Profitable)'),
                marker_color='#10b981', text=trend_pivot[True], textposition='auto'
            ))
            fig_bar.add_trace(go.Bar(
                x=trend_pivot['Month'], y=trend_pivot[False],
                name=_t('Přebaleno (Zbytečná práce)', 'Repacked (Wasted Effort)'),
                marker_color='#ef4444', text=trend_pivot[False], textposition='auto'
            ))
            fig_bar.add_trace(go.Scatter(
                x=trend_pivot['Month'], y=trend_pivot['Uspesnost_pct'],
                name=_t('Úspěšnost (%)', 'Success Rate (%)'),
                yaxis='y2', mode='lines+markers+text',
                text=trend_pivot['Uspesnost_pct'].round(1).astype(str) + '%',
                textposition='top center',
                line=dict(color='#3b82f6', width=3),
                marker=dict(symbol='circle', size=8)
            ))

            fig_bar.update_layout(
                barmode='group',
                yaxis=dict(title=_t("Počet palet (TO)", "Pallets Count (TO)")),
                yaxis2=dict(title=_t("Úspěšnost (%)", "Success Rate (%)"),
                            side="right", overlaying="y", showgrid=False, range=[0, 115]),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=20, b=10, l=10, r=10),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            st.plotly_chart(fig_bar, use_container_width=True)
            st.markdown("<br>", unsafe_allow_html=True)

    # === METRIKY ===
    total_fu_pal = int(df_view[queue_count_col].nunique())
    total_x_pal = int(df_view[df_view['Has_X']][queue_count_col].nunique())
    total_neprebalovano = int(df_view[df_view['Neprebalovano']][queue_count_col].nunique())

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric(
            _t("Celkem pickováno palet (TO)", "Total Picked Pallets (TO)"),
            f"{total_fu_pal:,}"
        )
    with c2:
        st.metric(
            _t("Celá paleta ze skladu ('X')", "Full Pallet from Storage ('X')"),
            f"{total_x_pal:,}"
        )
    with c3:
        st.metric(
            _t("Nepřebalováno ✅", "Not Repacked ✅"),
            f"{total_neprebalovano:,}",
            delta=f"{(total_neprebalovano / total_x_pal * 100 if total_x_pal > 0 else 0):.1f}% úspěšnost"
        )

    # === ÚSPĚŠNÉ VS ZBYTEČNÉ PRÁCE ===
    prebaleno_x = df_view[(df_view['Has_X']) & (~df_view['Neprebalovano'])]

    col_t1, col_t2 = st.columns(2)
    with col_t1:
        st.success(f"**✅ {_t('Úspěšné Vollpalety', 'Successful Vollpallets')}: {total_neprebalovano} TO**")
        nepreb_df = df_view[df_view['Neprebalovano']].drop_duplicates(subset=[queue_count_col]).copy()
        if not nepreb_df.empty:
            cols = ['Delivery', queue_count_col, 'Material', 'Qty']
            if c_su:
                cols.append(c_su)
            disp1 = nepreb_df[[c for c in cols if c in nepreb_df.columns]].copy()
            st.dataframe(disp1, use_container_width=True, hide_index=True)
        else:
            st.info(_t("Žádné záznamy.", "No records found."))

    with col_t2:
        st.error(f"**⚠️ {_t('Zbytečná práce (Přebaleno)', 'Wasted Effort (Repacked)')}: {prebaleno_x[queue_count_col].nunique()} TO**")
        if not prebaleno_x.empty:
            disp2_raw = prebaleno_x.drop_duplicates(subset=[queue_count_col])
            cols = ['Delivery', queue_count_col, 'Material', 'Qty']
            if c_su:
                cols.append(c_su)
            disp2 = disp2_raw[[c for c in cols if c in disp2_raw.columns]].copy()
            st.dataframe(disp2, use_container_width=True, hide_index=True)
        else:
            st.success(_t("Skvělá práce! Všechny celé palety prošly čistě.", "Great job! All full pallets were processed cleanly."))


def _render_xray_audit(fu_df, c_su, queue_count_col, _t):
    """X-Ray: Detailní audit konkrétní zakázky."""
    st.divider()
    st.markdown(
        f"<div class='section-header'>"
        f"<h3>🔍 {_t('Rentgen paletové zakázky (Audit logiky)', 'Pallet Order X-Ray (Logic Audit)')}</h3>"
        f"</div>",
        unsafe_allow_html=True
    )

    audit_dels = sorted(fu_df['_clean_del'].dropna().unique())
    sel_audit_del = st.selectbox(
        _t("Vyberte zakázku (Delivery) pro rentgen:", "Select an Order (Delivery) for X-Ray:"),
        options=[""] + audit_dels,
        key="audit_fu_del"
    )

    if not sel_audit_del:
        return

    pick_audit = fu_df[fu_df['_clean_del'] == sel_audit_del].copy()
    st.markdown(f"#### {_t('Výsledky pro zakázku:', 'Results for Order:')} `{sel_audit_del}`")

    st.markdown(f"**1. {_t('Data ze Skladu (Pick Report):', 'Warehouse Data (Pick Report):')}**")
    cols_to_show = [queue_count_col, 'Material', 'Qty', 'Removal of total SU']
    if c_su:
        cols_to_show.append(c_su)
    for c in ['Handling Unit', 'Source storage unit']:
        if c in pick_audit.columns:
            cols_to_show.append(c)
    avail_cols = [c for c in cols_to_show if c in pick_audit.columns]
    st.dataframe(pick_audit[avail_cols], hide_index=True, use_container_width=True)

    # Detailní audit po TO
    voll_set = st.session_state.get('voll_set', set())
    st.markdown(f"**2. {_t('Myšlenkový pochod Centrálního Mozku (TO po TO):', 'Algorithm Logic Flow (TO by TO):')}**")
    for _, r in pick_audit.drop_duplicates(subset=[queue_count_col]).iterrows():
        with st.expander(f"TO: {r[queue_count_col]}", expanded=True):
            d = r['_clean_del']
            hu = r.get('_pick_hu', '')

            if r.get('Is_KLT', False):
                st.info(f"🚫 {_t('Je to krabice (Ignorováno)', 'It is a box (Ignored)')}")
            else:
                st.success(f"✔️ {_t('Typ obalu je paleta.', 'Package type is Pallet.')}")

            if not r.get('Has_X', False):
                st.error(f"❌ {_t('Chybí značka X.', 'Missing X mark.')}")
            else:
                st.success(f"✔️ {_t('Nalezena značka X.', 'X mark found.')}")

            if (d, hu) in voll_set:
                st.success(
                    f"**✅ {_t('Výsledek: NEPŘEBALOVÁNO (100% ověřeno)', 'Result: NOT REPACKED (100% verified)')}**"
                )
            else:
                st.error(
                    f"**❌ {_t('Výsledek: PŘEBALENO', 'Result: REPACKED')}**"
                )