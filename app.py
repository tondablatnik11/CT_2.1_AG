import streamlit as st
import pandas as pd
import numpy as np
import io
import time
import re
from streamlit_option_menu import option_menu

from database import save_to_db, load_from_db
from modules.utils import t, fast_compute_moves, get_match_key_vectorized, get_match_key, parse_packing_time, BOX_UNITS, detect_vollpalettes, safe_hu, safe_del

# <-- Zde už nejsou žádné importy z modules/tab_ kromě těch nezbytných pro start. Plně Lazy-Loaded aplikace!

# ==========================================
# 1. NASTAVENÍ STRÁNKY A UNIVERZÁLNÍ SAAS DESIGN
# ==========================================
st.set_page_config(page_title="Warehouse Control Tower", page_icon="🚀", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    /* Načtení prémiového fontu Plus Jakarta Sans */
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Plus Jakarta Sans', -apple-system, sans-serif !important;
    }
    
    /* 2026 Glassmorphism & Modern Dark/Neon Aesthetics */
    .stApp {
        background-color: #0d0f14;
        background-image: 
            radial-gradient(ellipse at top left, rgba(59, 130, 246, 0.15), transparent 50%),
            radial-gradient(ellipse at bottom right, rgba(16, 185, 129, 0.1), transparent 50%);
        color: #e2e8f0;
    }

    /* Tabular-nums pro perfektní zarovnání cifer pod sebou */
    [data-testid="stMetricValue"], .tabular-nums {
        font-variant-numeric: tabular-nums;
        letter-spacing: -0.02em;
    }
    
    /* Vylepšení metrik - Glassmorphism "Karty" */
    [data-testid="stMetric"] {
        background: rgba(30, 41, 59, 0.45);
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 16px;
        padding: 24px;
        box-shadow: 0 4px 24px -1px rgba(0, 0, 0, 0.2);
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    }
    [data-testid="stMetric"]:hover {
        transform: translateY(-4px) scale(1.02);
        border-color: rgba(59, 130, 246, 0.5);
        box-shadow: 0 12px 32px -4px rgba(59, 130, 246, 0.3);
        background: rgba(30, 41, 59, 0.65);
    }
    [data-testid="stMetricLabel"] {
        font-weight: 600;
        opacity: 0.7;
        font-size: 13px;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        color: #94a3b8;
    }
    [data-testid="stMetricValue"] {
        font-weight: 800;
        font-size: 32px !important;
        background: linear-gradient(135deg, #ffffff 0%, #cbd5e1 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }

    /* Hero Metric - Speciální kontejner pro hlavní KPI */
    .hero-metric {
        background: linear-gradient(135deg, rgba(59, 130, 246, 0.15) 0%, rgba(37, 99, 235, 0.0) 100%);
        border: 1px solid rgba(59, 130, 246, 0.3);
        border-left: 5px solid #3b82f6;
        backdrop-filter: blur(12px);
        border-radius: 12px;
        padding: 24px;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
    }
    .hero-metric h2 { margin: 0; font-size: 14px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.1em; }
    .hero-metric h1 { margin: 8px 0 0 0; font-size: 46px; font-weight: 800; color: #60a5fa; font-variant-numeric: tabular-nums; text-shadow: 0 0 20px rgba(59, 130, 246, 0.3);}
    
    /* Zkrášlení záložek (Tabs) - Neon lines */
    [data-baseweb="tab-list"] { gap: 8px; background-color: transparent; }
    [data-baseweb="tab"] {
        background: rgba(30, 41, 59, 0.3);
        backdrop-filter: blur(8px);
        border-radius: 8px 8px 0px 0px;
        padding: 12px 24px; 
        font-weight: 600;
        border: 1px solid rgba(255, 255, 255, 0.05); 
        border-bottom: none;
        transition: all 0.2s ease;
    }
    [aria-selected="true"] {
        background: rgba(59, 130, 246, 0.1) !important;
        border-top: 3px solid #3b82f6 !important;
        color: #60a5fa !important;
        text-shadow: 0 0 12px rgba(59, 130, 246, 0.4);
    }
    
    .section-header {
        background: linear-gradient(90deg, rgba(30,41,59,0.7) 0%, rgba(15,23,42,0) 100%);
        border-left: 4px solid #3b82f6;
        padding: 16px 24px; 
        border-radius: 8px;
        margin-bottom: 24px; 
        box-shadow: 0 4px 20px rgba(0,0,0,0.1);
    }
    .section-header h3 { margin-top: 0; padding-top: 0; color: #f8fafc; font-weight: 700; text-shadow: 0 2px 4px rgba(0,0,0,0.5); }
    .section-header p { margin-bottom: 0; opacity: 0.8; font-size: 14px; color: #cbd5e1; }
    
    #MainMenu {visibility: hidden;}
    header {background: transparent !important;}
    [data-testid="stHeaderActionElements"] {display: none;}
    </style>
""", unsafe_allow_html=True)

if 'lang' not in st.session_state: st.session_state.lang = 'cs'

def _t(cs, en): 
    return en if st.session_state.get('lang', 'cs') == 'en' else cs

# ==========================================
# 2. LOGIKA NAČÍTÁNÍ A PŘÍPRAVY DAT
# ==========================================
@st.cache_data(show_spinner=False)
def fetch_and_prep_data(use_marm=True):
    df_pick_raw = load_from_db('raw_pick')
    if df_pick_raw is None or df_pick_raw.empty: return None

    df_marm_raw = load_from_db('raw_marm') if use_marm else None
    df_queue_raw = load_from_db('raw_queue')
    df_manual_raw = load_from_db('raw_manual')

    df_pick = df_pick_raw.copy()
    df_pick['Delivery'] = df_pick['Delivery'].astype(str).str.strip().replace(to_replace=['nan', 'NaN', 'None', 'none', ''], value=np.nan)
    df_pick['Material'] = df_pick['Material'].astype(str).str.strip().replace(to_replace=['nan', 'NaN', 'None', 'none', ''], value=np.nan)
    df_pick = df_pick.dropna(subset=['Delivery', 'Material']).copy()
    
    num_removed_admins = 0
    if 'User' in df_pick.columns:
        mask_admins = df_pick['User'].isin(['UIDJ5089', 'UIH25501'])
        num_removed_admins = int(mask_admins.sum())
        df_pick = df_pick[~mask_admins].copy()

    df_pick['Match_Key'] = get_match_key_vectorized(df_pick['Material'])
    df_pick['Qty'] = pd.to_numeric(df_pick['Act.qty (dest)'], errors='coerce').fillna(0)
    df_pick['Source Storage Bin'] = df_pick.get('Source Storage Bin', df_pick.get('Storage Bin', '')).fillna('').astype(str)
    df_pick['Removal of total SU'] = df_pick.get('Removal of total SU', '').fillna('').astype(str).str.strip().str.upper()
    df_pick['Date'] = pd.to_datetime(df_pick.get('Confirmation date', df_pick.get('Confirmation Date')), errors='coerce')
    
    queue_count_col = 'Delivery'
    df_pick['Queue'] = 'N/A'
    if df_queue_raw is not None and not df_queue_raw.empty:
        if 'Transfer Order Number' in df_pick.columns and 'Transfer Order Number' in df_queue_raw.columns:
            q_map = df_queue_raw.dropna(subset=['Transfer Order Number', 'Queue']).drop_duplicates('Transfer Order Number').set_index('Transfer Order Number')['Queue'].to_dict()
            df_pick['Queue'] = df_pick['Transfer Order Number'].map(q_map).fillna('N/A')
            queue_count_col = 'Transfer Order Number'
            for d_col in ['Confirmation Date', 'Creation Date']:
                if d_col in df_queue_raw.columns:
                    d_map = df_queue_raw.dropna(subset=['Transfer Order Number', d_col]).drop_duplicates('Transfer Order Number').set_index('Transfer Order Number')[d_col].to_dict()
                    to_dates = df_pick['Transfer Order Number'].map(d_map)
                    df_pick['Date'] = df_pick['Date'].fillna(pd.to_datetime(to_dates, errors='coerce'))
                    break
        elif 'SD Document' in df_queue_raw.columns:
            q_map = df_queue_raw.dropna(subset=['SD Document', 'Queue']).drop_duplicates('SD Document').set_index('SD Document')['Queue'].to_dict()
            df_pick['Queue'] = df_pick['Delivery'].map(q_map).fillna('N/A')
        df_pick = df_pick[df_pick['Queue'].astype(str).str.upper() != 'CLEARANCE'].copy()

    manual_boxes = {}
    if df_manual_raw is not None and not df_manual_raw.empty:
        c_mat, c_pkg = df_manual_raw.columns[0], df_manual_raw.columns[1]
        for _, row in df_manual_raw.iterrows():
            raw_mat = str(row[c_mat])
            if raw_mat.upper() in ['NAN', 'NONE', '']: continue
            mat_key = get_match_key(raw_mat)
            pkg = str(row[c_pkg])
            nums = re.findall(r'\bK-(\d+)ks?\b|(\d+)\s*ks\b|balen[íi]\s+po\s+(\d+)|krabice\s+(?:po\s+)?(\d+)|(?:role|pytl[íi]k|pytel)[^\d]*(\d+)', pkg, flags=re.IGNORECASE)
            ext = tuple(sorted(list(set([int(g) for m in nums for g in m if g])), reverse=True))
            if not ext and re.search(r'po\s*kusech', pkg, re.IGNORECASE): ext = (1,)
            if ext: manual_boxes[mat_key] = ext

    box_dict, weight_dict, dim_dict = {}, {} , {}
    if df_marm_raw is not None and not df_marm_raw.empty:
        df_marm_raw['Match_Key'] = get_match_key_vectorized(df_marm_raw['Material'])
        df_boxes = df_marm_raw[df_marm_raw['Alternative Unit of Measure'].isin(BOX_UNITS)].copy()
        df_boxes['Numerator'] = pd.to_numeric(df_boxes['Numerator'], errors='coerce').fillna(0)
        box_dict = df_boxes.groupby('Match_Key')['Numerator'].apply(lambda g: tuple(sorted([int(x) for x in g if x > 1], reverse=True))).to_dict()

        df_st = df_marm_raw[df_marm_raw['Alternative Unit of Measure'].isin(['ST', 'PCE', 'KS', 'EA', 'PC'])].copy()
        df_st['Gross Weight'] = pd.to_numeric(df_st['Gross Weight'], errors='coerce').fillna(0)
        df_st['Weight_KG'] = np.where(df_st['Unit of Weight'].astype(str).str.upper() == 'G', df_st['Gross Weight'] / 1000.0, df_st['Gross Weight'])
        weight_dict = df_st.groupby('Match_Key')['Weight_KG'].first().to_dict()

        def to_cm(val, unit):
            try:
                v = float(val); u = str(unit).upper().strip()
                return v / 10.0 if u == 'MM' else v * 100.0 if u == 'M' else v
            except: return 0.0

        for dim_col, short in [('Length', 'L'), ('Width', 'W'), ('Height', 'H')]:
            if dim_col in df_st.columns: df_st[short] = df_st.apply(lambda r, dc=dim_col: to_cm(r[dc], r.get('Unit of Dimension', 'CM')), axis=1)
            else: df_st[short] = 0.0
        dim_dict = df_st.set_index('Match_Key')[['L', 'W', 'H']].max(axis=1).to_dict()

    df_pick['Box_Sizes_List'] = df_pick['Match_Key'].apply(lambda m: manual_boxes.get(m, box_dict.get(m, ())))
    df_pick['Piece_Weight_KG'] = df_pick['Match_Key'].map(weight_dict).fillna(0.0)
    df_pick['Piece_Max_Dim_CM'] = df_pick['Match_Key'].map(dim_dict).fillna(0.0)

    # -------------------------------------------------------------
    # CENTRÁLNÍ MOZEK PRO DETEKCI VOLLPALET
    # -------------------------------------------------------------
    df_vekp_raw = load_from_db('raw_vekp')
    df_vepo_raw = load_from_db('raw_vepo')
    
    voll_set = detect_vollpalettes(df_pick, df_vekp_raw, df_vepo_raw)

    df_oe = load_from_db('raw_oe')
    if df_oe is not None and not df_oe.empty:
        cols_up = [str(c).upper() for c in df_oe.columns]
        rename_map = {}
        has_dn = False
        has_time = False
        
        for orig, up in zip(df_oe.columns, cols_up):
            if not has_dn and ('DN NUMBER' in up or 'DELIVERY' in up or 'DODAVKA' in up): 
                rename_map[orig] = 'DN NUMBER (SAP)'
                has_dn = True
            elif not has_time and ('PROCESS' in up or 'CAS' in up or 'ČAS' in up or 'TIME' in up): 
                rename_map[orig] = 'Process Time'
                has_time = True
                
        df_oe.rename(columns=rename_map, inplace=True)
        df_oe = df_oe.loc[:, ~df_oe.columns.duplicated()].copy()
        
        if 'DN NUMBER (SAP)' in df_oe.columns and 'Process Time' in df_oe.columns:
            df_oe['Delivery'] = df_oe['DN NUMBER (SAP)'].astype(str).str.strip()
            df_oe['Process_Time_Min'] = df_oe['Process Time'].apply(parse_packing_time)
            
            agg_dict = {'Process_Time_Min': 'sum'}
            for col in ['CUSTOMER', 'Material', 'Scanning serial numbers', 'Reprinting labels ', 'Difficult KLTs', 'Shift', 'Number of item types']:
                if col in df_oe.columns: agg_dict[col] = 'first'
                
            for col in ['KLT', 'Palety', 'Cartons']:
                if col in df_oe.columns: 
                    agg_dict[col] = lambda x, c=col: '; '.join(x.dropna().astype(str))
                
            df_oe = df_oe.groupby('Delivery').agg(agg_dict).reset_index()
        else:
            df_oe = None

    df_cats = load_from_db('raw_cats')
    if df_cats is not None and not df_cats.empty:
        c_del_cats = next((c for c in df_cats.columns if str(c).strip().lower() in ['lieferung', 'delivery', 'zakázka']), df_cats.columns[0])
        df_cats['Lieferung'] = df_cats[c_del_cats].astype(str).str.strip()
        if 'Kategorie' in df_cats.columns and 'Art' in df_cats.columns: 
            df_cats['Category_Full'] = df_cats['Kategorie'].astype(str).str.strip() + " " + df_cats['Art'].astype(str).str.strip()
        df_cats = df_cats.drop_duplicates('Lieferung')

    aus_data = {}
    for sheet in ["LIKP", "SDSHP_AM2", "T031", "VEKP", "VEPO", "LIPS", "T023"]:
        aus_df = load_from_db(f'aus_{sheet.lower()}')
        if aus_df is not None: aus_data[sheet] = aus_df

    return {
        'df_pick': df_pick, 'queue_count_col': queue_count_col, 'voll_set': voll_set,
        'df_vekp': df_vekp_raw, 'df_vepo': df_vepo_raw,
        'df_cats': df_cats, 'df_oe': df_oe, 'aus_data': aus_data,
        'num_removed_admins': num_removed_admins, 'manual_boxes': manual_boxes,
        'weight_dict': weight_dict, 'dim_dict': dim_dict, 'box_dict': box_dict
    }


# ==========================================
# 3. HLAVNÍ FUNKCE APLIKACE (FRONTEND)
# ==========================================
def main():
    col_title, col_lang = st.columns([8, 1])
    with col_title:
        st.markdown(f"<div class='main-header'>{t('title')}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='sub-header'>{t('desc')}</div>", unsafe_allow_html=True)
    with col_lang:
        if st.button(t('switch_lang'), use_container_width=True):
            st.session_state.lang = 'en' if st.session_state.lang == 'cs' else 'cs'
            st.rerun()

    with st.sidebar:
        selected_page = option_menu(
            menu_title=None,
            options=[
                _t("Přehled a Fronty", "Dashboard & Queue"), 
                _t("Denní KPI (Ráno)", "Daily KPI"),
                _t("Měsíční KPI (Cíle)", "Monthly KPI"), 
                _t("Paletové zakázky", "Pallet Orders"), 
                _t("Celé palety (FU)", "Full Pallets (FU)"),
                _t("Porovnání (FU vs SAP)", "Compare (FU vs SAP)"),
                _t("Materiály (TOP)", "Top Materials"), 
                _t("Fakturace", "Billing"), 
                _t("Balení (Packing)", "Packing"), 
                _t("Sklad (Storage)", "Storage"),        # <-- PŘIDÁNO: Nová záložka
                _t("Admins", "Admins"),                  # <-- PŘIDÁNO: Nová záložka
                _t("Audit & Rentgen", "Audit & X-Ray"),
                _t("Nástěnka (Tisk grafů)", "Notice Board (Print)")
            ],
            icons=["bar-chart-line", "sun", "calendar-check", "box-seam", "boxes", "arrow-left-right", "list-ol", "currency-dollar", "box", "building", "tools", "clipboard2-check", "printer"],
            menu_icon="cast", 
            default_index=0,
            styles={
                "container": {"padding": "0!important", "background-color": "transparent"},
                "icon": {"color": "#3b82f6", "font-size": "16px"}, 
                "nav-link": {"font-size": "14px", "text-align": "left", "margin":"0px", "--hover-color": "rgba(128,128,128,0.1)"},
                "nav-link-selected": {"background-color": "#3b82f6", "color": "white", "font-weight": "600"},
            }
        )

        st.divider()
        st.header(_t("⚙️ Konfigurace algoritmů", "⚙️ Algorithm Config"))
        
        use_marm = st.toggle(_t("📦 Zahrnout data z MARM", "📦 Include MARM data"), value=True, help=_t("Vypnutím zjistíte, kolik dat je aplikace schopna spočítat přesně pouze pomocí vašeho ručního ověření, a kolik musí odhadovat.", "By turning this off, you'll see how much data the app can calculate accurately using only your manual verification."))
        limit_vahy = st.number_input(_t("Hranice váhy (kg)", "Weight limit (kg)"), min_value=0.1, max_value=20.0, value=2.0, step=0.5)
        limit_rozmeru = st.number_input(_t("Hranice rozměru (cm)", "Dimension limit (cm)"), min_value=1.0, max_value=200.0, value=15.0, step=1.0)
        kusy_na_hmat = st.slider(_t("Ks do hrsti", "Pcs per grab"), min_value=1, max_value=20, value=1, step=1)

        st.divider()
        st.header(_t("🚫 Vyloučení dat", "🚫 Data Exclusion"))
        exclude_mats_input = st.text_area(_t("Vyloučit materiály (oddělené čárkou/mezerou):", "Exclude materials (comma/space separated):"), help=_t("Vložené materiály budou kompletně smazány z výpočtů.", "Entered materials will be completely removed from calculations."))

        with st.expander(_t("🛠️ Admin Zóna (Nahrát data do DB)", "🛠️ Admin Zone (Upload to DB)")):
            st.info(_t("Nahrajte Excely sem. Zpracují se do databáze a aplikace poběží bleskově.", "Upload Excel files here. They will be processed into the database."))
            admin_pwd = st.text_input(_t("Heslo:", "Password:"), type="password")
            if admin_pwd == "admin123":
                append_data = st.checkbox(_t("Připojovat nová data k existujícím (nevymazávat staré)", "Append new data to existing (don't delete old)"), value=True, help=_t("Pokud je zapnuto, stará data v databázi zůstanou a nová se k nim přidají (duplicity se odfiltrují). Vypněte, pokud chcete vyčistit databázi a nahrát zcela nová data od nuly.", "If checked, old data remains and new is added. Uncheck to upload a completely new database from scratch."))
                uploaded_files = st.file_uploader(_t("Nahrát CSV/Excel", "Upload CSV/Excel"), accept_multiple_files=True)
                if st.button(_t("Uložit do databáze", "Save to Database"), type="primary") and uploaded_files:
                    with st.spinner(_t("Zpracovávám a ukládám do Supabase...", "Processing and saving...")):
                        for file in uploaded_files:
                            try:
                                fname = file.name.lower()
                                if fname.endswith('.xlsx') and 'auswertung' in fname:
                                    aus_xl = pd.ExcelFile(file)
                                    for sn in aus_xl.sheet_names: 
                                        save_to_db(aus_xl.parse(sn, dtype=str), f"aus_{sn.lower()}", append_data)
                                    st.success(f"✅ {_t('Uloženo', 'Saved')} (Auswertung): {file.name}")
                                    continue

                                temp_df = pd.read_csv(file, dtype=str, sep=None, engine='python') if fname.endswith('.csv') else pd.read_excel(file, dtype=str)
                                temp_df.columns = temp_df.columns.str.strip()
                                cols = temp_df.columns.tolist()
                                cols_up = [str(c).upper().strip() for c in cols]
                                
                                # 💡 UNIVERZÁLNÍ A PŘESNÁ DETEKCE SLOUPCŮ (Otisk prstu každého reportu)
                                is_pick = any('ACT.QTY' in c or 'ISTMENGE' in c or 'MNOŽSTVÍ (CÍL)' in c for c in cols_up) and any('TRANSFER ORDER' in c or 'TRANSPORTAUFTRAG' in c for c in cols_up)
                                is_queue = any('QUEUE' in c for c in cols_up) and not is_pick
                                is_vepo = any('PACKED QUANTITY' in c or 'VEMNG' in c or 'BALENÉ MNOŽSTVÍ' in c for c in cols_up)
                                is_vekp = any('GENERATED DELIVERY' in c or 'GENERIERTE LIEFERUNG' in c or 'VYTVOŘENÁ DODÁVKA' in c for c in cols_up) or (any('TOTAL WEIGHT' in c or 'BRGEW' in c for c in cols_up) and any('HANDLING UNIT' in c or 'MANIPULAČNÍ' in c for c in cols_up) and not is_vepo)
                                is_cats = any('KATEGORIE' in c or 'CATEGORY' in c for c in cols_up) and any('DELIVERY' in c or 'LIEFERUNG' in c or 'ZAKÁZKA' in c for c in cols_up)
                                is_likp = any('SHIPPING POINT' in c or 'VERSANDSTELLE' in c or 'RECEIVING PT' in c or 'MÍSTO' in c for c in cols_up) and not is_vekp
                                is_marm = any('NUMERATOR' in c or 'ČITATEL' in c for c in cols_up) and any('ALTERNATIVE UNIT' in c or 'ALTERNATIVNÍ' in c for c in cols_up)
                                is_oe = 'oe-times' in fname or any('PROCESS' in c or 'PROCES' in c for c in cols_up) and any('TIME' in c or 'ČAS' in c or 'CAS' in c for c in cols_up)
                                
                                # PŘIDÁNO: LX03 a LT10
                                is_lt10 = any('AVAILABLE STOCK' in c or 'ZÁSOBA K DISP.' in c for c in cols_up) and any('LAST MOVEMENT' in c or 'POSLEDNÍ POHYB' in c for c in cols_up)
                                is_lx03 = any('STORAGE BIN TYPE' in c or 'TYP SKLAD.MÍSTA' in c or 'TYP SKLAD MISTA' in c for c in cols_up) and not is_lt10
                                
                                # ROZŘAZENÍ:
                                if is_pick:
                                    save_to_db(temp_df, 'raw_pick', append_data)
                                    st.success(f"✅ {_t('Uloženo jako Pick Report', 'Saved as Pick Report')}: {file.name}")
                                elif is_queue:
                                    save_to_db(temp_df, 'raw_queue', append_data)
                                    st.success(f"✅ {_t('Uloženo jako Queue (LTAK)', 'Saved as Queue')}: {file.name}")
                                elif is_vepo:
                                    save_to_db(temp_df, 'raw_vepo', append_data)
                                    st.success(f"✅ {_t('Uloženo jako VEPO', 'Saved as VEPO')}: {file.name}")
                                elif is_vekp:
                                    save_to_db(temp_df, 'raw_vekp', append_data)
                                    st.success(f"✅ {_t('Uloženo jako VEKP', 'Saved as VEKP')}: {file.name}")
                                elif is_cats:
                                    save_to_db(temp_df, 'raw_cats', append_data)
                                    st.success(f"✅ {_t('Uloženo jako Kategorie', 'Saved as Categories')}: {file.name}")
                                elif is_marm: 
                                    save_to_db(temp_df, 'raw_marm', append_data)
                                    st.success(f"✅ {_t('Uloženo jako MARM', 'Saved as MARM')}: {file.name}")
                                elif is_likp:
                                    save_to_db(temp_df, 'raw_likp', append_data)
                                    st.success(f"✅ {_t('Uloženo jako LIKP', 'Saved as LIKP')}: {file.name}")
                                elif is_lt10: # <-- PŘIDÁNO
                                    save_to_db(temp_df, 'raw_lt10', append_data)
                                    st.success(f"✅ {_t('Uloženo jako LT10 (Zásoby)', 'Saved as LT10')}: {file.name}")
                                elif is_lx03: # <-- PŘIDÁNO
                                    save_to_db(temp_df, 'raw_lx03', append_data)
                                    st.success(f"✅ {_t('Uloženo jako LX03 (Kapacita)', 'Saved as LX03')}: {file.name}")
                                elif is_oe:
                                    rename_map = {}
                                    has_dn = False
                                    has_time = False
                                    for orig, up in zip(cols, cols_up):
                                        if not has_dn and ('DN NUMBER' in up or 'DELIVERY' in up or 'DODAVKA' in up):
                                            rename_map[orig] = 'DN NUMBER (SAP)'
                                            has_dn = True
                                        elif not has_time and ('PROCESS' in up or 'CAS' in up or 'ČAS' in up or 'TIME' in up):
                                            rename_map[orig] = 'Process Time'
                                            has_time = True
                                    temp_df.rename(columns=rename_map, inplace=True)
                                    temp_df = temp_df.loc[:, ~temp_df.columns.duplicated()]
                                    save_to_db(temp_df, 'raw_oe', append_data)
                                    st.success(f"✅ {_t('Uloženo jako OE-Times', 'Saved as OE-Times')}: {file.name}")
                                    
                                elif len(cols) >= 2 and any('MATERIAL' in c or 'MATERIÁL' in c for c in cols_up):
                                    save_to_db(temp_df, 'raw_manual', append_data)
                                    st.success(f"✅ {_t('Uloženo jako Ruční Master Data', 'Saved as Manual Master Data')}: {file.name}")
                                    
                                else:
                                    st.error(f"🚨 {_t('Soubor', 'File')} '{file.name}' {_t('nebyl rozpoznán a NEULOŽIL SE do databáze!', 'was not recognized and NOT SAVED!')}")
                                    st.info(f"🔍 Aplikace v souboru vidí tyto sloupce: {', '.join(cols)}")
                                    
                            except Exception as e:
                                st.error(f"❌ {_t('Chyba u souboru', 'Error processing file')} {file.name}: {e}")
                                
                        st.cache_data.clear()
                        time.sleep(2.0)
                        st.rerun()

    progress_bar = st.progress(0, text=_t("🚀 Inicializace Warehouse Control Tower...", "🚀 Initializing Warehouse Control Tower..."))
    time.sleep(0.1)
    
    progress_bar.progress(30, text=_t("📥 Načítání a propojování dat z databáze...", "📥 Fetching and joining database records..."))
    data_dict = fetch_and_prep_data(use_marm)

    if data_dict is None:
        progress_bar.empty()
        st.warning(_t("🗄️ Databáze je zatím prázdná. Otevřete levé menu 'Admin Zóna', zadejte heslo 'admin123' a nahrajte Pick Report a další soubory.", "🗄️ Database is empty. Open Admin Zone in the left menu."))
        return

    progress_bar.progress(65, text=_t("⚙️ Výpočet fyzických pohybů a kontrola ergonomie...", "⚙️ Calculating physical movements and ergonomics..."))
    df_pick = data_dict['df_pick']
    
    if exclude_mats_input:
        excluded_materials = [m.strip().upper() for m in re.split(r'[,\s;]+', exclude_mats_input) if m.strip()]
        if excluded_materials:
            df_pick = df_pick[~df_pick['Material'].astype(str).str.upper().isin(excluded_materials)].copy()
            if df_pick.empty:
                progress_bar.empty()
                st.warning(_t("⚠️ Po vyloučení těchto materiálů nezbyla v Pick reportu žádná data.", "⚠️ No data left after excluding these materials."))
                st.stop()

    st.session_state['voll_set'] = data_dict['voll_set']

    # ==========================================
    # NOVÁ LOGIKA PRO FILTROVÁNÍ MĚSÍCŮ
    # ==========================================
    df_pick['Month'] = df_pick['Date'].dt.to_period('M').astype(str).replace('NaT', _t('Neznámé', 'Unknown'))
    st.sidebar.divider()
    
    date_options = [
        _t('Celé období', 'All Time'), 
        _t('Podle měsíce', 'By Month'),
        _t('Porovnání měsíců', 'Compare Months')
    ]
    date_mode = st.sidebar.radio(_t("Filtr období:", "Date Filter:"), date_options, label_visibility="collapsed")
    
    available_months = sorted(df_pick['Month'].unique())
    
    if date_mode == _t('Podle měsíce', 'By Month'):
        sel_month = st.sidebar.selectbox(_t("Vyberte měsíc:", "Select Month:"), options=available_months)
        df_pick = df_pick[df_pick['Month'] == sel_month].copy()
        
    elif date_mode == _t('Porovnání měsíců', 'Compare Months'):
        default_months = available_months[-2:] if len(available_months) >= 2 else available_months
        sel_months = st.sidebar.multiselect(_t("Vyberte měsíce k porovnání:", "Select Months to compare:"), options=available_months, default=default_months)
        
        if sel_months:
            df_pick = df_pick[df_pick['Month'].isin(sel_months)].copy()
        else:
            st.sidebar.info(_t("Vyberte alespoň jeden měsíc.", "Select at least one month."))
            df_pick = df_pick.iloc[0:0].copy()

    # ==========================================

    tt, te, tm = fast_compute_moves(df_pick['Qty'].values, df_pick['Queue'].values, df_pick['Removal of total SU'].values, df_pick['Box_Sizes_List'].values, df_pick['Piece_Weight_KG'].values, df_pick['Piece_Max_Dim_CM'].values, limit_vahy, limit_rozmeru, kusy_na_hmat)
    df_pick['Pohyby_Rukou'], df_pick['Pohyby_Exact'], df_pick['Pohyby_Loose_Miss'] = tt, te, tm
    df_pick['Celkova_Vaha_KG'] = df_pick['Qty'] * df_pick['Piece_Weight_KG']

    progress_bar.progress(90, text=_t("📊 Vykreslování vizualizací a tabulek...", "📊 Rendering charts and dashboards..."))
    time.sleep(0.2)
    progress_bar.empty()

    display_q = None
    if selected_page == _t("Přehled a Fronty", "Dashboard & Queue"): 
        from modules.tab_dashboard import render_dashboard
        display_q = render_dashboard(df_pick, data_dict['queue_count_col'])
    elif selected_page == _t("Denní KPI (Ráno)", "Daily KPI"):            
        from modules.tab_daily_kpi import render_daily_kpi
        render_daily_kpi(df_pick, data_dict['df_vekp'])
    elif selected_page == _t("Měsíční KPI (Cíle)", "Monthly KPI"):        
        from modules.tab_monthly_kpi import render_monthly_kpi
        render_monthly_kpi(df_pick, data_dict['df_vekp'], data_dict['df_vepo'])
    elif selected_page == _t("Paletové zakázky", "Pallet Orders"): 
        from modules.tab_pallets import render_pallets
        render_pallets(df_pick)
    elif selected_page == _t("Celé palety (FU)", "Full Pallets (FU)"): 
        from modules.tab_fu import render_fu
        render_fu(df_pick, data_dict['queue_count_col'])
    elif selected_page == _t("Porovnání (FU vs SAP)", "Compare (FU vs SAP)"):
        from modules.tab_fu_compare import render_fu_compare
        render_fu_compare(df_pick, st.session_state.get('billing_df'), st.session_state.get('voll_set'), data_dict['queue_count_col'])
    elif selected_page == _t("Materiály (TOP)", "Top Materials"): 
        from modules.tab_top import render_top
        render_top(df_pick)
    elif selected_page == _t("Fakturace", "Billing"): 
        from modules.tab_billing import render_billing
        billing_df = render_billing(df_pick, data_dict['df_vekp'], data_dict['df_vepo'], data_dict['df_cats'], data_dict['queue_count_col'])
        st.session_state['billing_df'] = billing_df
    elif selected_page == _t("Balení (Packing)", "Packing"): 
        from modules.tab_packing import render_packing
        render_packing(st.session_state.get('billing_df', pd.DataFrame()), data_dict['df_oe'])
    elif selected_page == _t("Sklad (Storage)", "Storage"):
        with st.spinner(_t("Načítám data skladu...", "Loading storage data...")):
            df_lx03 = load_from_db('raw_lx03')
            df_lt10 = load_from_db('raw_lt10')
            df_marm = load_from_db('raw_marm')
            from modules.tab_storage import render_storage
            render_storage(df_lx03, df_lt10, df_marm, df_pick)
            
    elif selected_page == _t("Admins", "Admins"):
        with st.spinner(_t("Načítám admin data...", "Loading admin data...")):
            df_likp = load_from_db('raw_likp')
            from modules.tab_admins import render_admins
            render_admins(data_dict['df_vekp'], df_likp)
            
    elif selected_page == _t("Audit & Rentgen", "Audit & X-Ray"): 
        from modules.tab_audit import render_audit
        render_audit(df_pick, data_dict['df_vekp'], data_dict['df_vepo'], data_dict['df_oe'], data_dict['queue_count_col'], st.session_state.get('billing_df', pd.DataFrame()), data_dict['manual_boxes'], data_dict['weight_dict'], data_dict['dim_dict'], data_dict['box_dict'], limit_vahy, limit_rozmeru, kusy_na_hmat)
    elif selected_page == _t("Nástěnka (Tisk grafů)", "Notice Board (Print)"):
        from modules.tab_board import render_board
        render_board(df_pick, st.session_state.get('billing_df', pd.DataFrame()))

    st.divider()
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        pd.DataFrame({"Parameter": ["Weight Limit", "Dim Limit", "Grab limit", "Admins Excluded"], "Value": [f"{limit_vahy} kg", f"{limit_rozmeru} cm", f"{kusy_na_hmat} pcs", data_dict['num_removed_admins']]}).to_excel(writer, index=False, sheet_name='Settings')
        
        if display_q is not None and not display_q.empty: 
            display_q.to_excel(writer, index=False, sheet_name='Queue_Analysis')
            
        df_pal_exp = df_pick[df_pick['Queue'].astype(str).str.upper().isin(['PI_PL', 'PI_PL_OE'])].groupby('Delivery').agg(num_materials=('Material', 'nunique'), material=('Material', 'first'), total_qty=('Qty', 'sum'), celkem_pohybu=('Pohyby_Rukou', 'sum'), pohyby_exact=('Pohyby_Exact', 'sum'), pohyby_miss=('Pohyby_Loose_Miss', 'sum'), vaha_zakazky=('Celkova_Vaha_KG', 'sum'), max_rozmer=('Piece_Max_Dim_CM', 'first'))
        df_pal_single = df_pal_exp[df_pal_exp['num_materials'] == 1].copy()
        
        if not df_pal_single.empty: 
            df_pal_single[['material', 'total_qty', 'celkem_pohybu', 'pohyby_exact', 'pohyby_miss', 'vaha_zakazky', 'max_rozmer']].rename(columns={'material': t('col_mat'), 'total_qty': t('col_qty'), 'celkem_pohybu': t('col_mov'), 'pohyby_exact': t('col_mov_exact'), 'pohyby_miss': t('col_mov_miss'), 'vaha_zakazky': t('col_wgt'), 'max_rozmer': t('col_max_dim')}).to_excel(writer, index=True, sheet_name='Single_Mat_Orders')
            
        df_pick.groupby('Material').agg(Moves=('Pohyby_Rukou', 'sum'), Qty=('Qty', 'sum'), Exact=('Pohyby_Exact', 'sum'), Estimates=('Pohyby_Loose_Miss', 'sum'), Lines=('Material', 'count')).reset_index().sort_values('Moves', ascending=False).to_excel(writer, index=False, sheet_name='Material_Totals')

    st.download_button(
        label=_t("⬇️ Stáhnout kompletní Excel report", "⬇️ Download Complete Excel Report"), 
        data=buffer.getvalue(), 
        file_name=f"Warehouse_Control_Tower_{time.strftime('%Y%m%d_%H%M')}.xlsx", 
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
        type="primary"
    )

if __name__ == "__main__":
    main()
