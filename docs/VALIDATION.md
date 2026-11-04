# Проверка UZEX Observatory

Проверена текущая локальная версия сайта без ИИ. Браузерный прогон: 04.11.2026 22:03 по Ташкенту. Публичный хостинг и восстановление среды в новой задаче не проверялись.

## Результаты

- Production-сборка TypeScript + Vite: успешно.
- Проверки расчётов, API и нормализации: **27 пройдено, 0 ошибок, 0 пропущено**. В том числе четыре случая различения сорта товара и класса качества.
- Сценарии реального Chromium: **13 пройдено**. Проверены десктоп, телефоны 390/320 px, RU/UZ, карта 3D/2D и восстановление карты в браузере без WebGL.
- Полная установка по фиксированным зависимостям `bash scripts/install.sh` выполнена повторно; импорт использует готовую базу при совпадении контрольных сумм.
- `bash scripts/start.sh` выполнен; реальными HTTP-запросами проверены здоровье API, все 500 000 сделок, выборка 2025 года и production HTML.
- Импорт финальной схемы 3 выполнен; последующий повторный импорт сохранил базу. Итоговая сумма совпала с независимым расчётом CSV.
- Контрольные суммы всех девяти CSV сохранены; исходные данные не изменены.
- Форматирование исходников проверено Prettier.

## Что проверялось в браузере

- Desktop initial data, 3D scene and layout
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

## Просмотр

- [Полная десктопная версия](screenshots/desktop.png)
- [Мобильная версия](screenshots/mobile.png)
- [Мобильная версия UZ](screenshots/mobile-uz.png)
- [Карточка сделки](screenshots/deal.png)
- [Отчёт с источником расчёта](screenshots/report.png)

Скриншоты получены из работающего приложения. Они не являются макетами с подставленными данными.

## Зафиксированные границы

ИИ и свободные вопросы на естественном языке отложены пользователем до окончания сайта. Текущий поиск работает по реквизитам и названиям, отчёты выбираются явно. Публичная ссылка и отправка конкурсной формы пока отсутствуют.

В конфигурации облачной среды сохранены `install_script` и `start_skill`. Сохранение черновика не означает публикацию снимка среды и не является размещением публичного сайта.

Машинные результаты текущих прогонов: `test-results/api-tests.xml`, `test-results/browser-results.json`. Эти временные файлы исключены из Git; сценарии воспроизводятся командами из README.
