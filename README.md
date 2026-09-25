<div align="center">

<h1>SKAZ</h1>

<p><strong>Озвучивайте выделенный текст или всю страницу русским голосом прямо в браузере.</strong><br>SKAZ работает на вашем компьютере. Для локальных моделей Silero текст не покидает компьютер.</p>

<p><a href="#установка-расширения">Установка расширения</a> · <a href="#установка">Установка</a> · <a href="#возможности">Возможности</a> · <a href="#настройки">Настройки</a> · <a href="#лицензии">Лицензии</a></p>

[![Скачать для Windows](https://img.shields.io/badge/Windows-7B61FF?style=flat-square&logo=data:image/svg%2Bxml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZmlsbD0iI2ZmZiIgZD0iTTEgMyAxMSAxLjV2MTBIMXptMTEtMS42TDIzIDB2MTEuNUgxMnpNMSAxMi41aDEwdjEwTDEgMjF6bTExIDBoMTFWMjRsLTExLTEuNXoiLz48L3N2Zz4=)](https://github.com/Qwill552/SKAZ/releases/latest/download/skaz-windows.zip) [![Скачать для Linux](https://img.shields.io/badge/Linux-7B61FF?style=flat-square&logo=linux&logoColor=white)](https://github.com/Qwill552/SKAZ/releases/latest/download/skaz-linux.tar.gz) [![Скачать для macOS](https://img.shields.io/badge/macOS-7B61FF?style=flat-square&logo=apple&logoColor=white)](https://github.com/Qwill552/SKAZ/releases/latest/download/skaz-macos.tar.gz)

<p><strong>ИСПОЛЬЗУЕТ МОДЕЛИ: Silero-v5, ЯНДЕКС, Edge-TTS.</strong></p>

https://github.com/user-attachments/assets/1f7c2d00-59da-403b-9547-a8f0513b4a0a

</div>

## Примеры голосов

### Яндекс

| TTS Name | Model | Examples |
| --- | --- | --- |
| Oksana | `oksana.gpu` | [Слушать](https://raw.githubusercontent.com/Alkohole/machine-reading-text/main/examples/Oksana.wav) |
| Jane | `jane.gpu` | [Слушать](https://raw.githubusercontent.com/Alkohole/machine-reading-text/main/examples/Jane.wav) |
| Omazh | `omazh.gpu` | [Слушать](https://raw.githubusercontent.com/Alkohole/machine-reading-text/main/examples/Omazh.wav) |
| Nastya | `nastya.gpu` | [Слушать](https://raw.githubusercontent.com/Alkohole/machine-reading-text/main/examples/Nastya.wav) |
| Sasha | `sasha.gpu` | [Слушать](https://raw.githubusercontent.com/Alkohole/machine-reading-text/main/examples/Sasha.wav) |
| Tatyana | `tatyana_abramova.gpu` | [Слушать](https://raw.githubusercontent.com/Alkohole/machine-reading-text/main/examples/Tatyana_Abramova.wav) |
| Ermil | `ermil.gpu` | [Слушать](https://raw.githubusercontent.com/Alkohole/machine-reading-text/main/examples/Ermil.wav) |
| Zahar | `zahar.gpu` | [Слушать](https://raw.githubusercontent.com/Alkohole/machine-reading-text/main/examples/Zahar.wav) |
| Kolya | `kolya.gpu` | [Слушать](https://raw.githubusercontent.com/Alkohole/machine-reading-text/main/examples/Kolya.wav) |
| Kostya | `kostya.gpu` | [Слушать](https://raw.githubusercontent.com/Alkohole/machine-reading-text/main/examples/Kostya.wav) |
| Anton | `anton_samokhvalov.gpu` | [Слушать](https://raw.githubusercontent.com/Alkohole/machine-reading-text/main/examples/Anton_Samokhvalov.wav) |

Примеры Яндекса: [machine-reading-text](https://github.com/Alkohole/machine-reading-text/tree/main/examples).

### Edge TTS

| TTS Name | Model | Examples |
| --- | --- | --- |
| Svetlana | `ru-RU-SvetlanaNeural` | [Слушать](https://huggingface.co/spaces/VItaliaN77/rus-edge-tts-webui/resolve/main/example/ru-RU-SvetlanaNeural.wav) |
| Dmitry | `ru-RU-DmitryNeural` | [Слушать](https://huggingface.co/spaces/VItaliaN77/rus-edge-tts-webui/resolve/main/example/ru-RU-DmitryNeural.wav) |

Примеры Edge TTS: [rus-edge-tts-webui](https://huggingface.co/spaces/VItaliaN77/rus-edge-tts-webui/tree/main/example).

## Установка расширения

Установите [Tampermonkey](https://www.tampermonkey.net/) в браузере. В Opera установите [Violentmonkey](https://violentmonkey.github.io/).

> [!CAUTION]
> Перед созданием нового сообщения о проблеме проверьте [существующие Issues](https://github.com/Qwill552/SKAZ/issues).

> [!WARNING]
> Пользователям Tampermonkey 5.2+ в браузерах на Chromium (Chrome, Edge, Brave, Vivaldi и других) нужно:
> 1. Открыть страницу расширений (`chrome://extensions`, в Edge — `edge://extensions`) и включить «Режим разработчика».
> 2. На Chromium 138+ открыть сведения о Tampermonkey и включить «Разрешить пользовательские скрипты».
>
> В Opera установите [Violentmonkey](https://violentmonkey.github.io/) вместо Tampermonkey и разрешите расширению доступ к результатам на странице поиска в его настройках.

## Установка

1. Скачайте архив для своей системы, распакуйте его и выполните раздел «УСТАНОВКА» из вложенного `README.txt`.
2. На странице настройки SKAZ установите предложенный юзерскрипт и нажмите «Связать с браузером». На любом сайте выделите текст и нажмите **Alt+T**.

Для первой установки нужны интернет и около **2 ГБ свободного места**: установщик скачивает Python, зависимости и выбранные модели. В установщике можно ввести несколько номеров через запятую для моделей Silero, Edge TTS и Яндекса. Системный Python ставить не требуется. Локальные модели после установки работают без интернета; сетевые голоса требуют интернет при чтении.

### ВАЖНО!!! Предупреждение Windows SmartScreen

Windows может предупредить о неподписанном приложении: «Система Windows защитила ваш компьютер». Для продолжения откройте «Подробнее» и выберите «Выполнить в любом случае», если архив скачан из [релиза SKAZ](https://github.com/Qwill552/SKAZ/releases/latest) и его SHA-256 совпадает с приложенной суммой. Отключать защиту Windows не нужно.

## Возможности

- Чтение выделения или всей страницы с паузой и переходом между предложениями.
- Подсветка текущего предложения и слова, прокрутка вслед за чтением.
- Отдельный список голосов для каждой установленной модели, выбор скорости и собственной горячей клавиши.
- Словарь для имён и терминов: ударение знаком `+`, пауза знаком `-`.
- Локальная работа через `127.0.0.1` с моделями Silero; необязательные сетевые голоса Edge TTS и Яндекса.
- Проверка обновлений при запуске; сервер обновляется после подтверждения, юзерскрипт обновляет Tampermonkey.

## Настройки

<details>
<summary>Как сменить голос и скорость</summary>

Откройте настройки SKAZ через значок шестерёнки на панели чтения. У каждой установленной модели свой выпадающий список голосов. Выберите модель переключателем и её голос в списке, затем скорость. На Windows настройки сервера доступны по правому клику на значке SKAZ возле часов.

</details>

<details>
<summary>Как добавить слово в словарь</summary>

В настройках SKAZ добавьте пару «слово на странице → произношение», например `Цунаде → Цун+адэ`, затем нажмите «Сохранить словарь». Словарь хранится локально и сохраняется при обновлении.

Для неоднозначных `е/ё` задавайте в словаре фразу с контекстом. Запись для одного слова `все → вс+е` затронет и предложения, где подразумевается «всё».

</details>

<details>
<summary>Как изменить горячую клавишу</summary>

Откройте меню Tampermonkey для SKAZ, выберите «Сменить горячую клавишу» и нажмите новое сочетание. По умолчанию используется Alt+T.

</details>

<details>
<summary>Если звук не появился</summary>

Проверьте, что сервер запущен, браузер связан с ним на странице `/setup`, а Tampermonkey разрешён на открытом сайте. В настройках SKAZ нажмите «Проверить связь». Для сообщения об ошибке используйте [шаблон issue](https://github.com/Qwill552/SKAZ/issues/new/choose), указав сайт, версии и шаги повторения. Не публикуйте ключ из `config.json`.

</details>

## Как устроено

Юзерскрипт берёт текст из живой страницы и отправляет его через `GM_xmlhttpRequest` серверу на `127.0.0.1`. Локальные модели Silero синтезируют WAV на компьютере. При выборе Edge TTS сервер отправляет текст Microsoft и получает MP3 с таймингами слов. При выборе Яндекса сервер использует механизм озвучивания Яндекс Переводчика, аналогичный [machine-reading-text](https://github.com/Alkohole/machine-reading-text), и получает Ogg Opus. Аккаунт Yandex Cloud и платный ключ не нужны. Оба сетевых способа неофициальны и могут перестать работать; при ошибке чтение продолжится голосом Silero. Текст каждого нового фрагмента отправляется выбранному сервису. Для Яндекса пословная подсветка рассчитывается приблизительно по длительности звука.

## Лицензии

Код SKAZ распространяется по [MIT](LICENSE). Эта лицензия **не распространяется на модели Silero**, которые скачиваются отдельно при установке. Модель `v5_ru` по умолчанию опубликована авторами под [CC BY-NC-SA 4.0](https://github.com/snakers4/silero-models/blob/master/LICENSE); альтернативная `v5_cis_base` — под [MIT](https://github.com/snakers4/silero-models/blob/master/LICENSE_CIS). Подробности в [NOTICE.md](NOTICE.md).
