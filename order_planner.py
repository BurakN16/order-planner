import streamlit as st
import pandas as pd
from solver import solve_assignment
from io import BytesIO
from PIL import Image
import tempfile
import os

# COM Excel için
try:
    import win32com.client as win32
except ImportError:
    win32 = None  # yoksa pivot otomasyonu devre dışı kalacak

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

# Excel pivot table oluşturan fonksiyon (COM üzerinden, Windows + Excel gerekir)
def create_excel_with_pivot_via_com(temp_path: str, output_path: str):
    if win32 is None:
        raise RuntimeError("win32com.client yüklü değil; gerçek pivot table oluşturulamaz.")

    # Excel sabitlerinin sayısal karşılıkları
    XL_DATABASE = 1          # xlDatabase
    XL_ROW_FIELD = 1         # xlRowField
    XL_SUM = -4157           # xlSum

    excel = win32.DispatchEx("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        wb = excel.Workbooks.Open(temp_path)
        # Veri sayfası
        try:
            data_ws = wb.Worksheets("Atama Sonuçları")
        except Exception:
            raise RuntimeError("Excel dosyasında 'Atama Sonuçları' sayfası yok.")

        # Varsa eski pivot sayfasını sil
        try:
            existing = wb.Worksheets("Pivot Atama Sonuçları")
            existing.Delete()
        except Exception:
            pass
        pivot_ws = wb.Worksheets.Add()
        pivot_ws.Name = "Pivot Atama Sonuçları"

        # Veri aralığını al (A1'den başlayıp bitişiğe kadar)
        source_range = data_ws.Range("A1").CurrentRegion

        # Pivot cache oluştur
        pivot_cache = wb.PivotCaches().Create(SourceType=XL_DATABASE, SourceData=source_range)
        dest = pivot_ws.Range("A3")
        pivot_table = pivot_cache.CreatePivotTable(TableDestination=dest, TableName="PivotTable1")

        # Satır alanları: varsa ekle
        for field in ["Assigned_Truck", "Ship to", "Sales Document","Ship to City", "Ship to name", "City_District"]:
            try:
                pf = pivot_table.PivotFields(field)
                pf.Orientation = XL_ROW_FIELD
            except Exception:
                pass  # alan yoksa atla

        # Değer alanı: EffectivePallet toplamı
        try:
            ep_field = pivot_table.PivotFields("EffectivePallet")
            pivot_table.AddDataField(ep_field, "Sum of EffectivePallet", XL_SUM)
        except Exception:
            pass

        pivot_table.RefreshTable()
        wb.SaveAs(output_path)
    finally:
        wb.Close(SaveChanges=False)
        excel.Quit()

# Sayfanın başına ortalanmış resim ekle
image = Image.open("Picture1.png")
st.markdown("<div style='text-align: center;'>", unsafe_allow_html=True)
st.image(image, width=300)
st.markdown("</div>", unsafe_allow_html=True)

st.title("🚛 Load Planner")

uploaded_file = st.file_uploader("Sipariş dosyasını yükleyin (Excel)", type=["xlsx"])

if uploaded_file:
    order_df = pd.read_excel(uploaded_file)

    st.subheader("📝Yüklenen Sipariş Verisi")
    st.dataframe(order_df, use_container_width=True, height=400)

    # Bilgi Kartları Bölümü - Dosya kalite kontrolleri
    st.subheader("🔍 Veri Kalite Kontrolleri")
    if 'EffectivePallet' in order_df.columns:
        sales_pallet_summary = order_df.groupby("Sales Document")["EffectivePallet"].sum().reset_index()
        over_limit_orders = sales_pallet_summary[sales_pallet_summary["EffectivePallet"] > 33]
        if not over_limit_orders.empty:
            st.markdown("<h4 style='color: red;'>⚠️ Aşağıdaki siparişlerde toplam palet sayısı 33'ü geçiyor:</h4>", unsafe_allow_html=True)
            st.dataframe(over_limit_orders, use_container_width=True, height=250)

    total_orders = order_df['Sales Document'].nunique()
    missing_paltype = order_df[order_df['PALTypeChoice'].isna()]
    missing_city = order_df[order_df['City_District'].isna()]

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

    if st.button("Araca Atamaları Yap"):
        assigned_df = solve_assignment(order_df)

        st.subheader("🚚 Atama Sonuçları")
        st.dataframe(assigned_df, use_container_width=True, height=500)

        # Araç bazlı özet tablo
        summary = assigned_df.groupby("Assigned_Truck").agg({
            'CPallet': 'sum',
            'CPallet_M3': 'sum',
            'CPallet_Gross': 'sum',
            'EffectivePallet': 'sum'
        }).reset_index()

        # Doluluk hesaplaması
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

        # Yeni detaylı özet tablo (Araç + Ship-to bazlı)
        truck_shipto_summary = assigned_df.groupby(
            ['Assigned_Truck', 'Ship to', 'Ship to name', 'City_District','Sales Document','Requested delivery d']
        )['EffectivePallet'].sum().reset_index()

        st.subheader("Araç & Ship-to Detaylı Özet")
        st.dataframe(truck_shipto_summary, use_container_width=True, height=400)

        # Excel dosyasını önce geçiciye yaz
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp_path = tmp.name
        with pd.ExcelWriter(tmp_path, engine='xlsxwriter') as writer:
            assigned_df.to_excel(writer, index=False, sheet_name='Atama Sonuçları')
            summary.to_excel(writer, index=False, sheet_name='Araç Özeti')
            truck_shipto_summary.to_excel(writer, index=False, sheet_name='Araç-ShipTo Özeti')

        final_path = tmp_path.replace(".xlsx", "_pivot.xlsx")
        try:
            create_excel_with_pivot_via_com(tmp_path, final_path)
            with open(final_path, "rb") as f:
                data = f.read()
            st.download_button(
                label="📥 Excel İndir (Atama + Gerçek Pivot)",
                data=data,
                file_name="order_arac_atama_pivot.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        except Exception as e:
            st.warning(f"Gerçek pivot oluşturulamadı: {e}. Excel dosyası pivot olmadan indiriliyor.")
            with open(tmp_path, "rb") as f:
                data = f.read()
            st.download_button(
                label="📥 Excel İndir (Atama + Özetler)",
                data=data,
                file_name="order_arac_atama.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        finally:
            try:
                os.remove(tmp_path)
            except:
                pass
            try:
                os.remove(final_path)
            except:
                pass

        # 🛑 Sipariş Bazlı Palet Uyarısı
        if 'EffectivePallet' in assigned_df.columns:
            sales_pallet_summary = assigned_df.groupby("Sales Document")["EffectivePallet"].sum().reset_index()
            over_limit_orders = sales_pallet_summary[sales_pallet_summary["EffectivePallet"] > 33]

            if not over_limit_orders.empty:
                st.markdown("<h4 style='color: red;'>⚠️ Aşağıdaki siparişlerde toplam palet sayısı 33'ü geçiyor:</h4>", unsafe_allow_html=True)
                st.dataframe(over_limit_orders, use_container_width=True, height=250)
