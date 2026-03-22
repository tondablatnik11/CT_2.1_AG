import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import datetime

try:
    fast_render = st.fragment
except AttributeError:
    fast_render = lambda f: f

@fast_render
def render_storage(df_lx03, df_lt10, df_marm, df_pick):
    st.markdown("<div class='section-header'><h3>🏢 Skladový Dispečink (Warehouse Control)</h3><p>Detailní přehled kapacity, optimalizace pozic a detekce mrtvých zásob ve skladech 800 a 820.</p></div>", unsafe_allow_html=True)

    if df_lx03 is None or df_lx03.empty or df_lt10 is None or df_lt10.empty:
        st.warning("⚠️ Chybí reporty **LX03** nebo **LT10**. Nahrajte je prosím v Admin Zóně.")
        return

    # --- PŘÍPRAVA DAT A FILTRACE ZÓN (800, 820) ---
    c_type_lx = next((c for c in df_lx03.columns if 'STORAGE TYPE' in str(c).upper() or 'TYP SKLADU' in str(c).upper()), None)
    c_bin_lx = next((c for c in df_lx03.columns if 'STORAGE BIN' in str(c).upper() or 'SKLADOVÉ MÍSTO' in str(c).upper()), None)
    c_mat_lx = next((c for c in df_lx03.columns if 'MATERIAL' in str(c).upper() or 'MATERIÁL' in str(c).upper()), None)
    c_bintype_lx = next((c for c in df_lx03.columns if 'STORAGE BIN TYPE' in str(c).upper() or 'TYP SKLAD.MÍSTA' in str(c).upper()), None)

    lx_clean = df_lx03.copy()
    if c_type_lx:
        lx_clean = lx_clean[lx_clean[c_type_lx].astype(str).str.strip().isin(['800', '820'])]

    # ==========================================
    # SEKCE 1: KAPACITA SKLADU
    # ==========================================
    st.markdown("#### 📊 Aktuální kapacita skladu (Zóny 800 a 820)")
    if c_bintype_lx and c_mat_lx:
        # Rozlišení prázdných a plných pozic
        lx_clean['Is_Empty'] = lx_clean[c_mat_lx].astype(str).str.strip().str.lower().isin(['<<empty>>', 'nan', ''])
        
        cap_agg = lx_clean.groupby([c_bintype_lx, 'Is_Empty']).size().reset_index(name='Count')
        cap_pivot = cap_agg.pivot(index=c_bintype_lx, columns='Is_Empty', values='Count').fillna(0)
        if True in cap_pivot.columns: cap_pivot.rename(columns={True: 'Volné'}, inplace=True)
        if False in cap_pivot.columns: cap_pivot.rename(columns={False: 'Obsazené'}, inplace=True)
        
        cap_pivot['Celkem'] = cap_pivot.get('Volné', 0) + cap_pivot.get('Obsazené', 0)
        cap_pivot['Využití (%)'] = (cap_pivot.get('Obsazené', 0) / cap_pivot['Celkem'] * 100).round(1)
        
        c1, c2 = st.columns([2, 3])
        with c1:
            st.dataframe(cap_pivot[['Obsazené', 'Volné', 'Využití (%)']].style.format({'Využití (%)': "{:.1f} %"}), use_container_width=True)
        with c2:
            fig = px.bar(cap_agg, x=c_bintype_lx, y='Count', color='Is_Empty', title="Obsazenost podle typu lokace",
                         color_discrete_map={True: '#10b981', False: '#ef4444'}, labels={'Is_Empty': 'Prázdné?'})
            fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ==========================================
    # SEKCE 2: NÁVRHY NA PŘESUNY (Downsizing do K1)
    # ==========================================
    st.markdown("#### 💡 Optimalizace: Doporučené přesuny z Palet (EP1-EP4) do Regálů (K1)")
    st.write("Aplikace hledá materiály, kterých je na paletových pozicích jen zbytek (pár kusů), a podle fyzických rozměrů z MARM garantuje, že se vejdou do K1 (55x45x40 cm).")
    
    col_sl1, col_sl2 = st.columns(2)
    with col_sl1: limit_ks = st.slider("Maximální počet kusů na paletě pro přesun:", min_value=1, max_value=50, value=5, step=1)
    
    c_mat_lt = next((c for c in df_lt10.columns if 'MATERIAL' in str(c).upper() or 'MATERIÁL' in str(c).upper()), None)
    c_qty_lt = next((c for c in df_lt10.columns if 'AVAILABLE STOCK' in str(c).upper() or 'ZÁSOBA K DISP.' in str(c).upper()), None)
    c_bintype_lt = next((c for c in df_lt10.columns if 'STORAGE BIN TYPE' in str(c).upper() or 'TYP SKLAD.MÍSTA' in str(c).upper()), None)
    c_bin_lt = next((c for c in df_lt10.columns if 'STORAGE BIN' in str(c).upper() or 'SKLADOVÉ MÍSTO' in str(c).upper()), None)
    
    if c_mat_lt and c_qty_lt and c_bintype_lt:
        lt_ep = df_lt10[df_lt10[c_bintype_lt].astype(str).str.strip().str.upper().isin(['EP1', 'EP2', 'EP3', 'EP4'])].copy()
        lt_ep['Qty_Num'] = pd.to_numeric(lt_ep[c_qty_lt], errors='coerce').fillna(0)
        candidates = lt_ep[(lt_ep['Qty_Num'] > 0) & (lt_ep['Qty_Num'] <= limit_ks)].copy()
        
        # Ověření rozměrů přes MARM (Chytrá 3D rotace)
        if df_marm is not None and not candidates.empty:
            c_marm_mat = next((c for c in df_marm.columns if 'MATERIAL' in str(c).upper() or 'MATERIÁL' in str(c).upper()), df_marm.columns[0])
            c_len = next((c for c in df_marm.columns if 'LENGTH' in str(c).upper() or 'LÄNGE' in str(c).upper() or 'DÉLKA' in str(c).upper()), None)
            c_wid = next((c for c in df_marm.columns if 'WIDTH' in str(c).upper() or 'BREITE' in str(c).upper() or 'ŠÍŘKA' in str(c).upper()), None)
            c_hei = next((c for c in df_marm.columns if 'HEIGHT' in str(c).upper() or 'HÖHE' in str(c).upper() or 'VÝŠKA' in str(c).upper()), None)
            
            if c_len and c_wid and c_hei:
                valid_mats = []
                for _, r in df_marm.iterrows():
                    mat = str(r[c_marm_mat]).strip().lstrip('0')
                    try:
                        l = float(str(r[c_len]).replace(',', '.'))
                        w = float(str(r[c_wid]).replace(',', '.'))
                        h = float(str(r[c_hei]).replace(',', '.'))
                        # Seřadíme rozměry krabice vs rozměry regálu (55x45x40)
                        dims = sorted([l, w, h])
                        if dims[0] <= 40 and dims[1] <= 45 and dims[2] <= 55:
                            valid_mats.append(mat)
                    except: pass
                
                candidates['Clean_Mat'] = candidates[c_mat_lt].astype(str).str.strip().str.lstrip('0')
                approved = candidates[candidates['Clean_Mat'].isin(valid_mats)].copy()
                
                if not approved.empty:
                    st.success(f"Nalezeno {len(approved)} palet, které lze uvolnit přesunem do K1!")
                    disp_app = approved[[c_bin_lt, c_bintype_lt, c_mat_lt, c_qty_lt]].copy()
                    disp_app.columns = ['Současná pozice', 'Typ pozice', 'Materiál', 'Počet kusů k přesunu']
                    st.dataframe(disp_app.sort_values('Počet kusů k přesunu'), hide_index=True, use_container_width=True)
                else:
                    st.info("Žádné materiály nesplňují limity počtu kusů a 3D rozměrů pro K1.")
            else: st.warning("V MARM reportu chybí sloupce Délka/Šířka/Výška.")
        else: st.info("Pro ověření rozměrů nahrajte MARM report.")

    st.divider()

    # ==========================================
    # SEKCE 3: LEŽÁKY A OBRÁTKOVOST (Dead Stock)
    # ==========================================
    st.markdown("#### 💀 Mrtvá zásoba (Ležáky ve skladu)")
    c_date_lt = next((c for c in df_lt10.columns if 'LAST MOVEMENT' in str(c).upper() or 'POSLEDNÍ POHYB' in str(c).upper()), None)
    
    if c_date_lt and c_mat_lt:
        col_ds1, _ = st.columns(2)
        with col_ds1: days_limit = st.slider("Za ležák považovat materiál bez pohybu více než X dní:", min_value=30, max_value=365, value=90, step=10)
        
        lt_dead = df_lt10.copy()
        lt_dead['Date_Mov'] = pd.to_datetime(lt_dead[c_date_lt], errors='coerce')
        cutoff_date = datetime.datetime.now() - datetime.timedelta(days=days_limit)
        
        dead_stock = lt_dead[lt_dead['Date_Mov'] < cutoff_date].copy()
        if not dead_stock.empty:
            dead_stock['Dní bez pohybu'] = (datetime.datetime.now() - dead_stock['Date_Mov']).dt.days
            disp_dead = dead_stock[[c_bin_lt, c_bintype_lt, c_mat_lt, c_qty_lt, c_date_lt, 'Dní bez pohybu']].sort_values('Dní bez pohybu', ascending=False)
            disp_dead.columns = ['Pozice', 'Typ', 'Materiál', 'Kusů', 'Datum posledního pohybu', 'Dní bez pohybu']
            st.error(f"Nalezeno {len(dead_stock)} palet/boxů, které se nehnuly déle než {days_limit} dní!")
            st.dataframe(disp_dead, hide_index=True, use_container_width=True)
        else: st.success("Sklad je čistý, nemáte žádné ležáky!")
