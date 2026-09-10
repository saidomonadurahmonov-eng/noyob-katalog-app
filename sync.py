# -*- coding: utf-8 -*-
"""NOYOB agent planshet katalogi — Billz'dan sinxronizatsiya.

    python sync.py

Billz'dan mahsulot, optom narx, qoldiq va rasmlarni oladi; rasmlarni offline
uchun siqadi (450px WebP, ~30KB) va katalog ma'lumotini yozadi.

Ofisda Wi-Fi'da ishga tushiriladi. Keyin planshet supermarketda internetsiz
ishlayveradi — hammasi service worker keshida turadi.
"""
import base64
import concurrent.futures as cf
import hashlib
import io
import json
import os
import pathlib
import secrets
import sys
import threading

import requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PAPKA = pathlib.Path(__file__).parent
RASM_PAPKA = PAPKA / "rasm"
RASM_PAPKA.mkdir(exist_ok=True)

HOST = "https://api-admin.billz.ai"
SHOP_ID = "dee67ee3-58cf-4c58-a505-af5fa915640f"   # Склад NOYOB (ombor)
FAQAT_QOLDIQLI = True      # qoldig'i tugaganlar katalogda ko'rinmaydi
RASM_OLCHAM = 450
RASM_SIFAT = 80

# Narxni himoyalaydigan PIN. .env dan yoki muhit o'zgaruvchisidan.
PIN = os.getenv("KATALOG_PIN") or ""
if not PIN:
    _envf = PAPKA / ".env"
    if _envf.exists():
        for _q in _envf.read_text(encoding="utf-8").splitlines():
            if _q.strip().startswith("KATALOG_PIN="):
                PIN = _q.split("=", 1)[1].strip()
if not PIN:
    PIN = "2604"           # standart — .env da o'zgartiring


def _env(nom, standart=""):
    v = os.getenv(nom)
    if v:
        return v.strip()
    f = PAPKA / ".env"
    if f.exists():
        for q in f.read_text(encoding="utf-8").splitlines():
            if q.strip().startswith(nom + "="):
                return q.split("=", 1)[1].strip()
    return standart


# Savdo API (mijoz + buyurtma). Kalit noyob-savdo-api/.env dan olinadi.
SAVDO_API_URL = _env("SAVDO_API_URL",
                     "https://noyob-savdo-api-production.up.railway.app")
SAVDO_API_KALIT = _env("SAVDO_API_KALIT", "")
if not SAVDO_API_KALIT:
    _apienv = pathlib.Path(r"C:\Users\user\noyob-savdo-api\.env")
    if _apienv.exists():
        for _q in _apienv.read_text(encoding="utf-8").splitlines():
            if _q.strip().startswith("API_KALIT="):
                SAVDO_API_KALIT = _q.split("=", 1)[1].strip()

_qulf = threading.Lock()


def billz_kirish() -> dict:
    """Billz ochiq API'siga kirish. Panel tokeni KERAK EMAS — shu sabab
    sinxronni bulutda (GitHub Actions) ham yurgizsa bo'ladi."""
    token = _env("BILLZ_SECRET_TOKEN")
    if not token:                      # lokal kompyuterdagi eski joyi
        f = pathlib.Path(r"C:\Users\user\billz-bot\.env")
        if f.exists():
            for q in f.read_text(encoding="utf-8").splitlines():
                if q.strip().startswith("BILLZ_SECRET_TOKEN="):
                    token = q.split("=", 1)[1].strip()
    if not token:
        sys.exit("BILLZ_SECRET_TOKEN topilmadi "
                 "(muhit o'zgaruvchisi yoki billz-bot/.env)")
    d = requests.post(f"{HOST}/v1/auth/login",
                      json={"secret_token": token}, timeout=30).json()
    t = (d.get("data") or {}).get("access_token") or d.get("access_token")
    return {"Authorization": f"Bearer {t}"}


def optom_narx(p: dict) -> float:
    """product_supplier_stock.wholesale_price; topilmasa chakana."""
    eng = 0.0
    for s in p.get("product_supplier_stock") or []:
        if s.get("shop_id") == SHOP_ID:
            w = float(s.get("wholesale_price") or 0)
            if w and (not eng or w < eng):
                eng = w
    if eng:
        return eng
    for s in p.get("shop_prices") or []:
        if s.get("shop_id") == SHOP_ID:
            return float(s.get("retail_price") or 0)
    return 0.0


def chakana_narx(p: dict) -> float:
    for s in p.get("shop_prices") or []:
        if s.get("shop_id") == SHOP_ID:
            return float(s.get("retail_price") or 0)
    return 0.0


def qoldiq(p: dict) -> float:
    for s in p.get("shop_measurement_values") or []:
        if s.get("shop_id") == SHOP_ID:
            return float(s.get("active_measurement_value") or 0)
    return 0.0


def aksiya_narx(p: dict) -> float:
    """Billz chegirma (promo) narxi shu do'kon uchun. Yo'q bo'lsa 0."""
    for s in p.get("shop_prices") or []:
        if s.get("shop_id") == SHOP_ID:
            pp = float(s.get("promo_price") or 0)
            rp = float(s.get("retail_price") or 0)
            if pp and rp and pp < rp:
                return pp
    return 0.0


# Qaysi webp qaysi Billz manzilidan olingani — manzil o'zgarsa (ya'ni
# Billz'ga YANGI rasm yuklangan bo'lsa) katalog o'zi yangilanadi.
# Busiz tuzatilgan kartalar katalogga hech qachon yetib bormaydi.
MANBA_F = PAPKA / "rasm_manba.json"
try:
    MANBA = json.loads(MANBA_F.read_text(encoding="utf-8"))
except (OSError, ValueError):
    MANBA = {}
_mqulf = threading.Lock()


def rasmni_tayyorla(pid: str, url: str) -> bool:
    """Yuklab olib 450px WebP qilib saqlaydi.

    Fayl bor VA manbasi o'sha-o'sha bo'lsa qayta yuklamaydi. Billz'da rasm
    almashtirilgan bo'lsa manzil o'zgaradi — u holda qayta yuklaymiz.
    """
    fayl = RASM_PAPKA / f"{pid}.webp"
    if fayl.exists() and MANBA.get(pid) == url:
        return True
    try:
        r = requests.get(url, timeout=60)
        if not r.ok:
            return fayl.exists()
        im = Image.open(io.BytesIO(r.content)).convert("RGB")
        im.thumbnail((RASM_OLCHAM, RASM_OLCHAM), Image.LANCZOS)
        im.save(fayl, "WEBP", quality=RASM_SIFAT, method=4)
        with _mqulf:
            MANBA[pid] = url
        return True
    except Exception:
        return fayl.exists()


def main():
    H = billz_kirish()
    print("Billz'dan mahsulotlar olinmoqda...")
    xom, page = [], 1
    while True:
        r = requests.get(f"{HOST}/v2/products", headers=H,
                         params={"page": page, "limit": 100}, timeout=60).json()
        ch = r.get("products") or []
        if not ch:
            break
        xom.extend(ch)
        total = r.get("count") or 0
        if page * 100 >= total or page >= 60:
            break
        page += 1
    print(f"  {len(xom)} ta mahsulot")

    mahsulotlar, rasmli = [], []
    tashlandi = {"narxsiz": 0, "qoldiqsiz": 0, "kategoriyasiz": 0}
    for p in xom:
        narx = optom_narx(p)
        if narx <= 0:
            tashlandi["narxsiz"] += 1
            continue
        qold = qoldiq(p)
        if FAQAT_QOLDIQLI and qold <= 0:
            tashlandi["qoldiqsiz"] += 1
            continue
        kats = p.get("categories") or []
        yol = (kats[0].get("name") or "").strip() if kats else ""
        guruh, _, bolim = yol.partition(">")
        guruh, bolim = guruh.strip(), bolim.strip()
        if not guruh:
            tashlandi["kategoriyasiz"] += 1
            continue
        url = p.get("main_image_url_full") or ""
        pid = p["id"]
        aks = aksiya_narx(p)
        m = {
            "id": pid,
            "nom": (p.get("name") or "").strip(),
            "sku": p.get("sku") or "",
            "barcode": p.get("barcode") or "",
            "narx": round(narx),
            "chakana": round(chakana_narx(p)),
            "aksiya": round(aks),          # 0 = chegirma yo'q
            "qoldiq": round(qold),
            "guruh": guruh,
            "bolim": bolim or guruh,
            "rasm": bool(url),
        }
        mahsulotlar.append(m)
        if url:
            rasmli.append((pid, url))

    print(f"  katalogga yaroqli: {len(mahsulotlar)} | rasmli: {len(rasmli)}")
    print(f"  tashlandi — narxsiz: {tashlandi['narxsiz']}, "
          f"qoldiqsiz: {tashlandi['qoldiqsiz']}, "
          f"kategoriyasiz: {tashlandi['kategoriyasiz']}")

    print("\nRasmlar siqilmoqda (450px WebP)...")
    ok = xato = 0
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        ishlar = {ex.submit(rasmni_tayyorla, pid, u): pid for pid, u in rasmli}
        for i, f in enumerate(cf.as_completed(ishlar), 1):
            if f.result():
                ok += 1
            else:
                xato += 1
            if i % 200 == 0:
                print(f"  {i}/{len(rasmli)}")
    print(f"  tayyor: {ok} | xato: {xato}")
    try:
        MANBA_F.write_text(json.dumps(MANBA, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        print(f"  rasm_manba.json yozilmadi: {e}")

    # rasmi yuklanmaganlarni belgilaymiz
    bor = {f.stem for f in RASM_PAPKA.glob("*.webp")}
    for m in mahsulotlar:
        m["rasm"] = m["id"] in bor

    guruhlar = {}
    for m in mahsulotlar:
        guruhlar.setdefault(m["guruh"], set()).add(m["bolim"])
    daraxt = [{"guruh": g, "bolimlar": sorted(b)} for g, b in sorted(guruhlar.items())]

    from datetime import datetime
    vaqt = datetime.now().strftime("%d.%m.%Y %H:%M")

    # --- OCHIQ fayl: narxsiz (GitHub Pages'ga chiqadi) ---
    # Narx maydonlari olib tashlanadi, lekin "aksiyada" bayrog'i (aks:1/0)
    # qoladi — aksiya bo'limi PIN'siz ham ko'rinishi uchun. Chegirma NARXI
    # esa shifrlangan faylда (bayroq narxni oshkor qilmaydi).
    ochiq = []
    for m in mahsulotlar:
        o = {k: v for k, v in m.items() if k not in ("narx", "chakana", "aksiya")}
        o["aks"] = 1 if m["aksiya"] else 0
        ochiq.append(o)
    (PAPKA / "katalog.json").write_text(json.dumps(
        {"yangilandi": vaqt, "dokon": "Noyob", "daraxt": daraxt, "mahsulotlar": ochiq},
        ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # --- Narx PIN bilan SHIFRLANADI (narx_enc.json) ---
    # Fayl ochiq Pages'da yotadi, lekin PIN'siz o'qib bo'lmaydi. Ilova PIN
    # kiritilganda deshifrlaydi. Shifrlash Web Crypto bilan mos: PBKDF2-SHA256
    # (100k) -> AES-GCM. Xuddi shu algoritm index.html da takrorlanadi.
    # [optom, chakana, aksiya_narxi]  — aksiya narxi ham shifrlangan
    narxlar = {m["id"]: [m["narx"], m["chakana"], m["aksiya"]]
               for m in mahsulotlar}
    # Savdo API kaliti ham shifrlangan faylда — PIN kiritilgachgina buyurtma
    # yuborish mumkin. URL ochiq bo'lishi mumkin, kalit muhim.
    ochiq_json = json.dumps({
        "yangilandi": vaqt, "narxlar": narxlar,
        "api_url": SAVDO_API_URL, "api_kalit": SAVDO_API_KALIT,
    }, ensure_ascii=False, separators=(",", ":")).encode()
    salt = secrets.token_bytes(16)
    iv = secrets.token_bytes(12)
    kalit = hashlib.pbkdf2_hmac("sha256", PIN.encode(), salt, 100_000, dklen=32)
    aes = AESGCM(kalit)
    shifr = aes.encrypt(iv, ochiq_json, None)
    (PAPKA / "narx_enc.json").write_text(json.dumps({
        "v": 1, "salt": base64.b64encode(salt).decode(),
        "iv": base64.b64encode(iv).decode(),
        "data": base64.b64encode(shifr).decode(),
        "yangilandi": vaqt,
    }, separators=(",", ":")), encoding="utf-8")

    # --- Narxlarni savdo API'ga ham yuboramiz ---
    # Telegram Mini App (optom do'kondorlar) narxni shundan oladi: u yerда
    # kirish Telegram imzosi bilan tekshiriladi, PIN ishlatilmaydi.
    if SAVDO_API_KALIT:
        try:
            rr = requests.post(
                SAVDO_API_URL + "/narx/yukla",
                data=json.dumps({"yangilandi": vaqt, "narxlar": narxlar},
                                ensure_ascii=False).encode("utf-8"),
                headers={"X-Api-Kalit": SAVDO_API_KALIT,
                         "Content-Type": "application/json"},
                timeout=90)
            print(f"narx API'ga yuborildi: {'OK' if rr.ok else 'XATO ' + str(rr.status_code)}")
        except Exception as e:  # noqa: BLE001
            print(f"narx API'ga yuborilmadi: {type(e).__name__}")

    hajm = sum(f.stat().st_size for f in RASM_PAPKA.glob("*.webp"))
    print(f"\nkatalog.json (OCHIQ, narxsiz): {len(ochiq)} mahsulot, {len(daraxt)} guruh")
    print(f"narx_enc.json (PIN bilan SHIFRLANGAN): {len(mahsulotlar)} narx")
    # PIN jurnalga YOZILMAYDI — sinxron ommaviy repo'ning Actions jurnalida
    # ham yuriladi, u yerda har bir satr hammaga ko'rinadi.
    print(f"  PIN: {'*' * len(PIN)}  (o'zgartirish: .env da KATALOG_PIN=)")
    print(f"rasm papkasi: {len(bor)} ta fayl, {hajm/1024/1024:.1f} MB")


if __name__ == "__main__":
    main()
