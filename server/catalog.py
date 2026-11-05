"""Dataset vocabulary. Labels do not replace source identifiers or attributes."""
import re
import unicodedata

REGIONS = [
    ('karakalpakstan', 'Qoraqalpog‘iston Respublikasi', 'Каракалпакстан', 'Qoraqalpog‘iston', 59.61, 43.15, ['каракалп', 'qoraqalp', 'нукус', 'nukus']),
    ('khorezm', 'Xorazm viloyati', 'Хорезмская область', 'Xorazm', 60.63, 41.56, ['хорезм', 'xorazm', 'ургенч', 'urganch']),
    ('navoi', 'Navoiy viloyati', 'Навоийская область', 'Navoiy', 64.5, 42.05, ['наво', 'navoi']),
    ('bukhara', 'Buxoro viloyati', 'Бухарская область', 'Buxoro', 63.8, 40.2, ['бухар', 'buxoro']),
    ('samarkand', 'Samarqand viloyati', 'Самаркандская область', 'Samarqand', 66.96, 39.65, ['самарканд', 'samarqand', 'samarkand']),
    ('kashkadarya', 'Qashqadaryo viloyati', 'Кашкадарьинская область', 'Qashqadaryo', 66.0, 38.75, ['кашкадар', 'qashqadar', 'qarshi', 'карши']),
    ('surkhandarya', 'Surxondaryo viloyati', 'Сурхандарьинская область', 'Surxondaryo', 67.35, 38.05, ['сурхандар', 'surxondar', 'termez', 'термез']),
    ('jizzakh', 'Jizzax viloyati', 'Джизакская область', 'Jizzax', 67.75, 40.12, ['джизак', 'jizzax']),
    ('syrdarya', 'Sirdaryo viloyati', 'Сырдарьинская область', 'Sirdaryo', 68.65, 40.45, ['сырдар', 'sirdar', 'гулистан', 'guliston']),
    ('tashkent_region', 'Toshkent viloyati', 'Ташкентская область', 'Toshkent viloyati', 69.73, 41.15, ['ташкентск', 'toshkent viloyat', 'tashkent region']),
    ('tashkent_city', 'Toshkent shahri', 'Ташкент', 'Toshkent shahri', 69.24, 41.31, ['ташкент', 'toshkent', 'tashkent']),
    ('namangan', 'Namangan viloyati', 'Наманганская область', 'Namangan', 71.6, 41.0, ['наманган', 'namangan']),
    ('fergana', 'Farg‘ona viloyati', 'Ферганская область', 'Farg‘ona', 71.5, 40.35, ['ферган', "farg'ona", 'fergana']),
    ('andijan', 'Andijon viloyati', 'Андижанская область', 'Andijon', 72.3, 40.78, ['андижан', 'andijon', 'andijan']),
]
REGION_BY_ID = {r[0]: r for r in REGIONS}
REGION_BY_RAW = {r[1]: r[0] for r in REGIONS}

# TN VED 271019 is deliberately split: diesel and fuel oil are different products.
COMMODITIES = [
    ('cotton', '520100', 'Хлопок-сырец', 'Paxta xomashyosi', ['хлопок', 'хлопка', 'paxta', 'paxta xom ashyo', 'пахта']),
    ('flour', '110100', 'Пшеничная мука', 'Bug‘doy uni', ['мук', 'bugdoy uni', "bug'doy uni", ' un ', 'уни']),
    ('wheat', '100199', 'Пшеница', 'Bug‘doy', ['пшениц', 'bugdoy', "bug'doy", 'буғдой']),
    ('rice', '100630', 'Рис', 'Guruch', ['рис ', 'риса', 'guruch', 'гуруч']),
    ('cotton_oil', '151229', 'Хлопковое масло', 'Paxta yog‘i', ['хлопковое масло', 'масло хлопков', "paxta yog", 'пахта ёғ']),
    ('sunflower_oil', '151219', 'Подсолнечное масло', 'Kungaboqar yog‘i', ['подсолнеч', 'kungaboqar']),
    ('sugar', '170199', 'Сахар', 'Shakar', ['сахар', 'shakar', 'шакар']),
    ('water', '220190', 'Питьевая вода', 'Ichimlik suvi', ['воды', 'вода', 'питьев', 'ichimlik', 'suv']),
    ('meal', '230610', 'Хлопковый шрот', 'Paxta shroti', ['шрот', 'shrot']),
    ('feed', '230990', 'Комбикорм', 'Omuxta yem', ['комбикорм', 'кормосм', 'omuxta', 'yem']),
    ('salt', '250100', 'Пищевая соль', 'Osh tuzi', ['соль', 'соли', 'tuz']),
    ('gypsum', '252020', 'Гипс', 'Gips', ['гипс', 'gips']),
    ('lime', '252210', 'Известь', 'Ohak', ['извест', 'ohak']),
    ('cement', '252329', 'Портландцемент', 'Portlandsement', ['цемент', 'sement']),
    ('gasoline', '271012', 'Бензин', 'Benzin', ['бензин', 'benzin']),
    ('diesel', '271019', 'Дизельное топливо', 'Dizel yoqilg‘isi', ['дизел', 'dizel']),
    ('fuel_oil', '271019', 'Мазут', 'Mazut', ['мазут', 'mazut']),
    ('lpg', '271112', 'Сжиженный газ', 'Suyultirilgan gaz', ['сжиженн', 'пропан', 'suyultirilgan', 'propan']),
    ('bitumen', '271320', 'Нефтяной битум', 'Neft bitumi', ['битум', 'bitum']),
    ('argon', '280421', 'Аргон', 'Argon', ['аргон', 'argon']),
    ('nitrogen', '280430', 'Азот', 'Azot', ['азот', 'azot']),
    ('acid', '280700', 'Серная кислота', 'Sulfat kislota', ['серная', 'серной', 'sulfat', 'kislota']),
    ('soda', '281511', 'Каустическая сода', 'Kaustik soda', ['сода', 'соды', 'соду', 'kaustik', 'soda']),
    ('urea', '310210', 'Карбамид', 'Karbamid', ['карбамид', 'мочевин', 'karbamid', 'mochevina']),
    ('nitrate', '310230', 'Аммиачная селитра', 'Ammiakli selitra', ['селитр', 'selitra']),
    ('enamel', '320810', 'Эмаль', 'Emal', ['эмаль', 'эмали', 'emal']),
    ('polyethylene', '390120', 'Полиэтилен', 'Polietilen', ['полиэтилен', 'polietilen']),
    ('polypropylene', '390210', 'Полипропилен', 'Polipropilen', ['полипропилен', 'polipropilen']),
    ('pvc', '390410', 'Поливинилхлорид', 'Polivinilxlorid', ['поливинил', 'пвх', 'polivinil', 'pvc']),
    ('pipe', '391721', 'Полиэтиленовые трубы', 'Polietilen quvurlar', ['труб', 'quvur']),
    ('timber', '440711', 'Пиломатериалы', 'Yog‘och materiallari', ['пиломатер', 'yogoch', "yog'och"]),
    ('yarn', '520512', 'Хлопковая пряжа', 'Paxta kalavasi', ['пряж', 'kalava', 'ip ']),
    ('brick', '690410', 'Керамический кирпич', 'Keramik g‘isht', ['кирпич', 'gisht', "g'isht"]),
    ('glass', '700529', 'Листовое стекло', 'Listli shisha', ['стекл', 'shisha']),
    ('steel_sheet', '720853', 'Стальной лист', 'Po‘lat list', ['стальной лист', 'лист сталь', "po'lat list"]),
    ('rebar', '721420', 'Стальная арматура', 'Po‘lat armatura', ['арматур', 'armatura']),
    ('wire', '721710', 'Арматурная проволока', 'Armatura simi', ['проволок', 'sim ']),
    ('copper', '740311', 'Медный катод', 'Mis katodi', ['медь', 'меди', 'медн', 'катод', 'mis ', 'katod']),
    ('aluminium', '760421', 'Алюминиевый профиль', 'Alyuminiy profil', ['алюмин', 'alyumin']),
    ('bearing', '848210', 'Подшипник', 'Podshipnik', ['подшипник', 'podshipnik']),
    ('cable', '854449', 'Силовой кабель', 'Kuch kabeli', ['кабел', 'kabel']),
]
COMMODITY_BY_ID = {r[0]: r for r in COMMODITIES}
CODE_TO_ID = {r[1]: r[0] for r in COMMODITIES if r[1] != '271019'}
CANCELLED = 'Аннулирован(Не оплачен)'
SNAPSHOT = '2026-10-30'
STATUS_UZ = {'Исполнен': 'To‘liq bajarilgan', 'Исполнен(Частично)': 'Qisman bajarilgan', CANCELLED: 'To‘lovsiz bekor qilingan', 'Оплачен': 'To‘langan', 'Заключен': 'Tuzilgan', 'Ждёт оплату': 'To‘lov kutilmoqda', 'Не подписан': 'Imzolanmagan', 'Новый': 'Yangi'}


def normalize(value: str) -> str:
    value = unicodedata.normalize('NFKC', value).casefold().replace('ё', 'е')
    value = value.translate(str.maketrans({c: "'" for c in '‘’ʻʼ`ʹ'}))
    return re.sub(r'\s+', ' ', value).strip()


def commodity_for(code: str, name: str) -> str:
    if code == '271019':
        return 'diesel' if 'дизел' in name.casefold() else 'fuel_oil'
    return CODE_TO_ID[code]


def normalized_grade(value: str) -> str:
    t = normalize(value)
    if 'высш' in t or 'oliy' in t:
        return 'highest'
    m = re.search(r'(?<!\d)([12345])\s*[- ]?(?:сорт|sort)', t)
    if m:
        return m.group(1)
    words = [(3, ['трет', 'iii', 'uchinchi']), (2, ['втор', 'ii', 'ikkinchi']), (1, ['перв', 'i', 'birinchi'])]
    # Prefer "I сорт" over the following "сорт II класс" across an attribute boundary.
    for n, patterns in words:
        if any(t == p or re.search(r'\b' + re.escape(p) + r'\w*\s*[- ]?\s*(?:сорт|sort)\w*\b', t) for p in patterns):
            return str(n)
    for n, patterns in words:
        if any(re.search(r'\b(?:сорт|sort)\w*\s+' + re.escape(p) + r'\b', t) for p in patterns):
            return str(n)
    return ''


def region_label(identity: str, lang='ru') -> str:
    r = REGION_BY_ID.get(identity)
    return r[3 if lang == 'uz' else 2] if r else identity


def commodity_label(identity: str, lang='ru') -> str:
    c = COMMODITY_BY_ID.get(identity)
    return c[3 if lang == 'uz' else 2] if c else identity
