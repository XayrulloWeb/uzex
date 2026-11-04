import React from 'react';
import { Volume2, VolumeX, ShieldCheck, Cpu, Globe2, BarChart3, Database } from 'lucide-react';
import { sounds } from '../utils/audio';

export default function Header({ 
  lang, 
  setLang, 
  soundEnabled, 
  setSoundEnabled, 
  stats, 
  onOpenSectors 
}) {
  const toggleSound = () => {
    const newState = sounds.toggle();
    setSoundEnabled(newState);
    if (newState) sounds.playClick();
  };

  const changeLang = (l) => {
    sounds.playClick();
    setLang(l);
  };

  return (
    <header className="header-glass">
      {/* Top Banner Ticker */}
      <div className="ticker-bar">
        <div className="ticker-track">
          <span className="ticker-item">
            <span className="pulse-dot"></span>
            <b>REESTR:</b> 500,000 BITIM (2022–2026)
          </span>
          <span className="ticker-divider">/</span>
          <span className="ticker-item">
            <b>AYLANMA:</b> {stats ? (stats.total_volume_uzs / 1e12).toFixed(1) : '220.4'} TRLN UZS
          </span>
          <span className="ticker-divider">/</span>
          <span className="ticker-item">
            <b>SHARTNOMALAR:</b> {stats ? stats.contracts_count.toLocaleString() : '6,616'}
          </span>
          <span className="ticker-divider">/</span>
          <span className="ticker-item">
            <b>ISHTIROKCHILAR:</b> {stats ? stats.sellers_count.toLocaleString() : '14,392'} KOMPANIYA
          </span>
          <span className="ticker-divider">/</span>
          <span className="ticker-item">
            <b>USD KURSI:</b> 1 USD = {stats ? stats.latest_usd_rate.toLocaleString() : '13,212'} UZS
          </span>
          <span className="ticker-divider">/</span>
          <span className="ticker-item highlight">
            <ShieldCheck size={14} className="inline-icon" /> ZERO-HALLUCINATION VERIFIED
          </span>
        </div>
      </div>

      {/* Main Navbar */}
      <div className="nav-container">
        {/* Brand identity */}
        <div className="brand-block">
          <div className="brand-logo">
            <Cpu size={24} className="logo-icon" />
          </div>
          <div>
            <div className="brand-title">
              <span className="brand-uzex">UZEX</span> SYNAPSE
              <span className="badge-year">2026</span>
            </div>
            <div className="brand-subtitle">
              {lang === 'uz' ? 'Kognitiv Birja AI-Agenti' : 'Когнитивный AI-Агент Биржи'}
            </div>
          </div>
        </div>

        {/* Center Status Indicators */}
        <div className="center-badges">
          <div className="guard-badge" title="Gallyutsinatsiyalarga qarshi 100% himoya tizimi faol">
            <ShieldCheck size={16} className="text-emerald" />
            <span>ZERO-HALLUCINATION GUARD</span>
          </div>

          <button 
            className="sector-btn" 
            onClick={() => { sounds.playClick(); onOpenSectors(); }}
            onMouseEnter={() => sounds.playHover()}
          >
            <BarChart3 size={15} />
            <span>{lang === 'uz' ? 'Birja Sektorlari' : 'Секторы Биржи'}</span>
          </button>
        </div>

        {/* Controls */}
        <div className="controls-block">
          {/* Sound Toggle */}
          <button 
            className={`icon-btn ${soundEnabled ? 'active' : ''}`}
            onClick={toggleSound}
            title={soundEnabled ? 'Ovozni o‘chirish' : 'Ovozni yoqish'}
          >
            {soundEnabled ? <Volume2 size={18} /> : <VolumeX size={18} />}
          </button>

          {/* Language Switcher */}
          <div className="lang-switcher">
            <button 
              className={`lang-pill ${lang === 'uz' ? 'active' : ''}`}
              onClick={() => changeLang('uz')}
              onMouseEnter={() => sounds.playHover()}
            >
              UZ
            </button>
            <button 
              className={`lang-pill ${lang === 'ru' ? 'active' : ''}`}
              onClick={() => changeLang('ru')}
              onMouseEnter={() => sounds.playHover()}
            >
              RU
            </button>
          </div>
        </div>
      </div>
    </header>
  );
}
