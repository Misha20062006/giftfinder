# Платформы и сборка GiftFinder 0.7

Один исходный код и поисковая логика для Windows, macOS и Linux. Каждая сборка создаётся на своей ОС: PyInstaller не превращает Windows EXE в приложение macOS или Linux.

| Пакет | Требования | Как запустить |
|---|---|---|
| Windows x64, ZIP / EXE | Windows 10 или 11 x64 | Распаковать ZIP и запустить `GiftFinder.exe` |
| macOS arm64, DMG | macOS 14+, Apple Silicon (M1 и новее) | Открыть DMG, перенести `GiftFinder.app` в Applications |
| macOS x64, DMG | macOS 14+, Intel | Открыть DMG, перенести `GiftFinder.app` в Applications |
| Linux x64, tar.gz | glibc 2.35+, например Ubuntu 22.04+ | Распаковать архив и запустить `start-giftfinder.sh` |
| Linux arm64, tar.gz | glibc 2.39+, например Ubuntu 24.04+ | Распаковать архив и запустить `start-giftfinder.sh` |

Для готовых пакетов Python не нужен. Linux-сборки используют системные OpenGL/EGL/X11-библиотеки. На Debian/Ubuntu при их отсутствии:

```sh
sudo apt-get install libegl1 libopengl0 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-xinerama0 libxcb-randr0 libxcb-shape0
```

Сборки без коммерческой цифровой подписи и нотариального заверения Apple. ОС может запросить подтверждение доверия приложению. Системные требования Linux ARM64 и macOS обусловлены текущими бинарными пакетами Qt, а не только Python.

## Профиль и обновления

На Windows сохранён прежний путь `%LOCALAPPDATA%\GiftFinder\GiftFinder`. На macOS используется `~/Library/Application Support/GiftFinder/GiftFinder`, на Linux — `$XDG_DATA_HOME/GiftFinder/GiftFinder` или `~/.local/share/GiftFinder/GiftFinder`. Папки приложения и профиля разделены: замена программы не удаляет настройки, избранное и сохранённые поиски. Автоматический перенос профиля между устройствами не выполняется.

## Сборка из исходников

Нужен Python 3.12, соответствующий архитектуре пакета. Из корня репозитория, в отдельном виртуальном окружении:

```sh
python -m pip install -r requirements-lock.txt
python tools/build_release.py
```

Скрипт создаёт пакет в `release-dist/`, запускает его вне экрана с отдельным профилем и записывает SHA-256. На macOS для DMG нужны стандартные `sips`, `iconutil` и `hdiutil`. Локальный запуск исходников: `python app.py`.

[GitHub Actions](../.github/workflows/desktop-build.yml) запускает тесты, нативную сборку и проверку упакованной программы на пяти системах. Внеэкранная проверка подтверждает запуск и основные функции интерфейса, но не заменяет ручную проверку на каждом компьютере, графическом драйвере или живой площадке.

## Android и iOS

Android пока не входит в готовый релиз. [Qt поддерживает Widgets на Android](https://doc.qt.io/qt-6/android.html), а [официальный инструмент PySide6](https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-android-deploy.html) собирает APK/AAB на Linux или macOS. Однако текущие широкие окна, фильтры и диалоги GiftFinder рассчитаны на компьютер. Для пригодной мобильной версии нужны отдельная адаптивная компоновка, сенсорная навигация, обработка Back и экранной клавиатуры, экспорт файлов и проверка на устройстве или эмуляторе. APK с неизменённым настольным интерфейсом здесь не выдаётся за мобильный порт.

Для iOS [официальный путь PySide6](https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-ios-deploy.html) требует macOS, полного Xcode и подписи для устройства; готовой iOS-сборки в релизе нет.
