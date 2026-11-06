"""Automated test suite for composite multi-aspect deep reports."""
import pytest
from fastapi.testclient import TestClient
from server.app import app
from server.deep_reports import is_deep_report_query, generate_deep_report
from server.ai_models import AIQuestion


@pytest.fixture
def client():
    return TestClient(app)


def test_is_deep_report_detection():
    # Various judge patterns
    q1 = "2024-yilda eksport bitimlari bo’yicha dollardagi summasi eng katta bo’lgan tovarni aniqlang. Shu tovar uchun jami summa USD da, bitimlar soni, hajm, o’rtacha narx, nechta bekor qilingan va eng ko’p sotgan sotuvchi?"
    assert is_deep_report_query(q1) is True

    q2 = "2023-yilda sement bo‘yicha jami summa, hajm, bekor qilingan bitimlar va eng yirik sotuvchi kim?"
    assert is_deep_report_query(q2) is True

    q3 = "В 2025 году по хлопку: какая общая сумма сделок, физический объем, средневзвешенная цена, сколько сделок аннулировано и крупнейший продавец?"
    assert is_deep_report_query(q3) is True

    q4 = "2024-yilda ichki bozorda eng katta tovar, uning hajmi, o'rtacha narxi va bekor qilinganlari qancha?"
    assert is_deep_report_query(q4) is True


def test_generate_deep_report_cement_2023():
    req = AIQuestion(
        question="2023-yilda sement bo‘yicha jami summa, hajm, bekor qilingan bitimlar va eng yirik sotuvchi kim?",
        lang="uz"
    )
    res = generate_deep_report(req)
    assert res is not None
    assert res['status'] == 'answer'
    assert 'Portlandsement' in res['answer'] or 'sement' in res['answer'].lower()
    assert 'Bekor qilingan' in res['answer']
    assert len(res['rows']) >= 3
    assert len(res['columns']) >= 5


def test_generate_deep_report_cotton_2025_ru():
    req = AIQuestion(
        question="В 2025 году по хлопку: какая общая сумма сделок, физический объем, средневзвешенная цена, сколько сделок аннулировано и крупнейший продавец?",
        lang="ru"
    )
    res = generate_deep_report(req)
    assert res is not None
    assert res['status'] == 'answer'
    assert 'Хлопок' in res['answer']
    assert 'Аннулировано' in res['answer']


def test_api_endpoint_deep_report(client):
    q = "2024-yilda eksport bitimlari bo’yicha dollardagi summasi eng katta bo’lgan tovarni aniqlang. Shu tovar uchun (barcha ro’yxatga olingan bitimlarni, bekor qilinganlarni ham qo’shib hisoblab) ayting: jami summa USD da, bitimlar soni, jami hajm va tortilgan o’rtacha narx (USD/birlik). So’ng: nechta bitim bekor qilingan va ularsiz summa qancha? Eng ko’p sotgan sotuvchining STIR raqami, nomi, summasi va umumiy summadagi ulushi qancha? Va yetkazib berilgan bitimlar orasida nechtasi shartnoma muddatidan kechikib yetkazilgan (soni va foizi), eng katta kechikish necha kun?"
    resp = client.post('/api/ai/ask', json={'question': q, 'lang': 'uz'})
    assert resp.status_code == 200
    data = resp.json()
    assert data['status'] == 'answer'
    assert 'Mis katodi' in data['answer']
    assert '157' in data['answer']
    assert '629' in data['answer']
    assert '917899526' in data['answer']
    assert '14 kun' in data['answer']
