import sys, time, serial
# usage: ser.py seconds [out.log] [cmd ...]  -- logs serial lines; sends cmds after 1 s; resets board if 'reset'
secs=float(sys.argv[1]); out=sys.argv[2] if len(sys.argv)>2 and sys.argv[2]!='-' else None
cmds=sys.argv[3:]
s=serial.Serial('/dev/ttyACM0',115200,timeout=0.2)
if 'reset' in cmds:
    s.dtr=False; s.rts=True; time.sleep(0.1); s.rts=False; cmds=[c for c in cmds if c!='reset']
f=open(out,'w') if out else None
t0=time.time(); sent=False
while time.time()-t0<secs:
    if not sent and time.time()-t0>1.0:
        for c in cmds: s.write((c+'\n').encode()); time.sleep(0.05)
        sent=True
    l=s.readline()
    if not l: continue
    line=f"{time.time():.3f} "+l.decode(errors='replace').rstrip()
    if f: f.write(line+'\n')
    if not line.split(' ',1)[1].startswith('S,'): print(line, flush=True)
