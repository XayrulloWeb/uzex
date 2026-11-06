"""Test statistical queries: Mean vs Median and Unique Entities Turnover."""
import pytest
from fastapi.testclient import TestClient
from server.app import app
from server.statistical_reports import is_statistical_query, generate_statistical_report
from server.ai_models import AIQuestion


def test_is_statistical_query():
    q1 = "Сколько уникальных продавцов имели хотя бы одну полностью исполненную сделку в 2025 году? Для каждого продавца рассчитайте общую стоимость таких сделок в сумах с конвертацией долларов по курсу на дату сделки, а затем найдите медиану оборота среди этих продавцов. Укажите оба результата."
    assert is_statistical_query(q1) is True

    q2 = "2025-yilda to‘liq bajarilgan barcha bitimlarning so‘mdagi qiymati bo‘yicha o‘rtacha arifmetik va median summani alohida hisoblang. Dollar bitimlarini har bir bitim sanasidagi kurs bilan aylantiring. Nima uchun bu ikki ko‘rsatkich farq qiladi?"
    assert is_statistical_query(q2) is True

    # General queries should not trigger statistical query
    assert is_statistical_query("Сколько всего сделок в 2024 году?") is False
    assert is_statistical_query("Курс доллара на 30 октября") is False


def test_unique_sellers_median_turnover_local():
    q = "Сколько уникальных продавцов имели хотя бы одну полностью исполненную сделку в 2025 году? Для каждого продавца рассчитайте общую стоимость таких сделок в сумах с конвертацией долларов по курсу на дату сделки, а затем найдите медиану оборота среди этих продавцов. Укажите оба результата."
    res = generate_statistical_report(AIQuestion(question=q, lang='ru'))
    assert res is not None
    assert res['status'] == 'answer'
    assert '319' in res['answer']
    assert '52' in res['answer']  # ~52.85 billion UZS
    assert len(res['rows']) == 4


def test_mean_and_median_deals_local():
    q = "2025-yilda to‘liq bajarilgan barcha bitimlarning so‘mdagi qiymati bo‘yicha o‘rtacha arifmetik va median summani alohida hisoblang. Dollar bitimlarini har bir bitim sanasidagi kurs bilan aylantiring. Nima uchun bu ikki ko‘rsatkich farq qiladi?"
    res = generate_statistical_report(AIQuestion(question=q, lang='uz'))
    assert res is not None
    assert res['status'] == 'answer'
    assert '102,261' in res['answer'] or '102 261' in res['answer'] or '102261' in res['answer']
    assert '483' in res['answer']  # ~483.45 mln
    assert '261' in res['answer']  # ~261.02 mln
    assert 'Nima uchun bu ikki ko‘rsatkich farq qiladi' in res['answer']
