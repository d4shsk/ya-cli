# YandexGPT CLI

Терминальный coding agent для моделей YandexGPT и Alice AI. CLI использует нативный цикл Yandex `toolCallList` / `toolResultList`, поэтому модель вызывает инструменты через API, а не печатает псевдо-tool-call в чат.

## 0. Требования к платформе

> **Только Linux и macOS.** Нативный Windows не поддерживается.
>
> Интерактивный ввод использует POSIX-модули стандартной библиотеки (`readline`, `termios`, `tty`, `select` по файловым дескрипторам), которых нет в Windows-сборке Python. На Windows запуск падает с `ModuleNotFoundError: No module named 'readline'` (а после него — `termios`), и обойти это установкой пакетов нельзя.
>
> Пользователям Windows: установите [WSL](https://learn.microsoft.com/windows/wsl/install) (`wsl --install`) и выполняйте все шаги ниже внутри Linux-окружения.

### Быстрый старт через WSL (Windows)

1. В PowerShell установите WSL с Ubuntu (нужны права администратора) и перезагрузитесь, если попросит:

   ```powershell
   wsl --install -d Ubuntu
   ```

2. Запустите Ubuntu (из меню «Пуск» или командой `wsl`) и установите Python с pip:

   ```bash
   sudo apt update
   sudo apt install -y python3 python3-pip python3-venv git
   ```

3. Перейдите в проект. Папка с Windows доступна внутри WSL через `/mnt/c/...`:

   ```bash
   cd /mnt/c/Users/<ваш-пользователь>/path/to/ya-cli
   ```

   Либо склонируйте репозиторий в домашнюю папку WSL (так быстрее работает ФС):

   ```bash
   git clone https://github.com/d4shsk/ya-cli.git ~/ya-cli
   cd ~/ya-cli
   ```

4. Дальше выполняйте обычные шаги: [конфиг](#1-конфиг) и [установку](#2-установка-команды). Команды `python3`, `pip`, `yandexgpt` внутри WSL работают как описано ниже.

> Все команды из разделов ниже выполняются внутри WSL (Ubuntu), а не в PowerShell.

## 1. Конфиг

Ключи, модели и провайдеры задаются в `yacli.jsonc`. Можно начать с шаблона:

```bash
cp yacli.example.jsonc yacli.jsonc
chmod 600 yacli.jsonc
```

Минимальный Yandex-конфиг:

```jsonc
{
  "model": "yandex/alice",
  "provider": {
    "yandex": {
      "name": "Yandex Foundation Models",
      "npm": "yandex",
      "options": {
        "baseURL": "https://llm.api.cloud.yandex.net/foundationModels/v1",
        "folderId": "your_yandex_cloud_folder_id",
        "iamToken": "your_yandex_iam_token",
        "apiKey": ""
      },
      "models": {
        "alice": { "name": "Alice AI LLM", "modelUri": "gpt://{folderId}/aliceai-llm/latest" },
        "gemma-3-27b-it": { "name": "Gemma 3 27B IT", "modelUri": "gpt://{folderId}/gemma-3-27b-it", "attachment": true }
      }
    }
  },
  "permission": {
    "bash": "allow"
  }
}
```

Заполните `folderId` и один из ключей: `iamToken` или `apiKey`. `model` указывает модель по схеме `provider/model`; для Yandex можно также передать полный `gpt://...` через `--model-uri`.

CLI ищет конфиг в таком порядке: путь из `--config`, путь из `YACLI_CONFIG`, `./yacli.jsonc`, проектный `yacli.jsonc`, `~/.config/yandexgpt/yacli.jsonc`. Файл `yacli.jsonc` добавлен в `.gitignore`, потому что внутри могут быть ключи. Если файл доступен group/others, CLI предупредит и предложит `chmod 600 yacli.jsonc`.

Дополнительные переменные окружения остались только для локального состояния:

- `YANDEXGPT_HISTORY=~/.yandexgpt/history`
- `YANDEXGPT_SESSIONS=~/.yandexgpt/sessions`

### OpenAI-compatible и Anthropic

Провайдеры в стиле opencode добавляются в тот же объект `provider`. Поддерживаются `@ai-sdk/openai-compatible` и `@ai-sdk/anthropic`:

```jsonc
{
  "model": "openai/gpt-5.5",
  "provider": {
    "provider": {
      "name": "provider",
      "npm": "@ai-sdk/openai-compatible",
      "options": {
        "baseURL": "https://provider/v1",
        "apiKey": "key"
      },
      "models": {
        "gpt-5.5": { "name": "GPT 5.5", "attachment": true, "modalities": { "input": ["text", "image"], "output": ["text"] } }
      }
    },
    "provider-claude": {
      "name": "provider - Claude",
      "npm": "@ai-sdk/anthropic",
      "options": {
        "baseURL": "https://provider/v1",
        "apiKey": "key"
      },
      "models": {
        "claude-sonnet-4-6": { "name": "Claude Sonnet 4.6", "attachment": true, "modalities": { "input": ["text", "image"], "output": ["text"] } }
      }
    }
  }
}
```

Для OpenAI-compatible CLI вызывает `{baseURL}/chat/completions`. Для Anthropic-compatible CLI вызывает `{baseURL}/messages`.

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
/config                   показать статус yacli.jsonc
/model                    открыть выбор модели
/plan                     включить режим План
/edit                     включить режим Код
/mode                     переключить План/Код
/forget                   очистить контекст текущего диалога
/model yandex/alice       выбрать Alice AI
/model provider/gpt-5.5   выбрать OpenAI-compatible модель
/model provider-claude/claude-sonnet-4-6
/history                  показать путь к истории
/clear                    перерисовать экран
/quit                     выйти
```

`/env` оставлен как алиас `/config`.

Пример списка моделей:

```text
1. yandex/alice - Alice AI LLM
2. yandex/yandexgpt-5-lite - YandexGPT 5 Lite
3. yandex/gemma-3-27b-it - Gemma 3 27B IT
4. provider/gpt-5.5 - GPT 5.5
```

Модель по умолчанию:

```text
yandex/alice
```

## 5. Полезные флаги

```bash
yandexgpt --dry-run "создай index.html"
yandexgpt --allow-shell "запусти тесты"
yandexgpt --allow-shell --yes-shell "запусти тесты"
yandexgpt --debug-agent "проверь tool calls"
yandexgpt --plain
yandexgpt --session 1
yandexgpt --model provider/gpt-5.5
yandexgpt --config ~/.config/yandexgpt/yacli.jsonc
```

Назначение флагов:

- `--dry-run` показывает, какие файлы были бы изменены, но ничего не записывает.
- `--yes` подтверждает запись файлов.
- `--allow-shell` включает shell-инструмент. По умолчанию он выключен.
- `--yes-shell` подтверждает shell-команды, если включен `--allow-shell`; обычный `--yes` shell не подтверждает.
- `--debug-agent` показывает низкоуровневые логи agent loop.
- `--plain` отключает ANSI-стили и цвета.
- `--session N` продолжает сохраненный интерактивный чат с номером `N`.
- `--model provider/model` выбирает модель из `yacli.jsonc`.
- `--model-uri gpt://...` оставлен как совместимость для Yandex.
- `--config path/to/yacli.jsonc` выбирает файл конфига явно.

## 6. Как агент работает

Перед первым ответом агент собирает контекст workspace: список файлов, статус git-репозитория, выдержки из ключевых файлов (`AGENTS.md`, `README.md`, `pyproject.toml`, `.gitignore`, `vulnerabilities.md`) и подсказки по словам из запроса. Это помогает модели выбирать релевантные файлы без чтения всего проекта.

В интерактивном режиме стартовый экран показывает логотип, служебную информацию, модель и многострочное чёрное поле ввода по центру. `Tab` переключает режимы `План` и `Код`, подсказки `Tab`, `@`, `?` и `/model` находятся в нижней строке поля, `/model` открывает выбор модели отдельным центрированным окном. В режиме План агент может читать и искать по проекту, но инструменты записи, `edit_file` и shell-команды не передаются модели и дополнительно блокируются при выполнении. В режиме Код агент может вносить изменения с обычными подтверждениями. После первого сообщения стартовый экран скрывается, и дальше видна только переписка.

Для точечных изменений агенту доступен `edit_file`: он заменяет точный фрагмент текста в существующем файле и по умолчанию требует, чтобы совпадение было единственным. `write_file` остается для создания новых файлов или осознанной полной перезаписи.

Можно ссылаться на файлы прямо в промпте через `@`:

```bash
yandexgpt "объясни @README.md"
yandexgpt "что на @screen.png?" --model yandex/gemma-3-27b-it
yandexgpt 'сравни @"first screenshot.png" @"second screenshot.png"'
```

В интерактивном вводе после `@` показываются подсказки файлов из workspace. Стрелки вверх/вниз выбирают вариант, `Enter` или стрелка вправо вставляет выбранную ссылку.

Текстовые файлы до 200 KB добавляются в prompt как контекст. Изображения `jpg`, `jpeg`, `png`, `webp`, `gif` до 20 MB кодируются в Base64 и отправляются в vision-сообщении. Для vision используйте мультимодальную модель, например `gemma-3-27b-it`.

Интерактивные чаты сохраняются как сессии с простыми числовыми id. При выходе CLI печатает команду продолжения:

```text
Сессия 3 сохранена. Продолжить: yandexgpt --workspace /path/to/project --session 3
```

Сессии хранятся в `~/.yandexgpt/sessions` или в пути из `YANDEXGPT_SESSIONS`. Команда `/session` показывает текущий номер и команду возобновления.

## 7. Проверка

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

Опциональные dev-проверки:

```bash
python3 -m pip install -e '.[dev]'
python3 -m ruff check .
python3 -m mypy yandexcli
```

## 8. Сертификаты macOS

Если появляется ошибка `CERTIFICATE_VERIFY_FAILED`, выполните:

```bash
"/Applications/Python 3.14/Install Certificates.command"
```

После этого повторите запуск `yandexgpt`. Не отключайте SSL-проверку.

## 9. Безопасность

- Инструменты могут читать и писать только внутри выбранного workspace.
- Режим План ограничивает инструменты чтением и поиском; изменения файлов и shell-команды доступны только в режиме Код.
- `@file`-ссылки читают локальные файлы из workspace. Текстовые файлы добавляются в prompt, изображения отправляются в модель как Base64.
- Запись файлов требует подтверждения, если не передан `--yes`.
- Shell-команды выключены, пока не передан `--allow-shell`; автоподтверждение shell требует отдельный `--yes-shell`.
- `permission.bash: "allow"` в `yacli.jsonc` включает shell-инструмент, но не отменяет подтверждение команд без `--yes-shell`.
- Инструмент чтения файлов отклоняет бинарные и слишком большие файлы, чтобы случайно не отправлять их в модель.
- Временные ошибки Yandex API (`429`, `5xx`, сетевые сбои) повторяются с backoff.
- История промптов хранится обычным текстом в `~/.yandexgpt/history`.
- Сессии чата хранятся обычным JSON в `~/.yandexgpt/sessions`.
- `yacli.jsonc` может содержать API-ключи; держите права `600` и не добавляйте файл в публичные репозитории.
- Заметки по безопасности ведутся в `vulnerabilities.md`.
