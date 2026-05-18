# YandexGPT CLI

Терминальный coding agent для моделей YandexGPT и Alice AI. CLI использует нативный цикл Yandex `toolCallList` / `toolResultList`, поэтому модель вызывает инструменты через API, а не печатает псевдо-tool-call в чат.

## 1. Токены

Укажите данные Yandex Cloud в файле `.env` в корне проекта:

```env
YANDEX_CLOUD_FOLDER=your_yandex_cloud_folder_id
YANDEX_IAM_TOKEN=your_yandex_iam_token
```

Кавычки использовать необязательно, но такой вариант тоже поддерживается:

```env
YANDEX_CLOUD_FOLDER="your_yandex_cloud_folder_id"
YANDEX_IAM_TOKEN="your_yandex_iam_token"
```

Файл `.env` добавлен в `.gitignore`. Не рекомендуется вставлять токены в промпты, скриншоты и публичные чаты.

Дополнительные переменные:

```env
YANDEX_MODEL_URI=gpt://your_yandex_cloud_folder_id/aliceai-llm/latest
YANDEXGPT_HISTORY=~/.yandexgpt/history
```

## 2. Установка команды

Из папки проекта:

```bash
python3 -m pip install -e . --no-deps
```

После этого команда доступна из любой папки:

```bash
yandexgpt
```

Если установка не требуется, можно запускать CLI напрямую:

```bash
./bin/yandexgpt
```

## 3. Запуск

Откройте интерактивный интерфейс:

```bash
yandexgpt
```

Выполните один промпт сразу:

```bash
yandexgpt "создай файл hello.txt с текстом: привет" --yes
```

Запустите CLI для конкретной рабочей папки:

```bash
yandexgpt --workspace /path/to/project
```

## 4. Команды внутри интерфейса

```text
?                         показать быстрые команды
/help                     показать команды
/env                      показать статус переменных окружения
/model                    открыть выбор модели
/forget                   очистить контекст текущего диалога
/model alice              выбрать Alice AI
/model yandexgpt-5-lite   выбрать YandexGPT 5 Lite
/model yandexgpt-5-pro    выбрать YandexGPT 5 Pro
/model yandexgpt-5.1      выбрать YandexGPT 5.1
/history                  показать путь к истории
/clear                    перерисовать экран
/quit                     выйти
```

Список моделей:

```text
1. yandexgpt-5-lite  -> gpt://<folder>/yandexgpt-5-lite/latest
2. alice             -> gpt://<folder>/aliceai-llm/latest
3. yandexgpt-5-pro   -> gpt://<folder>/yandexgpt-5-pro/latest
4. yandexgpt-5.1     -> gpt://<folder>/yandexgpt-5.1/latest
```

Модель по умолчанию:

```text
gpt://<folder>/aliceai-llm/latest
```

## 5. Полезные флаги

```bash
yandexgpt --dry-run "создай index.html"
yandexgpt --allow-shell "запусти тесты"
yandexgpt --debug-agent "проверь tool calls"
yandexgpt --plain
```

Назначение флагов:

- `--dry-run` показывает, какие файлы были бы изменены, но ничего не записывает.
- `--allow-shell` включает shell-инструмент. По умолчанию он выключен.
- `--debug-agent` показывает низкоуровневые логи agent loop.
- `--plain` отключает ANSI-стили и цвета.

## 6. Проверка

Из любой тестовой папки:

```bash
yandexgpt "создай файл test-yandexcli.txt с текстом: YandexCLI работает" --yes
cat test-yandexcli.txt
```

Ожидаемый текст в файле:

```text
YandexCLI работает
```

Локальные тесты проекта:

```bash
python3 -B -m unittest discover -s tests -v
```

## 7. Сертификаты macOS

Если появляется ошибка `CERTIFICATE_VERIFY_FAILED`, выполните:

```bash
"/Applications/Python 3.14/Install Certificates.command"
```

После этого повторите запуск `yandexgpt`. Не отключайте SSL-проверку.

## 8. Безопасность

- Инструменты могут читать и писать только внутри выбранного workspace.
- Запись файлов требует подтверждения, если не передан `--yes`.
- Shell-команды выключены, пока не передан `--allow-shell`.
- История промптов хранится обычным текстом в `~/.yandexgpt/history`.
- Заметки по безопасности ведутся в `vulnerabilities.md`.
