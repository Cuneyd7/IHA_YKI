import requests
import time
import json

# Terminal Renklendirme
class Color:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BOLD = '\033[1m'
    END = '\033[0m'

BASE_URL = "http://127.0.0.1:5000"
session = requests.Session()

def log_success(msg):
    print(f"{Color.GREEN}{Color.BOLD}[BAŞARILI]{Color.END} {msg}")

def log_error(msg):
    print(f"{Color.RED}{Color.BOLD}[HATA]{Color.END} {msg}")

def log_info(msg):
    print(f"{Color.YELLOW}[BİLGİ]{Color.END} {msg}")

# --- TEST SENARYOLARI ---

def test_1_login():
    log_info("Senaryo 1: Oturum Açma (/api/giris) test ediliyor...")
    payload = {"kadi": "takimkadi", "sifre": "sifre"}
    try:
        response = session.post(f"{BASE_URL}/api/giris", json=payload, timeout=5)
        if response.status_code == 200 and response.text.isdigit():
            log_success(f"Giriş yapıldı. Takım No: {response.text}")
            return True
        else:
            log_error(f"Giriş başarısız! Kod: {response.status_code}, Cevap: {response.text}")
            return False
    except Exception as e:
        log_error(f"Sunucuya bağlanılamadı: {e}")
        return False

def test_2_server_time():
    log_info("Senaryo 2: Sunucu Saati (/api/sunucusaati) formatı denetleniyor...")
    try:
        response = session.get(f"{BASE_URL}/api/sunucusaati")
        if response.status_code == 200:
            data = response.json()
            keys = ["gun", "saat", "dakika", "saniye", "milisaniye"]
            if all(k in data for k in keys):
                log_success(f"Sunucu saati formatı doğru: {data}")
            else:
                log_error(f"Eksik anahtarlar var! Beklenen: {keys}")
        else:
            log_error(f"İstek başarısız. Kod: {response.status_code}")
    except Exception as e:
        log_error(f"Hata: {e}")

def test_3_telemetry_types_and_logic():
    log_info("Senaryo 3: Telemetri Veri Tipleri ve 1 Hz Kuralı denetleniyor...")
    
    # Kurala uygun örnek paket
    telem_packet = {
        "takim_numarasi": 1,
        "iha_enlem": 41.123456,    # float olmalı
        "iha_boylam": 28.123456,   # float olmalı
        "iha_irtifa": 100,         # int olmalı
        "iha_dikilme": 5,          # int olmalı
        "iha_yonelme": 180,        # int olmalı
        "iha_yatis": 0,            # int olmalı
        "iha_hiz": 25,             # int olmalı
        "iha_batarya": 85,         # int olmalı
        "iha_otonom": 1,           # int olmalı
        "iha_kilitlenme": 0,       # int olmalı
        "hedef_merkez_X": 0,
        "hedef_merkez_Y": 0,
        "hedef_genislik": 0,
        "hedef_yukseklik": 0,
        "gps_saati": {
            "saat": 12, "dakika": 30, "saniye": 45, "milisaniye": 500
        }
    }

    # Tip Doğrulaması (Script tarafında ön denetim)
    if not isinstance(telem_packet["iha_enlem"], float) or not isinstance(telem_packet["iha_boylam"], float):
        log_error("Koordinat verileri float tipinde değil!")
        return

    # Gönderim testi
    try:
        resp = session.post(f"{BASE_URL}/api/telemetri_gonder", json=telem_packet)
        if resp.status_code == 200:
            log_success("Telemetri paketi kabul edildi.")
            data = resp.json()
            if "konumBilgileri" in data and "sunucusaati" in data:
                log_success("Cevap içeriği (Rakip konumları ve saat) eksiksiz.")
            else:
                log_error("Cevapta 'konumBilgileri' veya 'sunucusaati' eksik!")
        else:
            log_error(f"Telemetri reddedildi. Kod: {resp.status_code}")

        # 1 Hz Kuralı (Hızlı gönderim hatası testi)
        log_info("Spam testi yapılıyor (2 Hz üstü gönderim)...")
        for _ in range(3):
            session.post(f"{BASE_URL}/api/telemetri_gonder", json=telem_packet)
        
        fast_resp = session.post(f"{BASE_URL}/api/telemetri_gonder", json=telem_packet)
        if fast_resp.status_code == 400:
            log_success("KURAL DOĞRULANDI: Sunucu hızlı istekleri (2 Hz+) başarıyla reddetti (400).")
        else:
            log_error(f"KURAL İHLALİ: Sunucu çok hızlı gelen isteklere 400 dönmedi! Kod: {fast_resp.status_code}")
    except Exception as e:
        log_error(f"Hata: {e}")

def test_4_missions():
    log_info("Senaryo 4: Kilitlenme ve Kamikaze operasyonları test ediliyor...")
    
    try:
        # Kilitlenme
        lock_data = {
            "kilitlenmeBitisZamani": {"saat": 10, "dakika": 5, "saniye": 30, "milisaniye": 0},
            "otonom_kilitlenme": 1
        }
        r_lock = session.post(f"{BASE_URL}/api/kilitlenme_bilgisi", json=lock_data)
        if r_lock.status_code == 200:
            log_success("Kilitlenme bilgisi gönderimi başarılı.")
        else:
            log_error(f"Kilitlenme hatası: {r_lock.status_code}")

        # Kamikaze
        kami_data = {
            "kamikazeBaslangicZamani": {"saat": 11, "dakika": 0, "saniye": 0, "milisaniye": 0},
            "kamikazeBitisZamani": {"saat": 11, "dakika": 0, "saniye": 45, "milisaniye": 0},
            "qrMetni": "teknofest2026"
        }
        r_kami = session.post(f"{BASE_URL}/api/kamikaze_bilgisi", json=kami_data)
        if r_kami.status_code == 200:
            log_success("Kamikaze bilgisi gönderimi başarılı.")
        else:
            log_error(f"Kamikaze hatası: {r_kami.status_code}")
    except Exception as e:
        log_error(f"Hata: {e}")

def test_5_coordinates():
    log_info("Senaryo 5: QR ve HSS Koordinat alımı test ediliyor...")
    
    try:
        # QR
        r_qr = session.get(f"{BASE_URL}/api/qr_koordinati")
        if r_qr.status_code == 200:
            log_success(f"QR Koordinatları alındı: {r_qr.json()}")
        else:
            log_error(f"QR koordinat alımı başarısız. Kod: {r_qr.status_code}")

        # HSS
        r_hss = session.get(f"{BASE_URL}/api/hss_koordinatlari")
        if r_hss.status_code == 200:
            log_success(f"HSS listesi alındı ({len(r_hss.json().get('hss_koordinat_bilgileri', []))} sistem).")
        else:
            log_error(f"HSS koordinat alımı başarısız. Kod: {r_hss.status_code}")
    except Exception as e:
        log_error(f"Hata: {e}")

# --- ANA ÇALIŞTIRICI ---

if __name__ == "__main__":
    print(f"\n{Color.BOLD}=== TEKNOFEST SAVAŞAN İHA SİSTEM TESTİ BAŞLATILDI ==={Color.END}\n")
    
    if test_1_login():
        test_2_server_time()
        test_3_telemetry_types_and_logic()
        test_4_missions()
        test_5_coordinates()
        
    print(f"\n{Color.BOLD}=== TEST TAMAMLANDI ==={Color.END}\n")
