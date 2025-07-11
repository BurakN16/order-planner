import pandas as pd

def palet_factor(pal_type):
    return 0.5 if pal_type == 'Kısa Hafif' else 1

def calculate_effective_pallet(row):
    return row['CPallet'] * palet_factor(row['PALTypeChoice'])

def split_large_orders(city_group, truck_counter_start=1):
    """33 paleti geçen büyük siparişleri böl ve 33 paletlik parçaları ata,
    kalanları da liste olarak döndür."""
    assignments = []
    leftover_parts = []
    truck_counter = truck_counter_start

    shipto_groups = city_group.groupby('Ship to')

    for ship_to, sub_group in shipto_groups:
        total_pallet = sub_group['EffectivePallet'].sum()
        if total_pallet <= 33:
            # Küçük siparişler burada değil, sonraya bırakacağız
            leftover_parts.append((ship_to, sub_group))
            continue

        # Büyük siparişleri böl
        rows = sub_group.to_dict('records')
        part = []
        part_load = 0

        for row in rows:
            p = row['EffectivePallet']
            if part_load + p > 33:
                # 33 paleti geçen parça tamamlanınca ata
                df_part = pd.DataFrame(part)
                for r in df_part.to_dict('records'):
                    r['Assigned_Truck'] = f"Truck-{truck_counter}"
                    assignments.append(r)
                truck_counter += 1
                part = []
                part_load = 0
            part.append(row)
            part_load += p

        # Kalan parçayı atama listesine ekle
        if part:
            df_part = pd.DataFrame(part)
            leftover_parts.append((ship_to, df_part))

    return assignments, leftover_parts, truck_counter

def group_and_assign_leftovers(leftover_parts, truck_counter_start=1):
    """Kalan parçaları şehir bazında grupla, 33 palet ve 4 shipto kısıtları ile araçlara ata."""
    assignments = []
    truck_counter = truck_counter_start

    # leftover_parts: list of (ship_to, DataFrame)
    # Önce ship_to bazında grupla ve tüm DataFrame'leri birleştir
    combined_df = pd.concat([df for _, df in leftover_parts], ignore_index=True)

    # Şehir bazında grupla
    grouped_city = combined_df.groupby('Ship to City')

    for city, city_group in grouped_city:
        city_group = city_group.reset_index(drop=True)

        # Ship to bazında grupla
        subgroups = city_group.groupby('Ship to')

        pending_groups = []
        for ship_to, sub_group in subgroups:
            total_pallet = sub_group['EffectivePallet'].sum()
            pending_groups.append((ship_to, sub_group, total_pallet))

        # Palet sayısına göre azalan sırala
        pending_groups.sort(key=lambda x: x[2], reverse=True)

        while pending_groups:
            current_load = 0
            truck_orders = []
            used_shiptos = set()
            remaining_groups = []

            def calc_adjusted_pallet(sub_group, multiple_shipto):
                if not multiple_shipto:
                    return sub_group['EffectivePallet'].sum()
                else:
                    def pallet_factor_override(row):
                        if row['PALTypeChoice'] == 'Kısa Hafif':
                            return row['CPallet'] * 1
                        else:
                            return row['CPallet'] * 1
                    return sub_group.apply(pallet_factor_override, axis=1).sum()

            for ship_to, sub_group, total_pallet in pending_groups:
                multiple_shipto_in_truck = len(used_shiptos | {ship_to}) > 1
                adjusted_pallet = calc_adjusted_pallet(sub_group, multiple_shipto_in_truck)

                if adjusted_pallet <= 33:
                    if (current_load + adjusted_pallet <= 33) and (len(used_shiptos | {ship_to}) <= 4):
                        current_load += adjusted_pallet
                        truck_orders.append((ship_to, sub_group))
                        used_shiptos.add(ship_to)
                    else:
                        remaining_groups.append((ship_to, sub_group, total_pallet))
                else:
                    remaining_groups.append((ship_to, sub_group, total_pallet))

            if truck_orders:
                for ship_to, sub_group in truck_orders:
                    for _, row in sub_group.iterrows():
                        order = row.to_dict()
                        order['Assigned_Truck'] = f"Truck-{truck_counter}"
                        assignments.append(order)

                truck_counter += 1
            pending_groups = remaining_groups

    return assignments, truck_counter

def solve_assignment(order_df):
    order_df = order_df.copy()
    order_df.columns = order_df.columns.str.strip()
    order_df = order_df.reset_index(drop=True)

    if 'Ship to City' not in order_df.columns or 'Ship to' not in order_df.columns:
        print("HATA: Gerekli sütunlar eksik!")
        return pd.DataFrame()

    try:
        order_df['EffectivePallet'] = order_df.apply(calculate_effective_pallet, axis=1)
    except Exception as e:
        print("EffectivePallet hesaplamasında hata:", e)
        return pd.DataFrame()

    assignments = []
    truck_counter = 1

    grouped_city = order_df.groupby('Ship to City')

    for city, city_group in grouped_city:
        # 1. Büyük siparişleri böl ve 33 paletlik parçaları ata
        assigned_large, leftover_parts, truck_counter = split_large_orders(city_group, truck_counter)

        assignments.extend(assigned_large)

        # 2. Kalan parçalarla şehir bazında gruplayarak araçlara ata
        assigned_leftovers, truck_counter = group_and_assign_leftovers(leftover_parts, truck_counter)
        assignments.extend(assigned_leftovers)

    # assignments listesini DataFrame'e çevir
    assigned_df = pd.DataFrame(assignments)

    # Burada Assigned_Truck bazında araç isimlerini güncelleyelim
    def update_truck_name(truck_id, df):
        # Araçta Temp_Type sütununda 'Temp' geçen var mı kontrolü
        has_temp = df['Temp_Type'].astype(str).str.contains('Temp').any()

        truck_type = "Frigo" if has_temp else "Tente"

        total_pallet = df['EffectivePallet'].sum()
        vehicle_type = "Kamyon" if total_pallet <= 18 else "Tır"

        return f"{truck_type} {vehicle_type} -{truck_id}"

    # Assigned_Truck sütunundaki değerlerden sadece sayıyı alalım (örneğin 'Truck-3' -> 3)
    assigned_df['Truck_Number'] = assigned_df['Assigned_Truck'].str.extract(r'(\d+)').astype(int)

    # Araç bazında yeni isimler oluştur
    truck_names = {}
    for truck_num, group in assigned_df.groupby('Truck_Number'):
        truck_names[truck_num] = update_truck_name(truck_num, group)

    # Yeni isimleri Assigned_Truck sütununa yaz
    assigned_df['Assigned_Truck'] = assigned_df['Truck_Number'].map(truck_names)

    # Yardımcı sütunu kaldıralım
    assigned_df = assigned_df.drop(columns=['Truck_Number'])

    print(f"\n✅ Toplam atanan kayıt: {len(assigned_df)}")
    return assigned_df

