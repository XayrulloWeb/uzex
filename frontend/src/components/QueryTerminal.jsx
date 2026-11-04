import React, { useState } from 'react';
import { Search, Send, Sparkles, AlertTriangle, ArrowRight, CornerDownLeft } from 'lucide-react';
import { sounds } from '../utils/audio';

const PRESET_QUERIES = {
  uz: [
    { label: '🏆 Sement xaridorlari 2024', query: 'Qaysi kompaniya 2024-yilda eng koʻp sement sotib olgan va qancha summaga?' },
    { label: '💎 Eng yirik eksport bitimi', query: 'Eng yirik eksport bitimi qachon, kimlar o\'rtasida va qancha summaga tuzilgan?' },
    { label: '⛽ Benzin narxi tahlili', query: '2023-yil avgust oyida AI-92 benzini bo\'yicha o\'rtacha birja narxi qancha bo\'lgan?' },
    { label: '🏢 Kompaniya (STIR)', query: 'STIR 953758401 bo\'lgan kompaniya haqida ma\'lumot' },
    { label: '🏛 Broker BK001 aylanmasi', query: 'BK001 brokeri orqali tuzilgan bitimlar soni va umumiy aylanmasi qancha?' },
    { label: '⚠️ Bekor qilingan bitimlar', query: '2025-yilda qancha bitim bekor qilingan (annulirovan)?' },
    { label: '🛡 Gallyutsinatsiya testi: Oltin', query: '2024-yilda oltin (gold) sotilganmi?' },
    { label: '🛡 Gallyutsinatsiya: Soxta STIR', query: 'STIR 999999999 kompaniyasi qancha bug\'doy sotgan?' },
  ],
  ru: [
    { label: '🏆 Покупатели цемента 2024', query: 'Какая компания в 2024 году купила больше всего цемента и на какую сумму?' },
    { label: '💎 Крупнейший экспорт', query: 'Какая самая крупная экспортная сделка за все время?' },
    { label: '⛽ Средняя цена бензина АИ-92', query: 'Какая средняя цена бензина АИ-92 в августе 2023 года?' },
    { label: '🏢 Досье по ИНН 953758401', query: 'Информация по компании с ИНН 953758401' },
    { label: '🏛 Оборот брокера BK001', query: 'Сколько сделок и какой товарооборот у брокера BK001?' },
    { label: '⚠️ Аннулированные сделки 2025', query: 'Сколько сделок аннулировано в 2025 году?' },
    { label: '🛡 Тест: Несуществующая фирма', query: 'Сколько металла продала компания OOO "Global Super Trade"?' },
    { label: '🛡 Тест: Торговля золотом', query: 'Проводились ли сделки по золоту в 2024 году?' },
  ]
};

export default function QueryTerminal({ lang, onQuery, loading }) {
  const [inputVal, setInputVal] = useState('');

  const handleSubmit = (e) => {
    if (e) e.preventDefault();
    if (!inputVal.trim() || loading) return;
    sounds.playPulse();
    onQuery(inputVal.trim());
  };

  const handleChipClick = (q) => {
    sounds.playClick();
    setInputVal(q);
    onQuery(q);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const presets = PRESET_QUERIES[lang] || PRESET_QUERIES.uz;

  return (
    <div className="terminal-container">
      {/* Search Input Box */}
      <form onSubmit={handleSubmit} className="search-form-glass">
        <div className="search-glow-border"></div>
        <div className="search-inner">
          <div className="search-icon-wrapper">
            <Search size={22} className="search-icon" />
          </div>

          <input
            type="text"
            className="search-input"
            value={inputVal}
            onChange={(e) => setInputVal(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              lang === 'uz'
                ? "Birja bitimlari bo'yicha savolingizni yozing (masalan: 2024 sement xaridorlari, STIR, broker)..."
                : "Задайте вопрос по биржевым сделкам (например: лидеры по цементу 2024, ИНН, брокер)..."
            }
          />

          <button
            type="submit"
            disabled={!inputVal.trim() || loading}
            className={`submit-btn ${loading ? 'loading' : ''}`}
            onMouseEnter={() => sounds.playHover()}
          >
            {loading ? (
              <div className="spinner"></div>
            ) : (
              <>
                <span>{lang === 'uz' ? 'So‘rash' : 'Запрос'}</span>
                <CornerDownLeft size={16} />
              </>
            )}
          </button>
        </div>
      </form>

      {/* Preset Chips */}
      <div className="presets-wrapper">
        <div className="presets-title">
          <Sparkles size={14} className="text-cyan inline-icon" />
          <span>{lang === 'uz' ? 'Tezkor sinov stsenariylari:' : 'Быстрые сценарии проверки:'}</span>
        </div>
        <div className="presets-chips">
          {presets.map((item, idx) => (
            <button
              key={idx}
              className={`preset-chip ${item.label.includes('🛡') ? 'guard-chip' : ''}`}
              onClick={() => handleChipClick(item.query)}
              onMouseEnter={() => sounds.playHover()}
            >
              <span>{item.label}</span>
              <ArrowRight size={12} className="chip-arrow" />
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
