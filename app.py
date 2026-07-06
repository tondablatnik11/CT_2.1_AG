"""
Warehouse Control Tower - Hlavní aplikace (Streamlit + Supabase)

Hlavní entry point pro end-to-end skladovou analytiku.
- Načítá data ze Supabase Storage (Parquet)
- Počítá fyzické pohyby, fakturaci, efektivitu
- Vykresluje dashboardy přes 13 specializovaných záložek

Architektura:
    app.py (tento soubor)
        ├── database.py       - Supabase storage operace
        └── modules/
            ├── utils.py          - výpočetní jádro, helpers
            ├── safe_render.py    - error handling
            └── tab_*.py          - jednotlivé záložky
"""
import io
import logging
import os
import re
import time
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd
import streamlit as st
from streamlit_option_menu import option_menu

from database import clear_cache, get_supabase_client, load_from_db, save_to_db
from modules.diagnostics import (
    get_system_health,
    log_performance,
    record_successful_load,
    safe_execute,
)
from modules.safe_render import ErrorBoundary
from modules.utils import (
    BOX_UNITS,
    detect_vollpalettes,
    fast_compute_moves,
    get_match_key,
    get_match_key_vectorized,
    safe_del,
    t,
)

# ==========================================
# LOGGING CONFIGURATION
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("warehouse.app")


def _get_admin_password() -> str:
    """Admin heslo ze st.secrets nebo env var ADMIN_PASSWORD.
    Fallback na 'admin123' jen pokud není nakonfigurováno nic (zpětná kompatibilita)."""
    try:
        if hasattr(st, "secrets") and "ADMIN_PASSWORD" in st.secrets:
            return str(st.secrets["ADMIN_PASSWORD"])
    except Exception:
        pass
    return os.environ.get("ADMIN_PASSWORD", "admin123")

# ==========================================
# PAGE CONFIGURATION & GLOBAL STYLES
# ==========================================
st.set_page_config(
    page_title="Warehouse Control Tower",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Prémiový CSS - Modern Dark Glassmorphism (2026 Edition)
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"] {
    font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif !important;
    font-feature-settings: 'cv11', 'ss01';
}

/* === HLAVNÍ POZADÍ S GRADIENTEM === */
.stApp {
    background-color: #0d0f14;
    background-image:
        radial-gradient(ellipse at top left, rgba(59, 130, 246, 0.15), transparent 50%),
        radial-gradient(ellipse at bottom right, rgba(16, 185, 129, 0.10), transparent 50%),
        radial-gradient(ellipse at center, rgba(139, 92, 246, 0.05), transparent 70%);
    color: #e2e8f0;
}

/* === TABULAR NUMS PRO METRIKY === */
[data-testid="stMetricValue"], .tabular-nums {
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.02em;
}

/* === GLASSMORPHISM KARTY PRO METRIKY === */
[data-testid="stMetric"] {
    background: rgba(30, 41, 59, 0.45);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 16px;
    padding: 20px 24px;
    box-shadow: 0 4px 24px -1px rgba(0, 0, 0, 0.2);
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
[data-testid="stMetric"]:hover {
    transform: translateY(-3px) scale(1.01);
    border-color: rgba(59, 130, 246, 0.5);
    box-shadow: 0 12px 32px -4px rgba(59, 130, 246, 0.3);
    background: rgba(30, 41, 59, 0.65);
}
[data-testid="stMetricLabel"] {
    font-weight: 600;
    opacity: 0.7;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #94a3b8;
}
[data-testid="stMetricValue"] {
    font-weight: 800;
    font-size: 28px !important;
    background: linear-gradient(135deg, #ffffff 0%, #cbd5e1 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}

/* === HERO METRICKÝ KONTEJNER === */
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

/* === TABS - NEON LINES === */
[data-baseweb="tab-list"] { gap: 8px; background-color: transparent; padding: 4px; }
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
[data-baseweb="tab"]:hover {
    background: rgba(30, 41, 59, 0.5);
    border-color: rgba(59, 130, 246, 0.3);
}
[aria-selected="true"] {
    background: rgba(59, 130, 246, 0.1) !important;
    border-top: 3px solid #3b82f6 !important;
    color: #60a5fa !important;
    text-shadow: 0 0 12px rgba(59, 130, 246, 0.4);
}

/* === SECTION HEADERS === */
.section-header {
    background: linear-gradient(90deg, rgba(30,41,59,0.7) 0%, rgba(15,23,42,0) 100%);
    border-left: 4px solid #3b82f6;
    padding: 16px 24px;
    border-radius: 8px;
    margin-bottom: 24px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.1);
}
.section-header h3 {
    margin-top: 0;
    padding-top: 0;
    color: #f8fafc;
    font-weight: 700;
    text-shadow: 0 2px 4px rgba(0,0,0,0.5);
    font-size: 22px;
}
.section-header p {
    margin-bottom: 0;
    opacity: 0.85;
    font-size: 14px;
    color: #cbd5e1;
    line-height: 1.5;
}

/* === HLAVNÍ HLAVIČKA === */
.main-header {
    font-size: 42px;
    font-weight: 800;
    background: linear-gradient(135deg, #3b82f6 0%, #8b5cf6 50%, #10b981 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin-bottom: 4px;
    letter-spacing: -0.02em;
}
.sub-header {
    font-size: 15px;
    color: #94a3b8;
    margin-bottom: 24px;
    opacity: 0.9;
}

/* === CONTAINERS === */
[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 12px;
    border-color: rgba(255, 255, 255, 0.08) !important;
}

/* === SKRÝT DEFAULT UI === */
#MainMenu {visibility: hidden;}
header {background: transparent !important;}
[data-testid="stHeaderActionElements"] {display: none;}
footer {visibility: hidden;}

/* === LOADING SPINNER === */
.stSpinner > div { border-top-color: #3b82f6 !important; }

/* === DATAFRAME STYLING === */
[data-testid="stDataFrame"] {
    border-radius: 8px;
    overflow: hidden;
}

/* === TOASTY === */
.stToast {
    background: rgba(30, 41, 59, 0.95) !important;
    backdrop-filter: blur(12px);
    border: 1px solid rgba(59, 130, 246, 0.3) !important;
}

/* === LOADING STATES - SKELETON (vylepšené) === */
@keyframes skeleton-pulse {
    0%, 100% { opacity: 0.4; }
    50% { opacity: 0.8; }
}
@keyframes skeleton-shimmer {
    0% { background-position: -200% 0; }
    100% { background-position: 200% 0; }
}
.skeleton {
    background: linear-gradient(90deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.15) 50%, rgba(255,255,255,0.05) 100%);
    background-size: 200% 100%;
    animation: skeleton-shimmer 1.8s ease-in-out infinite;
    border-radius: 8px;
    height: 24px;
    margin-bottom: 8px;
}
.skeleton-line {
    background: linear-gradient(90deg, rgba(59,130,246,0.08) 0%, rgba(59,130,246,0.20) 50%, rgba(59,130,246,0.08) 100%);
    background-size: 200% 100%;
    animation: skeleton-shimmer 1.8s ease-in-out infinite;
    border-radius: 6px;
    height: 14px;
    margin-bottom: 8px;
}
.skeleton-card {
    background: linear-gradient(135deg, rgba(30,41,59,0.45) 0%, rgba(30,41,59,0.65) 100%);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 12px;
}
.skeleton-card .skeleton-line { width: 80%; }
.skeleton-card .skeleton-line:nth-child(2) { width: 50%; }
.skeleton-card .skeleton-line:nth-child(3) { width: 65%; }

/* === TABULKY - HOVER EFEKTY === */
[data-testid="stDataFrame"] tbody tr {
    transition: background-color 0.15s ease, transform 0.1s ease;
}
[data-testid="stDataFrame"] tbody tr:hover {
    background-color: rgba(59, 130, 246, 0.08) !important;
    cursor: default;
}
[data-testid="stDataFrame"] thead th {
    background: rgba(30, 41, 59, 0.6) !important;
    backdrop-filter: blur(8px);
    font-weight: 700 !important;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    font-size: 11px !important;
    color: #94a3b8 !important;
    border-bottom: 2px solid rgba(59, 130, 246, 0.3) !important;
}

/* === PRINT STYLES - NOTICE BOARD (vysoký kontrast) === */
@media print {
    html, body, [class*="css"] {
        background: #ffffff !important;
        color: #000000 !important;
        font-family: 'Helvetica Neue', Arial, sans-serif !important;
    }
    .stApp {
        background: #ffffff !important;
        background-image: none !important;
    }
    [data-testid="stSidebar"], [data-testid="stHeader"],
    .stButton, .stDownloadButton, .stProgress,
    header, footer, [data-testid="stToolbar"] {
        display: none !important;
    }
    .main-header, .sub-header, .hero-metric h1, .hero-metric h2,
    [data-testid="stMetricValue"], [data-testid="stMetricLabel"],
    .section-header h3, .section-header p, h1, h2, h3, h4, p, span, div {
        color: #000000 !important;
        -webkit-text-fill-color: #000000 !important;
        background: none !important;
        text-shadow: none !important;
    }
    [data-testid="stMetric"] {
        background: #f5f5f5 !important;
        border: 1px solid #333333 !important;
        backdrop-filter: none !important;
        page-break-inside: avoid;
        box-shadow: none !important;
    }
    .section-header {
        background: #f0f0f0 !important;
        border-left: 4px solid #000000 !important;
        box-shadow: none !important;
    }
    [data-testid="stDataFrame"] {
        border: 1px solid #000000 !important;
        page-break-inside: avoid;
    }
    [data-testid="stDataFrame"] tbody tr:hover {
        background-color: transparent !important;
    }
    .badge {
        border: 1px solid #000000 !important;
        color: #000000 !important;
        background: #ffffff !important;
    }
    [data-baseweb="tab-list"], [data-baseweb="tab"] {
        display: none !important;
    }
}

/* === PŘÍSTUPNOST - REDUCED MOTION === */
@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
        scroll-behavior: auto !important;
    }
    [data-testid="stMetric"]:hover,
    [data-baseweb="tab"]:hover {
        transform: none !important;
    }
    .skeleton, .skeleton-line {
        animation: none !important;
        opacity: 0.6;
    }
}

/* === PIPELINE STATUS INDICATOR === */
.pipeline-status {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 6px 14px;
    border-radius: 20px;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    transition: all 0.2s ease;
}
.pipeline-status-loading {
    background: rgba(245, 158, 11, 0.15);
    border: 1px solid rgba(245, 158, 11, 0.4);
    color: #fbbf24;
}
.pipeline-status-ok {
    background: rgba(16, 185, 129, 0.15);
    border: 1px solid rgba(16, 185, 129, 0.4);
    color: #34d399;
}
.pipeline-status-error {
    background: rgba(239, 68, 68, 0.15);
    border: 1px solid rgba(239, 68, 68, 0.4);
    color: #f87171;
}
.pipeline-status .status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    display: inline-block;
}
.pipeline-status-loading .status-dot {
    background: #fbbf24;
    animation: pulse-dot 1.4s ease-in-out infinite;
}
.pipeline-status-ok .status-dot { background: #34d399; }
.pipeline-status-error .status-dot { background: #f87171; }
@keyframes pulse-dot {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.5; transform: scale(1.3); }
}

/* === APP BRANDING V SIDEBARU === */
.app-brand {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 16px;
    margin-bottom: 8px;
    background: linear-gradient(135deg, rgba(59,130,246,0.18) 0%, rgba(139,92,246,0.12) 100%);
    border: 1px solid rgba(59,130,246,0.3);
    border-radius: 12px;
    backdrop-filter: blur(10px);
}
.app-brand-logo {
    font-size: 28px;
    line-height: 1;
    filter: drop-shadow(0 0 8px rgba(59,130,246,0.5));
}
.app-brand-text { display: flex; flex-direction: column; }
.app-brand-title {
    font-size: 14px;
    font-weight: 800;
    color: #f8fafc;
    line-height: 1.2;
    letter-spacing: -0.01em;
}
.app-brand-subtitle {
    font-size: 10px;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-top: 2px;
}

/* === QUICK STATS V SIDEBARU === */
.sidebar-stat {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 12px;
    margin-bottom: 4px;
    background: rgba(30, 41, 59, 0.35);
    border: 1px solid rgba(255, 255, 255, 0.05);
    border-radius: 8px;
    font-size: 12px;
}
.sidebar-stat-label { color: #94a3b8; }
.sidebar-stat-value {
    color: #60a5fa;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
}

/* === SCROLLBAR === */
::-webkit-scrollbar {
    width: 10px;
    height: 10px;
}
::-webkit-scrollbar-track {
    background: rgba(15, 23, 42, 0.3);
    border-radius: 5px;
}
::-webkit-scrollbar-thumb {
    background: rgba(59, 130, 246, 0.5);
    border-radius: 5px;
    transition: all 0.2s;
}
::-webkit-scrollbar-thumb:hover {
    background: rgba(59, 130, 246, 0.8);
}

/* === BUDGET BADGES === */
.badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
}
.badge-success { background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }
.badge-warning { background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }
.badge-error { background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }
.badge-info { background: rgba(59, 130, 246, 0.2); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.3); }

/* === PŘEPÍNAČ JAZYKA === */
.lang-button {
    background: rgba(30, 41, 59, 0.5) !important;
    backdrop-filter: blur(8px);
    border: 1px solid rgba(255, 255, 255, 0.1) !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    transition: all 0.2s !important;
}
.lang-button:hover {
    background: rgba(59, 130, 246, 0.2) !important;
    border-color: rgba(59, 130, 246, 0.5) !important;
}

/* === EXPANDER POLISH === */
.streamlit-expanderHeader {
    background: rgba(30, 41, 59, 0.4) !important;
    backdrop-filter: blur(8px);
    border-radius: 8px !important;
    border: 1px solid rgba(255, 255, 255, 0.06) !important;
    font-weight: 600 !important;
}
.streamlit-expanderHeader:hover {
    border-color: rgba(59, 130, 246, 0.3) !important;
}

/* === ALERTS === */
.stAlert {
    border-radius: 12px !important;
    border-left: 4px solid !important;
    backdrop-filter: blur(8px);
}
[data-baseweb="notification"] {
    border-radius: 12px;
}
</style>
""", unsafe_allow_html=True)


# ==========================================
# SESSION STATE INITIALIZATION
# ==========================================
if 'lang' not in st.session_state:
    st.session_state.lang = 'cs'
if 'app_initialized' not in st.session_state:
    st.session_state.app_initialized = True
    st.session_state.app_started_at = time.time()
    logger.info("Aplikace inicializována")

# === DIAGNOSTIKA - inicializace session_state klíčů ===
# error_counter: dict s "total" + "recent" (rolling window timestampů)
if 'error_counter' not in st.session_state:
    st.session_state.error_counter = {
        "total": 0,
        "recent": [],
        "recent_window_s": 60.0,
        "warn_threshold": 5,
    }
# last_successful_load: ISO timestamp posledního úspěšného loadu (None = dosud nic)
if 'last_successful_load' not in st.session_state:
    st.session_state.last_successful_load = None
# last_warning_ts: kdy se naposledy zobrazilo varování (throttling, ne spamovat)
if 'diag_last_warning_ts' not in st.session_state:
    st.session_state.diag_last_warning_ts = 0.0


def _t(cs: str, en: str) -> str:
    """Lokální helper pro překlad v app.py."""
    return en if st.session_state.get('lang', 'cs') == 'en' else cs


# ==========================================
# HLAVNÍ DATA PIPELINE - OPTIMALIZOVANÝ
# ==========================================

# =====================================================================
# Rozklad fetch_and_prep_data na menší cache funkce (Fix A: OOM).
# Každá funkce drží v paměti jen svůj vlastní dataset → špička RAM klesne
# z ~400 MB (8 datasetů najednou v jednom blobu) na ~150 MB (df_pick +
# jedna skupina master dat). Zároveň to zrychlí cold start, protože
# loady běží paralelněji a neblokují se navzájem.
# =====================================================================

@st.cache_data(show_spinner=False, ttl=300)
def _load_pick_processed(use_marm: bool) -> Optional[pd.DataFrame]:
    """Nejtežší část: načte raw_pick, provede čištění/kategorie a vrátí df_pick
    s derived sloupci (Month, Clean_Del, Queue, Match_Key, Box_Sizes_List,
    Piece_Weight_KG, Piece_Max_Dim_CM)."""
    df_pick_raw = load_from_db('raw_pick')
    if df_pick_raw is None or df_pick_raw.empty:
        return None

    df_pick = df_pick_raw.copy()
    df_pick['Delivery'] = (
        df_pick['Delivery'].astype(str).str.strip()
        .replace(to_replace=['nan', 'NaN', 'None', 'none', ''], value=np.nan)
    )
    df_pick['Material'] = (
        df_pick['Material'].astype(str).str.strip()
        .replace(to_replace=['nan', 'NaN', 'None', 'none', ''], value=np.nan)
    )

    for col in ['Delivery', 'Material', 'User', 'Queue']:
        if col in df_pick.columns and df_pick[col].dtype == 'object':
            try:
                df_pick[col] = df_pick[col].astype('category')
            except (TypeError, ValueError):
                pass

    df_pick = df_pick.dropna(subset=['Delivery', 'Material']).copy()
    initial_rows = len(df_pick)  # pro log (po dropna, před admin filtrem)

    num_removed_admins = 0
    if 'User' in df_pick.columns:
        mask_admins = df_pick['User'].astype(str).isin(['UIDJ5089', 'UIH25501'])
        num_removed_admins = int(mask_admins.sum())
        if num_removed_admins > 0:
            df_pick = df_pick[~mask_admins].copy()

    df_pick['Match_Key'] = get_match_key_vectorized(df_pick['Material'].astype(str))
    df_pick['Qty'] = pd.to_numeric(df_pick['Act.qty (dest)'], errors='coerce').fillna(0).astype('float32')

    bin_col = 'Source Storage Bin' if 'Source Storage Bin' in df_pick.columns else 'Storage Bin'
    df_pick['Source Storage Bin'] = df_pick.get(bin_col, pd.Series(dtype=str)).fillna('').astype(str)

    df_pick['Removal of total SU'] = (
        df_pick.get('Removal of total SU', pd.Series(dtype=str))
        .fillna('').astype(str).str.strip().str.upper()
    )

    date_src = df_pick.get('Confirmation date', df_pick.get('Confirmation Date'))
    df_pick['Date'] = pd.to_datetime(date_src, errors='coerce')

    # Uložení statistiky pro build_data_dict (mimo Streamlit cache).
    _pick_stats['initial_rows'] = initial_rows
    _pick_stats['num_removed_admins'] = num_removed_admins
    return df_pick


# Interní dict pro mezivýpočty mezi @st.cache_data funkcemi (Streamlit cache
# nesmí vracet mutable sdílený stav, ale prostý dict v modulu je bezpečný).
_pick_stats: Dict[str, int] = {'initial_rows': 0, 'num_removed_admins': 0}


@st.cache_data(show_spinner=False, ttl=300)
def _load_queue_and_dates() -> Tuple[Optional[Dict[Any, str]], Optional[Dict[Any, Any]]]:
    """Queue lookup (TO → Queue) + fallback date lookup. None pokud tabulka chybí."""
    df_queue_raw = load_from_db('raw_queue')
    if df_queue_raw is None or df_queue_raw.empty:
        return None, None
    q_map = (
        df_queue_raw.dropna(subset=['Transfer Order Number', 'Queue'])
        .drop_duplicates('Transfer Order Number')
        .set_index('Transfer Order Number')['Queue'].to_dict()
    ) if 'Transfer Order Number' in df_queue_raw.columns else None
    d_map = None
    for d_col in ['Confirmation Date', 'Creation Date']:
        if d_col in df_queue_raw.columns:
            d_map = (
                df_queue_raw.dropna(subset=['Transfer Order Number', d_col])
                .drop_duplicates('Transfer Order Number')
                .set_index('Transfer Order Number')[d_col].to_dict()
            )
            break
    return q_map, d_map


@st.cache_data(show_spinner=False, ttl=300)
def _load_manual_boxes() -> Dict[str, Tuple[int, ...]]:
    """Manuální master data (krabice pro materiály) → dict[match_key] = tuple(box sizes)."""
    df_manual_raw = load_from_db('raw_manual')
    manual_boxes: Dict[str, Tuple[int, ...]] = {}
    if df_manual_raw is None or df_manual_raw.empty:
        return manual_boxes
    try:
        c_mat, c_pkg = df_manual_raw.columns[0], df_manual_raw.columns[1]
        pkgs = df_manual_raw[c_pkg].astype(str).fillna('')
        mat_keys = df_manual_raw[c_mat].astype(str).apply(get_match_key)
        for mat_key, pkg in zip(mat_keys, pkgs):
            if not mat_key or mat_key in ('NAN', 'NONE', '0'):
                continue
            nums = re.findall(
                r'\bK-(\d+)ks?\b|(\d+)\s*ks\b|balen[íi]\s+po\s+(\d+)|krabice\s+(?:po\s+)?(\d+)|(?:role|pytl[íi]k|pytel)[^\d]*(\d+)',
                pkg, flags=re.IGNORECASE
            )
            ext = tuple(sorted(set(int(g) for m in nums for g in m if g), reverse=True))
            if not ext and re.search(r'po\s*kusech', pkg, re.IGNORECASE):
                ext = (1,)
            if ext:
                manual_boxes[mat_key] = ext
    except Exception as e:
        logger.warning(f"Chyba při parsování manual boxes: {e}")
    return manual_boxes


@st.cache_data(show_spinner=False, ttl=300)
def _load_marm_master() -> Tuple[Dict[str, Tuple[int, ...]], Dict[str, float], Dict[str, float]]:
    """MARM master data: box_dict (dict→tuple), weight_dict (per material KG), dim_dict (max dim CM)."""
    df_marm_raw = load_from_db('raw_marm')
    box_dict: Dict[str, Tuple[int, ...]] = {}
    weight_dict: Dict[str, float] = {}
    dim_dict: Dict[str, float] = {}
    if df_marm_raw is None or df_marm_raw.empty:
        return box_dict, weight_dict, dim_dict
    try:
        df_marm_raw = df_marm_raw.copy()
        df_marm_raw['Match_Key'] = get_match_key_vectorized(df_marm_raw['Material'].astype(str))

        df_boxes = df_marm_raw[df_marm_raw['Alternative Unit of Measure'].isin(BOX_UNITS)].copy()
        if not df_boxes.empty:
            df_boxes['Numerator'] = pd.to_numeric(df_boxes['Numerator'], errors='coerce').fillna(0)
            box_dict = (
                df_boxes[df_boxes['Numerator'] > 1]
                .groupby('Match_Key')['Numerator']
                .apply(lambda g: tuple(sorted(g.astype(int).tolist(), reverse=True)))
                .to_dict()
            )

        df_st = df_marm_raw[df_marm_raw['Alternative Unit of Measure'].isin(['ST', 'PCE', 'KS', 'EA', 'PC'])].copy()
        if not df_st.empty:
            df_st['Gross Weight'] = pd.to_numeric(df_st['Gross Weight'], errors='coerce').fillna(0)
            is_gram = df_st['Unit of Weight'].astype(str).str.upper() == 'G'
            df_st['Weight_KG'] = np.where(is_gram, df_st['Gross Weight'] / 1000.0, df_st['Gross Weight']).astype('float32')
            weight_dict = df_st.groupby('Match_Key')['Weight_KG'].first().to_dict()

            def _to_cm_vec(arr, units):
                v = pd.to_numeric(arr, errors='coerce').fillna(0).astype('float32')
                u = units.astype(str).str.upper().str.strip()
                return np.where(u == 'MM', v / 10.0, np.where(u == 'M', v * 100.0, v))

            for dim_col, short in [('Length', 'L'), ('Width', 'W'), ('Height', 'H')]:
                if dim_col in df_st.columns:
                    unit_col = df_st.get('Unit of Dimension', pd.Series(['CM'] * len(df_st)))
                    df_st[short] = _to_cm_vec(df_st[dim_col], unit_col)
                else:
                    df_st[short] = 0.0
            dim_dict = df_st.set_index('Match_Key')[['L', 'W', 'H']].max(axis=1).to_dict()
    except Exception as e:
        logger.warning(f"Chyba při zpracování MARM: {e}")
    return box_dict, weight_dict, dim_dict


@st.cache_data(show_spinner=False, ttl=300)
def _load_oe_processed() -> Optional[pd.DataFrame]:
    """OE-Times zpracovaný (Delivery jako klíč, Process_Time_Min, sloupčné agregace)."""
    df_oe = load_from_db('raw_oe')
    if df_oe is None or df_oe.empty:
        return None
    try:
        cols_up = [str(c).upper() for c in df_oe.columns]
        rename_map = {}
        has_dn = has_time = False
        for orig, up in zip(df_oe.columns, cols_up):
            if not has_dn and ('DN NUMBER' in up or 'DELIVERY' in up or 'DODAVKA' in up):
                rename_map[orig] = 'DN NUMBER (SAP)'
                has_dn = True
            elif not has_time and ('PROCESS' in up or 'CAS' in up or 'ČAS' in up or 'TIME' in up):
                rename_map[orig] = 'Process Time'
                has_time = True
        df_oe = df_oe.rename(columns=rename_map)
        df_oe = df_oe.loc[:, ~df_oe.columns.duplicated()].copy()
        if 'DN NUMBER (SAP)' not in df_oe.columns or 'Process Time' not in df_oe.columns:
            return None
        df_oe['Delivery'] = df_oe['DN NUMBER (SAP)'].astype(str).str.strip()
        df_oe['Process_Time_Min'] = _vectorize_packing_times(df_oe['Process Time'])
        agg_dict = {'Process_Time_Min': 'sum'}
        for col in ['CUSTOMER', 'Material', 'Scanning serial numbers', 'Reprinting labels ',
                    'Difficult KLTs', 'Shift', 'Number of item types']:
            if col in df_oe.columns:
                agg_dict[col] = 'first'
        for col in ['KLT', 'Palety', 'Cartons']:
            if col in df_oe.columns:
                agg_dict[col] = lambda x, c=col: '; '.join(x.dropna().astype(str))
        return df_oe.groupby('Delivery').agg(agg_dict).reset_index()
    except Exception as e:
        logger.warning(f"Chyba při zpracování OE-Times: {e}")
        return None


@st.cache_data(show_spinner=False, ttl=300)
def _load_cats_processed() -> Optional[pd.DataFrame]:
    """df_cats s normalizovaným Lieferung a Category_Full."""
    df_cats = load_from_db('raw_cats')
    if df_cats is None or df_cats.empty:
        return None
    try:
        c_del_cats = next(
            (c for c in df_cats.columns
             if str(c).strip().lower() in ['lieferung', 'delivery', 'zakázka', 'dodávka']),
            df_cats.columns[0]
        )
        df_cats['Lieferung'] = df_cats[c_del_cats].astype(str).str.strip()
        if 'Kategorie' in df_cats.columns and 'Art' in df_cats.columns:
            df_cats['Category_Full'] = (
                df_cats['Kategorie'].astype(str).str.strip() + " " +
                df_cats['Art'].astype(str).str.strip()
            )
        return df_cats.drop_duplicates('Lieferung')
    except Exception as e:
        logger.warning(f"Chyba při zpracování df_cats: {e}")
        return None


@st.cache_data(show_spinner=False, ttl=300)
def _load_aus_data() -> Dict[str, pd.DataFrame]:
    """Vedlejší SAP tabulky (aus_likp, aus_sdshp_am2, …). Většinou vrací prázdný dict
    (storage vrací 400 — opraveno Fixem B v database.py)."""
    aus_data: Dict[str, pd.DataFrame] = {}
    for sheet in ["LIKP", "SDSHP_AM2", "T031", "VEKP", "VEPO", "LIPS", "T023"]:
        aus_df = load_from_db(f'aus_{sheet.lower()}')
        if aus_df is not None:
            aus_data[sheet] = aus_df
    return aus_data


@st.cache_data(show_spinner=False, ttl=300)
def _load_pick_enriched(use_marm: bool) -> Optional[pd.DataFrame]:
    """df_pick s Queue, datem, Vollpaletten a box mappingem — vše pohromadě,
    ale drží se v paměti jen tohle (master data se vyhodí po dokončení)."""
    df_pick = _load_pick_processed(use_marm)
    if df_pick is None or df_pick.empty:
        return None
    initial_rows = len(df_pick)

    q_map, d_map = _load_queue_and_dates()
    queue_count_col = 'Delivery'
    df_pick['Queue'] = 'N/A'
    if q_map is not None and 'Transfer Order Number' in df_pick.columns:
        df_pick['Queue'] = df_pick['Transfer Order Number'].map(q_map).fillna('N/A')
        queue_count_col = 'Transfer Order Number'
        if d_map is not None:
            to_dates = df_pick['Transfer Order Number'].map(d_map)
            df_pick['Date'] = df_pick['Date'].fillna(pd.to_datetime(to_dates, errors='coerce'))

    # Filtr CLEARANCE front
    if 'Queue' in df_pick.columns:
        df_pick = df_pick[df_pick['Queue'].astype(str).str.upper() != 'CLEARANCE'].copy()

    # Mapování na master data
    manual_boxes = _load_manual_boxes() if use_marm else {}
    if use_marm:
        box_dict, weight_dict, dim_dict = _load_marm_master()
    else:
        box_dict, weight_dict, dim_dict = {}, {}, {}
    combined_boxes = {**box_dict, **manual_boxes}
    mapped_boxes = df_pick['Match_Key'].map(combined_boxes)
    df_pick['Box_Sizes_List'] = [b if isinstance(b, tuple) else () for b in mapped_boxes]
    df_pick['Piece_Weight_KG'] = df_pick['Match_Key'].map(weight_dict).fillna(0.0)
    df_pick['Piece_Max_Dim_CM'] = df_pick['Match_Key'].map(dim_dict).fillna(0.0)

    # Vollpaletten (držíme jen set, ne celý df)
    df_vekp_raw = load_from_db('raw_vekp')
    df_vepo_raw = load_from_db('raw_vepo')
    with ErrorBoundary("Detekce Vollpalet", level="warning"):
        voll_set = detect_vollpalettes(df_pick, df_vekp_raw, df_vepo_raw)

    # Finální optimalizace dtype
    for col in ['Queue', 'Storage Unit Type', 'Type', 'Removal of total SU']:
        if col in df_pick.columns and df_pick[col].dtype == 'object':
            try:
                df_pick[col] = df_pick[col].astype('category')
            except (TypeError, ValueError):
                pass

    # Month
    if 'Date' in df_pick.columns and 'Month' not in df_pick.columns:
        try:
            df_pick['Month'] = df_pick['Date'].dt.to_period('M').astype(str).replace('NaT', 'Neznámé')
        except Exception as e:
            logger.warning(f"Nelze vytvořit Month sloupec: {e}")
            df_pick['Month'] = 'Neznámé'

    # Clean_Del
    if 'Clean_Del' not in df_pick.columns and 'Delivery' in df_pick.columns:
        try:
            df_pick['Clean_Del'] = df_pick['Delivery'].apply(safe_del)
        except Exception as e:
            logger.warning(f"Nelze vytvořit Clean_Del: {e}")

    return df_pick


def build_data_dict(use_marm: bool = True) -> Optional[Dict[str, Any]]:
    """
    Tenký orchestrátor, který slepí výsledky dílčích cache funkcí do tvaru,
    jaký čeká zbytek aplikace (klíče: df_pick, queue_count_col, voll_set,
    df_vekp, df_vepo, df_cats, df_oe, aus_data, manual_boxes, weight_dict,
    dim_dict, box_dict, num_removed_admins).

    DŮLEŽITÉ: Tato funkce sama o sobě není cacheovaná — pouze skládá.
    Streamlit cachuje výsledky dílčích loaderů nezávisle, takže v RAM
    najednou leží jen ~df_pick + jedna skupina master dat.
    """
    df_pick = _load_pick_enriched(use_marm)
    if df_pick is None or df_pick.empty:
        logger.warning("df_pick je prázdný - databáze neinicializovaná")
        return None

    # Zjistí queue_count_col z derived df_pick (Queue sloupec + Transfer Order Number)
    queue_count_col = 'Delivery'
    if 'Transfer Order Number' in df_pick.columns:
        queue_count_col = 'Transfer Order Number'

    # Vollpaletten set + raw vekp/vepo (musí se držet pro Billing/Admins/Audit)
    df_vekp_raw = load_from_db('raw_vekp')
    df_vepo_raw = load_from_db('raw_vepo')
    with ErrorBoundary("Detekce Vollpalet", level="warning"):
        voll_set = detect_vollpalettes(df_pick, df_vekp_raw, df_vepo_raw)

    df_oe = _load_oe_processed()
    df_cats = _load_cats_processed()
    aus_data = _load_aus_data()

    # Master data musíme vrátit i v dictu pro Audit/Billing — znovu z cache.
    manual_boxes = _load_manual_boxes()
    if use_marm:
        box_dict, weight_dict, dim_dict = _load_marm_master()
    else:
        box_dict, weight_dict, dim_dict = {}, {}, {}

    initial_rows = _pick_stats.get('initial_rows', len(df_pick))
    num_removed_admins = _pick_stats.get('num_removed_admins', 0)
    logger.info(
        f"build_data_dict hotovo: {len(df_pick):,} řádků (z {initial_rows:,} původních), "
        f"{num_removed_admins} adminů odebráno"
    )

    return {
        'df_pick': df_pick,
        'queue_count_col': queue_count_col,
        'voll_set': voll_set,
        'df_vekp': df_vekp_raw,
        'df_vepo': df_vepo_raw,
        'df_cats': df_cats,
        'df_oe': df_oe,
        'aus_data': aus_data,
        'num_removed_admins': num_removed_admins,
        'manual_boxes': manual_boxes,
        'weight_dict': weight_dict,
        'dim_dict': dim_dict,
        'box_dict': box_dict,
    }


def fetch_and_prep_data(use_marm: bool = True) -> Optional[Dict[str, Any]]:
    """Back-compat obal — volá nový build_data_dict. Drží se v API kvůli
    případným externím importům; samotná implementace je v build_data_dict.
    Logika se nyní skládá z menších cache funkcí → špička RAM klesne."""
    return build_data_dict(use_marm)


def _vectorize_packing_times(series: pd.Series) -> pd.Series:
    """Vektorová verze parse_packing_time - 50x rychlejší než apply.

    Podporuje formáty:
    - Decimal minuty ("5.5", "123.4")
    - Decimal hodiny < 1 ("0.5" = 30 min, převede se na 720 min)
    - Celé minuty ("30", "120")
    - HH:MM:SS ("01:30:00" = 90 min)
    - HH:MM ("01:30" = 90 min)
    """
    s = series.astype(str).str.strip()

    # Prázdné hodnoty -> 0 minut
    result = np.zeros(len(s), dtype=np.float32)
    valid_mask = ~s.isin(['', 'nan', 'None', 'NaN'])
    if not valid_mask.any():
        return pd.Series(result, index=s.index)

    valid = s[valid_mask]

    # 1. Pokus o float konverzi (většina případů)
    try:
        nums = pd.to_numeric(valid, errors='coerce')
        float_mask = nums.notna()
        if float_mask.any():
            # Čísla < 1 = hodiny v desetinné soustavě, převést na minuty
            vals = nums[float_mask].values
            converted = np.where(vals < 1.0, vals * 24 * 60, vals).astype(np.float32)
            # DŮLEŽITÉ: valid_mask a float_mask mají různé indexy (float_mask je z 'valid', ne z 's').
            # Musíme namapovat výsledky zpět na pozice v 's'. Indexy v 'nums' odpovídají
            # indexům v 'valid', které odpovídají indexům v 's' kde valid_mask=True.
            valid_idx = np.where(valid_mask.values)[0]
            float_idx_in_valid = np.where(float_mask.values)[0]
            for out_pos, in_pos in zip(valid_idx[float_idx_in_valid], range(len(float_idx_in_valid))):
                result[out_pos] = converted[in_pos]
    except Exception:
        nums = pd.Series([], dtype='float64')
        float_mask = pd.Series([], dtype=bool)

    # 2. Zpracování formátu HH:MM:SS nebo HH:MM pro zbývající (non-numeric)
    if len(nums) > 0:
        already_numeric = nums.notna()
        remaining = valid[~already_numeric.values]
    else:
        remaining = valid

    if len(remaining) > 0:
        for idx, val in remaining.items():
            try:
                parts = str(val).split(':')
                if len(parts) == 3:
                    result[idx] = int(parts[0]) * 60 + int(parts[1]) + float(parts[2]) / 60.0
                elif len(parts) == 2:
                    # POZOR: HH:MM formát - parts[0] jsou HODINY, parts[1] jsou MINUTY
                    # ne zlomek hodiny! Proto int(parts[0]) + parts[1]/60 je ŠPATNĚ.
                    result[idx] = int(parts[0]) * 60 + int(parts[1])
            except (ValueError, IndexError):
                pass

    return pd.Series(result, index=series.index)


# ==========================================
# HLAVNÍ UI - APLIKACE
# ==========================================

def main():
    """Hlavní vstupní bod aplikace."""
    # Hlavička s přepínačem jazyka, stavem pipeline a rychlým refresh
    col_title, col_lang = st.columns([8, 1])
    with col_title:
        st.markdown(f"<div class='main-header'>{t('title')}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='sub-header'>{t('desc')}</div>", unsafe_allow_html=True)
    with col_lang:
        if st.button(t('switch_lang'), width="stretch", key="lang_switch"):
            st.session_state.lang = 'en' if st.session_state.lang == 'cs' else 'cs'
            logger.info(f"Jazyk přepnut na: {st.session_state.lang}")
            st.rerun()

    # Inicializace session state pro pipeline status + datum/čas
    if 'pipeline_status' not in st.session_state:
        st.session_state.pipeline_status = 'idle'  # idle | loading | ok | error
    if 'pipeline_start_ts' not in st.session_state:
        st.session_state.pipeline_start_ts = None

    # === HLAVIČKA: DATUM/ČAS + STATUS + REFRESH ===
    _render_app_header_bar()

    # Sidebar - menu + konfigurace
    selected_page = _render_sidebar()

    # === HLAVNÍ DATOVÝ PIPELINE ===
    pipeline_steps = [
        (10, "🚀 Spouštím Warehouse Control Tower...", "Inicializace", "~1s"),
        (20, "📥 Načítám konfiguraci algoritmů...", "Konfigurace", "<1s"),
        (40, "📦 Načítám data ze Supabase (raw_pick)...", "raw_pick", "~3-5s"),
        (55, "📦 Načítám data ze Supabase (MARM master)...", "raw_marm", "~2-4s"),
        (70, "📦 Načítám data ze Supabase (OE-Times, CATS)...", "raw_oe / raw_cats", "~2-3s"),
        (82, "⚙️ Počítám fyzické pohyby skladníků...", "Výpočet pohybů", "~1-2s"),
        (95, "📊 Vykresluji dashboard...", "Render UI", "~1s"),
        (100, "✅ Hotovo!", "Dokončeno", "0s"),
    ]
    progress_bar = st.progress(0, text=pipeline_steps[0][1])

    def _advance(idx: int, table_hint: str = ""):
        pct, text, step_name, eta = pipeline_steps[idx]
        suffix = f" — {table_hint}" if table_hint else ""
        progress_bar.progress(pct, text=f"{text}{suffix}")

    st.session_state.pipeline_status = 'loading'
    st.session_state.pipeline_start_ts = time.time()
    pipeline_error: Optional[Exception] = None
    pipeline_start_time = time.time()

    try:
        _advance(1)
        use_marm = st.session_state.get('use_marm', True)

        _advance(2, table_hint="raw_pick")
        data_dict = fetch_and_prep_data(use_marm)

        if data_dict is None:
            progress_bar.empty()
            st.session_state.pipeline_status = 'error'
            _render_empty_database_warning()
            return

        _advance(3, table_hint="raw_marm")

        # .copy() — data_dict['df_pick'] pochází z @st.cache_data (sdílený objekt).
        # _compute_movements_safe přidává sloupce in-place; bez kopie by mutace
        # prosákla do cache a mezi taby/sessiony (viz performance rules).
        df_pick = data_dict['df_pick'].copy()

        _advance(4, table_hint="raw_oe / raw_cats")

        # === FILTROVÁNÍ PODLE STRÁNKY ===
        if selected_page in (_t("Sklad (Storage)", "Storage"), _t("Admins", "Admins")):
            excluded_materials = st.session_state.get('excluded_materials', [])
        else:
            excluded_materials = _render_exclusion_filter(df_pick)
            df_pick = _apply_exclusion_filter(df_pick, excluded_materials)

        if df_pick.empty:
            progress_bar.empty()
            st.session_state.pipeline_status = 'error'
            st.warning(_t("⚠️ Po vyloučení těchto materiálů nezbyla žádná data.", "⚠️ No data left after excluding these materials."))
            st.stop()

        # Uložení klíčových struktur do session_state (pro sdílení mezi taby)
        st.session_state['voll_set'] = data_dict['voll_set']
        st.session_state['data_dict'] = data_dict

        # === VÝPOČET POHYBŮ (cacheovaný - závisí na filtrech) ===
        _advance(5, table_hint=f"df_pick · {len(df_pick):,} řádků")
        _compute_movements_safe(df_pick, data_dict)

        _advance(6)
        time.sleep(0.1)
        _advance(7)
        time.sleep(0.05)
        progress_bar.empty()
        st.session_state.pipeline_status = 'ok'

        # === DIAGNOSTIKA: záznam úspěšného loadu + výkonu pipeline ===
        pipeline_elapsed = time.time() - pipeline_start_time
        try:
            record_successful_load()
            log_performance("main_pipeline", pipeline_elapsed)
        except Exception as diag_e:
            logger.debug(f"Diagnostika po úspěšném loadu selhala: {diag_e}")

        # Aktualizace sidebar quick stats po úspěšném loadu
        st.session_state['sidebar_stats'] = {
            'rows': f"{len(df_pick):,}",
            'last_update': time.strftime('%H:%M:%S'),
        }

        # === ROZBALENÍ PODLE STRÁNKY ===
        _route_to_page(selected_page, df_pick, data_dict)

        # === EXPORT DO EXCELU ===
        st.divider()
        _render_excel_export(df_pick, data_dict)

        # === FOOTER ===
        _render_footer(df_pick, data_dict)

    except Exception as e:
        pipeline_error = e
        progress_bar.empty()
        st.session_state.pipeline_status = 'error'

        # === DIAGNOSTIKA: záznam chyby do error_counter (rolling window) ===
        try:
            err_counter = st.session_state.get('error_counter')
            if not isinstance(err_counter, dict):
                err_counter = {"total": 0, "recent": [], "recent_window_s": 60.0, "warn_threshold": 5}
                st.session_state.error_counter = err_counter
            now_ts = time.time()
            window_s = float(err_counter.get('recent_window_s', 60.0))
            cutoff = now_ts - window_s
            recent = [t for t in err_counter.get('recent', []) if isinstance(t, (int, float)) and t >= cutoff]
            recent.append(now_ts)
            err_counter['recent'] = recent
            err_counter['total'] = int(err_counter.get('total', 0)) + 1
        except Exception as diag_e:
            logger.debug(f"Záznam chyby do error_counter selhal: {diag_e}")

        logger.exception("Kritická chyba v main()")
        st.error(
            f"🚨 **Kritická chyba aplikace:** `{type(e).__name__}`\n\n"
            f"**Detail:** {str(e)[:300]}\n\n"
            "Obnovte stránku (F5) nebo kontaktujte správce."
        )
        with st.expander("🔧 Technické detaily"):
            import traceback
            st.code(traceback.format_exc(), language="python")

        # === DIAGNOSTIKA: varování při > 5 chybách za minutu (s throttlingem) ===
        try:
            err_counter = st.session_state.get('error_counter', {})
            warn_threshold = int(err_counter.get('warn_threshold', 5))
            recent_count = len(err_counter.get('recent', []))
            now_ts = time.time()
            last_warn_ts = float(st.session_state.get('diag_last_warning_ts', 0.0))
            # Throttling: ne častěji než 1× za 30s
            if recent_count > warn_threshold and (now_ts - last_warn_ts) > 30.0:
                st.session_state.diag_last_warning_ts = now_ts
                health = safe_execute(get_system_health, fallback={}, operation_name="get_system_health")
                mem_mb = health.get('memory_mb') if isinstance(health, dict) else None
                mem_text = f", paměť: {mem_mb:.1f} MB" if isinstance(mem_mb, (int, float)) else ""
                st.warning(
                    f"🚧 **Vysoká chybovost detekována**: "
                    f"{recent_count} chyb za posledních "
                    f"{err_counter.get('recent_window_s', 60.0):.0f}s"
                    f"{mem_text}.\n\n"
                    f"Aplikace může být nestabilní. Zvažte obnovení stránky (F5)."
                )
                logger.warning(
                    f"Vysoká chybovost: {recent_count} chyb za "
                    f"{err_counter.get('recent_window_s', 60.0):.0f}s "
                    f"(práh: {warn_threshold})"
                )
        except Exception as warn_e:
            logger.debug(f"Varování o vysoké chybovosti selhalo: {warn_e}")

    finally:
        # Překreslíme header bar s finálním stavem pipeline (pouze pokud ještě nebyl vykreslen).
        # DŮLEŽITÉ: V Streamlit se widgety s klíčem "quick_refresh" NESMÍ renderovat 2x,
        # protože to vyhodí StreamlitDuplicateElementKey. Pokud se _render_app_header_bar
        # již zavolal na začátku main(), tady pouze aktualizujeme session state - samotné
        # překreslení proběhne v dalším rerunu.
        if st.session_state.get('pipeline_status') != st.session_state.get('_header_last_status'):
            st.session_state['_header_last_status'] = st.session_state.pipeline_status
            # Nekreslíme znovu - aktualizace statusu se projeví v dalším Streamlit rerunu.


def _render_app_header_bar(status_override: Optional[str] = None):
    """Vylepšená hlavička: datum/čas, indikátor stavu pipeline, rychlý refresh."""
    status = status_override or st.session_state.get('pipeline_status', 'idle')
    elapsed = ""
    if st.session_state.get('pipeline_start_ts') and status in ('ok', 'error'):
        elapsed_s = time.time() - st.session_state.pipeline_start_ts
        elapsed = f" · {elapsed_s:.1f}s"

    status_map = {
        'idle':    ('pipeline-status', '⏸ Připraveno'),
        'loading': ('pipeline-status-loading', '⟳ Načítám data'),
        'ok':      ('pipeline-status-ok', f'✓ OK{elapsed}'),
        'error':   ('pipeline-status-error', '✗ Chyba'),
    }
    css_class, label = status_map.get(status, status_map['idle'])

    now = time.strftime('%A %d.%m.%Y · %H:%M:%S')
    # Přeložíme název dne do češtiny (základní mapování)
    day_cz = {
        'Monday': 'Pondělí', 'Tuesday': 'Úterý', 'Wednesday': 'Středa',
        'Thursday': 'Čtvrtek', 'Friday': 'Pátek', 'Saturday': 'Sobota', 'Sunday': 'Neděle',
    }
    if st.session_state.get('lang', 'cs') == 'cs':
        for en, cz in day_cz.items():
            now = now.replace(en, cz)

    col_dt, col_status, col_refresh = st.columns([3, 2, 1])
    with col_dt:
        st.markdown(
            f"<div style='font-size:13px; color:#94a3b8; padding-top:6px;'>"
            f"📅 <strong style='color:#cbd5e1;'>{now}</strong></div>",
            unsafe_allow_html=True,
        )
    with col_status:
        st.markdown(
            f"<div style='text-align:right; padding-top:4px;'>"
            f"<span class='pipeline-status {css_class}'>"
            f"<span class='status-dot'></span>{label}</span></div>",
            unsafe_allow_html=True,
        )
    with col_refresh:
        if st.button(
            _t("🔄 Obnovit", "🔄 Refresh"),
            width="stretch",
            key="quick_refresh",
            help=_t("Vyčistí cache a znovu načte data ze Supabase.", "Clear cache and reload data from Supabase."),
        ):
            clear_cache()
            st.session_state.pipeline_status = 'idle'
            logger.info("Rychlý refresh: cache vyčištěna")
            st.rerun()


def _render_sidebar() -> str:
    """Sidebar s navigací a konfigurací algoritmů."""
    with st.sidebar:
        # === APP BRANDING ===
        _render_app_brand()

        # === RYCHLÉ STATISTIKY ===
        _render_sidebar_quick_stats()

        st.divider()

        st.markdown("### 🎛️ Navigace")

        selected = option_menu(
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
                _t("Sklad (Storage)", "Storage"),
                _t("Admins", "Admins"),
                _t("Audit & Rentgen", "Audit & X-Ray"),
                _t("Nástěnka (Tisk grafů)", "Notice Board (Print)"),
            ],
            icons=["bar-chart-line", "sun", "calendar-check", "box-seam", "boxes",
                   "arrow-left-right", "list-ol", "currency-dollar", "box", "building",
                   "tools", "clipboard2-check", "printer"],
            menu_icon="cast",
            default_index=0,
            styles={
                "container": {"padding": "0!important", "background-color": "transparent"},
                "icon": {"color": "#3b82f6", "font-size": "16px"},
                "nav-link": {"font-size": "14px", "text-align": "left", "margin": "0px",
                             "--hover-color": "rgba(128,128,128,0.1)"},
                "nav-link-selected": {"background-color": "#3b82f6", "color": "white", "font-weight": "600"},
            }
        )

        st.divider()

        # === COLLAPSE: KONFIGURACE ALGORITMŮ ===
        with st.expander(_t("⚙️ Konfigurace algoritmů", "⚙️ Algorithm Configuration"), expanded=False):
            use_marm = st.toggle(
                _t("📦 Zahrnout data z MARM", "📦 Include MARM data"),
                value=True,
                help=_t("Vypnutím zjistíte, kolik dat je aplikace schopna spočítat přesně pouze pomocí vašeho ručního ověření.",
                        "By turning this off, you'll see how much data the app can calculate accurately using only your manual verification.")
            )
            st.session_state['use_marm'] = use_marm

            limit_vahy = st.number_input(
                _t("Hranice váhy (kg)", "Weight limit (kg)"),
                min_value=0.1, max_value=20.0, value=2.0, step=0.5,
                help=_t("Těžší kus než limit = 1 samostatný pohyb", "Heavier piece than limit = 1 separate move")
            )
            limit_rozmeru = st.number_input(
                _t("Hranice rozměru (cm)", "Dimension limit (cm)"),
                min_value=1.0, max_value=200.0, value=15.0, step=1.0,
                help=_t("Větší kus než limit = 1 samostatný pohyb", "Larger piece than limit = 1 separate move")
            )
            kusy_na_hmat = st.slider(
                _t("Ks do hrsti", "Pcs per grab"),
                min_value=1, max_value=20, value=1, step=1,
                help=_t("Maximální počet lehkých kusů, které skladník vezme najednou",
                        "Max number of light pieces picked at once")
            )

            st.session_state['algorithm_limits'] = {
                'vaha': limit_vahy, 'rozmer': limit_rozmeru, 'hrst': kusy_na_hmat
            }

        # === COLLAPSE: VYLOUČENÍ DAT ===
        with st.expander(_t("🚫 Vyloučení dat", "🚫 Data Exclusion"), expanded=False):
            exclude_mats_input = st.text_area(
                _t("Vyloučit materiály (oddělené čárkou/mezerou):", "Exclude materials (comma/space separated):"),
                help=_t("Vložené materiály budou kompletně smazány z výpočtů.", "Entered materials will be completely removed from calculations.")
            )
            excluded_materials = []
            if exclude_mats_input:
                excluded_materials = [m.strip().upper() for m in re.split(r'[,\s;]+', exclude_mats_input) if m.strip()]
            st.session_state['excluded_materials'] = excluded_materials

        # Status indicator - Supabase připojení
        st.divider()
        _render_connection_status()

        # Admin zóna
        with st.expander(_t("🛠️ Admin Zóna (Nahrát data do DB)", "🛠️ Admin Zone (Upload to DB)")):
            _render_admin_zone()

        return selected


def _render_app_brand():
    """Logo a branding aplikace v horní části sidebaru."""
    st.markdown(
        """
        <div class="app-brand">
            <div class="app-brand-logo">🏢</div>
            <div class="app-brand-text">
                <div class="app-brand-title">Warehouse CT</div>
                <div class="app-brand-subtitle">Control Tower · v2.1</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_sidebar_quick_stats():
    """Rychlé statistiky v sidebaru (počet řádků, datum posledního update)."""
    stats = st.session_state.get('sidebar_stats', {})
    rows = stats.get('rows', '—')
    last_update = stats.get('last_update', '—')

    st.markdown(
        f"""
        <div class="sidebar-stat">
            <span class="sidebar-stat-label">📊 Řádků v DB</span>
            <span class="sidebar-stat-value">{rows}</span>
        </div>
        <div class="sidebar-stat">
            <span class="sidebar-stat-label">🕒 Posl. update</span>
            <span class="sidebar-stat-value">{last_update}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_connection_status():
    """Zobrazí status připojení k Supabase v sidebaru."""
    client = get_supabase_client()
    if client:
        st.markdown(
            '<div style="text-align:center; padding:8px; background:rgba(16,185,129,0.1); '
            'border:1px solid rgba(16,185,129,0.3); border-radius:8px;">'
            '<span style="color:#34d399;">●</span> '
            '<span style="font-size:12px; color:#94a3b8;">Supabase: Connected</span></div>',
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            '<div style="text-align:center; padding:8px; background:rgba(239,68,68,0.1); '
            'border:1px solid rgba(239,68,68,0.3); border-radius:8px;">'
            '<span style="color:#f87171;">●</span> '
            '<span style="font-size:12px; color:#94a3b8;">Supabase: Disconnected</span></div>',
            unsafe_allow_html=True
        )


def _render_admin_zone():
    """Admin zóna pro upload dat."""
    st.info(_t(
        "Nahrajte Excely sem. Zpracují se do databáze a aplikace poběží bleskově.",
        "Upload Excel files here. They will be processed into the database."
    ))
    admin_pwd = st.text_input(_t("Heslo:", "Password:"), type="password", key="admin_pwd")

    if admin_pwd and admin_pwd == _get_admin_password():
        append_data = st.checkbox(
            _t("Připojovat nová data k existujícím", "Append new data to existing"),
            value=True,
            help=_t("Pokud je zapnuto, stará data zůstanou.", "If checked, old data remains and new is added.")
        )
        uploaded_files = st.file_uploader(
            _t("Nahrát CSV/Excel", "Upload CSV/Excel"),
            accept_multiple_files=True,
            type=["xlsx", "csv"]
        )

        if st.button(_t("Uložit do databáze", "Save to Database"), type="primary", key="admin_save_btn") and uploaded_files:
            with st.spinner(_t("Zpracovávám a ukládám do Supabase...", "Processing and saving...")):
                success_count = 0
                error_files = []
                for file in uploaded_files:
                    try:
                        result = _process_uploaded_file(file, append_data)
                        if result:
                            success_count += 1
                            st.success(f"✅ {file.name}: {result}")
                        else:
                            error_files.append(file.name)
                    except Exception as e:
                        logger.exception(f"Chyba při zpracování {file.name}")
                        error_files.append(file.name)
                        st.error(f"❌ {file.name}: {e}")

                if success_count > 0:
                    st.success(f"🎉 Úspěšně uloženo: {success_count} souborů")
                if error_files:
                    st.warning(f"⚠️ Neuloženo: {len(error_files)} souborů")

                clear_cache()
                time.sleep(1.5)
                st.rerun()
    elif admin_pwd:
        st.error("🔐 Nesprávné heslo")


def _process_uploaded_file(file, append_data: bool) -> Optional[str]:
    """Zpracuje jeden nahraný soubor - uloží ho pod správným klíčem."""
    fname = file.name.lower()

    if fname.endswith('.xlsx') and 'auswertung' in fname:
        aus_xl = pd.ExcelFile(file)
        for sn in aus_xl.sheet_names:
            save_to_db(aus_xl.parse(sn, dtype=str), f"aus_{sn.lower()}", append_data)
        return "Auswertung (multi-sheet)"

    temp_df = pd.read_csv(file, dtype=str, sep=None, engine='python') \
        if fname.endswith('.csv') else pd.read_excel(file, dtype=str)
    temp_df.columns = temp_df.columns.str.strip()
    cols = temp_df.columns.tolist()
    cols_up = [str(c).upper().strip() for c in cols]

    # Univerzální detekce typu reportu
    is_pick = any('ACT.QTY' in c or 'ISTMENGE' in c or 'MNOŽSTVÍ (CÍL)' in c for c in cols_up) \
        and any('TRANSFER ORDER' in c or 'TRANSPORTAUFTRAG' in c for c in cols_up)
    is_queue = any('QUEUE' in c for c in cols_up) and not is_pick
    is_vepo = any('PACKED QUANTITY' in c or 'VEMNG' in c or 'BALENÉ MNOŽSTVÍ' in c for c in cols_up)
    is_vekp = any('GENERATED DELIVERY' in c or 'GENERIERTE LIEFERUNG' in c or 'VYTVOŘENÁ DODÁVKA' in c for c in cols_up) \
        or (any('TOTAL WEIGHT' in c or 'BRGEW' in c for c in cols_up)
            and any('HANDLING UNIT' in c or 'MANIPULAČNÍ' in c for c in cols_up)
            and not is_vepo)
    is_cats = any('KATEGORIE' in c or 'CATEGORY' in c for c in cols_up) \
        and any('DELIVERY' in c or 'LIEFERUNG' in c or 'ZAKÁZKA' in c for c in cols_up)
    is_likp = any('SHIPPING POINT' in c or 'VERSANDSTELLE' in c or 'RECEIVING PT' in c or 'MÍSTO' in c for c in cols_up) \
        and not is_vekp
    is_marm = any('NUMERATOR' in c or 'ČITATEL' in c for c in cols_up) \
        and any('ALTERNATIVE UNIT' in c or 'ALTERNATIVNÍ' in c for c in cols_up)
    is_oe = 'oe-times' in fname or (
        any('PROCESS' in c or 'PROCES' in c for c in cols_up)
        and any('TIME' in c or 'ČAS' in c or 'CAS' in c for c in cols_up)
    )
    is_lt10 = any('AVAILABLE STOCK' in c or 'ZÁSOBA K DISP.' in c for c in cols_up) \
        and any('LAST MOVEMENT' in c or 'POSLEDNÍ POHYB' in c for c in cols_up)
    is_lx03 = any('STORAGE BIN TYPE' in c or 'TYP SKLAD.MÍSTA' in c or 'TYP SKLAD MISTA' in c for c in cols_up) \
        and not is_lt10

    # Přiřazení k databázovému klíči
    if is_pick:
        save_to_db(temp_df, 'raw_pick', append_data); return "Pick Report"
    if is_queue:
        save_to_db(temp_df, 'raw_queue', append_data); return "Queue (LTAK)"
    if is_vepo:
        save_to_db(temp_df, 'raw_vepo', append_data); return "VEPO"
    if is_vekp:
        save_to_db(temp_df, 'raw_vekp', append_data); return "VEKP"
    if is_cats:
        save_to_db(temp_df, 'raw_cats', append_data); return "Kategorie"
    if is_marm:
        save_to_db(temp_df, 'raw_marm', append_data); return "MARM"
    if is_likp:
        save_to_db(temp_df, 'raw_likp', append_data); return "LIKP"
    if is_lt10:
        save_to_db(temp_df, 'raw_lt10', append_data); return "LT10 (Zásoby)"
    if is_lx03:
        save_to_db(temp_df, 'raw_lx03', append_data); return "LX03 (Kapacita)"
    if is_oe:
        rename_map = {}
        has_dn = has_time = False
        for orig, up in zip(cols, cols_up):
            if not has_dn and ('DN NUMBER' in up or 'DELIVERY' in up or 'DODAVKA' in up):
                rename_map[orig] = 'DN NUMBER (SAP)'; has_dn = True
            elif not has_time and ('PROCESS' in up or 'CAS' in up or 'ČAS' in up or 'TIME' in up):
                rename_map[orig] = 'Process Time'; has_time = True
        temp_df = temp_df.rename(columns=rename_map)
        temp_df = temp_df.loc[:, ~temp_df.columns.duplicated()]
        save_to_db(temp_df, 'raw_oe', append_data); return "OE-Times"
    if len(cols) >= 2 and any('MATERIAL' in c or 'MATERIÁL' in c for c in cols_up):
        save_to_db(temp_df, 'raw_manual', append_data); return "Ruční Master Data"

    st.error(f"🚨 Soubor '{file.name}' nebyl rozpoznán a NEULOŽIL SE!")
    st.info(f"🔍 Aplikace v souboru vidí tyto sloupce: {', '.join(cols)}")
    return None


def _render_empty_database_warning():
    """Warning pokud je databáze prázdná."""
    st.markdown(
        """
        <div style="text-align: center; padding: 60px 20px;">
            <div style="font-size: 64px; margin-bottom: 16px;">🗄️</div>
            <h2 style="color: #94a3b8; margin-bottom: 8px;">Databáze je prázdná</h2>
            <p style="color: #64748b; font-size: 16px; max-width: 500px; margin: 0 auto;">
                Otevřete v levém menu <strong>Admin Zónu</strong>, zadejte administrátorské heslo
                a nahrajte Pick Report a další SAP soubory.
            </p>
        </div>
        """,
        unsafe_allow_html=True
    )


def _render_exclusion_filter(df_pick) -> list:
    """Vrací seznam materiálů k vyloučení (zobrazeno v sidebaru)."""
    return st.session_state.get('excluded_materials', [])


def _apply_exclusion_filter(df_pick: pd.DataFrame, excluded: list) -> pd.DataFrame:
    """Aplikuje filtr vyloučených materiálů (vektorově)."""
    if not excluded:
        return df_pick
    try:
        mat_str = df_pick['Material'].astype(str).str.upper()
        excluded_set = set(excluded)
        mask = ~mat_str.isin(excluded_set)
        return df_pick[mask].copy()
    except Exception as e:
        logger.warning(f"Chyba při aplikaci filtru: {e}")
        return df_pick


def _compute_movements_safe(df_pick: pd.DataFrame, data_dict: dict):
    """Bezpečně vypočítá pohyby a uloží je do df_pick (in-place)."""
    limits = st.session_state.get('algorithm_limits', {'vaha': 2.0, 'rozmer': 15.0, 'hrst': 1})
    try:
        tt, te, tm = fast_compute_moves(
            df_pick['Qty'].values,
            df_pick['Queue'].values,
            df_pick['Removal of total SU'].values,
            df_pick['Box_Sizes_List'].values,
            df_pick['Piece_Weight_KG'].values,
            df_pick['Piece_Max_Dim_CM'].values,
            limits['vaha'], limits['rozmer'], limits['hrst']
        )
        df_pick['Pohyby_Rukou'] = pd.Series(tt, index=df_pick.index, dtype='int32')
        df_pick['Pohyby_Exact'] = pd.Series(te, index=df_pick.index, dtype='int32')
        df_pick['Pohyby_Loose_Miss'] = pd.Series(tm, index=df_pick.index, dtype='int32')
        df_pick['Celkova_Vaha_KG'] = (df_pick['Qty'] * df_pick['Piece_Weight_KG']).astype('float32')
    except Exception as e:
        logger.exception("Chyba při výpočtu pohybů")
        st.error(f"⚠️ Chyba při výpočtu fyzických pohybů: {e}")
        df_pick['Pohyby_Rukou'] = 0
        df_pick['Pohyby_Exact'] = 0
        df_pick['Pohyby_Loose_Miss'] = 0
        df_pick['Celkova_Vaha_KG'] = 0.0


def _route_to_page(selected_page: str, df_pick: pd.DataFrame, data_dict: dict):
    """Routuje podle vybrané stránky - lazy loading modulů."""
    page_routes = {
        _t("Přehled a Fronty", "Dashboard & Queue"):
            lambda: _safe_render_tab("dashboard", "render_dashboard",
                                     df_pick, data_dict['queue_count_col']),
        _t("Denní KPI (Ráno)", "Daily KPI"):
            lambda: _safe_render_tab("daily_kpi", "render_daily_kpi",
                                     df_pick, data_dict['df_vekp']),
        _t("Měsíční KPI (Cíle)", "Monthly KPI"):
            lambda: _safe_render_tab("monthly_kpi", "render_monthly_kpi",
                                     df_pick, data_dict['df_vekp'], data_dict['df_vepo']),
        _t("Paletové zakázky", "Pallet Orders"):
            lambda: _safe_render_tab("pallets", "render_pallets", df_pick),
        _t("Celé palety (FU)", "Full Pallets (FU)"):
            lambda: _safe_render_tab("fu", "render_fu",
                                     df_pick, data_dict['queue_count_col']),
        _t("Porovnání (FU vs SAP)", "Compare (FU vs SAP)"):
            lambda: _safe_render_tab("fu_compare", "render_fu_compare",
                                     df_pick, st.session_state.get('billing_df'),
                                     st.session_state.get('voll_set'),
                                     data_dict['queue_count_col']),
        _t("Materiály (TOP)", "Top Materials"):
            lambda: _safe_render_tab("top", "render_top", df_pick),
        _t("Fakturace", "Billing"):
            lambda: _safe_render_billing(df_pick, data_dict),
        _t("Balení (Packing)", "Packing"):
            lambda: _safe_render_tab("packing", "render_packing",
                                     st.session_state.get('billing_df', pd.DataFrame()),
                                     data_dict['df_oe']),
        _t("Sklad (Storage)", "Storage"):
            lambda: _safe_render_storage(df_pick),
        _t("Admins", "Admins"):
            lambda: _safe_render_admins(data_dict),
        _t("Audit & Rentgen", "Audit & X-Ray"):
            lambda: _safe_render_audit(df_pick, data_dict),
        _t("Nástěnka (Tisk grafů)", "Notice Board (Print)"):
            lambda: _safe_render_tab("board", "render_board", df_pick,
                                     st.session_state.get('billing_df', pd.DataFrame())),
    }

    route = page_routes.get(selected_page)
    if route:
        try:
            route()
        except Exception as e:
            logger.exception(f"Chyba při routování na {selected_page}")
            st.error(f"⚠️ Chyba při načítání stránky: {e}")
    else:
        st.warning(f"⚠️ Neznámá stránka: {selected_page}")


def _safe_render_tab(module_name: str, func_name: str, *args):
    """Lazy import + safe render wrapper pro standardní tab moduly."""
    try:
        module = __import__(f"modules.tab_{module_name}", fromlist=[func_name])
        func = getattr(module, func_name)
        func(*args)
    except ImportError as e:
        st.error(f"❌ Modul `tab_{module_name}` se nepodařilo načíst: {e}")
    except AttributeError as e:
        st.error(f"❌ Funkce `{func_name}` nebyla nalezena: {e}")
    except Exception as e:
        logger.exception(f"Chyba v tab_{module_name}")
        st.error(f"⚠️ Chyba v záložce: {e}")


def _safe_render_billing(df_pick, data_dict):
    """Speciální wrapper pro Billing - vyžaduje návrat billing_df."""
    try:
        from modules.tab_billing import render_billing
        billing_df = render_billing(
            df_pick, data_dict['df_vekp'], data_dict['df_vepo'],
            data_dict['df_cats'], data_dict['queue_count_col']
        )
        st.session_state['billing_df'] = billing_df
    except Exception as e:
        logger.exception("Chyba v Billing")
        st.error(f"⚠️ Chyba ve Fakturaci: {e}")


def _safe_render_storage(df_pick):
    """Wrapper pro Storage s lazy loading dat."""
    with st.spinner(_t("Načítám data skladu...", "Loading storage data...")):
        try:
            df_lx03 = load_from_db('raw_lx03')
            df_lt10 = load_from_db('raw_lt10')
            df_marm = load_from_db('raw_marm')
            from modules.tab_storage import render_storage
            render_storage(df_lx03, df_lt10, df_marm, df_pick)
        except Exception as e:
            logger.exception("Chyba v Storage")
            st.error(f"⚠️ Chyba ve Skladu: {e}")


def _safe_render_admins(data_dict):
    """Wrapper pro Admins."""
    with st.spinner(_t("Načítám admin data...", "Loading admin data...")):
        try:
            df_likp = load_from_db('raw_likp')
            from modules.tab_admins import render_admins
            render_admins(data_dict['df_vekp'], df_likp)
        except Exception as e:
            logger.exception("Chyba v Admins")
            st.error(f"⚠️ Chyba v Admins: {e}")


def _safe_render_audit(df_pick, data_dict):
    """Wrapper pro Audit s kompletními parametry."""
    limits = st.session_state.get('algorithm_limits', {'vaha': 2.0, 'rozmer': 15.0, 'hrst': 1})
    try:
        from modules.tab_audit import render_audit
        render_audit(
            df_pick, data_dict['df_vekp'], data_dict['df_vepo'], data_dict['df_oe'],
            data_dict['queue_count_col'], st.session_state.get('billing_df', pd.DataFrame()),
            data_dict['manual_boxes'], data_dict['weight_dict'], data_dict['dim_dict'],
            data_dict['box_dict'], limits['vaha'], limits['rozmer'], limits['hrst']
        )
    except Exception as e:
        logger.exception("Chyba v Audit")
        st.error(f"⚠️ Chyba v Auditu: {e}")


def _render_excel_export(df_pick: pd.DataFrame, data_dict: dict):
    """Generuje a zobrazuje tlačítko pro Excel export."""
    buffer = io.BytesIO()
    try:
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            # Settings sheet
            limits = st.session_state.get('algorithm_limits', {})
            pd.DataFrame({
                "Parameter": ["Weight Limit", "Dim Limit", "Grab limit", "Admins Excluded"],
                "Value": [f"{limits.get('vaha', 2.0)} kg",
                          f"{limits.get('rozmer', 15.0)} cm",
                          f"{limits.get('hrst', 1)} pcs",
                          data_dict['num_removed_admins']]
            }).to_excel(writer, index=False, sheet_name='Settings')

            # Material totals
            if 'Pohyby_Rukou' in df_pick.columns and not df_pick.empty:
                mat_summary = df_pick.groupby('Material', observed=True).agg(
                    Moves=('Pohyby_Rukou', 'sum'),
                    Qty=('Qty', 'sum'),
                    Exact=('Pohyby_Exact', 'sum'),
                    Estimates=('Pohyby_Loose_Miss', 'sum'),
                    Lines=('Material', 'count')
                ).reset_index().sort_values('Moves', ascending=False)
                mat_summary.to_excel(writer, index=False, sheet_name='Material_Totals')

                # Pallet orders
                try:
                    queue_col = 'Queue'
                    df_pal_exp = df_pick[
                        df_pick[queue_col].astype(str).str.upper().isin(['PI_PL', 'PI_PL_OE'])
                    ].groupby('Delivery', observed=True).agg(
                        num_materials=('Material', 'nunique'),
                        material=('Material', 'first'),
                        total_qty=('Qty', 'sum'),
                        total_moves=('Pohyby_Rukou', 'sum'),
                        exact_moves=('Pohyby_Exact', 'sum'),
                        estimated_moves=('Pohyby_Loose_Miss', 'sum'),
                        order_weight=('Celkova_Vaha_KG', 'sum'),
                        max_dim=('Piece_Max_Dim_CM', 'first')
                    ).reset_index()
                    df_pal_single = df_pal_exp[df_pal_exp['num_materials'] == 1].copy()
                    if not df_pal_single.empty:
                        df_pal_single.to_excel(writer, index=False, sheet_name='Single_Material_Orders')
                except Exception as e:
                    logger.warning(f"Export pallet orders selhal: {e}")

        st.download_button(
            label=_t("⬇️ Stáhnout kompletní Excel report", "⬇️ Download Complete Excel Report"),
            data=buffer.getvalue(),
            file_name=f"Warehouse_Control_Tower_{time.strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            width="stretch"
        )
    except Exception as e:
        logger.exception("Chyba při generování Excel exportu")
        st.warning(f"⚠️ Excel export selhal: {e}")


def _render_footer(df_pick: pd.DataFrame, data_dict: dict):
    """Footer s metadaty o aplikaci a datech."""
    st.markdown("---")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown(
            "**📊 Data**  \n"
            f"<small>{len(df_pick):,} řádků</small>",
            unsafe_allow_html=True
        )
    with col2:
        st.markdown(
            "**🗄️ Databáze**  \n"
            "<small>Supabase Parquet</small>",
            unsafe_allow_html=True
        )
    with col3:
        st.markdown(
            "**⚙️ Algoritmus**  \n"
            "<small>End-to-End Pick Analysis</small>",
            unsafe_allow_html=True
        )
    with col4:
        st.markdown(
            "**📅 Vygenerováno**  \n"
            f"<small>{time.strftime('%Y-%m-%d %H:%M:%S')}</small>",
            unsafe_allow_html=True
        )
    st.caption(
        "Warehouse Control Tower v2.1 · "
        "Pokud narazíte na chybu, obnovte stránku (F5) nebo kontaktujte administrátora."
    )


# ==========================================
# ENTRY POINT
# ==========================================

if __name__ == "__main__":
    main()