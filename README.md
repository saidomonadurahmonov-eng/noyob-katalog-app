# Noyob — agent planshet katalogi

Savdo agenti supermarketlarga olib kiradigan planshet uchun katalog.
Internetsiz to'liq ishlaydi.

## Kundalik ish tartibi

**Ofisda (Wi-Fi bor):**

```bash
python C:/Users/user/noyob-planshet/sync.py
```

Billz'dan mahsulot, ombor qoldig'i, optom narx va rasmlarni oladi. Rasmlarni
450px WebP qilib siqadi (570 MB → 26 MB). Keyin planshetda ilovani ochib
**⬇ Offline** tugmasini bosing — hamma rasm qurilmaga tushadi.

**Supermarketda (internet yo'q):** ilova o'zi ishlayveradi. Katalog, rasm,
narx, qidiruv, buyurtma — hammasi keshdan.

## Narx qayerda turadi

Optom narx **ochiq faylda yo'q** — raqobatchi ko'rmasligi uchun.

| Fayl | Ichida | Qayerga chiqadi |
|---|---|---|
| `katalog.json` | nom, kategoriya, qoldiq, rasm | ochiq (GitHub Pages) |
| `narx.json` | faqat narxlar | `.gitignore` — hech qayerga |

Planshetda narx ikki yo'ldan biri bilan keladi va `localStorage` da keshlanadi:

1. Yonida `narx.json` bo'lsa (lokal sinov)
2. Bot API'sidan — `/api/catalog`, agent Telegram orqali bir marta kirgach

Keshlangandan keyin internetsiz ham ko'rinaveradi.

## Sozlamalar (`sync.py` boshida)

| O'zgaruvchi | Hozir | Ma'nosi |
|---|---|---|
| `SHOP_ID` | `dee67ee3…` | Склад NOYOB (ombor) |
| `FAQAT_QOLDIQLI` | `True` | qoldig'i tugagani katalogga tushmaydi |
| `RASM_OLCHAM` | 450 | rasm tomoni, px |

Boshqa do'kon narxi kerak bo'lsa `SHOP_ID` ni almashtiring:
NOYOB BOZOR `aa14a186-30c6-4742-85a6-284de3078a8e`,
Noyob DUKON 2 `48e0e5ec-29b5-4472-942a-c4a57405147c`.

## Hozirgi holat

1 122 mahsulot katalogda, 697 tasida rasm bor (62%).
Tashlanganlar: qoldig'i yo'q 1495, ombor narxi yo'q 295, kategoriyasiz 37.

Rasmsiz 425 mahsulot — ular uchun `noyob-katalog` dagi rembg + Gemini karta
liniyasi ishlatilishi mumkin (hodim rasmga oladi → karta yasaladi → Billz).

## Sinovdan o'tgan

Server butunlay o'chirilgan holda: 1122 mahsulot, 45 kategoriya, rasmlar
keshdan, narx keshdan, qidiruv ishlaydi. Buyurtma `localStorage` da saqlanadi,
"📤 Yuborish" matn qilib beradi (Telegramga qo'yiladi).
