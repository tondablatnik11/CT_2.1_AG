import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from database import load_from_db
from modules.safe_render import safe_render
from modules.utils import safe_del, safe_hu

try:
    fast_render = st.fragment
except AttributeError:
    fast_render = lambda f: f

# Verze v31 - Přidána robustní detekce chyb + optimalizace
@st.cache_data(show_spinner=False)
def cached_billing_logic_v28(df_pick, df_vekp, df_vepo, df_cats, queue_count_col, voll_set):
    """Hlavní billing logika - plně deterministická, s error safety."""
    billing_df = pd.DataFrame()
    df_hu_details = pd.DataFrame()
    if df_vekp is None or df_vekp.empty:
        return billing_df, df_hu_details

    # ---------------------------------------------------------
    # 1. PŘÍPRAVA A OČIŠTĚNÍ VEKP (S UNIFIKACÍ SLOUPCŮ)
    # ---------------------------------------------------------
    vekp_clean = df_vekp.copy()
    cols_lower = [str(c).lower().strip() for c in vekp_clean.columns]

    hu_int_cols = [c for c, l in zip(vekp_clean.columns, cols_lower) if "internal" in l or "intern" in l or "handling unit" == l or "manipul" in l or "mj" in l]
    hu_ext_cols = [c for c, l in zip(vekp_clean.columns, cols_lower) if "external" in l or "extern" in l]
    del_cols = [c for c, l in zip(vekp_clean.columns, cols_lower) if "delivery" in l or "lieferung" in l or "dodávka" in l or "dodavka" in l or "zakázka" in l or "zakazka" in l]
    parent_cols = [c for c, l in zip(vekp_clean.columns, cols_lower) if "higher-level" in l or "übergeordn" in l or "superordinate" in l or "nadřazen" in l]
    date_cols = [c for c, l in zip(vekp_clean.columns, cols_lower) if "created on" in l or "erfasst am" in l or "datum" in l or "date" in l or "čas" in l or "time" in l]

    if hu_int_cols: vekp_clean['Uni_HU_Int'] = vekp_clean[hu_int_cols].bfill(axis=1).iloc[:, 0]
    else: vekp_clean['Uni_HU_Int'] = vekp_clean.iloc[:, 0]

    if del_cols: vekp_clean['Uni_Del'] = vekp_clean[del_cols].bfill(axis=1).iloc[:, 0]
    else: vekp_clean['Uni_Del'] = np.nan

    vekp_clean = vekp_clean.dropna(subset=["Uni_HU_Int", "Uni_Del"])
    vekp_clean['Clean_Del'] = vekp_clean['Uni_Del'].apply(safe_del)
    vekp_filtered = vekp_clean[vekp_clean['Clean_Del'] != ''].copy() 

    if vekp_filtered.empty: return billing_df, df_hu_details

    vekp_filtered['Uni_HU_Ext'] = vekp_filtered[hu_ext_cols].bfill(axis=1).iloc[:, 0] if hu_ext_cols else vekp_filtered.iloc[:, 1]
    vekp_filtered['Uni_Parent'] = vekp_filtered[parent_cols].bfill(axis=1).iloc[:, 0] if parent_cols else ""

    vekp_filtered['Clean_HU_Int'] = vekp_filtered['Uni_HU_Int'].apply(safe_hu)
    vekp_filtered['Clean_HU_Ext'] = vekp_filtered['Uni_HU_Ext'].apply(safe_hu)
    vekp_filtered['Clean_Parent'] = vekp_filtered['Uni_Parent'].apply(safe_hu)

    if date_cols:
        vekp_filtered['VEKP_Date'] = pd.to_datetime(vekp_filtered[date_cols].bfill(axis=1).iloc[:, 0], errors='coerce')
        vekp_filtered['VEKP_Month'] = vekp_filtered['VEKP_Date'].dt.to_period('M').astype(str).replace('NaT', 'Neznámé')
    else:
        vekp_filtered['VEKP_Month'] = 'Neznámé'

    del_vekp_month = vekp_filtered.groupby('Clean_Del')['VEKP_Month'].first().to_dict()
    int_to_ext = dict(zip(vekp_filtered['Clean_HU_Int'], vekp_filtered['Clean_HU_Ext']))

    # ---------------------------------------------------------
    # 2. PŘÍPRAVA PICK DAT (Pro spárování s TO)
    # ---------------------------------------------------------
    df_pick_billing = pd.DataFrame()
    picked_mats_by_del = {}
    if df_pick is not None and not df_pick.empty:
        df_pick_billing = df_pick.copy()
        df_pick_billing['Clean_Del'] = df_pick_billing['Delivery'].apply(safe_del)
        picked_mats_by_del = df_pick_billing.groupby('Clean_Del')['Material'].apply(lambda x: set(x.astype(str).str.strip())).to_dict()

        if 'Pohyby_Rukou' not in df_pick_billing.columns:
            df_pick_billing['Pohyby_Rukou'] = 0

        def is_row_voll(row):
            d = row['Clean_Del']
            hu = safe_hu(row.get('Handling Unit', ''))
            if not hu: hu = safe_hu(row.get('Source storage unit', ''))
            return (d, hu) in voll_set
        df_pick_billing['Is_Vollpalette'] = df_pick_billing.apply(is_row_voll, axis=1)

    # ---------------------------------------------------------
    # 3. ZÁKLADNÍ KATEGORIE (df_cats -> T031 -> VBPA/KEP)
    # ---------------------------------------------------------
    del_base_map = {}
    if df_cats is not None and not df_cats.empty:
        c_del_cats = next((c for c in df_cats.columns if str(c).strip().lower() in ['lieferung', 'delivery', 'zakázka', 'dodávka', 'zakazka', 'dodavka']), df_cats.columns[0])
        c_kat = next((c for c in df_cats.columns if 'kategorie' in str(c).lower() or 'category' in str(c).lower()), None)
        if c_del_cats and c_kat:
            idx_del = next(i for i, c in enumerate(df_cats.columns) if c == c_del_cats)
            idx_kat = next(i for i, c in enumerate(df_cats.columns) if c == c_kat)
            for row in df_cats.to_numpy():
                d = safe_del(row[idx_del])
                cat_val = str(row[idx_kat]).strip().upper()
                if cat_val in ['N', 'E', 'O', 'OE']:
                    del_base_map[d] = cat_val

    del_vs_map = {}
    df_likp = load_from_db('raw_likp')
    if df_likp is not None and not df_likp.empty:
        c_lief = next((c for c in df_likp.columns if "delivery" in str(c).lower() or "lieferung" in str(c).lower() or "dodávka" in str(c).lower() or "zakázka" in str(c).lower()), df_likp.columns[0])
        c_vs = next((c for c in df_likp.columns if "shipping point" in str(c).lower() or "versandstelle" in str(c).lower() or "receiving pt" in str(c).lower() or "místo" in str(c).lower()), None)
        if c_vs:
            idx_lief = next(i for i, c in enumerate(df_likp.columns) if c == c_lief)
            idx_vs = next(i for i, c in enumerate(df_likp.columns) if c == c_vs)
            for row in df_likp.to_numpy():
                del_vs_map[safe_del(row[idx_lief])] = str(row[idx_vs]).strip().upper()

    kep_carriers = set()
    df_kep = load_from_db('aus_sdshp_am2')
    if df_kep is not None and not df_kep.empty:
        c_sped = next((c for c in df_kep.columns if "Spediteur" in str(c)), df_kep.columns[0])
        c_kep = next((c for c in df_kep.columns if "KEP" in str(c)), None)
        if c_kep:
            idx_sped = next(i for i, c in enumerate(df_kep.columns) if c == c_sped)
            idx_kep = next(i for i, c in enumerate(df_kep.columns) if c == c_kep)
            for row in df_kep.to_numpy():
                if str(row[idx_kep]).strip().upper() == 'X':
                    kep_carriers.add(str(row[idx_sped]).strip().lstrip('0'))

    del_is_kep = {}
    df_vbpa = load_from_db('aus_vbpa')
    if df_vbpa is not None and not df_vbpa.empty:
        c_beleg = next((c for c in df_vbpa.columns if "Vertriebsbeleg" in str(c) or "Delivery" in str(c)), df_vbpa.columns[0])
        c_role = next((c for c in df_vbpa.columns if "Partnerrolle" in str(c) or "Partner Function" in str(c)), None)
        c_kred = next((c for c in df_vbpa.columns if "Kreditor" in str(c) or "Vendor" in str(c)), None)
        c_deb = next((c for c in df_vbpa.columns if "Debitor" in str(c) or "Customer" in str(c)), None)

        if c_role and (c_kred or c_deb):
            idx_beleg = next((i for i, c in enumerate(df_vbpa.columns) if c == c_beleg), -1)
            idx_role = next((i for i, c in enumerate(df_vbpa.columns) if c == c_role), -1)
            idx_kred = next((i for i, c in enumerate(df_vbpa.columns) if c == c_kred), -1) if c_kred else -1
            idx_deb = next((i for i, c in enumerate(df_vbpa.columns) if c == c_deb), -1) if c_deb else -1
            for row in df_vbpa.to_numpy():
                if str(row[idx_role]).strip().upper() in ['SP', 'CR']:
                    val_kred = str(row[idx_kred]) if idx_kred >= 0 else ''
                    val_deb = str(row[idx_deb]) if idx_deb >= 0 else ''
                    sped = (val_kred if val_kred else val_deb).strip().lstrip('0')
                    if sped in kep_carriers:
                        del_is_kep[safe_del(row[idx_beleg])] = True

    all_active_dels = vekp_filtered['Clean_Del'].unique()

    # 💥 ODSTRANĚNÍ NEKONEČNÉHO O(N*M) ÚZKÉHO HRDLA
    df_pick_queues_cache = {}
    if not df_pick_billing.empty:
        for d_pick, grp_pick in df_pick_billing.groupby('Clean_Del'):
            df_pick_queues_cache[d_pick] = set(grp_pick['Queue'].dropna().astype(str).str.upper().unique())

    for d in all_active_dels:
        if d not in del_base_map:
            vs = del_vs_map.get(d, "")
            is_kep = del_is_kep.get(d, False)

            if vs == 'FM20': base = 'N'
            elif vs == 'FM21': base = 'E'
            elif vs == 'FM22': base = 'E'
            elif vs == 'FM23': base = 'N'
            elif vs == 'FM24': base = 'O'
            else: base = 'N' 

            if is_kep:
                if base == 'N': base = 'E'
                if base == 'O': base = 'OE'
            elif not df_pick_billing.empty:
                all_queues = df_pick_queues_cache.get(d, set())
                if all_queues:
                    has_pallet = any(q in ['PI_PL', 'PI_PL_OE', 'FU', 'FU_O', 'FUOE', 'PI_PL_FU'] for q in all_queues)
                    has_parcel = 'PI_PA' in all_queues or 'PI_PA_OE' in all_queues
                    if has_parcel and not has_pallet:
                        if base == 'N': base = 'E'
                        if base == 'O': base = 'OE'

            del_base_map[d] = base

    # ---------------------------------------------------------
    # 4. VEPO STROM A MAPOVÁNÍ MATERIÁLŮ (S UNIFIKACÍ)
    # ---------------------------------------------------------
    vepo_mats = {}
    if df_vepo is not None and not df_vepo.empty:
        vepo_clean = df_vepo.copy()
        v_cols_lower = [str(c).lower().strip() for c in vepo_clean.columns]

        v_hu_cols = [c for c, l in zip(vepo_clean.columns, v_cols_lower) if "internal" in l or "intern" in l or "handling unit" == l or "manipul" in l or "mj" in l]
        v_mat_cols = [c for c, l in zip(vepo_clean.columns, v_cols_lower) if "material" in l or "materiál" in l]

        if v_hu_cols: vepo_clean['Uni_HU'] = vepo_clean[v_hu_cols].bfill(axis=1).iloc[:, 0]
        else: vepo_clean['Uni_HU'] = vepo_clean.iloc[:, 0]

        if v_mat_cols:
            vepo_clean['Uni_Mat'] = vepo_clean[v_mat_cols].bfill(axis=1).iloc[:, 0]

            idx_hu = next((i for i, c in enumerate(vepo_clean.columns) if c == 'Uni_HU'), -1)
            idx_mat = next((i for i, c in enumerate(vepo_clean.columns) if c == 'Uni_Mat'), -1)

            vepo_dropna = vepo_clean.dropna(subset=['Uni_HU', 'Uni_Mat'])
            for row in vepo_dropna.to_numpy():
                h = safe_hu(row[idx_hu])
                m = str(row[idx_mat]).strip()
                if h not in vepo_mats: vepo_mats[h] = set()
                vepo_mats[h].add(m)

    parent_map = dict(zip(vekp_filtered['Clean_HU_Int'], vekp_filtered['Clean_Parent']))
    children_map = {}
    for child, parent in parent_map.items():
        if parent:
            if parent not in children_map: children_map[parent] = []
            children_map[parent].append(child)

    def get_leaves(node, visited=None):
        if visited is None: visited = set()
        if node in visited: return []
        visited.add(node)

        if node not in children_map or not children_map[node]: 
            return [node]

        leaves = []
        for child in children_map[node]:
            leaves.extend(get_leaves(child, visited))
        return leaves

    # ---------------------------------------------------------
    # 5. VYÚČTOVÁNÍ: ZLATÁ LOGIKA (Pouze Kořeny)
    # ---------------------------------------------------------
    del_hu_counts = []
    del_mat_cats = {} 
    hu_details_list = [] 

    root_df = vekp_filtered[vekp_filtered['Clean_Parent'] == '']
    if not root_df.empty:
        idx_ext = next((i for i, c in enumerate(root_df.columns) if c == 'Clean_HU_Ext'), -1)
        idx_int = next((i for i, c in enumerate(root_df.columns) if c == 'Clean_HU_Int'), -1)

    for d, grp in root_df.groupby('Clean_Del'):
        base = del_base_map.get(d, "N")
        valid_picked_mats = picked_mats_by_del.get(d, set())

        for row in grp.to_numpy():
            ext_hu = row[idx_ext]
            root_hu = row[idx_int]

            leaves = get_leaves(root_hu)

            is_voll = False
            if (d, ext_hu) in voll_set or (d, root_hu) in voll_set:
                is_voll = True
            else:
                for leaf in leaves:
                    if (d, leaf) in voll_set or (d, int_to_ext.get(leaf, '')) in voll_set:
                        is_voll = True
                        break

            if is_voll:
                cat = f"{base} Vollpalette"
                if base == "OE": cat = "O Vollpalette" 
                if base == "E": cat = "N Vollpalette"  

                mats = set()
                for leaf in leaves: 
                    mats.update(vepo_mats.get(leaf, set()))

                real_mats = {m for m in mats if m in valid_picked_mats}
                if not real_mats and len(mats) > 0: real_mats = mats

                del_hu_counts.append({'Clean_Del': d, 'Category_Full': cat, 'pocet_hu': 1})
                hu_details_list.append({'Clean_Del': d, 'HU_Ext': ext_hu, 'HU_Int': root_hu, 'Is_Vollpalette': 'ANO', 'Category_Full': cat, 'Materials': ", ".join(real_mats)})

                for m in real_mats:
                    if (d, m) not in del_mat_cats: del_mat_cats[(d, m)] = set()
                    del_mat_cats[(d, m)].add(cat)

            else:
                mats = set()
                for leaf in leaves: 
                    mats.update(vepo_mats.get(leaf, set()))

                real_mats = {m for m in mats if m in valid_picked_mats}
                if not real_mats and len(mats) > 0: real_mats = mats 

                if len(real_mats) > 0:
                    cat = f"{base} Sortenrein" if len(real_mats) == 1 else f"{base} Misch"

                    del_hu_counts.append({'Clean_Del': d, 'Category_Full': cat, 'pocet_hu': 1})
                    hu_details_list.append({'Clean_Del': d, 'HU_Ext': ext_hu, 'HU_Int': root_hu, 'Is_Vollpalette': 'NE', 'Category_Full': cat, 'Materials': ", ".join(real_mats)})

                    for m in real_mats:
                        if (d, m) not in del_mat_cats: del_mat_cats[(d, m)] = set()
                        del_mat_cats[(d, m)].add(cat)

    df_hu_counts = pd.DataFrame(del_hu_counts)
    if not df_hu_counts.empty:
        df_hu_counts = df_hu_counts.groupby(['Clean_Del', 'Category_Full']).size().reset_index(name='pocet_hu')
    else:
        df_hu_counts = pd.DataFrame(columns=['Clean_Del', 'Category_Full', 'pocet_hu'])

    df_hu_details = pd.DataFrame(hu_details_list)

    # ---------------------------------------------------------
    # 6. SPÁROVÁNÍ FYZICKÝCH PICKŮ (TO) NA VÝSLEDNÉ KATEGORIE
    # ---------------------------------------------------------
    if not df_pick_billing.empty:
        non_voll_mats = df_pick_billing[~df_pick_billing['Is_Vollpalette']].groupby('Clean_Del')['Material'].nunique().to_dict()

        def get_full_category(row):
            d = row['Clean_Del']
            base = del_base_map.get(d, "N")

            if row['Is_Vollpalette']:
                if base == "OE": return "O Vollpalette"
                if base == "E": return "N Vollpalette"
                return f"{base} Vollpalette"

            mat = str(row.get('Material', '')).strip()
            cats = del_mat_cats.get((d, mat), set())
            valid_cats = {c for c in cats if "Vollpalette" not in c}

            if len(valid_cats) == 1: return list(valid_cats)[0]
            elif len(valid_cats) > 1: return f"{base} Misch" 
            else:
                mats_in_del = non_voll_mats.get(d, 1)
                return f"{base} Misch" if mats_in_del > 1 else f"{base} Sortenrein"

        df_pick_billing['Category_Full'] = df_pick_billing.apply(get_full_category, axis=1)

        pick_agg = df_pick_billing.groupby(['Clean_Del', 'Category_Full']).agg(
            pocet_to=(queue_count_col, "nunique"),
            pohyby_celkem=("Pohyby_Rukou", "sum"),
            pocet_lokaci=("Source Storage Bin", "nunique"),
            pocet_mat=("Material", "nunique") 
        ).reset_index()
    else:
        pick_agg = pd.DataFrame(columns=['Clean_Del', 'Category_Full', 'pocet_to', 'pohyby_celkem', 'pocet_lokaci', 'pocet_mat'])

    # ---------------------------------------------------------
    # 7. AGREGACE DLE ZAKÁZKY
    # ---------------------------------------------------------
    billing_df = pd.merge(df_hu_counts, pick_agg, on=['Clean_Del', 'Category_Full'], how='outer')

    billing_df['Delivery'] = billing_df['Clean_Del']
    billing_df['Clean_Del_Merge'] = billing_df['Clean_Del']

    if not df_pick_billing.empty:
        del_metadata = df_pick_billing.groupby('Clean_Del').agg(
            Month=('Month', 'first'),
            hlavni_fronta=("Queue", lambda x: x.mode()[0] if not x.empty else "")
        ).to_dict('index')
        billing_df['Month'] = billing_df['Clean_Del'].apply(
            lambda d: del_vekp_month.get(d, 'Neznámé') if del_vekp_month.get(d, 'Neznámé') != 'Neznámé' 
            else del_metadata.get(d, {}).get('Month', 'Neznámé')
        )
        billing_df['hlavni_fronta'] = billing_df.apply(lambda r: del_metadata.get(r['Clean_Del'], {}).get('hlavni_fronta', ''), axis=1)
    else:
        billing_df['Month'] = billing_df['Clean_Del'].map(del_vekp_month).fillna('Neznámé')
        billing_df['hlavni_fronta'] = ''

    for col in ['pocet_to', 'pohyby_celkem', 'pocet_lokaci', 'pocet_hu', 'pocet_mat']:
        billing_df[col] = billing_df[col].fillna(0).astype(int)

    billing_df["Bilance"] = (billing_df["pocet_to"] - billing_df["pocet_hu"]).astype(int)
    billing_df["TO_navic"] = billing_df["Bilance"].clip(lower=0)

    return billing_df, df_hu_details

@fast_render
def render_reliability_report(df_pick, df_vekp, df_vepo):
    if df_vekp is None or df_vekp.empty: return

    st.markdown("<div class='section-header'><h3>🛡️ Spolehlivost dat a chybějící záznamy</h3></div>", unsafe_allow_html=True)

    df_vekp_clean = df_vekp.copy()
    cols_lower = [str(c).lower().strip() for c in df_vekp_clean.columns]

    c_del = [c for c, l in zip(df_vekp_clean.columns, cols_lower) if "delivery" in l or "lieferung" in l or "dodávka" in l or "dodavka" in l or "zakázka" in l or "zakazka" in l]
    c_hu = [c for c, l in zip(df_vekp_clean.columns, cols_lower) if "internal" in l or "intern" in l or "handling unit" == l or "manipul" in l or "mj" in l]

    df_vekp_clean['Clean_Del'] = df_vekp_clean[c_del].bfill(axis=1).iloc[:, 0].apply(safe_del) if c_del else ""
    df_vekp_clean['Clean_HU'] = df_vekp_clean[c_hu].bfill(axis=1).iloc[:, 0].apply(safe_hu) if c_hu else ""

    all_dels = df_vekp_clean[df_vekp_clean['Clean_Del'] != '']['Clean_Del'].unique()
    pick_dels = set(df_pick['Delivery'].apply(safe_del)) if df_pick is not None else set()

    likp_dels = set()
    df_likp = load_from_db('raw_likp')
    if df_likp is not None and not df_likp.empty:
        l_cols_lower = [str(c).lower().strip() for c in df_likp.columns]
        c_likp_del = next((c for c, l in zip(df_likp.columns, l_cols_lower) if "delivery" in l or "lieferung" in l or "dodávka" in l or "zakázka" in l), df_likp.columns[0])
        likp_dels = set(df_likp[c_likp_del].apply(safe_del))

    vepo_hus = set()
    if df_vepo is not None and not df_vepo.empty:
        v_cols_lower = [str(c).lower().strip() for c in df_vepo.columns]
        c_vepo_hu = [c for c, l in zip(df_vepo.columns, v_cols_lower) if "internal" in l or "intern" in l or "handling unit" == l or "manipul" in l or "mj" in l]
        if c_vepo_hu:
            vepo_hus = set(df_vepo[c_vepo_hu].bfill(axis=1).iloc[:, 0].apply(safe_hu))

    del_hu_map = df_vekp_clean.groupby('Clean_Del')['Clean_HU'].apply(set).to_dict()

    missing_data = []
    for d in all_dels:
        has_pick = d in pick_dels
        has_likp = d in likp_dels
        d_hus = del_hu_map.get(d, set())
        has_vepo = len(d_hus.intersection(vepo_hus)) > 0

        if not (has_pick and has_likp and has_vepo):
            missing_data.append({
                'Zakázka (Delivery)': d,
                'Pick Report (TO)': '✅ OK' if has_pick else '❌ Chybí',
                'LIKP (Brány)': '✅ OK' if has_likp else '❌ Chybí',
                'VEPO (Materiály)': '✅ OK' if has_vepo else '❌ Chybí (Prázdné)'
            })

    total_dels = len(all_dels)
    perfect_dels = total_dels - len(missing_data)
    reliability_pct = (perfect_dels / total_dels * 100) if total_dels > 0 else 0

    col1, col2 = st.columns([1, 3])
    with col1:
        st.metric("Spolehlivost datových podkladů", f"{reliability_pct:.1f} %", help="Procento fakturovaných zakázek, které mají kompletní záznamy ve všech nahraných tabulkách.")
    with col2:
        if missing_data:
            with st.expander(f"⚠️ Zobrazit zakázky s chybějícími daty ({len(missing_data)} zakázek)", expanded=False):
                st.dataframe(pd.DataFrame(missing_data), hide_index=True, width="stretch")
        else:
            st.success("Perfektní! Všechny fakturované zakázky mají svá data kompletní.")
    st.divider()


@safe_render(fallback_message="⚠️ Chyba při vykreslování Fakturace")
def render_billing(df_pick, df_vekp, df_vepo, df_cats, queue_count_col, aus_data=None):
    """Hlavní renderer Billing - obalený v bezpečnostních kontrolách."""
    def _t(cs, en): return en if st.session_state.get('lang', 'cs') == 'en' else cs

    st.markdown(f"<div class='section-header'><h3>💰 {_t('Korelace mezi Pickováním a Účtováním', 'Correlation Between Picking and Billing')}</h3><p>{_t('Zákazník platí podle počtu výsledných balících jednotek (HU). Zde vidíte náročnost vytvoření těchto zpoplatněných jednotek napříč fakturačními kategoriemi.', 'The customer pays based on the number of billed HUs. Here you can see the effort required to create these billed units across categories.')}</p></div>", unsafe_allow_html=True)

    # 🚨 BEZPEČNOSTNÍ DIAGNOSTIKA VEKP
    if df_vekp is not None and not df_vekp.empty:
        cols_lower = [str(c).lower().strip() for c in df_vekp.columns]
        del_cols = [c for c, l in zip(df_vekp.columns, cols_lower) if "delivery" in l or "lieferung" in l or "dodávka" in l or "dodavka" in l or "zakázka" in l or "zakazka" in l]
        if not del_cols:
            st.error(f"🚨 **Kritická chyba: Aplikace nedokáže ve vašem VEKP souboru najít sloupec se zakázkou.** \n\nZkuste upravit export ze SAPu, nebo se mi ozvěte. \n\n**Názvy sloupců, které máte ve VEKP teď:** `{list(df_vekp.columns)}`")
            return pd.DataFrame()

    # 🚨 BEZPEČNOSTNÍ DIAGNOSTIKA VEPO
    if df_vepo is not None and not df_vepo.empty:
        cols_lower_v = [str(c).lower().strip() for c in df_vepo.columns]
        mat_cols = [c for c, l in zip(df_vepo.columns, cols_lower_v) if "material" in l or "materiál" in l]
        if not mat_cols:
            st.error(f"🚨 **Kritická chyba: Aplikace nedokáže ve vašem VEPO souboru najít sloupec pro Materiál.** \n\n**Názvy sloupců, které máte ve VEPO teď:** `{list(df_vepo.columns)}`")
            return pd.DataFrame()

    with st.spinner("🧠 Analyzuji SAP data (VEKP, VEPO)..."):
        try:
            render_reliability_report(df_pick, df_vekp, df_vepo)
        except Exception as e:
            st.warning(f"⚠️ Nedokončena analýza spolehlivosti: {e}")

        voll_set = st.session_state.get('voll_set', set()) or set()

        # Bezpečné volání hlavní logiky s fallbackem
        try:
            billing_df, df_hu_details = cached_billing_logic_v28(
                df_pick, df_vekp, df_vepo, df_cats, queue_count_col, voll_set
            )
        except Exception as e:
            st.error(f"❌ Kritická chyba v Billing Logic: {e}")
            import traceback
            with st.expander("🔧 Detaily"):
                st.code(traceback.format_exc(), language="python")
            return pd.DataFrame()

        # ===============================================
        # APLIKACE FILTRU MĚSÍCE (aby vše sedělo s menu)
        # ===============================================
        if 'Month' in df_pick.columns:
            pick_months = [m for m in df_pick['Month'].unique() if m != 'Neznámé']
            if len(pick_months) >= 1:
                valid_dels = set(df_pick['Delivery'].apply(safe_del).dropna().unique())
                billing_df = billing_df[(billing_df['Month'].isin(pick_months)) | (billing_df['Clean_Del'].isin(valid_dels))].copy()
                df_hu_details = df_hu_details[df_hu_details['Clean_Del'].isin(billing_df['Clean_Del'])].copy()

        st.session_state['billing_df'] = billing_df 
        st.session_state['debug_hu_details'] = df_hu_details

    if load_from_db('raw_likp') is None:
        st.warning("⚠️ **Info:** Pro 100% přesné oddělení N a O zakázek doporučujeme v Admin Zóně nahrát LIKP report.")

    if not billing_df.empty:
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            with st.container(border=True): st.metric(_t("Zakázek celkem", "Total Orders"), f"{billing_df['Delivery'].nunique():,}")
        with c2:
            with st.container(border=True): st.metric(_t("Fakturované palety/krabice (HU)", "Billed Pallets/Boxes (HU)"), f"{int(billing_df['pocet_hu'].sum()):,}")
        with c3:
            with st.container(border=True): st.metric(_t("Fyzických Pick TO", "Physical Pick TOs"), f"{int(billing_df['pocet_to'].sum()):,}")
        with c4:
            net_diff = int(billing_df['Bilance'].sum())
            loss_total = int(billing_df['TO_navic'].sum())
            profit_total = loss_total - net_diff
            with st.container(border=True): 
                st.metric(
                    _t("Celková čistá bilance (TO - HU)", "Total Net Balance (TO - HU)"), 
                    f"{net_diff:,}", 
                    help=_t(f"Kladné číslo = Prodělek. Ztráta z nevýhodných zakázek byla {loss_total:,} picků, ale efektivní zakázky vám uspořily {profit_total:,} picků.", f"Positive number = Loss. Loss from inefficient orders was {loss_total:,} picks, but efficient orders saved {profit_total:,} picks.")
                )

        st.divider()
        col_t1, col_t2 = st.columns([1.2, 1])
        with col_t1:
            st.markdown(f"**{_t('Souhrn podle kategorií zabalených HU (Zisky a Ztráty)', 'Summary by Packed HU Categories (Profit & Loss)')}**")

            cat_sum = billing_df.groupby("Category_Full").agg(
                pocet_casti=("Delivery", "count"), 
                pocet_to=("pocet_to", "sum"), 
                pocet_hu=("pocet_hu", "sum"), 
                pocet_mat=("pocet_mat", "sum"), 
                pocet_lok=("pocet_lokaci", "sum"), 
                poh=("pohyby_celkem", "sum"), 
                bilance=("Bilance", "sum"), 
                to_navic=("TO_navic", "sum")
            ).reset_index()

            cat_sum["prum_poh"] = np.where(cat_sum["pocet_lok"] > 0, cat_sum["poh"] / cat_sum["pocet_lok"], 0)

            disp = cat_sum[["Category_Full", "pocet_casti", "pocet_to", "pocet_hu", "pocet_mat", "prum_poh", "bilance", "to_navic"]].copy()
            disp.columns = [
                _t("Kategorie HU", "HU Category"), 
                _t("Části zakázek", "Order Parts"), 
                _t("Počet TO", "Total TO"), 
                _t("Zúčtované HU", "Billed HU"), 
                _t("Položky (Items)", "Items"), 
                _t("Prům. pohybů na lokaci", "Avg Moves/Location"), 
                _t("Čistá bilance (Zisk/Ztráta)", "Net Balance (Profit/Loss)"), 
                _t("Hrubá ztráta (TO navíc)", "Gross Loss (Extra TO)")
            ]

            st.dataframe(disp.style.format({_t("Prům. pohybů na lokaci", "Avg Moves/Location"): "{:.1f}"}), width="stretch", hide_index=True)

            st.markdown(f"<br>**🔍 {_t('Detailní seznam částí zakázek podle kategorie:', 'Detailed Order Parts List by Category:')}**", unsafe_allow_html=True)
            cat_opts = [_t("— Vyberte kategorii pro detail —", "— Select Category for Detail —")] + sorted(billing_df["Category_Full"].dropna().unique().tolist())
            sel_detail_cat = st.selectbox("Vyberte", options=cat_opts, label_visibility="collapsed")

            if sel_detail_cat != _t("— Vyberte kategorii pro detail —", "— Select Category for Detail —"):
                det_df = billing_df[billing_df["Category_Full"] == sel_detail_cat].copy()
                det_df["prum_poh_lok"] = np.where(det_df["pocet_lokaci"] > 0, det_df["pohyby_celkem"] / det_df["pocet_lokaci"], 0)
                det_df = det_df.sort_values(by="Bilance", ascending=False)

                disp_det = det_df[["Delivery", "pocet_to", "pocet_hu", "pocet_mat", "prum_poh_lok", "Bilance"]].copy()
                disp_det.columns = [
                    _t("Zakázka (Delivery)", "Order (Delivery)"), 
                    _t("Počet TO", "Total TO"), 
                    _t("Zabalené HU", "Packed HU"), 
                    _t("Položky (Items)", "Items"), 
                    _t("Prům. pohybů na lok.", "Avg Moves/Loc"), 
                    _t("Čistá bilance (TO navíc)", "Net Balance (Extra TO)")
                ]

                def color_bilance_simple(val):
                    try:
                        if val > 0: return 'color: #ef4444; font-weight: bold'
                        elif val < 0: return 'color: #10b981; font-weight: bold'
                    except: pass
                    return ''

                try:
                    styled_det = disp_det.style.format({_t("Prům. pohybů na lok.", "Avg Moves/Loc"): "{:.1f}"}).map(color_bilance_simple, subset=[_t("Čistá bilance (TO navíc)", "Net Balance (Extra TO)")])
                except AttributeError:
                    styled_det = disp_det.style.format({_t("Prům. pohybů na lok.", "Avg Moves/Loc"): "{:.1f}"}).applymap(color_bilance_simple, subset=[_t("Čistá bilance (TO navíc)", "Net Balance (Extra TO)")])

                st.dataframe(styled_det, width="stretch", hide_index=True)

        with col_t2:
            st.markdown(f"**{_t('Trend v čase (Měsíce)', 'Trend over Time (Months)')}**")
            @fast_render
            def interactive_chart():
                cat_options = [_t("Všechny kategorie", "All Categories")] + sorted(billing_df["Category_Full"].dropna().unique().tolist())
                selected_cat = st.selectbox(_t("Vyberte kategorii pro graf:", "Select category for chart:"), options=cat_options, label_visibility="collapsed", key="billing_chart_cat")

                if selected_cat == _t("Všechny kategorie", "All Categories"):
                    plot_df = billing_df.copy()
                else:
                    plot_df = billing_df[billing_df["Category_Full"] == selected_cat].copy()

                tr_df = plot_df.groupby("Month").agg(
                    to_sum=("pocet_to", "sum"), 
                    hu_sum=("pocet_hu", "sum"), 
                    mat_sum=("pocet_mat", "sum"), # <-- Přidáno: Položky (Items)
                    poh=("pohyby_celkem", "sum"), 
                    lok=("pocet_lokaci", "sum")
                ).reset_index()

                tr_df['prum_poh'] = np.where(tr_df['lok']>0, tr_df['poh']/tr_df['lok'], 0)

                fig = go.Figure()
                fig.add_trace(go.Bar(
                    x=tr_df['Month'], 
                    y=tr_df['to_sum'], 
                    name=_t('Počet TO', 'Total TOs'), 
                    marker_color='#38bdf8', 
                    text=tr_df['to_sum'], 
                    textposition='auto'
                ))
                fig.add_trace(go.Bar(
                    x=tr_df['Month'], 
                    y=tr_df['hu_sum'], 
                    name=_t('Počet HU', 'Total HUs'), 
                    marker_color='#818cf8', 
                    text=tr_df['hu_sum'], 
                    textposition='auto'
                ))
                fig.add_trace(go.Bar(
                    x=tr_df['Month'], 
                    y=tr_df['mat_sum'], 
                    name=_t('Položky (Items)', 'Total Items'), 
                    marker_color='#f59e0b', # <-- Přidáno: Sloupec oranžové barvy
                    text=tr_df['mat_sum'], 
                    textposition='auto'
                ))
                fig.add_trace(go.Scatter(
                    x=tr_df['Month'], 
                    y=tr_df['prum_poh'], 
                    name=_t('Pohyby na lokaci', 'Moves per Loc'), 
                    yaxis='y2', 
                    mode='lines+markers+text', 
                    text=tr_df['prum_poh'].round(1), 
                    textposition='top center', 
                    textfont=dict(color='#f43f5e'), 
                    line=dict(color='#f43f5e', width=3)
                ))

                fig.update_layout(
                    yaxis2=dict(title=_t("Pohyby", "Moves"), side="right", overlaying="y", showgrid=False), 
                    plot_bgcolor="rgba(0,0,0,0)", 
                    paper_bgcolor="rgba(0,0,0,0)", 
                    margin=dict(l=0, r=0, t=30, b=0), 
                    legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="left", x=0)
                )
                st.plotly_chart(fig, width="stretch")

            interactive_chart()

        st.divider()
        st.markdown(f"### 💎 {_t('Analýza efektivity a ziskovosti (Master Data)', 'Efficiency & Profitability Analysis (Master Data)')}")
        st.markdown(_t("Tato tabulka odhaluje skutečnou hloubku finančních úniků z konsolidace a fyzickou náročnost na 1 fakturační jednotku.", "This table reveals the true depth of financial leaks from consolidation and the physical effort per 1 billed unit."))

        with st.expander(f"📖 {_t('Vysvětlení výpočtů ve sloupcích', 'Explanation of Column Calculations')}"):
            st.markdown(_t("""
            * **Index konsolidace (TO/HU):** Kolik pickovacích úkolů (TO) musí skladník průměrně udělat na vytvoření 1 vyfakturované jednotky (HU). Ideál je 1.0. Čím vyšší číslo, tím více TO se "slévá" a ztrácí.
            * **Fyzické pohyby na 1 Billed HU:** Kolik reálných pohybů rukou (přeložení kusů) stojí firmu vytvoření 1 vyfakturované jednotky.
            * **1:1 (Ideál):** Počet zakázek, kde se 1 vychystané TO rovná přesně 1 vyfakturované HU (žádná ztráta z konsolidace).
            * **Více TO (Prodělaly) / Ztráta (ks TO):** Zakázky, u kterých se více picků spojilo do menšího počtu palet/krabic. Sloupec Ztráta ukazuje *přesný počet TO*, které jste fyzicky odchodili, ale zákazník je nezaplatil.
            * **Více HU (Vydělaly) / Zisk (ks HU):** Zakázky, u kterých se 1 pick rozpadl do multiple menších balení. Sloupec Zisk ukazuje, kolik HU jste vyfakturovali *navíc*.
            * **Čistá bilance (HU - TO):** Celkový výsledek kategorie v kusech. Zelená = zisk. Červená = ztráta.
            """, """
            * **Consolidation Index (TO/HU):** How many pick tasks (TO) a worker averages to create 1 billed unit (HU). Ideal is 1.0. Higher = more TOs are consolidated and "lost".
            * **Physical Moves per Billed HU:** How many real hand moves it costs to create 1 billed unit.
            * **1:1 (Ideal):** Orders where 1 picked TO equals exactly 1 billed HU (no consolidation loss).
            * **More TO (Loss) / Loss (pcs TO):** Orders where multiple picks merged into fewer units. The Loss column shows *exact TO count* physically walked but unpaid.
            * **More HU (Profit) / Profit (pcs HU):** Orders where 1 pick split into multiple billed units. The Profit column shows *extra* billed HUs.
            * **Net Balance (HU - TO):** Total category result. Green = profit. Red = loss.
            """))

        billing_df['is_1_to_1'] = (billing_df['pocet_to'] == billing_df['pocet_hu']).astype(int)
        billing_df['is_more_to'] = (billing_df['pocet_to'] > billing_df['pocet_hu']).astype(int)
        billing_df['is_more_hu'] = (billing_df['pocet_to'] < billing_df['pocet_hu']).astype(int)

        billing_df['ztrata_to'] = np.where(billing_df['is_more_to'], billing_df['pocet_to'] - billing_df['pocet_hu'], 0)
        billing_df['zisk_hu'] = np.where(billing_df['is_more_hu'], billing_df['pocet_hu'] - billing_df['pocet_to'], 0)

        ratio_table = billing_df.groupby('Category_Full').agg(
            celkem=('Delivery', 'count'), 
            to_celkem=('pocet_to', 'sum'), 
            hu_celkem=('pocet_hu', 'sum'), 
            mat_celkem=('pocet_mat', 'sum'), 
            pohyby_celkem=('pohyby_celkem', 'sum'), 
            count_1_1=('is_1_to_1', 'sum'), 
            count_more_to=('is_more_to', 'sum'), 
            ztrata_to=('ztrata_to', 'sum'), 
            count_more_hu=('is_more_hu', 'sum'), 
            zisk_hu=('zisk_hu', 'sum')
        ).reset_index()

        def format_pct(count, total):
            if total == 0: return "0 (0.0%)"
            return f"{int(count)} ({(count/total*100):.1f}%)"

        ratio_table['1:1 (Ideál)'] = ratio_table.apply(lambda r: format_pct(r['count_1_1'], r['celkem']), axis=1)
        ratio_table['Více TO (Počet)'] = ratio_table.apply(lambda r: format_pct(r['count_more_to'], r['celkem']), axis=1)
        ratio_table['Více HU (Počet)'] = ratio_table.apply(lambda r: format_pct(r['count_more_hu'], r['celkem']), axis=1)

        ratio_table['Index (TO na 1 HU)'] = np.where(ratio_table['hu_celkem'] > 0, ratio_table['to_celkem'] / ratio_table['hu_celkem'], 0)
        ratio_table['Pohyby na 1 HU'] = np.where(ratio_table['hu_celkem'] > 0, ratio_table['pohyby_celkem'] / ratio_table['hu_celkem'], 0)
        ratio_table['Čistá bilance'] = ratio_table['hu_celkem'] - ratio_table['to_celkem'] 

        disp_ratio = ratio_table[[
            'Category_Full', 'celkem', 'to_celkem', 'hu_celkem', 'mat_celkem', 
            'Index (TO na 1 HU)', 'Pohyby na 1 HU', 
            '1:1 (Ideál)', 'Více TO (Počet)', 'ztrata_to', 
            'Více HU (Počet)', 'zisk_hu', 'Čistá bilance'
        ]].copy()

        disp_ratio.columns = [
            _t("Kategorie HU", "HU Category"), 
            _t("Částí zakázek", "Order Parts"), 
            _t("TO Celkem", "Total TO"), 
            _t("HU Celkem", "Total HU"), 
            _t("Položky (Items) Celkem", "Total Items"), 
            _t("Index konsolidace (TO/HU)", "Consolidation Index (TO/HU)"), 
            _t("Fyzické pohyby na 1 Billed HU", "Physical Moves / Billed HU"), 
            _t("1:1 (Ideál)", "1:1 (Ideal)"), 
            _t("Více TO (Prodělaly)", "More TO (Loss)"), 
            _t("Ztráta (ks TO)", "Loss (pcs TO)"), 
            _t("Více HU (Vydělaly)", "More HU (Profit)"), 
            _t("Zisk (ks HU)", "Profit (pcs HU)"), 
            _t("Čistá bilance (HU - TO)", "Net Balance (HU - TO)")
        ]

        def style_master_table(val):
            try:
                if isinstance(val, (int, float)) and val > 0 and 'Ztráta' not in str(val) and 'Loss' not in str(val):
                    return 'color: #10b981; font-weight: bold'
                elif isinstance(val, (int, float)) and val < 0:
                    return 'color: #ef4444; font-weight: bold'
            except: pass
            return ''

        try:
            styled_master = disp_ratio.style.format({
                _t("Index konsolidace (TO/HU)", "Consolidation Index (TO/HU)"): "{:.2f} TO", 
                _t("Fyzické pohyby na 1 Billed HU", "Physical Moves / Billed HU"): "{:.1f} " + _t("pohybů", "moves"),
                _t("Ztráta (ks TO)", "Loss (pcs TO)"): "- {}",
                _t("Zisk (ks HU)", "Profit (pcs HU)"): "+ {}"
            }).map(style_master_table, subset=[_t("Čistá bilance (HU - TO)", "Net Balance (HU - TO)")])
        except AttributeError:
            styled_master = disp_ratio.style.format({
                _t("Index konsolidace (TO/HU)", "Consolidation Index (TO/HU)"): "{:.2f} TO", 
                _t("Fyzické pohyby na 1 Billed HU", "Physical Moves / Billed HU"): "{:.1f} " + _t("pohybů", "moves"),
                _t("Ztráta (ks TO)", "Loss (pcs TO)"): "- {}",
                _t("Zisk (ks HU)", "Profit (pcs HU)"): "+ {}"
            }).applymap(style_master_table, subset=[_t("Čistá bilance (HU - TO)", "Net Balance (HU - TO)")])

        st.dataframe(styled_master, width="stretch", hide_index=True)

        st.markdown(f"<br>**{_t('Trend typů zakázek (Měsíce)', 'Trend of Order Types (Months)')}**", unsafe_allow_html=True)

        all_trend_cats = sorted(billing_df['Category_Full'].dropna().unique().tolist())
        sel_trend_cats = st.multiselect(
            _t("Vyberte kategorie pro zobrazení trendu:", "Select categories for trend chart:"), 
            options=all_trend_cats, 
            default=all_trend_cats, 
            key="trend_ratio_cats"
        )

        if sel_trend_cats:
            trend_df_filtered = billing_df[billing_df['Category_Full'].isin(sel_trend_cats)].copy()
            trend_ratio = trend_df_filtered.groupby('Month').agg(
                count_1_1=('is_1_to_1', 'sum'), 
                count_more_to=('is_more_to', 'sum'), 
                count_more_hu=('is_more_hu', 'sum')
            ).reset_index()

            trend_ratio['total'] = trend_ratio['count_1_1'] + trend_ratio['count_more_to'] + trend_ratio['count_more_hu']
            trend_ratio['pct_1_1'] = np.where(trend_ratio['total'] > 0, trend_ratio['count_1_1'] / trend_ratio['total'] * 100, 0)
            trend_ratio['pct_more_to'] = np.where(trend_ratio['total'] > 0, trend_ratio['count_more_to'] / trend_ratio['total'] * 100, 0)
            trend_ratio['pct_more_hu'] = np.where(trend_ratio['total'] > 0, trend_ratio['count_more_hu'] / trend_ratio['total'] * 100, 0)

            fig_r = go.Figure()
            fig_r.add_trace(go.Bar(
                x=trend_ratio['Month'], 
                y=trend_ratio['count_1_1'], 
                name=_t('1:1 (Kusy)', '1:1 (Pcs)'), 
                marker_color='rgba(16, 185, 129, 0.5)', 
                text=trend_ratio['count_1_1'], 
                textposition='inside', 
                yaxis='y'
            ))
            fig_r.add_trace(go.Bar(
                x=trend_ratio['Month'], 
                y=trend_ratio['count_more_hu'], 
                name=_t('Více HU (Kusy)', 'More HU (Pcs)'), 
                marker_color='rgba(59, 130, 246, 0.5)', 
                text=trend_ratio['count_more_hu'], 
                textposition='inside', 
                yaxis='y'
            ))
            fig_r.add_trace(go.Bar(
                x=trend_ratio['Month'], 
                y=trend_ratio['count_more_to'], 
                name=_t('Více TO (Kusy)', 'More TO (Pcs)'), 
                marker_color='rgba(239, 68, 68, 0.5)', 
                text=trend_ratio['count_more_to'], 
                textposition='inside', 
                yaxis='y'
            ))

            fig_r.add_trace(go.Scatter(
                x=trend_ratio['Month'], 
                y=trend_ratio['pct_1_1'], 
                name=_t('1:1 (%)', '1:1 (%)'), 
                mode='lines+markers+text', 
                text=trend_ratio['pct_1_1'].round(1).astype(str) + '%', 
                textposition='top center', 
                marker_color='#10b981', 
                line=dict(width=3), 
                yaxis='y2'
            ))
            fig_r.add_trace(go.Scatter(
                x=trend_ratio['Month'], 
                y=trend_ratio['pct_more_hu'], 
                name=_t('Více HU (%)', 'More HU (%)'), 
                mode='lines+markers+text', 
                text=trend_ratio['pct_more_hu'].round(1).astype(str) + '%', 
                textposition='top center', 
                marker_color='#3b82f6', 
                line=dict(width=3), 
                yaxis='y2'
            ))
            fig_r.add_trace(go.Scatter(
                x=trend_ratio['Month'], 
                y=trend_ratio['pct_more_to'], 
                name=_t('Více TO (%)', 'More TO (%)'), 
                mode='lines+markers+text', 
                text=trend_ratio['pct_more_to'].round(1).astype(str) + '%', 
                textposition='bottom center', 
                marker_color='#ef4444', 
                line=dict(width=3), 
                yaxis='y2'
            ))

            fig_r.update_layout(
                barmode='stack', 
                plot_bgcolor="rgba(0,0,0,0)", 
                paper_bgcolor="rgba(0,0,0,0)", 
                margin=dict(l=0, r=0, t=30, b=0), 
                legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="left", x=0),
                yaxis=dict(title=_t("Celkem částí zakázek", "Total Order Parts")),
                yaxis2=dict(title=_t("Podíl zakázek (%)", "Order Share (%)"), side="right", overlaying="y", showgrid=False, range=[0, 110])
            )
            st.plotly_chart(fig_r, width="stretch")
        else: 
            st.info(_t("Zvolte alespoň jednu kategorii pro zobrazení grafu.", "Select at least one category to display the chart."))

        st.divider()
        st.markdown(f"### ⚠️ {_t('Žebříček neefektivity z konsolidace (Práce zdarma)', 'Inefficiency Ranking from Consolidation (Free Labor)')}")
        imb_df = billing_df[billing_df['TO_navic'] > 0].sort_values("TO_navic", ascending=False).head(50)

        if not imb_df.empty:
            imb_disp = imb_df[['Delivery', 'Category_Full', 'pocet_to', 'pohyby_celkem', 'pocet_hu', 'pocet_mat', 'TO_navic']].copy()
            imb_disp.columns = [
                _t("Delivery", "Delivery"), 
                _t("Kategorie", "Category"), 
                _t("Pick TO celkem", "Total Pick TOs"), 
                _t("Pohyby rukou", "Hand Moves"), 
                _t("Účtované HU", "Billed HU"), 
                _t("Položky (Items)", "Items"), 
                _t("Prodělek (Rozdíl)", "Loss (Difference)")
            ]
            st.dataframe(imb_disp, width="stretch", hide_index=True)
        else: 
            st.success(_t("Žádné zakázky s prodělkem nenalezeny!", "No loss-making orders found!"))

    return billing_df
