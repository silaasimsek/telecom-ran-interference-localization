import numpy as np
import pandas as pd
import os
import folium
import math
import matplotlib.pyplot as plt
import cv2 
from folium.plugins import HeatMap
from shapely.geometry import Polygon

# %% [1] dosyaların bulunup okunması kısmı
print("--- FULL ANALİZ BAŞLADI ---")
filenames = {"plan": "1500_2_plandata.csv", "data": "1500_2_data.csv", "ta": "1500_2_TA.csv"}

paths = {}
for key, name in filenames.items():
    if os.path.exists(name):
        paths[key] = name
    elif os.path.exists(os.path.join("data", name)):
        paths[key] = os.path.join("data", name)
    else:
        print(f"!!! HATA: '{name}' dosyası bulunamadı. Lütfen klasörü kontrol edin."); exit()

# verileirn okunması
df_plan = pd.read_csv(paths["plan"], sep=None, engine='python')
df_data = pd.read_csv(paths["data"], sep=None, engine='python')
df_ta = pd.read_csv(paths["ta"], sep=None, engine='python')

# sütunları standartlaştır(farklı formatları okunacak aynı format yapmak)
for df in [df_plan, df_data, df_ta]:
    df.columns = df.columns.str.strip().str.upper()
if 'CELL' not in df_ta.columns: df_ta.rename(columns={df_ta.columns[0]: 'CELL'}, inplace=True)

# %% [2] verileri birleştirip hesaplamak için(merge)
df_temp = pd.merge(df_plan, df_data, on="CELL")
df_combined = pd.merge(df_temp, df_ta, on="CELL").copy()

# sayısal dönüşümler için.(, ve . kısımları aynı gözüksün diye)
df_combined['LAT'] = pd.to_numeric(df_combined['LAT'].astype(str).str.replace(',', '.'), errors='coerce')
df_combined['LON'] = pd.to_numeric(df_combined['LON'].astype(str).str.replace(',', '.'), errors='coerce')
df_combined['P_MAX'] = pd.to_numeric(df_combined['P_MAX'], errors='coerce')
df_combined['AZIMUTH'] = pd.to_numeric(df_combined['AZIMUTH'], errors='coerce').fillna(0)

# histogram hesaplaması(78'den başlıyor 8kya kadar)
ta_values = [78, 234, 546, 1014, 1950, 3510, 6630, 14430, 30030, 53430, 78830, 80000]

# sütun isimlerini exceldeki gerçek halleriyle eşleştirelim (büyük/küçük harf veya boşluk hatalarını engellemek için)
col_mapping = {}
for i in range(12):
    target = f'INDEX{i}'
    # Excel'deki sütunların içinde 'INDEX0', 'INDEX1' geçenleri bul
    match = [c for c in df_combined.columns if target in c]
    if match:
        col_mapping[i] = match[0]

# Pay ve Payda'yı 0 (Series) olarak başlatalım
df_combined['pay'] = 0.0
df_combined['payda'] = 0.0

for i, actual_col in col_mapping.items():
    # veriyi sayıya çevirme kısmı
    df_combined[actual_col] = pd.to_numeric(df_combined[actual_col], errors='coerce').fillna(0)
    # Pay ve Payda eklemesi
    df_combined['pay'] += df_combined[actual_col] * ta_values[i]
    df_combined['payda'] += df_combined[actual_col]


# Payda 0 ise 1'e çeviriyoruz ki bölme hatası olmasın
df_combined['ORTALAMA_MESAFE'] = df_combined['pay'] / df_combined['payda'].replace(0, 1)

# 2. MAX KAPSAMA RANGE HESABI
def calculate_max_range(row):
    # En uzaktan (Index 11) başlayarak 0'dan büyük ilk değeri arıyoruz
    for i in range(11, -1, -1):
        if i in col_mapping:
            col_name = col_mapping[i]
            if row[col_name] > 0:
                return ta_values[i]
    return 78 # Hiç veri yoksa en yakın mesafe

df_combined['MAX_RANGE'] = df_combined.apply(calculate_max_range, axis=1)
df_combined['MESAFE_METRE'] = df_combined['MAX_RANGE']

df_combined.drop(['pay', 'payda'], axis=1, inplace=True)

# En güçlü hücreyi tespit et (interference signature için)
df_unique = df_combined.sort_values(by="P_MAX", ascending=False).drop_duplicates(subset=['CELL']).copy()

if not df_unique.empty:
    top_cell_id = df_unique.iloc[0]['CELL']
    top_cell_data = df_combined[df_combined['CELL'] == top_cell_id].copy()
else:
    print("HATA: Benzersiz hücre bulunamadı!")
    exit()

# En güçlü hücreyi tespit et
df_unique = df_combined.sort_values(by="P_MAX", ascending=False).drop_duplicates(subset=['CELL']).copy()

# %% [3] harita oluşturma kısmı (html için)
def get_sector_poly(lat, lon, azimuth, radius):
    points = [(lon, lat)]
    for angle in range(int(azimuth - 30), int(azimuth + 31), 5):
        rad = math.radians(90 - angle)
        new_lat = lat + (radius / 111320) * math.sin(rad)
        new_lon = lon + (radius / (111320 * math.cos(math.radians(lat)))) * math.cos(rad)
        points.append((new_lon, new_lat))
    return Polygon(points)

# harita başlangıç noktası (ortalama koordinat)
m = folium.Map(location=[df_unique['LAT'].mean(), df_unique['LON'].mean()], zoom_start=14, tiles='OpenStreetMap')
heat_data = []
max_p, min_p = df_unique['P_MAX'].max(), df_unique['P_MAX'].min()

for _, row in df_unique.iterrows():
    poly = get_sector_poly(row['LAT'], row['LON'], row['AZIMUTH'], row['MESAFE_METRE'])
    if poly.is_valid:
        # ısı haritası ağırlığı
        weight = (row['P_MAX'] - min_p) / (max_p - min_p) if max_p != min_p else 1.0
        heat_data.append([poly.centroid.y, poly.centroid.x, weight])
        
        # Sektör Poligonları ve Popup
        coords = [[c[1], c[0]] for c in poly.exterior.coords]
        info = (f"<b>CELL:</b> {row['CELL']}<br><b>P_MAX:</b> {row['P_MAX']} dBm<br>"
                f"<b>AZIMUTH:</b> {row['AZIMUTH']}°<br><b>MESAFE:</b> {row['MESAFE_METRE']}m")
        
        folium.Polygon(locations=coords, color='red', weight=1.5, fill=True, fill_opacity=0.1, 
                       popup=folium.Popup(info, max_width=300)).add_to(m)
        
        # Baz istasyonu simgeleri
        folium.Marker([row['LAT'], row['LON']], 
                       icon=folium.Icon(color='blue', icon='broadcast-tower', prefix='fa'),
                       tooltip=row['CELL']).add_to(m)

# Isı Haritası Katmanı
HeatMap(heat_data, radius=22, blur=18, min_opacity=0.4, 
        gradient={0.4:'blue', 0.65:'lime', 0.85:'yellow', 1.0:'red'}).add_to(m)

# Tahmini Kaynak Noktası (X İşareti) belirlenmesi.
if heat_data:
    lats, lons, ws = [p[0] for p in heat_data], [p[1] for p in heat_data], [p[2] for p in heat_data]
    avg_lat, avg_lon = sum(lats[i]*ws[i] for i in range(len(ws)))/sum(ws), sum(lons[i]*ws[i] for i in range(len(ws)))/sum(ws)
    folium.Marker([avg_lat, avg_lon], icon=folium.Icon(color='darkred', icon='times', prefix='fa'),
                  popup=f"<b>Tahmini Kaynak</b><br>LAT: {avg_lat:.5f}<br>LON: {avg_lon:.5f}").add_to(m)

m.save("localization_final_rapor.html")

# %% [4] 224x224 PNG çıktısı
print(f"İmza grafiği oluşturuluyor: {top_cell_id}...")

prb_cols = [c for c in top_cell_data.columns if c.startswith('PRB')]
if prb_cols:
    # 1. Veri Hazırlama (Matris)
    prb_matrix = top_cell_data[prb_cols].apply(pd.to_numeric, errors='coerce').fillna(-125).values
    
    # 2. 224x224 Boyutlandırma
    signature_resized = cv2.resize(prb_matrix, (224, 224), interpolation=cv2.INTER_LINEAR)
    
    # 3. Görselleştirme
    plt.figure(figsize=(10, 7))
    # Zaman yatay (X), PRB dikey (Y) olacak şekilde Transpoze (.T) alıyoruz
    im = plt.imshow(signature_resized.T, cmap='RdYlGn_r', vmin=-120, vmax=-80, aspect='auto')

    # eksen düzeltme
    # Sol Eksen: PRB Numaraları (1-100 arası 10 etiket)
    plt.yticks(np.linspace(0, 224, 10), labels=[f"PRB {int(i)}" for i in np.linspace(1, 100, 10)])
    
    # Alt Eksen: Sadece Örnek Numaraları (Veri sırası)
    total_samples = len(top_cell_data)
    plt.xticks(np.linspace(0, 224, 5), labels=np.linspace(0, total_samples, 5).astype(int))

    # Başlık ve Etiketler
    plt.title(f"Interference Signature (224x224)\nCell: {top_cell_id}", fontsize=12)
    plt.ylabel("Frekans Kanalları")
    plt.xlabel("Veri Kayıt Sırası (Örnek Sayısı)")
    
    # Renk Skalası (Sağ taraf)
    plt.colorbar(im, label='Gürültü Şiddeti (dBm)')

    # Kaydet
    plt.tight_layout()
    plt.savefig('Interference Signature.png', bbox_inches='tight', dpi=300)
    plt.close()
    
    print("\n--- İŞLEM TAMAM ---")
    print("Grafik 'Inteference Signature.png' adıyla oluşturuldu.")

# %% [5] sonuç kısmı
print("\n--- ANALİZ TAMAMLANDI ---")
print("1. Harita (HTML): localization_final_rapor.html")
print("2. Interference Signature (PNG): Interference_Signature_horizontal.png")
print("\nEn Kritik Hücreler:")
print(df_unique[["CELL", "P_MAX", "AZIMUTH", "MESAFE_METRE"]].head(10).to_string(index=False))