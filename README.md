<h1 align="center"> CommaMatrix</h1>
<p align="center">
  <img src="https://raw.githubusercontent.com/matrixd0t/commamatrix/master/assets/logo.png" alt="CommaMatrix" width="512">
</p>
<p align="center">
  <strong>СКРАФТИ СВОЕГО ИИ-АГЕНТА</strong>
</p>

<p align="center">
  <strong>Русский | <a href="https://github.com/matrixd0t/commamatrix/blob/master/assets/README.en.md">English</a></strong>
</p>

<p align="center">
  <a href="https://raw.githubusercontent.com/matrixd0t/commamatrix/master/installer/windows/install.ps1">Установщик</a>
  ·
  <a href="https://github.com/matrixd0t/commamatrix/blob/master/src/commamatrix/builtin/self_extension/guides/main.md">Документация</a>
  ·
  <a href="https://github.com/matrixd0t/commamatrix/tree/master/examples/">Примеры</a>
</p>


## Вы - пользователь с Windows?

Запустите минималистичного ИИ-агента, поставляемого с CommaMatrix, прямо сейчас (инструкция ниже). Это **абсолютно** бесплатно и **абсолютно** конфиденциально: между вами и ИИ стоит лишь интернет-провайдер.


### Способ 1. Скачать файл

Скачайте и запустите [`install.ps1`](https://raw.githubusercontent.com/matrixd0t/commamatrix/master/installer/windows/install.ps1). Скачанный файл откройте двойным кликом.

### Способ 2. Одна команда

1. Нажмите `Win + R`.
2. Введите `powershell` и нажмите Enter.
3. Вставьте команду:

```powershell
irm https://raw.githubusercontent.com/matrixd0t/commamatrix/master/installer/windows/install.ps1 | iex
```

4. Дождитесь установки Python и необходимых библиотек.
5. Выберите русский язык.
6. Выберите базовый режим установки.
7. Следуйте инструкциям по получению ключа доступа для провайдера по умолчанию. 
8. Не забудьте сохранить пароль. Вы сможете поменять имя или пароль через веб-интерфейс.
9. Приложение появится в области уведомлений, откуда можно будет открыть окно чата в браузере или завершить работу программы. Значок быстрого запуска появится на рабочем столе.


### Чем это отличается от ChatGPT?
Агент может сделать все, что вы можете сделать за компьютером. Например, обработать 20 фотографий в **вашем** Photoshop; собрать для вас сводку вечерних новостей через **ваш** браузер; или написать отчет, а затем сохранить его в формате Word и отправить с **вашей** почты. Не нужны ни промпты, ни плагины, ни иные формы интеграции: модель **сама по себе** достаточно умна для таких задач, а встроенные возможности CommaMatrix достаточно полны.

# Вы - разработчик?

*CommaMatrix для агента — как операционная система для пользователя.*

Если одна модель — это мозг, то CommaMatrix — это нервная система.

Библиотека позволяет соединять в согласованную систему любой набор компонентов: мозгов (llm-адаптеров), модулей речи и органов чувств (коннекторов), конечностей (инструментов), внутренних органов (компонентов жизненного цикла), инструкций, моделей "диалога" и конфигурационных полей, а также как внутренней, так и бизнес-логики (хуков).

CommaMatrix полностью модульна. Вы можете заменить любой класс библиотеки на свою реализацию, или добавить свою реализацию к существующим в `commamatrix/builtin`.

Все `builtin` — лишь модули, написанные на CommaMatrix, но идущие в комплексте с ней. Этого достаточно, чтобы понимать богатство его возможностей — и баланс этого с простотой фреймворка. В их число входят:

- Десять хуков в различных местах жизненного цикла, имеющих механизмы абсолютного и относительного "приоритета". Кстати, такой же механизм имеют и инструкции модели - влияет на их расположение в промпте относительно друг друга. **Вся** внутренняя логика CommaMatrix реализована через ее хуки.
- LLM HTTP адаптер. CommaMatrix понимает все, что говорит на `chat completions`, `openai requests` или `anthropic messages`, и вы можете добавить к этому свои кодеки, реализуя подкласс `ApiCodec`. Или реализуйте собственный `LLMAdapter`, например, для управления локальной моделью изнутри CommaMatrix.
- `CodeAct` - программируемые вызовы инструментов. Любая функция на Python с декоратором @tool — инструмент модели, а любой инструмент модели, независимо от источника (даже MCP) — асинхронная функция на Python. Вы можете добавлять свои источники инструментов, реализуя свой подкласс `ToolSource`, или переопределять компоненты, используемые `builtin`.
- Поддержка многопользовательского и мультидиалогового общения ("диалогом" для CommaMatrix считается любой уникальный объект, способный принимать, хранить и отдавать слушателю сообщения пользователей). Реализуйте подклассы `DialogOrigin` и `Connector`. #todo пример в examples: кроссплатформенный мессенджер с ИИ-модерацией
- HTTP-коннектор: общайтесь с моделью через окно чата в браузере сами и передавайте права доступа другим, генерируя одноразовые приглашения. Есть и API-эндпойнты.
- Планировщик заданий: создавайте heartbeat для агента или позвольте ему создавать их самостоятельно.
- SQL-хранилище данных: агент может выполнять поиск по диалогам, базе пользователей и любой иной информации из базы. SQLite и PostgreSQL поддерживаются "из коробки". Если вашему приложению нужно хранить структурированные данные, реализуйте подкласс `BaseTable`. Хотите ORM? Пожалуйста, реализуйте свой подкласс `Storage`.
- Веб-клиент на httpx2 и минималистичный веб-сервер на uvicorn + starlette, но вы можете — что? — правильно, использовать что-то иное, реализовав подкласс.
- Автоинжекция контекста в инструменты, инструкции, хуки через параметр `ctx` в стиле fastapi. Все контексты строго типизированы и содержат ссылку на инстанс агента.
- А еще поиск в интернете через `ddgs` (#todo: сделать поисковой бэкенд нормальным классом, чтобы вы могли подключить / реализовать собственный) и запись/чтение любого вида данных по HTTP / с диска / из произвольной реализации файлового хранилища (реализуйте подкласс `FileStorage`).
- Хотите что-то принципиально новое, не указанное в списке? Реализуйте подкласс `Service`, `AbstractService`, `Descriptor`, `Manager`, `Source` или любого из существующих подклассов; чтобы подключить любой свой компонент к жизненному циклу агента.


**Модель отвечает за интеллект. CommaMatrix отвечает за всё остальное.**

## Весь фреймворк - в контекстном окне

Исходник CommaMatrix помещается в контекстное окно даже моделей предыдущего поколения. **Менее 200k токенов** со всеми функциями "из коробки".

| Метрика           | Ядро, без `builtin` | С `builtin` |
|-------------------|--------------------:|------------:|
| Токенов           |             ~48 000 |    ~124 000 |
| Строк Python-кода |              ~6 000 |     ~16 000 |


## Технические подробности

CommaMatrix рассчитан на **Python 3.13+**, для установки рекомендуется использовать [`uv`](https://docs.astral.sh/uv/).

```bash
uv venv --python 3.13
uv add "commamatrix[all]"
```

Если делаете git clone:

```bash
uv sync --extra all
```

### Quickstart

Задайте конфигурацию провайдера. CommaMatrix также подхватит `.env`:

```bash
export OPENAI_API_KEY="your-api-key"
export LLM_API_BASE="https://api.openai.com"
```


Создайте `quickstart.py`:

```python
import asyncio
import os

from commamatrix import *
from commamatrix.builtin import llm_http_adapter

async def main() -> None:
    agent = Agent(name="my_lovely_assistant")
    await agent.add_extensions(
        commamatrix.builtin.default_instruction,  # добавляйте расширения так
        llm_http_adapter,  # или так
        "commamatrix.builtin.http_connector",  # или по именам модулей
    )

    # полная изоляция состояний для каждого агента

    agent.config.set(llm_api_base, os.environ["LLM_API_BASE"])  # изменяйте настройки в любой момент
    agent.config.set(openai_api_key, os.environ["OPENAI_API_KEY"])  # можно передавать lambda-предикаты в значения
    agent.config.set(agentic_model, "deepseek-v4-flash")
    # для названия модели: первое вхождение подстроки будет распознано
    # например, 'deepseek/deepseek-v4-flash'
    # в приоритете наиболее дешевый провайдер

    async with agent:  # в стиле asynccontextmanager, но можно и await agent.start() / agent.stop()
        print(f"CommaMatrix agent is running at {agent.http_server.base_url}")
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
```

Запустите:

```bash
uv run quickstart.py
```

`async with agent` гарантирует корректную остановку агента при выходе из блока, включая
отмену по `Ctrl+C`. Если приложению нечего делать между запуском и остановкой,
используйте:

```python
await agent.run_forever()
```

### HTTP UI и HTTP-коннектор

Откройте `http://127.0.0.1:8338/commamatrix`. При первом запуске HTTP-коннектор
создаёт администратора и возвращает сгенерированный пароль.

По умолчанию хост задан как `127.0.0.1`. Если вы поднимаете приложение на сервере, переключите `http_host` на `0.0.0.0`, чтобы к вашему агенту можно было подключиться извне. Добавляйте или удаляйте пользователей через страницу в браузере, чтобы работать над проектами совместно.

#### Свой интерфейс / доступ через API

Health-эндпойнт не требует авторизации:

```bash
curl http://127.0.0.1:8338/commamatrix/health
```

Для API-запросов сначала получите токен:

```bash
curl -X POST http://127.0.0.1:8338/commamatrix/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"YOUR_ADMIN_PASSWORD"}'
```

Затем отправьте сообщение:

```bash
curl -X POST http://127.0.0.1:8338/commamatrix/api/messages \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content":"Explain what CommaMatrix does in one sentence."}'
```

Для SSE-потока добавьте к запросу `?stream=1` и читайте события из `/commamatrix/api/events`.

### Взаимодействие с LLM

LLM HTTP adapter по умолчанию требует:

| Переменная          | Назначение                                         |
|---------------------|----------------------------------------------------|
| `OPENAI_API_KEY`    | Токен для OpenAI-compatible и OpenAI Responses API |
| `ANTHROPIC_API_KEY` | Токен для Anthropic Messages API                   |
| `LLM_API_BASE`      | Base URL провайдера                                |

В зависимости от провайдера задайте `llm_api_protocol` как `chat_completions` (по умолчанию),
`responses` или `anthropic_messages`.

Отправка локальных файлов внешней LLM требует публичного IP-адреса: настройте `http_external_url`, иначе функция будет недоступна.

### Конфигурация

Вы можете также задавать поля конфигурации при создании агента, передавая словарь `config` как аргумент.

Вызов функции `agent.config_fields_markdown()` выведет все конфигурационные поля: тип,
описание и значение по умолчанию. Вызовите метод, не запуская агента, чтобы посмотреть, какие настройки доступны с текущим набором расширений:

```python
from commamatrix import *

async def main() -> None:
    agent = Agent(name="my_lovely_assistant", config={
      agentic_model: 'claude-opus-5'
    })
    await agent.add_extensions(
        commamatrix.builtin.default_instruction,
        commamatrix.builtin.llm_http_adapter,
        commamatrix.builtin.http_connector,
    )
    print(agent.config_fields_markdown())
```

### Расширения

Список расширений изолирован для конкретного агента и не привязан к импорту модулей. Можно добавлять свои расширения: все содержимое модуля просматривается CommaMatrix на наличие объявленных хуков, инструментов, инструкций, коннекторов и иных модулей. Все компоненты, имеющие жизненный цикл, автоматически подтягиваются в жизненный цикл агента.

По умолчанию все, что объявлено в модуле `__main__` и все, что содержится в директории `.commamatrix/plugins`, загружается как расширение. Предотвратить это можно при помощи `Agent(auto_load_main=False)` и/или `Agent(auto_load_plugins=False)`.

```python
from commamatrix.builtin import data_tools, web_utils
import my_package, my_module

await agent.add_extensions("data_tools", "web_utils")  # можно использовать имена
await agent.add_extensions(my_package.my_extension)
await agent.add_extensions(my_module)
```

Внутренние модули пакета нужно импортировать из его `__init__.py`; ре-экспорт сам по себе не считается декларацией компонента.

Основные смысловые компоненты: `@tool`, `@instruction`, `@hook` (и конструктор `Hook`, позволяющий создавать новые события для хуков), `Service`, `Connector`, `BaseTable`, `Storage`, `FileStorage`, `LLMAdapter` и `@lifecycle_component`.

Прочитайте [руководство по созданию расширений](https://github.com/matrixd0t/commamatrix/blob/master/src/commamatrix/builtin/self_extension/guides/main.md).
Там же находятся ссылки на специализированные руководства.

Посмотрите папку [`examples/`](https://github.com/matrixd0t/commamatrix/tree/master/examples/) — там есть пример интерфейсного
агента и headless executor с делегированием задач субагенту.

### Безопасность

- Пароли HTTP-коннектора хешируются, а сгенерированный пароль администратора выдается
  единожды при первом запуске агента
- В CodeAct на бэкенде по-умолчанию (`SubprocessBackend`) выполняется произвольный Python-код с оступом к стандартной библиотеке,  установленным зависимостям и терминалу. Это **небезопасно**. Для недоверенных
  пользователей используйте внешний isolation layer, например systemd или
  Docker.
- Перед публикацией HTTP-коннектора проверьте reverse proxy, TLS, CORS, авторизацию.
- Используйте общие для всех расширений компоненты, не создавайте их заново: например, `agent.http_client` для Интернет-запросов и `agent.http_server` для регистрации своих эндпойнтов.

`written with love by dotmatrix`
