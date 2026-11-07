"""Build GUI_IN_6_STL.zip, SHA256.json and the Vietnamese print notes from verified output."""
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

P=Path(__file__).resolve().parent;D=P/'GUI_IN_6_STL'
rows=json.loads((D/'DANH_SACH_CHI_TIET.json').read_text())
counts=[len(r['parts']) for r in rows]
shutil.copy2(P/'README.md',D/'HUONG_DAN_LAP.md')
lines=['PPG MAC DESKTOP V2 - BO GUI IN 6 STL (man hinh nghieng 10 do)','',
 'Chi gui 6 file BAN_01.stl den BAN_06.stl. Don vi mm, scale 100%.',
 f'Tong {sum(counts)} chi tiet roi, chia 6 nhom trong kho 180 x 180 x 180 mm.']
lines+=[f'{r["file"]}: {len(r["parts"])} chi tiet' for r in rows]
lines+=['','Man hinh khung nhom 178 x 105 x 10 mm, nghieng ra sau 10 do. Vo lap xong',
 'rong 220, sau 200.5, cao 170 mm (chua tinh dau oc/dem chan). De thap cao 30 mm,',
 'nho ra truoc than 50 mm. Cum Pi + buong toi chong nhau trong than phia sau.',
 'Vat lieu PETG. Lo M4 thong 4.5 mm; hoc dai oc AF7.4 mm. 36 oc M4 (HUONG_DAN_LAP.md).',
 'Dan 4 dem chan cao su day it nhat 5 mm duoi day. Khong in man hinh, PCB, day.','',
 'CAN SLICE VA KIEM TRA SUPPORT/BRIM truoc khi in. Mai rong cua de truoc (50 mm) va',
 'cac tai ngang can support hoac doi huong. Khoang chua mep 4 mm la danh dinh.',
 'Khong coi STL la G-code. Chua in thu, chua thu tai, chua kiem tra PCB/day that.']
(D/'HUONG_DAN_GUI_IN.txt').write_text('\n'.join(lines)+'\n')
(D/'SHA256.json').write_text(json.dumps({f.name:hashlib.sha256(f.read_bytes()).hexdigest()
    for f in sorted(D.glob('BAN_0*.stl'))},indent=2)+'\n')
z=P/'GUI_IN_6_STL.zip';z.unlink(missing_ok=True)
with zipfile.ZipFile(z,'w',zipfile.ZIP_DEFLATED) as zf:
    for f in sorted(D.iterdir()):zf.write(f,f.name)
print('zip',z.stat().st_size,counts)
