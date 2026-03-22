import streamlit as st
import pandas as pd
import numpy as np
import re

# Globální nastavení barev a designu pro všechny grafy Plotly - MODERN 2026 EDITION
CHART_COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#0ea5e9', '#ec4899', '#14b8a6']

CHART_LAYOUT = dict(
    paper_bgcolor='rgba(0,0,0,0)', 
    plot_bgcolor='rgba(0,0,0,0)',
    font=dict(color='#cbd5e1', size=13, family="'Plus Jakarta Sans', sans-serif"),
    colorway=CHART_COLORS,
    margin=dict(l=10, r=10, t=50, b=10),
    legend=dict(orientation='h', yanchor='bottom', y=1.05, xanchor='left', x=0, bgcolor='rgba(0,0,0,0)'),
    hovermode="x unified",
    hoverlabel=dict(bgcolor="rgba(15, 23, 42, 0.9)", font_size=13, font_family="'Plus Jakarta Sans', sans-serif"),
    xaxis=dict(showgrid=False, zeroline=False),
    yaxis=dict(gridcolor='rgba(255, 255, 255, 0.05)', gridwidth=1, zerolinecolor='rgba(255, 255, 255, 0.1)')
)

QUEUE_DESC = {
    'PI_PL (Single)': 'Single SKU Pal',
    'PI_PL (Total)': 'Single SKU Pal + Mix Pal',
    'PI_PL_OE (Single)': 'OE Single SKU Pal',
    'PI_PL_OE (Total)': 'OE Single SKU Pal + Mix Pal',
    'PI_PA_OE': 'OE Parcel',
    'PI_PL (Mix)': 'Mix Pal',
    'PI_PA': 'Parcel',
    'PI_PL_OE (Mix)': 'OE Mix Pal',
    'PI_PA_RU': 'Parcel Express',
    'PI_PL_FU': 'Full Pall',
    'PI_PL_FUOE': 'OE Full Pal'
}
BOX_UNITS = {'AEK', 'KAR', 'KART', 'PAK', 'VPE', 'CAR', 'BLO', 'ASK', 'BAG', 'PAC'}

TEXTS = {
    'cs': {
        'switch_lang': "🇬🇧 Switch to English", 'title': "🏢 Warehouse Control Tower",
        'desc': "Kompletní End-to-End analýza: od fyzického pickování až po čas balení.",
        'sec_ratio': "🎯 Spolehlivost dat a zdroj výpočtů",
        'ratio_desc': "Z jakých podkladů aplikace vycházela (Ukazatel kvality dat ze SAPu):",
        'logic_explain_title': "ℹ️ Podrobná metodika: Jak aplikace vypočítává výsledná data?",
        'logic_explain_text': "Tento analytický model detailně simuluje fyzickou zátěž skladníka a balení:\n\n**1. Dekompozice na celá balení (Krabice)**\nSystém matematicky rozdělí množství na plné krabice od největší. Co krabice, to **1 fyzický pohyb**.\n\n**2. Analýza volných kusů (Limity)**\nZbylé rozbalené kusy podléhají kontrole ergonomických limitů. Každý těžký/velký kus = **1 pohyb**, lehké kusy se berou do hrsti.\n\n**3. Obalová hierarchie (Tree-Climbing)**\nPomocí VEKP a VEPO se aplikace prokouše složitou strukturou balení až na hlavní kořen (Top-Level HU).\n\n**4. Časová náročnost (End-to-End)**\nPropojuje zjištěné fyzické pohyby a výsledné palety se záznamy z OE-Times.",
        'ratio_moves': "Podíl z celkového počtu POHYBŮ:",
        'ratio_exact': "Přesně (Krabice / Palety / Volné)", 'ratio_miss': "Odhady (Chybí balení)",
        'sec_queue_title': "📊 Průměrná náročnost dle typu pickování (Queue)",
        'q_col_queue': "Queue", 'q_col_desc': "Popis", 'q_col_to': "Počet TO", 'q_col_orders': "Zakázky",
        'q_col_loc': "Prům. lokací", 'q_col_mov_loc': "Prům. pohybů na lokaci", 'q_col_exact_loc': "Prům. přesně na lokaci",
        'q_pct_exact': "% Přesně", 'q_col_miss_loc': "Prům. odhad na lokaci", 'q_pct_miss': "% Odhad",
        'tab_dashboard': "📊 Dashboard & Queue", 'tab_pallets': "📦 Palety", 'tab_fu': "🏭 Celé palety (FU)",
        'tab_top': "🏆 TOP Materiály", 'tab_billing': "💰 Fakturace (VEKP)", 'tab_packing': "⏱️ Časy Balení (OE)", 'tab_audit': "🔍 Nástroje & Audit",
        'col_mat': "Materiál", 'col_qty': "Kusů celkem", 'col_mov': "Celkem pohybů", 'col_mov_exact': "Pohyby (Přesně)",
        'col_mov_miss': "Pohyby (Odhady)", 'col_wgt': "Hmotnost (kg)", 'col_max_dim': "Rozměr (cm)",
        'btn_download': "📥 Stáhnout kompletní report (Excel)"
    },
    'en': {
        'switch_lang': "🇨🇿 Přepnout do češtiny", 'title': "🏢 Warehouse Control Tower",
        'desc': "End-to-End analysis: from physical picking to packing times.",
        'sec_ratio': "🎯 Data Reliability & Source",
        'ratio_desc': "Data foundation (SAP Data Quality indicator):",
        'logic_explain_title': "ℹ️ Detailed Methodology: How does the app calculate results?",
        'logic_explain_text': "This analytical model meticulously simulates the picker's physical workload and packing:\n\n**1. Decomposition into Full Boxes**\nQuantities are split into full boxes from largest first. Each box = **1 physical move**.\n\n**2. Loose Pieces Analysis**\nRemaining pieces are checked against ergonomic limits. Heavy/large = **1 move each**, light pieces are grabbed together.\n\n**3. Packing Hierarchy (Tree-Climbing)**\nUsing VEKP and VEPO, the app climbs through complex nested packing structures up to the Top-Level HU.\n\n**4. End-to-End Time**\nCorrelates physical moves and final pallets with OE-Times to analyze packing speed.",
        'ratio_moves': "Share of total MOVEMENTS:",
        'ratio_exact': "Exact (Boxes / Pallets / Loose)", 'ratio_miss': "Estimates (Missing packaging)",
        'sec_queue_title': "📊 Average Workload by Queue",
        'q_col_queue': "Queue", 'q_col_desc': "Description", 'q_col_to': "TO Count", 'q_col_orders': "Orders",
        'q_col_loc': "Avg Locs", 'q_col_mov_loc': "Avg Moves per Loc", 'q_col_exact_loc': "Avg Exact per Loc",
        'q_pct_exact': "% Exact", 'q_col_miss_loc': "Avg Estimate per Loc", 'q_pct_miss': "% Estimate",
        'tab_dashboard': "📊 Dashboard & Queue", 'tab_pallets': "📦 Pallet Orders", 'tab_fu': "🏭 Full Pallets (FU)",
        'tab_top': "🏆 TOP Materials", 'tab_billing': "💰 Billing & Packing (VEKP)", 'tab_packing': "⏱️ Packing Times (OE)", 'tab_audit': "🔍 Tools & Audit",
        'col_mat': "Material", 'col_qty': "Total Pieces", 'col_mov': "Total Moves", 'col_mov_exact': "Moves (Exact)",
        'col_mov_miss': "Moves (Estimates)", 'col_wgt': "Weight (kg)", 'col_max_dim': "Max Dim (cm)",
        'btn_download': "📥 Download Comprehensive Report (Excel)"
    }
}

def t(key): 
    lang = st.session_state.get('lang', 'cs')
    return TEXTS.get(lang, TEXTS['cs']).get(key, key)

def get_match_key_vectorized(series):
    s = series.astype(str).str.strip().str.upper()
    mask_decimal = s.str.match(r'^\d+\.\d+$')
    s = s.copy()
    s[mask_decimal] = s[mask_decimal].str.rstrip('0').str.rstrip('.')
    mask_numeric = s.str.match(r'^0+\d+$')
    s[mask_numeric] = s[mask_numeric].str.lstrip('0')
    return s

def get_match_key(val):
    v = str(val).strip().upper()
    if '.' in v and v.replace('.', '').isdigit(): v = v.rstrip('0').rstrip('.')
    if v.isdigit(): v = v.lstrip('0') or '0'
    return v

def parse_packing_time(val):
    v = str(val).strip()
    if v in ['', 'nan', 'None', 'NaN']: return 0.0
    try:
        num = float(v)
        if num < 1.0: return num * 24 * 60
        return num
    except: pass
    parts = v.split(':')
    try:
        if len(parts) == 3: return int(parts[0])*60 + int(parts[1]) + float(parts[2])/60.0
        elif len(parts) == 2: return int(parts[0]) + float(parts[1])/60.0
    except: pass
    return 0.0

def fast_compute_moves(qty_list, queue_list, su_list, box_list, w_list, d_list, v_lim, d_lim, h_lim):
    res_total, res_exact, res_miss = [], [], []
    # 1. Ochrana výpočtů: Pokud je limit hrsti 0 nebo None, nastavíme na 1 pro zabránění ZeroDivisionError.
    safe_h_lim = max(1, int(h_lim)) if pd.notnull(h_lim) else 1
    
    for qty, q, su, boxes, w, d in zip(qty_list, queue_list, su_list, box_list, w_list, d_list):
        if pd.isna(qty) or qty <= 0:
            res_total.append(0); res_exact.append(0); res_miss.append(0); continue
            
        if str(q).upper() in ('PI_PL_FU', 'PI_PL_FUOE') and str(su).strip().upper() == 'X':
            res_total.append(1); res_exact.append(1); res_miss.append(0); continue
            
        # Ochrana proti nefunkčním datovým typům (nan / float na místě kolekcí)
        if not isinstance(boxes, (list, tuple)): 
            boxes = ()
        real_boxes = tuple([b for b in boxes if pd.notnull(b) and b > 1])
        
        # Ochrana extémů proti NaN u rozměrů a vah
        safe_w = float(w) if pd.notnull(w) else 0.0
        safe_d = float(d) if pd.notnull(d) else 0.0
        
        pb = pok = pmiss = 0
        zbytek = float(qty)
        for b in real_boxes:
            if zbytek >= b:
                m = int(zbytek // b)
                pb += m
                zbytek = zbytek % b
                
        if zbytek > 0:
            if safe_w >= v_lim or safe_d >= d_lim: 
                p = int(np.ceil(zbytek)) # Těžký předmět / 1 kus na pohyb jako fallback
            else: 
                p = int(np.ceil(zbytek / safe_h_lim))
                
            if len(real_boxes) > 0: 
                pok += p
            else: 
                pmiss += p
            
        res_total.append(pb + pok + pmiss)
        res_exact.append(pb + pok)
        res_miss.append(pmiss)
        
    return res_total, res_exact, res_miss


# ==========================================
# CENTRÁLNÍ MOZEK PRO DETEKCI VOLLPALET (Vylepšené párování SSU a HU)
# ==========================================

def safe_hu(val):
    v = str(val).strip()
    if v.lower() in ['nan', 'none', '']: return ''
    if v.endswith('.0'): v = v[:-2]
    return v

def safe_del(val):
    v = str(val).strip()
    if v.lower() in ['nan', 'none', '']: return ''
    if v.endswith('.0'): v = v[:-2]
    return v.lstrip('0')

def is_box(v):
    v = str(v).upper().strip()
    if v == 'CARTON-16': return False 
    if v in ['K1','K2','K3','K4','KLT','KLT1','KLT2']: return True
    if v.startswith('K') and len(v) <= 2: return True
    if 'CARTON' in v or 'BOX' in v or v in ['CT', 'CD3', 'CD', 'CR']: return True
    return False

def detect_vollpalettes(df_pick, df_vekp, df_vepo):
    voll_set = set()
    if any(df is None or df.empty for df in [df_pick, df_vekp, df_vepo]):
        return voll_set
        
    vepo_hu_col = next((c for c in df_vepo.columns if "Internal HU" in str(c) or "HU-Nummer intern" in str(c)), df_vepo.columns[0])
    valid_vepo_hus = set(df_vepo[vepo_hu_col].dropna().apply(safe_hu))
    
    vekp_hu_col = next((c for c in df_vekp.columns if "Internal HU" in str(c) or "HU-Nummer intern" in str(c)), df_vekp.columns[0])
    vekp_ext_col = df_vekp.columns[1]
    parent_col = next((c for c in df_vekp.columns if "higher-level" in str(c).lower() or "übergeordn" in str(c).lower() or "superordinate" in str(c).lower()), None)
    c_gen = next((c for c in df_vekp.columns if "Generated delivery" in str(c) or "generierte" in str(c).lower()), None)
    c_pm = next((c for c in df_vekp.columns if "Packmittel" in str(c) or "Packaging" in str(c) or "Pack. mat" in str(c)), None)
    
    # SUPER RYCHLÁ VERZE BEZ iterrows()
    c_gen_idx = df_vekp.columns.get_loc(c_gen) if c_gen else -1
    parent_idx = df_vekp.columns.get_loc(parent_col) if parent_col else -1
    pm_idx = df_vekp.columns.get_loc(c_pm) if c_pm else -1
    vekp_ext_idx = df_vekp.columns.get_loc(vekp_ext_col)
    vekp_hu_idx = df_vekp.columns.get_loc(vekp_hu_col)
    
    valid_roots = {}
    for r in df_vekp.itertuples(index=False):
        deliv = safe_del(r[c_gen_idx]) if c_gen_idx >= 0 else ""
        parent = safe_hu(r[parent_idx]) if parent_idx >= 0 else ""
        pm = str(r[pm_idx]).upper().strip() if pm_idx >= 0 else ""
        
        if parent == "" and not is_box(pm):
            ext_hu = safe_hu(r[vekp_ext_idx])
            int_hu = safe_hu(r[vekp_hu_idx])
            if int_hu in valid_vepo_hus:
                if ext_hu: valid_roots[(deliv, ext_hu)] = int_hu
                if int_hu: valid_roots[(deliv, int_hu)] = int_hu
                
    c_su = 'Storage Unit Type' if 'Storage Unit Type' in df_pick.columns else ('Type' if 'Type' in df_pick.columns else None)
    
    # Předzpracujeme indexy pro druhou smyčku
    col_su_idx = df_pick.columns.get_loc(c_su) if c_su else -1
    col_rem_idx = df_pick.columns.get_loc('Removal of total SU') if 'Removal of total SU' in df_pick.columns else -1
    col_q_idx = df_pick.columns.get_loc('Queue') if 'Queue' in df_pick.columns else -1
    col_ssu_idx = df_pick.columns.get_loc('Source storage unit') if 'Source storage unit' in df_pick.columns else -1
    col_hu_idx = df_pick.columns.get_loc('Handling Unit') if 'Handling Unit' in df_pick.columns else -1
    col_del_idx = df_pick.columns.get_loc('Delivery') if 'Delivery' in df_pick.columns else -1
    
    for r in df_pick.itertuples(index=False):
        rem = str(r[col_rem_idx]).strip().upper() if col_rem_idx >= 0 else ''
        if rem != 'X': continue 
        
        su_type = str(r[col_su_idx]) if col_su_idx >= 0 else ''
        if is_box(su_type): continue 
        
        queue_val = str(r[col_q_idx]).upper() if col_q_idx >= 0 else ''
        if 'PI_PA' in queue_val: continue 
        
        ssu = safe_hu(r[col_ssu_idx]) if col_ssu_idx >= 0 else ''
        hu = safe_hu(r[col_hu_idx]) if col_hu_idx >= 0 else ''
        
        pick_hu = ""
        if ssu and hu:
            if ssu != hu: continue 
            pick_hu = ssu
        elif ssu: pick_hu = ssu
        elif hu: pick_hu = hu
        else: continue
        
        deliv = safe_del(r[col_del_idx]) if col_del_idx >= 0 else ''
        
        if (deliv, pick_hu) in valid_roots:
            int_match = valid_roots[(deliv, pick_hu)]
            voll_set.add((deliv, pick_hu))
            voll_set.add((deliv, int_match)) # Přidáme obě varianty pro jistotu
            
    return voll_set
