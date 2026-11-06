"""Deterministic deep analytical report for export commodity leaders."""
from __future__ import annotations

import re
from decimal import Decimal
from server.ai_models import AIQuestion, money
from server.catalog import commodity_label
from server.db import query


def is_export_deep_query(question: str) -> bool:
    q = question.lower()
    has_export = bool(re.search(r'eksport|экспорт', q))
    has_top = bool(re.search(r'eng\s+(?:katta|ko\'p|yirik)|наибольш|крупнейш|лидер|больше\s+всего', q))
    has_commodity = bool(re.search(r'tovar|товар', q))
    has_details = bool(re.search(r'bekor|аннулир|sotuvchi|продав|kechik|опоздан|prosroch|просроч', q))
    return has_export and has_top and has_commodity and has_details


def generate_export_deep_report(request: AIQuestion):
    q = request.question
    lang = getattr(request, 'lang', 'ru')
    uz = (lang == 'uz')

    # 1. Detect year
    year_match = re.search(r'(?<!\d)(202[2-6])(?!\d)', q)
    year = int(year_match.group(1)) if year_match else (request.scope.year if request.scope and request.scope.year else 2024)

    # 2. Find top export commodity by USD amount
    top_comm_sql = """
    SELECT commodity, count(*) as deals, sum(amount_native) as total_usd
    FROM trades
    WHERE year(deal_date) = ? AND contract_type = 'Экспортный'
    GROUP BY commodity
    ORDER BY total_usd DESC
    LIMIT 1
    """
    top_comm_rows = query(top_comm_sql, [year])
    if not top_comm_rows:
        return None

    top_comm = top_comm_rows[0]
    comm = top_comm['commodity']
    comm_name = commodity_label(comm, lang)

    # 3. All registered deals for this commodity
    all_deals_sql = """
    SELECT 
        count(*) as deals_count,
        sum(amount_native) as total_usd,
        sum(quantity) as total_volume,
        sum(amount_native) / nullif(sum(quantity), 0) as weighted_price,
        min(unit) as sample_unit
    FROM trades
    WHERE year(deal_date) = ? AND contract_type = 'Экспортный' AND commodity = ?
    """
    all_deals = query(all_deals_sql, [year, comm])[0]

    deals_count = int(all_deals['deals_count'] or 0)
    total_usd = Decimal(str(all_deals['total_usd'] or 0))
    total_vol = Decimal(str(all_deals['total_volume'] or 0))
    w_price = Decimal(str(all_deals['weighted_price'] or 0))
    unit_str = all_deals['sample_unit'] or ('тонна' if not uz else 'tonna')

    # 4. Cancelled deals
    canc_sql = """
    SELECT 
        count(*) as canc_count,
        coalesce(sum(amount_native), 0) as canc_usd
    FROM trades
    WHERE year(deal_date) = ? AND contract_type = 'Экспортный' AND commodity = ?
      AND status = 'Аннулирован(Не оплачен)'
    """
    canc_res = query(canc_sql, [year, comm])[0]
    canc_count = int(canc_res['canc_count'] or 0)
    canc_usd = Decimal(str(canc_res['canc_usd'] or 0))

    active_count = deals_count - canc_count
    active_usd = total_usd - canc_usd

    # 5. Top seller
    top_seller_sql = """
    SELECT 
        seller_inn,
        seller_name,
        count(*) as cnt,
        sum(amount_native) as seller_usd
    FROM trades
    WHERE year(deal_date) = ? AND contract_type = 'Экспортный' AND commodity = ?
    GROUP BY seller_inn, seller_name
    ORDER BY seller_usd DESC
    LIMIT 1
    """
    top_seller_res = query(top_seller_sql, [year, comm])
    if top_seller_res:
        top_seller = top_seller_res[0]
        seller_inn = top_seller['seller_inn']
        seller_name = top_seller['seller_name']
        seller_usd = Decimal(str(top_seller['seller_usd'] or 0))
        seller_cnt = int(top_seller['cnt'] or 0)
        share_total = (seller_usd / total_usd * 100) if total_usd else Decimal(0)
        share_active = (seller_usd / active_usd * 100) if active_usd else Decimal(0)
    else:
        seller_inn, seller_name, seller_usd, seller_cnt, share_total, share_active = "—", "—", Decimal(0), 0, Decimal(0), Decimal(0)

    # 6. Late deliveries
    late_sql = """
    SELECT 
        count(*) as delivered_count,
        sum(case when late_delivery then 1 else 0 end) as late_count,
        max(case when late_delivery then (delivery_date - (payment_date + delivery_days)) else 0 end) as max_delay
    FROM trades
    WHERE year(deal_date) = ? AND contract_type = 'Экспортный' AND commodity = ?
      AND status = 'Исполнен' AND delivery_date IS NOT NULL
    """
    late_res = query(late_sql, [year, comm])[0]
    delivered_count = int(late_res['delivered_count'] or 0)
    late_count = int(late_res['late_count'] or 0)
    late_pct = (Decimal(late_count) / Decimal(delivered_count) * 100) if delivered_count else Decimal(0)
    max_delay = int(late_res['max_delay'] or 0)

    # 7. Formulate text answer
    if uz:
        lines = [
            f"{year}-yilda eksport bitimlari bo‘yicha dollardagi summasi eng katta bo‘lgan tovar — {comm_name} (commodity: {comm}).",
            "",
            "Barcha ro‘yxatga olingan bitimlar bo‘yicha ko‘rsatkichlar (bekor qilinganlar bilan birga):",
            f"• Jami summa: {money(total_usd, 2)} USD",
            f"• Bitimlar soni: {money(deals_count, 0)} ta bitim",
            f"• Jami hajm: {money(total_vol, 4)} {unit_str}",
            f"• O‘rtacha tortilgan narx: {money(w_price, 2)} USD / {unit_str}",
            "",
            "Bekor qilingan bitimlar tahlili:",
            f"• Bekor qilingan bitimlar: {money(canc_count, 0)} ta bitim ({money(canc_usd, 2)} USD)",
            f"• Bekor qilinganlarsiz summa: {money(active_usd, 2)} USD ({money(active_count, 0)} ta bitim)",
            "",
            "Eng ko‘p sotgan sotuvchi:",
            f"• Nomi: {seller_name}",
            f"• STIR: {seller_inn}",
            f"• Summasi: {money(seller_usd, 2)} USD ({money(seller_cnt, 0)} ta bitim)",
            f"• Umumiy summadagi ulushi: {money(share_total, 2)}% (bekor qilinganlarsiz summadagi ulushi: {money(share_active, 2)}%)",
            "",
            "Yetkazib berish intizomi (ijro etilgan bitimlar):",
            f"• Yetkazib berilgan bitimlar soni: {money(delivered_count, 0)} ta bitim",
            f"• Muddatidan kechikib yetkazilganlar: {money(late_count, 0)} ta bitim ({money(late_pct, 2)}%)",
            f"• Eng katta kechikish: {max_delay} kun"
        ]
    else:
        lines = [
            f"В {year} году товаром с наибольшей суммой экспортных сделок в долларах является {comm_name} (commodity: {comm}).",
            "",
            "Показатели по всем зарегистрированным сделкам (включая аннулированные):",
            f"• Общая сумма: {money(total_usd, 2)} USD",
            f"• Число сделок: {money(deals_count, 0)} сделок",
            f"• Физический объём: {money(total_vol, 4)} {unit_str}",
            f"• Средневзвешенная цена: {money(w_price, 2)} USD / {unit_str}",
            "",
            "Анализ аннулированных сделок:",
            f"• Число аннулированных: {money(canc_count, 0)} сделок ({money(canc_usd, 2)} USD)",
            f"• Сумма без аннулированных: {money(active_usd, 2)} USD ({money(active_count, 0)} сделок)",
            "",
            "Крупнейший продавец:",
            f"• Наименование: {seller_name}",
            f"• ИНН / STIR: {seller_inn}",
            f"• Сумма продаж: {money(seller_usd, 2)} USD ({money(seller_cnt, 0)} сделок)",
            f"• Доля в общем экспорте: {money(share_total, 2)}% (без аннулированных: {money(share_active, 2)}%)",
            "",
            "Сроки поставок (по исполненным сделкам):",
            f"• Всего исполненных поставок: {money(delivered_count, 0)}",
            f"• С задержкой срока: {money(late_count, 0)} сделок ({money(late_pct, 2)}%)",
            f"• Максимальная задержка: {max_delay} дней"
        ]

    answer = "\n".join(lines)

    rows = [
        {
            "category": "Jami / Всего" if uz else "Всего",
            "commodity": comm_name,
            "deals": deals_count,
            "volume": float(total_vol),
            "amount_usd": float(total_usd),
            "weighted_price": float(w_price),
            "unit": unit_str
        },
        {
            "category": "Faol / Без аннулированных" if uz else "Без аннулированных",
            "commodity": comm_name,
            "deals": active_count,
            "volume": float(total_vol),
            "amount_usd": float(active_usd),
            "weighted_price": float(w_price),
            "unit": unit_str
        },
        {
            "category": "Yetakchi sotuvchi / Лидер-продавец" if uz else "Лидер-продавец",
            "commodity": f"{seller_name} ({seller_inn})",
            "deals": seller_cnt,
            "volume": 0,
            "amount_usd": float(seller_usd),
            "weighted_price": float(share_total),
            "unit": "%"
        }
    ]

    columns = [
        {"key": "category", "label": "Kategoriya" if uz else "Категория", "kind": "text"},
        {"key": "commodity", "label": "Tovar / Ishtirokchi" if uz else "Товар / Участник", "kind": "text"},
        {"key": "deals", "label": "Bitimlar" if uz else "Сделки", "kind": "integer"},
        {"key": "amount_usd", "label": "Summa (USD)" if uz else "Сумма (USD)", "kind": "decimal", "unit": "USD"},
        {"key": "weighted_price", "label": "O‘rtacha narx / Ulush" if uz else "Ср. цена / Доля", "kind": "decimal"}
    ]

    return {
        "status": "answer",
        "answer": answer,
        "rows": rows,
        "columns": columns,
        "provenance": {
            "method": "Multi-stage deterministic SQL pipeline across 500k deals in DuckDB. 1) Top export commodity ranking by USD amount; 2) Full volume & weighted price aggregation; 3) Cancellation split; 4) Seller group rank and share; 5) Delivery date minus (payment_date + delivery_days) latency calculation.",
            "operations": [
                {"title": "Commodity rank", "sql": top_comm_sql, "parameters": [year]},
                {"title": "All registered", "sql": all_deals_sql, "parameters": [year, comm]},
                {"title": "Cancellations", "sql": canc_sql, "parameters": [year, comm]},
                {"title": "Top seller", "sql": top_seller_sql, "parameters": [year, comm]},
                {"title": "Late deliveries", "sql": late_sql, "parameters": [year, comm]}
            ]
        },
        "provider": {
            "kind": "local",
            "model": "verified-deep-export-report",
            "attempts": 0,
            "used_backup": False
        }
    }
