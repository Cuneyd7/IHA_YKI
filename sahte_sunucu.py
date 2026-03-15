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

# 3. Telemetri Gönderimi ve Rakip Verileri
@app.route('/api/telemetri_gonder', methods=['POST'])
def telemetri():
    veri = request.json
    print(f"[TELEMETRİ GELDİ] Enlem: {veri.get('iha_enlem')} | Boylam: {veri.get('iha_boylam')} | İrtifa: {veri.get('iha_irtifa')}m | Batarya: {veri.get('iha_batarya')}%")
    
    cevap = {
        "sunucusaati": get_saat(),
        "konumBilgileri": [
            {
                "takim_numarasi": 2,
                "iha_enlem": 41.5100365,
                "iha_boylam": 36.11837,
                "iha_irtifa": 44.0,
                "iha_dikilme": 24.0,
                "iha_yonelme": 277.0,
                "iha_yatis": -37.0,
                "iha_hizi": 40.0,
                "zaman_farki": 248
            },
            {
                "takim_numarasi": 3,
                "iha_enlem": 41.5123138,
                "iha_boylam": 36.12,
                "iha_irtifa": 32.0,
                "iha_dikilme": 9.0,
                "iha_yonelme": 13,
                "iha_yatis": -30.0,
                "iha_hizi": 45.0,
                "zaman_farki": 30
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
    return jsonify({"qrEnlem": 41.51238882, "qrBoylam": 36.11935778}), 200

# 7. Hava Savunma Sistemi (HSS)
@app.route('/api/hss_koordinatlari', methods=['GET'])
def hss():
    print("[HSS BÖLGELERİ SORGULANDI]")
    cevap = {
        "sunucusaati": get_saat(),
        "hss_koordinat_bilgileri": [
            {"id": 0, "hssEnlem": 40.23260922, "hssBoylam": 29.00573015, "hssYaricap": 50},
            {"id": 1, "hssEnlem": 40.23351019, "hssBoylam": 28.99976492, "hssYaricap": 50},
            {"id": 2, "hssEnlem": 40.23105297, "hssBoylam": 29.00744677, "hssYaricap": 75}
        ]
    }
    return jsonify(cevap), 200

if __name__ == '__main__':
    print("=====================================================")
    print(" SAHTE TEKNOFEST SUNUCUSU BAŞLATILDI (127.0.0.25:5000)")
    print("=====================================================")
    # YKİ'deki SERVER_URL adresiyle aynı olan IP ve Port
    app.run(host='127.0.0.25', port=5000)
