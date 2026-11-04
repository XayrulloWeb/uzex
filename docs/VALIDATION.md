# Проверка UZEX Observatory и Gemini

Браузерный прогон: 04.11.2026 23:06 по Ташкенту. Проверена текущая локальная версия сайта. Живой запрос к Google Gemini не выполнен: секреты `UZEX_GEMINI_KEY_PRIMARY` и `UZEX_GEMINI_KEY_BACKUP` отсутствуют в работающей среде, доступ к домену сохранён в черновик, но применение не подтверждено.

## Что прошло

- Production-сборка TypeScript + Vite.
- **63 автоматических проверок: 0 ошибок, 0 пропущено.** Использована реальная база из 500 000 сделок и независимые эталоны CSV.
- **16 браузерных сценариев Chromium:** десктоп, мобильные 390/320 px, RU/UZ, 3D/2D, отсутствие WebGL, поиск, карточки, отчёты, CSV, обработка ошибок и AI-интерфейс.
- В реальном локальном HTTP-интерфейсе вопрос за 2024 год вернул 106 647 сделок через явно обозначенный локальный резерв; вопрос за 2027 год вернул честный отказ без чисел другого периода.
- Gemini failover проверен через `httpx.MockTransport`: 429, таймаут, сетевой сбой, 401/403, Google 400 API_KEY_INVALID, неверный JSON, снятая с доступа модель, cooldown и общий дедлайн. Эти тесты не подтверждают текущие квоты реальных ключей.
- Запрос модели не может превратиться из пустого JSON в общую статистику, подставить отсутствующий в вопросе идентификатор или проигнорировать явно указанный год.
- Проверены точные валютные суммы, лоты, разные единицы, средневзвешенная цена, крупнейшая экспортная сделка, различие даты сделки и оплаты, карточки справочников и различие сорта/класса.
- Повторяемые `scripts/install.sh` и `scripts/start.sh` проверены, исходные SHA-256 и полный импорт сохранены.
- Исходники форматированы Prettier; `git diff --check` выполняется перед коммитом.

## Сценарии браузера

- Desktop initial data, 3D scene and layout
- AI UI returns grounded 2024 count and reproducible SQL
- AI UI refuses absent 2027 data instead of fabricating zero or other years
- Missing Gemini credentials are a service error, not missing data
- All five years: 500,000 deals rendered
- Combined year, commodity and region filters
- 2D map selection and filter reset
- Report, provenance, CSV export and Escape dismissal
- Direct deal lookup, lot arithmetic and detail card
- Uzbek commodity search, registry pagination and page CSV
- Uzbek interface and language persistence
- Data error hides stale metrics; retry recovers
- Mobile 390px RU/UZ, modal and no horizontal overflow
- Mobile 320px RU/UZ, modal and no horizontal overflow
- No-WebGL browser retains interactive SVG map
- No uncaught browser JavaScript errors

## Скриншоты работающего сайта

- [Десктоп](screenshots/desktop.png)
- [Мобильная версия](screenshots/mobile.png)
- [Мобильная версия UZ](screenshots/mobile-uz.png)
- [Отказ на отсутствующий 2027 год](screenshots/ai-guardrails.png)
- [Карточка сделки](screenshots/deal.png)
- [Отчёт с основанием расчёта](screenshots/report.png)

Скриншоты получены из приложения. Отказ за 2027 год и подсчёт за 2024 год выполнялись без внешнего API; не следует выдавать их за успешный живой запрос Gemini.

## Что остаётся

Ввести значения двух ключей в защищённых настройках, сохранить/применить доступ к `generativelanguage.googleapis.com`, перезапустить сервис и проверить живой запрос. Нужно отдельно проверить понимание формулировок реальной моделью, фактическую квоту и время ответа. Публикация снимка среды, публичный хостинг и отправка конкурсной формы — отдельные действия; они не выполнены автоматически от Git push.

Код сайта заменил прежний Synapse в `main`; исходный коммит сохранён в истории. Найденные проблемы старого движка описаны в [SYNAPSE_REVIEW.md](SYNAPSE_REVIEW.md). Контур Gemini: [GEMINI.md](GEMINI.md).

Машинные результаты текущих прогонов: `test-results/api-tests.xml`, `test-results/browser-results.json`. Они исключены из Git; команды воспроизведения — в README.
