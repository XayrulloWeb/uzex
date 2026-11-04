import React, { useState, useEffect, useRef } from 'react';
import confetti from 'canvas-confetti';
import ThreeCanvas from './components/ThreeCanvas';
import Header from './components/Header';
import QueryTerminal from './components/QueryTerminal';
import ResponseCard from './components/ResponseCard';
import SectorModal from './components/SectorModal';
import { sounds } from './utils/audio';
import { Sparkles, ShieldCheck, Zap } from 'lucide-react';

export default function App() {
  const [lang, setLang] = useState('uz');
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(false);
  const [queryText, setQueryText] = useState('');
  const [result, setResult] = useState(null);
  const [pulseTrigger, setPulseTrigger] = useState(0);
  const [isSectorModalOpen, setIsSectorModalOpen] = useState(false);

  const resultsRef = useRef(null);

  // Fetch overview stats
  useEffect(() => {
    fetch('/api/stats')
      .then(res => res.json())
      .then(data => setStats(data))
      .catch(err => console.error("Failed to fetch stats:", err));
  }, []);

  const handleQuery = async (q) => {
    setQueryText(q);
    setLoading(true);
    setPulseTrigger(Date.now());

    try {
      const res = await fetch('/api/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: q })
      });
      const data = await res.json();
      setResult(data);

      if (data.no_data) {
        sounds.playWarning();
      } else {
        sounds.playSuccess();
        // Subtle cyber confetti
        confetti({
          particleCount: 28,
          spread: 60,
          origin: { y: 0.8 },
          colors: ['#00f2fe', '#00f5a0', '#7f00ff']
        });
      }

      // Smooth scroll down to response card
      setTimeout(() => {
        if (resultsRef.current) {
          resultsRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
      }, 150);

    } catch (err) {
      console.error("Query failed:", err);
      setResult({
        answer: lang === 'uz' ? "Server bilan aloqa uzildi. Iltimos qaytadan urinib ko'ring." : "Ошибка связи с сервером. Пожалуйста, повторите запрос.",
        sql: null,
        records: [],
        no_data: true
      });
      sounds.playWarning();
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="app-container">
      {/* 3D WebGL Background Canvas */}
      <ThreeCanvas pulseTrigger={pulseTrigger} />

      {/* Header & Nav */}
      <Header
        lang={lang}
        setLang={setLang}
        soundEnabled={soundEnabled}
        setSoundEnabled={setSoundEnabled}
        stats={stats}
        onOpenSectors={() => setIsSectorModalOpen(true)}
      />

      {/* Main Interactive Stage */}
      <main className="main-stage">
        {/* Hero Section */}
        <section className="hero-header">
          <div className="hero-tag">
            <Zap size={13} className="text-cyan inline-icon" />
            <span>UZEX AI HACKATHON 2026 // SARALASH BOSQICHI</span>
          </div>

          <h1 className="hero-title">
            {lang === 'uz' ? (
              <>
                Birja Bitimlari Bo‘yicha <br />
                <span className="gradient-text">Kognitiv AI-Agent</span>
              </>
            ) : (
              <>
                Когнитивный AI-Агент <br />
                <span className="gradient-text">Биржевых Сделок UZEX</span>
              </>
            )}
          </h1>

          <p className="hero-desc">
            {lang === 'uz'
              ? "500,000 ta birja bitimi, shartnomalar kartochkalari, ishtirokchilar va kunlik valyuta kurslari asosida mutlaqo faktik, o'ta aniq va nolinchi gallyutsinatsiyali ma'lumotlar tahlili."
              : "Мгновенный прецизионный анализ 500 000 сделок, карточек контрактов, участников и курсов валют биржи UZEX (2022–2026). Строгая защита от галлюцинаций и полная доказательная база."}
          </p>
        </section>

        {/* Query Input Terminal */}
        <QueryTerminal
          lang={lang}
          onQuery={handleQuery}
          loading={loading}
        />

        {/* Dynamic Response & Grounding Card */}
        <div ref={resultsRef} style={{ width: '100%', display: 'flex', justifyContent: 'center' }}>
          {result && (
            <ResponseCard
              result={result}
              lang={lang}
              queryText={queryText}
            />
          )}
        </div>
      </main>

      {/* Sector Exploration Modal */}
      <SectorModal
        isOpen={isSectorModalOpen}
        onClose={() => setIsSectorModalOpen(false)}
        lang={lang}
      />
    </div>
  );
}
