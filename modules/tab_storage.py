import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import re

try:
    fast_render = st.fragment
except AttributeError:
    fast_render = lambda f: f

def parse_bin_coords(bin_str):
    s = str(bin_str).strip()
    pts = s.split('-')
    
    aisle, stack, level, pos = 0, 0, 0, 0
    try:
        if len(pts) >= 4:
            aisle = int(re.sub(r'\D', '', pts[0])) if re.sub(r'\D', '', pts[0]) else 0
            stack = int(re.sub(r'\D', '', pts[1])) if re.sub(r'\D', '', pts[1]) else 0
            level = int(re.sub(r'\D', '', pts[2])) if re.sub(r'\D', '', pts[2]) else 0
            pos = int(re.sub(r'\D', '', pts[3])) if re.sub(r'\D', '', pts[3]) else 0
        elif len(pts) == 3:
            aisle = int(re.sub(r'\D', '', pts[0])) if re.sub(r'\D', '', pts[0]) else 0
            stack = int(re.sub(r'\D', '', pts[1])) if re.sub(r'\D', '', pts[1]) else 0
            level = int(re.sub(r'\D', '', pts[2])) if re.sub(r'\D', '', pts[2]) else 0
        elif len(pts) == 2:
            aisle = int(re.sub(r'\D', '', pts[0])) if re.sub(r'\D', '', pts[0]) else 0
            stack = int(re.sub(r'\D', '', pts[1])) if re.sub(r'\D', '', pts[1]) else 0
        else:
            nums = re.findall(r'\d+', s)
            if len(nums) >= 3:
                aisle, stack, level = int(nums[0]), int(nums[1]), int(nums[2])
    except: pass
    
    return aisle, stack, level, pos

@fast_render
def render_storage(df_lx03, df_lt10, df_marm, df_pick):
    st.markdown("<div class='section-header'><h3>🏢 Skladový Dispečink & 3D Mapa (Digital Twin)</h3><p>Detailní přehled kapacity, optimalizace pozic, detekce ležáků a 3D vizualizace zóny 800/820.</p></div>", unsafe_allow_html=True)

    if df_lx03 is None or df_lx03.empty or df_lt10 is None or df_lt10.empty:
        st.warning("⚠️ Chybí reporty **LX03** nebo **LT10**. Nahrajte je prosím v Admin Zóně.")
        return

    # --- PŘÍPRAVA DAT ---
    c_type_lx = next((c for c in df_lx03.columns if 'STORAGE TYPE' in str(c).upper() or 'TYP SKLAD' in str(c).upper() or 'LAGERTYP' in str(c).upper()), None)
    c_bin_lx = next((c for c in df_lx03.columns if 'STORAGE BIN' in str(c).upper() or 'SKLADOVÉ MÍSTO' in str(c).upper() or 'LAGERPLATZ' in str(c).upper()), None)
    c_mat_lx = next((c for c in df_lx03.columns if 'MATERIAL' in str(c).upper() or 'MATERIÁL' in str(c).upper()), None)
    c_bintype_lx = next((c for c in df_lx03.columns if 'STORAGE BIN TYPE' in str(c).upper() or 'TYP SKLAD' in str(c).upper() or 'PLATZTYP' in str(c).upper()), None)
    
    c_type_lt = next((c for c in df_lt10.columns if 'STORAGE TYPE' in str(c).upper() or 'TYP SKLAD' in str(c).upper() or 'LAGERTYP' in str(c).upper()), None)
    c_mat_lt = next((c for c in df_lt10.columns if 'MATERIAL' in str(c).upper() or 'MATERIÁL' in str(c).upper()), None)
    c_qty_lt = next((c for c in df_lt10.columns if 'AVAILABLE STOCK' in str(c).upper() or 'ZÁSOBA K DISP' in str(c).upper() or 'VERFÜGBARER BESTAND' in str(c).upper()), None)
    c_bintype_lt = next((c for c in df_lt10.columns if 'STORAGE BIN TYPE' in str(c).upper() or 'TYP SKLAD' in str(c).upper() or 'PLATZTYP' in str(c).upper()), None)
    c_bin_lt = next((c for c in df_lt10.columns if 'STORAGE BIN' in str(c).upper() or 'SKLADOVÉ MÍSTO' in str(c).upper() or 'LAGERPLATZ' in str(c).upper()), None)
    c_date_lt = next((c for c in df_lt10.columns if 'LAST MOVEMENT' in str(c).upper() or 'POSLEDNÍ POHYB' in str(c).upper() or 'LETZTE BEWEGUNG' in str(c).upper()), None)

    lx_clean = df_lx03.copy()
    if c_type_lx: lx_clean = lx_clean[lx_clean[c_type_lx].astype(str).str.strip().str.lstrip('0').isin(['800', '820'])]

    lt_clean = df_lt10.copy()
    if c_type_lt: lt_clean = lt_clean[lt_clean[c_type_lt].astype(str).str.strip().str.lstrip('0').isin(['800', '820'])]

    tab1, tab2, tab3 = st.tabs(["🚀 Optimalizace & Volná kapacita", "🗺️ 3D Interaktivní Mapa Skladu", "💀 Analýza Ležáků (Dead Stock)"])

    # ============================
    # TAB 1: KAPACITA A PŘESUNY
    # ============================
    with tab1:
        st.markdown("#### 📊 Kapacita skladu (Rozděleno dle Zón)")
        if c_bintype_lx and c_mat_lx and c_type_lx:
            for sk_zone in ['800', '820']:
                df_zone = lx_clean[lx_clean[c_type_lx].astype(str).str.strip().str.lstrip('0') == sk_zone].copy()
                if df_zone.empty: continue
                
                st.markdown(f"##### Skladová Zóna {sk_zone}")
                df_zone['Is_Empty'] = df_zone[c_mat_lx].astype(str).str.strip().str.lower().isin(['<<empty>>', 'nan', ''])
                
                obs = len(df_zone[df_zone['Is_Empty'] == False])
                vol = len(df_zone[df_zone['Is_Empty'] == True])
                celkem = obs + vol
                
                c_met, c_pie, c_bar = st.columns([1, 1, 2])
                with c_met:
                    st.metric(f"Míst Celkem [{sk_zone}]", f"{celkem}")
                    st.metric("Obsazeno", f"{obs}", f"{(obs/celkem*100):.1f}%" if celkem else "0%")
                    st.metric("Volno", f"{vol}")
                    
                with c_pie:
                    fig_pie = px.pie(names=['Obsazené', 'Volné'], values=[obs, vol], hole=0.7, color_discrete_sequence=['#ef4444', '#10b981'])
                    fig_pie.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', showlegend=False, margin=dict(t=10,b=10,l=10,r=10))
                    st.plotly_chart(fig_pie, use_container_width=True, key=f"pie_{sk_zone}")
                    
                with c_bar:
                    cap_agg = df_zone.groupby([c_bintype_lx, 'Is_Empty']).size().reset_index(name='Count')
                    cap_agg['Stav'] = np.where(cap_agg['Is_Empty'], 'Volné', 'Obsazené')
                    fig_bar = px.bar(cap_agg, x=c_bintype_lx, y='Count', color='Stav', barmode='stack', color_discrete_map={'Volné': '#10b981', 'Obsazené': '#ef4444'})
                    fig_bar.update_layout(title="Obsazenost dle typu pozice", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', xaxis_title="")
                    st.plotly_chart(fig_bar, use_container_width=True, key=f"bar_{sk_zone}")
                st.divider()

        st.markdown("#### 💡 Doporučené přesuny zbytkových kusů z Palet do Regálů (K1)")
        st.write("Skener hledá palety na pozicích (EP1/P1, EP2/P2, EP3/PE3, EP4/P4), kde zůstal jen nepatrný počet kusů, které zbytečně blokují paletové místo a lze je ručně přeskladnit.")
        col_sl1, col_sl2 = st.columns(2)
        with col_sl1: limit_ks = st.slider("Max. limit kusů na paletě pro návrh na přesun:", min_value=1, max_value=50, value=10, step=1)
        
        if c_mat_lt and c_qty_lt and c_bintype_lt:
            valid_types = ['EP1', 'P1', 'EP2', 'P2', 'EP3', 'PE3', 'P3', 'EP4', 'P4']
            lt_ep = lt_clean[lt_clean[c_bintype_lt].astype(str).str.strip().str.upper().isin(valid_types)].copy()
            lt_ep['Qty_Num'] = pd.to_numeric(lt_ep[c_qty_lt], errors='coerce').fillna(0)
            candidates = lt_ep[(lt_ep['Qty_Num'] > 0) & (lt_ep['Qty_Num'] <= limit_ks)].copy()
            
            if not candidates.empty:
                st.success(f"Nalezeno {len(candidates)} palet vhodných k nezbytnému spojení / 'Downsizingu' na KLT!")
                disp_app = candidates[[c_bin_lt, c_bintype_lt, c_mat_lt, c_qty_lt]].copy()
                disp_app.columns = ['Současná pozice', 'Typ lokace', 'Materiál (SAP)', 'Zásoba k přesunu']
                st.dataframe(disp_app.sort_values('Zásoba k přesunu'), hide_index=True, use_container_width=True)
            else: st.info(f"Ve skladech nejsou instalovány žádné palety specifikovaných typů s objemem menším jak {limit_ks} ks.")

    # ============================
    # TAB 2: 3D MAPA SKLADU
    # ============================
    with tab2:
        st.markdown("#### 🗺️ 3D Digital Twin (Aktuální stav pozic - LX03)")
        st.write("Interaktivní reprezentace struktury skladu. Zelené body = volno, Červené = plno.")
        
        if c_bin_lx and c_mat_lx:
            df_map = lx_clean.copy()
            df_map['Is_Empty'] = df_map[c_mat_lx].astype(str).str.strip().str.lower().isin(['<<empty>>', 'nan', ''])
            
            coords = df_map[c_bin_lx].apply(parse_bin_coords).tolist()
            # Fyzikální mapa souřadnic:
            # X = Ulička. Násobíme masivně (50) aby se mezi uličky vešel projíždějící vozík.
            # Y = Dům + Pozice. Dům násobíme (6), protože jsou v něm 3 palety nebo víc KLT. Pozici jen přičteme.
            # Z = Výška. SAP výšky 10-70 dělíme 3. Malé výšky (1-6) ponecháme.
            df_map['X'] = [c[0] * 50.0 for c in coords]
            df_map['Y'] = [(c[1] * 6.0) + c[3] for c in coords]
            df_map['Z'] = [(c[2] if c[2] <= 10 else c[2] / 3.0) + 0.5 for c in coords]
            
            # Bezpečnostní filtr, kdyby se náhodou připletlo vadné jméno pozice bez čísel
            df_map = df_map[df_map['X'] > 0].copy()
            
            df_map['Status'] = np.where(df_map['Is_Empty'], 'Volno', 'Obsazeno')
            
            # Barevná paleta:
            # Volno -> Vysoce průhledná "duchová" zelená krabice
            # Obsazeno -> Realistická plná barva (hnědožlutá textura krabic / palet s červeným nádechem pro plnost)
            df_map['Color'] = np.where(df_map['Is_Empty'], 'rgba(16, 185, 129, 0.05)', '#d97706')
            df_map['LineColor'] = np.where(df_map['Is_Empty'], 'rgba(16, 185, 129, 0.3)', '#92400e')
            
            # --- 1. Rychlý Render: Oranžové Horizontální Nosníky (Rack Beams) ---
            beam_x, beam_y, beam_z = [], [], []
            for (ul, pa), group in df_map.groupby(['X', 'Z']):
                beam_x.extend([ul, ul, None])
                beam_y.extend([group['Y'].min() - 0.5, group['Y'].max() + 0.5, None])
                beam_z.extend([pa - 0.2, pa - 0.2, None]) # Nosník je těsně pod paletou
            beam_trace = go.Scatter3d(x=beam_x, y=beam_y, z=beam_z, mode='lines', line=dict(color='#ea580c', width=5), hoverinfo='skip', showlegend=False)

            # --- 2. Rychlý Render: Modré Vertikální Sloupy (Rack Pillars) ---
            pillar_x, pillar_y, pillar_z = [], [], []
            for (ul, sl), group in df_map.groupby(['X', 'Y']):
                pillar_x.extend([ul, ul, None])
                pillar_y.extend([sl - 0.5, sl - 0.5, None])
                pillar_z.extend([0, group['Z'].max() + 0.6, None])
            
            # Přidání stojny na samotný konec každé řady
            for ul, group in df_map.groupby('X'):
                max_sl = group['Y'].max()
                pillar_x.extend([ul, ul, None])
                pillar_y.extend([max_sl + 0.5, max_sl + 0.5, None])
                pillar_z.extend([0, group['Z'].max() + 0.6, None])
            pillar_trace = go.Scatter3d(x=pillar_x, y=pillar_y, z=pillar_z, mode='lines', line=dict(color='#1e3a8a', width=7), hoverinfo='skip', showlegend=False)
            
            # --- 3. Betonová Podlaha (Floor) ---
            x_min, x_max = df_map['X'].min() - 2, df_map['X'].max() + 2
            y_min, y_max = df_map['Y'].min() - 2, df_map['Y'].max() + 2
            floor_trace = go.Mesh3d(
                x=[x_min, x_max, x_max, x_min], y=[y_min, y_min, y_max, y_max], z=[0, 0, 0, 0],
                color='#cbd5e1', opacity=0.15, hoverinfo='skip', showlegend=False
            )

            # --- 4. Samotné Palety / Náklad (Pojiva na nosnících) ---
            pallets_trace = go.Scatter3d(
                x=df_map['X'], y=df_map['Y'], z=df_map['Z'],
                mode='markers',
                marker=dict(
                    symbol='square', size=7, 
                    color=df_map['Color'], 
                    line=dict(width=3, color=df_map['LineColor'])
                ),
                text="Lokace: " + df_map[c_bin_lx] + "<br>Zásoba: " + df_map[c_mat_lx] + "<br>Stav: " + df_map['Status'],
                hoverinfo='text', name='Lokace'
            )
            
            fig3d = go.Figure(data=[floor_trace, pillar_trace, beam_trace, pallets_trace])
            
            fig3d.update_layout(
                paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                scene=dict(
                    aspectmode='data', # Extrémně důležité: Zachová fyzikální proporce skladu (nebude to zdeformovaná kostka)
                    xaxis=dict(showgrid=False, zeroline=False, showticklabels=False, title='', showbackground=False),
                    yaxis=dict(showgrid=False, zeroline=False, showticklabels=False, title='', showbackground=False),
                    zaxis=dict(showgrid=False, zeroline=False, showticklabels=False, title='', showbackground=False),
                    camera=dict(eye=dict(x=-1.5, y=-1.5, z=0.8)) # Nástřih kamery shora z rohu jako na kamerovém systému
                ),
                margin=dict(l=0, r=0, b=0, t=0), height=750
            )
            st.plotly_chart(fig3d, use_container_width=True)
            
            st.info("💡 **Tip:** Toto je přímý Digital Twin vygenerovaný architekturou vašich dat. Oranžové linie značí nosníky, modré svislé stojny drží regály. Prázdný prostor ukazuje uličky. Rotujte myší, scrollujte pro přiblížení k detailům lokací.")

    # ============================
    # TAB 3: LEŽÁKY (DEATH STOCK)
    # ============================
    with tab3:
        st.markdown("#### 💀 Mrtvá zásoba (Sledování ležáků - LT10)")
        if c_date_lt and c_mat_lt:
            col_ds1, _ = st.columns(2)
            with col_ds1: days_limit = st.slider("Identifikovat palety bez pohybu déle než X dní:", min_value=30, max_value=365, value=90, step=10)
            
            lt_dead = lt_clean.copy()
            lt_dead['Date_Mov'] = pd.to_datetime(lt_dead[c_date_lt], errors='coerce', dayfirst=True)
            cutoff_date = pd.Timestamp.now().normalize() - pd.Timedelta(days=days_limit)
            
            dead_stock = lt_dead[lt_dead['Date_Mov'] < cutoff_date].copy()
            if not dead_stock.empty:
                dead_stock['Dní bez pohybu'] = (pd.Timestamp.now().normalize() - dead_stock['Date_Mov']).dt.days
                disp_dead = dead_stock[[c_bin_lt, c_bintype_lt, c_mat_lt, c_qty_lt, c_date_lt, 'Dní bez pohybu']].sort_values('Dní bez pohybu', ascending=False)
                disp_dead.columns = ['Lokace', 'Typ. poz', 'Skladový materiál', 'Dostupné Množství', 'Datum posledního pohybu', 'Uplynulých Dní']
                st.error(f"Nalezeno {len(dead_stock)} palet/boxů, na které nebylo sáhnuto déle než {days_limit} dní!")
                st.dataframe(disp_dead, hide_index=True, use_container_width=True)
            else: st.success(f"Geniální! Tento sklad nemá žádné skryté ležáky s expozicí delší jak {days_limit} dní.")
