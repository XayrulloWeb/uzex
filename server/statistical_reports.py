"""Statistical distribution and analytical aggregation reports.
Covers questions on:
1) Mean vs Median of deals with skewness/economic explanation (RU & UZ).
2) Unique sellers/buyers count with median & average turnover across entities (RU & UZ).
"""
from __future__ import annotations

import re
from decimal import Decimal
from server.ai_models import AIQuestion, money
from server.db import query


def is_statistical_query(question: str) -> bool:
    q = question.lower()
    
    # Pattern 1: Mean and Median comparison / calculation
    has_mean = bool(re.search(r"o['’`]?rtacha\s+arifmetik|среднее\s+арифметическ|arifmetik|mean", q))
    has_median = bool(re.search(r"median|медиан", q))
    if has_mean and has_median:
        return True
    if has_median and bool(re.search(r"farq|разниц|nima uchun|почему|taqqosla|сравни", q)):
        return True

    # Pattern 2: Unique entities (sellers/buyers) and median turnover
    has_unique_entity = bool(re.search(r"(?:уникальн|noyob|unique).*(?:продавц|покупател|sotuvchi|xaridor|seller|buyer)|(?:продавц|покупател|sotuvchi|xaridor|seller|buyer).*(?:уникальн|noyob|unique)", q))
    has_turnover = bool(re.search(r"оборот|aylanma|turnover|стоимост|qiymat|summa|сумм", q))
    if has_unique_entity and (has_median or has_turnover):
        return True
    
    if has_median and bool(re.search(r"sotuvchi|xaridor|продавц|покупател", q)):
        return True

    return False


def generate_statistical_report(request: AIQuestion) -> dict | None:
    q = request.question
    ql = q.lower()
    lang = getattr(request, 'lang', 'ru')
    uz = (lang == 'uz')

    # Detect year
    year_match = re.search(r'(?<!\d)(202[2-6])(?!\d)', q)
    year = int(year_match.group(1)) if year_match else (request.scope.year if request.scope and request.scope.year else 2025)

    # Detect status requirement (e.g. executed/fulfilled)
    status_filter = "status = 'Исполнен'" if re.search(r"to['’`]?liq\s+bajarilgan|bajarilgan|исполнен|fully\s+executed|executed", ql) else "1=1"

    # CASE A: Mean vs Median of deals
    is_deal_stats = bool(re.search(r"o['’`]?rtacha|среднее|arifmetik|mean", ql)) and bool(re.search(r"median|медиан", ql))
    if is_deal_stats or (bool(re.search(r"median|медиан", ql)) and not re.search(r"sotuvchi|xaridor|продавц|покупател", ql)):
        sql = f"""
        SELECT 
            count(*) as total_deals,
            avg(amount_uzs) as mean_amount,
            median(amount_uzs) as median_amount,
            min(amount_uzs) as min_amount,
            max(amount_uzs) as max_amount,
            quantile_cont(amount_uzs, 0.25) as q25,
            quantile_cont(amount_uzs, 0.75) as q75
        FROM trades
        WHERE year(deal_date) = ? AND {status_filter}
        """
        rows = query(sql, [year])
        if not rows or not rows[0]['total_deals']:
            return None

        row = rows[0]
        deals_count = int(row['total_deals'])
        mean_uzs = Decimal(str(row['mean_amount']))
        median_uzs = Decimal(str(row['median_amount']))
        min_uzs = Decimal(str(row['min_amount']))
        max_uzs = Decimal(str(row['max_amount']))

        if uz:
            status_desc = "to‘liq bajarilgan" if "status = 'Исполнен'" in status_filter else "barcha"
            answer = (
                f"### {year}-yilda {status_desc} bitimlar bo‘yicha o‘rtacha arifmetik va mediana tahlili\n\n"
                f"• **Jami ko‘rib chiqilgan bitimlar:** {deals_count:,} ta\n"
                f"• **O‘rtacha arifmetik summa (Mean):** {money(mean_uzs)} UZS (~{money(mean_uzs / Decimal(1000000), 2)} mln so‘m)\n"
                f"• **Mediana summa (Median):** {money(median_uzs)} UZS (~{money(median_uzs / Decimal(1000000), 2)} mln so‘m)\n"
                f"• **Eng kichik bitim (Min):** {money(min_uzs)} UZS\n"
                f"• **Eng yirik bitim (Max):** {money(max_uzs)} UZS (~{money(max_uzs / Decimal(1000000000), 2)} mlrd so‘m)\n\n"
                f"*(Barcha xorijiy valyutadagi / dollar bitimlari har bir bitim sanasidagi O‘zbekiston Respublikasi Markaziy bankining rasmiy kursi bo‘yicha so‘mga avtomatik konvertatsiya qilingan).*\n\n"
                f"#### Nima uchun bu ikki ko‘rsatkich farq qiladi?\n"
                f"1. **Taqsimotning o‘ng tomonga kuchli cho‘zilganligi (Right-skewed / Heavy-tail):** Birja bozorida bitimlarning asosiy massasi o‘rtacha va kichik hajmlarda amalga oshiriladi, biroq sanoat miqyosidagi ayrim gigant bitimlar (maksimal {money(max_uzs / Decimal(1000000000), 2)} mlrd so‘mgacha) mavjud.\n"
                f"2. **O‘rtacha arifmetikning zaifligi:** O‘rtacha arifmetik hisobda barcha bitimlar summasi qo‘shilib umumiy songa bo‘lingani bois, bunday yirik bitimlar butun ko‘rsatkichni sun’iy ravishda yuqoriga ({money(mean_uzs / Decimal(1000000), 2)} mln so‘mga) tortadi.\n"
                f"3. **Mediananing mustahkamligi (Robustness):** Mediana ekstremal qiymatlarga (outliers) berilmaydi va barcha bitimlarni o‘sish tartibida teng ikkiga ajratadi — bitimlarning roppa-rosa 50% qismi {money(median_uzs / Decimal(1000000), 2)} mln so‘mdan past, qolgan 50% qismi esa undan yuqori. Shuning uchun birjadagi odatiy (tipik) bitim hajmini baholashda aynan mediana ko‘rsatkichi obyektiv hisoblanadi."
            )
        else:
            status_desc = "полностью исполненным" if "status = 'Исполнен'" in status_filter else "всем"
            answer = (
                f"### Анализ среднего арифметического и медианы по {status_desc} сделкам за {year} год\n\n"
                f"• **Всего учтено сделок:** {deals_count:,}\n"
                f"• **Среднее арифметическое (Mean):** {money(mean_uzs)} UZS (~{money(mean_uzs / Decimal(1000000), 2)} млн сум)\n"
                f"• **Медианная сумма сделки (Median):** {money(median_uzs)} UZS (~{money(median_uzs / Decimal(1000000), 2)} млн сум)\n"
                f"• **Минимальная сделка:** {money(min_uzs)} UZS\n"
                f"• **Максимальная сделка:** {money(max_uzs)} UZS (~{money(max_uzs / Decimal(1000000000), 2)} млрд сум)\n\n"
                f"*(Все валютные/долларовые контракты конвертированы в сумы по официальному курсу ЦБ РУз на дату совершения каждой конкретной сделки).*\n\n"
                f"#### Почему эти два показателя различаются?\n"
                f"1. **Правосторонняя асимметрия распределения (Right-skewed / Парето-эффект):** Распределение сумм биржевых сделок не является нормальным. Большинство контрактов совершается на умеренные суммы, но на бирже регулярно заключаются мегасделки промышленного масштаба (вплоть до {money(max_uzs / Decimal(1000000000), 2)} млрд сум).\n"
                f"2. **Чувствительность среднего к экстремумам:** Среднее арифметическое суммирует весь совокупный объём и делит на число сделок, поэтому редкие крупные сделки сильно смещают среднюю планку вверх ({money(mean_uzs / Decimal(1000000), 2)} млн сум).\n"
                f"3. **Робастность медианы:** Медиана устойчива к выбросам и делит ранжированный массив ровно пополам — ровно у половины сделок сумма меньше {money(median_uzs / Decimal(1000000), 2)} млн сум, а у половины больше. Поэтому медиана наиболее объективно отражает размер типовой сделки на бирже."
            )

        rows_data = [
            {"indicator": "Jami bitimlar soni" if uz else "Всего сделок", "value": deals_count, "unit": "ta" if uz else "сделок"},
            {"indicator": "O‘rtacha arifmetik summa" if uz else "Среднее арифметическое", "value": float(mean_uzs), "unit": "UZS"},
            {"indicator": "Mediana summa" if uz else "Медианная сумма", "value": float(median_uzs), "unit": "UZS"},
            {"indicator": "Minimal summa" if uz else "Минимальная сделка", "value": float(min_uzs), "unit": "UZS"},
            {"indicator": "Maksimal summa" if uz else "Максимальная сделка", "value": float(max_uzs), "unit": "UZS"}
        ]

        columns_def = [
            {"key": "indicator", "label": "Ko‘rsatkich" if uz else "Показатель", "kind": "text"},
            {"key": "value", "label": "Qiymat" if uz else "Значение", "kind": "decimal"},
            {"key": "unit", "label": "Birlik" if uz else "Единица", "kind": "text"}
        ]

        return {
            "status": "answer",
            "answer": answer,
            "rows": rows_data,
            "columns": columns_def,
            "provenance": {
                "method": "Grounded SQL aggregation over verified DuckDB trades. Currency conversion computed dynamically per deal date via CB rates table.",
                "sql": sql,
                "parameters": [year]
            },
            "provider": {"kind": "local", "model": "verified-distribution-stats", "attempts": 0, "used_backup": False}
        }

    # CASE B: Unique sellers/buyers count with median turnover across entities
    is_seller = not bool(re.search(r"xaridor|покупател|buyer", ql))
    role_col = "seller" if is_seller else "buyer"
    inn_col = f"{role_col}_inn"
    name_col = f"{role_col}_name"

    sql_entity = f"""
    WITH entity_totals AS (
        SELECT 
            {inn_col} as inn, 
            {name_col} as name, 
            count(*) as deals_cnt, 
            sum(amount_uzs) as turnover_uzs
        FROM trades
        WHERE year(deal_date) = ? AND {status_filter}
        GROUP BY {inn_col}, {name_col}
    )
    SELECT 
        count(*) as total_entities,
        median(turnover_uzs) as median_turnover,
        avg(turnover_uzs) as avg_turnover,
        min(turnover_uzs) as min_turnover,
        max(turnover_uzs) as max_turnover,
        sum(turnover_uzs) as grand_total
    FROM entity_totals;
    """

    res = query(sql_entity, [year])
    if not res or not res[0]['total_entities']:
        return None

    row = res[0]
    total_entities = int(row['total_entities'])
    median_turnover = Decimal(str(row['median_turnover']))
    avg_turnover = Decimal(str(row['avg_turnover']))
    min_turnover = Decimal(str(row['min_turnover']))
    max_turnover = Decimal(str(row['max_turnover']))
    grand_total = Decimal(str(row['grand_total']))

    if uz:
        role_label = "sotuvchilar" if is_seller else "xaridorlar"
        single_role = "sotuvchi" if is_seller else "xaridor"
        status_desc = "kamida bitta to‘liq bajarilgan bitimga ega" if "status = 'Исполнен'" in status_filter else "faoliyat yuritgan"
        answer = (
            f"### {year}-yilda {status_desc} noyob {role_label} va ularning aylanmasi bo‘yicha statistika\n\n"
            f"• **Noyob (unikal) {role_label} soni:** **{total_entities} ta**\n"
            f"• **Bir {single_role}ga to‘g‘ri keluvchi aylanmaning medianasi:** **{money(median_turnover)} UZS** (~{money(median_turnover / Decimal(1000000000), 2)} mlrd so‘m)\n"
            f"• **O‘rtacha aylanma:** {money(avg_turnover)} UZS (~{money(avg_turnover / Decimal(1000000000), 2)} mlrd so‘m)\n"
            f"• **Barcha {role_label}ning umumiy aylanmasi:** {money(grand_total)} UZS (~{money(grand_total / Decimal(1000000000000), 2)} trln so‘m)\n"
            f"• **Eng kichik {single_role} aylanmasi:** {money(min_turnover)} UZS\n"
            f"• **Eng yirik {single_role} aylanmasi:** {money(max_turnover)} UZS (~{money(max_turnover / Decimal(1000000000), 2)} mlrd so‘m)\n\n"
            f"*(Barcha dollar bitimlari har bir bitim sanasidagi Markaziy bank kursi bilan so‘mga konvertatsiya qilingan holda hisoblangan).*"
        )
    else:
        role_label = "продавцов" if is_seller else "покупателей"
        single_role = "продавца" if is_seller else "покупателя"
        status_desc = "имевших хотя бы одну полностью исполненную сделку" if "status = 'Исполнен'" in status_filter else "активных"
        answer = (
            f"### Статистика по уникальным {role_label} и их обороту за {year} год\n\n"
            f"• **Количество уникальных {role_label} ({status_desc}):** **{total_entities}**\n"
            f"• **Медиана оборота на одного {single_role}:** **{money(median_turnover)} UZS** (~{money(median_turnover / Decimal(1000000000), 2)} млрд сум)\n"
            f"• **Средний оборот на одного {single_role}:** {money(avg_turnover)} UZS (~{money(avg_turnover / Decimal(1000000000), 2)} млрд сум)\n"
            f"• **Совокупный оборот всех {role_label}:** {money(grand_total)} UZS (~{money(grand_total / Decimal(1000000000000), 2)} трлн сум)\n"
            f"• **Минимальный оборот {single_role}:** {money(min_turnover)} UZS\n"
            f"• **Максимальный оборот крупнейшего {single_role}:** {money(max_turnover)} UZS (~{money(max_turnover / Decimal(1000000000), 2)} млрд сум)\n\n"
            f"*(Долларовые сделки пересчитаны в сумы по курсу ЦБ РУз на дату совершения каждой сделки).*"
        )

    rows_data = [
        {"indicator": f"Noyob {role_label} soni" if uz else f"Уникальных {role_label}", "value": total_entities, "unit": "ta" if uz else "компаний"},
        {"indicator": "Aylanma medianasi" if uz else "Медиана оборота", "value": float(median_turnover), "unit": "UZS"},
        {"indicator": "O‘rtacha aylanma" if uz else "Средний оборот", "value": float(avg_turnover), "unit": "UZS"},
        {"indicator": "Jami yig‘indi aylanma" if uz else "Совокупный оборот", "value": float(grand_total), "unit": "UZS"}
    ]

    columns_def = [
        {"key": "indicator", "label": "Ko‘rsatkich" if uz else "Показатель", "kind": "text"},
        {"key": "value", "label": "Qiymat" if uz else "Значение", "kind": "decimal"},
        {"key": "unit", "label": "Birlik" if uz else "Единица", "kind": "text"}
    ]

    return {
        "status": "answer",
        "answer": answer,
        "rows": rows_data,
        "columns": columns_def,
        "provenance": {
            "method": "Grounded multi-stage SQL: 1) Group deals by entity INN to get total turnover per participant; 2) Compute median and summary distribution across all participants.",
            "sql": sql_entity,
            "parameters": [year]
        },
        "provider": {"kind": "local", "model": "verified-entity-turnover", "attempts": 0, "used_backup": False}
    }
