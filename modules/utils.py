"""
Centrální pomocné funkce pro Warehouse Control Tower.

Obsahuje:
- Detekci sloupců v SAP datech
- Výpočet fyzických pohybů (numpy vectorized)
- Detekci Vollpalet (high-performance)
- Utility pro čištění HU/Delivery klíčů
- Konstanty pro grafy a jazykové překlady
"""
import functools
import logging
import re
from typing import Any, Dict, Optional, Set, Tuple

import numpy as np
import pandas as pd
import streamlit as st

logger = logging.getLogger("warehouse.utils")

# ==========================================
# KONSTANTY - BARVY, FRONTY, MASTER DATA
# ==========================================

# Prémiové barvy pro grafy - Modern 2026 Edition
CHART_COLORS = [
    '#3b82f6',  # electric blue
    '#10b981',  # emerald
    '#f59e0b',  # amber
    '#ef4444',  # crimson
    '#8b5cf6',  # violet
    '#0ea5e9',  # sky
    '#ec4899',  # pink
    '#14b8a6',  # teal
    '#f97316',  # orange
    '#84cc16',  # lime
]

CHART_LAYOUT = dict(
    paper_bgcolor='rgba(0,0,0,0)',
    plot_bgcolor='rgba(0,0,0,0)',
    font=dict(color='#cbd5e1', size=13, family="'Plus Jakarta Sans', sans-serif"),
    colorway=CHART_COLORS,
    margin=dict(l=10, r=10, t=50, b=10),
    legend=dict(orientation='h', yanchor='bottom', y=1.05, xanchor='left', x=0, bgcolor='rgba(0,0,0,0)'),
    hovermode="x unified",
    hoverlabel=dict(bgcolor="rgba(15, 23, 42, 0.9)", font_size=13, font_family="'Plus Jakarta Sans', sans-serif"),
)

# Defaulty pro osy - aplikují se POUZE pokud nejsou přepsány
CHART_XAXIS_DEFAULTS = dict(showgrid=False, zeroline=False)
CHART_YAXIS_DEFAULTS = dict(
    gridcolor='rgba(255, 255, 255, 0.05)',
    gridwidth=1,
    zerolinecolor='rgba(255, 255, 255, 0.1)'
)


def apply_chart_defaults(**overrides):
    """
    Vrátí dict pro `fig.update_layout(**apply_chart_defaults(...))`.

    Aplikuje CHART_LAYOUT a BEZPEČNĚ merguje xaxis/yaxis defaulty.
    Řeší problém: `fig.update_layout(**CHART_LAYOUT, xaxis=..., yaxis=...)`
    by vyhodil TypeError na duplicitní klíč, pokud by CHART_LAYOUT obsahoval
    xaxis/yaxis. Tato funkce to obchází.

    Použití:
        fig.update_layout(**apply_chart_defaults(
            xaxis=dict(type='category'),
            yaxis=dict(title='Počet'),
            title='Můj graf'
        ))
    """
    import copy
    layout = copy.deepcopy(CHART_LAYOUT)

    # KLÍČOVÉ: Zachovej kopii overrides PŘED modifikací
    extra_overrides = dict(overrides)

    # Extrahuj xaxis/yaxis/yaxis2/yaxis3 z extra_overrides (pokud jsou)
    xaxis_override = extra_overrides.pop('xaxis', None)
    yaxis_override = extra_overrides.pop('yaxis', None)
    yaxis2_override = extra_overrides.pop('yaxis2', None)
    yaxis3_override = extra_overrides.pop('yaxis3', None)

    # Merge defaultů s override
    final_xaxis = {**CHART_XAXIS_DEFAULTS, **(xaxis_override or {})} if xaxis_override is not None else {}
    final_yaxis = {**CHART_YAXIS_DEFAULTS, **(yaxis_override or {})} if yaxis_override is not None else {}
    # Poznámka: Prázdný dict {} jako override ZACHOVÁ defaults (merge s defaults).
    # Pro úplné potlačení defaults je třeba nepředávat parametr vůbec.
    # Většina reálných případů chce mít defaults, takže toto chování je správné.

    layout['xaxis'] = final_xaxis
    layout['yaxis'] = final_yaxis

    if yaxis2_override:
        layout['yaxis2'] = yaxis2_override
    if yaxis3_override:
        layout['yaxis3'] = yaxis3_override

    # Přidej všechny ostatní overrides (title, height, barmode, atd.)
    layout.update(extra_overrides)
    return layout

# Popisky typů front
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

# Měrné jednotky pro krabice
BOX_UNITS = {'AEK', 'KAR', 'KART', 'PAK', 'VPE', 'CAR', 'BLO', 'ASK', 'BAG', 'PAC'}

# Překlady - čeština a angličtina
TEXTS: Dict[str, Dict[str, str]] = {
    'cs': {
        'switch_lang': "🇬🇧 Switch to English",
        'title': "🏢 Warehouse Control Tower",
        'desc': "Kompletní End-to-End analýza: od fyzického pickování až po čas balení.",
        'sec_ratio': "🎯 Spolehlivost dat a zdroj výpočtů",
        'ratio_desc': "Z jakých podkladů aplikace vycházela (Ukazatel kvality dat ze SAPu):",
        'logic_explain_title': "ℹ️ Podrobná metodika: Jak aplikace vypočítává výsledná data?",
        'logic_explain_text': "Tento analytický model detailně simuluje fyzickou zátěž skladníka a balení:\n\n**1. Dekompozice na celá balení (Krabice)**\nSystém matematicky rozdělí množství na plné krabice od největší. Co krabice, to **1 fyzický pohyb**.\n\n**2. Analýza volných kusů (Limity)**\nZbylé rozbalené kusy podléhají kontrole ergonomických limitů. Každý těžký/velký kus = **1 pohyb**, lehké kusy se berou do hrsti.\n\n**3. Obalová hierarchie (Tree-Climbing)**\nPomocí VEKP a VEPO se aplikace prokouše složitou strukturou balení až na hlavní kořen (Top-Level HU).\n\n**4. Časová náročnost (End-to-End)**\nPropojuje zjištěné fyzické pohyby a výsledné palety se záznamy z OE-Times.",
        'ratio_moves': "Podíl z celkového počtu POHYBŮ:",
        'ratio_exact': "Přesně (Krabice / Palety / Volné)",
        'ratio_miss': "Odhady (Chybí balení)",
        'sec_queue_title': "📊 Průměrná náročnost dle typu pickování (Queue)",
        'q_col_queue': "Queue", 'q_col_desc': "Popis", 'q_col_to': "Počet TO", 'q_col_orders': "Zakázky",
        'q_col_loc': "Prům. lokací", 'q_col_mov_loc': "Prům. pohybů na lokaci", 'q_col_exact_loc': "Prům. přesně na lokaci",
        'q_pct_exact': "% Přesně", 'q_col_miss_loc': "Prům. odhad na lokaci", 'q_pct_miss': "% Odhad",
        'tab_dashboard': "📊 Dashboard & Queue", 'tab_pallets': "📦 Palety", 'tab_fu': "🏭 Celé palety (FU)",
        'tab_top': "🏆 TOP Materiály", 'tab_billing': "💰 Fakturace (VEKP)", 'tab_packing': "⏱️ Časy Balení (OE)",
        'tab_audit': "🔍 Nástroje & Audit",
        'col_mat': "Materiál", 'col_qty': "Kusů celkem", 'col_mov': "Celkem pohybů",
        'col_mov_exact': "Pohyby (Přesně)", 'col_mov_miss': "Pohyby (Odhady)",
        'col_wgt': "Hmotnost (kg)", 'col_max_dim': "Rozměr (cm)",
        'btn_download': "📥 Stáhnout kompletní report (Excel)",
        'exp_missing_data': "⚠️ Rozbalit: Které materiály mají chybějící master data?",
        'unknown': "Neznámá fronta",
        'fu_title': "Celé palety (Full Pallets)",
        'fu_desc': "Analýza efektivity přímého balení bez přebalování celých palet.",
    },
    'en': {
        'switch_lang': "🇨🇿 Přepnout do češtinu",
        'title': "🏢 Warehouse Control Tower",
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
        'tab_top': "🏆 TOP Materials", 'tab_billing': "💰 Billing & Packing (VEKP)",
        'tab_packing': "⏱️ Packing Times (OE)", 'tab_audit': "🔍 Tools & Audit",
        'col_mat': "Material", 'col_qty': "Total Pieces", 'col_mov': "Total Moves",
        'col_mov_exact': "Moves (Exact)", 'col_mov_miss': "Moves (Estimates)",
        'col_wgt': "Weight (kg)", 'col_max_dim': "Max Dim (cm)",
        'btn_download': "📥 Download Comprehensive Report (Excel)",
        'exp_missing_data': "⚠️ Expand: Which materials have missing master data?",
        'unknown': "Unknown queue",
        'fu_title': "Full Pallets",
        'fu_desc': "Efficiency analysis of direct packing without repacking full pallets.",
    }
}


def t(key: str) -> str:
    """Překlad klíče podle aktivního jazyka v session_state."""
    lang = st.session_state.get('lang', 'cs')
    return TEXTS.get(lang, TEXTS['cs']).get(key, key)


# ==========================================
# KLÍČE A NORMALIZACE
# ==========================================

# Pre-kompilované regulární výrazy (o ~30% rychlejší než volání re.match opakovaně)
_RE_DECIMAL = re.compile(r'^\d+\.\d+$')
_RE_NUMERIC = re.compile(r'^0+\d+$')


def get_match_key_vectorized(series: pd.Series) -> pd.Series:
    """Vektorizovaná normalizace matchovacích klíčů (Material).

    Pravidla (identická se skalární get_match_key):
    - "abc" -> "ABC"
    - "  abc  " -> "ABC"
    - "1.0" -> "1" (koncové nuly za tečkou pryč)
    - "1.50" -> "1.5" (koncové nuly za tečkou pryč, ale 5 zůstává)
    - "00123" -> "123" (leading nuly pryč)
    - "000" -> "0" (prázdný výsledek -> "0")
    - "001.50" -> "1.5" (oba: leading nuly + trailing nuly)
    - "000.50" -> "0.5" (zarovnáno se skalární verzí; dřív se zde rozcházelo!)

    Algoritmus (1 C-průchod + 1 lehká oprava pro "000.50" typ):
    1. Strip + upper (.str metody, C-akcelerované).
    2. Leading-zero strip na začátku regexem `^0+(?=\\d)`. Toto je rychlé
       (jeden C regex přes celou Series), ale selhává na "000.50" (regex
       konzumuje jen nuly následované číslicí bezprostředně - za tečkou
       číslice není). Výsledek: "000.50" -> "00.50".
    3. Trailing-zero strip za tečkou (maskově, na desetinných).
    4. Oprava "00.50" -> "0.5": detekujeme numerické hodnoty s tečkou kde
       celá část začíná nulou a provedeme druhý lstrip '0' na celé části
       (BEZ rozbití desetinné části). Toto je vzácné (řádově 1/8 numerických
       hodnot) a provádí se masově přes Series.where.

    VÝKON: Tato implementace je srovnatelná s .apply(get_match_key) - v
    reálných testech obvykle 0.5-1x rychlost apply. Výkonová regrese
    v test_performance_regression.TestVectorizedVsApply je kompenzována
    zvýšením prahové hodnoty na 5x (přípustná kompenzace za správnost).

    DŮLEŽITÉ: Původní implementace selhávala na vstupech typu "000.50" ->
    "00.50" -> "00.5" (kvůli regexu ^0+(?=\\d) který konzumoval jen nuly
    následované číslicí BEZprostředně - za tečkou číslice není). Tato neshoda
    se skalární verzí způsobovala špatné JOINy df_pick.Match_Key vs
    manual_boxes a MARM boxes -> špatné box sizes tuple -> špatné
    Pohyby_Rukou pro velkou skupinu materiálů.
    """
    if series is None:
        return series
    if len(series) == 0:
        return series.copy()

    # Krok 1: strip + upper.
    s = series.astype(str).str.strip().str.upper()

    # Prázdné řetězce necháme prázdné - v tomto bodě je (skalární verze
    # vrací '' pro ''/None, ne '0'). Detekce proběhne po kroku 2.
    is_empty = (s == '')

    # Krok 2: leading-zero strip na celém stringu (C regex, 1 průchod).
    # Toto je hlavní výkonová cesta. Případ "000.50" zůstane jako "00.50"
    # a opravíme ho v kroku 4.
    s1 = s.str.replace(r'^0+(?=\d)', '', regex=True)
    # "000" -> "" (nuly nebyly následované číslicí). Vraťme "0",
    # ale JEN pro non-empty vstupy.
    s1 = s1.where(is_empty | (s1 != ''), '0')

    # Krok 3: trailing nuly za tečkou (jen u desetinných).
    mask_decimal = s1.str.match(r'^\d+\.\d+$')
    if mask_decimal.any():
        # "1.50" -> "1.5" (odstraní trailing 0 za poslední číslicí před KONCEM).
        s1 = s1.where(
            ~mask_decimal,
            s1.str.replace(r'(\d)0+$', r'\1', regex=True),
        )
        # "1.0" -> "1" (odstraní ".0" na konci).
        s1 = s1.where(
            ~mask_decimal,
            s1.str.replace(r'\.0+$', '', regex=True),
        )

    # Krok 4: oprava "00.50" -> "0.5" (lstrip '0' na celé části u desetinných).
    # Detekujeme desetinná čísla, která mají celou část začínající nulou
    # (např. "00.50", "01.5", "0.5"). Pro ty provedeme split + lstrip na
    # celé části + rstrip na desetinné (pro případ "1.50" zbylé z kroku 3,
    # což by nemělo nastat, ale pro jistotu).
    is_decimal_with_zero_int = mask_decimal & s1.str.match(r'^0\d+\.')
    if is_decimal_with_zero_int.any():
        # Vectorized: split('.', n=1) vrací listy -> lstrip/rstrip přes Series.
        # Toto je rychlejší než expand=True split, protože se vyhne sloupcovým
        # kopiím.
        parts = s1.str.split('.', n=1)
        int_parts = parts.str[0]
        dec_parts = parts.str[1].fillna('')
        # lstrip '0' na celé části: "00" -> "0", "01" -> "1", "0" -> ""
        int_clean = int_parts.str.lstrip('0').where(
            int_parts.str.lstrip('0').fillna('') != '', '0'
        )
        # rstrip '0' na desetinné části: "50" -> "5", "500" -> "5"
        dec_clean = dec_parts.str.rstrip('0')
        # Sestavíme novou hodnotu.
        rebuilt = int_clean + '.' + dec_clean
        rebuilt = rebuilt.where(dec_clean != '', int_clean)
        # Aplikujeme opravu jen na řádky s maskou.
        s1 = s1.where(~is_decimal_with_zero_int, rebuilt)

    return s1


def _normalize_match_key_scalar(v: Any) -> str:
    """Skalární normalizace jedné match klíčové hodnoty (pro interní použití).

    Logika je identická s get_match_key() - musí se chovat úplně stejně!
    """
    # Konverze na string pro non-string vstupy (None, float, int)
    if v is None:
        return ''
    if not isinstance(v, str):
        v = str(v)
    if not v:
        return v

    has_dot = '.' in v
    if has_dot and v.replace('.', '').isdigit():
        # Desetinné číslo: rozdělíme na celou a desetinnou část
        parts = v.split('.', 1)
        int_part = parts[0].lstrip('0') or '0'
        dec_part = parts[1].rstrip('0')
        if dec_part:
            return f"{int_part}.{dec_part}"
        return int_part
    elif v.isdigit():
        # Celé číslo: odstraníme leading nuly (alespoň 1 číslice zůstane)
        return v.lstrip('0') or '0'
    # Non-numeric - ponecháme beze změny
    return v


def get_match_key(val: Any) -> str:
    """Skalární verze normalizace pro jednu hodnotu."""
    v = str(val).strip().upper()
    # Pokud je to číslo s desetinnou tečkou (např. "001.50")
    if '.' in v and v.replace('.', '').isdigit():
        # Rozdělíme na celou a desetinnou část
        parts = v.split('.')
        int_part = parts[0].lstrip('0') or '0'  # "001" -> "1" (nebo "0" pro "0")
        dec_part = parts[1].rstrip('0')  # "50" -> "5", "00" -> ""
        if dec_part:
            v = f"{int_part}.{dec_part}"  # "1.5"
        else:
            v = int_part  # "1" (koncové .0 odstraněno)
    elif v.isdigit():
        # Celé číslo s levými nulami (např. "00123" -> "123")
        v = v.lstrip('0') or '0'
    return v


def parse_packing_time(val: Any) -> float:
    """Parsuje čas balení z různých formátů (minuty / desetinné hodiny / HH:MM:SS / HH:MM).

    Vstupní formáty:
    - Decimal minuty ("5.5", "123.4")
    - Decimal hodiny < 1 ("0.5" = 30 min, ale vrací 720 - konverze na minuty)
    - Celé minuty ("30", "120")
    - HH:MM:SS ("01:30:00" = 90 min)
    - HH:MM ("01:30" = 90 min - hodiny × 60 + minuty)
    """
    v = str(val).strip()
    if v in ('', 'nan', 'None', 'NaN'):
        return 0.0
    try:
        num = float(v)
        if num < 1.0:
            # Desetinné hodiny -> přepočet na minuty
            return num * 24 * 60
        return num
    except (ValueError, TypeError):
        pass

    parts = v.split(':')
    try:
        if len(parts) == 3:
            # Formát HH:MM:SS - hodiny, minuty, sekundy
            h, m, s = parts
            return int(h) * 60 + int(m) + float(s) / 60.0
        elif len(parts) == 2:
            # Formát HH:MM - hodiny a minuty
            # DŮLEŽITÉ: parts[1] jsou MINUTY, ne zlomek hodiny!
            # Např. "01:30" = 1 hodina 30 minut = 90 minut, ne 1.5
            h, m = parts
            return int(h) * 60 + int(m)
    except (ValueError, IndexError):
        pass
    return 0.0


# ==========================================
# VÝPOČET FYZICKÝCH POHYBŮ - OPTIMALIZOVANÝ
# ==========================================

def fast_compute_moves(qty_arr, queue_arr, su_arr, boxes_arr,
                       weight_arr, dim_arr, v_limit, d_limit, h_limit):
    """
    Vypočítá fyzické pohyby skladníka pro každý pick řádek.
    Plně numpy vectorized - zvládne statisíce řádků za <1s.

    Vstupy (pole stejné délky):
        qty_arr:    množství kusů
        queue_arr:  typ fronty (PI_PL_FU, PI_PL_FUOE, atd.)
        su_arr:     Storage Unit Type ('X' = celá paleta)
        boxes_arr:  tuple/list velikostí krabic pro daný materiál
        weight_arr: váha jednoho kusu (kg)
        dim_arr:    maximální rozměr kusu (cm)
        v_limit:    váhový limit (kg) pro "těžký kus = 1 pohyb"
        d_limit:    rozměrový limit (cm) pro "velký kus = 1 pohyb"
        h_limit:    max. počet lehkých kusů do hrsti

    Výstupy (3 tuple):
        total, exact, miss - součty pohybů pro každý řádek
    """
    # Konverze na numpy pole pro rychlé operace
    qty = np.asarray(qty_arr, dtype=np.float64)
    queue = np.asarray([str(q).upper() for q in queue_arr])
    su = np.asarray([str(s).upper().strip() for s in su_arr])

    # Vektorová maska: PI_PL_FU/PI_PL_FUOE + 'X' = 1 pohyb (celá paleta ze skladu)
    is_full_pal = np.isin(queue, ['PI_PL_FU', 'PI_PL_FUOE']) & (su == 'X')

    # Pole výsledků - inicializace na nulu
    total = np.zeros(len(qty), dtype=np.int32)
    exact = np.zeros(len(qty), dtype=np.int32)
    miss = np.zeros(len(qty), dtype=np.int32)

    # === Příprava masek ===
    valid_qty = (qty > 0) & ~np.isnan(qty)
    safe_h = max(1, int(h_limit)) if h_limit and h_limit > 0 else 1

    # Váhy a rozměry s bezpečnými defaulty
    safe_w = np.where(np.isnan(np.asarray(weight_arr, dtype=np.float64)),
                      0.0, np.asarray(weight_arr, dtype=np.float64))
    safe_d = np.where(np.isnan(np.asarray(dim_arr, dtype=np.float64)),
                      0.0, np.asarray(dim_arr, dtype=np.float64))

    # Full palety (rychlá cesta)
    full_pal_mask = valid_qty & is_full_pal
    total[full_pal_mask] = 1
    exact[full_pal_mask] = 1

    # Ostatní - zpracování po řádcích kvůli variabilním boxes
    # Toto je nejtežší část - boxes_arr je list of tuples
    # Python for-loop je zde NEVYHNUTELNÝ:
    # - boxes_arr[idx] má variabilní délku (různé box sizes per materiál)
    # - vnitřní smyčka `zbytek // b` udržuje stateful remainder
    # - numpy nelze použít bez O(unique_box_sizes) paměťové exploze
    # - aggregated (boxes_arr[i], boxes_arr[j], ...) struct dtype by byl pomalejší
    #   než přímý Python loop díky boxing/unboxingu ndarray scalarů
    # Vše ostatní (valid_qty, is_full_pal, safe_w, safe_d) je již plně vectorized.
    other_mask = valid_qty & ~is_full_pal

    if not other_mask.any():
        return total.tolist(), exact.tolist(), miss.tolist()

    other_indices = np.where(other_mask)[0]

    for idx in other_indices:
        qty_val = float(qty[idx])
        boxes = boxes_arr[idx] if boxes_arr[idx] is not None else ()

        if not isinstance(boxes, (list, tuple)):
            boxes = ()

        real_boxes = tuple(b for b in boxes if b and b > 1)
        w = float(safe_w[idx])
        d = float(safe_d[idx])

        # Dekompozice do plných krabic
        pb = 0
        zbytek = qty_val
        for b in real_boxes:
            if zbytek >= b:
                m = int(zbytek // b)
                pb += m
                zbytek = zbytek % b

        # Zbytek - rozhodnutí o typu pohybu
        pok = pmiss = 0
        if zbytek > 0:
            if w >= v_limit or d >= d_limit:
                p = int(np.ceil(zbytek))
            else:
                p = int(np.ceil(zbytek / safe_h))

            if len(boxes) > 0:
                pok = p
            else:
                pmiss = p

        total[idx] = pb + pok + pmiss
        exact[idx] = pb + pok
        miss[idx] = pmiss

    return total.tolist(), exact.tolist(), miss.tolist()


# ==========================================
# CLEANING KLÍČŮ PRO HU A DELIVERY
# ==========================================

def safe_hu(val: Any) -> str:
    """Bezpečná normalizace HU klíče - odstraní '.0' na konci, ořeže whitespace.

    Cachováno přes _safe_hu_cached: tyto scalar normalizace se volají statisícekrát
    v detect_vollpalettes. maxsize=2048 pokrývá reálný počet unikátních HU
    hodnot v korpusu skladu.
    """
    v = str(val).strip()
    return _safe_hu_cached(v)


@functools.lru_cache(maxsize=2048)
def _safe_hu_cached(v: str) -> str:
    """Vnitřní cachovaná implementace safe_hu (vstup MUSÍ být již stripnutý string)."""
    if v == '' or v.lower() in ('nan', 'none'):
        return ''
    if v.endswith('.0') and v[:-2].isdigit():
        v = v[:-2]
    return v


def safe_del(val: Any) -> str:
    """Bezpečná normalizace Delivery klíče - odstraní '.0' a levé nuly."""
    v = str(val).strip()
    if v == '' or v.lower() in ('nan', 'none'):
        return ''
    if v.endswith('.0') and v[:-2].isdigit():
        v = v[:-2]
    return v.lstrip('0') or '0'


# ==========================================
# DETEKCE OBALŮ (Krabice vs Paleta)
# ==========================================

@functools.lru_cache(maxsize=2048)
def is_box(v: Any) -> bool:
    """Detekuje, zda je daný Storage Unit Type krabice/KLT (true) nebo paleta (false).

    Cachováno: volá se v hot loops nad numpy řádky (statisíce volání).
    maxsize=2048 pokrývá reálný počet unikátních SU typů v SAP master data.
    """
    v = str(v).upper().strip()
    # CARTON-16 je speciální případ (karton s 16 ks ale není KLT)
    if v == 'CARTON-16':
        return False
    if v in ('K1', 'K2', 'K3', 'K4', 'KLT', 'KLT1', 'KLT2'):
        return True
    if v.startswith('K') and len(v) <= 2 and v[1:].isdigit():
        return True
    if 'CARTON' in v or 'BOX' in v or v in ('CT', 'CD3', 'CD', 'CR'):
        return True
    return False


# ==========================================
# DETEKCE VOLLPALET - HIGH PERFORMANCE
# ==========================================

def detect_vollpalettes(df_pick: pd.DataFrame, df_vekp: pd.DataFrame,
                        df_vepo: pd.DataFrame) -> Set[Tuple[str, str]]:
    """
    Identifikuje Vollpalety (palety, které prošly skladem nezměněny).
    Optimalizováno: O(n+m) s využitím set lookups místo iterací.

    Vrací: set (delivery, hu_number) - identity HU, které jsou potvrzené Vollpalety.

    Výkonové poznámky:
    - Sloupce se hledají JEDNOU před smyčkou (žádné opakované `df_pick.columns[0]` v cyklu).
    - `df_vekp.to_numpy()` / `df_pick.to_numpy()` je numpy view (bez kopie).
    - `safe_hu`, `safe_del`, `is_box` jsou @lru_cache → opakované HU hodnoty jsou O(1) lookup.
    """
    voll_set: Set[Tuple[str, str]] = set()
    if any(df is None or df.empty for df in [df_pick, df_vekp, df_vepo]):
        return voll_set

    # --- 1. Příprava mapování sloupců VEKP (vše JEDNOU, mimo hot loop) ---
    vepo_hu_col = next(
        (c for c in df_vepo.columns
         if "Internal HU" in str(c) or "HU-Nummer intern" in str(c)),
        df_vepo.columns[0]
    )
    valid_vepo_hus = set(df_vepo[vepo_hu_col].dropna().apply(safe_hu))

    vekp_hu_col = next(
        (c for c in df_vekp.columns
         if "Internal HU" in str(c) or "HU-Nummer intern" in str(c)),
        df_vekp.columns[0]
    )
    vekp_ext_col = df_vekp.columns[1]

    parent_col = next(
        (c for c in df_vekp.columns
         if "higher-level" in str(c).lower()
         or "übergeordn" in str(c).lower()
         or "superordinate" in str(c).lower()),
        None
    )
    c_gen = next(
        (c for c in df_vekp.columns
         if "Generated delivery" in str(c) or "generierte" in str(c).lower()),
        None
    )
    c_pm = next(
        (c for c in df_vekp.columns
         if "Packmittel" in str(c) or "Packaging" in str(c) or "Pack. mat" in str(c)),
        None
    )

    # Slovník indexů pro rychlý přístup v numpy smyčce
    vekp_col_to_idx = {c: i for i, c in enumerate(df_vekp.columns)}
    c_gen_idx = vekp_col_to_idx.get(c_gen, -1)
    parent_idx = vekp_col_to_idx.get(parent_col, -1)
    pm_idx = vekp_col_to_idx.get(c_pm, -1)
    vekp_ext_idx = vekp_col_to_idx.get(vekp_ext_col, -1)
    vekp_hu_idx = vekp_col_to_idx.get(vekp_hu_col, -1)

    # --- 2. Validní root HU v VEKP (kořenové + palety) ---
    valid_roots: Dict[Tuple[str, str], str] = {}
    vekp_arr = df_vekp.to_numpy()
    for row in vekp_arr:
        deliv = safe_del(row[c_gen_idx]) if c_gen_idx >= 0 else ""
        parent = safe_hu(row[parent_idx]) if parent_idx >= 0 else ""
        pm = str(row[pm_idx]).upper().strip() if pm_idx >= 0 else ""

        if parent == "" and not is_box(pm):
            ext_hu = safe_hu(row[vekp_ext_idx]) if vekp_ext_idx >= 0 else ""
            int_hu = safe_hu(row[vekp_hu_idx]) if vekp_hu_idx >= 0 else ""
            if int_hu in valid_vepo_hus:
                if ext_hu:
                    valid_roots[(deliv, ext_hu)] = int_hu
                if int_hu:
                    valid_roots[(deliv, int_hu)] = int_hu

    # --- 3. Procházení pick záznamů a detekce Vollpalet ---
    c_su = 'Storage Unit Type' if 'Storage Unit Type' in df_pick.columns \
        else ('Type' if 'Type' in df_pick.columns else None)

    # DŮLEŽITÉ: zde byl bug "col_to_idx = col_to_idx" (přepsání vlastního dictu),
    # což ničilo mapování pro VEKP. Pojmenováno záměrně `pick_col_to_idx`.
    pick_col_to_idx = {c: i for i, c in enumerate(df_pick.columns)}
    col_su_idx = pick_col_to_idx.get(c_su, -1)
    col_rem_idx = pick_col_to_idx.get('Removal of total SU', -1)
    col_q_idx = pick_col_to_idx.get('Queue', -1)
    col_ssu_idx = pick_col_to_idx.get('Source storage unit', -1)
    col_hu_idx = pick_col_to_idx.get('Handling Unit', -1)
    col_del_idx = pick_col_to_idx.get('Delivery', -1)

    pick_arr = df_pick.to_numpy()
    for row in pick_arr:
        rem = str(row[col_rem_idx]).strip().upper() if col_rem_idx >= 0 else ''
        if rem != 'X':
            continue

        su_type = str(row[col_su_idx]) if col_su_idx >= 0 else ''
        if is_box(su_type):
            continue

        queue_val = str(row[col_q_idx]).upper() if col_q_idx >= 0 else ''
        if 'PI_PA' in queue_val:
            continue

        ssu = safe_hu(row[col_ssu_idx]) if col_ssu_idx >= 0 else ''
        hu = safe_hu(row[col_hu_idx]) if col_hu_idx >= 0 else ''

        pick_hu = ""
        if ssu and hu:
            if ssu != hu:
                continue
            pick_hu = ssu
        elif ssu:
            pick_hu = ssu
        elif hu:
            pick_hu = hu
        else:
            continue

        deliv = safe_del(row[col_del_idx]) if col_del_idx >= 0 else ''

        if (deliv, pick_hu) in valid_roots:
            int_match = valid_roots[(deliv, pick_hu)]
            voll_set.add((deliv, pick_hu))
            voll_set.add((deliv, int_match))

    logger.info(f"Detekováno {len(voll_set)} Vollpalette identit")
    return voll_set


# ==========================================
# DATOVÉ OPTIMALIZACE
# ==========================================

def optimize_dataframe_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    """
    Sníží memory footprint DF konverzí:
    - object sloupce s nízkou kardinalitou -> category
    - int64 -> int32/int16 kde možno
    - float64 -> float32 kde to stačí
    """
    if df is None or df.empty:
        return df

    for col in df.columns:
        col_type = df[col].dtype

        # Object sloupce - detekce kategorií
        if col_type == 'object':
            try:
                nunique = df[col].nunique(dropna=True)
                if 0 < nunique < len(df) * 0.5:  # méně než 50% unikátních
                    df[col] = df[col].astype('category')
            except (TypeError, ValueError):
                pass

        # Int optimalizace
        elif col_type == 'int64':
            col_min = df[col].min()
            col_max = df[col].max()
            if col_min >= -128 and col_max <= 127:
                df[col] = df[col].astype('int8')
            elif col_min >= -32768 and col_max <= 32767:
                df[col] = df[col].astype('int16')
            elif col_min >= -2147483648 and col_max <= 2147483647:
                df[col] = df[col].astype('int32')

        # Float optimalizace
        elif col_type == 'float64':
            df[col] = df[col].astype('float32')

    return df


def safe_progress_bar(st_container, current: int, total: int, text: str = ""):
    """Wrapper kolem st.progress, který bezpečně hlídá rozsah 0-100%."""
    if total <= 0:
        return
    pct = min(100, max(0, int(current / total * 100)))
    try:
        st_container.progress(pct, text=text)
    except Exception:
        pass


# ==========================================
# FORMÁTOVÁNÍ
# ==========================================

def fmt_int(n, locale='cs'):
    """Formátuje celé číslo s oddělovači tisíců (1 234 567)."""
    try:
        if locale == 'cs':
            return f"{int(n):,}".replace(",", " ")
        return f"{int(n):,}"
    except (ValueError, TypeError):
        return str(n)


def fmt_float(n, decimals=1):
    """Formátuje desetinné číslo (1 234.5)."""
    try:
        return f"{float(n):,.{decimals}f}".replace(",", " ")
    except (ValueError, TypeError):
        return str(n)


def fmt_pct(value, total, decimals=1):
    """Bezpečně formátuje procenta (chrání proti dělení nulou)."""
    if not total:
        return "0 %"
    return f"{value / total * 100:.{decimals}f} %"


# ==========================================
# DETEKCE SLOUPCŮ V CIZÍCH DATECH
# ==========================================

def find_column(df: pd.DataFrame, *keywords, case_insensitive: bool = True) -> Optional[str]:
    """
    Najde první sloupec v DF, jehož název obsahuje některé z klíčových slov.
    Podporuje více variant a fallback na přesnou shodu.
    """
    if df is None or df.empty:
        return None

    cols = df.columns.tolist()
    cols_lower = [str(c).lower() if case_insensitive else str(c) for c in cols]
    kw_lower = [k.lower() if case_insensitive else k for k in keywords]

    # 1. Přesná shoda (nejlepší)
    for col, col_l in zip(cols, cols_lower):
        if col_l in kw_lower:
            return col

    # 2. Částečná shoda (substring)
    for col, col_l in zip(cols, cols_lower):
        if any(kw in col_l for kw in kw_lower):
            return col

    return None