import pandas as pd


# ————————————————————————————————————————————————————————————————————
# Yardımcı fonksiyonlar
# ————————————————————————————————————————————————————————————————————

def palet_factor(pal_type: str) -> float:
    """Palet tipine göre katsayı döndür."""
    return 0.5 if pal_type == "Kısa Hafif" else 1.0


def calculate_effective_pallet(row: pd.Series) -> float:
    """Satır bazlı efektif palet değeri."""
    return row["CPallet"] * palet_factor(row["PALTypeChoice"])


def get_truck_type(pallet_sum: float) -> str:
    """
    Palet toplamına göre aracın gövde tipini döndür.
    ≤ 18  → Kamyon
    ≥ 19  → Tır
    """
    return "Kamyon" if pallet_sum <= 18 else "Tır"


def get_temp_prefix(df: pd.DataFrame) -> str:
    """
    Temp_Type sütununa göre araç için sıcaklık ön ekini döndür.
    - En az bir “Temp” varsa  → Frigo
    - Aksi hâlde (tamamı Ambient) → Tente
    Sütun yoksa da “Tente” varsayılır.
    """
    if "Temp_Type" not in df.columns:
        return "Tente"

    is_temp = (
        df["Temp_Type"]
        .astype(str)
        .str.strip()
        .str.lower()
        .eq("temp")
        .any()
    )
    return "Frigo" if is_temp else "Tente"


# ————————————————————————————————————————————————————————————————————
# Ana çözümleyici
# ————————————————————————————————————————————————————————————————————

def solve_assignment(order_df: pd.DataFrame) -> pd.DataFrame:
    """
    Parametre: order_df – sipariş verisi
    Dönüş   : ataması yapılmış sipariş satırlarını içeren DataFrame
    """
    order_df = order_df.copy()
    order_df.columns = order_df.columns.str.strip()
    order_df = order_df.reset_index(drop=True)

    if "Ship to City" not in order_df.columns or "Ship to" not in order_df.columns:
        print("HATA: Gerekli sütunlar eksik!")
        return pd.DataFrame()

    # Efektif palet hesabı
    try:
        order_df["EffectivePallet"] = order_df.apply(calculate_effective_pallet, axis=1)
    except Exception as e:
        print("EffectivePallet hesaplamasında hata:", e)
        return pd.DataFrame()

    assignments = []
    truck_counter = 1

    # Şehir kombinasyonları
    city_combinations = [
        {"Bursa", "Yalova"},
        {"Balikesir", "Canakkale"},
        {"Mugla", "Aydin"},
    ]

    leftover_groups = []  # Küçük / orta yükler burada tutulur

    # ——— 1) Şehir bazlı ön atama ——————————————————————————————
    grouped_city = order_df.groupby("Ship to City")

    for city, city_group in grouped_city:
        print(f"\n🛻 Atama işlemi başlatıldı – {city} ({len(city_group)} kayıt)")

        city_group = city_group.reset_index(drop=True)
        subgroups = city_group.groupby("Ship to")

        for ship_to, sub_group in subgroups:
            total_pallet = sub_group["EffectivePallet"].sum()
            print(f"  ▶ Ship-to: {ship_to} | Toplam Palet: {total_pallet:.2f}")

            if total_pallet > 33:
                # Büyük grup → doğrudan atama
                truck_type = get_truck_type(total_pallet)
                temp_prefix = get_temp_prefix(sub_group)
                truck_name = f"{temp_prefix} {truck_type}-{truck_counter}"

                for _, row in sub_group.iterrows():
                    order = row.to_dict()
                    order["Assigned_Truck"] = truck_name
                    assignments.append(order)

                print(
                    f"🚚 {truck_name} ⇒ Ship-to {ship_to} "
                    f"(büyük grup) | {total_pallet:.2f} Palet"
                )
                truck_counter += 1
            else:
                # Küçük / orta yükler daha sonra birleştirilecek
                leftover_groups.append((city, ship_to, sub_group, total_pallet))

    # ——— 2) Küçük yükleri şehir kombinasyonlarına göre birleştir ———
    normalize = lambda c: c.strip().lower()

    city_group_map = {}
    for city, ship_to, sub_group, total_pallet in leftover_groups:
        city_norm = normalize(city)
        city_group_map.setdefault(city_norm, []).append(
            (ship_to, sub_group, total_pallet)
        )

    normalized_combinations = [set(map(normalize, comb)) for comb in city_combinations]

    city_comb_group_map = {}
    for city_norm, groups in city_group_map.items():
        placed = False
        for comb in normalized_combinations:
            if city_norm in comb:
                city_comb_group_map.setdefault(frozenset(comb), []).extend(groups)
                placed = True
                break
        if not placed:
            city_comb_group_map.setdefault(frozenset({city_norm}), []).extend(groups)

    # ——— Kombinasyon bazlı atama ——————————————————————————————
    for comb_key, group_list in city_comb_group_map.items():
        comb_cities = list(comb_key)
        print(f"\n🔗 Kombinasyon ile atama: {comb_cities} ({len(group_list)} grup)")

        group_list.sort(key=lambda x: x[2], reverse=True)  # büyükten küçüğe
        pending_groups = group_list.copy()

        while pending_groups:
            current_load = 0.0
            truck_orders = []
            used_shiptos = set()
            remaining = []

            for ship_to, sub_group, total_pallet in pending_groups:
                if (
                    total_pallet <= 33
                    and current_load + total_pallet <= 33
                    and len(used_shiptos | {ship_to}) <= 4
                ):
                    current_load += total_pallet
                    truck_orders.append((ship_to, sub_group))
                    used_shiptos.add(ship_to)
                else:
                    remaining.append((ship_to, sub_group, total_pallet))

            if truck_orders:
                # Tek seferde bu araca atanacak tüm grupları birleştir
                df_truck = pd.concat([sg for _, sg in truck_orders], ignore_index=True)

                truck_type = get_truck_type(current_load)
                temp_prefix = get_temp_prefix(df_truck)
                truck_name = f"{temp_prefix} {truck_type}-{truck_counter}"

                for _, sub_group in truck_orders:
                    for _, row in sub_group.iterrows():
                        order = row.to_dict()
                        order["Assigned_Truck"] = truck_name
                        assignments.append(order)

                print(
                    f"🚚 {truck_name} ⇒ Kombinasyon ataması "
                    f"| Toplam Palet: {current_load:.2f}"
                )
                truck_counter += 1
            else:
                break  # Daha fazla gruplanamıyor

            pending_groups = remaining

    print(f"\n✅ Toplam atanan kayıt: {len(assignments)}")
    return pd.DataFrame(assignments)
