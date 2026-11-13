# Сборка установщиков «МедГрафик: Поликлиника»

Здесь собраны скрипты и конфигурации для сборки релизных установщиков под
разные операционные системы. Официальная сборка выполняется автоматически в
**GitHub Actions** (`.github/workflows/release.yml`) при публикации тега `v*`,
и готовая установка прикрепляется к релизу на GitHub.

## Что собирается

| Система | Артефакт | Чем собирается |
| --- | --- | --- |
| Windows 7 / 10 / 11 | `MedGrafik-Setup-<ver>.exe` | PyInstaller (onedir) + NSIS |
| Debian / Ubuntu | `med-roster_<ver>_amd64.deb` | `fpm` |
| Fedora / Simply Linux и др. | `med-roster-<ver>.x86_64.rpm` | `fpm` |
| Любой Linux | `med-roster-<ver>.tar.gz` | `tar` (переносимая сборка) |

## Windows

1. Установите Python **3.8** (для совместимости с Windows 7) и [NSIS](https://nsis.sourceforge.io/).
2. Запустите `build_windows.bat` (или `build_windows.bat py -3.8`).
3. Результат: `dist\MedGrafik\MedGrafik.exe` и
   `packaging\MedGrafik-Setup-<ver>.exe`.

Сборка выполняется в виртуальном окружении `build\venv` и не трогает системный
Python. Установщик ставится в профиль пользователя (`%LOCALAPPDATA%\Programs\MedGrafik`)
**без прав администратора** — это работает и на старых ПК.

## Linux

1. Установите `fpm` и `rpm` (см. `.github/workflows/release.yml`).
2. Запустите `packaging/build_linux.sh`.
3. Результат в `packaging/output/`.

Пакеты `.deb`/`.rpm` ставят приложение в `/opt/med-roster`, создают ярлык в меню
и команду `/usr/bin/med-roster`. При установке (postinst) создаётся виртуальное
окружение и ставятся зависимости — **нужен доступ в интернет**. Для офлайн-ПК
используйте переносимый `tar.gz` и установите зависимости вручную:
`python3 -m pip install -r requirements.txt`.

## Иконка

У Windows-установщика иконка по умолчанию (свой `.ico` можно указать в
`installer_windows.nsi`, параметр `MUI_ICON`). У Linux-пакета иконка —
`packaging/linux/med-roster.svg` (входит в `.deb`/`.rpm`).
