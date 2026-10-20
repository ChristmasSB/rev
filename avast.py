# -*- coding: utf-8 -*-
"""
RUST NO-RECOIL - Venice edition (v3)
Prave recoil tablice, sync iz igre, GUI, auto prebacivanje oruzja.
Vanjski (SendInput) -> EAC friendly.
"""
import sys, os, json, time, threading, ctypes, ctypes.wintypes as wt
import subprocess, importlib, re, traceback

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, "rust_norecoil_config.json")

def _ensure(pkgs):
    miss = []
    for mod, pip in pkgs:
        try:
            importlib.import_module(mod)
        except Exception:
            miss.append(pip)
    if miss:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", *miss])
        except Exception as e:
            print("pip install nije uspio:", e)

_ensure([("pynput", "pynput")])

from pynput import keyboard as kb
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# ---------------- WIN32 ----------------
user32 = ctypes.WinDLL("user32", use_last_error=True)
MOUSEEVENTF_MOVE = 0x0001
VK_LBUTTON, VK_RBUTTON = 0x01, 0x02

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]
class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]
class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]
class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _U)]

user32.SendInput.argtypes = (wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetForegroundWindow.restype = wt.HWND
user32.GetWindowTextW.argtypes = (wt.HWND, wt.LPWSTR, ctypes.c_int)

def send_move(dx, dy):
    inp = INPUT(type=0, u=_U(mi=MOUSEINPUT(int(dx), int(dy), 0, MOUSEEVENTF_MOVE, 0, None)))
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

def key_down(vk):
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)

def rust_focused():
    hwnd = user32.GetForegroundWindow()
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return "rust" in buf.value.lower()

# ---------------- SYNC IZ IGRE ----------------
def _cfg_candidates():
    c = []
    for drv in ("C:", "D:", "E:", "F:", "G:"):
        for sub in ("Program Files (x86)", "Program Files", "SteamLibrary", "Games"):
            c.append(os.path.join(drv, sub, "Steam", "steamapps", "common", "Rust", "cfg", "client.cfg"))
            c.append(os.path.join(drv, sub, "steamapps", "common", "Rust", "cfg", "client.cfg"))
    for drv in ("C:", "D:", "E:", "F:", "G:"):
        for sub in ("Program Files (x86)", "Program Files"):
            sf = os.path.join(drv, sub, "Steam", "steamapps", "libraryfolders.vdf")
            try:
                txt = open(sf, "r", encoding="utf-8", errors="ignore").read()
                for m in re.finditer(r'"path"\s+"([^"]+)"', txt):
                    p = m.group(1).replace("\\\\", "\\")
                    c.append(os.path.join(p, "steamapps", "common", "Rust", "cfg", "client.cfg"))
            except Exception:
                pass
    return c

def find_rust_cfg():
    for p in _cfg_candidates():
        if os.path.isfile(p):
            return p
    return None

def sync_from_game(cfg_path=None):
    out = {}
    path = cfg_path or find_rust_cfg()
    if path and os.path.isfile(path):
        try:
            txt = open(path, "r", encoding="utf-8", errors="ignore").read()
            for key, name in ((r'input\.sensitivity\s+"([0-9.,]+)"', "sens"),
                              (r'input\.ads_?sensitivity\s+"([0-9.,]+)"', "ads"),
                              (r'graphics\.fov\s+"([0-9.,]+)"', "fov")):
                m = re.search(key, txt)
                if m:
                    out[name] = float(m.group(1).replace(",", "."))
            out["_src"] = path
        except Exception:
            pass
    if "sens" not in out:
        try:
            import winreg
            for p in (r"Software\Facepunch Studios\Rust", r"Software\Facepunch Studios\RustClient"):
                try:
                    k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, p)
                except OSError:
                    continue
                i = 0
                while True:
                    try:
                        name, val, _ = winreg.EnumValue(k, i)
                    except OSError:
                        break
                    i += 1
                    nl = name.lower()
                    try:
                        fv = float(val)
                    except Exception:
                        continue
                    if "sens" in nl and "ads" in nl and "ads" not in out:
                        out["ads"] = fv
                    elif "sens" in nl and "ads" not in nl and "sens" not in out:
                        out["sens"] = fv
                    elif "fov" in nl and "fov" not in out:
                        out["fov"] = fv
                if "sens" in out:
                    out["_src"] = "registry"
                    break
        except Exception:
            pass
    return out

# ---------------- PODACI ----------------
def P(s):
    out = []
    for part in s.replace("\n", " ").split(";"):
        part = part.strip()
        if part:
            a, b = part.split(",")
            out.append([float(a), float(b)])
    return out

def rep(pair, n):
    return (pair + ";") * n

def W(rpm, auto, patt, semi_ms=70):
    return {"rpm": rpm, "auto": auto, "pattern": P(patt), "semi_ms": semi_ms}

DEFAULT_WEAPONS = {
"Assault Rifle": W(450, True,
 "0,-2.258;0.323,-2.301;0.65,-2.3;0.849,-2.259;1.075,-2.324;1.268,-2.216;1.331,-2.237;"
 "1.337,-2.218;1.506,-2.143;1.504,-2.233;1.442,-2.27;1.479,-2.204;1.393,-2.166;1.481,-2.178;"
 "1.597,-2.271;1.45,-2.146;1.369,-2.27;1.582,-2.298;1.517,-2.235;1.498,-2.238;1.466,-2.332;"
 "1.565,-2.243;1.518,-2.303;1.422,-2.212;1.553,-2.248;1.51,-2.285;1.554,-2.24;1.52,-2.222;"
 "1.554,-2.24;1.553,-2.248"),
"LR-300": W(500, True,
 "0,-2.053;0.056,-1.898;-0.247,-1.863;-0.244,-1.94;0.096,-1.967;0.108,-1.886;0.325,-1.947;"
 "-0.181,-1.88;0.162,-1.82;-0.292,-1.995;0.065,-1.837;-0.127,-1.888;-0.091,-1.833;0.065,-1.807;"
 "-0.197,-1.706;-0.217,-1.786;0.043,-1.806;-0.066,-1.758;0.086,-1.904;-0.097,-1.969;"
 "-0.213,-1.85;-0.018,-1.731;-0.046,-1.784;-0.053,-1.886;0.055,-1.793;-0.092,-1.922;"
 "-0.034,-1.796;0.266,-1.994;0.079,-1.921"),
"MP5A4": W(600, True,
 "0.125,-1.052;-0.1,-0.932;0.028,-0.954;-0.014,-0.852;-0.008,-1.071;0.096,-1.018;-0.046,-0.794;"
 "0.034,-1.113;-0.004,-0.93;-0.009,-0.889;0.141,-0.971;-0.015,-1.047;0.096,-0.86;-0.27,-1.039;"
 "0,-0.84;0.018,-1.038;0.099,-0.852;0.2,-0.893;-0.083,-1.069;0.007,-0.881;0.092,-1.151;"
 "-0.109,-0.966;0.17,-1.099;-0.038,-1.12;-0.086,-0.877;0.136,-1.048;0.196,-1.04;-0.153,-1.209;"
 "-0.215,-0.957;0.034,-0.095"),
"Thompson": W(667, True,
 "-0.114,-0.681;0.009,-0.677;0.01,-0.683;0.065,-0.691;0.104,-0.656;-0.088,-0.66;0.09,-0.675;"
 "0.037,-0.633;0.178,-0.635;0.035,-0.669;-0.083,-0.665;0.026,-0.637;0.082,-0.647;-0.123,-0.662;"
 "0.028,-0.662;-0.117,-0.693;-0.269,-0.661;-0.053,-0.677;0.042,-0.647;0.042,-0.647"),
"Custom SMG": W(667, True,
 "-0.114,-0.681;0.009,-0.677;0.01,-0.683;0.065,-0.691;0.104,-0.656;-0.088,-0.66;0.09,-0.675;"
 "0.037,-0.633;0.178,-0.635;0.035,-0.669;-0.083,-0.665;0.026,-0.637;0.082,-0.647;-0.123,-0.662;"
 "0.028,-0.662;-0.117,-0.693;-0.269,-0.661;-0.053,-0.677;0.004,-0.647;0.014,-0.551;-0.01,-0.552;"
 "0.044,-0.578;-0.043,-0.55"),
"M249": W(600, True, "0,-1.49;0.39,-1.49;" + rep("0.72,-1.49", 54) + rep("0,-1.49", 44)),
"HMLMG": W(600, True, "0,-1.4;-0.39,-1.4;" + rep("-0.73,-1.4", 58)),
"Semi-Automatic Rifle": W(343, False, "0,-1.4", 175),
"M39 Rifle": W(343, False, "0.9,-1.6", 175),
"Revolver": W(343, False, "0,-1.7", 175),
"M92 Pistol": W(400, False, "0,-3", 150),
"Semi-Automatic Pistol (P2)": W(400, False, "0,-0.95", 150),
"Python Revolver": W(400, False, "0,-5.8", 150),
"Nail Gun": W(400, False, "0.2,-2.1", 150),
"Waterpipe Shotgun": W(120, False, "0,-0.9", 70),
"Double Barrel Shotgun": W(120, False, "0,-0.8", 60),
"Pump Shotgun": W(90, False, "0,-0.6", 60),
"Spas-12": W(180, False, "0,-0.6", 70),
"Eoka Pistol": W(60, False, "0,-1.2", 80),
"Bolt Action Rifle": W(60, False, "0,-0.5", 60),
"L96 Rifle": W(60, False, "0,-0.5", 60),
"Crossbow": W(60, False, "0,-0.6", 70),
"Compound Bow": W(60, False, "0,-0.4", 70),
"Multiple Grenade Launcher": W(120, False, "0,-1.5", 90),
"Rocket Launcher": W(60, False, "0,-1.0", 80),
"Snowball Gun": W(200, True, "0,-0.4", 50),
}

DEFAULT_CFG = {
    "version": 3,
    "settings": {
        "sens": 0.30,
        "ads_sens": 0.30,
        "fov": 90.0,
        "movement": 1.0,
        "muzzle": 1.0,
        "scope": 1.0,
        "multiplier": 1.0,
        "enabled": True,
        "only_rust": True,
        "toggle_key": "f8",
        "cfg_path": ""
    },
    "slots": {
        "1": "Assault Rifle",
        "2": "LR-300",
        "3": "MP5A4",
        "4": "Thompson",
        "5": "Custom SMG",
        "6": "Semi-Automatic Rifle",
        "7": "M92 Pistol",
        "8": "Python Revolver",
        "9": "Nail Gun"
    },
    "active": "Assault Rifle",
    "weapons": DEFAULT_WEAPONS
}

def load_cfg():
    if os.path.exists(CONFIG_PATH):
        try:
            data = json.load(open(CONFIG_PATH, "r", encoding="utf-8"))
            cfg = json.loads(json.dumps(DEFAULT_CFG))
            if data.get("version", 1) >= 3:
                cfg.update({k: v for k, v in data.items() if k != "settings"})
                cfg["settings"].update(data.get("settings", {}))
            else:
                cfg["settings"].update(data.get("settings", {}))
            return cfg
        except Exception:
            pass
    return json.loads(json.dumps(DEFAULT_CFG))

def save_cfg(cfg):
    try:
        json.dump(cfg, open(CONFIG_PATH, "w", encoding="utf-8"), indent=2)
    except Exception as e:
        print("snimanje nije uspjelo:", e)

CFG = load_cfg()

# ---------------- ENGINE ----------------
def _path(pattern, interval):
    cum = [(0.0, 0.0, 0.0)]
    t = 0.0
    for dx, dy in pattern:
        t += interval
        cum.append((t, cum[-1][1] + dx, cum[-1][2] + dy))
    return cum

def _interp(cum, t):
    if t <= 0:
        return 0.0, 0.0
    if t >= cum[-1][0]:
        return cum[-1][1], cum[-1][2]
    lo, hi = 0, len(cum) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if cum[mid][0] <= t:
            lo = mid
        else:
            hi = mid
    t0, x0, y0 = cum[lo]
    t1, x1, y1 = cum[hi]
    f = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
    return x0 + (x1 - x0) * f, y0 + (y1 - y0) * f

class Engine(threading.Thread):
    def __init__(self, cfg):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.weapon = cfg["active"]
        self.enabled = cfg["settings"]["enabled"]
        self.stop_flag = False
        self.ads = False
        self.prev_lmb = False

    def scale(self):
        s = self.cfg["settings"]
        sens = float(s["ads_sens"]) if self.ads else float(s["sens"])
        sens = max(sens, 0.001)
        d = -0.03 * sens * float(s["movement"]) * 3.0 * (float(s["fov"]) / 100.0)
        return (1.0 / d) * float(s["multiplier"]) * float(s["muzzle"]) * float(s["scope"])

    def run(self):
        while not self.stop_flag:
            s = self.cfg["settings"]
            if not self.enabled or (s["only_rust"] and not rust_focused()):
                self.prev_lmb = key_down(VK_LBUTTON)
                time.sleep(0.005)
                continue
            w = self.cfg["weapons"].get(self.weapon)
            lmb = key_down(VK_LBUTTON)
            self.ads = key_down(VK_RBUTTON)
            if w and w["pattern"]:
                if w["auto"]:
                    if lmb:
                        self.spray(w)
                else:
                    if lmb and not self.prev_lmb:
                        self.tap(w)
            self.prev_lmb = lmb
            if not lmb:
                time.sleep(0.0012)

    def spray(self, w):
        interval = 60.0 / max(w["rpm"], 1)
        cum = _path(w["pattern"], interval)
        sc = self.scale()
        ax = ay = 0.0
        t0 = time.perf_counter()
        while not self.stop_flag and self.enabled:
            if not key_down(VK_LBUTTON):
                break
            e = (time.perf_counter() - t0) * 1000.0
            tx, ty = _interp(cum, e)
            tx *= sc; ty *= sc
            ix, iy = int(tx - ax), int(ty - ay)
            if ix or iy:
                send_move(ix, iy); ax += ix; ay += iy
            time.sleep(0.0006)

    def tap(self, w):
        pts = w["pattern"]
        dur = max(w.get("semi_ms", 70), 10) / 1000.0
        n = max(len(pts), 1)
        cum = [(0.0, 0.0, 0.0)]
        for i, (dx, dy) in enumerate(pts):
            cum.append(((i + 1) / n * dur, cum[-1][1] + dx, cum[-1][2] + dy))
        sc = self.scale()
        ax = ay = 0.0
        t0 = time.perf_counter()
        while not self.stop_flag and self.enabled:
            e = time.perf_counter() - t0
            if e >= dur:
                break
            tx, ty = _interp(cum, e * 1000)
            tx *= sc; ty *= sc
            ix, iy = int(tx - ax), int(ty - ay)
            if ix or iy:
                send_move(ix, iy); ax += ix; ay += iy
            time.sleep(0.0008)
        ix, iy = int(cum[-1][1] * sc - ax), int(cum[-1][2] * sc - ay)
        if ix or iy:
            send_move(ix, iy)

# ---------------- GUI ----------------
TOGGLE_KEYS = {("f%d" % i): getattr(kb.Key, "f%d" % i) for i in range(1, 13)}
MOVEMENTS = {"Stoji (1.0)": 1.0, "Hoda (0.8)": 0.8, "Cuchi (2.0)": 2.0, "Cuchi-hoda (1.8)": 1.8}
MUZZLES = {"Bez (1.0)": 1.0, "Muzzle Brake (0.85)": 0.85, "Muzzle Boost (1.2)": 1.2, "Silencer (0.9)": 0.9}
app_ref = None

def _lbl(d, val, default):
    for k, v in d.items():
        if abs(float(v) - float(val)) < 1e-6:
            return k
    return default

def fmt_patt(p):
    return ";".join(("%g,%g" % (a, b)) for a, b in p)

class App:
    def __init__(self, root, cfg, engine):
        self.root = root
        self.cfg = cfg
        self.engine = engine
        root.title("Rust No-Recoil - Venice v3")
        root.geometry("800x660")
        root.minsize(740, 600)
        self.status = tk.StringVar()
        self.nb = ttk.Notebook(root)
        self.nb.pack(fill="both", expand=True, padx=6, pady=6)
        self._tab_weapons()
        self._tab_settings()
        self._tab_slots()
        self._tab_info()
        self._bottom()
        self._tick()

    def _tab_weapons(self):
        f = ttk.Frame(self.nb); self.nb.add(f, text="Oruzja")
        left = ttk.Frame(f); left.pack(side="left", fill="y", padx=6, pady=6)
        self.lb = tk.Listbox(left, width=28, exportselection=False)
        self.lb.pack(fill="y", expand=True)
        self.lb.bind("<<ListboxSelect>>", lambda e: self.load_weapon())
        for n in sorted(self.cfg["weapons"]):
            self.lb.insert("end", n)
        right = ttk.Frame(f); right.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        ttk.Label(right, text="Naziv:").grid(row=0, column=0, sticky="w")
        self.e_name = ttk.Entry(right, width=28); self.e_name.grid(row=0, column=1, sticky="w", pady=2)
        ttk.Label(right, text="RPM:").grid(row=1, column=0, sticky="w")
        self.e_rpm = ttk.Entry(right, width=10); self.e_rpm.grid(row=1, column=1, sticky="w", pady=2)
        self.v_auto = tk.BooleanVar()
        ttk.Checkbutton(right, text="Full-auto (drzi klik)", variable=self.v_auto).grid(row=2, column=1, sticky="w")
        ttk.Label(right, text="Semi trajanje (ms):").grid(row=3, column=0, sticky="w")
        self.e_semi = ttk.Entry(right, width=10); self.e_semi.grid(row=3, column=1, sticky="w", pady=2)
        ttk.Label(right, text="Pattern (x,y po metku):").grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.t_patt = tk.Text(right, height=12, width=56, wrap="word")
        self.t_patt.grid(row=5, column=0, columnspan=2, sticky="nsew", pady=4)
        right.rowconfigure(5, weight=1)
        b = ttk.Frame(right); b.grid(row=6, column=0, columnspan=2, sticky="w", pady=6)
        for txt, cmd in (("Primijeni", self.apply_weapon), ("Novo", self.new_weapon),
                         ("Dupliciraj", self.dup_weapon), ("Obrisi", self.del_weapon),
                         ("Reset", self.reset_weapons)):
            ttk.Button(b, text=txt, command=cmd).pack(side="left", padx=2)

    def _sel(self):
        s = self.lb.curselection()
        return self.lb.get(s[0]) if s else None

    def load_weapon(self):
        n = self._sel()
        if not n: return
        w = self.cfg["weapons"][n]
        self.e_name.delete(0, "end"); self.e_name.insert(0, n)
        self.e_rpm.delete(0, "end"); self.e_rpm.insert(0, str(w["rpm"]))
        self.e_semi.delete(0, "end"); self.e_semi.insert(0, str(w.get("semi_ms", 70)))
        self.v_auto.set(w["auto"])
        self.t_patt.delete("1.0", "end"); self.t_patt.insert("1.0", fmt_patt(w["pattern"]))

    def apply_weapon(self):
        old = self._sel()
        if not old: return
        new = self.e_name.get().strip() or old
        try:
            patt = P(self.t_patt.get("1.0", "end"))
        except Exception as e:
            messagebox.showerror("Pattern", "Greska: %s" % e); return
        w = {"rpm": int(float(self.e_rpm.get() or 500)), "auto": bool(self.v_auto.get()),
             "pattern": patt, "semi_ms": int(float(self.e_semi.get() or 70))}
        if new != old:
            self.cfg["weapons"].pop(old, None)
            for k, v in list(self.cfg["slots"].items()):
                if v == old: self.cfg["slots"][k] = new
            if self.cfg["active"] == old: self.cfg["active"] = new
            self.engine.weapon = self.cfg["active"]
        self.cfg["weapons"][new] = w
        self.rebuild_list(new)
        save_cfg(self.cfg)

    def rebuild_list(self, select=None):
        self.lb.delete(0, "end")
        names = sorted(self.cfg["weapons"])
        for n in names: self.lb.insert("end", n)
        if select and select in names:
            i = names.index(select)
            self.lb.selection_clear(0, "end"); self.lb.selection_set(i); self.lb.see(i)
        self.refresh_slot_combos()

    def new_weapon(self):
        n = "Novo %d" % (len(self.cfg["weapons"]) + 1)
        self.cfg["weapons"][n] = {"rpm": 500, "auto": True, "pattern": [[0, -1.5]], "semi_ms": 70}
        self.rebuild_list(n); self.load_weapon(); save_cfg(self.cfg)

    def dup_weapon(self):
        n = self._sel()
        if not n: return
        i = 2
        while ("%s copy%d" % (n, i)) in self.cfg["weapons"]: i += 1
        self.cfg["weapons"]["%s copy%d" % (n, i)] = json.loads(json.dumps(self.cfg["weapons"][n]))
        self.rebuild_list(); save_cfg(self.cfg)

    def del_weapon(self):
        n = self._sel()
        if not n: return
        self.cfg["weapons"].pop(n, None); self.rebuild_list(); save_cfg(self.cfg)

    def reset_weapons(self):
        self.cfg["weapons"] = json.loads(json.dumps(DEFAULT_WEAPONS))
        self.rebuild_list(); save_cfg(self.cfg)

    def _tab_settings(self):
        f = ttk.Frame(self.nb); self.nb.add(f, text="Postavke")
        s = self.cfg["settings"]
        self.v_sens = tk.StringVar(value=str(s["sens"]))
        self.v_ads = tk.StringVar(value=str(s["ads_sens"]))
        self.v_fov = tk.StringVar(value=str(s["fov"]))
        self.v_scope = tk.StringVar(value=str(s["scope"]))
        self.v_mult = tk.DoubleVar(value=s["multiplier"])
        self.v_only = tk.BooleanVar(value=s["only_rust"])
        self.v_toggle = tk.StringVar(value=s["toggle_key"])
        self.v_move = tk.StringVar(value=_lbl(MOVEMENTS, s["movement"], "Stoji (1.0)"))
        self.v_muz = tk.StringVar(value=_lbl(MUZZLES, s["muzzle"], "Bez (1.0)"))
        r = 0
        def row(label, widget):
            nonlocal r
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", padx=8, pady=4)
            widget.grid(row=r, column=1, sticky="w", pady=4); r += 1
        row("Rust sensitivity (hip-fire):", ttk.Entry(f, textvariable=self.v_sens, width=12))
        row("Rust ADS sensitivity:", ttk.Entry(f, textvariable=self.v_ads, width=12))
        row("FOV:", ttk.Entry(f, textvariable=self.v_fov, width=12))
        row("Scope mnozitelj:", ttk.Entry(f, textvariable=self.v_scope, width=12))
        row("Muzzle:", ttk.Combobox(f, textvariable=self.v_muz, values=list(MUZZLES), state="readonly", width=22))
        row("Kretanje:", ttk.Combobox(f, textvariable=self.v_move, values=list(MOVEMENTS), state="readonly", width=22))
        ttk.Label(f, text="Globalni mnozitelj:").grid(row=r, column=0, sticky="w", padx=8)
        ttk.Scale(f, from_=0.3, to=2.0, variable=self.v_mult, orient="h", length=240).grid(row=r, column=1, sticky="w")
        self.lbl_mult = ttk.Label(f, text="%.2f" % self.v_mult.get())
        self.lbl_mult.grid(row=r, column=2, sticky="w"); r += 1
        self.v_mult.trace_add("write", lambda *a: self.lbl_mult.config(text="%.2f" % self.v_mult.get()))
        ttk.Checkbutton(f, text="Radi samo kad je Rust u fokusu", variable=self.v_only).grid(row=r, column=1, sticky="w"); r += 1
        row("Toggle tipka:", ttk.Combobox(f, textvariable=self.v_toggle, values=list(TOGGLE_KEYS), width=8, state="readonly"))
        bb = ttk.Frame(f); bb.grid(row=r, column=1, sticky="w", pady=8)
        ttk.Button(bb, text="SYNC iz Rust postavki", command=self.sync_game).pack(side="left", padx=2)
        ttk.Button(bb, text="Rucno odaberi client.cfg", command=self.pick_cfg).pack(side="left", padx=2)
        ttk.Button(bb, text="Primijeni", command=self.apply_settings).pack(side="left", padx=2)
        r += 1
        self.sync_info = ttk.Label(f, text="", foreground="#888", wraplength=560)
        self.sync_info.grid(row=r, column=0, columnspan=3, sticky="w", padx=8, pady=6)

    def pick_cfg(self):
        p = filedialog.askopenfilename(title="Odaberi Rust client.cfg")
        if p:
            self.cfg["settings"]["cfg_path"] = p
            self.sync_game()

    def sync_game(self):
        vals = sync_from_game(self.cfg["settings"].get("cfg_path") or None)
        if not vals or "sens" not in vals:
            self.sync_info.config(text="Nije nadjeno - odaberi client.cfg rucno.")
            return
        if "sens" in vals: self.v_sens.set("%g" % vals["sens"])
        if "ads" in vals: self.v_ads.set("%g" % vals["ads"])
        if "fov" in vals: self.v_fov.set("%g" % vals["fov"])
        self.sync_info.config(text="Ucitano iz: %s" % vals.get("_src", "?"))
        self.apply_settings()

    def apply_settings(self):
        s = self.cfg["settings"]
        try:
            s["sens"] = float(self.v_sens.get().replace(",", "."))
            s["ads_sens"] = float(self.v_ads.get().replace(",", "."))
            s["fov"] = float(self.v_fov.get().replace(",", "."))
            s["scope"] = float(self.v_scope.get().replace(",", "."))
            s["multiplier"] = float(self.v_mult.get())
        except ValueError:
            messagebox.showerror("Postavke", "Neispravan broj."); return
        s["movement"] = MOVEMENTS[self.v_move.get()]
        s["muzzle"] = MUZZLES[self.v_muz.get()]
        s["only_rust"] = bool(self.v_only.get())
        s["toggle_key"] = self.v_toggle.get()
        save_cfg(self.cfg)

    def _tab_slots(self):
        f = ttk.Frame(self.nb); self.nb.add(f, text="Slotovi (auto)")
        ttk.Label(f, text="Tipka hotbara -> oruzje. U igri pritisnes tipku, program sam prebaci oruzje.").pack(anchor="w", padx=8, pady=6)
        g = ttk.Frame(f); g.pack(anchor="w", padx=8)
        self.slot_combos = {}
        for i, k in enumerate("123456789"):
            ttk.Label(g, text="Tipka %s:" % k).grid(row=i, column=0, sticky="w", pady=2)
            cb = ttk.Combobox(g, values=sorted(self.cfg["weapons"]), width=28, state="readonly")
            cb.set(self.cfg["slots"].get(k, ""))
            cb.grid(row=i, column=1, sticky="w", padx=6)
            cb.bind("<<ComboboxSelected>>", lambda e, kk=k: self.slot_changed(kk))
            self.slot_combos[k] = cb
        ttk.Button(f, text="Snimi slotove", command=lambda: save_cfg(self.cfg)).pack(anchor="w", padx=8, pady=10)

    def slot_changed(self, k):
        self.cfg["slots"][k] = self.slot_combos[k].get()
        save_cfg(self.cfg)

    def refresh_slot_combos(self):
        for cb in self.slot_combos.values():
            cb["values"] = sorted(self.cfg["weapons"])

    def _tab_info(self):
        f = ttk.Frame(self.nb); self.nb.add(f, text="Info")
        txt = ("IZVOR PATTERNA\n"
               "Izmjereni recoil podaci iz igre (UnknownCheats / MatiProYaa), prosjek 15 sprayeva.\n"
               "Formula: px = pattern * Scope * Muzzle / (-0.03 * (Sens*Movement) * 3.0 * (Fov/100))\n\n"
               "KALIBRACIJA\n"
               "1) Klikni 'SYNC iz Rust postavki' (cita Rust/cfg/client.cfg).\n"
               "2) Ako spray ide prekratko/prejako -> diraj 'Globalni mnozitelj'.\n"
               "3) ADS automatski koristi ads_sens.\n\n"
               "Toggle tipka: " + self.cfg["settings"]["toggle_key"].upper() + "\n"
               "Config: rust_norecoil_config.json\n")
        t = tk.Text(f, wrap="word"); t.insert("1.0", txt); t.config(state="disabled")
        t.pack(fill="both", expand=True, padx=8, pady=8)

    def _bottom(self):
        b = ttk.Frame(self.root); b.pack(fill="x", padx=6, pady=(0, 6))
        self.btn = ttk.Button(b, text="STOP", width=10, command=self.toggle_enabled)
        self.btn.pack(side="left")
        ttk.Button(b, text="Snimi", width=10, command=lambda: save_cfg(self.cfg)).pack(side="left", padx=4)
        ttk.Label(b, textvariable=self.status).pack(side="left", padx=12)

    def toggle_enabled(self):
        self.engine.enabled = not self.engine.enabled
        self.cfg["settings"]["enabled"] = self.engine.enabled

    def _tick(self):
        e = self.engine
        self.btn.config(text="STOP" if e.enabled else "START")
        self.status.set("[%s]  oruzje: %s   |   sens %s  fov %s   |   toggle %s" % (
            "RADIM" if e.enabled else "PAUZA", e.weapon,
            self.cfg["settings"]["sens"], self.cfg["settings"]["fov"],
            self.cfg["settings"]["toggle_key"].upper()))
        self.root.after(200, self._tick)

# ---------------- START ----------------
def start_listener():
    def on_press(key):
        ch = getattr(key, "char", None)
        if ch and ch.isdigit() and ch != "0":
            w = CFG["slots"].get(ch)
            if w and w in CFG["weapons"]:
                CFG["active"] = w
                app_ref.engine.weapon = w
        for name, k in TOGGLE_KEYS.items():
            if key == k and name == CFG["settings"]["toggle_key"]:
                app_ref.toggle_enabled()
    lis = kb.Listener(on_press=on_press)
    lis.daemon = True
    lis.start()

def main():
    global app_ref
    print(">>> start...", flush=True)
    engine = Engine(CFG)
    engine.start()
    print(">>> engine OK", flush=True)
    root = tk.Tk()
    print(">>> tkinter OK", flush=True)
    app = App(root, CFG, engine)
    print(">>> GUI OK - prozor je otvoren", flush=True)
    app_ref = app
    start_listener()
    print(">>> hotkey listener OK", flush=True)
    root.mainloop()
    print(">>> prozor zatvoren", flush=True)

if __name__ == "__main__":
    try:
        main()
    except BaseException:
        traceback.print_exc()
        input("GRESKA - pritisni Enter za izlaz...")