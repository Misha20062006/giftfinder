<p align="center">
  <img src="giftfinder/icon.png" width="88" alt="GiftFinder">
</p>

<h1 align="center">GiftFinder</h1>

<p align="center"><strong>Найдите нужный подарок Telegram и сравните предложения шести площадок в одном окне.</strong></p>

<p align="center">Windows · macOS · Linux · Android preview · Open source · 28 языков</p>

| Платформа | Прямая загрузка | Как запустить |
|---|:---:|---|
| Windows 10/11 x64 · ZIP | [![Скачать Windows ZIP](docs/images/download.svg)](https://github.com/Misha20062006/giftfinder/releases/download/v0.7.1/GiftFinder-0.7.1-Windows-x64.zip) | Распаковать ZIP → `GiftFinder.exe` |
| macOS 14+ · Apple Silicon · DMG | [![Скачать macOS Apple Silicon](docs/images/download.svg)](https://github.com/Misha20062006/giftfinder/releases/download/v0.7.1/GiftFinder-0.7.1-macOS-arm64.dmg) | Перенести приложение в Applications |
| macOS 14+ · Intel · DMG | [![Скачать macOS Intel](docs/images/download.svg)](https://github.com/Misha20062006/giftfinder/releases/download/v0.7.1/GiftFinder-0.7.1-macOS-x64.dmg) | Перенести приложение в Applications |
| Linux x64 · glibc 2.35+ · tar.gz | [![Скачать Linux x64](docs/images/download.svg)](https://github.com/Misha20062006/giftfinder/releases/download/v0.7.1/GiftFinder-0.7.1-Linux-x64.tar.gz) | Распаковать → `start-giftfinder.sh` |
| Linux ARM64 · glibc 2.39+ · tar.gz | [![Скачать Linux ARM64](docs/images/download.svg)](https://github.com/Misha20062006/giftfinder/releases/download/v0.7.1/GiftFinder-0.7.1-Linux-arm64.tar.gz) | Распаковать → `start-giftfinder.sh` |
| Android 9+ · ARM64 · APK · preview | [![Скачать Android APK](docs/images/download.svg)](https://github.com/Misha20062006/giftfinder/releases/download/v0.7.1-android.1/GiftFinder-0.7.1-Android-arm64-v8a.apk) | Открыть APK и разрешить установку из выбранного источника |

<p align="center">
  <a href="docs/USER_GUIDE.md">Руководство</a>
  &nbsp;·&nbsp;
  <a href="docs/RELEASE_NOTES.md">Что нового</a>
</p>

![Каталог GiftFinder с тематическими подборками](docs/images/catalog.png)

## Что умеет

Выберите подарок из каталога или вставьте ссылку `t.me/nft/…`. Уточните нужное сочетание и сравните найденные цены без переключения между несколькими магазинами.

| Возможность | Что доступно |
|---|---|
| Точный поиск | Коллекция, модель, фон, узор, номер, площадка и диапазон цены; несколько вариантов одного свойства одновременно |
| Сравнение предложений | Сортировка по цене, номеру, свежести данных или редкости модели; переход к объявлению на площадке |
| Готовые подборки | 20 разделов: Пепе, золотые, серебристые, Star Wars, Гарри Поттер, Pokémon, Sailor Moon, Doge, космос, Minecraft и другие |
| Монохромки | Модели и фоны близкого цвета; выбор одного или нескольких из 13 цветов |
| Удобные цены | GRAM, Stars и приблизительный пересчёт в рубли, доллары, евро и другие валюты с источником и датой курса |
| Быстрый повторный поиск | Избранное, сохранённые фильтры и локальный кеш предложений |
| Выгрузка и обновление | Экспорт результатов в CSV, обновление по F5 и автоматическая догрузка страниц Fragment и Portals |

В комплектном каталоге на **24 октября 2026 года**: 123 коллекции, 7 806 моделей и 80 фонов. В версии 0.7.1 добавлены девять визуально проверенных подборок — 110 моделей; подборка Пепе включает 32 модели за пределами отдельно доступной коллекции Plush Pepe. Каталог обновляется в фоне. Тематические подборки и монохромки — наша группировка, а не официальный атрибут Telegram.

## Какие площадки и откуда данные

GiftFinder сам разбирает страницы Fragment и получает данные Portals. Для остальных площадок используется посредник — внешний агрегатор **[browse.tg](https://browse.tg/)**.

| Площадка | Как получаем предложения |
|---|---|
| [Fragment](https://fragment.com/gifts) | Напрямую: парсинг публичных страниц и догрузка поиска |
| [Portals](https://portal-market.com/) | Напрямую: публичный API |
| Telegram, Getgems, MRKT, Tonnel | Через индекс browse.tg; отдельных прямых подключений нет |

Каталог и изображения — [Gift Changes / changes.tg](https://t.me/GiftChangesAPI). Курсы — ExchangeRate-API и CoinGecko; ориентир стоимости Stars — Fragment. Отдельного прямого подключения к Gift Satellite нет.

## Насколько актуальны цены

- При поиске сначала видны сохранённые результаты, затем приходят обновления из сети. В приложении указаны источник, время данных, ошибки и неполная выдача.
- Прямые данные Fragment и Portals получаются во время поиска. Индекс browse.tg и локальный кеш могут отставать; фиксированный интервал обновления всех площадок не гарантируется.
- Полный охват рынка и самая низкая цена среди всех существующих объявлений не гарантируются. Завершение шкалы поиска означает завершение проверок, а не просмотр всего рынка.
- Пересчёт валют справочный, комиссии площадок автоматически не добавляются. Перед покупкой проверьте наличие подарка и итоговую сумму в самом магазине.

**GiftFinder ищет и сравнивает предложения.** Вход в Telegram, доступ к вашей сессии и подключение кошелька не требуются; покупки приложение не совершает.

## Как начать

1. Нажмите **«Скачать»** напротив своей системы в таблице выше.
2. Выберите коллекцию, подборку или нужные фильтры и нажмите **«Показать»**.
3. Сравните цены и откройте подходящее предложение на площадке.

Python для готовых сборок не нужен. Настольные пакеты без коммерческой подписи; Android APK подписан постоянным ключом проекта. При обновлении настройки, избранное и сохранённые поиски остаются в пользовательском профиле. Android получил отдельный сенсорный интерфейс; это предварительная версия, проверенная в эмуляторе, пока без проверки на физическом ARM64-телефоне и живого поиска по всем площадкам. [Подробности запуска, системные требования и статус iOS](docs/PLATFORMS.md).

## Открытый код — используйте свободно

GiftFinder — **open source**. Собственный код проекта доступен по [Unlicense](UNLICENSE): используйте, копируйте, изменяйте, распространяйте и включайте в коммерческие проекты — бесплатно и без обязательного указания автора.

Есть идея, нашли ошибку или хотите добавить площадку? [Предлагайте улучшения в Issues](https://github.com/Misha20062006/giftfinder/issues) или присылайте pull request — вклад в развитие приветствуется.

Сторонние библиотеки, данные и изображения сохраняют свои лицензии и условия использования: см. [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt).

<details>
<summary><strong>Для разработчиков: запуск, проверка и сборка</strong></summary>

Python 3.12 · PySide6 / Qt Widgets · Requests · Beautiful Soup · SQLite. Без встроенного Chromium, WebEngine и WebView.

PowerShell, из корня репозитория:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe app.py
```

Проверки используют отдельную папку данных и внеэкранный интерфейс:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:GIFT_FINDER_DATA_DIR = Join-Path $PWD '.qa\profile'
.\.venv\Scripts\python.exe -m pytest tests -q --basetemp .test-work
```

Нативная сборка, проверка без видимого окна и упаковка для текущей ОС:

```powershell
.\.venv\Scripts\python.exe tools/build_release.py
```

Подробнее: [как устроен поиск](SEARCH_TECHNICAL.txt), [руководство](docs/USER_GUIDE.md). Скриншот получен вне экрана из версии 0.7.1. Условия использования компонентов: [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt) и [third-party/](third-party/).

</details>
