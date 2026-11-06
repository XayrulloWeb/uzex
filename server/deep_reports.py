"""Deterministic deep multi-intent analytical engine for UZEX Observatory.
Handles composite analytical queries combining entity rankings, commodity deep dives,
cancellation breakdowns, counterparty analysis, market shares, and delivery discipline.
"""
from __future__ import annotations

import calendar
import re
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Optional

from server.ai_models import AIQuestion, money
from server.catalog import COMMODITIES, commodity_label, normalize
from server.db import query


def detect_commodity_in_text(text: str) -> Optional[str]:
    """Find known commodity alias in query text, supporting inflected forms."""
    q = normalize(text).lower()
    if re.search(r'хлоп(?:ок|к[а-я]*)|paxta\w*', q):
        return 'cotton'
    if re.search(r'мед[ьияею]|mis\w*', q):
        return 'copper'
    if re.search(r'семент\w*|цемент\w*|cement\w*', q):
        return 'cement'
    if re.search(r'пшениц\w*|bug[\'’]?doy\w*', q):
        return 'wheat'
    if re.search(r'сахар\w*|shakar\w*', q):
        return 'sugar'
    if re.search(r'бензин\w*|benzin\w*', q):
        return 'gasoline'

    for item in COMMODITIES:
        code = item[0]
        aliases = [item[1], item[2], item[3], *item[-1]]
        for a in sorted(aliases, key=len, reverse=True):
            a_norm = normalize(a).lower().strip()
            if not a_norm:
                continue
            pattern = r'(?<!\w)' + re.escape(a_norm) + (r'\w*' if len(a_norm) >= 4 else r'(?!\w)')
            if re.search(pattern, q):
                return code
    return None


def is_deep_report_query(question: str) -> bool:
    """Identify if a question requires a composite multi-stage analytical report.
    Only triggers on heavy composite queries (combining cancellations breakdown,
    counterparties, delivery discipline, and commodity/totals), avoiding basic benchmark queries.
    """
    q = question.lower()
    has_commodity = bool(re.search(r'tovar|товар', q)) or (detect_commodity_in_text(q) is not None)
    has_cancellations = bool(re.search(r'bekor|аннулир', q))
    has_late = bool(re.search(r'kechik|опоздан|prosroch|просроч', q))
    has_seller_or_buyer = bool(re.search(r'sotuvchi|xaridor|sotgan|xarid\s+qil|продав|покупат', q))
    has_totals = bool(re.search(r'jami\s+summa|общая\s+сумма|jami\s+hajm|общий\s+объем|jami\s+bitim|общ\w*\s+число|o[\'’]?rtacha\s+narx|средн\w*\s+цена', q))

    # 1. Commodity + cancellations + (seller or buyer) + totals/late
    if has_commodity and has_cancellations and has_seller_or_buyer and (has_totals or has_late):
        return True

    # 2. Cancellations + Late deliveries simultaneously
    if has_cancellations and has_late:
        return True

    # 3. Commodity leader + totals + cancellations
    has_top_comm = bool(re.search(r'summasi\s+eng\s+katta|eng\s+(?:katta|ko[\'’]?p|yirik)\s+tovar|крупнейш\w*\s+товар|товар\w*\s+лидер', q))
    if has_top_comm and (has_cancellations or has_totals):
        return True

    return False


def generate_deep_report(request: AIQuestion) -> Optional[Dict[str, Any]]:
    q = request.question
    lang = getattr(request, 'lang', 'ru')
    uz = (lang == 'uz')

    # 1. Period / Year detection
    year_match = re.search(r'(?<!\d)(202[2-6])(?!\d)', q)
    year = int(year_match.group(1)) if year_match else (request.scope.year if request.scope and request.scope.year else 2024)

    # Quarter detection
    quarter = None
    q_match = re.search(r'\b([1-4])(?:\s*-?\s*(?:й|м|ом|го))?\s*[- ]?\s*(?:квартал\w*|chora[kg]\w*)', q, re.I)
    if q_match:
        quarter = int(q_match.group(1))

    # 2. Filters
    contract_type = 'Экспортный' if re.search(r'eksport|экспорт', q, re.I) else 'Внутренний' if re.search(r'ichki|внутренн', q, re.I) else None
    form = 'Спот' if re.search(r'\bspot|\bспот', q, re.I) else 'Форвард' if re.search(r'\bforward|\bфорвард', q, re.I) else None

    # Base WHERE builder
    where_clauses = ['year(deal_date) = ?']
    where_params = [year]

    if quarter:
        start_month = (quarter - 1) * 3 + 1
        end_month = start_month + 2
        last_day = calendar.monthrange(year, end_month)[1]
        where_clauses.append('deal_date BETWEEN ? AND ?')
        where_params.extend([f"{year}-{start_month:02d}-01", f"{year}-{end_month:02d}-{last_day:02d}"])

    if contract_type:
        where_clauses.append('contract_type = ?')
        where_params.append(contract_type)

    if form:
        where_clauses.append('form = ?')
        where_params.append(form)

    # 3. Commodity detection or ranking
    named_commodity = detect_commodity_in_text(q)
    target_commodity = named_commodity

    if not target_commodity:
        # Determine top commodity by amount or volume
        rank_col = 'amount_native' if contract_type == 'Экспортный' else 'amount_uzs'
        top_comm_sql = f"""
        SELECT commodity, count(*) as deals, sum({rank_col}) as total_amt
        FROM trades
        WHERE {' AND '.join(where_clauses)}
        GROUP BY commodity
        ORDER BY total_amt DESC
        LIMIT 1
        """
        top_comm_rows = query(top_comm_sql, where_params)
        if top_comm_rows and top_comm_rows[0]['commodity']:
            target_commodity = top_comm_rows[0]['commodity']

    # Add commodity to filter if we have one
    comm_where = list(where_clauses)
    comm_params = list(where_params)
    if target_commodity:
        comm_where.append('commodity = ?')
        comm_params.append(target_commodity)

    comm_name = commodity_label(target_commodity, lang) if target_commodity else ("Барча товарлар" if not uz else "Barcha tovarlar")

    # Currency
    is_usd = (contract_type == 'Экспортный') or bool(re.search(r'\busd\b|dollar|доллар', q, re.I))
    curr_col = 'amount_native' if is_usd else 'amount_uzs'
    currency_label = 'USD' if is_usd else 'UZS'

    # 4. Summary totals (All registered)
    summary_sql = f"""
    SELECT 
        count(*) as deals_count,
        sum({curr_col}) as total_amount,
        sum(quantity) as total_volume,
        sum({curr_col}) / nullif(sum(quantity), 0) as weighted_price,
        min(unit) as sample_unit,
        count(distinct seller_inn) as distinct_sellers,
        count(distinct buyer_inn) as distinct_buyers
    FROM trades
    WHERE {' AND '.join(comm_where)}
    """
    summary_res = query(summary_sql, comm_params)[0]
    deals_count = int(summary_res['deals_count'] or 0)
    if deals_count == 0:
        return None

    total_amount = Decimal(str(summary_res['total_amount'] or 0))
    total_volume = Decimal(str(summary_res['total_volume'] or 0))
    weighted_price = Decimal(str(summary_res['weighted_price'] or 0))
    unit_str = summary_res['sample_unit'] or ('тонна' if not uz else 'tonna')
    distinct_sellers = int(summary_res['distinct_sellers'] or 0)
    distinct_buyers = int(summary_res['distinct_buyers'] or 0)

    # 5. Cancellation Breakdown
    canc_where = list(comm_where) + ["status = 'Аннулирован(Не оплачен)'"]
    canc_sql = f"""
    SELECT 
        count(*) as canc_count,
        coalesce(sum({curr_col}), 0) as canc_amount
    FROM trades
    WHERE {' AND '.join(canc_where)}
    """
    canc_res = query(canc_sql, comm_params)[0]
    canc_count = int(canc_res['canc_count'] or 0)
    canc_amount = Decimal(str(canc_res['canc_amount'] or 0))

    active_count = deals_count - canc_count
    active_amount = total_amount - canc_amount

    # 6. Counterparty Ranking (Top seller or Top buyer)
    want_buyer = bool(re.search(r'xaridor|xarid\s+qilgan|покупател|купивш', q, re.I))
    party_col = 'buyer_inn' if want_buyer else 'seller_inn'
    party_name_col = 'buyer_name' if want_buyer else 'seller_name'
    broker_col = 'buyer_broker' if want_buyer else 'seller_broker'

    party_sql = f"""
    SELECT 
        {party_col} as inn,
        {party_name_col} as name,
        {broker_col} as broker,
        count(*) as deals,
        sum({curr_col}) as amount,
        sum(quantity) as volume
    FROM trades
    WHERE {' AND '.join(comm_where)}
    GROUP BY {party_col}, {party_name_col}, {broker_col}
    ORDER BY amount DESC
    LIMIT 1
    """
    party_rows = query(party_sql, comm_params)
    if party_rows:
        top_party = party_rows[0]
        party_inn = top_party['inn'] or "—"
        party_name = top_party['name'] or "—"
        party_broker = top_party['broker'] or "—"
        party_deals = int(top_party['deals'] or 0)
        party_amount = Decimal(str(top_party['amount'] or 0))
        party_volume = Decimal(str(top_party['volume'] or 0))
        share_total = (party_amount / total_amount * 100) if total_amount else Decimal(0)
        share_active = (party_amount / active_amount * 100) if active_amount else Decimal(0)
    else:
        party_inn, party_name, party_broker, party_deals, party_amount, party_volume, share_total, share_active = "—", "—", "—", 0, Decimal(0), Decimal(0), Decimal(0), Decimal(0)

    # 7. Delivery Discipline (Executed trades)
    late_where = list(comm_where) + ["status = 'Исполнен'", "delivery_date IS NOT NULL"]
    late_sql = f"""
    SELECT 
        count(*) as delivered_count,
        sum(case when late_delivery then 1 else 0 end) as late_count,
        max(case when late_delivery then (delivery_date - (payment_date + delivery_days)) else 0 end) as max_delay
    FROM trades
    WHERE {' AND '.join(late_where)}
    """
    late_res = query(late_sql, comm_params)[0]
    delivered_count = int(late_res['delivered_count'] or 0)
    late_count = int(late_res['late_count'] or 0)
    late_pct = (Decimal(late_count) / Decimal(delivered_count) * 100) if delivered_count else Decimal(0)
    max_delay = int(late_res['max_delay'] or 0)

    # 8. Build textual answer
    period_label = f"{year}-yil" if uz else f"{year} год"
    if quarter:
        period_label += f" ({quarter}-chorak)" if uz else f" ({quarter}-й квартал)"

    party_role_label = ("xaridor" if want_buyer else "sotuvchi") if uz else ("покупатель" if want_buyer else "продавец")

    if uz:
        lines = [
            f"{period_label}da ko‘rib chiqilayotgan tovar: {comm_name} (kod: {target_commodity}).",
            "",
            "Barcha ro‘yxatga olingan bitimlar (bekor qilinganlar bilan birga):",
            f"• Jami summa: {money(total_amount, 2)} {currency_label}",
            f"• Bitimlar soni: {money(deals_count, 0)} ta bitim",
            f"• Jami hajm: {money(total_volume, 4)} {unit_str}",
            f"• O‘rtacha tortilgan narx: {money(weighted_price, 2)} {currency_label} / {unit_str}",
            f"• Ishtirokchilar: {distinct_sellers} ta turli sotuvchi, {distinct_buyers} ta turli xaridor",
            "",
            "Bekor qilingan bitimlar tahlili:",
            f"• Bekor qilinganlar: {money(canc_count, 0)} ta bitim ({money(canc_amount, 2)} {currency_label})",
            f"• Bekor qilinganlarsiz sof summa: {money(active_amount, 2)} {currency_label} ({money(active_count, 0)} ta bitim)",
            "",
            f"Eng faol {party_role_label}:",
            f"• Nomi: {party_name}",
            f"• STIR: {party_inn}",
            f"• Broker: {party_broker}",
            f"• Summasi: {money(party_amount, 2)} {currency_label} ({money(party_deals, 0)} ta bitim)",
            f"• Umumiy hajmdagi ulushi: {money(share_total, 2)}% (bekor qilinganlarsiz ulushi: {money(share_active, 2)}%)",
            "",
            "Yetkazib berish intizomi (ijro etilgan bitimlar):",
            f"• Yetkazib berilgan jami bitimlar: {money(delivered_count, 0)} ta bitim",
            f"• Shartnoma muddatidan kechikkanlar: {money(late_count, 0)} ta bitim ({money(late_pct, 2)}%)",
            f"• Eng katta kechikish: {max_delay} kun"
        ]
    else:
        lines = [
            f"В периоде ({period_label}) анализируемый товар: {comm_name} (код: {target_commodity}).",
            "",
            "Показатели по всем зарегистрированным сделкам (включая аннулированные):",
            f"• Общая сумма: {money(total_amount, 2)} {currency_label}",
            f"• Число сделок: {money(deals_count, 0)} сделок",
            f"• Физический объём: {money(total_volume, 4)} {unit_str}",
            f"• Средневзвешенная цена: {money(weighted_price, 2)} {currency_label} / {unit_str}",
            f"• Контрагенты: {distinct_sellers} продавцов, {distinct_buyers} покупателей",
            "",
            "Анализ аннулированных сделок:",
            f"• Аннулировано: {money(canc_count, 0)} сделок ({money(canc_amount, 2)} {currency_label})",
            f"• Сумма без аннулированных: {money(active_amount, 2)} {currency_label} ({money(active_count, 0)} сделок)",
            "",
            f"Крупнейший {party_role_label}:",
            f"• Наименование: {party_name}",
            f"• ИНН / STIR: {party_inn}",
            f"• Брокер: {party_broker}",
            f"• Сумма: {money(party_amount, 2)} {currency_label} ({money(party_deals, 0)} сделок)",
            f"• Доля в общем объёме: {money(share_total, 2)}% (без аннулированных: {money(share_active, 2)}%)",
            "",
            "Исполнение сроков поставок:",
            f"• Всего исполненных поставок: {money(delivered_count, 0)} сделок",
            f"• С задержкой срока: {money(late_count, 0)} сделок ({money(late_pct, 2)}%)",
            f"• Максимальная задержка: {max_delay} дней"
        ]

    rows = [
        {
            "category": "Jami / Всего" if uz else "Всего",
            "commodity": comm_name,
            "deals": deals_count,
            "volume": float(total_volume),
            "amount": float(total_amount),
            "weighted_price": float(weighted_price),
            "unit": currency_label
        },
        {
            "category": "Faol / Без аннулированных" if uz else "Без аннулированных",
            "commodity": comm_name,
            "deals": active_count,
            "volume": float(total_volume),
            "amount": float(active_amount),
            "weighted_price": float(weighted_price),
            "unit": currency_label
        },
        {
            "category": f"Yetakchi {party_role_label}" if uz else f"Лидер ({party_role_label})",
            "commodity": f"{party_name} ({party_inn})",
            "deals": party_deals,
            "volume": float(party_volume),
            "amount": float(party_amount),
            "weighted_price": float(share_total),
            "unit": "%"
        }
    ]

    columns = [
        {"key": "category", "label": "Kategoriya" if uz else "Категория", "kind": "text"},
        {"key": "commodity", "label": "Tovar / Ishtirokchi" if uz else "Товар / Участник", "kind": "text"},
        {"key": "deals", "label": "Bitimlar" if uz else "Сделки", "kind": "integer"},
        {"key": "amount", "label": f"Summa ({currency_label})" if uz else f"Сумма ({currency_label})", "kind": "decimal", "unit": currency_label},
        {"key": "weighted_price", "label": "O‘rtacha narx / Ulush" if uz else "Ср. цена / Доля", "kind": "decimal"}
    ]

    return {
        "status": "answer",
        "answer": "\n".join(lines),
        "rows": rows,
        "columns": columns,
        "provenance": {
            "method": "Deterministic multi-stage deep analytical report on 500k UZEX trades.",
            "operations": [
                {"title": "Summary", "sql": summary_sql, "parameters": comm_params},
                {"title": "Cancellations", "sql": canc_sql, "parameters": comm_params},
                {"title": "Counterparty", "sql": party_sql, "parameters": comm_params},
                {"title": "Late deliveries", "sql": late_sql, "parameters": comm_params}
            ]
        },
        "provider": {
            "kind": "local",
            "model": "verified-deep-report",
            "attempts": 0,
            "used_backup": False
        }
    }
