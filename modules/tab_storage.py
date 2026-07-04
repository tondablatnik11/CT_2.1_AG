import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import re
from modules.safe_render import ErrorBoundary, safe_render

try:
    fast_render = st.fragment
except AttributeError:
    fast_render = lambda f: f

def extract_num(part):
    if not part: return 0
    digits = re.sub(r'\D', '', str(part))
    if digits: return int(digits)
    letters = re.sub(r'[^A-Za-z]', '', str(part))
    if letters: return sum(ord(c.upper()) - 64 for c in letters)
    return 0

def parse_bin_coords(bin_str):
    s = str(bin_str).strip()
    pts = s.split('-')
    
    aisle, stack, level, pos = 0, 0, 0, 0
    try:
        if len(pts) >= 4:
            aisle, stack, level, pos = extract_num(pts[0]), extract_num(pts[1]), extract_num(pts[2]), extract_num(pts[3])
        elif len(pts) == 3:
            aisle, stack, level = extract_num(pts[0]), extract_num(pts[1]), extract_num(pts[2])
        elif len(pts) == 2:
            aisle, stack = extract_num(pts[0]), extract_num(pts[1])
        else:
            nums = re.findall(r'\d+', s)
            if len(nums) >= 3:
                aisle, stack, level = int(nums[0]), int(nums[1]), int(nums[2])
            elif len(nums) == 2:
                aisle, stack = int(nums[0]), int(nums[1])
            else:
                aisle = extract_num(s)
    except: pass
    
    return aisle, stack, level, pos

@safe_render(fallback_message="⚠️ Chyba při vykreslování Skladu (Storage)")
def render_storage(df_lx03, df_lt10, df_marm, df_pick):
    st.markdown("<div class='section-header'><h3>🏢 Rídící Věž Skladu (Control Tower)</h3><p>Plný přehled zón, půdorysné mapy (2D Layout), vizualizace frekvence pickování a detekce přesunů/ležáků.</p></div>", unsafe_allow_html=True)

    if df_lx03 is None or df_lx03.empty or df_lt10 is None or df_lt10.empty:
        st.warning("⚠️ Chybí reporty **LX03** nebo **LT10**. Nahrajte je prosím na hlavní obrazovce Admin Zóny.")
        return

    # --- BEZPEČNÁ DETEKCE SLOUPCŮ ---
    def find_zone_col(df):
        kws = ['SKLAD', 'WAREHOUSE', 'LAGERNUMMER', 'LGNUM', 'TYP SKLAD', 'STORAGE TYPE', 'LAGERTYP', 'LGTYP', 'SEKTOR']
        for c in df.columns:
            if any(k in str(c).upper() for k in kws):
                s_vals = df[c].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.lstrip('0')
                if s_vals.isin(['800', '820']).any(): return c
        return None

    c_type_lx = find_zone_col(df_lx03)
    c_bin_lx = next((c for c in df_lx03.columns if any(k in str(c).upper() for k in ['STORAGE BIN', 'SKLADOVÉ MÍSTO', 'LAGERPLATZ'])), None)
    c_mat_lx = next((c for c in df_lx03.columns if 'MATERIAL' in str(c).upper() or 'MATERIÁL' in str(c).upper()), None)
    c_bintype_lx = next((c for c in df_lx03.columns if any(k in str(c).upper() for k in ['BIN TYPE', 'TYP MÍST', 'PLATZTYP'])), None)

    c_type_lt = find_zone_col(df_lt10)
    c_mat_lt = next((c for c in df_lt10.columns if 'MATERIAL' in str(c).upper() or 'MATERIÁL' in str(c).upper()), None)
    c_qty_lt = next((c for c in df_lt10.columns if any(k in str(c).upper() for k in ['AVAILABLE STOCK', 'ZÁSOBA K DISP', 'VERFÜGBARER BESTAND', 'MNOŽSTVÍ'])), None)
    c_bintype_lt = next((c for c in df_lt10.columns if any(k in str(c).upper() for k in ['BIN TYPE', 'TYP MÍST', 'PLATZTYP'])), None)
    c_bin_lt = next((c for c in df_lt10.columns if any(k in str(c).upper() for k in ['STORAGE BIN', 'SKLADOVÉ MÍSTO', 'LAGERPLATZ'])), None)
    c_date_lt = next((c for c in df_lt10.columns if 'LAST MOVEMENT' in str(c).upper() or 'POSLEDNÍ POHYB' in str(c).upper() or 'BEWEGUNG' in str(c).upper()), None)
    
    # Heatmap Pick dataset
    c_pick_bin = None
    if df_pick is not None and not df_pick.empty:
        c_pick_bin = next((c for c in df_pick.columns if any(k in str(c).upper() for k in ['ZDROJ.MÍSTO', 'SOURCE BIN', 'VLPLA', 'VL.PLATZ'])), None)
        pick_counts = {}
        if c_pick_bin: pick_counts = df_pick[c_pick_bin].astype(str).str.strip().value_counts().to_dict()

    # --- FILTRACE NA ZÓNY 800/820 ---
    lx_clean = df_lx03.copy()
    if c_type_lx:
        lx_clean['Zone_Code'] = lx_clean[c_type_lx].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.lstrip('0')
        lx_clean = lx_clean[lx_clean['Zone_Code'].isin(['800', '820'])].copy()
    else: lx_clean['Zone_Code'] = 'ALL'

    lt_clean = df_lt10.copy()
    if c_type_lt:
        var_zone = lt_clean[c_type_lt].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.lstrip('0')
        lt_clean = lt_clean[var_zone.isin(['800', '820'])].copy()

    if lx_clean.empty:
        st.error("❌ Kritická chyba: Repor LX03 po filtraci na zóny 800 a 820 neobsahuje žádná data.")
        return

    # --- GENEROVÁNÍ GEOMETRIE ---
    coords = lx_clean[c_bin_lx].apply(parse_bin_coords).tolist()
    lx_clean['Raw_Aisle'] = [c[0] for c in coords]
    lx_clean['Raw_Stack'] = [c[1] for c in coords]
    
    # Izolace pouze reálných fyzických uliček (ne bufferů) pro vykreslování
    main_layout = lx_clean[(lx_clean['Raw_Aisle'] > 0) & (lx_clean['Raw_Aisle'] <= 150) & (lx_clean['Raw_Stack'] > 0)].copy()
    
    if c_mat_lx:
        main_layout['Is_Empty'] = main_layout[c_mat_lx].astype(str).str.strip().str.lower().isin(['<<empty>>', 'nan', '', 'none', 'null'])
    else:
        main_layout['Is_Empty'] = True
        
    if c_pick_bin: main_layout['Picks'] = main_layout[c_bin_lx].astype(str).str.strip().map(pick_counts).fillna(0)
    else: main_layout['Picks'] = 0

    # =========================================================================
    # ROZVRŽENÍ TABS
    # =========================================================================
    t1, t2, t3, t4 = st.tabs(["📊 Kapacity & Zóny", "🗺️ 2D Půdorys", "🔥 Heatmapa Pickování", "💡 Analýza (Přesuny & Ležáky)"])

    with t1:
        st.markdown("#### Rozbor Využití Skladových Zón")
        if c_bintype_lx and c_mat_lx:
            zones = ['800', '820'] if c_type_lx else ['ALL']
            for sk_zone in zones:
                df_zone = lx_clean[lx_clean['Zone_Code'] == sk_zone].copy() if sk_zone != 'ALL' else lx_clean.copy()
                if df_zone.empty: continue
                
                df_zone['Is_Empty'] = df_zone[c_mat_lx].astype(str).str.strip().str.lower().isin(['<<empty>>', 'nan', '', 'null'])
                obs, vol = sum(~df_zone['Is_Empty']), sum(df_zone['Is_Empty'])
                celkem = obs + vol
                
                st.markdown(f"#### 🏭 Budova / Zóna: {sk_zone}")
                c_m, c_p, c_b = st.columns([1, 1.2, 2])
                with c_m:
                    st.metric("Celková kapacita", f"{celkem} lok.")
                    st.metric("Plné", f"{obs}", f"{(obs/(celkem if celkem>0 else 1)*100):.1f} % obsazenost", delta_color="off")
                    st.metric("Volné místo", f"{vol}")
                with c_p:
                    fig_p = px.pie(names=['Obsazeno', 'Volno'], values=[obs, vol], hole=0.75, color_discrete_sequence=['#f59e0b', '#10b981'])
                    fig_p.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', showlegend=False, margin=dict(t=10,b=10,l=10,r=10))
                    st.plotly_chart(fig_p, width="stretch", key=f"pie_{sk_zone}")
                with c_b:
                    b_agg = df_zone.groupby([c_bintype_lx, 'Is_Empty']).size().reset_index(name='C')
                    b_agg['Stav'] = np.where(b_agg['Is_Empty'], 'Volno', 'Obsazeno')
                    fig_b = px.bar(b_agg, x=c_bintype_lx, y='C', color='Stav', barmode='stack', color_discrete_map={'Volno':'#10b981', 'Obsazeno':'#f59e0b'})
                    fig_b.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', xaxis_title="", yaxis_title="Míst", margin=dict(t=10,b=10))
                    st.plotly_chart(fig_b, width="stretch", key=f"bar_{sk_zone}")
                st.divider()

    with t2:
        st.markdown("#### 🗺️ 2D Půdorys Skladu (Floor Plan)")
        st.caption("Pohled shora na geometrii regálů. X = Řady, Y = Domy. Zelená barva indukuje volné komíny, oranžová přeplněné.")
        if not main_layout.empty:
            # Agregace 3D na 2D pudorys (kolik je v dome vyskove a kapacitne plno)
            agg_2d = main_layout.groupby(['Raw_Aisle', 'Raw_Stack']).agg(Total=('Is_Empty', 'count'), Free=('Is_Empty', 'sum')).reset_index()
            agg_2d['Capacity'] = (agg_2d['Total'] - agg_2d['Free']) / agg_2d['Total']
            
            fig_2d = px.scatter(
                agg_2d, x='Raw_Aisle', y='Raw_Stack', color='Capacity',
                color_continuous_scale=[(0, '#10b981'), (0.5, '#fbbf24'), (1, '#ef4444')],
                labels={'Raw_Aisle':'Řada (Ulička)', 'Raw_Stack':'Dům (Stack)', 'Capacity':'Zaplněno'},
                hover_data={'Total':True, 'Free':True}
            )
            fig_2d.update_traces(marker=dict(symbol='square', size=14, line=dict(width=1, color='rgba(255,255,255,0.2)')))
            fig_2d.update_layout(
                paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                xaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.05)', dtick=1),
                yaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.05)', autorange="reversed"), # reversed so front of warehouse is bottom
                height=700, margin=dict(l=0, r=0, b=0, t=10)
            )
            st.plotly_chart(fig_2d, width="stretch")

    with t3:
        st.markdown("#### 🔥 Teplotní Mapa Odběrů (Heatmapa z OE-Times / LTAK)")
        st.caption("Vykresluje ohniska frekvence vychystávání v půdorysu 2D na základě dat o pickování.")
        if c_pick_bin and not main_layout.empty:
            p_agg = main_layout.groupby(['Raw_Aisle', 'Raw_Stack'])['Picks'].sum().reset_index()
            max_p = p_agg['Picks'].max() if p_agg['Picks'].max() > 0 else 1
            
            fig_h = px.scatter(
                p_agg, x='Raw_Aisle', y='Raw_Stack', color='Picks', size='Picks',
                color_continuous_scale='Inferno', size_max=25,
                labels={'Raw_Aisle':'Řada', 'Raw_Stack':'Dům', 'Picks':'Počet Picků'}
            )
            fig_h.update_traces(marker=dict(symbol='square', line=dict(width=0)))
            fig_h.update_layout(
                paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                xaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.05)', dtick=1),
                yaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.05)', autorange="reversed"),
                height=700, margin=dict(l=0, r=0, b=0, t=10)
            )
            st.plotly_chart(fig_h, width="stretch")
        else:
            st.info("Nahrajte pickovací export (LTAK/LTAP s detaily ZDROJ.MÍSTA) na nástěnce a mapa se automaticky rozsvítí.")

    with t4:
        st.markdown("#### 💡 Optimalizace: Cílené přesuny plýtvajícího místa z P na K1")
        col_sl1, _ = st.columns(2)
        with col_sl1: limit_ks = st.number_input("Tolerovaný maximální počet kusů na hledaných pozicích (Downsizing):", 1, 100, 10)
        
        if c_mat_lt and c_qty_lt and c_bintype_lt:
            # Oprava filtrace na neomezeno dimenzemi a striktní typy
            val_t = ['EP1', 'P1', 'EP2', 'P2', 'EP3', 'PE3', 'P3', 'EP4', 'P4']
            lt_ep = lt_clean[lt_clean[c_bintype_lt].astype(str).str.strip().str.upper().isin(val_t)].copy()
            lt_ep['Q_Num'] = pd.to_numeric(lt_ep[c_qty_lt], errors='coerce').fillna(0)
            cands = lt_ep[(lt_ep['Q_Num'] > 0) & (lt_ep['Q_Num'] <= limit_ks)].copy()
            
            if not cands.empty:
                st.success(f"Nalezeno {len(cands)} zbytečně blokovaných obřích pozic, kde zbývá pouze <= {limit_ks} ks! Vhodné přeskladnit do regálu.")
                t_disp = cands[[c_bin_lt, c_bintype_lt, c_mat_lt, c_qty_lt]].copy()
                t_disp.columns = ['Zablokovaná pozice', 'Zablokovaný Typ', 'Materiál (SAP)', 'Počet ks k přehození']
                st.dataframe(t_disp.sort_values('Počet ks k přehození'), hide_index=True, width="stretch")
            else: st.info(f"Nenalezeny žádné plýtvající boxy (0 výskytů s <= {limit_ks} ks).")
            
        st.divider()
        st.markdown("#### 💀 Audit smrti: Ležáky bez známky života (Dead Stock)")
        if c_date_lt and c_mat_lt:
            limit_days = st.slider("Minimální expozice izolace (Počet dní bez pohybu vzhledem k dnešku):", 30, 365, 90, 10)
            ld = lt_clean.copy()
            ld['D_Mov'] = pd.to_datetime(ld[c_date_lt], errors='coerce', dayfirst=True)
            now = pd.Timestamp.now().normalize()
            cut = now - pd.Timedelta(days=limit_days)
            # NaT = žádný záznam o pohybu → nejsilnější kandidát na ležáka.
            # Původní `D_Mov < cut` tyto řádky tiše zahazoval (NaT porovnání = False).
            ds = ld[(ld['D_Mov'].isna()) | (ld['D_Mov'] < cut)].copy()
            if not ds.empty:
                days = (now - ds['D_Mov']).dt.days
                # Řádky bez data: neznámé stáří, ale prokazatelně bez pohybu → nahoru
                ds['Dni_bez'] = days.fillna(-1).astype(int)
                ds['D_Mov_Disp'] = ds['D_Mov'].dt.strftime('%d.%m.%Y').fillna('— bez záznamu —')
                ds['Dni_bez_Disp'] = ds['Dni_bez'].apply(
                    lambda d: '∞ (bez data)' if d < 0 else str(d)
                )
                # Řazení: nejdřív bez data (∞), pak sestupně dle stáří
                ds = ds.sort_values(['Dni_bez'], ascending=False)
                ds_no_date = ds[ds['Dni_bez'] < 0]
                ds_dated = ds[ds['Dni_bez'] >= 0].sort_values('Dni_bez', ascending=False)
                ds = pd.concat([ds_no_date, ds_dated])
                h_disp = ds[[c_bin_lt, c_bintype_lt, c_mat_lt, c_qty_lt, 'D_Mov_Disp', 'Dni_bez_Disp']]
                h_disp.columns = ['Lokace krypty', 'Typ', 'Materiál', 'Zásoba zamražena', 'Datum zkázy', 'Dní mrtvo']
                st.warning(f"Kritický nález: {len(ds)} palet nevykázalo fyzický pohyb z regálu déle než {limit_days} dní (včetně palet zcela bez záznamu pohybu).")
                st.dataframe(h_disp, hide_index=True, width="stretch")
            else: st.success(f"Sklad se hejbe skvěle! Žádný materiál neleží déle jak {limit_days} dní ladem.")
