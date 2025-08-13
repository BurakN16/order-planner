import streamlit as st
import pandas as pd
from solver import solve_assignment
from io import BytesIO
from PIL import Image

# CSS ile yazı tipi ve boyutu ayarlayalım
st.markdown("""
    <style>
        div[data-testid="stDataFrame"] div[role="gridcell"] {
            font-family: Calibri, sans-serif;
            font-size: 9pt;
        }
        .dataframe {
            font-family: Calibri, sans-serif;
            font-size: 9pt;
        }
    </style>
""", unsafe_allow_html=True)

# Sayfanın başına ortalanmış resim ekle
image = Image.open("Picture1.png")
st.markdown("<div style='text-align: center;'>", unsafe_allow_html=True)
st.image(image, width=300)
st.markdown("</div>", unsafe_allow_html=True)

st.title("🚛 Load Planner")

# State başlatma
if "show_results" not in st.session_state:
    st.session_state.show_results = False
if "assigned_df" not in st.session_state:
    st.session_state.assigned_df = None

uploaded_file = st.file_uploader("Sipariş dosyasını yükleyin (Excel)", type=["xlsx"])

if uploaded_file:
    order_df = pd.read_excel(uploaded_file)

    st.subheader("📝Yüklenen Sipariş Verisi")
    st.dataframe(order_df, use_container_width=True, height=400)

    # Bilgi Kartları Bölümü
    st.subheader("🔍 Veri Kalite Kontrolleri")

    # 🛑 Sipariş Bazlı Palet Uyarısı
    if 'EffectivePallet' in order_df.columns:
        sales_pallet_summary = order_df.groupby("Sales Document")["EffectivePallet"].sum().reset_index()
        over_limit_orders = sales_pallet_summary[sales_pallet_summary["EffectivePallet"] > 33]
        if not over_limit_orders.empty:
            st.markdown("<h4 style='color: red;'>⚠️ Aşağıdaki siparişlerde toplam palet sayısı 33'ü geçiyor:</h4>", unsafe_allow_html=True)
            st.dataframe(over_limit_orders, use_container_width=True, height=250)

    total_orders = order_df['Sales Document'].nunique()
    missing_paltype = order_df[order_df['PALTypeChoice'].isna()]
    missing_city = order_df[order_df['City_District'].isna()]

    # Renk belirleme
    paltype_color = "#90ee90" if missing_paltype.empty else "#ff7f7f"
    city_color = "#90ee90" if missing_city.empty else "#ff7f7f"

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown(f"""
            <div style='padding: 20px; background-color: #90ee90; border-radius: 10px; text-align: center'>
                <h4 style='margin: 0'>Planda {total_orders} sipariş var</h4>
            </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown(f"""
            <div style='padding: 20px; background-color: {paltype_color}; border-radius: 10px; text-align: center'>
                <h4 style='margin: 0'>
                    {len(missing_paltype)} adet siparişin 'PALTypeChoice' bilgisi eksik.<br>Kontrol edin.
                </h4>
            </div>
        """, unsafe_allow_html=True)

    with col3:
        st.markdown(f"""
            <div style='padding: 20px; background-color: {city_color}; border-radius: 10px; text-align: center'>
                <h4 style='margin: 0'>
                    {missing_city['Ship to'].nunique()} adet müşterinin 'City_District' bilgisi eksik.<br>Kontrol edin.
                </h4>
            </div>
        """, unsafe_allow_html=True)

    # Butona basıldığında state güncelle
    if st.button("Araca Atamaları Yap"):
        st.session_state.assigned_df = solve_assignment(order_df)
        st.session_state.show_results = True

# Eğer atama yapılmışsa sonuçları göster
if st.session_state.show_results and st.session_state.assigned_df is not None:
    assigned_df = st.session_state.assigned_df

    st.subheader("🚚 Atama Sonuçları")
    st.dataframe(assigned_df, use_container_width=True, height=500)

    # Araç bazlı özet tablo
    summary = assigned_df.groupby("Assigned_Truck").agg({
        'CPallet': 'sum',
        'CPallet_M3': 'sum',
        'CPallet_Gross': 'sum',
        'EffectivePallet': 'sum'
    }).reset_index()

    # Doluluk hesaplama
    def hesapla_doluluk_satiri(row):
        if row['EffectivePallet'] <= 18:
            palet_kapasite = 18
            hacim_kapasite = 44
            agirlik_kapasite = 12000
        else:
            palet_kapasite = 33
            hacim_kapasite = 82
            agirlik_kapasite = 24000

        return pd.Series({
            'DolulukOrani_Pallet': (row['EffectivePallet'] / palet_kapasite) * 100,
            'DolulukOrani_Volume': (row['CPallet_M3'] / hacim_kapasite) * 100,
            'DolulukOrani_Weight': (row['CPallet_Gross'] / agirlik_kapasite) * 100
        })

    doluluk_df = summary.apply(hesapla_doluluk_satiri, axis=1)
    summary = pd.concat([summary, doluluk_df], axis=1)

    def renk_kodla(deger):
        if deger >= 95:
            return 'background-color: lightgreen'
        elif deger >= 70:
            return 'background-color: yellow'
        else:
            return 'background-color: lightcoral'

    st.subheader("📊Araç Bazlı Özet")
    styled_summary = summary.style \
        .applymap(renk_kodla, subset=['DolulukOrani_Pallet']) \
        .format({
            'DolulukOrani_Pallet': "{:.1f}%",
            'DolulukOrani_Volume': "{:.1f}%",
            'DolulukOrani_Weight': "{:.1f}%"
        })

    st.dataframe(styled_summary, use_container_width=True, height=500)

    # Excel çıktısı
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        assigned_df.to_excel(writer, index=False, sheet_name='Atama Sonuçları')
        summary.to_excel(writer, index=False, sheet_name='Araç Özeti')
    output.seek(0)

    st.download_button(
        label="📥 Excel İndir (Atama + Özetler)",
        data=output,
        file_name="order_arac_atama.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    # 🛑 Sipariş Bazlı Palet Uyarısı
    if 'EffectivePallet' in assigned_df.columns:
        sales_pallet_summary = assigned_df.groupby("Sales Document")["EffectivePallet"].sum().reset_index()
        over_limit_orders = sales_pallet_summary[sales_pallet_summary["EffectivePallet"] > 33]
        if not over_limit_orders.empty:
            st.markdown("<h4 style='color: red;'>⚠️ Aşağıdaki siparişlerde toplam palet sayısı 33'ü geçiyor:</h4>", unsafe_allow_html=True)
            st.dataframe(over_limit_orders, use_container_width=True, height=250)
