# OPTİMİZASYON: Multiprocessing video işleme modülü
# Bu dosya ayrı bir process'te çalışır — GIL'den tamamen bağımsız çekirdeğe taşır.
# Windows spawn mekanizması nedeniyle ana modülden (yerkontrol.py) ayrı tutulmalıdır.

import cv2
import time


def kamera_process_fn(queue, video_path, w, h):
    """
    Ayrı CPU çekirdeğinde video okuma + resize.
    Queue doluysa eski kareleri atar (Frame Dropping).
    """
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            print(f"[VideoWorker] Açılamadı: {video_path}")
            return

        while True:
            ret, frame = cap.read()
            if not ret:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue

            # OPTİMİZASYON: INTER_NEAREST en hızlı interpolasyon — gereksiz kalite kaybı yok
            frame = cv2.resize(frame, (w, h), interpolation=cv2.INTER_NEAREST)
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            # OPTİMİZASYON: Kare Atlama (Frame Dropping) — kuyruk doluysa eskiyi at
            while not queue.empty():
                try:
                    queue.get_nowait()
                except Exception:
                    break

            try:
                queue.put_nowait(frame_rgb)
            except Exception:
                pass

            time.sleep(0.030)  # ~33fps capture rate

    except Exception as e:
        print(f"[VideoWorker] Hata: {e}")
