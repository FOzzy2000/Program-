import socket, ustruct as struct, time, math, random, gc, _thread, micropython, sqlite3
from array import array
try: import uasyncio as asyncio
except ImportError: import asyncio
try: from machine import Pin, PWM
except ImportError:
    class Pin: OUT = 1; __init__ = lambda *a: None
    class PWM: freq = duty_u16 = lambda *a: None
try: from ucollections import deque
except ImportError: from collections import deque

# ==========================================
# 1. COMPILE-TIME CONSTANTS & STORAGE CONFIG
# ==========================================
PORT   = const(5005)
MAGIC  = const(0x55AA)
SZ     = const(46)  # Pre-computed struct.calcsize(">HQIfffffffH")
PL_LEN = const(44)  # SZ - 2
DB_PATH = "sovereign_metrics.db"

def init_sovereign_db():
    """Initializes a high-speed indexed database for real-time telemetry logs."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS system_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_epoch INTEGER,
            sequence_id INTEGER,
            node_state TEXT,
            target_status TEXT,
            pwm_output REAL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_seq ON system_logs(sequence_id)")
    conn.commit()
    conn.close()

# Initialize localized database routing on boot
init_sovereign_db()

# ==========================================
# 2. VIPER EMITTER ASSEMBLY MATH ENGINE
# ==========================================
class Mth:
    @staticmethod
    @micropython.viper
    def mul(a: int, b: int) -> int: 
        return (a * b) >> 16
        
    @staticmethod
    @micropython.viper
    def div(a: int, b: int) -> int: 
        if b == 0: return 1
        return (a << 16) // b
        
    @staticmethod
    @micropython.viper
    def sqrt(v: int) -> int:
        if v <= 0: return 0
        x = v
        y = (v + 1) >> 1
        while y < x: 
            x = y
            y = (y + v // y) >> 1
        return x << 8

# ==========================================
# 3. ZERO-ALLOCATION NATIVE NEURAL CORE
# ==========================================
class AdaptiveNeuralCore:
    __slots__ = ['w', 'b', 'p_pos', 'p_vel', 'pid_l', 'pid_r', 'history', 'regs', 'v_l', 'v_r', 'hb', 'seq']
    def __init__(self):
        self.w = array('i', [32768, -19660, -26214, 45875])
        self.b = 6553
        self.history = deque((), 3)
        self.p_pos = array('i', [0, 0, 0])
        self.p_vel = array('i', [0, 0, 0])
        self.regs = array('i', [0, 0, 0])
        
        self.pid_l = array('i', [4915, 204, 410, 0, 0]) 
        self.pid_r = array('i', [4915, 204, 410, 0, 0]) 
        
        self.v_l, self.v_r = PWM(Pin(2)), PWM(Pin(3))
        self.hb, self.seq = time.time(), 0
        self.v_l.freq(200); self.v_r.freq(200)

    @micropython.viper
    def process(self, seq: int, x_f: int, y_f: int, z_f: int, vx_f: int, vy_f: int, vz_f: int, ph_f: int, stp: int) -> int:
        w = ptr32(self.w)
        p_pos = ptr32(self.p_pos)
        pid_l = ptr32(self.pid_l)
        pid_r = ptr32(self.pid_r)
        regs = ptr32(self.regs)
        
        if y_f == y_f: 
            y_f += (vy_f >> 4)

        dt = 3276
        c_drg = int(math.cos(float(stp) * 0.1) * 655.0)
        s_drg = int(math.sin(float(stp) * 0.1) * 655.0)
        p_pos[0] = x_f + (((vx_f + c_drg) * dt) >> 16)
        p_pos[1] = y_f + (((vy_f + s_drg) * dt) >> 16)
        p_pos[2] = z_f + ((vz_f * dt) >> 16)

        d3_sq = (x_f*x_f + y_f*y_f + z_f*z_f) >> 16
        d3 = int(Mth.sqrt(d3_sq))
        
        xy_sq = (x_f*x_f + y_f*y_f) >> 16
        xy = int(Mth.sqrt(xy_sq))
        
        denom_xy = xy if xy >= 6553 else 6553
        slp = 65536 + ((abs(z_f) << 16) // denom_xy)
        
        denom_d3 = d3 if d3 > 0 else 1
        t_score = int(Mth.mul(int(Mth.div(abs(vx_f + vy_f + vz_f), denom_d3)), slp))

        n1 = int(Mth.mul(w[0], d3)) + int(Mth.mul(w[1], ph_f)) + int(self.b)
        n2 = int(Mth.mul(w[2], d3)) + int(Mth.mul(w[3], ph_f)) + int(self.b)
        prob = ((n1 if n1 > 0 else 0) + (n2 if n2 > 0 else 0)) >> 1
        
        p_idx = 4
        intensity = 0
        if t_score > 131072 or prob > 45875:
            p_idx = 6
            intensity = 62259
        elif t_score > 52428 or prob > 19660:
            p_idx = 5
            intensity = 39321
            
        mod = 655 if p_idx == 6 else -655
        w[0] = w[0] + int(Mth.mul(mod, d3))
        if w[0] > 65536: w[0] = 65536
        elif w[0] < -65536: w[0] = -65536

        sec_idx = 2
        if y_f < 0:
            if x_f < -32768: sec_idx = 3
            elif x_f > 32768: sec_idx = 4
            else: sec_idx = 5
        
        is_left_active = 1 if (sec_idx == 3 or sec_idx == 5) else 0
        tgt_l = intensity if is_left_active == 1 else 0
        err_l = tgt_l - pid_l[3]
        pid_l[3] = pid_l[3] + err_l
        if pid_l[3] > 262144: pid_l[3] = 262144
        elif pid_l[3] < -262144: pid_l[3] = -262144
        out_l = int(Mth.mul(pid_l[0], err_l)) + int(Mth.mul(pid_l[1], pid_l[3])) + int(Mth.mul(pid_l[2], err_l - pid_l[4]))
        pid_l[4] = err_l
        if out_l > 65536: out_l = 65536
        elif out_l < 0: out_l = 0

        is_right_active = 1 if (sec_idx == 4 or sec_idx == 5) else 0
        tgt_r = intensity if is_right_active == 1 else 0
        err_r = tgt_r - pid_r[3]
        pid_r[3] = pid_r[3] + err_r
        if pid_r[3] > 262144: pid_r[3] = 262144
        elif pid_r[3] < -262144: pid_r[3] = -262144
        out_r = int(Mth.mul(pid_r[0], err_r)) + int(Mth.mul(pid_r[1], pid_r[3])) + int(Mth.mul(pid_r[2], err_r - pid_r[4]))
        pid_r[4] = err_r
        if out_r > 65536: out_r = 65536
        elif out_r < 0: out_r = 0

        self.v_l.duty_u16(out_l)
        self.v_r.duty_u16(out_r)
        
        regs[0] = p_idx
        regs[1] = out_l
        regs[2] = sec_idx
        
        return p_idx

class PacketQueue:
    def __init__(self):
        self.pool = [bytearray(SZ) for _ in range(8)]
        self.w, self.r, self.c = 0, 0, 0
        self.l = _thread.allocate_lock()
        
    def write(self, sock):
        buf = self.pool[self.w]
        try:
            n, a = sock.recvfrom_into(buf)
            if n == SZ:
                s1 = s2 = 0
                for i in range(PL_LEN):
                    s1 = (s1 + buf[i]) % 255
                    s2 = (s2 + s1) % 255
                if ((s2 << 8) | s1) == struct.unpack_from(">H", buf, PL_LEN)[0]:
                    with self.l:
                        if self.c < 8: 
                            self.w = (self.w + 1) % 8
                            self.c += 1
        except OSError: pass
        
    def read(self, out):
        with self.l:
            if self.c == 0: return False
            out[:] = self.pool[self.r][:]
            self.r = (self.r + 1) % 8
            self.c -= 1
            return True

async def run_os(engine, q):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    sock.bind(("0.0.0.0", PORT))
    
    p_buf = bytearray(SZ)
    s_arr = ["NONE", "FAULT", "PASSIVE", "LEFT", "RIGHT", "CENTER"]
    p_arr = ["INIT", "FAIL", "LIMIT", "NOISE", "ZERO", "METER", "MAX"]
    step = 0
    
    print("[v13.0-EXTREME]: Ultra-performance zero-allocation Viper database core active.")
    while True:
        q.write(sock)
        step += 1
        if q.read(p_buf):
            mag, ts, seq, x, y, z, vx, vy, vz, ph, _ = struct.unpack(">HQIfffffffH", p_buf)
            if mag == MAGIC:
                x_f, y_f, z_f = int(x * 65536.0), int(y * 65536.0), int(z * 65536.0)
                vx_f, vy_f, vz_f = int(vx * 65536.0), int(vy * 65536.0), int(vz * 65536.0)
                raw_ph_f = int(ph * 65536.0)
                ph_f = 262144 if raw_ph_f < 262144 else (589824 if raw_ph_f > 589824 else raw_ph_f)
                
                p_idx = engine.process(seq, x_f, y_f, z_f, vx_f, vy_f, vz_f, ph_f, step)
                
                engine.history.append(p_idx)
                for h in engine.history:
                    if h == 6:
                        p_idx = 6
                        break
                        
                r = engine.regs
                node_string = s_arr[r[2]]
                target_string = p_arr[p_idx]
                pwm_float = float(r[1]) / 65536.0
                
                print(f"[SEQ:{seq:04d}] Node: {node_string} | Target: {target_string} | PWM: {pwm_float:.2f}")
                
                try:
                    conn = sqlite3.connect(DB_PATH)
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO system_logs (timestamp_epoch, sequence_id, node_state, target_status, pwm_output)
                        VALUES (?, ?, ?, ?, ?)
                    """, (int(time.time()), seq, node_string, target_string, pwm_float))
                    conn.commit()
                    conn.close()
                except Exception:
                    pass

                if (step & 63) == 0: gc.collect()
        else: 
            await asyncio.sleep_ms(1)

if __name__ == "__main__":
    q = PacketQueue()
    engine = AdaptiveNeuralCore()
    asyncio.run(run_os(engine, q))
