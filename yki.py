"""
YKİ OpenGL - Pygame Donanım İvmelendirmeli Sürüm (Glass Cockpit UI)
- Ortadaki ufuk çizgisi kaldırıldı.
- HUD üstüne Pusula, Sol ve Sağ tarafa bağımsız Roll ve Pitch yuvarlak kadranları (Artificial Horizon) eklendi.
- KUSURSUZ OPTİMİZASYON: StringVar asenkron UI motoru, C-Level Tkinter Render, Multithreading Ağ.
"""

import customtkinter as ctk
import tkinter as tk
from pymavlink import mavutil
import math
import os
import threading
import time as _time
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

        clock = pygame.time.Clock()
        prev_time = _time.perf_counter()
        pbo_idx = 0
        first_frame = True
        roll_pos = 0.0; pitch_pos = 0.0
        roll_vel = 0.0; pitch_vel = 0.0
        ROLL_OMEGA  = 7.0;  ROLL_ZETA  = 1.05
        PITCH_OMEGA = 4.0;  PITCH_ZETA = 1.15
        last_att_time = 0.0   

        def spring_step(pos, vel, target, omega, zeta, dt):
            acc = -2.0 * zeta * omega * vel - omega * omega * (pos - target)
            return pos + (vel + acc * dt) * dt, vel + acc * dt

        while True:
            try:
                pygame.event.pump()
                now = _time.perf_counter()
                dt = min(now - prev_time, 0.025)   
                prev_time = now

                att_t = D.get("att_time", 0.0)
                if att_t != last_att_time:
                    last_att_time = att_t
                    mav_rollspeed = D.get("rollspeed",  0.0)
                    mav_pitchspeed = D.get("pitchspeed", 0.0)
                    BLEND = 0.6
                    roll_vel = roll_vel * (1.0 - BLEND) + mav_rollspeed * BLEND
                    pitch_vel = pitch_vel * (1.0 - BLEND) + mav_pitchspeed * BLEND

                roll_pos, roll_vel = spring_step(roll_pos, roll_vel, D.get("roll", 0.0), ROLL_OMEGA, ROLL_ZETA, dt)
                pitch_pos, pitch_vel = spring_step(pitch_pos, pitch_vel, D.get("pitch", 0.0), PITCH_OMEGA, PITCH_ZETA, dt)

                glViewport(0, 0, HUD_W, HUD_H)
                glClearColor(0.02, 0.04, 0.10, 1.0)
                glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
                glMatrixMode(GL_PROJECTION); glLoadIdentity()
                gluPerspective(45, HUD_W / HUD_H, 1.0, 100.0)
                glMatrixMode(GL_MODELVIEW); glLoadIdentity()
                glTranslatef(0.0, 0.0, -2.8)
                glRotatef(math.degrees(-roll_pos),  0, 0, 1)
                glRotatef(math.degrees(pitch_pos),  1, 0, 0)
                glEnable(GL_LIGHTING)
                glColor3f(1, 1, 1)
                glCallList(model_list)

                if pbo_ok:
                    read_idx = pbo_idx; proc_idx = 1 - pbo_idx      
                    glBindBuffer(GL_PIXEL_PACK_BUFFER, pbo_ids[read_idx])
                    glPixelStorei(GL_PACK_ALIGNMENT, 1)
                    glReadPixels(0, 0, HUD_W, HUD_H, GL_RGB, GL_UNSIGNED_BYTE, 0)  
                    if not first_frame:
                        glBindBuffer(GL_PIXEL_PACK_BUFFER, pbo_ids[proc_idx])
                        ptr = glMapBuffer(GL_PIXEL_PACK_BUFFER, GL_READ_ONLY)
                        if ptr and NUMPY_OK:
                            ctypes.memmove(np_buf.ctypes.data, ptr, PIX_BYTES)
                            glUnmapBuffer(GL_PIXEL_PACK_BUFFER)
                            img = Image.fromarray(np_buf[::-1].copy())
                            with HUD_KILIDI: SON_HUD_KARESI = img
                        elif ptr:
                            raw = ctypes.string_at(ptr, PIX_BYTES)
                            glUnmapBuffer(GL_PIXEL_PACK_BUFFER)
                            img = Image.frombytes("RGB", (HUD_W, HUD_H), raw)
                            img = img.transpose(Image.FLIP_TOP_BOTTOM)
                            with HUD_KILIDI: SON_HUD_KARESI = img
                        else: glUnmapBuffer(GL_PIXEL_PACK_BUFFER)
                    glBindBuffer(GL_PIXEL_PACK_BUFFER, 0)
                    first_frame = False
                    pbo_idx = 1 - pbo_idx   
                else:
                    glPixelStorei(GL_PACK_ALIGNMENT, 1)
                    if NUMPY_OK:
                        glReadPixels(0, 0, HUD_W, HUD_H, GL_RGB, GL_UNSIGNED_BYTE, np_buf)
                        img = Image.fromarray(np_buf[::-1].copy())
                    else:
                        raw = glReadPixels(0, 0, HUD_W, HUD_H, GL_RGB, GL_UNSIGNED_BYTE)
                        img = Image.frombytes("RGB", (HUD_W, HUD_H), raw)
                        img = img.transpose(Image.FLIP_TOP_BOTTOM)
                    with HUD_KILIDI: SON_HUD_KARESI = img
                pygame.display.flip()
                clock.tick(120)
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
}

MAP_ILK_ODAK = False; SON_HARITA_GUNCELLEME = 0; MAP_ODAK_MODU = ["IHA"]  
SON_KAMERA_KARESI = None; KAMERA_KILIDI = threading.Lock()

SMOOTH_HEADING = 0.0; SMOOTH_UI_ROLL = 0.0; SMOOTH_UI_PITCH = 0.0
MAP_SMOOTH_LAT = [0.0]; MAP_SMOOTH_LON = [0.0]
MAP_HEDEF_LAT = [0.0]; MAP_HEDEF_LON = [0.0]
MAP_HEDEF_HEADING = [0]; MAP_SMOOTH_HEADING = [0.0]
MAP_LERP_HAZIR = [False]; MAP_GPS_TIME = [0.0]     

HEDEF_KAMERA_W = 450; HEDEF_KAMERA_H = 350
_msl_val = [0.0]; _agl_val = [0.0]; ALT_TOGGLE_MODE = ["MSL"]
LAST_UI_ROLL = [-999.0]; LAST_UI_PITCH = [-999.0]; LAST_UI_HEADING = [-999.0]; LAST_MAP_UPDATE_TIME = [0.0]

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
#  GUI (ARAYÜZ BAŞLATMA VE STRİNGBELLEKLERİ)
# ══════════════════════════════════════════════════════════════
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")
app = ctk.CTk()
app.geometry("1600x900")
app.title("KARAN İHA-YKİ")
app.configure(bg="#02050e")

# --- KUSURSUZ OPTİMİZASYON: C-TABANLI ASENKRON DEĞİŞKENLER ---
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

if EKSTRA_MODULLER_OK and UCAK_BASE_IMG is not None:
    UCAK_IKON_CACHE = ucak_ikon_onbellegi_olustur(UCAK_BASE_IMG)

FB = ctk.CTkFont(family="Consolas", size=22, weight="bold")
FK = ctk.CTkFont(family="Consolas", size=14, weight="bold")
FL = ctk.CTkFont(family="Consolas", size=14)
FU = ctk.CTkFont(family="Consolas", size=11, weight="bold")

top = ctk.CTkFrame(app, height=50, fg_color="#04080f", corner_radius=0)
top.pack(side="top", fill="x")
ctk.CTkLabel(top, text="❖  KARAN İHA YER KONTROL İSTASYONU  ❖", font=FB, text_color="#00ffcc").pack(pady=10)

main = ctk.CTkFrame(app, fg_color="transparent")
main.pack(fill="both", expand=True, padx=15, pady=15)
main.grid_columnconfigure(0, weight=0, minsize=480); main.grid_columnconfigure(1, weight=1); main.grid_columnconfigure(2, weight=0, minsize=380); main.grid_rowconfigure(0, weight=1)

# ----- SOL SÜTUN (KAMERA VE HARİTA) -----
left_panel = ctk.CTkFrame(main, width=480, fg_color="transparent")
left_panel.grid(row=0, column=0, padx=(0,10), sticky="nsew")
left_panel.grid_propagate(False) 
left_panel.grid_rowconfigure(0, weight=1); left_panel.grid_rowconfigure(1, weight=1); left_panel.grid_columnconfigure(0, weight=1)

cam_frame = ctk.CTkFrame(left_panel, corner_radius=12, fg_color="#040810", border_width=2, border_color="#38BDF8")
cam_frame.grid(row=0, column=0, pady=(0,5), sticky="nsew"); cam_frame.pack_propagate(False) 
ctk.CTkLabel(cam_frame, text="[ İHA FPV KAMERA ]", font=FK, text_color="#38BDF8").pack(pady=6)

if EKSTRA_MODULLER_OK:
    lbl_kamera = tk.Label(cam_frame, bg="#040810"); lbl_kamera.pack(expand=True) 

map_frame = ctk.CTkFrame(left_panel, corner_radius=12, fg_color="#040810", border_width=2, border_color="#10B981")
map_frame.grid(row=1, column=0, pady=(5,0), sticky="nsew"); map_frame.pack_propagate(False)
map_hdr_row = ctk.CTkFrame(map_frame, fg_color="transparent"); map_hdr_row.pack(fill="x", padx=4, pady=(2,0))
ctk.CTkLabel(map_hdr_row, text="[ CANLI UYDU HARİTASI ]", font=FK, text_color="#10B981").pack(side="left", padx=6, pady=3)

def toggle_map_mode(event=None):
    if MAP_ODAK_MODU[0] == "IHA":
        MAP_ODAK_MODU[0] = "SERBEST"
        lbl_map_mod.configure(text="✦ SERBEST", text_color="#F59E0B", fg_color="#2a1a00")
    else:
        MAP_ODAK_MODU[0] = "IHA"
        lbl_map_mod.configure(text="✦ İHA KİLİT", text_color="#10B981", fg_color="#022c22")

lbl_map_mod = ctk.CTkLabel(map_hdr_row, text="✦ İHA KİLİT", font=ctk.CTkFont(family="Consolas", size=11, weight="bold"), text_color="#10B981", fg_color="#022c22", corner_radius=5, cursor="hand2", padx=6, pady=2)
lbl_map_mod.pack(side="right", padx=6, pady=3)
lbl_map_mod.bind("<Button-1>", toggle_map_mode)

if EKSTRA_MODULLER_OK:
    map_widget = tkintermapview.TkinterMapView(map_frame, corner_radius=8)
    map_widget.pack(fill="both", expand=True, padx=6, pady=(2,6))
    map_widget.set_tile_server("https://mt0.google.com/vt/lyrs=s&hl=en&x={x}&y={y}&z={z}&s=Ga", max_zoom=22)
    map_widget.set_position(41.0, 28.9); map_widget.set_zoom(12)
    UCAK_TK_IMG = None; ucak_marker = None

# ----- ORTA SÜTUN (3D HUD) -----
frame3d = ctk.CTkFrame(main, corner_radius=12, fg_color="#040810", border_width=2, border_color="#00ffcc")
frame3d.grid(row=0, column=1, padx=(0,10), pady=0, sticky="nsew")

if OPENGL_OK:
    lbl_hud = tk.Label(frame3d, bg="#040810"); lbl_hud.pack(fill="both", expand=True, padx=2, pady=2)

hud_spd_box = ctk.CTkFrame(frame3d, corner_radius=8, fg_color="#04101a", border_width=1, border_color="#00cc99")
hud_spd_box.place(relx=0.03, rely=0.94, anchor="sw")
ctk.CTkLabel(hud_spd_box, text="▲ HIZ", font=ctk.CTkFont(family="Consolas", size=10, weight="bold"), text_color="#009977").pack(padx=10, pady=(4,0))
lbl_hud_spd = ctk.CTkLabel(hud_spd_box, textvariable=SV["hud_spd"], font=ctk.CTkFont(family="Consolas", size=18, weight="bold"), text_color="#00ffcc")
lbl_hud_spd.pack(padx=10, pady=(0,4))

hud_roll_lbl = tk.Label(frame3d, bg="#040810", bd=0); hud_roll_lbl.place(relx=0.12, rely=0.08, anchor="center")
ctk.CTkLabel(frame3d, text="ROLL", font=FU, text_color="#38BDF8").place(relx=0.12, rely=0.16, anchor="center")

hud_comp_lbl = tk.Label(frame3d, bg="#090810", bd=1, highlightthickness=1, highlightbackground="#00ffcc"); hud_comp_lbl.place(relx=0.5, rely=0.08, anchor="center")

hud_pitch_lbl = tk.Label(frame3d, bg="#040810", bd=0); hud_pitch_lbl.place(relx=0.88, rely=0.08, anchor="center")
ctk.CTkLabel(frame3d, text="PITCH", font=FU, text_color="#10B981").place(relx=0.88, rely=0.16, anchor="center")

try: FONT_COMPASS_B = ImageFont.truetype("consola.ttf", 48); FONT_COMPASS_N = ImageFont.truetype("consola.ttf", 40)   
except:
    try: FONT_COMPASS_B = ImageFont.truetype("arial.ttf", 48); FONT_COMPASS_N = ImageFont.truetype("arial.ttf", 40)
    except: FONT_COMPASS_B = ImageFont.load_default(); FONT_COMPASS_N = ImageFont.load_default()

def create_adi_frame(roll_deg, pitch_deg, is_roll_mode):
    SS = 4; SIZE = 90 * SS; R = 40 * SS; CX, CY = SIZE // 2, SIZE // 2
    p_deg = 0 if is_roll_mode else pitch_deg; r_deg = roll_deg if is_roll_mode else 0  
    p_off = max(min(p_deg * 2.0 * SS, R * 1.5), -R * 1.5) 
    img = Image.new("RGBA", (SIZE, SIZE), "#040810"); draw = ImageDraw.Draw(img)
    inner_size = int(R * 3); inner = Image.new("RGBA", (inner_size, inner_size), (0,0,0,0)); idraw = ImageDraw.Draw(inner)
    icx, icy = inner_size // 2, inner_size // 2; ihy = icy + p_off 
    idraw.rectangle([0, 0, inner_size, ihy], fill="#38BDF8")
    idraw.rectangle([0, ihy, inner_size, inner_size], fill="#78350F")
    idraw.line([0, ihy, inner_size, ihy], fill="#ffffff", width=2*SS)
    if not is_roll_mode:
        for pt in [-20, -15, -10, -5, 5, 10, 15, 20]:
            ty = ihy - (pt * 2.0 * SS); w = 12*SS if pt % 10 == 0 else 6*SS
            idraw.line([icx - w, ty, icx + w, ty], fill="#ffffff", width=SS)
    if is_roll_mode:
        for rt in [-45, -30, -15, 0, 15, 30, 45]:
            rad = math.radians(rt - 90)
            idraw.line([icx + (R - 5*SS) * math.cos(rad), icy + (R - 5*SS) * math.sin(rad), icx + R * math.cos(rad), icy + R * math.sin(rad)], fill="#ffffff", width=2*SS)
    inner_rot = inner.rotate(-r_deg, resample=Image.BICUBIC, center=(icx, icy))
    mask = Image.new("L", (SIZE, SIZE), 0); ImageDraw.Draw(mask).ellipse([CX-R, CY-R, CX+R, CY+R], fill=255)
    left, top = icx - CX, icy - CY
    img.paste(inner_rot.crop((left, top, left+SIZE, top+SIZE)), (0, 0), mask)
    renk = "#38BDF8" if is_roll_mode else "#10B981"
    draw.ellipse([CX-R, CY-R, CX+R, CY+R], outline=renk, width=2*SS)
    draw.line([CX-15*SS, CY, CX-5*SS, CY], fill="#ef4444", width=2*SS); draw.line([CX+5*SS, CY, CX+15*SS, CY], fill="#ef4444", width=2*SS)
    draw.polygon([CX-3*SS, CY+3*SS, CX+3*SS, CY+3*SS, CX, CY-3*SS], fill="#ef4444")
    return ImageTk.PhotoImage(img.resize((90, 90), Image.LANCZOS))

def create_compass_frame(heading):
    SS = 4; W, H = 320 * SS, 45 * SS
    img = Image.new("RGBA", (W, H), "#090810"); draw = ImageDraw.Draw(img)
    CX = W // 2; carpan = 5 * SS; offset = (heading - int(heading)) * carpan
    for i in range(-35, 36):
        aci = (int(heading) + i); x = CX + (i * carpan) - offset
        if x < -20*SS or x > W + 20*SS: continue
        gercek_aci = aci % 360; dist = abs(x - CX)
        if dist > 120 * SS: renk = "#0f4b4b"
        elif dist > 70 * SS: renk = "#00b38f"
        else: renk = "#00ffcc"
        if gercek_aci % 15 == 0:
            draw.line([x, 0, x, 14*SS], fill=renk, width=2*SS)
            if gercek_aci == 0: txt = "N"
            elif gercek_aci == 90: txt = "E"
            elif gercek_aci == 180: txt = "S"
            elif gercek_aci == 270: txt = "W"
            else: txt = str(gercek_aci)
            fnt = FONT_COMPASS_B if txt in ["N","E","S","W"] else FONT_COMPASS_N
            yazi_renk = "#ef4444" if txt == "N" else renk
            bbox = draw.textbbox((0, 0), txt, font=fnt); tw = bbox[2] - bbox[0]  
            draw.text((x - tw/2, 20*SS), txt, fill=yazi_renk, font=fnt)
        elif gercek_aci % 5 == 0:
            draw.line([x, 0, x, 7*SS], fill=renk, width=SS)
    draw.polygon([CX-6*SS, 45*SS, CX+6*SS, 45*SS, CX, 36*SS], fill="#ef4444")
    for y in range(0, 35*SS, 8*SS): draw.line([CX, y, CX, y+4*SS], fill="#ef4444", width=2)
    return ImageTk.PhotoImage(img.resize((320, 45), Image.LANCZOS))

# ----- SAĞ SÜTUN (TELEMETRİ) - AŞAĞI KAYDIRILABİLİR (SCROLLABLE) -----
right = ctk.CTkScrollableFrame(main, width=380, corner_radius=12, fg_color="#0b1320", border_width=1, border_color="#1e293b")
right.grid(row=0, column=2, padx=0, pady=0, sticky="nsew")
right.grid_columnconfigure(0, weight=1)

BCOLS = {"#38BDF8": "#1E3A8A", "#F59E0B": "#78350F", "#14B8A6": "#042F2E", "#10B981": "#064E3B", "#f97316": "#7c2d12", "#a78bfa": "#4c1d95"}
HCOLS = {"#38BDF8": "#172554", "#F59E0B": "#451A03", "#14B8A6": "#134E4A", "#10B981": "#022C22", "#f97316": "#431407", "#a78bfa": "#2e1065"}

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
    
    # --- YENİ KUSURSUZ SÜRÜKLE BIRAK (0 HESAPLAMA YÜKÜ) ---
    def drag_start(e):
        card.lift()
        card.configure(border_color="#ffffff", border_width=2); hdr.configure(fg_color="#334155")
        # Önbellek: Sürükleme başladığında diğerlerinin yerini bir kez ölçer. Harekette CPU harcamaz.
        card._drag_cache = [(other, other.winfo_rooty(), other.winfo_rooty() + other.winfo_height()) for other in SECTION_FRAMES if other != card]
        
    def drag_motion(e):
        y = e.y_root
        for other, oy0, oy1 in getattr(card, '_drag_cache', []):
            if oy0 < y < oy1:
                if not getattr(other, '_is_drag_target', False):
                    other.configure(border_color="#facc15", border_width=2)
                    other._is_drag_target = True
            else:
                if getattr(other, '_is_drag_target', False):
                    other.configure(border_color=other._orig_bc, border_width=1)
                    other._is_drag_target = False
                        
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
    return card

def data_row(parent, label, str_var, lcolor="#00ffcc", vsize=22):
    rf = ctk.CTkFrame(parent, fg_color="transparent"); rf.pack(fill="x", padx=16, pady=3)
    ctk.CTkLabel(rf, text=label, font=FL, text_color="#94a3b8", anchor="w").pack(side="left")
    # textvariable kullanımı sayesinde Python CPU tüketmeden arkadan C seviyesinde çizilir.
    vl = ctk.CTkLabel(rf, textvariable=str_var, font=ctk.CTkFont(family="Consolas", size=vsize, weight="bold"), text_color=lcolor, anchor="e")
    vl.pack(side="right")
    return vl

def div(parent): ctk.CTkFrame(parent, height=1, fg_color="#1e293b").pack(fill="x", padx=16, pady=2)

c1 = section(right, "▸  YÖNELİM AÇILARI", "#38BDF8", 0)
data_row(c1, "ROLL   (Yatış)", SV["roll"], lcolor="#38BDF8")
div(c1); data_row(c1, "PITCH  (Yunuslama)", SV["pitch"], lcolor="#38BDF8")
div(c1); data_row(c1, "YAW    (Sapma)", SV["yaw"], lcolor="#38BDF8")
ctk.CTkFrame(c1, height=4, fg_color="transparent").pack()

c2 = section(right, "▸  JİROSKOPİK HIZLAR", "#F59E0B", 1)
data_row(c2, "Roll Hızı", SV["rs"], lcolor="#F59E0B", vsize=18)
div(c2); data_row(c2, "Pitch Hızı", SV["ps"], lcolor="#F59E0B", vsize=18)
div(c2); data_row(c2, "Yaw Hızı", SV["ys"], lcolor="#F59E0B", vsize=18)
ctk.CTkFrame(c2, height=4, fg_color="transparent").pack()

c3 = section(right, "▸  SEYRÜSEFER & HIZ", "#14B8A6", 2)
data_row(c3, "İrtifa  MSL", SV["alt"], lcolor="#14B8A6")
div(c3); data_row(c3, "İrtifa  AGL", SV["agl"], lcolor="#a3e635")
div(c3); data_row(c3, "Hava Hızı", SV["as"], lcolor="#14B8A6")
div(c3); data_row(c3, "Yer Hızı", SV["gs"], lcolor="#14B8A6")
div(c3); data_row(c3, "Pusula", SV["hdg"], lcolor="#14B8A6")
ctk.CTkFrame(c3, height=4, fg_color="transparent").pack()

c4 = section(right, "▸  KONUM & SİSTEM", "#10B981", 3)
mf = ctk.CTkFrame(c4, fg_color="transparent"); mf.pack(fill="x", padx=16, pady=6)
ctk.CTkLabel(mf, text="UÇUŞ MODU", font=FL, text_color="#34d399", width=120, anchor="w").pack(side="left")
ctk.CTkLabel(mf, textvariable=SV["mode"], font=ctk.CTkFont(family="Courier New", size=18, weight="bold"), text_color="#10B981").pack(side="right", padx=6)
div(c4); data_row(c4, "Enlem", SV["lat"], lcolor="#f43f5e", vsize=16)
data_row(c4, "Boylam", SV["lon"], lcolor="#f43f5e", vsize=16); div(c4)

bf = ctk.CTkFrame(c4, fg_color="transparent"); bf.pack(fill="x", padx=16, pady=6)
sf = ctk.CTkFrame(bf, fg_color="#042f2e", corner_radius=6, border_width=1, border_color="#134e4a")
sf.pack(side="left", expand=True, fill="x", padx=(0,4))
ctk.CTkLabel(sf, text="SAT (Uydu)", font=FU, text_color="#94a3b8").pack(pady=(2,0))
ctk.CTkLabel(sf, textvariable=SV["sat"], font=ctk.CTkFont(family="Consolas", size=20, weight="bold"), text_color="#10B981").pack(pady=(0,2))

vf = ctk.CTkFrame(bf, fg_color="#451a03", corner_radius=6, border_width=1, border_color="#78350f")
vf.pack(side="right", expand=True, fill="x", padx=(4,0))
ctk.CTkLabel(vf, text="BATARYA", font=FU, text_color="#94a3b8").pack(pady=(2,0))
lbl_vlt = ctk.CTkLabel(vf, textvariable=SV["vlt"], font=ctk.CTkFont(family="Consolas", size=20, weight="bold"), text_color="#F59E0B"); lbl_vlt.pack(pady=(0,2))

c5 = section(right, "▸  MOTOR TELEMETRİSİ", "#f97316", 4)
mtr_top = ctk.CTkFrame(c5, fg_color="transparent"); mtr_top.pack(fill="x", padx=12, pady=(6,0))

rpm_card = ctk.CTkFrame(mtr_top, fg_color="#1a0a00", corner_radius=8, border_width=1, border_color="#7c3b00")
rpm_card.pack(side="left", expand=True, fill="x", padx=(0,4))
ctk.CTkLabel(rpm_card, text="RPM", font=FU, text_color="#94a3b8").pack(pady=(4,0))
ctk.CTkLabel(rpm_card, textvariable=SV["rpm"], font=ctk.CTkFont(family="Consolas", size=22, weight="bold"), text_color="#f97316").pack(pady=(0,4))

thr_card = ctk.CTkFrame(mtr_top, fg_color="#1a0a00", corner_radius=8, border_width=1, border_color="#7c3b00")
thr_card.pack(side="right", expand=True, fill="x", padx=(4,0))
ctk.CTkLabel(thr_card, text="THROTTLE", font=FU, text_color="#94a3b8").pack(pady=(4,0))
ctk.CTkLabel(thr_card, textvariable=SV["thr"], font=ctk.CTkFont(family="Consolas", size=22, weight="bold"), text_color="#fb923c").pack(pady=(0,4))

thr_bar_bg = ctk.CTkFrame(c5, height=8, corner_radius=4, fg_color="#1a0a00"); thr_bar_bg.pack(fill="x", padx=12, pady=(4,2))
thr_bar = ctk.CTkFrame(thr_bar_bg, height=8, corner_radius=4, width=0, fg_color="#f97316"); thr_bar.place(x=0, y=0, relheight=1.0, relwidth=0.0)

div(c5); data_row(c5, "Motor Akımı", SV["mamp"], lcolor="#f97316", vsize=18)
ctk.CTkFrame(c5, height=4, fg_color="transparent").pack()

c6 = section(right, "▸  BATARYA", "#a78bfa", 5)
batt_top = ctk.CTkFrame(c6, fg_color="transparent"); batt_top.pack(fill="x", padx=12, pady=(6,0))

volt_card = ctk.CTkFrame(batt_top, fg_color="#12072a", corner_radius=8, border_width=1, border_color="#4c1d95")
volt_card.pack(side="left", expand=True, fill="x", padx=(0,4))
ctk.CTkLabel(volt_card, text="GERİLİM", font=FU, text_color="#94a3b8").pack(pady=(4,0))
lbl_bvolt = ctk.CTkLabel(volt_card, textvariable=SV["vlt"], font=ctk.CTkFont(family="Consolas", size=22, weight="bold"), text_color="#a78bfa"); lbl_bvolt.pack(pady=(0,4))

bamp_card = ctk.CTkFrame(batt_top, fg_color="#12072a", corner_radius=8, border_width=1, border_color="#4c1d95")
bamp_card.pack(side="right", expand=True, fill="x", padx=(4,0))
ctk.CTkLabel(bamp_card, text="AKIM", font=FU, text_color="#94a3b8").pack(pady=(4,0))
ctk.CTkLabel(bamp_card, textvariable=SV["bamp"], font=ctk.CTkFont(family="Consolas", size=22, weight="bold"), text_color="#c4b5fd").pack(pady=(0,4))

batt_bar_bg = ctk.CTkFrame(c6, height=12, corner_radius=6, fg_color="#12072a"); batt_bar_bg.pack(fill="x", padx=12, pady=(6,2))
batt_bar_fill = ctk.CTkFrame(batt_bar_bg, height=12, corner_radius=6, fg_color="#10B981"); batt_bar_fill.place(x=0, y=0, relheight=1.0, relwidth=1.0)
lbl_bpct_overlay = ctk.CTkLabel(batt_bar_bg, textvariable=SV["bpct"], font=ctk.CTkFont(family="Consolas", size=10, weight="bold"), text_color="#ffffff", fg_color="transparent")
lbl_bpct_overlay.place(relx=0.5, rely=0.5, anchor="center")

div(c6)
batt_bot = ctk.CTkFrame(c6, fg_color="transparent"); batt_bot.pack(fill="x", padx=12, pady=(4,6))
ctk.CTkLabel(batt_bot, text="Kalan Kapasite", font=FU, text_color="#94a3b8").pack(side="left")
ctk.CTkLabel(batt_bot, textvariable=SV["bmah"], font=ctk.CTkFont(family="Consolas", size=18, weight="bold"), text_color="#a78bfa").pack(side="right")

# ══════════════════════════════════════════════════════════════
#  DÖNGÜLER, GÜVENLİK VE MULTITHREADING (YENİ MİMARİ)
# ══════════════════════════════════════════════════════════════
def kamera_arka_plan():
    global SON_KAMERA_KARESI
    try:
        cap = cv2.VideoCapture("test.mp4")
        while True:
            ret, frame = cap.read()
            if not ret: 
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0); continue
            frame = cv2.resize(frame, (HEDEF_KAMERA_W, HEDEF_KAMERA_H))
            cv2image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            with KAMERA_KILIDI: SON_KAMERA_KARESI = cv2image
            _time.sleep(0.03) 
    except Exception as e:
        print("Video Hatası:", e)

if EKSTRA_MODULLER_OK: threading.Thread(target=kamera_arka_plan, daemon=True).start()

# --- YENİ: ARAYÜZÜ KASTIRMAYAN BAĞIMSIZ MAVLINK İŞ PARÇACIĞI (THREAD) ---
def mavlink_dinleyici_thread():
    global MAP_HEDEF_LAT, MAP_HEDEF_LON, MAP_HEDEF_HEADING, MAP_GPS_TIME, MAP_LERP_HAZIR
    global MAP_SMOOTH_LAT, MAP_SMOOTH_LON, MAP_SMOOTH_HEADING
    while True:
        if baglanti:
            try:
                # Bloklayarak okur, CPU'yu sömürmez. Arayüzün yorulması fiziksel olarak imkansızlaşır.
                m = baglanti.recv_match(blocking=True, timeout=0.05)
                if not m: continue
                t = m.get_type()
                if t == 'BAD_DATA': continue
            
                if t == 'ATTITUDE':
                    D["roll"]=m.roll; D["pitch"]=m.pitch; D["yaw"]=m.yaw
                    D["rollspeed"]=m.rollspeed; D["pitchspeed"]=m.pitchspeed; D["yawspeed"]=m.yawspeed
                    D["att_time"] = _time.perf_counter()
                elif t == 'VFR_HUD':
                    D["airspeed"]=m.airspeed; D["alt"]=m.alt
                    D["heading"]=m.heading;   D["gs"]=m.groundspeed
                    _msl_val[0] = m.alt
                elif t == 'SYS_STATUS':
                    D["batt_volt"] = m.voltage_battery / 1000.0
                    D["batt_amp"] = m.current_battery / 100.0 if m.current_battery != -1 else 0.0
                    D["batt_pct"] = m.battery_remaining if m.battery_remaining != -1 else 0
                elif t == 'HEARTBEAT':
                    D["mode"] = mavutil.mode_string_v10(m)
                elif t == 'BATTERY_STATUS':
                    D["batt_mah"] = m.current_consumed if m.current_consumed != -1 else 0
                elif t in ('ESC_TELEMETRY_1_TO_4', 'ESC_STATUS'):
                    try:
                        D["rpm"] = m.rpm[0] if hasattr(m, 'rpm') else 0
                        D["motor_current"] = m.current[0] / 100.0 if hasattr(m, 'current') else 0.0
                    except: pass
                elif t == 'RC_CHANNELS':
                    try: D["throttle_pct"] = max(0, min(100, int((getattr(m, 'chan3_raw', 1000) - 1000) / 10)))
                    except: pass
                elif t == 'VFR_HUD' and hasattr(m, 'throttle'):
                    pct = max(0, min(100, int(m.throttle)))
                    if D.get("throttle_pct", 0) == 0: D["throttle_pct"] = pct
                elif t == 'GPS_RAW_INT':
                    D["sats"] = m.satellites_visible
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
            except Exception:
                _time.sleep(0.01)
        else:
            _time.sleep(0.5)

threading.Thread(target=mavlink_dinleyici_thread, daemon=True).start()

# --- YENİ: ARAYÜZ (TEXT) GÜNCELLEME DÖNGÜSÜ (20 FPS / 50ms) ---
def telemetry_ui_loop():
    try:
        SV["roll"].set(f"{math.degrees(D.get('roll', 0)):+.1f} °")
        SV["pitch"].set(f"{math.degrees(D.get('pitch', 0)):+.1f} °")
        SV["yaw"].set(f"{math.degrees(D.get('yaw', 0)):+.1f} °")
        SV["rs"].set(f"{math.degrees(D.get('rollspeed', 0)):+.1f} °/s")
        SV["ps"].set(f"{math.degrees(D.get('pitchspeed', 0)):+.1f} °/s")
        SV["ys"].set(f"{math.degrees(D.get('yawspeed', 0)):+.1f} °/s")
        SV["alt"].set(f"{_msl_val[0]:.1f} m")
        SV["agl"].set(f"{_agl_val[0]:.1f} m")
        SV["as"].set(f"{D.get('airspeed', 0):.1f} m/s")
        SV["gs"].set(f"{D.get('gs', 0):.1f} m/s")
        SV["hdg"].set(f"{D.get('heading', 0)} °")
        SV["hud_spd"].set(f"{D.get('airspeed', 0):.1f} m/s")
        SV["mode"].set(D.get("mode", "---"))
        SV["lat"].set(f"{D.get('lat', 0.0):.5f} °")
        SV["lon"].set(f"{D.get('lon', 0.0):.5f} °")
        SV["sat"].set(str(D.get("sats", "--")))
        
        b_v = D.get("batt_volt", 0.0)
        SV["vlt"].set(f"{b_v:.2f} V")
        SV["bamp"].set(f"{D.get('batt_amp', 0.0):.1f} A")
        SV["bmah"].set(f"{D.get('batt_mah', 0)} mAh")
        b_pct = D.get("batt_pct", 0)
        SV["bpct"].set(f"{b_pct} %")
        
        SV["rpm"].set(f"{D.get('rpm', 0):,}".replace(",", "."))
        SV["mamp"].set(f"{D.get('motor_current', 0.0):.1f} A")
        t_pct = D.get("throttle_pct", 0)
        SV["thr"].set(f"{t_pct} %")

        # Dinamik Renk Güncellemeleri
        vc = "#10B981" if b_v > 14.0 else ("#F59E0B" if b_v > 12.5 else "#f43f5e")
        if getattr(lbl_vlt, "_last_col", "") != vc:
            lbl_vlt.configure(text_color=vc); lbl_bvolt.configure(text_color=vc); lbl_vlt._last_col = vc

        pc = "#10B981" if b_pct > 50 else ("#F59E0B" if b_pct > 20 else "#f43f5e")
        if getattr(batt_bar_fill, "_last_col", "") != pc:
            batt_bar_fill.configure(fg_color=pc); batt_bar_fill._last_col = pc
            
        try:
            w_b = b_pct/100.0; w_t = t_pct/100.0
            if abs(w_b - getattr(batt_bar_fill, "_lw", -1)) > 0.01:
                batt_bar_fill.place(x=0, y=0, relheight=1.0, relwidth=w_b); batt_bar_fill._lw = w_b
            if abs(w_t - getattr(thr_bar, "_lw", -1)) > 0.01:
                thr_bar.place(x=0, y=0, relheight=1.0, relwidth=w_t); thr_bar._lw = w_t
        except: pass

    except Exception: pass
    app.after(50, telemetry_ui_loop) # 50ms'de bir yorulmadan çalışır

# --- ANA GRAFİK DÖNGÜSÜ (60 FPS - Yalnızca görsel yükler kaldi) ---
_ui_prev_time = [_time.perf_counter()]  
def master_loop():
    global MAP_ILK_ODAK, SON_HARITA_GUNCELLEME, SON_KAMERA_KARESI, UCAK_TK_IMG, ucak_marker, SON_HUD_KARESI
    global SMOOTH_HEADING, SMOOTH_UI_ROLL, SMOOTH_UI_PITCH
    
    if EKSTRA_MODULLER_OK:
        with KAMERA_KILIDI:
            if SON_KAMERA_KARESI is not None:
                imgtk = ImageTk.PhotoImage(image=Image.fromarray(SON_KAMERA_KARESI))
                lbl_kamera.imgtk = imgtk; lbl_kamera.configure(image=imgtk)
                SON_KAMERA_KARESI = None 

    if OPENGL_OK:
        with HUD_KILIDI:
            if SON_HUD_KARESI is not None:
                kare = SON_HUD_KARESI; SON_HUD_KARESI = None
                lw = max(lbl_hud.winfo_width(), 1); lh = max(lbl_hud.winfo_height(), 1)
                img_r = kare if (lw == HUD_W and lh == HUD_H) else kare.resize((lw, lh), Image.BILINEAR)
                imgtk = ImageTk.PhotoImage(image=img_r)
                lbl_hud.imgtk = imgtk; lbl_hud.configure(image=imgtk)

    _ui_now = _time.perf_counter()
    _dt_ui  = min(_ui_now - _ui_prev_time[0], 0.033)
    _ui_prev_time[0] = _ui_now
    _K_UI   = 1.0 - math.exp(-_dt_ui / 0.07)

    fark = (D.get("heading", 0.0) - SMOOTH_HEADING + 180) % 360 - 180
    SMOOTH_HEADING = (SMOOTH_HEADING + fark * _K_UI + math.degrees(D.get("yawspeed", 0.0)) * _dt_ui * 0.5) % 360
    SMOOTH_UI_ROLL  += (math.degrees(D.get("roll",  0.0))  - SMOOTH_UI_ROLL)  * _K_UI
    SMOOTH_UI_PITCH += (math.degrees(D.get("pitch", 0.0)) - SMOOTH_UI_PITCH) * _K_UI

    if abs(SMOOTH_HEADING - LAST_UI_HEADING[0]) > 0.5:
        comp_img = create_compass_frame(SMOOTH_HEADING)
        hud_comp_lbl.configure(image=comp_img); hud_comp_lbl.imgtk = comp_img
        LAST_UI_HEADING[0] = SMOOTH_HEADING

    if abs(SMOOTH_UI_ROLL - LAST_UI_ROLL[0]) > 0.5 or abs(SMOOTH_UI_PITCH - LAST_UI_PITCH[0]) > 0.5:
        roll_img = create_adi_frame(SMOOTH_UI_ROLL, SMOOTH_UI_PITCH, is_roll_mode=True)
        hud_roll_lbl.configure(image=roll_img); hud_roll_lbl.imgtk = roll_img
        pitch_img = create_adi_frame(SMOOTH_UI_ROLL, SMOOTH_UI_PITCH, is_roll_mode=False)
        hud_pitch_lbl.configure(image=pitch_img); hud_pitch_lbl.imgtk = pitch_img
        LAST_UI_ROLL[0] = SMOOTH_UI_ROLL; LAST_UI_PITCH[0] = SMOOTH_UI_PITCH

    if EKSTRA_MODULLER_OK and MAP_LERP_HAZIR[0]:
        if not MAP_ILK_ODAK: map_widget.set_zoom(16); MAP_ILK_ODAK = True
        
        _now_map = _time.perf_counter()
        _dt_map  = 0.016   
        _gps_age  = min(_now_map - MAP_GPS_TIME[0], 0.5)  
        _dlat_per_m = 1.0 / 111319.5; _dlon_per_m = 1.0 / (111319.5 * math.cos(math.radians(MAP_HEDEF_LAT[0])))
        _dr_lat = MAP_HEDEF_LAT[0] + D.get("vx", 0.0) * _gps_age * _dlat_per_m
        _dr_lon = MAP_HEDEF_LON[0] + D.get("vy", 0.0) * _gps_age * _dlon_per_m
        _K_pos   = 1.0 - math.exp(-_dt_map / 0.06)   

        prev_lat = MAP_SMOOTH_LAT[0]; prev_lon = MAP_SMOOTH_LON[0]
        MAP_SMOOTH_LAT[0] += (_dr_lat - MAP_SMOOTH_LAT[0]) * _K_pos
        MAP_SMOOTH_LON[0] += (_dr_lon - MAP_SMOOTH_LON[0]) * _K_pos
        
        _hdg_fark = (float(MAP_HEDEF_HEADING[0]) - MAP_SMOOTH_HEADING[0] + 180) % 360 - 180
        MAP_SMOOTH_HEADING[0] = (MAP_SMOOTH_HEADING[0] + _hdg_fark * (1.0 - math.exp(-_dt_map / 0.10)) + math.degrees(D.get("yawspeed", 0.0)) * _dt_map * 0.3) % 360

        yeni_ikon = UCAK_IKON_CACHE.get(int(MAP_SMOOTH_HEADING[0]) % 360)
        if yeni_ikon is not None:
            if ucak_marker is None: ucak_marker = map_widget.set_marker(MAP_SMOOTH_LAT[0], MAP_SMOOTH_LON[0], icon=yeni_ikon)
            else:
                try: ucak_marker.change_icon(yeni_ikon); ucak_marker.set_position(MAP_SMOOTH_LAT[0], MAP_SMOOTH_LON[0])
                except Exception: pass

        if MAP_ODAK_MODU[0] == "IHA" and (_now_map - LAST_MAP_UPDATE_TIME[0] > 0.2):
            if abs(MAP_SMOOTH_LAT[0] - prev_lat) > 5e-8 or abs(MAP_SMOOTH_LON[0] - prev_lon) > 5e-8:
                map_widget.set_position(MAP_SMOOTH_LAT[0], MAP_SMOOTH_LON[0])
                LAST_MAP_UPDATE_TIME[0] = _now_map

    app.after(16, master_loop) # Saf 60 FPS Grafik Döngüsü

# Sistemleri Başlat
app.after(100, telemetry_ui_loop)
app.after(200, master_loop)
app.mainloop()
