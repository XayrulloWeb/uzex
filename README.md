# UZEX SYNAPSE 2026 // Birja Kognitiv AI-Agenti & Interaktiv Terminali

> **UZEX AI Hackathon 2026 (Saralash bosqichi)** uchun yaratilgan ikki tilli (RU + UZ), mutlaqo faktik va nolinchi gallyutsinatsiyali (Zero-Hallucination) sunʼiy intellekt agenti va 3D interaktiv birja terminali.

---

## 🌟 Asosiy Xususiyatlar va Imkoniyatlar

1. **100% Maʼlumotlarga Asoslangan (Zero-Hallucination Guardrail)**:
   - Agar soʻralgan kompaniya, tovar yoki davr birja reyestrida mavjud boʻlmasa, agent **buni ochiq aytadi** va hech qachon raqam yoki nomlarni oʻylab topmaydi (*xakatonning asosiy diskvalifikatsiya sharti*).
   - Har bir javob ortida aniq SQL-soʻrov, mos tushgan bitimlar roʻyxati va hisob-kitob formulasi keltiriladi.

2. **Ikki Tilli NLP Tahlil (RU + UZ)**:
   - Rus va oʻzbek tillaridagi erkin matnli savollarni avtomatik taniydi va shu tilda toʻliq hisobot shakllantiradi.
   - Oʻzbekcha o‘/g‘ harflari, apostroflar, sinonimlar va ruscha tovar nomlari oʻrtasida mukammal semantik bogʻlanish.

3. **Murakkab Birja Qoidalarining Toʻliq Qamrab Olinishi**:
   - **Lot va Birlik Narxi**: $\text{Bitim hajmi} = \text{Количество} \times \text{Лот}$; $\text{Birlik narxi} = \text{Сумма сделки} / \text{Bitim hajmi}$.
   - **Eksport va Valyuta**: Eksport bitimlari AQSh dollarida; soʻmdagi qiymat bitim sanasidagi kunlik dollar kursi (`usd_rates.csv`) boʻyicha aniq konvertatsiya qilinadi.
   - **Mintaqalar integratsiyasi**: `contracts.csv` dagi ruscha viloyat nomlari (`Ферганская область`) va `deals` dagi lotincha nomlar (`Farg‘ona viloyati`) toʻliq oʻzaro bogʻlangan.
   - **Bitimlar holati**: 8 ta holat (Исполнен, Аннулирован, Исполнен(Частично) va h.k.) inobatga olingan.

4. **Awwwards-Darajasidagi 3D Interaktiv Veb-Terminal**:
   - **Three.js WebGL 3D Galaxy**: 500 000 bitimni ifodalovchi yulduzli klaster va 6 ta asosiy tovar sektori.
   - **Web Audio API**: Taktil sci-fi audio qayta aloqa (tashqi fayllarsiz toza sintez).
   - **Glassmorphism & Cyber-Fintech UI**: Qorongʻi OLED fon, neon aksentlar, jonli reestr statistikasi va tezkor sinov tugmalari.

5. **Telegram Bot (aiogram 3)**:
   - Telegram orqali har qanday qurilmadan oʻrnatishsiz va roʻyxatdan oʻtishsiz tezkor ishlash imkoniyati.

---

## 📊 Maʼlumotlar Bazasi va Arxitektura

- **Hajm**: 500 000 ta birja bitimi (2022–2026), 6 616 ta shartnoma, 14 392 ta ishtirokchi, 120 ta broker, 1 765 kunlik valyuta kursi.
- **Dvigatel**: SQLite 3.50 (WAL mode, xotirada 64MB kesh) + FTS5 (Full-Text Search) + B-Tree indekslar.
- **Tezlik**: 500 000 yozuv boʻyicha agregat hisoblar — **15–40 millisekund** (90 soniyalik limitdan 2000 barobar tezroq!).

```
[Foydalanuvchi / Komissiya (RU / UZ)]
                 │
                 ▼
     [Web-Terminal / Telegram Bot]
                 │
                 ▼
┌──────────────────────────────────────────────┐
│ 1. Guardrail & Entity Resolver (FTS5):       │
│    STIR, Broker, Shartnoma, Tovar, Sana     │
│    Mavjud bo'lmasa -> STRICT GROUNDED REFUSAL│
└──────────────────────┬───────────────────────┘
                       │ (topilganda)
                       ▼
┌──────────────────────────────────────────────┐
│ 2. Schema-Aware Analytical SQL Generator     │
│    (Valyuta, lot, status hisob-kitoblari)    │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│ 3. Answer & Grounding Evidence Packager:     │
│    • Kognitiv tahlil va javob matni          │
│    • Bajarilgan SQL-soʻrov                   │
│    • Asos boʻlgan faktik yozuvlar jadvali    │
└──────────────────────────────────────────────┘
```

---

## 🚀 Ishga Tushirish (Quick Start)

### 1. Talablar
- Python 3.10+
- Node.js 18+ (faqat frontendni qayta yigʻish uchun, tayyor `dist` mavjud)

### 2. Oʻrnatish va bazani qurish
```bash
# Bogʻliqliklarni oʻrnatish
pip install -r requirements.txt

# Maʼlumotlar bazasini qurish (14 soniya davom etadi)
python build_db.py
```

### 3. Veb-xizmatni ishga tushirish
```bash
python server.py
# Brauzerda oching: http://localhost:8000
```

### 4. Telegram-botni ishga tushirish (ixtiyoriy)
```bash
set TELEGRAM_BOT_TOKEN=sizning_bot_tokeningiz
python bot.py
```

---

## 🏆 Sinov Savollari (Test Scenarios)

1. **Sement boʻyicha xaridlar**:
   - *«Qaysi kompaniya 2024-yilda eng koʻp sement sotib olgan va qancha summaga?»*
   - 👉 Natija: `LO‘HI IMPEKS MCHJ` (STIR: 955082698), 51,765 tonna, 44.58 mlrd soʻm, 342 ta bitim.

2. **Eng yirik eksport**:
   - *«Eng yirik eksport bitimi qachon, kimlar o'rtasida va qancha summaga tuzilgan?»*
   - 👉 Natija: Bitim №547500 (24.06.2026), Katod medniy M00k, $1,683,554.25 (22.24 mlrd soʻm), TIZAHI METALL MCHJ -> Bejul Savdo OK.

3. **Benzin narxlari tahlili**:
   - *«2023-yil avgust oyida AI-92 benzini bo'yicha o'rtacha birja narxi qancha bo'lgan?»*
   - 👉 Natija: Oʻrtacha tortilgan narx: 12,101.91 soʻm/tonna, 127 ta bitim, 40.8 mlrd soʻm aylanma.

4. **Gallyutsinatsiyadan himoya (Mavjud boʻlmagan subyekt)**:
   - *«OOO "Global Super Trade" qancha metall sotgan?»*
   - 👉 Natija: `❌ Maʼlumotlar bazasida kompaniya topilmadi. Reyestrda «Global Super Trade» nomli savdo ishtirokchisi mavjud emas.`

5. **Gallyutsinatsiyadan himoya (Mavjud boʻlmagan tovar)**:
   - *«2024-yilda oltin (gold) sotilganmi?»*
   - 👉 Natija: `❌ Maʼlumotlar bazasida javob yoʻq. Spot savdolari reyestrida «Oltin» boʻyicha hech qanday shartnoma yoki bitim qayd etilmagan.`
