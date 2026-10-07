 simulation_transmitter.
import socket, ustruct as struct, time, math, random

SERVER_IP = "127.0.0.1"
PORT = 5005
FMT = ">HQIfffffffH"
SZ = struct.calcsize(FMT)
PL_LEN = SZ - 2
MAGIC = 0x55AA
DT = 0.05  # 20Hz Loop

def start_binary_transmitter():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    server_addr = (SERVER_IP, PORT)
    write_buffer = bytearray(SZ)
    
    print(f"[TRANSMITTER]: Streaming v13.0 cryptographic binary frames to {SERVER_IP}:{PORT}")
    y_pos, vy_vel, z_pos, vz_vel, current_ph, frame_count, sequence_id = -20.0, 8.0, -1.0, 0.2, 7.4, 0, 0
    get_rand_bits = random.getrandbits

    try:
        while True:
            frame_count += 1; step_angle = frame_count * 0.1
            
            # Allocation-Free Brownian Noise (Fluid Drag)
            b_noise_x = ((get_rand_bits(16) / 65535.0) * 0.1) - 0.05
            b_noise_y = ((get_rand_bits(16) / 65535.0) * 0.04) - 0.02
            y_pos += (vy_vel * 0.05) + b_noise_y; z_pos += (vz_vel * 0.05)
            
            # Simulated System Jitter (Immune Interferences)
            vx_jitter = ((get_rand_bits(16) / 65535.0) * 30.0) - 15.0 if (frame_count & 31) == 0 else 0.0
            x_pos = (0.1 * math.sin(step_angle)) + b_noise_x; vx_vel = (0.05 * math.cos(step_angle)) + vx_jitter
            
            # Target Coordinate Terrain Logic
            if -5.0 <= y_pos <= 2.0:
                ph_drop = current_ph - (0.01 * abs(y_pos)); current_ph = ph_drop if ph_drop > 4.8 else 4.8
                vel_drop = vy_vel - 0.4; vy_vel = vel_drop if vel_drop > 0.5 else 0.5
            elif 2.0 < y_pos < 2.5:
                vy_vel, current_ph = -2.0, 4.2  
            
            if y_pos > 5.0 or current_ph < 4.0:
                y_pos, vy_vel, z_pos, vz_vel, current_ph, frame_count = -20.0, 8.0, -1.0, 0.2, 7.4, 0
                print("\n--- RESETTING SIMULATED PATHOLOGY TRACK ---")

            sequence_id = (sequence_id + 1) & 0xFFFFFFFF
            ts = int(time.time() * 1000000)
            
            # Structural Pack Step
            struct.pack_into(FMT, write_buffer, 0, MAGIC, ts, sequence_id, x_pos, y_pos, z_pos, vx_vel, vy_vel, vz_vel, current_ph, 0)
            
            # Compute Cryptographic Data Integrity Fletcher-16 Tail Checklist
            s1 = s2 = 0
            for i in range(PL_LEN): s1 = (s1 + write_buffer[i]) % 255; s2 = (s2 + s1) % 255
            struct.pack_into(">H", write_buffer, PL_LEN, (s2 << 8) | s1)
            
            try: sock.sendto(write_buffer, server_addr)
            except OSError: pass  
            time.sleep(DT)
            
    except KeyboardInterrupt: print("\n[TRANSMITTER]: Stream closed safely.")

if __name__ == "__main__": start_binary_transmitter()


