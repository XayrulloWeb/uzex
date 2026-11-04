import React, { useEffect, useState } from 'react';
import { X, BarChart3, TrendingUp, Layers, ArrowUpRight } from 'lucide-react';
import { sounds } from '../utils/audio';

export default function SectorModal({ isOpen, onClose, lang }) {
  const [sectors, setSectors] = useState([]);
  const [recentDeals, setRecentDeals] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!isOpen) return;
    setLoading(true);
    Promise.all([
      fetch('/api/sectors').then(r => r.json()).catch(() => ({ sectors: [] })),
      fetch('/api/recent-deals').then(r => r.json()).catch(() => ({ deals: [] }))
    ]).then(([secData, dealsData]) => {
      setSectors(secData.sectors || []);
      setRecentDeals(dealsData.deals || []);
      setLoading(false);
    });
  }, [isOpen]);

  if (!isOpen) return null;

  const totalVol = sectors.reduce((sum, s) => sum + (s.total_uzs || 0), 0);

  return (
    <div className="modal-backdrop">
      <div className="modal-glass">
        {/* Header */}
        <div className="modal-header">
          <div className="modal-title-group">
            <BarChart3 size={20} className="text-cyan" />
            <h2>{lang === 'uz' ? 'Birja Sektorlari va Bozor Tahlili' : 'Секторы Биржи и Анализ Рынка'}</h2>
          </div>
          <button 
            className="modal-close-btn"
            onClick={() => { sounds.playClick(); onClose(); }}
          >
            <X size={20} />
          </button>
        </div>

        {loading ? (
          <div className="modal-loading">
            <div className="spinner"></div>
            <span>{lang === 'uz' ? 'Maʼlumotlar yuklanmoqda...' : 'Загрузка данных...'}</span>
          </div>
        ) : (
          <div className="modal-content">
            {/* Sector Breakdown Grid */}
            <div className="sector-grid">
              {sectors.map((sec, idx) => {
                const pct = totalVol > 0 ? (sec.total_uzs / totalVol) * 100 : 0;
                return (
                  <div key={idx} className="sector-card-item">
                    <div className="sector-header-row">
                      <span className="sector-name">{sec.category}</span>
                      <span className="sector-pct">{pct.toFixed(1)}%</span>
                    </div>
                    <div className="sector-progress-bar">
                      <div className="sector-progress-fill" style={{ width: `${pct}%` }}></div>
                    </div>
                    <div className="sector-stats-row">
                      <span>{sec.deals_count.toLocaleString()} {lang === 'uz' ? 'bitim' : 'сделок'}</span>
                      <span className="sector-amount">{(sec.total_uzs / 1e9).toFixed(1)} mlrd UZS</span>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Recent Deals Table */}
            <div className="recent-deals-section">
              <h3 className="section-title">
                <TrendingUp size={16} className="text-emerald inline-icon" />
                <span>{lang === 'uz' ? 'Oxirgi Tuzilgan Bitimlar (Jonli Reestr)' : 'Последние Заключенные Сделки (Реестр)'}</span>
              </h3>
              <div className="recent-table-wrapper">
                <table className="recent-table">
                  <thead>
                    <tr>
                      <th>№</th>
                      <th>{lang === 'uz' ? 'Sana' : 'Дата'}</th>
                      <th>{lang === 'uz' ? 'Tovar' : 'Товар'}</th>
                      <th>{lang === 'uz' ? 'Hajm' : 'Объем'}</th>
                      <th>{lang === 'uz' ? 'Summa (UZS)' : 'Сумма (UZS)'}</th>
                      <th>{lang === 'uz' ? 'Holat' : 'Статус'}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentDeals.map((d, i) => (
                      <tr key={i}>
                        <td className="deal-num">#{d.deal_num}</td>
                        <td>{d.deal_date}</td>
                        <td className="deal-product">{d.product_name}</td>
                        <td>{d.quantity.toLocaleString()} {d.unit}</td>
                        <td className="deal-amount-cell">{d.deal_amount_uzs.toLocaleString()} soʻm</td>
                        <td><span className={`status-tag ${d.status === 'Исполнен' ? 'tag-green' : 'tag-gray'}`}>{d.status}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
