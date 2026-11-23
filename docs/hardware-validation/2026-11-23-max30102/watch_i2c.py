import sys, time, serial
# reset board, log all non-S lines with timestamps, count S lines; stop 10 s after first failure sign or at limit
limit=float(sys.argv[1]); out=open(sys.argv[2],'w')
s=serial.Serial('/dev/ttyACM0',115200,timeout=0.2)
s.dtr=False; s.rts=True; time.sleep(0.1); s.rts=False
t0=time.time(); fail_t=None; n_s=0
while time.time()-t0<limit and (fail_t is None or time.time()-fail_t<10):
    l=s.readline()
    if not l: continue
    line=l.decode(errors='replace').rstrip()
    if line.startswith('S,'): n_s+=1; continue
    if 'probe device timeout' in line or 'transaction timeout' in line: continue
    out.write(f"{time.time()-t0:8.2f} S={n_s} {line}\n"); out.flush()
    if fail_t is None and ('not answering' in line or '"sensor":false' in line or 'i2c_err":' in line and '"i2c_err":0' not in line):
        fail_t=time.time()
out.write(f"END after {time.time()-t0:.1f} s, S lines {n_s}, fail_t {None if fail_t is None else round(fail_t-t0,1)}\n")
