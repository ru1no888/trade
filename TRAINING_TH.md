# วิธีเทรนและใช้งานบอท

## สิ่งที่แก้เพิ่ม

- `symbol` ใส่หลายตัวได้ คั่นด้วย comma
- ระบบดึง Yahoo Finance ทีละตัว แล้วรวม dataset ก่อน train
- หน้า Train Model แสดง metric เพิ่ม:
  - `signal_trades`: จำนวนสัญญาณที่ผ่าน threshold ในชุด test
  - `signal_accuracy`: สัดส่วนทายถูกเฉพาะสัญญาณที่ bot กล้าเข้า
  - `signal_coverage`: สัดส่วนแท่งที่ bot กล้าเทรด
  - `min_probability`: threshold ที่ใช้

## ตั้งค่าแนะนำ

ไฟล์ `config.json`

```json
{
  "symbol": "EURUSD=X,AAPL,MSFT,GC=F",
  "period": "2y",
  "interval": "1h",
  "horizon_candles": 3,
  "min_model_probability": 0.7,
  "risk_percent": 0.5,
  "reward_risk": 2.0,
  "max_trades_per_day": 5
}
```

แนวทาง:

- อยาก data เยอะขึ้น: เพิ่ม `period` เช่น `5y`
- อยากเทรดสั้นมาก: ใช้ `interval` เป็น `15m` หรือ `30m` แต่ Yahoo อาจจำกัดข้อมูลย้อนหลัง
- อยากให้เข้าไม้ชัวร์ขึ้น: เพิ่ม `min_model_probability` เช่น `0.75` ถึง `0.85`
- อยากให้เข้าไม้บ่อยขึ้น: ลด `min_model_probability` เช่น `0.58` ถึง `0.65`

## วิธีรัน

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

เปิด:

```txt
http://127.0.0.1:8000
```

ลำดับใช้:

1. แก้ `Symbol` เป็นหลายตัวได้ เช่น `EURUSD=X,AAPL,MSFT,NVDA,GC=F`
2. กด `Save Config`
3. กด `Train Model`
4. ดู `signal_accuracy` และ `signal_trades`
5. กด `Reload Data / Step Bot`
6. ถ้าพอใจ กด `Start Auto Bot`

## เรื่อง 95%

ไม่มีโมเดลเทรดที่รับประกันชนะ 95% ได้จริงตลอดตลาด. ทำได้แค่ตั้ง threshold สูง เช่น `0.95`.

ผลที่มักเกิด:

- ความชัวร์สูงขึ้น
- จำนวนไม้ลดลงมาก
- บางช่วงอาจไม่เข้าไม้เลย

กฎปลอดภัย:

- ใช้ paper/demo อย่างน้อย 1-3 เดือน
- ไม่เสี่ยงเกิน 0.25-1% ต่อไม้
- ดู `signal_accuracy` คู่กับ `signal_trades`; ถ้าแม่น 95% แต่มีแค่ 1-2 ไม้ ยังเชื่อไม่ได้
- เงินจริงต้องต่อ broker API, slippage, spread, commission, order reject, latency ก่อน

