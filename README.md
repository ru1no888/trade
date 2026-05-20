# Auto FX Web Paper Bot

เว็บแอปสำหรับเทสระบบเทรดอัตโนมัติแบบ Paper Trading เท่านั้น

สิ่งที่มี:
- หน้าเว็บดูกราฟแท่งเทียน
- ปุ่ม Reload ข้อมูล
- ปุ่ม Train Model
- ปุ่ม Start/Stop Auto Bot
- แก้ config ผ่านหน้าเว็บ
- ระบบจำลองเข้าไม้/ออกไม้เองตาม Signal
- Stop Loss / Take Profit / Balance / Trade Log
- ข่าวถูกใช้เป็น Filter ผ่าน sentiment score แบบเบื้องต้น

> ระบบนี้ไม่ส่งคำสั่งซื้อขายเงินจริง และตั้งใจให้ใช้ทดสอบ/ศึกษาเท่านั้น

## วิธีติดตั้งบน Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy config.example.json config.json
```

## รันเว็บ

```powershell
python app.py
```

จากนั้นเปิด:

```txt
http://127.0.0.1:8000
```

## วิธีใช้หน้าเว็บ

1. กด `Train Model` ก่อน
2. กด `Reload Data / Step Bot` เพื่อดึงกราฟและคำนวณสัญญาณ
3. กด `Start Auto Bot` เพื่อให้ระบบ reload และ paper trade อัตโนมัติ
4. แก้ค่า config จากหน้าเว็บ เช่น risk %, RR, symbol, timeframe แล้วกด `Save Config`

## Symbol ตัวอย่างจาก Yahoo Finance

- EUR/USD: `EURUSD=X`
- GBP/USD: `GBPUSD=X`
- USD/JPY: `JPY=X` หรือ `USDJPY=X` อาจใช้ได้ต่างกันตาม Yahoo
- Gold Futures: `GC=F`

## คำเตือน

- yfinance ไม่เหมาะสำหรับส่งออเดอร์จริง
- ข่าว sentiment เป็นแค่ตัวกรองหยาบ ไม่เข้าใจบริบทเชิงเศรษฐกิจลึก
- โมเดล ML ไม่การันตีกำไร
- ก่อนใช้เงินจริงต้องทำ backtest, forward test, demo test และตรวจ broker rules
