"""
YKİ OpenGL - Pygame Donanım İvmelendirmeli Sürüm (Glass Cockpit UI)
- Ortadaki ufuk çizgisi kaldırıldı.
- HUD üstüne Pusula, Sol ve Sağ tarafa bağımsız Roll ve Pitch yuvarlak kadranları (Artificial Horizon) eklendi.
- KUSURSUZ OPTİMİZASYON: Z-Index Sıfır Gecikmeli Sekmeler, Multithreading Ağ.
- YENİ: Harita Üzerinde Canlı Rakip Radarı, HSS Çemberleri ve QR Hedefi!
- YENİ: Telemetri Veri Tipi Optimizasyonu (Katı Integer/Float Dönüşümü)
"""

import customtkinter as ctk
import tkinter as tk
from pymavlink import mavutil
import math
import os
import threading
import multiprocessing
import time as _time
import queue as _queue
try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False
# OPTİMİZASYON: Asenkron ağ mimarisi için asyncio ve aiohttp
import asyncio
try:
    import aiohttp
    AIOHTTP_OK = True
except ImportError:
    AIOHTTP_OK = False
try:
    import numpy as np
    NUMPY_OK = True
except ImportError:
    NUMPY_OK = False
from PIL import Image, ImageTk, ImageDraw, ImageFont

# --- EKSTRA MODÜLLER ---
try:
    import cv2
    from PIL import Image, ImageTk, ImageDraw
    import tkintermapview
    EKSTRA_MODULLER_OK = True
except ImportError:
    EKSTRA_MODULLER_OK = False
    print("Modüller eksik! 'pip install opencv-python pillow tkintermapview' çalıştırın.")

try:
    import pygame
    import ctypes
    from OpenGL.GL import *
    from OpenGL.GLU import *
    OPENGL_OK = True
except ImportError:
    OPENGL_OK = False
    print("Modül eksik! 'pip install pygame-ce PyOpenGL' çalıştırın.")

# ══════════════════════════════════════════════════════════════
#  OBJ YÜKLEYİCİ VE 3D GEOMETRİ
# ══════════════════════════════════════════════════════════════
class ObjLoader:
    def __init__(self, filename, scale=1.0):
        self.vertices = []
        self.faces = []
        self.loaded = False
        try:
            raw_v = []
            with open(filename, 'r') as f:
                for line in f:
                    if line.startswith('v '):
                        p = line.strip().split()
                        raw_v.append([float(p[1]), float(p[2]), float(p[3])])
                    elif line.startswith('f '):
                        parts = line.strip().split()[1:]
                        face = [int(p.split('/')[0])-1 for p in parts]
                        self.faces.append(face)
            
            if raw_v:
                min_x = min(v[0] for v in raw_v)
                max_x = max(v[0] for v in raw_v)
                min_y = min(v[1] for v in raw_v)
                max_y = max(v[1] for v in raw_v)
                min_z = min(v[2] for v in raw_v)
                max_z = max(v[2] for v in raw_v)

                cx = (max_x + min_x) / 2.0
                cy = (max_y + min_y) / 2.0
                cz = (max_z + min_z) / 2.0

                max_dim = max(max_x - min_x, max_y - min_y, max_z - min_z)
                if max_dim == 0: max_dim = 1.0

                for v in raw_v:
                    nx = ((v[0] - cx) / max_dim) * 2.0 * scale
                    ny = ((v[1] - cy) / max_dim) * 2.0 * scale
                    nz = ((v[2] - cz) / max_dim) * 2.0 * scale
                    self.vertices.append([nx, ny, nz])

            self.loaded = True
        except:
            pass

def compile_obj_list(obj):
    lst = glGenLists(1)
    glNewList(lst, GL_COMPILE)
    glColor3f(0.25, 0.35, 0.32)
    glBegin(GL_TRIANGLES)
    for face in obj.faces:
        if len(face) < 3: continue
        try:
            vs = [obj.vertices[i] for i in face[:3]]
            a = [vs[1][k]-vs[0][k] for k in range(3)]
            b = [vs[2][k]-vs[0][k] for k in range(3)]
            n = [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]
            mag = math.sqrt(sum(x*x for x in n)) or 1
            glNormal3f(n[0]/mag, n[1]/mag, n[2]/mag)
            for vi in face[:3]: glVertex3fv(obj.vertices[vi])
            if len(face) == 4:
                vs4 = [obj.vertices[i] for i in [face[0],face[2],face[3]]]
                a=[vs4[1][k]-vs4[0][k] for k in range(3)]; b=[vs4[2][k]-vs4[0][k] for k in range(3)]
                n=[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
                mag=math.sqrt(sum(x*x for x in n)) or 1
                glNormal3f(n[0]/mag,n[1]/mag,n[2]/mag)
                for vi in [face[0],face[2],face[3]]: glVertex3fv(obj.vertices[vi])
        except: pass
    glEnd()
    glEndList()
    return lst

def build_procedural_gl_lists():
    C = (205/255, 218/255, 232/255) 
    def tube_ring(cx, cy, cz, rx, ry, N=24):
        return [(cx + rx*math.cos(2*math.pi*i/N), cy + ry*math.sin(2*math.pi*i/N), cz) for i in range(N)]

    def draw_tube(prof, N=24):
        rings = [tube_ring(0, 0, z, rx, ry, N) for z, rx, ry in prof]
        for ri in range(len(rings)-1):
            r0, r1 = rings[ri], rings[ri+1]
            glBegin(GL_QUADS)
            for i in range(N):
                j = (i+1)%N
                v0 = r0[i]; v1 = r0[j]; v2 = r1[j]; v3 = r1[i]
                nx = (v0[0]+v3[0])/2; ny = (v0[1]+v3[1])/2; nz = 0
                mag = math.sqrt(nx*nx+ny*ny) or 1
                glNormal3f(nx/mag, ny/mag, 0)
                glVertex3fv(v3); glVertex3fv(v2); glVertex3fv(v1); glVertex3fv(v0)
            glEnd()

    lst = glGenLists(1)
    glNewList(lst, GL_COMPILE)
    glColor3f(*C)

    fus_prof = [
        (-1.22, 0.000, 0.000), (-1.10, 0.020, 0.016), (-0.90, 0.055, 0.042),
        (-0.65, 0.090, 0.070), (-0.35, 0.116, 0.090), (-0.05, 0.128, 0.100),
        ( 0.20, 0.126, 0.098), ( 0.45, 0.115, 0.090), ( 0.68, 0.098, 0.076),
        ( 0.88, 0.076, 0.060), ( 1.04, 0.052, 0.042), ( 1.16, 0.028, 0.022),
        ( 1.22, 0.006, 0.005),
    ]
    draw_tube(fus_prof, N=28)

    for side in [-1, 1]:
        stations = [(0.00, -0.080, 0.280, 0.020), (0.40, -0.078, 0.265, 0.016), (0.90, -0.072, 0.248, 0.012), (1.42, -0.064, 0.232, 0.008), (1.88, -0.058, 0.218, 0.005)]
        glBegin(GL_QUADS)
        for i in range(len(stations)-1):
            y0,zf0,zr0,th0 = stations[i]; y1,zf1,zr1,th1 = stations[i+1]
            glNormal3f(0,1,0); glVertex3f(side*y0, th0*0.5, zf0); glVertex3f(side*y0, th0*0.5, zr0); glVertex3f(side*y1, th1*0.5, zr1); glVertex3f(side*y1, th1*0.5, zf1)
            glNormal3f(0,-1,0); glVertex3f(side*y0, -th0*0.5, zf0); glVertex3f(side*y1, -th1*0.5, zf1); glVertex3f(side*y1, -th1*0.5, zr1); glVertex3f(side*y0, -th0*0.5, zr0)
            glNormal3f(0,0,-1); glVertex3f(side*y0, th0*0.5, zf0); glVertex3f(side*y1, th1*0.5, zf1); glVertex3f(side*y1, -th1*0.5, zf1); glVertex3f(side*y0, -th0*0.5, zf0)
            glNormal3f(0,0,1); glVertex3f(side*y0, th0*0.5, zr0); glVertex3f(side*y0, -th0*0.5, zr0); glVertex3f(side*y1, -th1*0.5, zr1); glVertex3f(side*y1, th1*0.5, zr1)
        yn,zfn,zrn,thn = stations[-1]
        glNormal3f(side,0,0); glVertex3f(side*yn, thn*0.5, zfn); glVertex3f(side*yn, thn*0.5, zrn); glVertex3f(side*yn, -thn*0.5, zrn); glVertex3f(side*yn, -thn*0.5, zfn)
        glEnd()

        hstab = [(0.00, 0.888, 1.058, 0.014), (0.20, 0.890, 1.050, 0.011), (0.45, 0.895, 1.042, 0.008), (0.60, 0.898, 1.036, 0.006)]
        glBegin(GL_QUADS)
        for i in range(len(hstab)-1):
            y0,zf0,zr0,th0 = hstab[i]; y1,zf1,zr1,th1 = hstab[i+1]; off=0.042 
            glNormal3f(0,1,0); glVertex3f(side*y0, off+th0*0.5, zf0); glVertex3f(side*y0, off+th0*0.5, zr0); glVertex3f(side*y1, off+th1*0.5, zr1); glVertex3f(side*y1, off+th1*0.5, zf1)
            glNormal3f(0,-1,0); glVertex3f(side*y0, off-th0*0.5, zf0); glVertex3f(side*y1, off-th1*0.5, zf1); glVertex3f(side*y1, off-th1*0.5, zr1); glVertex3f(side*y0, off-th0*0.5, zr0)
        glEnd()

    TH=0.009
    vstab = [(0.038, 0.882, 1.108), (0.100, 0.886, 1.104), (0.180, 0.896, 1.099), (0.268, 0.910, 1.092), (0.345, 0.932, 1.086), (0.405, 0.948, 1.080)]
    glBegin(GL_QUADS)
    for i in range(len(vstab)-1):
        y0,zf0,zr0 = vstab[i]; y1,zf1,zr1 = vstab[i+1]
        glNormal3f(1,0,0); glVertex3f( TH/2,y0,zf0); glVertex3f( TH/2,y0,zr0); glVertex3f( TH/2,y1,zr1); glVertex3f( TH/2,y1,zf1)
        glNormal3f(-1,0,0); glVertex3f(-TH/2,y0,zf0); glVertex3f(-TH/2,y1,zf1); glVertex3f(-TH/2,y1,zr1); glVertex3f(-TH/2,y0,zr0)
        glNormal3f(0,0,-1); glVertex3f( TH/2,y0,zf0); glVertex3f(-TH/2,y0,zf0); glVertex3f(-TH/2,y1,zf1); glVertex3f( TH/2,y1,zf1)
    glEnd()
    glEndList()
    return lst

# ══════════════════════════════════════════════════════════════
#  PYGAME HUD THREAD (DONANIMSAL İVMELENDİRME BURADA!)
# ══════════════════════════════════════════════════════════════
HUD_W, HUD_H   = 600, 700
SON_HUD_KARESI = None
HUD_KILIDI     = threading.Lock()

def _hud_arka_plan():
    global SON_HUD_KARESI
    try:
        os.environ['SDL_VIDEO_WINDOW_POS'] = "-5000,-5000"
        pygame.init()
        pygame.display.gl_set_attribute(pygame.GL_MULTISAMPLEBUFFERS, 1)
        pygame.display.gl_set_attribute(pygame.GL_MULTISAMPLESAMPLES, 4)
        pygame.display.gl_set_attribute(pygame.GL_DEPTH_SIZE, 24)

        screen = pygame.display.set_mode((HUD_W, HUD_H), pygame.OPENGL | pygame.DOUBLEBUF | pygame.NOFRAME)
        glEnable(GL_DEPTH_TEST); glDepthFunc(GL_LESS)
        glEnable(GL_CULL_FACE);  glCullFace(GL_BACK)
        glEnable(GL_MULTISAMPLE)
        glShadeModel(GL_SMOOTH)
        glEnable(GL_NORMALIZE)
        glEnable(GL_LIGHTING); glEnable(GL_LIGHT0)
        glLightfv(GL_LIGHT0, GL_POSITION, [5.0,  8.0, 10.0, 1.0])
        glLightfv(GL_LIGHT0, GL_AMBIENT,  [0.40, 0.42, 0.45, 1.0])
        glLightfv(GL_LIGHT0, GL_DIFFUSE,  [0.75, 0.75, 0.78, 1.0])
        glLightfv(GL_LIGHT0, GL_SPECULAR, [0.30, 0.30, 0.32, 1.0])
        glEnable(GL_LIGHT1)
        glLightfv(GL_LIGHT1, GL_POSITION, [-4.0, 3.0, 5.0, 1.0])
        glLightfv(GL_LIGHT1, GL_DIFFUSE,  [0.25, 0.25, 0.28, 1.0])
        glEnable(GL_COLOR_MATERIAL)
        glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)
        glMaterialfv(GL_FRONT, GL_SPECULAR, [0.3, 0.3, 0.35, 1.0])
        glMaterialf(GL_FRONT, GL_SHININESS, 32.0)

        obj = ObjLoader(OBJ_FILE, scale=OBJ_SCALE)
        model_list = compile_obj_list(obj) if (obj.loaded and obj.faces) else build_procedural_gl_lists()

        pbo_ok = False
        pbo_ids = [0, 0]
        PIX_BYTES = HUD_W * HUD_H * 3

        try:
            pbo_ids = list(glGenBuffers(2))
            for pid in pbo_ids:
                glBindBuffer(GL_PIXEL_PACK_BUFFER, pid)
                glBufferData(GL_PIXEL_PACK_BUFFER, PIX_BYTES, None, GL_STREAM_READ)
            glBindBuffer(GL_PIXEL_PACK_BUFFER, 0)
            pbo_ok = True
        except Exception: pass

        if NUMPY_OK: np_buf = np.empty((HUD_H, HUD_W, 3), dtype=np.uint8)

        ROLL_OMEGA  = 8.0;   ROLL_ZETA  = 1.0   
        PITCH_OMEGA = 5.0;   PITCH_ZETA = 1.1   
        YAW_OMEGA   = 3.0;   YAW_ZETA   = 1.2   

        roll_pos  = 0.0; roll_vel  = 0.0
        pitch_pos = 0.0; pitch_vel = 0.0
        yaw_vis   = 0.0; yaw_vel   = 0.0   

        def rk4(pos, vel, target, omega, zeta, dt):
            def d(p, v):
                a = -2.0*zeta*omega*v - omega*omega*(p - target)
                return v, a
            k1p, k1v = d(pos,           vel)
            k2p, k2v = d(pos+k1p*dt*.5, vel+k1v*dt*.5)
            k3p, k3v = d(pos+k2p*dt*.5, vel+k2v*dt*.5)
            k4p, k4v = d(pos+k3p*dt,    vel+k3v*dt)
            return (pos + (k1p+2*k2p+2*k3p+k4p)*dt/6,
                    vel + (k1v+2*k2v+2*k3v+k4v)*dt/6)

        FRAME_DT  = 1.0 / 120.0   
        prev_time = _time.perf_counter()
        next_frame = prev_time
        pbo_idx = 0; first_frame = True

        while True:
            try:
                next_frame += FRAME_DT
                sleep_t = next_frame - _time.perf_counter() - 0.001
                if sleep_t > 0: _time.sleep(sleep_t)
                while _time.perf_counter() < next_frame: pass   

                now = _time.perf_counter()
                dt  = min(now - prev_time, 0.020)   
                prev_time = now

                pygame.event.pump()

                mav_rr = D.get("rollspeed",  0.0)
                mav_pr = D.get("pitchspeed", 0.0)
                mav_yr = D.get("yawspeed",   0.0)
                
                k_rate = 1.0 - math.exp(-dt / 0.015)
                roll_vel  += (mav_rr - roll_vel)  * k_rate * 0.45
                pitch_vel += (mav_pr - pitch_vel) * k_rate * 0.35
                yaw_vel   += (mav_yr - yaw_vel)   * k_rate * 0.30

                roll_pos,  roll_vel  = rk4(roll_pos,  roll_vel, D.get("roll",  0.0), ROLL_OMEGA,  ROLL_ZETA,  dt)
                pitch_pos, pitch_vel = rk4(pitch_pos, pitch_vel, D.get("pitch", 0.0), PITCH_OMEGA, PITCH_ZETA, dt)

                coordinated_yaw = roll_pos * 0.12
                yaw_vis, yaw_vel = rk4(yaw_vis, yaw_vel, coordinated_yaw, YAW_OMEGA, YAW_ZETA, dt)

                glViewport(0, 0, HUD_W, HUD_H)
                glClearColor(0.02, 0.04, 0.10, 1.0)
                glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
                glMatrixMode(GL_PROJECTION); glLoadIdentity()
                gluPerspective(50, HUD_W / HUD_H, 0.3, 200.0)
                glMatrixMode(GL_MODELVIEW); glLoadIdentity()

                glTranslatef(0.0, -0.28, -2.6)

                glRotatef(math.degrees(yaw_vis * 0.25), 0, 1, 0)  
                glRotatef(math.degrees( pitch_pos),     1, 0, 0)  
                glRotatef(math.degrees(-roll_pos),      0, 0, 1)  

                glEnable(GL_LIGHTING)
                glColor3f(1, 1, 1)
                glCallList(model_list)

                if pbo_ok:
                    glBindBuffer(GL_PIXEL_PACK_BUFFER, pbo_ids[pbo_idx])
                    glPixelStorei(GL_PACK_ALIGNMENT, 1)
                    glReadPixels(0, 0, HUD_W, HUD_H, GL_RGB, GL_UNSIGNED_BYTE, 0)
                    if not first_frame:
                        glBindBuffer(GL_PIXEL_PACK_BUFFER, pbo_ids[1-pbo_idx])
                        ptr = glMapBuffer(GL_PIXEL_PACK_BUFFER, GL_READ_ONLY)
                        if ptr:
                            if NUMPY_OK:
                                ctypes.memmove(np_buf.ctypes.data, ptr, PIX_BYTES)
                                glUnmapBuffer(GL_PIXEL_PACK_BUFFER)
                                with HUD_KILIDI: SON_HUD_KARESI = Image.fromarray(np_buf[::-1].copy())
                            else:
                                raw = ctypes.string_at(ptr, PIX_BYTES)
                                glUnmapBuffer(GL_PIXEL_PACK_BUFFER)
                                img = Image.frombytes("RGB",(HUD_W,HUD_H),raw).transpose(Image.FLIP_TOP_BOTTOM)
                                with HUD_KILIDI: SON_HUD_KARESI = img
                        else: glUnmapBuffer(GL_PIXEL_PACK_BUFFER)
                    glBindBuffer(GL_PIXEL_PACK_BUFFER, 0)
                    first_frame = False; pbo_idx = 1 - pbo_idx
                else:
                    glPixelStorei(GL_PACK_ALIGNMENT, 1)
                    if NUMPY_OK:
                        glReadPixels(0,0,HUD_W,HUD_H,GL_RGB,GL_UNSIGNED_BYTE,np_buf)
                        with HUD_KILIDI: SON_HUD_KARESI = Image.fromarray(np_buf[::-1].copy())
                    else:
                        raw = glReadPixels(0,0,HUD_W,HUD_H,GL_RGB,GL_UNSIGNED_BYTE)
                        img = Image.frombytes("RGB",(HUD_W,HUD_H),raw).transpose(Image.FLIP_TOP_BOTTOM)
                        with HUD_KILIDI: SON_HUD_KARESI = img
                pygame.display.flip()

            except Exception: _time.sleep(0.05)
    except Exception as e: print("Pygame Başlatma Hatası:", e)

if OPENGL_OK: threading.Thread(target=_hud_arka_plan, daemon=True).start()

# ══════════════════════════════════════════════════════════════
#  AYARLAR, DEĞİŞKENLER & HARİTA SİMGESİ
# ══════════════════════════════════════════════════════════════
OBJ_FILE  = "karan.obj"   
OBJ_SCALE = 1            
D = {
    "roll":0.0, "pitch":0.0, "yaw":0.0, "rollspeed":0.0, "pitchspeed":0.0, "yawspeed":0.0,
    "airspeed":0.0, "alt":0.0, "mode":"---", "gs":0.0, "heading":0.0, "vx":0.0, "vy":0.0,
    "att_time": 0.0, "rpm":0, "throttle_pct":0, "motor_current":0.0,
    "batt_volt":0.0, "batt_amp":0.0, "batt_mah":0, "batt_pct":0,
    "lat":0.0, "lon":0.0, "sats":0,
    "gps_saat":0, "gps_dakika":0, "gps_saniye":0, "gps_ms":0,
}

MAP_ILK_ODAK = False; SON_HARITA_GUNCELLEME = 0; MAP_ODAK_MODU = ["IHA"]
# OPTİMİZASYON: Thread-safe Queue — frame dropping ile en taze kareyi iletir
_KAMERA_QUEUE = _queue.Queue(maxsize=3)
SON_KAMERA_KARESI = None; KAMERA_KILIDI = threading.Lock()

SMOOTH_HEADING = 0.0; SMOOTH_UI_ROLL = 0.0; SMOOTH_UI_PITCH = 0.0
MAP_SMOOTH_LAT = [0.0]; MAP_SMOOTH_LON = [0.0]
MAP_HEDEF_LAT = [0.0]; MAP_HEDEF_LON = [0.0]
MAP_HEDEF_HEADING = [0]; MAP_SMOOTH_HEADING = [0.0]
MAP_LERP_HAZIR = [False]; MAP_GPS_TIME = [0.0]     

HEDEF_KAMERA_W = 450; HEDEF_KAMERA_H = 350
_msl_val = [0.0]; _agl_val = [0.0]; ALT_TOGGLE_MODE = ["MSL"]
LAST_UI_ROLL = [-999.0]; LAST_UI_PITCH = [-999.0]; LAST_UI_HEADING = [-999.0]
LAST_MAP_UPDATE_TIME = [0.0]; LAST_TEAM_MAP_UPDATE_TIME = [0.0]

RAKIP_MARKER_NESNELERI = {}
HSS_POLI_NESNELERI = []
QR_MARKER = [None]

def ucak_base_ciz():
    if not EKSTRA_MODULLER_OK: return None
    SS = 4; S = 64 * SS; cx, cy = S // 2, S // 2
    img  = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    fw, fh = int(4*SS), int(30*SS)
    draw.ellipse([cx-fw, cy-fh, cx+fw, cy+fh], fill="#cdd9e5", outline="#8faabb", width=SS)
    draw.polygon([(cx - int(3*SS), cy - int(4*SS)), (cx - int(30*SS), cy + int(8*SS)), (cx - int(29*SS), cy + int(13*SS)), (cx - int(2*SS), cy + int(2*SS))], fill="#b8c8d8", outline="#8faabb", width=SS)
    draw.polygon([(cx + int(3*SS), cy - int(4*SS)), (cx + int(30*SS), cy + int(8*SS)), (cx + int(29*SS), cy + int(13*SS)), (cx + int(2*SS), cy + int(2*SS))], fill="#b8c8d8", outline="#8faabb", width=SS)
    draw.polygon([(cx - int(2*SS), cy + int(20*SS)), (cx - int(12*SS), cy + int(26*SS)), (cx - int(11*SS), cy + int(29*SS)), (cx - int(1*SS), cy + int(23*SS))], fill="#a0b4c4", outline="#8faabb", width=SS)
    draw.polygon([(cx + int(2*SS), cy + int(20*SS)), (cx + int(12*SS), cy + int(26*SS)), (cx + int(11*SS), cy + int(29*SS)), (cx + int(1*SS), cy + int(23*SS))], fill="#a0b4c4", outline="#8faabb", width=SS)
    draw.ellipse([cx-int(2*SS), cy-fh+int(1*SS), cx+int(2*SS), cy-fh+int(5*SS)], fill="#ef4444")
    return img.resize((64, 64), Image.LANCZOS)

def ucak_ikon_onbellegi_olustur(base_img):
    if base_img is None: return {}
    cache = {}
    for deg in range(360): cache[deg] = ImageTk.PhotoImage(base_img.rotate(-deg, resample=Image.BICUBIC, expand=False))
    return cache

def haritaya_hss_ciz(hss_listesi):
    if not EKSTRA_MODULLER_OK: return
    for p in HSS_POLI_NESNELERI: 
        try: p.delete()
        except: pass
    HSS_POLI_NESNELERI.clear()
    
    for h in hss_listesi:
        lat = h.get("hssEnlem", 0)
        lon = h.get("hssBoylam", 0)
        r_m = h.get("hssYaricap", 0)
        if r_m <= 0: continue
        
        path = []
        for aci in range(0, 361, 10):
            rad = math.radians(aci)
            d_lat = (r_m / 111320.0) * math.cos(rad)
            d_lon = (r_m / (111320.0 * math.cos(math.radians(lat)))) * math.sin(rad)
            path.append((lat + d_lat, lon + d_lon))
        
        try:
            cizgi = map_widget.set_path(path, color="#ef4444", width=3)
            HSS_POLI_NESNELERI.append(cizgi)
            m = map_widget.set_marker(lat, lon, text=f"HSS ID:{h.get('id')} (r={r_m}m)")
            HSS_POLI_NESNELERI.append(m)
        except Exception as e:
            print("HSS Çizim Hatası:", e)

def haritaya_qr_ciz(lat, lon):
    if not EKSTRA_MODULLER_OK: return
    if QR_MARKER[0] is not None:
        try: QR_MARKER[0].delete()
        except: pass
    try:
        QR_MARKER[0] = map_widget.set_marker(lat, lon, text="QR HEDEF BÖLGESİ")
    except: pass

if EKSTRA_MODULLER_OK:
    UCAK_BASE_IMG   = ucak_base_ciz()   
    UCAK_IKON_CACHE = {}                
    UCAK_TK_IMG     = None
    ucak_marker     = None

MAVLINK_PORT = 14552
print(f"MAVLink bağlantısı bekleniyor (UDP {MAVLINK_PORT})...")
try:
    baglanti = mavutil.mavlink_connection(f'udpin:127.0.0.1:{MAVLINK_PORT}')
    baglanti.wait_heartbeat(timeout=0)  
    print(f"[OK] UDP 127.0.0.1:{MAVLINK_PORT} soketi dinleniyor...")
except Exception as e:
    print(f"[HATA] MAVLink bağlantı hatası: {e}")
    baglanti = None


# ══════════════════════════════════════════════════════════════
#  TEKNOFEST PANEL — PAYLAŞILAN STATE
# ══════════════════════════════════════════════════════════════
SERVER_URL      = "http://127.0.0.25:5000"
TAKIM_NO        = [0]
session_cookie  = [None]
sunucu_zaman    = [{}]
diger_takimlar  = [[]]
son_cevap_kodu  = ["-"]
telemetri_aktif = [False]
_panel_log      = []

def plog(msg):
    ts = _time.strftime("%H:%M:%S")
    _panel_log.append(f"[{ts}] {msg}")
    if len(_panel_log) > 200: _panel_log.pop(0)

if REQUESTS_OK:
    _http = requests.Session()
    _retry = Retry(total=2, backoff_factor=0.2, status_forcelist=[500,502,503])
    _http.mount("http://", HTTPAdapter(max_retries=_retry))
else:
    _http = None

def _api_post(endpoint, data):
    if not REQUESTS_OK or not _http: return 0, {}
    try:
        r = _http.post(f"{SERVER_URL}{endpoint}", json=data, cookies=session_cookie[0], timeout=2.0)
        son_cevap_kodu[0] = str(r.status_code)
        try: return r.status_code, r.json()
        except: return r.status_code, {}
    except Exception as e:
        son_cevap_kodu[0] = "ERR"; plog(f"POST {endpoint} hata: {e}"); return 0, {}

def _api_get(endpoint):
    if not REQUESTS_OK or not _http: return 0, {}
    try:
        r = _http.get(f"{SERVER_URL}{endpoint}", cookies=session_cookie[0], timeout=2.0)
        son_cevap_kodu[0] = str(r.status_code)
        try: return r.status_code, r.json()
        except: return r.status_code, {}
    except Exception as e:
        son_cevap_kodu[0] = "ERR"; plog(f"GET {endpoint} hata: {e}"); return 0, {}

def _sunucu_saati_dict():
    s = sunucu_zaman[0]
    return {
        "saat": int(s.get("saat",0)),
        "dakika": int(s.get("dakika",0)),
        "saniye": int(s.get("saniye",0)),
        "milisaniye": int(s.get("milisaniye",0))
    }

def _gps_saati_dict():
    return {
        "saat": int(D.get("gps_saat", 0)),
        "dakika": int(D.get("gps_dakika", 0)),
        "saniye": int(D.get("gps_saniye", 0)),
        "milisaniye": int(D.get("gps_ms", 0))
    }

def _otonom_mu():
    m = D.get("mode","").upper()
    return 1 if any(k in m for k in ["AUTO","GUIDED","LOITER","RTL","CIRCLE"]) else 0

# OPTİMİZASYON: Asenkron telemetri — aiohttp ile ağ gecikmesi diğer thread'leri ASLA bloklamaz
async def _async_telemetri_loop():
    """Asyncio event loop içinde çalışır — sıfır bloklama garantisi."""
    _timeout = aiohttp.ClientTimeout(total=2.0) if AIOHTTP_OK else None
    async with aiohttp.ClientSession(timeout=_timeout) as session:
        while True:
            if telemetri_aktif[0] and TAKIM_NO[0] > 0:
                paket = {
                    "takim_numarasi":  int(TAKIM_NO[0]),
                    "iha_enlem":       float(D.get("lat", 0.0)),
                    "iha_boylam":      float(D.get("lon", 0.0)),
                    "iha_irtifa":      int(_agl_val[0]),
                    "iha_dikilme":     int(max(-90, min(90, math.degrees(D.get("pitch", 0.0))))),
                    "iha_yonelme":     int(D.get("heading", 0)) % 360,
                    "iha_yatis":       int(max(-90, min(90, math.degrees(D.get("roll", 0.0))))),
                    "iha_hiz":         int(max(0, D.get("gs", 0.0))),
                    "iha_batarya":     int(max(0, min(100, D.get("batt_pct", 0)))),
                    "iha_otonom":      int(_otonom_mu()),
                    "iha_kilitlenme":  int(0),
                    "hedef_merkez_X":  int(0),
                    "hedef_merkez_Y":  int(0),
                    "hedef_genislik":  int(0),
                    "hedef_yukseklik": int(0),
                    "gps_saati":       _gps_saati_dict(),
                }
                try:
                    # OPTİMİZASYON: Cookie'yi header olarak gönder (aiohttp uyumu)
                    cookies = {}
                    if session_cookie[0]:
                        cookies = {c.name: c.value for c in session_cookie[0]}
                    async with session.post(f"{SERVER_URL}/api/telemetri_gonder",
                                            json=paket, cookies=cookies) as resp:
                        son_cevap_kodu[0] = str(resp.status)
                        if resp.status == 200:
                            cevap = await resp.json()
                            diger_takimlar[0] = cevap.get("konumBilgileri", [])
                            sunucu_zaman[0]   = cevap.get("sunucusaati", {})
                        elif resp.status not in (0,):
                            plog(f"Telemetri hata: {resp.status}")
                except Exception as e:
                    son_cevap_kodu[0] = "ERR"
                    plog(f"Async telemetri hata: {e}")
            await asyncio.sleep(1.0)

def _start_async_telemetri():
    """Asyncio event loop'u ayrı thread'de çalıştırır."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(_async_telemetri_loop())

# OPTİMİZASYON: aiohttp varsa async kullan, yoksa eski requests fallback
if AIOHTTP_OK:
    threading.Thread(target=_start_async_telemetri, daemon=True).start()
elif REQUESTS_OK:
    def _telemetri_thread_fallback():
        while True:
            if telemetri_aktif[0] and TAKIM_NO[0] > 0:
                paket = {
                    "takim_numarasi":  int(TAKIM_NO[0]),
                    "iha_enlem":       float(D.get("lat", 0.0)),
                    "iha_boylam":      float(D.get("lon", 0.0)),
                    "iha_irtifa":      int(_agl_val[0]),
                    "iha_dikilme":     int(max(-90, min(90, math.degrees(D.get("pitch", 0.0))))),
                    "iha_yonelme":     int(D.get("heading", 0)) % 360,
                    "iha_yatis":       int(max(-90, min(90, math.degrees(D.get("roll", 0.0))))),
                    "iha_hiz":         int(max(0, D.get("gs", 0.0))),
                    "iha_batarya":     int(max(0, min(100, D.get("batt_pct", 0)))),
                    "iha_otonom":      int(_otonom_mu()),
                    "iha_kilitlenme":  int(0),
                    "hedef_merkez_X":  int(0),
                    "hedef_merkez_Y":  int(0),
                    "hedef_genislik":  int(0),
                    "hedef_yukseklik": int(0),
                    "gps_saati":       _gps_saati_dict(),
                }
                kod, cevap = _api_post("/api/telemetri_gonder", paket)
                if kod == 200:
                    diger_takimlar[0] = cevap.get("konumBilgileri", [])
                    sunucu_zaman[0]   = cevap.get("sunucusaati", {})
                elif kod not in (0,):
                    plog(f"Telemetri hata: {kod}")
            _time.sleep(1.0)
    threading.Thread(target=_telemetri_thread_fallback, daemon=True).start()

# ══════════════════════════════════════════════════════════════
#  GUI (ARAYÜZ BAŞLATMA VE STRİNGBELLEKLERİ)
# ══════════════════════════════════════════════════════════════
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")
app = ctk.CTk()
app.geometry("1600x900")
app.title("KARAN İHA-YKİ")
app.configure(bg="#02050e")

if EKSTRA_MODULLER_OK and UCAK_BASE_IMG is not None:
    UCAK_IKON_CACHE = ucak_ikon_onbellegi_olustur(UCAK_BASE_IMG)

SV = {
    "roll": tk.StringVar(value="--- °"), "pitch": tk.StringVar(value="--- °"), "yaw": tk.StringVar(value="--- °"),
    "rs": tk.StringVar(value="--- °/s"), "ps": tk.StringVar(value="--- °/s"), "ys": tk.StringVar(value="--- °/s"),
    "alt": tk.StringVar(value="--- m"), "agl": tk.StringVar(value="--- m"), 
    "as": tk.StringVar(value="--- m/s"), "gs": tk.StringVar(value="--- m/s"), "hdg": tk.StringVar(value="--- °"),
    "hud_spd": tk.StringVar(value="0.0 m/s"), "mode": tk.StringVar(value="---"),
    "lat": tk.StringVar(value="--- °"), "lon": tk.StringVar(value="--- °"), "sat": tk.StringVar(value="--"),
    "vlt": tk.StringVar(value="--.- V"), "bamp": tk.StringVar(value="--.- A"),
    "bmah": tk.StringVar(value="---- mAh"), "bpct": tk.StringVar(value="--- %"),
    "rpm": tk.StringVar(value="----"), "mamp": tk.StringVar(value="--- A"), "thr": tk.StringVar(value="-- %")
}

FB = ctk.CTkFont(family="Consolas", size=22, weight="bold")
FK = ctk.CTkFont(family="Consolas", size=14, weight="bold")
FL = ctk.CTkFont(family="Consolas", size=14)
FU = ctk.CTkFont(family="Consolas", size=11, weight="bold")

# ══ SIFIR GECİKMELİ SEKME SİSTEMİ (Z-INDEX) ════════════════════════
aktif_sekme = [None]
sekme_frames = {}   
sekme_btnler = {}   

def sekme_ac(ad):
    aktif_sekme[0] = ad
    for k, b in sekme_btnler.items():
        if k == ad: b.configure(fg_color="#1e3a5f", text_color="#00ffcc")
        else: b.configure(fg_color="transparent", text_color="#64748b")
        
    if ad in _popout_windows and _popout_windows[ad].winfo_exists():
        return
        
    f = sekme_frames.get(ad)
    if f: 
        f.tkraise() 

_popout_windows = {}   
_kamera_labels = [] 

def pop_out(ad, title):
    if ad in _popout_windows and _popout_windows[ad].winfo_exists():
        _popout_windows[ad].lift(); return

    f = sekme_frames.get(ad)
    if f is None: return

    # OPTİMİZASYON: Pop-out penceresini oluştur
    win = ctk.CTkToplevel(app)
    win.title(f"⤢  {title}")
    win.geometry("1400x860")
    win.configure(bg="#020810")
    win.attributes("-topmost", True) # Öne getir
    _popout_windows[ad] = win

    if ad == "kamera":
        lbl_kamera_pop = tk.Label(win, bg="#000000")
        lbl_kamera_pop.pack(fill="both", expand=True)
        _kamera_labels.append(lbl_kamera_pop)
        
        def on_close_kamera():
            if lbl_kamera_pop in _kamera_labels: _kamera_labels.remove(lbl_kamera_pop)
            win.destroy()
            _popout_windows.pop(ad, None)
            if aktif_sekme[0] == ad: sekme_ac(ad)
        win.protocol("WM_DELETE_WINDOW", on_close_kamera)
        
    elif ad == "yarisma":
        # OPTİMİZASYON: Chrome benzeri akıcılık için içeriği yeni pencereye taşı
        # Eski içeriği temizle ve widget'ları pop-out penceresine kur
        _build_panel(win)

        def on_close_yarisma():
            _popout_windows.pop(ad, None)
            win.destroy()
            # Kapatıldığında akıcı bir şekilde ana frame'e geri kur
            _build_panel(yarisma_frame)
            if aktif_sekme[0] == ad: sekme_ac(ad)
        win.protocol("WM_DELETE_WINDOW", on_close_yarisma)

    if aktif_sekme[0] == ad:
        sekme_ac("yki")

# ── Üst Bar ───────────────────────────────────────────────────
top = ctk.CTkFrame(app, height=52, fg_color="#04080f", corner_radius=0)
top.pack(side="top", fill="x")
top.grid_columnconfigure(1, weight=1)

ctk.CTkLabel(top, text="❖  KARAN İHA YER KONTROL İSTASYONU  ❖", font=FB, text_color="#00ffcc").pack(side="left", padx=20, pady=10)

tab_bar = ctk.CTkFrame(top, fg_color="transparent")
tab_bar.pack(side="right", padx=10, pady=8)

TAB_DEFS = [
    ("yki",      "⬛  YKİ İSTASYONU"),
    ("kamera",   "📷  KAMERA"),
    ("yarisma",  "🏁  YARIŞMA SUNUCUSU"),
]
for k, label in TAB_DEFS:
    b = ctk.CTkButton(tab_bar, text=label, font=ctk.CTkFont(family="Consolas", size=13, weight="bold"),
        fg_color="transparent", text_color="#64748b", hover_color="#0f2a4a", corner_radius=8, height=32, width=180,
        command=lambda x=k: sekme_ac(x))
    b.pack(side="left", padx=3)
    sekme_btnler[k] = b

for k, label in TAB_DEFS:
    if k != "yki": 
        titles = {"kamera":"FPV Kamera - Tam Ekran", "yarisma":"TEKNOFEST Yarışma Sunucusu"}
        ctk.CTkButton(tab_bar, text="⤢", font=ctk.CTkFont(family="Consolas", size=13, weight="bold"),
            fg_color="#050d1a", text_color="#38BDF8", hover_color="#1e3a5f", corner_radius=6, height=32, width=36,
            command=lambda x=k, t=titles[k]: pop_out(x, t)).pack(side="left", padx=(0,6))

# ── Ana sekme container ─────────────
tab_container = ctk.CTkFrame(app, fg_color="transparent", corner_radius=0)
tab_container.pack(fill="both", expand=True)
tab_container.grid_rowconfigure(0, weight=1)
tab_container.grid_columnconfigure(0, weight=1)

# 1. YKİ SEKMESİ
yki_frame = ctk.CTkFrame(tab_container, fg_color="transparent")
yki_frame.grid(row=0, column=0, sticky="nsew")
sekme_frames["yki"] = yki_frame

main = ctk.CTkFrame(yki_frame, fg_color="transparent")
main.pack(fill="both", expand=True, padx=15, pady=15)
main.grid_columnconfigure(0, weight=0, minsize=480); main.grid_columnconfigure(1, weight=1); main.grid_columnconfigure(2, weight=0, minsize=380); main.grid_rowconfigure(0, weight=1)

# ----- SOL SÜTUN -----
left_panel = ctk.CTkFrame(main, width=480, fg_color="transparent")
left_panel.grid(row=0, column=0, padx=(0,10), sticky="nsew")
left_panel.grid_propagate(False) 
left_panel.grid_rowconfigure(0, weight=1); left_panel.grid_rowconfigure(1, weight=1); left_panel.grid_columnconfigure(0, weight=1)

cam_frame = ctk.CTkFrame(left_panel, corner_radius=12, fg_color="#000000", border_width=1, border_color="#000000")
cam_frame.grid(row=0, column=0, pady=(0,5), sticky="nsew"); cam_frame.pack_propagate(False) 
ctk.CTkLabel(cam_frame, text="[ İHA FPV KAMERA ]", font=FK, text_color="#FFFFFF").pack(pady=6)

if EKSTRA_MODULLER_OK:
    lbl_kamera = tk.Label(cam_frame, bg="#040810"); lbl_kamera.pack(expand=True) 

map_frame = ctk.CTkFrame(left_panel, corner_radius=12, fg_color="#000000", border_width=1, border_color="#000000")
map_frame.grid(row=1, column=0, pady=(5,0), sticky="nsew"); map_frame.pack_propagate(False)
map_hdr_row = ctk.CTkFrame(map_frame, fg_color="transparent"); map_hdr_row.pack(fill="x", padx=4, pady=(2,0))
ctk.CTkLabel(map_hdr_row, text="[ CANLI UYDU HARİTASI ]", font=FK, text_color="#FFFFFF").pack(side="left", padx=6, pady=3)

def toggle_map_mode(event=None):
    if MAP_ODAK_MODU[0] == "IHA":
        MAP_ODAK_MODU[0] = "SERBEST"; lbl_map_mod.configure(text="✦ SERBEST", text_color="#F59E0B", fg_color="#2a1a00")
    else:
        MAP_ODAK_MODU[0] = "IHA"; lbl_map_mod.configure(text="✦ İHA KİLİT", text_color="#10B981", fg_color="#022c22")

lbl_map_mod = ctk.CTkLabel(map_hdr_row, text="✦ İHA KİLİT", font=ctk.CTkFont(family="Consolas", size=11, weight="bold"), text_color="#10B981", fg_color="#022c22", corner_radius=5, cursor="hand2", padx=6, pady=2)
lbl_map_mod.pack(side="right", padx=6, pady=3)
lbl_map_mod.bind("<Button-1>", toggle_map_mode)

if EKSTRA_MODULLER_OK:
    map_widget = tkintermapview.TkinterMapView(map_frame, corner_radius=8)
    map_widget.pack(fill="both", expand=True, padx=6, pady=(0,6))
    map_widget.set_tile_server("https://mt0.google.com/vt/lyrs=s&hl=en&x={x}&y={y}&z={z}&s=Ga", max_zoom=22)
    map_widget.set_position(41.0, 28.9); map_widget.set_zoom(12)

# ----- ORTA SÜTUN -----
frame3d = ctk.CTkFrame(main, corner_radius=12, fg_color="#000000", border_width=1, border_color="#000000")
frame3d.grid(row=0, column=1, padx=(0,10), pady=0, sticky="nsew")

def _mav_bg(fn): threading.Thread(target=lambda: _safe_mav(fn), daemon=True).start()
def _safe_mav(fn):
    try: fn()
    except Exception as e: print(f"MAVLink cmd hatası: {e}")
def _arm():
    if baglanti: _mav_bg(baglanti.arducopter_arm)
def _disarm():
    if baglanti: _mav_bg(baglanti.arducopter_disarm)
def _set_mode(m):
    if baglanti: _mav_bg(lambda: baglanti.set_mode(m))
def _takeoff(alt=50):
    if not baglanti: return
    _mav_bg(lambda: baglanti.mav.command_long_send(baglanti.target_system, baglanti.target_component, mavutil.mavlink.MAV_CMD_NAV_TAKEOFF, 0, 0,0,0,0,0,0, alt))

ctrl_bar = ctk.CTkFrame(frame3d, fg_color="#06111a", corner_radius=8, border_width=1, border_color="#000000")
ctrl_bar.pack(fill="x", side="bottom", padx=10, pady=(0,10))
ctrl_bar.pack_propagate(False)
ctrl_bar.configure(height=90) 

for i in range(5): ctrl_bar.grid_columnconfigure(i, weight=1 if i!=2 else 0)
ctrl_bar.grid_columnconfigure(2, minsize=160)
ctrl_bar.grid_rowconfigure(0, weight=1); ctrl_bar.grid_rowconfigure(1, weight=1)

_FKB = ctk.CTkFont(family="Consolas", size=13, weight="bold")

# Satır 1
ctk.CTkButton(ctrl_bar, text="🔓 ARM", fg_color="#14532D", hover_color="#15803d", font=_FKB, text_color="#86efac", command=_arm).grid(row=0, column=0, padx=6, pady=(8,4), sticky="ew")
ctk.CTkButton(ctrl_bar, text="✈ AUTO", fg_color="#1e3a5f", hover_color="#2563eb", font=_FKB, text_color="#e2e8f0", command=lambda:_set_mode("AUTO")).grid(row=0, column=1, padx=6, pady=(8,4), sticky="ew")
ctk.CTkLabel(ctrl_bar, textvariable=SV["mode"], font=ctk.CTkFont(family="Consolas", size=22, weight="bold"), text_color="#FFFFFF", fg_color="#04101a", corner_radius=8).grid(row=0, column=2, rowspan=2, padx=12, pady=8, sticky="nsew")
ctk.CTkButton(ctrl_bar, text="⟳ LOITER", fg_color="#064E3B", hover_color="#059669", font=_FKB, text_color="#e2e8f0", command=lambda:_set_mode("LOITER")).grid(row=0, column=3, padx=6, pady=(8,4), sticky="ew")
ctk.CTkButton(ctrl_bar, text="⬆ TAKEOFF", fg_color="#2e1065", hover_color="#7c3aed", font=_FKB, text_color="#e2e8f0", command=lambda:_takeoff(50)).grid(row=0, column=4, padx=6, pady=(8,4), sticky="ew")

# Satır 2
ctk.CTkButton(ctrl_bar, text="🔒 DISARM", fg_color="#7f1d1d", hover_color="#b91c1c", font=_FKB, text_color="#fca5a5", command=_disarm).grid(row=1, column=0, padx=6, pady=(4,8), sticky="ew")
ctk.CTkButton(ctrl_bar, text="🎯 GUIDED", fg_color="#1e3a5f", hover_color="#2563eb", font=_FKB, text_color="#e2e8f0", command=lambda:_set_mode("GUIDED")).grid(row=1, column=1, padx=6, pady=(4,8), sticky="ew")
ctk.CTkButton(ctrl_bar, text="🏠 RTL", fg_color="#7c2d12", hover_color="#c2410c", font=_FKB, text_color="#e2e8f0", command=lambda:_set_mode("RTL")).grid(row=1, column=3, padx=6, pady=(4,8), sticky="ew")
ctk.CTkButton(ctrl_bar, text="⬇ LAND", fg_color="#4c1d95", hover_color="#6d28d9", font=_FKB, text_color="#e2e8f0", command=lambda:_set_mode("LAND")).grid(row=1, column=4, padx=6, pady=(4,8), sticky="ew")

if OPENGL_OK:
    lbl_hud = tk.Label(frame3d, bg="#040810"); lbl_hud.pack(fill="both", expand=True, padx=2, pady=(8,2))

# ── SAĞ PANEL (Sıfır kasmayan scroll motoru) ────────────
_right_border = ctk.CTkFrame(main, width=395, corner_radius=12, fg_color="#000000", border_width=1, border_color="#000000")
_right_border.grid(row=0, column=2, padx=0, pady=0, sticky="nsew")
_right_border.grid_propagate(False)
_right_border.grid_rowconfigure(0, weight=1); _right_border.grid_columnconfigure(0, weight=1)

_vp = tk.Canvas(_right_border, bg="#000000", highlightthickness=0, bd=0, yscrollincrement=1)
_vp.grid(row=0, column=0, sticky="nsew")

_vsb = tk.Scrollbar(_right_border, orient="vertical", command=_vp.yview, width=5, bg="#000000", troughcolor="#000000", activebackground="#2563eb", relief="flat", bd=0)
_vsb.grid(row=0, column=1, sticky="ns"); _vp.configure(yscrollcommand=_vsb.set)

right = ctk.CTkFrame(_vp, fg_color="#000000", corner_radius=0)
right.grid_columnconfigure(0, weight=1)
_win = _vp.create_window((0, 0), window=right, anchor="nw")

_vp.bind("<Configure>", lambda e: _vp.itemconfig(_win, width=e.width))
right.bind("<Configure>", lambda e: _vp.configure(scrollregion=_vp.bbox("all")))

_sv  = [0.0]; _sp  = [0.0]; _tok = [None]
def _tick():
    v = _sv[0]
    if abs(v) < 1e-5: _sv[0] = 0.0; _tok[0] = None; return
    _sp[0] = max(0.0, min(1.0, _sp[0] + v))
    _vp.yview_moveto(_sp[0])   
    _sv[0] *= 0.82             
    _tok[0] = app.after(8, _tick)

def _sync_pos(e=None): top, _ = _vp.yview(); _sp[0] = top
_vp.bind("<<ScrollbarScroll>>", _sync_pos, add="+")

def _content_height():
    try:
        bb = _vp.bbox("all")
        return bb[3] - bb[1] if bb else 1
    except: return 1

def _mw(e):
    d = getattr(e, 'delta', 0)
    if d == 0: d = -120 if getattr(e,'num',0)==5 else 120
    ch = _content_height()
    impulse = (-d / 120.0) * 25.0 / max(ch, 1)
    _sv[0] = max(-0.06, min(0.06, _sv[0] + impulse))
    top, _ = _vp.yview(); _sp[0] = top
    if _tok[0] is None: _tok[0] = app.after(8, _tick)

def _sb(w):
    try: w.bind("<MouseWheel>", _mw, add="+"); w.bind("<Button-4>", _mw, add="+"); w.bind("<Button-5>", _mw, add="+")
    except: pass
    for c in w.winfo_children(): _sb(c)

_vp.bind("<MouseWheel>", _mw); _vp.bind("<Button-4>", _mw); _vp.bind("<Button-5>", _mw)
app.after(600, lambda: _sb(right))

# OPTİMİZASYON: Ghost (Siyah & Beyaz) Teması
BCOLS = {"#38BDF8": "#000000", "#60A5FA": "#000000", "#00D1FF": "#000000", "#1E40AF": "#000000", "#3B82F6": "#000000", "#93C5FD": "#000000"}
HCOLS = {"#38BDF8": "#000000", "#60A5FA": "#000000", "#00D1FF": "#000000", "#1E40AF": "#000000", "#3B82F6": "#000000", "#93C5FD": "#000000"}
SECTION_FRAMES = []

def section(parent, title, color, row):
    bc = BCOLS.get(color, "#2a3850"); hc = HCOLS.get(color, "#101e30")
    card = ctk.CTkFrame(parent, corner_radius=10, fg_color="#0d1829", border_width=1, border_color=bc)
    card.grid(row=row, column=0, padx=12, pady=6, sticky="ew")
    card._orig_bc = bc; card._orig_hc = hc; card._is_drag_target = False
    
    hdr = ctk.CTkFrame(card, height=30, corner_radius=8, fg_color=hc, cursor="fleur")
    hdr.pack(fill="x", padx=3, pady=(3,0))
    lbl = ctk.CTkLabel(hdr, text=f"  {title}", font=FK, text_color=color, anchor="w", cursor="fleur")
    lbl.pack(side="left", pady=4, padx=6)
    SECTION_FRAMES.append(card)
    
    def drag_start(e):
        card.lift()
        card.configure(border_color="#ffffff", border_width=2); hdr.configure(fg_color="#334155")
        card._drag_cache = [(other, other.winfo_rooty(), other.winfo_rooty() + other.winfo_height()) for other in SECTION_FRAMES if other != card]
        
    def drag_motion(e):
        y = e.y_root
        for other, oy0, oy1 in getattr(card, '_drag_cache', []):
            if oy0 < y < oy1:
                if not getattr(other, '_is_drag_target', False):
                    other.configure(border_color="#facc15", border_width=2); other._is_drag_target = True
            else:
                if getattr(other, '_is_drag_target', False):
                    other.configure(border_color=other._orig_bc, border_width=1); other._is_drag_target = False
                        
    def drag_stop(e):
        card.configure(border_color=card._orig_bc, border_width=1); hdr.configure(fg_color=card._orig_hc)
        current_row = int(card.grid_info()['row'])
        for other in SECTION_FRAMES:
            if getattr(other, '_is_drag_target', False):
                target_row = int(other.grid_info()['row'])
                card.grid(row=target_row); other.grid(row=current_row)
                other.configure(border_color=other._orig_bc, border_width=1); other._is_drag_target = False
                break

    hdr.bind("<ButtonPress-1>", drag_start); hdr.bind("<B1-Motion>", drag_motion); hdr.bind("<ButtonRelease-1>", drag_stop)
    lbl.bind("<ButtonPress-1>", drag_start); lbl.bind("<B1-Motion>", drag_motion); lbl.bind("<ButtonRelease-1>", drag_stop)
    for _w in (hdr, lbl, card):
        _w.bind("<MouseWheel>", _mw, add="+"); _w.bind("<Button-4>", _mw, add="+"); _w.bind("<Button-5>", _mw, add="+")
    return card

def data_row(parent, label, str_var, lcolor="#00ffcc", vsize=22):
    rf = ctk.CTkFrame(parent, fg_color="transparent"); rf.pack(fill="x", padx=16, pady=3)
    l1 = ctk.CTkLabel(rf, text=label, font=FL, text_color="#94a3b8", anchor="w"); l1.pack(side="left")
    vl = ctk.CTkLabel(rf, textvariable=str_var, font=ctk.CTkFont(family="Consolas", size=vsize, weight="bold"), text_color=lcolor, anchor="e"); vl.pack(side="right")
    for _w in (rf, l1, vl): _w.bind("<MouseWheel>", _mw, add="+"); _w.bind("<Button-4>", _mw, add="+"); _w.bind("<Button-5>", _mw, add="+")
    return vl

def div(parent):
    d = ctk.CTkFrame(parent, height=1, fg_color="#1e293b"); d.pack(fill="x", padx=16, pady=2)
    d.bind("<MouseWheel>", _mw, add="+"); d.bind("<Button-4>", _mw, add="+"); d.bind("<Button-5>", _mw, add="+")

c1 = section(right, "▸  YÖNELİM AÇILARI", "#38BDF8", 0)
data_row(c1, "ROLL   (Yatış)", SV["roll"], lcolor="#60A5FA")
div(c1); data_row(c1, "PITCH  (Yunuslama)", SV["pitch"], lcolor="#60A5FA")
div(c1); data_row(c1, "YAW    (Sapma)", SV["yaw"], lcolor="#60A5FA")
ctk.CTkFrame(c1, height=4, fg_color="transparent").pack()

c2 = section(right, "▸  JİROSKOPİK HIZLAR", "#60A5FA", 1)
data_row(c2, "Roll Hızı", SV["rs"], lcolor="#38BDF8", vsize=18)
div(c2); data_row(c2, "Pitch Hızı", SV["ps"], lcolor="#38BDF8", vsize=18)
div(c2); data_row(c2, "Yaw Hızı", SV["ys"], lcolor="#38BDF8", vsize=18)
ctk.CTkFrame(c2, height=4, fg_color="transparent").pack()

c3 = section(right, "▸  SEYRÜSEFER & HIZ", "#00D1FF", 2)
data_row(c3, "İrtifa  MSL", SV["alt"], lcolor="#00D1FF")
div(c3); data_row(c3, "İrtifa  AGL", SV["agl"], lcolor="#93C5FD")
div(c3); data_row(c3, "Hava Hızı", SV["as"], lcolor="#00D1FF")
div(c3); data_row(c3, "Yer Hızı", SV["gs"], lcolor="#00D1FF")
div(c3); data_row(c3, "Pusula", SV["hdg"], lcolor="#00D1FF")
ctk.CTkFrame(c3, height=4, fg_color="transparent").pack()

c4 = section(right, "▸  KONUM & SİSTEM", "#FFFFFF", 3)
div(c4); data_row(c4, "Enlem", SV["lat"], lcolor="#FFFFFF", vsize=16)
data_row(c4, "Boylam", SV["lon"], lcolor="#FFFFFF", vsize=16); div(c4)
bf = ctk.CTkFrame(c4, fg_color="transparent"); bf.pack(fill="x", padx=16, pady=6)
sf = ctk.CTkFrame(bf, fg_color="#000000", corner_radius=6, border_width=1, border_color="#FFFFFF")
sf.pack(side="left", expand=True, fill="x", padx=(0,4))
ctk.CTkLabel(sf, text="SAT (Uydu)", font=FU, text_color="#FFFFFF").pack(pady=(2,0))
ctk.CTkLabel(sf, textvariable=SV["sat"], font=ctk.CTkFont(family="Consolas", size=20, weight="bold"), text_color="#FFFFFF").pack(pady=(0,2))
vf = ctk.CTkFrame(bf, fg_color="#000000", corner_radius=6, border_width=1, border_color="#FFFFFF")
vf.pack(side="right", expand=True, fill="x", padx=(4,0))
ctk.CTkLabel(vf, text="BATARYA", font=FU, text_color="#FFFFFF").pack(pady=(2,0))
lbl_vlt = ctk.CTkLabel(vf, textvariable=SV["vlt"], font=ctk.CTkFont(family="Consolas", size=20, weight="bold"), text_color="#FFFFFF"); lbl_vlt.pack(pady=(0,2))

c5 = section(right, "▸  MOTOR TELEMETRİSİ", "#FFFFFF", 4)
mtr_top = ctk.CTkFrame(c5, fg_color="transparent"); mtr_top.pack(fill="x", padx=12, pady=(6,0))
rpm_card = ctk.CTkFrame(mtr_top, fg_color="#000000", corner_radius=8, border_width=1, border_color="#FFFFFF")
rpm_card.pack(side="left", expand=True, fill="x", padx=(0,4))
ctk.CTkLabel(rpm_card, text="RPM", font=FU, text_color="#FFFFFF").pack(pady=(4,0))
ctk.CTkLabel(rpm_card, textvariable=SV["rpm"], font=ctk.CTkFont(family="Consolas", size=22, weight="bold"), text_color="#FFFFFF").pack(pady=(0,4))
thr_card = ctk.CTkFrame(mtr_top, fg_color="#000000", corner_radius=8, border_width=1, border_color="#FFFFFF")
thr_card.pack(side="right", expand=True, fill="x", padx=(4,0))
ctk.CTkLabel(thr_card, text="THROTTLE", font=FU, text_color="#FFFFFF").pack(pady=(4,0))
ctk.CTkLabel(thr_card, textvariable=SV["thr"], font=ctk.CTkFont(family="Consolas", size=22, weight="bold"), text_color="#FFFFFF").pack(pady=(0,4))
thr_bar_bg = ctk.CTkFrame(c5, height=8, corner_radius=4, fg_color="#1a1a1a"); thr_bar_bg.pack(fill="x", padx=12, pady=(4,2))
thr_bar = ctk.CTkFrame(thr_bar_bg, height=8, corner_radius=4, width=0, fg_color="#FFFFFF"); thr_bar.place(x=0, y=0, relheight=1.0, relwidth=0.0)
div(c5); data_row(c5, "Motor Akımı", SV["mamp"], lcolor="#FFFFFF", vsize=18)
ctk.CTkFrame(c5, height=4, fg_color="transparent").pack()

c6 = section(right, "▸  BATARYA", "#FFFFFF", 5)
batt_top = ctk.CTkFrame(c6, fg_color="transparent"); batt_top.pack(fill="x", padx=12, pady=(6,0))
volt_card = ctk.CTkFrame(batt_top, fg_color="#000000", corner_radius=8, border_width=1, border_color="#FFFFFF")
volt_card.pack(side="left", expand=True, fill="x", padx=(0,4))
ctk.CTkLabel(volt_card, text="GERİLİM", font=FU, text_color="#FFFFFF").pack(pady=(4,0))
lbl_bvolt = ctk.CTkLabel(volt_card, textvariable=SV["vlt"], font=ctk.CTkFont(family="Consolas", size=22, weight="bold"), text_color="#FFFFFF"); lbl_bvolt.pack(pady=(0,4))
bamp_card = ctk.CTkFrame(batt_top, fg_color="#000000", corner_radius=8, border_width=1, border_color="#FFFFFF")
bamp_card.pack(side="right", expand=True, fill="x", padx=(4,0))
ctk.CTkLabel(bamp_card, text="AKIM", font=FU, text_color="#FFFFFF").pack(pady=(4,0))
ctk.CTkLabel(bamp_card, textvariable=SV["bamp"], font=ctk.CTkFont(family="Consolas", size=22, weight="bold"), text_color="#FFFFFF").pack(pady=(0,4))
batt_bar_bg = ctk.CTkFrame(c6, height=12, corner_radius=6, fg_color="#1a1a1a"); batt_bar_bg.pack(fill="x", padx=12, pady=(6,2))
batt_bar_fill = ctk.CTkFrame(batt_bar_bg, height=12, corner_radius=6, fg_color="#FFFFFF"); batt_bar_fill.place(x=0, y=0, relheight=1.0, relwidth=1.0)
lbl_bpct_overlay = ctk.CTkLabel(batt_bar_bg, textvariable=SV["bpct"], font=ctk.CTkFont(family="Consolas", size=10, weight="bold"), text_color="#000000", fg_color="transparent")
lbl_bpct_overlay.place(relx=0.5, rely=0.5, anchor="center")
div(c6)
batt_bot = ctk.CTkFrame(c6, fg_color="transparent"); batt_bot.pack(fill="x", padx=12, pady=(4,6))
ctk.CTkLabel(batt_bot, text="Kalan Kapasite", font=FU, text_color="#FFFFFF").pack(side="left")
ctk.CTkLabel(batt_bot, textvariable=SV["bmah"], font=ctk.CTkFont(family="Consolas", size=18, weight="bold"), text_color="#FFFFFF").pack(side="right")

# OPTİMİZASYON: Görüntü kısmında video yerine sabit görsel (test_image.jpeg) kullanılır.
def _kamera_thread_fn():
    """Arka planda görseli yükler ve Queue'ya basar."""
    try:
        # Klasör içindeki yeni eklenen görseli oku
        # Kullanıcı 'test_image.jpeg' olarak eklediği için bu ismi hedefliyoruz
        img_path = "test_image.jpeg"
        frame = cv2.imread(img_path)
        
        if frame is not None:
            frame = cv2.resize(frame, (HEDEF_KAMERA_W, HEDEF_KAMERA_H), interpolation=cv2.INTER_NEAREST)
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            while True:
                # Görseli kuyruğa bas
                while not _KAMERA_QUEUE.empty():
                    try: _KAMERA_QUEUE.get_nowait()
                    except: break
                try: _KAMERA_QUEUE.put_nowait(frame_rgb)
                except: pass
                _time.sleep(0.1)
        else:
            print(f"HATA: {img_path} dosyası cv2 tarafından okunamadı! Lütfen dosya adını ve formatını kontrol edin.")
    except Exception as e: print("Görsel Yükleme Hatası:", e)

if EKSTRA_MODULLER_OK:
    threading.Thread(target=_kamera_thread_fn, daemon=True).start()

def mavlink_dinleyici_thread():
    global MAP_HEDEF_LAT, MAP_HEDEF_LON, MAP_HEDEF_HEADING, MAP_GPS_TIME, MAP_LERP_HAZIR
    global MAP_SMOOTH_LAT, MAP_SMOOTH_LON, MAP_SMOOTH_HEADING

    # OPTİMİZASYON: Sadece GUI'nin ihtiyaç duyduğu paket tipleri — gerisi continue ile atlanır
    _ALLOWED_TYPES = frozenset({
        'ATTITUDE', 'VFR_HUD', 'SYS_STATUS', 'HEARTBEAT',
        'BATTERY_STATUS', 'ESC_TELEMETRY_1_TO_4', 'ESC_STATUS',
        'RC_CHANNELS', 'GPS_RAW_INT', 'GLOBAL_POSITION_INT'
    })

    while True:
        if baglanti:
            try:
                m = baglanti.recv_match(blocking=True, timeout=0.05)
                if not m: continue
                t = m.get_type()

                # OPTİMİZASYON: İşe yaramayan paketleri hızlıca atla
                if t not in _ALLOWED_TYPES: continue
            
                if t == 'ATTITUDE':
                    D["roll"]=m.roll; D["pitch"]=m.pitch; D["yaw"]=m.yaw
                    D["rollspeed"]=m.rollspeed; D["pitchspeed"]=m.pitchspeed; D["yawspeed"]=m.yawspeed
                    D["att_time"] = _time.perf_counter()
                elif t == 'VFR_HUD':
                    D["airspeed"]=m.airspeed; D["alt"]=m.alt
                    D["heading"]=m.heading;   D["gs"]=m.groundspeed
                    _msl_val[0] = m.alt
                    # OPTİMİZASYON: Throttle bilgisini aynı paket içinde yakala
                    if hasattr(m, 'throttle'):
                        pct = max(0, min(100, int(m.throttle)))
                        if D.get("throttle_pct", 0) == 0: D["throttle_pct"] = pct
                elif t == 'SYS_STATUS':
                    D["batt_volt"] = m.voltage_battery / 1000.0
                    D["batt_amp"] = m.current_battery / 100.0 if m.current_battery != -1 else 0.0
                    D["batt_pct"] = m.battery_remaining if m.battery_remaining != -1 else 0
                elif t == 'HEARTBEAT':
                    D["mode"] = mavutil.mode_string_v10(m)
                elif t == 'BATTERY_STATUS':
                    D["batt_mah"] = m.current_consumed if m.current_consumed != -1 else 0
                elif t in ('ESC_TELEMETRY_1_TO_4', 'ESC_STATUS'):
                    try: D["rpm"] = m.rpm[0] if hasattr(m, 'rpm') else 0; D["motor_current"] = m.current[0] / 100.0 if hasattr(m, 'current') else 0.0
                    except: pass
                elif t == 'RC_CHANNELS':
                    try: D["throttle_pct"] = max(0, min(100, int((getattr(m, 'chan3_raw', 1000) - 1000) / 10)))
                    except: pass
                elif t == 'GPS_RAW_INT':
                    D["sats"] = m.satellites_visible
                    try:
                        us = m.time_usec; ms_t = (us // 1000) % 86400000
                        D["gps_saat"]   = ms_t // 3600000
                        D["gps_dakika"] = (ms_t % 3600000) // 60000
                        D["gps_saniye"] = (ms_t % 60000) // 1000
                        D["gps_ms"]     = ms_t % 1000
                    except: pass
                elif t == 'GLOBAL_POSITION_INT':
                    D["lat"] = m.lat / 1e7; D["lon"] = m.lon / 1e7
                    D["vx"] = m.vx / 100.0; D["vy"] = m.vy / 100.0 
                    _agl_val[0] = m.relative_alt / 1000.0

                    if EKSTRA_MODULLER_OK and D["lat"] != 0.0 and D["lon"] != 0.0:
                        MAP_HEDEF_LAT[0] = D["lat"]; MAP_HEDEF_LON[0] = D["lon"]
                        MAP_HEDEF_HEADING[0] = int(D.get("heading", 0)) % 360
                        MAP_GPS_TIME[0] = _time.perf_counter()
                        if not MAP_LERP_HAZIR[0]:
                            MAP_SMOOTH_LAT[0] = D["lat"]; MAP_SMOOTH_LON[0] = D["lon"]
                            MAP_SMOOTH_HEADING[0] = float(MAP_HEDEF_HEADING[0])
                            MAP_LERP_HAZIR[0] = True
            except Exception: _time.sleep(0.01)
        else: _time.sleep(0.5)

threading.Thread(target=mavlink_dinleyici_thread, daemon=True).start()

# OPTİMİZASYON: Toplu (Batch) StringVar güncelleme sistemi
# MAVLink thread'i değerleri buffer'a yazar, UI thread belirli aralıklarla toplu flush yapar.
# Bu sayede soket okuma hızında StringVar.set() çağrılmaz — UI thread yorulmaz.
_SV_CACHE = {}
_SV_BATCH_BUFFER = {}  # thread-safe dict — MAVLink hızında yazılır, UI hızında okunur
_SV_BATCH_LOCK = threading.Lock()

def _sv_set(key, val):
    """Değeri buffer'a yaz — gerçek StringVar güncellemesi batch flush'ta yapılır."""
    if _SV_CACHE.get(key) != val:
        _SV_CACHE[key] = val
        with _SV_BATCH_LOCK:
            _SV_BATCH_BUFFER[key] = val

def _sv_batch_flush():
    """OPTİMİZASYON: Buffer'daki tüm değişiklikleri tek seferde UI'a uygula."""
    with _SV_BATCH_LOCK:
        if _SV_BATCH_BUFFER:
            updates = _SV_BATCH_BUFFER.copy()
            _SV_BATCH_BUFFER.clear()
        else:
            updates = None
    if updates:
        for key, val in updates.items():
            SV[key].set(val)

def telemetry_ui_loop():
    # OPTİMİZASYON: Buffer'daki tüm SV değişikliklerini UI thread'de toplu flush et
    _sv_batch_flush()
    try:
        _sv_set("roll",  f"{math.degrees(D.get('roll', 0)):+.1f} °")
        _sv_set("pitch", f"{math.degrees(D.get('pitch', 0)):+.1f} °")
        _sv_set("yaw",   f"{math.degrees(D.get('yaw', 0)):+.1f} °")
        _sv_set("rs",    f"{math.degrees(D.get('rollspeed', 0)):+.1f} °/s")
        _sv_set("ps",    f"{math.degrees(D.get('pitchspeed', 0)):+.1f} °/s")
        _sv_set("ys",    f"{math.degrees(D.get('yawspeed', 0)):+.1f} °/s")
        _sv_set("alt",   f"{_msl_val[0]:.1f} m")
        _sv_set("agl",   f"{_agl_val[0]:.1f} m")
        _sv_set("as",    f"{D.get('airspeed', 0):.1f} m/s")
        _sv_set("gs",    f"{D.get('gs', 0):.1f} m/s")
        _sv_set("hdg",   f"{D.get('heading', 0)} °")
        _sv_set("hud_spd", f"{D.get('airspeed', 0):.1f} m/s")
        _sv_set("mode",  D.get("mode", "---"))
        _sv_set("lat",   f"{D.get('lat', 0.0):.5f} °")
        _sv_set("lon",   f"{D.get('lon', 0.0):.5f} °")
        _sv_set("sat",   str(D.get("sats", "--")))

        b_v   = D.get("batt_volt", 0.0)
        b_pct = D.get("batt_pct", 0)
        t_pct = D.get("throttle_pct", 0)

        _sv_set("vlt",  f"{b_v:.2f} V")
        _sv_set("bamp", f"{D.get('batt_amp', 0.0):.1f} A")
        _sv_set("bmah", f"{D.get('batt_mah', 0)} mAh")
        _sv_set("bpct", f"{b_pct} %")
        _sv_set("rpm",  f"{D.get('rpm', 0):,}".replace(",", "."))
        _sv_set("mamp", f"{D.get('motor_current', 0.0):.1f} A")
        _sv_set("thr",  f"{t_pct} %")

        vc = "#10B981" if b_v > 14.0 else ("#F59E0B" if b_v > 12.5 else "#f43f5e")
        if getattr(lbl_vlt, "_last_col", "") != vc:
            lbl_vlt.configure(text_color=vc); lbl_bvolt.configure(text_color=vc); lbl_vlt._last_col = vc

        pc = "#10B981" if b_pct > 50 else ("#F59E0B" if b_pct > 20 else "#f43f5e")
        if getattr(batt_bar_fill, "_last_col", "") != pc:
            batt_bar_fill.configure(fg_color=pc); batt_bar_fill._last_col = pc

        try:
            w_b = b_pct / 100.0; w_t = t_pct / 100.0
            if abs(w_b - getattr(batt_bar_fill, "_lw", -1)) > 0.01:
                batt_bar_fill.place(x=0, y=0, relheight=1.0, relwidth=w_b); batt_bar_fill._lw = w_b
            if abs(w_t - getattr(thr_bar, "_lw", -1)) > 0.01:
                thr_bar.place(x=0, y=0, relheight=1.0, relwidth=w_t); thr_bar._lw = w_t
        except: pass

    except Exception: pass
    app.after(50, telemetry_ui_loop)

# ── HUD önbellek: son boyut saklanarak gereksiz resize engellenir ──────────
_HUD_LAST_SIZE = [0, 0]
_HUD_LAST_IMG  = [None]   # Son resize edilmiş ImageTk — boyut değişmediyse yeniden kullanılır

def hud_loop():
    """Sadece HUD (3D model) frame günceller — 16ms = ~62fps."""
    global SON_HUD_KARESI
    if OPENGL_OK:
        with HUD_KILIDI:
            if SON_HUD_KARESI is not None:
                kare = SON_HUD_KARESI; SON_HUD_KARESI = None
            else:
                kare = None
        if kare is not None:
            lw = max(lbl_hud.winfo_width(), 1); lh = max(lbl_hud.winfo_height(), 1)
            if lw == _HUD_LAST_SIZE[0] and lh == _HUD_LAST_SIZE[1]:
                # Boyut değişmedi — sadece pixel verisini güncelle, resize yok
                img_r = kare if (lw == HUD_W and lh == HUD_H) else kare.resize((lw, lh), Image.NEAREST)
            else:
                img_r = kare if (lw == HUD_W and lh == HUD_H) else kare.resize((lw, lh), Image.BILINEAR)
                _HUD_LAST_SIZE[0] = lw; _HUD_LAST_SIZE[1] = lh
            imgtk = ImageTk.PhotoImage(image=img_r)
            lbl_hud.imgtk = imgtk; lbl_hud.configure(image=imgtk)
    app.after(16, hud_loop)

# ── Kamera önbellek: PIL image thread'den hazır gelir ──────────────────────
_CAM_PIL_REF  = [None]   # Thread'den gelen son PIL image

def kamera_loop():
    """OPTİMİZASYON: Multiprocessing Queue'dan frame dropping ile en taze kareyi alır."""
    if EKSTRA_MODULLER_OK:
        # OPTİMİZASYON: Kare Atlama — kuyruktaki tüm eski kareleri atla, sadece en sonuncuyu al
        _kare = None
        try:
            while not _KAMERA_QUEUE.empty():
                _kare = _KAMERA_QUEUE.get_nowait()
        except Exception:
            pass

        if _kare is not None:
            _pil = Image.fromarray(_kare)
            _CAM_PIL_REF[0] = _pil
            imgtk = ImageTk.PhotoImage(image=_pil)
            lbl_kamera.imgtk = imgtk; lbl_kamera.configure(image=imgtk)

            # Tam ekran kamera — sadece o sekme aktifse
            try:
                if aktif_sekme[0] == "kamera" or _kamera_labels:
                    fw = max(lbl_kamera_fs.winfo_width(), 1)
                    fh = max(lbl_kamera_fs.winfo_height(), 1)
                    if fw > 10 and fh > 10:
                        _pil_fs = _pil.resize((fw, fh), Image.NEAREST)
                        imgtk_fs = ImageTk.PhotoImage(image=_pil_fs)
                        lbl_kamera_fs.imgtk_fs = imgtk_fs; lbl_kamera_fs.configure(image=imgtk_fs)
            except: pass

            for pop_lbl in _kamera_labels:
                try:
                    fw = max(pop_lbl.winfo_width(), 1); fh = max(pop_lbl.winfo_height(), 1)
                    if fw > 10 and fh > 10:
                        _pil_pop = _pil.resize((fw, fh), Image.NEAREST)
                        imgtk_pop = ImageTk.PhotoImage(image=_pil_pop)
                        pop_lbl.imgtk_fs = imgtk_pop; pop_lbl.configure(image=imgtk_pop)
                except: pass
    app.after(33, kamera_loop)

def map_loop():
    """OPTİMİZASYON: Delta threshold ile gereksiz harita render'ı engellenir."""
    global MAP_ILK_ODAK, LAST_MAP_UPDATE_TIME, ucak_marker
    if EKSTRA_MODULLER_OK and MAP_LERP_HAZIR[0]:
        if not MAP_ILK_ODAK: map_widget.set_zoom(16); MAP_ILK_ODAK = True

        _now_map = _time.perf_counter()
        _dt_map  = 0.080   # map_loop interval
        _gps_age  = min(_now_map - MAP_GPS_TIME[0], 0.5)
        _dlat_per_m = 1.0 / 111319.5
        _dlon_per_m = 1.0 / (111319.5 * math.cos(math.radians(MAP_HEDEF_LAT[0])))
        _dr_lat = MAP_HEDEF_LAT[0] + D.get("vx", 0.0) * _gps_age * _dlat_per_m
        _dr_lon = MAP_HEDEF_LON[0] + D.get("vy", 0.0) * _gps_age * _dlon_per_m
        _K_pos  = 1.0 - math.exp(-_dt_map / 0.06)

        prev_lat = MAP_SMOOTH_LAT[0]; prev_lon = MAP_SMOOTH_LON[0]
        MAP_SMOOTH_LAT[0] += (_dr_lat - MAP_SMOOTH_LAT[0]) * _K_pos
        MAP_SMOOTH_LON[0] += (_dr_lon - MAP_SMOOTH_LON[0]) * _K_pos

        _hdg_fark = (float(MAP_HEDEF_HEADING[0]) - MAP_SMOOTH_HEADING[0] + 180) % 360 - 180
        MAP_SMOOTH_HEADING[0] = (MAP_SMOOTH_HEADING[0] + _hdg_fark * (1.0 - math.exp(-_dt_map / 0.10)) + math.degrees(D.get("yawspeed", 0.0)) * _dt_map * 0.3) % 360

        # OPTİMİZASYON: Delta Threshold — konum çok az değiştiyse render atla (~0.5 metre)
        _DELTA_THRESHOLD = 0.000005  # ~0.5m enlem/boylam farkı
        _delta_lat = abs(MAP_SMOOTH_LAT[0] - prev_lat)
        _delta_lon = abs(MAP_SMOOTH_LON[0] - prev_lon)
        _delta_hdg = abs((MAP_SMOOTH_HEADING[0] - getattr(map_loop, '_last_hdg', 0) + 180) % 360 - 180)
        _konum_degisti = _delta_lat > _DELTA_THRESHOLD or _delta_lon > _DELTA_THRESHOLD or _delta_hdg > 1.0

        yeni_ikon = UCAK_IKON_CACHE.get(int(MAP_SMOOTH_HEADING[0]) % 360)
        if yeni_ikon is not None:
            if ucak_marker is None:
                ucak_marker = map_widget.set_marker(MAP_SMOOTH_LAT[0], MAP_SMOOTH_LON[0], icon=yeni_ikon)
                map_loop._last_hdg = MAP_SMOOTH_HEADING[0]
            elif _konum_degisti:
                # OPTİMİZASYON: Sadece konum anlamlı ölçüde değiştiyse marker ve kamera güncelle
                try: ucak_marker.change_icon(yeni_ikon); ucak_marker.set_position(MAP_SMOOTH_LAT[0], MAP_SMOOTH_LON[0])
                except: pass

                map_widget.set_position(MAP_SMOOTH_LAT[0], MAP_SMOOTH_LON[0])
                LAST_MAP_UPDATE_TIME[0] = _now_map
                map_loop._last_hdg = MAP_SMOOTH_HEADING[0]

        # --- DİĞER TAKIMLARI THROTTLE ET (250ms'de bir güncelle) ---
        if diger_takimlar[0] and (_now_map - LAST_TEAM_MAP_UPDATE_TIME[0] > 0.25):
            LAST_TEAM_MAP_UPDATE_TIME[0] = _now_map
            guncel_takimlar = set()
            for t in diger_takimlar[0]:
                t_no = t.get("takim_numarasi")
                if not t_no: continue
                guncel_takimlar.add(t_no)
                t_lat = t.get("iha_enlem", 0); t_lon = t.get("iha_boylam", 0)
                if t_no in RAKIP_MARKER_NESNELERI:
                    try: RAKIP_MARKER_NESNELERI[t_no].set_position(t_lat, t_lon)
                    except: pass
                else:
                    try:
                        m = map_widget.set_marker(t_lat, t_lon, text=f"Takım {t_no}")
                        RAKIP_MARKER_NESNELERI[t_no] = m
                    except: pass
            silinecekler = set(RAKIP_MARKER_NESNELERI.keys()) - guncel_takimlar
            for k in silinecekler:
                try: RAKIP_MARKER_NESNELERI[k].delete()
                except: pass
                del RAKIP_MARKER_NESNELERI[k]
    app.after(80, map_loop)

def master_loop():
    """Eski master_loop — artık hud_loop/kamera_loop/map_loop ayrı çalışır. Geriye dönük uyumluluk için boş bırakıldı."""
    pass

# OPTİMİZASYON: Widget Referansları (Update döngüsü için)
_W = {
    "labels": {}, 
    "psv": {},
    "log_tb": None,
    "diger_f": None,
    "dt_rows": [],
    "dt_count": [-1],
    "active_parent": None
}

def _build_panel(pwin=None):
    """
    OPTİMİZASYON: Yarışma panelini dinamik olarak hedeflenen pencereye kurar.
    Chrome sekmeleri gibi akıcı geçiş için pwin içeriğini temizler ve yeniden oluşturur.
    """
    if pwin is None: pwin = _YARISMA_PARENT
    
    # Mevcut widget'ları temizle (Akıcı geçiş için şart)
    for child in pwin.winfo_children():
        child.destroy()

    _W["active_parent"] = pwin
    _W["dt_rows"] = []
    _W["dt_count"] = [-1]
    
    pFB = ctk.CTkFont(family="Consolas", size=18, weight="bold")
    pFK = ctk.CTkFont(family="Consolas", size=13, weight="bold")
    pFL = ctk.CTkFont(family="Consolas", size=13)
    pFU = ctk.CTkFont(family="Consolas", size=11, weight="bold")
    pFS = ctk.CTkFont(family="Consolas", size=11)

    ptop = ctk.CTkFrame(pwin, height=44, fg_color="#03070f", corner_radius=0)
    ptop.pack(fill="x")
    ctk.CTkLabel(ptop, text="⬡  TEKNOFEST 2026  —  SAVAŞAN İHA YARIŞMASI SUNUCU PANELİ  ⬡", font=pFB, text_color="#00e5ff").pack(pady=8)

    pmain = ctk.CTkFrame(pwin, fg_color="transparent")
    pmain.pack(fill="both", expand=True, padx=10, pady=8)
    pmain.grid_columnconfigure(0, weight=0, minsize=320)
    pmain.grid_columnconfigure(1, weight=1)
    pmain.grid_columnconfigure(2, weight=0, minsize=320)
    pmain.grid_rowconfigure(0, weight=1)

    def pcard(parent, title, color, row):
        bc = {"#38BDF8":"#1E3A8A","#10B981":"#064E3B","#f97316":"#7c2d12", "#a78bfa":"#4c1d95","#f43f5e":"#881337","#facc15":"#713f12"}.get(color,"#1e3a5f")
        hc = {"#38BDF8":"#172554","#10B981":"#022C22","#f97316":"#431407", "#a78bfa":"#2e1065","#f43f5e":"#4c0519","#facc15":"#422006"}.get(color,"#0d1829")
        c = ctk.CTkFrame(parent, corner_radius=10, fg_color="#0a1628", border_width=1, border_color=bc)
        c.grid(row=row, column=0, padx=10, pady=5, sticky="ew")
        h = ctk.CTkFrame(c, height=26, corner_radius=6, fg_color=hc); h.pack(fill="x", padx=3, pady=(3,0))
        ctk.CTkLabel(h, text=f"  {title}", font=pFK, text_color=color, anchor="w").pack(side="left", padx=6, pady=3)
        return c

    def prow2(parent, lbl):
        f = ctk.CTkFrame(parent, fg_color="transparent"); f.pack(fill="x", padx=12, pady=2)
        ctk.CTkLabel(f, text=lbl, font=pFL, text_color="#94a3b8", anchor="w").pack(side="left")
        v = ctk.CTkLabel(f, text="---", font=ctk.CTkFont(family="Consolas",size=13,weight="bold"), text_color="#00ffcc", anchor="e"); v.pack(side="right")
        return v

    def psep(p): ctk.CTkFrame(p, height=1, fg_color="#1e3a5f").pack(fill="x", padx=10, pady=2)
    def pgrid_sep(parent, row): ctk.CTkFrame(parent, height=1, fg_color="#1e3a5f").grid(row=row, column=0, padx=10, pady=3, sticky="ew")

    # ── SOL PANEL ─────────────────────────────────────────────
    pleft = ctk.CTkFrame(pmain, corner_radius=12, fg_color="#070f1e", border_width=1, border_color="#1e3a5f")
    pleft.grid(row=0, column=0, padx=(0,6), sticky="nsew"); pleft.grid_columnconfigure(0, weight=1)

    ctk.CTkLabel(pleft, text="  SUNUCU AYARLARI", font=pFK, text_color="#38BDF8", anchor="w").grid(row=0, column=0, padx=12, pady=(8,2), sticky="w")

    url_f = ctk.CTkFrame(pleft, fg_color="transparent"); url_f.grid(row=1,column=0,padx=10,pady=2,sticky="ew")
    ctk.CTkLabel(url_f, text="Sunucu URL:", font=pFL, text_color="#94a3b8").pack(anchor="w", padx=4)
    url_entry = ctk.CTkEntry(url_f, font=pFL, fg_color="#050d1a", border_color="#1e3a5f", text_color="#00ffcc", height=30)
    url_entry.insert(0, SERVER_URL); url_entry.pack(fill="x", padx=4, pady=2)

    def set_url():
        global SERVER_URL; SERVER_URL = url_entry.get().strip(); plog(f"URL: {SERVER_URL}")

    ctk.CTkButton(url_f, text="Güncelle", font=pFU, height=26, fg_color="#1e3a5f", hover_color="#2563eb", command=set_url).pack(fill="x", padx=4, pady=2)
    ctk.CTkFrame(pleft, height=1, fg_color="#1e3a5f").grid(row=2,column=0,padx=10,pady=3,sticky="ew")

    cg = pcard(pleft, "▸  OTURUM AÇMA", "#38BDF8", 3)
    ctk.CTkLabel(cg, text="Kullanıcı Adı:", font=pFL, text_color="#94a3b8", anchor="w").pack(padx=12, pady=(5,0), anchor="w")
    kadi_e = ctk.CTkEntry(cg, font=pFL, fg_color="#050d1a", border_color="#1e3a5f", text_color="#fff", height=28, placeholder_text="takimkadi"); kadi_e.pack(fill="x", padx=12, pady=2)
    ctk.CTkLabel(cg, text="Şifre:", font=pFL, text_color="#94a3b8", anchor="w").pack(padx=12, anchor="w")
    sifre_e = ctk.CTkEntry(cg, font=pFL, fg_color="#050d1a", border_color="#1e3a5f", text_color="#fff", height=28, show="●", placeholder_text="şifre"); sifre_e.pack(fill="x", padx=12, pady=2)
    
    g_text = f"✓  Takım #{TAKIM_NO[0]}" if TAKIM_NO[0] > 0 else "⬤  Giriş yapılmadı"
    g_color = "#10B981" if TAKIM_NO[0] > 0 else "#64748b"
    lbl_giris = ctk.CTkLabel(cg, text=g_text, font=pFU, text_color=g_color); lbl_giris.pack(pady=3)

    def giris():
        def _g():
            if not REQUESTS_OK: return
            try:
                r = _http.post(f"{SERVER_URL}/api/giris", json={"kadi":kadi_e.get(),"sifre":sifre_e.get()}, timeout=3.0)
                if r.status_code == 200:
                    session_cookie[0] = r.cookies
                    n = int(r.text.strip()) if r.text.strip().isdigit() else 0
                    TAKIM_NO[0] = n
                    app.after(0, lambda: lbl_giris.configure(text=f"✓  Takım #{n}", text_color="#10B981")); plog(f"Giriş OK — Takım #{n}"); _saat_al_fn()
                else: app.after(0, lambda: lbl_giris.configure(text=f"✗  {r.status_code}", text_color="#f43f5e"))
            except Exception as e:
                app.after(0, lambda: lbl_giris.configure(text="✗  Bağlantı hatası", text_color="#f43f5e")); plog(str(e))
        threading.Thread(target=_g, daemon=True).start()

    ctk.CTkButton(cg, text="GİRİŞ YAP", font=pFK, height=32, fg_color="#1E3A8A", hover_color="#2563eb", command=giris).pack(fill="x", padx=12, pady=(2,8))

    cs = pcard(pleft, "▸  SUNUCU SAATİ", "#10B981", 4)
    lbl_saat = ctk.CTkLabel(cs, text="--:--:--.---", font=ctk.CTkFont(family="Consolas",size=20,weight="bold"), text_color="#10B981"); lbl_saat.pack(pady=5)

    def _saat_al_fn():
        def _s():
            kod, d = _api_get("/api/sunucusaati")
            if kod == 200:
                sunucu_zaman[0] = d
                s = f"{d.get('saat',0):02d}:{d.get('dakika',0):02d}:{d.get('saniye',0):02d}.{d.get('milisaniye',0):03d}"
                app.after(0, lambda: lbl_saat.configure(text=s)); plog(f"Sunucu saati: {s}")
        threading.Thread(target=_s, daemon=True).start()

    ctk.CTkButton(cs, text="Saat Sorgula", font=pFU, height=26, fg_color="#064E3B", hover_color="#059669", command=_saat_al_fn).pack(fill="x", padx=12, pady=(0,8))
    pgrid_sep(pleft, 6)

    cm = pcard(pleft, "▸  KARAN YKİ VERİLERİ", "#f97316", 5)
    lbl_p_lat  = prow2(cm, "Enlem"); psep(cm); lbl_p_lon  = prow2(cm, "Boylam"); psep(cm)
    lbl_p_alt  = prow2(cm, "İrtifa AGL"); psep(cm); lbl_p_hdg  = prow2(cm, "Heading"); psep(cm)
    lbl_p_mode = prow2(cm, "Mod"); psep(cm); lbl_p_batt = prow2(cm, "Batarya")
    ctk.CTkFrame(cm, height=4, fg_color="transparent").pack()

    # ── ORTA PANEL ────────────────────────────────────────────
    pmid = ctk.CTkFrame(pmain, corner_radius=12, fg_color="#070f1e", border_width=1, border_color="#1e3a5f")
    pmid.grid(row=0, column=1, padx=(0,6), sticky="nsew")
    pmid.grid_rowconfigure(1, weight=1); pmid.grid_columnconfigure(0, weight=1)

    thdr = ctk.CTkFrame(pmid, fg_color="transparent"); thdr.grid(row=0,column=0,padx=12,pady=(10,4),sticky="ew")
    ctk.CTkLabel(thdr, text="📡  GÖNDERİLEN TELEMETRİ", font=pFK, text_color="#38BDF8").pack(side="left")
    
    is_tel = telemetri_aktif[0]
    hz_t = "● GÖNDERİLİYOR 1 Hz" if is_tel else "● DURDURULDU"
    hz_c = "#10B981" if is_tel else "#64748b"
    lbl_hz = ctk.CTkLabel(thdr, text=hz_t, font=pFU, text_color=hz_c); lbl_hz.pack(side="right", padx=6)

    def toggle_tel():
        telemetri_aktif[0] = not telemetri_aktif[0]
        if telemetri_aktif[0]:
            btn_tel.configure(text="⏹ Durdur", fg_color="#7c2d12", hover_color="#b91c1c")
            lbl_hz.configure(text="● GÖNDERİLİYOR 1 Hz", text_color="#10B981"); plog("Telemetri başladı")
        else:
            btn_tel.configure(text="▶ Başlat", fg_color="#064E3B", hover_color="#059669")
            lbl_hz.configure(text="● DURDURULDU", text_color="#64748b"); plog("Telemetri durdu")

    btn_t = "⏹ Durdur" if is_tel else "▶ Başlat"
    btn_f = "#7c2d12" if is_tel else "#064E3B"
    btn_h = "#b91c1c" if is_tel else "#059669"
    btn_tel = ctk.CTkButton(thdr, text=btn_t, font=pFU, height=28, width=110, 
                            fg_color=btn_f, hover_color=btn_h, command=toggle_tel)
    btn_tel.pack(side="right", padx=4)

    tbox = ctk.CTkScrollableFrame(pmid, fg_color="#030810", scrollbar_button_color="#1e3a5f", scrollbar_fg_color="#030810")
    tbox.grid(row=1, column=0, padx=10, pady=(0,6), sticky="nsew")
    tbox.grid_columnconfigure(0, weight=1); tbox.grid_columnconfigure(1, weight=1)

    PSV = {k: tk.StringVar(value="---") for k in ["enlem","boylam","irtifa","dikilme","yonelme","yatis","hiz","batarya","otonom","gps_s","http_kod","takim"]}

    def ptf(row, col, label, sv, color="#00ffcc"):
        f = ctk.CTkFrame(tbox, fg_color="#050d1a", corner_radius=8, border_width=1, border_color="#0f2a4a")
        f.grid(row=row, column=col, padx=5, pady=4, sticky="ew")
        ctk.CTkLabel(f, text=label, font=pFU, text_color="#64748b", anchor="w").pack(anchor="w", padx=10, pady=(5,0))
        ctk.CTkLabel(f, textvariable=sv, font=ctk.CTkFont(family="Consolas",size=16,weight="bold"), text_color=color, anchor="e").pack(anchor="e", padx=10, pady=(0,5))

    ptf(0,0,"İHA ENLEM",   PSV["enlem"],   "#38BDF8"); ptf(0,1,"İHA BOYLAM",  PSV["boylam"],  "#38BDF8")
    ptf(1,0,"İRTİFA AGL",  PSV["irtifa"],  "#14B8A6"); ptf(1,1,"HEADING",     PSV["yonelme"], "#14B8A6")
    ptf(2,0,"DİKİLME",     PSV["dikilme"], "#a78bfa"); ptf(2,1,"YATIŞ",       PSV["yatis"],   "#a78bfa")
    ptf(3,0,"HIZ (m/s)",   PSV["hiz"],     "#10B981"); ptf(3,1,"BATARYA",     PSV["batarya"], "#10B981")
    ptf(4,0,"OTONOM",      PSV["otonom"],  "#f97316"); ptf(4,1,"GPS SAATİ",   PSV["gps_s"],   "#facc15")
    ptf(5,0,"HTTP KOD",    PSV["http_kod"],"#64748b"); ptf(5,1,"TAKIM NO",    PSV["takim"],   "#f43f5e")

    ctk.CTkLabel(pmid, text="  👁  DİĞER TAKIMLAR", font=pFK, text_color="#f97316", anchor="w").grid(row=2,column=0,padx=12,pady=(6,2),sticky="w")
    pmid.grid_rowconfigure(3, weight=0)

    diger_f = ctk.CTkScrollableFrame(pmid, height=190, fg_color="#030810", scrollbar_button_color="#1e3a5f", scrollbar_fg_color="#030810")
    diger_f.grid(row=3, column=0, padx=10, pady=(0,8), sticky="ew"); diger_f.grid_columnconfigure(0, weight=1)

    _dt_rows  = []   # mevcut satır label listesi
    _dt_count = [-1]  # son satır sayısı

    def _diger_yaz(liste):
        n = len(liste) if liste else 0
        df = _W["diger_f"]
        if n != _W["dt_count"][0]:
            for w in df.winfo_children(): w.destroy()
            _W["dt_rows"].clear(); _W["dt_count"][0] = n
            if not liste:
                ctk.CTkLabel(df, text="  — Veri yok —", font=pFL, text_color="#334155").pack(pady=6); return
            hdr_r = ctk.CTkFrame(df, fg_color="#0d1829", corner_radius=6); hdr_r.pack(fill="x", padx=4)
            for col,(txt,w) in enumerate([("Takım",50),("Enlem",100),("Boylam",100),("İrtifa",60),("Yönel.",55),("Hız",50),("∆T ms",60)]):
                ctk.CTkLabel(hdr_r, text=txt, font=pFU, text_color="#38BDF8", width=w, anchor="center").grid(row=0, column=col, padx=3, pady=2)
            for i, t in enumerate(liste):
                row_f = ctk.CTkFrame(df, fg_color="#050d1a" if i%2==0 else "#070f1e", corner_radius=0); row_f.pack(fill="x", padx=4)
                row_lbls = []
                vals = [str(t.get("takim_numarasi","?")), f"{t.get('iha_enlem',0):.5f}", f"{t.get('iha_boylam',0):.5f}", f"{t.get('iha_irtifa',0):.1f}m", f"{t.get('iha_yonelme',0):.0f}°", f"{t.get('iha_hizi',0):.1f}", f"{t.get('zaman_farki',0)}"]
                for c,(v,w) in enumerate(zip(vals, [50,100,100,60,55,50,60])):
                    lbl = ctk.CTkLabel(row_f, text=v, font=pFS, text_color="#cbd5e1", width=w, anchor="center")
                    lbl.grid(row=0, column=c, padx=3, pady=2); row_lbls.append(lbl)
                _W["dt_rows"].append(row_lbls)
        elif liste:
            for i, t in enumerate(liste):
                vals = [str(t.get("takim_numarasi","?")), f"{t.get('iha_enlem',0):.5f}", f"{t.get('iha_boylam',0):.5f}", f"{t.get('iha_irtifa',0):.1f}m", f"{t.get('iha_yonelme',0):.0f}°", f"{t.get('iha_hizi',0):.1f}", f"{t.get('zaman_farki',0)}"]
                if i < len(_W["dt_rows"]):
                    for lbl, v in zip(_W["dt_rows"][i], vals): lbl.configure(text=v)

    # ── SAĞ PANEL ─────────────────────────────────────────────
    pright = ctk.CTkFrame(pmain, corner_radius=12, fg_color="#070f1e", border_width=1, border_color="#1e3a5f")
    pright.grid(row=0, column=2, sticky="nsew"); pright.grid_columnconfigure(0, weight=1)

    ctk.CTkLabel(pright, text="  ⚡ OPERASYONLAR", font=pFK, text_color="#facc15", anchor="w").grid(row=0, column=0, padx=12, pady=(8,4), sticky="w")

    ck = pcard(pright, "▸  KİLİTLENME BİLGİSİ", "#f43f5e", 1)
    otonom_k = tk.IntVar(value=1)
    ctk.CTkCheckBox(ck, text="Otonom Kilitlenme", variable=otonom_k, font=pFL, text_color="#cbd5e1").pack(padx=12, pady=4, anchor="w")
    lbl_kl = ctk.CTkLabel(ck, text="Son: —", font=pFS, text_color="#64748b"); lbl_kl.pack(padx=12, pady=2, anchor="w")

    def kilit_gonder():
        def _k():
            s = _sunucu_saati_dict()
            kod, _ = _api_post("/api/kilitlenme_bilgisi", {"kilitlenmeBitisZamani":s,"otonom_kilitlenme":otonom_k.get()})
            renk = "#10B981" if kod==200 else "#f43f5e"
            msg = f"Gönderildi [{kod}] ✓" if kod==200 else f"Hata [{kod}]"
            app.after(0, lambda: lbl_kl.configure(text=msg, text_color=renk)); plog(f"Kilitlenme: {kod}")
        threading.Thread(target=_k, daemon=True).start()

    ctk.CTkButton(ck, text="🔒 Kilitlenme Gönder", font=pFK, height=32, fg_color="#881337", hover_color="#be123c", command=kilit_gonder).pack(fill="x", padx=12, pady=(0,8))
    ctk.CTkFrame(pright, height=1, fg_color="#1e3a5f").grid(row=2, column=0, padx=10, pady=3, sticky="ew")

    ckm = pcard(pright, "▸  KAMİKAZE BİLGİSİ", "#f97316", 3)
    ctk.CTkLabel(ckm, text="QR Metni:", font=pFL, text_color="#94a3b8", anchor="w").pack(padx=12, pady=(4,0), anchor="w")
    qr_e = ctk.CTkEntry(ckm, font=pFL, fg_color="#050d1a", border_color="#1e3a5f", text_color="#fff", height=28, placeholder_text="teknofest2026"); qr_e.pack(fill="x", padx=12, pady=2)
    _km_bas = [{}]
    lbl_km = ctk.CTkLabel(ckm, text="Son: —", font=pFS, text_color="#64748b"); lbl_km.pack(padx=12, pady=2, anchor="w")

    def km_bas(): _km_bas[0] = _sunucu_saati_dict(); lbl_km.configure(text="Başlangıç kaydedildi ✓", text_color="#f97316"); plog("Kamikaze başladı")
    def km_gonder():
        def _k():
            bit = _sunucu_saati_dict()
            kod, _ = _api_post("/api/kamikaze_bilgisi", {"kamikazeBaslangicZamani":_km_bas[0] or bit,"kamikazeBitisZamani":bit,"qrMetni":qr_e.get()})
            renk = "#10B981" if kod==200 else "#f43f5e"
            app.after(0, lambda: lbl_km.configure(text=f"Gönderildi [{kod}]", text_color=renk)); plog(f"Kamikaze: {kod}")
        threading.Thread(target=_k, daemon=True).start()

    bkm = ctk.CTkFrame(ckm, fg_color="transparent"); bkm.pack(fill="x", padx=12, pady=(2,8))
    ctk.CTkButton(bkm, text="⏱ Başlat", font=pFU, height=28, width=90, fg_color="#431407", hover_color="#c2410c", command=km_bas).pack(side="left", padx=(0,4))
    ctk.CTkButton(bkm, text="🚀 Gönder", font=pFU, height=28, fg_color="#7c2d12", hover_color="#ea580c", command=km_gonder).pack(side="right", expand=True)

    ctk.CTkFrame(pright, height=1, fg_color="#1e3a5f").grid(row=4, column=0, padx=10, pady=3, sticky="ew")

    cqr = pcard(pright, "▸  QR KOORDİNATI", "#a78bfa", 5)
    lbl_qre = prow2(cqr, "Enlem"); psep(cqr); lbl_qrb = prow2(cqr, "Boylam")
    def qr_al():
        def _q():
            kod, d = _api_get("/api/qr_koordinati")
            if kod == 200:
                lat = d.get("qrEnlem", 0.0)
                lon = d.get("qrBoylam", 0.0)
                app.after(0, lambda: [lbl_qre.configure(text=str(lat)), lbl_qrb.configure(text=str(lon)), haritaya_qr_ciz(lat, lon)])
                plog(f"QR: {lat} {lon}")
            else: plog(f"QR hata: {kod}")
        threading.Thread(target=_q, daemon=True).start()
    ctk.CTkButton(cqr, text="QR Konum Al", font=pFU, height=26, fg_color="#2e1065", hover_color="#7c3aed", command=qr_al).pack(fill="x", padx=12, pady=(0,8))

    ctk.CTkFrame(pright, height=1, fg_color="#1e3a5f").grid(row=6, column=0, padx=10, pady=3, sticky="ew")

    chss = pcard(pright, "▸  HAVA SAVUNMA SİSTEMLERİ", "#f43f5e", 7)
    hss_tb = ctk.CTkTextbox(chss, height=100, font=pFS, fg_color="#050d1a", text_color="#fca5a5", border_color="#4c0519", border_width=1)
    hss_tb.pack(fill="x", padx=12, pady=4); hss_tb.insert("end","— Sorgulanmadı —"); hss_tb.configure(state="disabled")
    def hss_al():
        def _h():
            kod, d = _api_get("/api/hss_koordinatlari")
            if kod == 200:
                lst = d.get("hss_koordinat_bilgileri",[])
                txt = chr(10).join([f"ID:{h.get('id')}  ({h.get('hssEnlem',0):.5f}, {h.get('hssBoylam',0):.5f})  r={h.get('hssYaricap')}m" for h in lst]) if lst else '— Aktif HSS yok —'
                def _u():
                    hss_tb.configure(state="normal"); hss_tb.delete("1.0","end")
                    hss_tb.insert("end",txt); hss_tb.configure(state="disabled")
                    haritaya_hss_ciz(lst) 
                app.after(0,_u); plog(f"HSS: {len(lst)} sistem")
            else: plog(f"HSS hata: {kod}")
        threading.Thread(target=_h, daemon=True).start()
    ctk.CTkButton(chss, text="HSS Konum Al", font=pFU, height=26, fg_color="#4c0519", hover_color="#be123c", command=hss_al).pack(fill="x", padx=12, pady=(0,6))

    ctk.CTkFrame(pright, height=1, fg_color="#1e3a5f").grid(row=8, column=0, padx=10, pady=3, sticky="ew")

    ctk.CTkLabel(pright, text="  📋 SISTEM LOGU", font=pFK, text_color="#64748b", anchor="w").grid(row=9, column=0, padx=12, pady=(6,2), sticky="w")
    log_tb = ctk.CTkTextbox(pright, height=130, font=pFS, fg_color="#020810", text_color="#475569", border_color="#0f172a", border_width=1)
    log_tb.grid(row=10, column=0, padx=10, pady=(0,8), sticky="ew"); log_tb.configure(state="disabled")

    # Update döngüsü için referansları kaydet
    _W["labels"]["lat"] = lbl_p_lat; _W["labels"]["lon"] = lbl_p_lon
    _W["labels"]["alt"] = lbl_p_alt; _W["labels"]["hdg"] = lbl_p_hdg
    _W["labels"]["mode"] = lbl_p_mode; _W["labels"]["batt"] = lbl_p_batt
    _W["labels"]["hz"] = lbl_hz; _W["labels"]["kl"] = lbl_kl; _W["labels"]["km"] = lbl_km
    _W["labels"]["qre"] = lbl_qre; _W["labels"]["qrb"] = lbl_qrb
    _W["psv"] = PSV; _W["log_tb"] = log_tb; _W["diger_f"] = diger_f
    _W["hss_tb"] = hss_tb; _W["btn_tel"] = btn_tel; _W["diger_yaz_fn"] = _diger_yaz

def _panel_update():
    """OPTİMİZASYON: Global panel update döngüsü. Hangi pencere aktifse ona yazar."""
    pwin = _W["active_parent"]
    if not pwin or not pwin.winfo_exists():
        app.after(1000, _panel_update); return

    # Verileri güncelle
    try:
        L = _W["labels"]; P = _W["psv"]
        if "lat" in L:
            L["lat"].configure(text=f"{D.get('lat',0.0):.5f} °")
            L["lon"].configure(text=f"{D.get('lon',0.0):.5f} °")
            L["alt"].configure(text=f"{_agl_val[0]:.1f} m")
            L["hdg"].configure(text=f"{D.get('heading',0)} °")
            L["mode"].configure(text=D.get("mode","---"))
            L["batt"].configure(text=f"{D.get('batt_pct',0)} %")

        P["enlem"].set(f"{D.get('lat',0.0):.6f}")
        P["boylam"].set(f"{D.get('lon',0.0):.6f}")
        P["irtifa"].set(f"{_agl_val[0]:.1f} m")
        P["dikilme"].set(f"{math.degrees(D.get('pitch',0.0)):.1f} °")
        P["yonelme"].set(f"{D.get('heading',0)} °")
        P["yatis"].set(f"{math.degrees(D.get('roll',0.0)):.1f} °")
        P["hiz"].set(f"{D.get('gs',0.0):.1f} m/s")
        P["batarya"].set(f"{D.get('batt_pct',0)} %")
        P["otonom"].set("1-OTONOM" if _otonom_mu() else "0-MANUEL")
        P["gps_s"].set(f"{D['gps_saat']:02d}:{D['gps_dakika']:02d}:{D['gps_saniye']:02d}.{D['gps_ms']:03d}")
        P["http_kod"].set(son_cevap_kodu[0])
        P["takim"].set(f"# {TAKIM_NO[0]}" if TAKIM_NO[0] > 0 else "Giriş yap")

        if "diger_yaz_fn" in _W: _W["diger_yaz_fn"](diger_takimlar[0])

        log_tb = _W["log_tb"]
        if log_tb:
            _log_yeni = "\n".join(_panel_log[-25:])
            if not hasattr(_panel_update, "_son_log") or _panel_update._son_log != _log_yeni:
                _panel_update._son_log = _log_yeni
                log_tb.configure(state="normal")
                log_tb.delete("1.0","end"); log_tb.insert("end", _log_yeni); log_tb.see("end"); log_tb.configure(state="disabled")
    except: pass

    app.after(500, _panel_update)

# Uygulama başında bir kez başlat
app.after(1000, _panel_update)

# ══════════════════════════════════════════════════════════════
#  KAMERA SEKMESİ — Tam Ekran FPV
# ══════════════════════════════════════════════════════════════
kamera_frame = ctk.CTkFrame(tab_container, fg_color="#000000", corner_radius=0)
kamera_frame.grid(row=0, column=0, sticky="nsew")
sekme_frames["kamera"] = kamera_frame

cam_hdr = ctk.CTkFrame(kamera_frame, height=38, fg_color="#04080f", corner_radius=0)
cam_hdr.pack(fill="x"); cam_hdr.pack_propagate(False)
ctk.CTkLabel(cam_hdr, text="[ İHA FPV KAMERA — TAM EKRAN ]", font=FK, text_color="#38BDF8").pack(side="left", padx=16, pady=8)

lbl_kamera_fs = tk.Label(kamera_frame, bg="#000000")
lbl_kamera_fs.pack(fill="both", expand=True)

cam_overlay = ctk.CTkFrame(kamera_frame, fg_color="#04080f", corner_radius=8, border_width=1, border_color="#1e3a5f")
cam_overlay.place(relx=0.99, rely=0.98, anchor="se")
ctk.CTkLabel(cam_overlay, textvariable=SV["lat"], font=ctk.CTkFont(family="Consolas", size=13, weight="bold"), text_color="#38BDF8").pack(padx=10, pady=(6,1))
ctk.CTkLabel(cam_overlay, textvariable=SV["lon"], font=ctk.CTkFont(family="Consolas", size=13, weight="bold"), text_color="#38BDF8").pack(padx=10, pady=(0,1))
ctk.CTkLabel(cam_overlay, textvariable=SV["alt"], font=ctk.CTkFont(family="Consolas", size=13, weight="bold"), text_color="#14B8A6").pack(padx=10, pady=(0,1))
ctk.CTkLabel(cam_overlay, textvariable=SV["as"], font=ctk.CTkFont(family="Consolas", size=13, weight="bold"), text_color="#10B981").pack(padx=10, pady=(0,6))

# ══════════════════════════════════════════════════════════════
#  YARIŞMA SEKMESİ — TEKNOFEST Panel
# ══════════════════════════════════════════════════════════════
yarisma_frame = ctk.CTkFrame(tab_container, fg_color="#020810", corner_radius=0)
yarisma_frame.grid(row=0, column=0, sticky="nsew")
sekme_frames["yarisma"] = yarisma_frame

_YARISMA_PARENT = yarisma_frame   
_build_panel()

app.after(100, lambda: sekme_ac("yki"))
app.after(150, telemetry_ui_loop)
app.after(200, hud_loop)       # HUD 3D model — 16ms/frame
app.after(220, kamera_loop)    # Kamera — 33ms/frame
app.after(300, map_loop)       # Harita — 80ms/frame
app.mainloop()
