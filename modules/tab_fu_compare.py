import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from modules.utils import t, safe_hu, safe_del

try:
    fast_render = st.fragment
except AttributeError:
    fast_render = lambda f: f

@fast_render
def render_fu_compare(df_pick, billing_df, voll_set, queue_count_col):
    def _t(cs, en): return en if st.session_state.get('lang', 'cs') == 'en' else cs

    st.markdown(f"<div class='section-header'><h3>⚖️ {_t('Detailní porovnání: Fyzický proces (Pick Queue) vs Fakturace ', 'Detailed Comparison: Physical Process vs Billing')}</h3><p>{_t('Tato záložka podrobně vysvětluje, proč nesedí čísla ze skeneru (fronty PI_PL_FU a PI_PL_FUOE) s konečnou fakturací, a jak Fakturační mozek zachraňuje přelepené palety.', 'This tab explains the differences between Scanner Data and Billing Data, and how the algorithm saves relabeled pallets.')}</p></div>", unsafe_allow_html=True)

    if billing_df is None or billing_df.empty or not voll_set:
        st.warning(_t("⚠️ Nejdříve navštivte záložku **Fakturace**, aby se provedly výpočty.", "⚠️ Please visit the **Billing** tab first to perform calculations."))
        return

    # --- PŘÍPRAVA DAT PRO HORNÍ METRIKY (Filtrovaná data) ---
    df_p = df_pick.copy()
    df_p['Clean_Del'] = df_p['Delivery'].apply(safe_del)
    df_p['Source_HU'] = df_p['Source storage unit'].apply(safe_hu)
    df_p['Dest_HU'] = df_p['Handling Unit'].apply(safe_hu)

    c_su = 'Storage Unit Type' if 'Storage Unit Type' in df_p.columns else ('Type' if 'Type' in df_p.columns else None)
    if c_su:
        df_p['Is_KLT'] = df_p[c_su].astype(str).str.upper().isin(['K1', 'K2', 'K3', 'K4', 'KLT', 'KLT1', 'KLT2'])
    else:
        df_p['Is_KLT'] = False

    df_p['Queue_UPPER'] = df_p['Queue'].astype(str).str.upper()
    df_p['Is_FU'] = (df_p['Queue_UPPER'] == 'PI_PL_FU') & (~df_p['Is_KLT'])
    df_p['Is_FUOE'] = (df_p['Queue_UPPER'] == 'PI_PL_FUOE') & (~df_p['Is_KLT'])
    df_p['Is_FU_Any'] = df_p['Is_FU'] | df_p['Is_FUOE']
    df_p['Is_Untouched'] = (df_p['Source_HU'] == df_p['Dest_HU']) & (df_p['Source_HU'] != '')

    def check_voll(row):
        d = row['Clean_Del']
        return (d, row['Dest_HU']) in voll_set or (d, row['Source_HU']) in voll_set

    df_p['Is_Voll_Billed'] = df_p.apply(check_voll, axis=1)

    to_agg = df_p.groupby(queue_count_col).agg(
        Delivery=('Clean_Del', 'first'),
        Queue=('Queue', 'first'),
        Queue_UPPER=('Queue_UPPER', 'first'),
        Storage_Unit_Type=(c_su, 'first') if c_su else ('Queue', 'first'),
        Is_FU_Any=('Is_FU_Any', 'max'),
        Is_Untouched=('Is_Untouched', 'min'),
        Is_Voll_Billed=('Is_Voll_Billed', 'max'),
        Source_HU=('Source_HU', 'first'),
        Dest_HU=('Dest_HU', 'first'),
        Material=('Material', 'first')
    ).reset_index()

    fu_tasks = to_agg[(to_agg['Queue_UPPER'] == 'PI_PL_FU') & (to_agg['Is_FU_Any'])].shape[0]
    fu_untouched = to_agg[(to_agg['Queue_UPPER'] == 'PI_PL_FU') & (to_agg['Is_FU_Any']) & (to_agg['Is_Untouched'])].shape[0]

    fuoe_tasks = to_agg[(to_agg['Queue_UPPER'] == 'PI_PL_FUOE') & (to_agg['Is_FU_Any'])].shape[0]
    fuoe_untouched = to_agg[(to_agg['Queue_UPPER'] == 'PI_PL_FUOE') & (to_agg['Is_FU_Any']) & (to_agg['Is_Untouched'])].shape[0]

    valid_dels = set(df_p['Clean_Del'].dropna().unique())
    billing_df_filtered = billing_df[billing_df['Clean_Del'].isin(valid_dels)]
    
    billed_n_voll = billing_df_filtered[billing_df_filtered['Category_Full'] == 'N Vollpalette']['pocet_hu'].sum()
    billed_o_voll = billing_df_filtered[billing_df_filtered['Category_Full'].isin(['O Vollpalette', 'OE Vollpalette'])]['pocet_hu'].sum()

    st.markdown("### 📊 Souhrnná čísla pro vybrané období")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric(_t("PI_PL_FU (Celkem úkolů na skeneru)", "PI_PL_FU (Total Scanner Tasks)"), int(fu_tasks))
        st.metric(_t("PI_PL_FUOE (Celkem úkolů na skeneru)", "PI_PL_FUOE (Total Scanner Tasks)"), int(fuoe_tasks))
    with c2:
        st.metric(_t("PI_PL_FU (Nepřebalováno)", "PI_PL_FU (Untouched)"), int(fu_untouched))
        st.metric(_t("PI_PL_FUOE (Nepřebalováno)", "PI_PL_FUOE (Untouched)"), int(fuoe_untouched))
    with c3:
        st.metric(_t("Fakturace: N Vollpalette", "Billing: N Vollpalette"), int(billed_n_voll))
        st.metric(_t("Fakturace: O/OE Vollpalette", "Billing: O/OE Vollpalette"), int(billed_o_voll))

    st.divider()

    # =========================================================
    # VÝPOČET GRAFU PRO VŠECHNY MĚSÍCE (Sáhnutí do raw paměti)
    # =========================================================
    df_full = st.session_state.get('data_dict', {}).get('df_pick', df_pick).copy()
    if 'Month' not in df_full.columns:
        df_full['Date'] = pd.to_datetime(df_full.get('Confirmation date', df_full.get('Confirmation Date')), errors='coerce')
        df_full['Month'] = df_full['Date'].dt.to_period('M').astype(str).replace('NaT', 'Neznámé')

    df_full['Clean_Del'] = df_full['Delivery'].apply(safe_del)
    df_full['Source_HU'] = df_full['Source storage unit'].apply(safe_hu)
    df_full['Dest_HU'] = df_full['Handling Unit'].apply(safe_hu)

    c_su_f = 'Storage Unit Type' if 'Storage Unit Type' in df_full.columns else ('Type' if 'Type' in df_full.columns else None)
    if c_su_f: df_full['Is_KLT'] = df_full[c_su_f].astype(str).str.upper().isin(['K1', 'K2', 'K3', 'K4', 'KLT', 'KLT1', 'KLT2'])
    else: df_full['Is_KLT'] = False

    df_full['Queue_UPPER'] = df_full['Queue'].astype(str).str.upper()
    df_full['Is_FU'] = (df_full['Queue_UPPER'] == 'PI_PL_FU') & (~df_full['Is_KLT'])
    df_full['Is_FUOE'] = (df_full['Queue_UPPER'] == 'PI_PL_FUOE') & (~df_full['Is_KLT'])
    df_full['Is_FU_Any'] = df_full['Is_FU'] | df_full['Is_FUOE']
    df_full['Is_Untouched'] = (df_full['Source_HU'] == df_full['Dest_HU']) & (df_full['Source_HU'] != '')
    df_full['Is_Voll_Billed'] = df_full.apply(check_voll, axis=1)

    to_agg_full = df_full.groupby(queue_count_col).agg(
        Delivery=('Clean_Del', 'first'),
        Queue_UPPER=('Queue_UPPER', 'first'),
        Month=('Month', 'first'),
        Is_FU_Any=('Is_FU_Any', 'max'),
        Is_Untouched=('Is_Untouched', 'min'),
        Is_Voll_Billed=('Is_Voll_Billed', 'max')
    ).reset_index()

    months = sorted([m for m in to_agg_full['Month'].unique() if m != 'Neznámé'])
    chart_data = []

    for m in months:
        m_df = to_agg_full[to_agg_full['Month'] == m]
        valid_dels_m = set(m_df['Delivery'].unique())
        
        # Billing pro daný měsíc přesně tak jak odjel na skeneru
        m_bill = billing_df[billing_df['Clean_Del'].isin(valid_dels_m)]
        
        chart_data.append({
            'Month': m,
            'FU_Tasks': m_df[(m_df['Queue_UPPER'] == 'PI_PL_FU') & (m_df['Is_FU_Any'])].shape[0],
            'FU_Untouched': m_df[(m_df['Queue_UPPER'] == 'PI_PL_FU') & (m_df['Is_FU_Any']) & (m_df['Is_Untouched'])].shape[0],
            'Billed_N': m_bill[m_bill['Category_Full'] == 'N Vollpalette']['pocet_hu'].sum(),
            
            'FUOE_Tasks': m_df[(m_df['Queue_UPPER'] == 'PI_PL_FUOE') & (m_df['Is_FU_Any'])].shape[0],
            'FUOE_Untouched': m_df[(m_df['Queue_UPPER'] == 'PI_PL_FUOE') & (m_df['Is_FU_Any']) & (m_df['Is_Untouched'])].shape[0],
            'Billed_O': m_bill[m_bill['Category_Full'].isin(['O Vollpalette', 'OE Vollpalette'])]['pocet_hu'].sum(),
            
            'Ideal': m_df[(m_df['Is_FU_Any']) & (m_df['Is_Untouched']) & (m_df['Is_Voll_Billed'])].shape[0],
            'Lost': m_df[(m_df['Is_FU_Any']) & (~m_df['Is_Voll_Billed'])].shape[0]
        })

    df_chart = pd.DataFrame(chart_data)

    if not df_chart.empty:
        st.markdown(f"### 📈 {_t('Trend v čase (Všechny měsíce)', 'Trend Over Time (All Months)')}")
        fig = go.Figure()
        
        # PI_PL_FU 
        fig.add_trace(go.Scatter(x=df_chart['Month'], y=df_chart['FU_Tasks'], name='PI_PL_FU (Celkem úkolů na skeneru)', mode='lines+markers', line=dict(color='#3b82f6')))
        fig.add_trace(go.Scatter(x=df_chart['Month'], y=df_chart['FU_Untouched'], name='PI_PL_FU (Nepřebalováno)', mode='lines+markers', line=dict(color='#93c5fd', dash='dash')))
        fig.add_trace(go.Scatter(x=df_chart['Month'], y=df_chart['Billed_N'], name='Fakturace: N Vollpalette', mode='lines+markers', line=dict(color='#10b981', width=3)))
        
        # PI_PL_FUOE 
        fig.add_trace(go.Scatter(x=df_chart['Month'], y=df_chart['FUOE_Tasks'], name='PI_PL_FUOE (Celkem úkolů na skeneru)', mode='lines+markers', line=dict(color='#f97316')))
        fig.add_trace(go.Scatter(x=df_chart['Month'], y=df_chart['FUOE_Untouched'], name='PI_PL_FUOE (Nepřebalováno)', mode='lines+markers', line=dict(color='#fdba74', dash='dash')))
        fig.add_trace(go.Scatter(x=df_chart['Month'], y=df_chart['Billed_O'], name='Fakturace: O/OE Vollpalette', mode='lines+markers', line=dict(color='#eab308', width=3)))
        
        # Ideální & Ztracené
        fig.add_trace(go.Scatter(x=df_chart['Month'], y=df_chart['Ideal'], name='Ideální palety', mode='lines+markers', line=dict(color='#8b5cf6', width=2)))
        fig.add_trace(go.Scatter(x=df_chart['Month'], y=df_chart['Lost'], name='Ztracené palety', mode='lines+markers', line=dict(color='#ef4444', width=2)))
        
        fig.update_layout(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5),
            margin=dict(l=0, r=0, t=10, b=0),
            hovermode="x unified"
        )
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # =========================================================
    # ROZPAD KATEGORIÍ (Filtrováno dle měsíce)
    # =========================================================
    st.markdown(f"### 🌉 {_t('Kde vznikají rozdíly? (Rozpad kategorií pro vybrané období)', 'Where do differences come from? (Category Breakdown)')}")

    cat_a = to_agg[(to_agg['Is_FU_Any']) & (to_agg['Is_Untouched']) & (to_agg['Is_Voll_Billed'])].copy()
    cat_b = to_agg[(to_agg['Is_FU_Any']) & (~to_agg['Is_Untouched']) & (to_agg['Is_Voll_Billed'])].copy()
    cat_c = to_agg[(to_agg['Is_FU_Any']) & (~to_agg['Is_Voll_Billed'])].copy()
    cat_d = to_agg[(~to_agg['Is_FU_Any']) & (to_agg['Is_Voll_Billed'])].copy()

    cc1, cc2, cc3, cc4 = st.columns(4)
    cc1.info(f"**🔵 {_t('Ideální palety', 'Ideal Pallets')} ({len(cat_a)})**\n\n{_t('Fronta FU/FUOE + Nepřelepeno + Vyfakturováno.', 'FU/FUOE Queue + Unchanged + Billed.')}")
    cc2.success(f"**🟢 {_t('Zachráněné palety', 'Saved Pallets')} ({len(cat_b)})**\n\n{_t('Fronta FU/FUOE + PŘELEPENO + Vyfakturováno.', 'FU/FUOE Queue + RELABELED + Billed.')}")
    cc3.error(f"**🔴 {_t('Ztracené palety', 'Lost Pallets')} ({len(cat_c)})**\n\n{_t('Fronta FU/FUOE + Nevyfakturováno.', 'FU/FUOE Queue + Not Billed.')}")
    cc4.warning(f"**🟡 {_t('Bonusové palety', 'Bonus Pallets')} ({len(cat_d)})**\n\n{_t('Obyčejná fronta + Vyfakturováno.', 'Normal Queue + Billed.')}")

    st.divider()

    t1, t2, t3, t4 = st.tabs([
        f"🔵 {_t('Ideální palety', 'Ideal Pallets')}",
        f"🟢 {_t('Zachráněné palety (Přelepené)', 'Saved Pallets (Relabeled)')}", 
        f"🔴 {_t('Ztracené palety (Zrušené/Rozbalené)', 'Lost Pallets (Cancelled/Unpacked)')}", 
        f"🟡 {_t('Bonusové palety (Z jiných front)', 'Bonus Pallets (From other queues)')}"
    ])

    cols_to_drop = ['Is_FU_Any', 'Queue_UPPER', 'Is_Untouched', 'Is_Voll_Billed']

    with t1:
        st.markdown(_t("Ideální proces: Skladník dostal úkol jít pro celou paletu, potvrdil původní štítek a v SAPu to bezpečně prošlo fakturací jako Vollpalette.", "Ideal process: Worker picked a full pallet, kept the label, and it was billed successfully."))
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### PI_PL_FU ")
            st.dataframe(cat_a[cat_a['Queue_UPPER'] == 'PI_PL_FU'].drop(columns=cols_to_drop, errors='ignore'), use_container_width=True, hide_index=True)
        with col2:
            st.markdown("#### PI_PL_FUOE")
            st.dataframe(cat_a[cat_a['Queue_UPPER'] == 'PI_PL_FUOE'].drop(columns=cols_to_drop, errors='ignore'), use_container_width=True, hide_index=True)

    with t2:
        st.markdown(_t("Skladník vytvořil u balení nové číslo palety (Dest HU se neshoduje se Source HU). Záložka 'Celé palety' by si myslela, že je to přebalené. **Fakturační mozek ale ve VEKP zjistil, že se obsah nezměnil a zachránil ji!**", "Worker relabeled the pallet. Basic tracking thinks it was unpacked, but the Billing engine confirmed unchanged content and saved it!"))
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### PI_PL_FU ")
            st.dataframe(cat_b[cat_b['Queue_UPPER'] == 'PI_PL_FU'].drop(columns=cols_to_drop, errors='ignore'), use_container_width=True, hide_index=True)
        with col2:
            st.markdown("#### PI_PL_FUOE")
            st.dataframe(cat_b[cat_b['Queue_UPPER'] == 'PI_PL_FUOE'].drop(columns=cols_to_drop, errors='ignore'), use_container_width=True, hide_index=True)

    with t3:
        st.markdown(_t("Skener hlásil **PI_PL_FU / PI_PL_FUOE**, ale v systému VEKP chybí jako Vollpalette. Důvody: Zakázka byla stornována, odjela v jiný den, nebo ji balírna fyzicky rozbalila a smíchala s něčím jiným.", "Scanner reported FU, but it is missing in VEKP as Vollpalette. Cancelled, moved to another day, or physically unpacked."))
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### PI_PL_FU ")
            st.dataframe(cat_c[cat_c['Queue_UPPER'] == 'PI_PL_FU'].drop(columns=cols_to_drop, errors='ignore'), use_container_width=True, hide_index=True)
        with col2:
            st.markdown("#### PI_PL_FUOE ")
            st.dataframe(cat_c[cat_c['Queue_UPPER'] == 'PI_PL_FUOE'].drop(columns=cols_to_drop, errors='ignore'), use_container_width=True, hide_index=True)

    with t4:
        st.markdown(_t("Tyto úkoly byly odeslány jako normální pickování, ale aplikace zjistila, že jste do balení (VEKP) už nic nepřidali a expedovalo se to jako jeden kus. **Zákazník to tudíž zaplatí jako Vollpaletu.**", "These tasks were normal picking, but the app detected it shipped as one piece. Customer will be billed for a Vollpalette."))
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### Běžné fronty (PI_PL, atd.)")
            st.dataframe(cat_d[~cat_d['Queue_UPPER'].isin(['PI_PL_OE', 'PI_PA_OE'])].drop(columns=cols_to_drop, errors='ignore'), use_container_width=True, hide_index=True)
        with col2:
            st.markdown("#### Exportní fronty (PI_PL_OE, atd.)")
            st.dataframe(cat_d[cat_d['Queue_UPPER'].isin(['PI_PL_OE', 'PI_PA_OE'])].drop(columns=cols_to_drop, errors='ignore'), use_container_width=True, hide_index=True)

    # =========================================================
    # RENTGEN PALETOVÉ ZAKÁZKY (INTERAKTIVNÍ DETAIL)
    # =========================================================
    st.divider()
    st.markdown(f"<div class='section-header'><h3>🔍 {_t('Rentgen paletové zakázky (Audit logiky)', 'Order X-Ray (Logic Audit)')}</h3><p>{_t('Zadejte číslo zakázky a podívejte se přesně, jak ji zpracoval skener vs. jak ji vyhodnotil Fakturační mozek v SAPu.', 'Enter an order number to see exactly how it was processed by the scanner vs. the Billing engine.')}</p></div>", unsafe_allow_html=True)

    avail_dels = sorted(to_agg['Delivery'].dropna().unique())
    sel_del = st.selectbox(_t("Vyberte zakázku (Delivery) pro detailní rentgen:", "Select Delivery for detailed X-Ray:"), options=[""] + avail_dels, key="compare_xray_del")

    if sel_del:
        del_data = to_agg[to_agg['Delivery'] == sel_del].copy()
        
        st.markdown(f"#### 📦 {_t('Úkoly ze skeneru (Pick Report)', 'Scanner Tasks (Pick Report)')}")
        
        def get_status_text(row):
            if row['Is_FU_Any'] and row['Is_Untouched'] and row['Is_Voll_Billed']: return "🔵 Ideální (Skener i SAP)"
            if row['Is_FU_Any'] and not row['Is_Untouched'] and row['Is_Voll_Billed']: return "🟢 Zachráněno (Přelepeno)"
            if row['Is_FU_Any'] and not row['Is_Voll_Billed']: return "🔴 Ztraceno (Není Vollpalette)"
            if not row['Is_FU_Any'] and row['Is_Voll_Billed']: return "🟡 Bonus (Z běžného picku)"
            return "⚪ Běžný pick (Neúčtuje se jako paleta)"
            
        del_data['Výsledek (Status)'] = del_data.apply(get_status_text, axis=1)
        disp_del = del_data[['Queue', 'Source_HU', 'Dest_HU', 'Material', 'Výsledek (Status)']].copy()
        
        def color_status(val):
            if '🔵' in str(val): return 'color: #3b82f6; font-weight: bold'
            if '🟢' in str(val): return 'color: #10b981; font-weight: bold'
            if '🔴' in str(val): return 'color: #ef4444; font-weight: bold'
            if '🟡' in str(val): return 'color: #eab308; font-weight: bold'
            return 'color: gray'
            
        try:
            styled_del = disp_del.style.map(color_status, subset=['Výsledek (Status)'])
        except AttributeError:
            styled_del = disp_del.style.applymap(color_status, subset=['Výsledek (Status)'])
            
        st.dataframe(styled_del, use_container_width=True, hide_index=True)
        
        df_hu_details = st.session_state.get('debug_hu_details')
        if df_hu_details is not None and not df_hu_details.empty:
            del_billed = df_hu_details[df_hu_details['Clean_Del'] == sel_del]
            if not del_billed.empty:
                st.markdown(f"#### 💰 {_t('Co se u této zakázky skutečně vyfakturovalo (SAP VEKP)', 'What was actually billed for this order (SAP VEKP)')}")
                disp_billed = del_billed[['HU_Ext', 'HU_Int', 'Category_Full', 'Is_Vollpalette', 'Materials']].copy()
                disp_billed.columns = ['HU (SSCC)', 'HU (Interní)', 'Kategorie Fakturace', 'Je Vollpalette?', 'Materiály']
                st.dataframe(disp_billed, use_container_width=True, hide_index=True)
            else:
                st.warning(_t("Tato zakázka nemá ve Fakturaci žádné vyfakturované jednotky (chybí data ve VEKP, nebo byla prázdná).", "This order has no billed units in Billing (missing VEKP data)."))
        else:
            st.info(_t("Pro detail ze SAPu musíte nejprve navštívit záložku Fakturace.", "Visit Billing tab first to see SAP details."))
