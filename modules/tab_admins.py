import streamlit as st
import pandas as pd
import numpy as np
import re
import datetime
import plotly.express as px
from modules.utils import safe_del, safe_hu
from modules.safe_render import ErrorBoundary, safe_render

try:
    fast_render = st.fragment
except AttributeError:
    fast_render = lambda f: f

@safe_render(fallback_message="⚠️ Chyba při vykreslování Admin Tools")
def render_admins(df_vekp, df_likp):
    st.markdown("<div class='section-header'><h3>🛠️ Admin Tools & Tracking</h3><p>Nástroje pro nákupčí obalů, expedici a sledování zásilek.</p></div>", unsafe_allow_html=True)

    # ==========================================
    # SEKCE 1: TRACKING ZÁSILEK (UPS / FEDEX)
    # ==========================================
    st.markdown("#### 🌍 Sledování zásilek (Tracking)")
    st.write("Zadejte sledovací číslo (např. z Bill of Lading) pro vyhledání příslušné zakázky a zobrazení odkazu na sledování.")
    
    if df_likp is not None and not df_likp.empty:
        # Najdeme sloupec se zakázkou
        c_del_likp = next((c for c in df_likp.columns if "DELIVERY" in str(c).upper() or "LIEFERUNG" in str(c).upper() or "DODÁVKA" in str(c).upper() or "ZAKÁZKA" in str(c).upper()), None)
        
        if not c_del_likp and len(df_likp.columns) > 0:
            c_del_likp = df_likp.columns[0] # Fallback na první sloupec, pokud se nenašel název

        track_input = st.text_input("🔍 Hledat podle sledovacího čísla (Tracking ID):", placeholder="Např. 1ZR1J... nebo 8832...").strip()
        
        if track_input:
            track_clean = track_input.upper().replace(" ", "").lstrip("0")
            
            # 💡 CHYTRÉ HLEDÁNÍ: Prohledáme ÚPLNĚ VŠECHNY sloupce v LIKP bez ohledu na formátování.
            mask = df_likp.astype(str).apply(lambda col: col.str.upper().str.replace(" ", "").str.replace(r"\.0$", "", regex=True).str.lstrip("0").str.contains(track_clean, na=False, regex=False))
            match_df = df_likp[mask.any(axis=1)]
            
            if not match_df.empty:
                for _, row in match_df.iterrows():
                    del_id = safe_del(row[c_del_likp])
                    st.success(f"✅ Nalezeno! Zásilka **{track_input}** patří k zakázce (Delivery): **{del_id}**")
                    
                    # Chytrá detekce dopravce z vloženého čísla
                    if track_clean.startswith('1Z'):
                        url = f"https://www.ups.com/track?tracknum={track_clean}"
                        st.markdown(f"📦 Detekováno **UPS**. [➡️ Klikněte zde pro sledování zásilky na webu UPS]({url})")
                    elif track_clean.isdigit() and len(track_clean) >= 10:
                        url = f"https://www.fedex.com/fedextrack/?trknbr={track_clean}"
                        st.markdown(f"📦 Detekováno **FedEx**. [➡️ Klikněte zde pro sledování zásilky na webu FedEx]({url})")
                    else:
                        st.warning("Dopravce nebyl automaticky rozpoznán. Zkuste tyto odkazy:")
                        st.markdown(f"[🔗 Zkusit UPS](https://www.ups.com/track?tracknum={track_clean}) | [🔗 Zkusit FedEx](https://www.fedex.com/fedextrack/?trknbr={track_clean})")
                    st.divider()
            else:
                st.error(f"❌ Číslo zásilky '{track_input}' nebylo v reportu LIKP nikde nalezeno.")
    else: st.info("Pro funkci Trackingu nahrajte report LIKP v Admin Zóně.")

    st.divider()

    # ==========================================
    # SEKCE 2: HROMADNÁ ANALÝZA OBALŮ
    # ==========================================
    st.markdown("#### 📦 Hromadná analýza obalového materiálu (Podle zakázek)")
    order_input = st.text_area("Seznam zakázek (můžete zkopírovat sloupec z Excelu):", height=100, placeholder="4941120299\n4941123347")

    if st.button("Analyzovat použité obaly", type="primary"):
        if not order_input.strip() or df_vekp is None or df_vekp.empty:
            st.error("Zadejte zakázky a ujistěte se, že máte nahraný VEKP.")
        else:
            raw_orders = re.split(r'[,\s\n]+', order_input.strip())
            clean_orders = [safe_del(o) for o in raw_orders if o]

            cols_lower = [str(c).lower().strip() for c in df_vekp.columns]
            c_del = next((c for c, l in zip(df_vekp.columns, cols_lower) if "delivery" in l or "lieferung" in l or "dodávka" in l), None)
            c_pack = next((c for c, l in zip(df_vekp.columns, cols_lower) if "packaging materials" in l or "packmittel" in l or "obalový" in l), None)
            c_hu = next((c for c, l in zip(df_vekp.columns, cols_lower) if "internal hu" in l or "hu-nummer intern" in l or "manipul" in l), None)

            if c_del and c_pack:
                df_vekp['Clean_Del'] = df_vekp[c_del].apply(safe_del)
                filt_vekp = df_vekp[df_vekp['Clean_Del'].isin(clean_orders)]
                
                if not filt_vekp.empty:
                    pack_summary = filt_vekp.groupby(c_pack)[c_hu].nunique().reset_index() if c_hu else filt_vekp.groupby(c_pack).size().reset_index()
                    pack_summary.columns = ['Obalový materiál', 'Počet použitých kusů']
                    st.dataframe(pack_summary.sort_values(by='Počet použitých kusů', ascending=False), hide_index=True)
                else: st.warning("Pro tyto zakázky nebyly nalezeny obaly.")

    st.divider()

    # ==========================================
    # SEKCE 3: DASHBOARD A PREDIKCE (S GRAFY)
    # ==========================================
    st.markdown("#### 📈 Sledování a predikce obalu pro Nákup")
    if df_vekp is not None and not df_vekp.empty:
        cols_lower_ana = [str(c).lower().strip() for c in df_vekp.columns]
        c_pack_ana = next((c for c, l in zip(df_vekp.columns, cols_lower_ana) if "packaging materials" in l or "packmittel" in l or "obalový materiál" in l or "obal" in l), None)
        c_date_ana = next((c for c, l in zip(df_vekp.columns, cols_lower_ana) if "created on" in l or "erfasst am" in l or "datum" in l or "date" in l), None)
        c_del_ana = next((c for c, l in zip(df_vekp.columns, cols_lower_ana) if "delivery" in l or "lieferung" in l or "dodávka" in l or "zakázka" in l), None)
        c_hu_ana = next((c for c, l in zip(df_vekp.columns, cols_lower_ana) if "internal hu" in l or "hu-nummer intern" in l or "handling unit" == l or "manipul" in l), None)

        if c_pack_ana and c_date_ana:
            vekp_ana = df_vekp.dropna(subset=[c_pack_ana]).copy()
            vekp_ana['TempDate'] = pd.to_datetime(vekp_ana[c_date_ana], errors='coerce')
            
            if c_hu_ana: 
                vekp_ana['Clean_HU'] = vekp_ana[c_hu_ana].apply(safe_hu)
                vekp_ana = vekp_ana.drop_duplicates(subset=['Clean_HU'])
                
            vekp_ana['MonthStr'] = vekp_ana['TempDate'].dt.strftime('%Y-%m')
            
            avail_packs = sorted([p for p in vekp_ana[c_pack_ana].astype(str).unique() if p and p.lower() != 'nan'])
            
            c_sel1, c_sel2 = st.columns([2, 1])
            with c_sel1: sel_pack = st.selectbox("Vyberte obalový materiál k detailní analýze:", options=["— Vyberte obal —"] + avail_packs)
            with c_sel2: predict_days = st.number_input("Počet odpracovaných dní pro predikci:", min_value=1, value=23)
            
            if sel_pack != "— Vyberte obal —":
                df_sel = vekp_ana[vekp_ana[c_pack_ana].astype(str) == sel_pack].copy()
                
                total_used = len(df_sel)
                monthly_counts = df_sel.groupby('MonthStr').size().reset_index(name='Count')
                
                curr_month = datetime.date.today().strftime('%Y-%m')
                df_comp = df_sel[df_sel['MonthStr'] < curr_month]
                vk_comp = vekp_ana[vekp_ana['MonthStr'] < curr_month]
                
                c1, c2, c3 = st.columns(3)
                
                if not df_comp.empty and not vk_comp.empty:
                    comp_used = len(df_comp)
                    comp_months = df_comp['MonthStr'].nunique()
                    avg_monthly = comp_used / comp_months
                    
                    work_days = vk_comp['TempDate'].dt.date.nunique() or 1
                    avg_daily = comp_used / work_days
                    pred = int(avg_daily * predict_days)
                    
                    c1.metric("📦 Historická spotřeba", f"{total_used} ks")
                    c2.metric("📅 Průměrná měsíční spotřeba", f"{int(avg_monthly)} ks")
                    c3.metric(f"🔮 Predikce ({predict_days} prac. dní)", f"{pred} ks")
                else: 
                    c1.metric("📦 Historická spotřeba", f"{total_used} ks")
                    c2.metric("📅 Průměrná měsíční spotřeba", "Čeká na data")
                    c3.metric(f"🔮 Predikce ({predict_days} dní)", "Čeká na data")
                    st.info("Nedostatek dat z kompletních měsíců pro výpočet spolehlivé predikce.")

                # --- VRÁCENÉ GRAFY A HISTORIE ---
                st.markdown(f"#### 📊 Vývoj spotřeby obalu **{sel_pack}** v čase (Měsíce)")
                if not monthly_counts.empty:
                    fig = px.bar(monthly_counts, x='MonthStr', y='Count', text='Count')
                    fig.update_traces(textposition='auto', marker_color='#8b5cf6')
                    fig.update_layout(
                        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                        xaxis_title="Měsíc", yaxis_title="Spotřebováno (ks)"
                    )
                    st.plotly_chart(fig, width="stretch")
                
                st.markdown("#### 📋 Historie použití (posledních 100 zabalených palet/krabic)")
                if c_del_ana:
                    detail = df_sel[[c_del_ana, c_date_ana, c_hu_ana] if c_hu_ana else [c_del_ana, c_date_ana]].sort_values(by=c_date_ana, ascending=False).head(100)
                    detail.columns = ['Zakázka (Delivery)', 'Datum', 'Manipulační jednotka (HU)'] if c_hu_ana else ['Zakázka (Delivery)', 'Datum']
                    st.dataframe(detail, hide_index=True, width="stretch")
