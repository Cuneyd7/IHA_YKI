from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)

def get_saat():
    now = datetime.now()
    return {
        "gun": now.day,
        "saat": now.hour,
        "dakika": now.minute,
        "saniye": now.second,
        "milisaniye": int(now.microsecond / 1000)
    }

# 1. Oturum Açma
@app.route('/api/giris', methods=['POST'])
def giris():
    data = request.json
    print(f"[GİRİŞ DENEMESİ] Kullanıcı: {data.get('kadi')} - Şifre: {data.get('sifre')}")
    # Herhangi bir veri girilirse Takım 1 olarak kabul et ve 200 dön
    if data and data.get("kadi"):
        return jsonify(1), 200
    return jsonify("Hatali Giris"), 400

# 2. Sunucu Saati
@app.route('/api/sunucusaati', methods=['GET'])
def sunucusaati():
    return jsonify(get_saat()), 200

import time as _time

# Basit hız sınırı (rate limit) denetimi için
son_telemetri_zamani = {}

# 3. Telemetri Gönderimi ve Rakip Verileri
@app.route('/api/telemetri_gonder', methods=['POST'])
def telemetri():
    veri = request.json
    t_no = veri.get("takim_numarasi", 0)
    simdi = _time.time()
    
    # 1 Hz Kuralı Denetimi (Örn: 2.0 saniyeden kısa aralıklar hata döndürür)
    if t_no in son_telemetri_zamani:
        fark = simdi - son_telemetri_zamani[t_no]
        if fark < 0.5: 
            print(f"  [!] HIZ SINIRI IHLALI: Takim {t_no}, Fark: {fark:.3f}s", flush=True)
            return jsonify("Hata: 1 Hz Kurali Ihlali"), 400
    
    son_telemetri_zamani[t_no] = simdi
    
    # TÜM PAKETİ GÖRSEL OLARAK YAZDIR
    import json
    print("\n" + "═"*60)
    print(f" 📡 [TELEMETRİ PAKETİ] Takım #{t_no} | {datetime.now().strftime('%H:%M:%S')}")
    print("─"*60)
    print(json.dumps(veri, indent=4, ensure_ascii=False))
    print("═"*60 + "\n", flush=True)
    import sys; sys.stdout.flush()
    
    cevap = {
        "sunucusaati": get_saat(),
        "konumBilgileri": [
            {
                "takim_numarasi": 2,
                "iha_enlem": 41.102500,
                "iha_boylam": 29.022500,
                "iha_irtifa": 45.0,
                "iha_dikilme": 5.0,
                "iha_yonelme": 45.0,
                "iha_yatis": 10.0,
                "iha_hizi": 35.0,
                "zaman_farki": 150
            },
            {
                "takim_numarasi": 3,
                "iha_enlem": 41.101500,
                "iha_boylam": 29.021000,
                "iha_irtifa": 38.0,
                "iha_dikilme": -2.0,
                "iha_yonelme": 180.0,
                "iha_yatis": -5.0,
                "iha_hizi": 42.0,
                "zaman_farki": 80
            }
        ]
    }
    return jsonify(cevap), 200

# 4. Kilitlenme
@app.route('/api/kilitlenme_bilgisi', methods=['POST'])
def kilitlenme():
    print(f"[KİLİTLENME GÖREVİ ALINDI] {request.json}")
    return jsonify("OK"), 200

# 5. Kamikaze
@app.route('/api/kamikaze_bilgisi', methods=['POST'])
def kamikaze():
    print(f"[KAMİKAZE GÖREVİ ALINDI] {request.json}")
    return jsonify("OK"), 200

# 6. QR Koordinat
@app.route('/api/qr_koordinati', methods=['GET'])
def qr_koordinati():
    print("[QR KOORDİNATI SORGULANDI]")
    return jsonify({"qrEnlem": 41.102200, "qrBoylam": 29.022000}), 200

# 7. Hava Savunma Sistemi (HSS)
@app.route('/api/hss_koordinatlari', methods=['GET'])
def hss():
    print("[HSS BÖLGELERİ SORGULANDI]")
    cevap = {
        "sunucusaati": get_saat(),
        "hss_koordinat_bilgileri": [
            {"id": 0, "hssEnlem": 41.103000, "hssBoylam": 29.023000, "hssYaricap": 100},
            {"id": 1, "hssEnlem": 41.101000, "hssBoylam": 29.021000, "hssYaricap": 120}
        ]
    }
    return jsonify(cevap), 200

if __name__ == '__main__':
    print("=====================================================")
    print(" SAHTE TEKNOFEST SUNUCUSU BAŞLATILDI (127.0.0.25:5000)")
    print("=====================================================")
    # YKİ'deki SERVER_URL adresiyle aynı olan IP ve Port
    app.run(host='127.0.0.25', port=5000)
