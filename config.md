# Конфигурация CommaMatrix

Каждое поле конфигурации объявляется на уровне модуля как `ConfigField[T](name=..., default=..., description=...)`.
Сам объект `ConfigField` выступает ключом в конфигурации агента, поэтому настройки задаются так:

```python
from commamatrix import *
from commamatrix.builtin import llm_http_adapter

agent = Agent(name="my_lovely_assistant", config={
    agentic_model: "claude-opus-5",
})

agent.config.set(llm_api_base, os.environ["LLM_API_BASE"])
agent.config.set(openai_api_key, os.environ["OPENAI_API_KEY"])

# Поля можно задавать лениво: callable-default вычисляется при первом чтении,
# а значением может быть и предикат (например, re.Pattern для имени модели).
```

Вызовите `agent.config_fields_markdown()`, чтобы получить список полей, доступных с текущим набором расширений
(имя, тип, значение по умолчанию, описание и модуль-объявитель). Метод работает без запуска агента.

Ниже перечислены поля ядра (`commamatrix.*`) и всех встроенных расширений (`commamatrix.builtin.*`).

## Ядро

### Общие (`commamatrix.utils`)

| Поле | Тип | По умолчанию | Описание |
|------|-----|--------------|----------|
| `commamatrix_dir` | `str` | `".commamatrix"` | Корневая директория для всех данных CommaMatrix |
| `allow_absolute_paths` | `bool` | `True` | Разрешать агенту доступ к абсолютным путям вне CWD |

### Логирование (`commamatrix.components.config`)

| Поле | Тип | По умолчанию | Описание |
|------|-----|--------------|----------|
| `log_level` | `str` | `"INFO"` | Минимальный уровень логирования агента |
| `log_format` | `str` | формат по умолчанию | Строка формата `logging` для этого агента |
| `log_file` | `str \| None` | `None` | Путь к файлу ротируемого лога агента |
| `log_to_console` | `bool` | `True` | Выводить логи агента в консоль |

### HTTP-сервер (`commamatrix.components.server`)

| Поле | Тип | По умолчанию | Описание |
|------|-----|--------------|----------|
| `http_port` | `int` | `8338` | Порт HTTP-сервера |
| `http_host` | `str` | `"0.0.0.0"` | Хост привязки HTTP-сервера; `127.0.0.1` ограничивает доступ из веба |
| `http_external_url` | `str \| None` | `None` | Публичный базовый URL для передачи файлов внешней LLM |

### HTTP-клиент (`commamatrix.components.http_client`)

| Поле | Тип | По умолчанию | Описание |
|------|-----|--------------|----------|
| `http_default_headers` | `dict[str, str] \| None` | `None` | Дополнительные заголовки, добавляемые к заголовкам HTTP-клиента агента |
| `http_timeout` | `int` | `120` | Таймаут HTTP-клиента агента в секундах |

### Провайдеры данных (`commamatrix.components.storage`, `commamatrix.components.file_storage`)

| Поле | Тип | По умолчанию | Описание |
|------|-----|--------------|----------|
| `active_storage` | `str \| None` | `None` | Id дескриптора активного `Storage`; `None` — первый доступный |
| `active_file_storage` | `str \| None` | `None` | Id дескриптора активного `FileStorage`; `None` — первый доступный |

### LLM-адаптер (`commamatrix.components.llm_adapter`)

| Поле | Тип | По умолчанию | Описание |
|------|-----|--------------|----------|
| `reasoning_level` | `str` | `""` | Режим рассуждений по умолчанию (если применим к модели). Универсальные значения: `max` / `highest` / `lowest` |

### Инструменты (`commamatrix.components.tool`)

| Поле | Тип | По умолчанию | Описание |
|------|-----|--------------|----------|
| `tool_max_out_chars` | `int` | `10000` | Бюджет символов для вывода инструментов с `truncation`; полный вывод пишется в `commamatrix_dir/tool_outputs` |

### Расширения (`commamatrix.core.agent.agent`)

| Поле | Тип | По умолчанию | Описание |
|------|-----|--------------|----------|
| `plugins_dir` | `str` | `"plugins"` | Поддиректория `commamatrix_dir`, откуда загружаются расширения при `auto_load_plugins` |
| `agentic_model` | `str \| re.Pattern` | `""` | Точное имя модели или regex для выбора модели по умолчанию; пусто — любая |

## Builtin

### CodeAct (`commamatrix.builtin.codeact`)

| Поле | Тип | По умолчанию | Описание |
|------|-----|--------------|----------|
| `codeact_enabled` | `bool` | `True` | Глобальный переключатель CodeAct. При `True` LLM видит только CodeAct-инструменты, остальные индексируются для BM25-поиска |
| `codeact_backend` | `type \| None` | `SubprocessBackend` | Класс бэкенда исполнения (по умолчанию это **не** песочница) |
| `codeact_searcher` | `type` | `BM25ToolSearcher` | Класс поискового движка по инструментам |
| `codeact_execution_timeout` | `float` | `120.0` | Таймаут одного исполнения кода, сек |
| `codeact_rpc_timeout` | `float` | `120.0` | Таймаут одного вложенного RPC-вызова инструмента, сек |
| `codeact_shutdown_timeout` | `float` | `5.0` | Время на graceful shutdown воркера, сек |
| `codeact_max_search_results` | `int` | `5` | Максимум результатов `tool_search` |
| `codeact_max_tools_list` | `int` | `50` | Максимум строк в `tools_list` |

### HTTP-коннектор (`commamatrix.builtin.http_connector`)

| Поле | Тип | По умолчанию | Описание |
|------|-----|--------------|----------|
| `http_ui_path` | `str \| None` | `None` | Явный путь к HTML UI; по умолчанию `CWD/commamatrix_dir/ui/index.html` |
| `http_auth_app_name` | `str` | `"commamatrix"` | Имя приложения для изоляции HTTP-пользователей |
| `http_auth_jwt_secret` | `str` | генерируется | Секрет подписи токенов; создаётся в `commamatrix_dir/.jwt_secret`, если не задан |
| `http_auth_token_ttl_seconds` | `int` | `86400` | Время жизни токена авторизации, сек |

### LLM HTTP адаптер (`commamatrix.builtin.llm_http_adapter`)

| Поле | Тип | По умолчанию | Описание |
|------|-----|--------------|----------|
| `openai_api_key` | `str` | `$OPENAI_API_KEY` | Ключ OpenAI-совместимого API |
| `anthropic_api_key` | `str` | `$ANTHROPIC_API_KEY` | Ключ Anthropic API |
| `llm_api_base` | `str` | `$LLM_API_BASE` | Базовый URL LLM API |
| `llm_api_protocol` | `str` | `chat_completions` | Протокол API по умолчанию (см. `ApiProtocol`) |
| `llm_refresh_on_start` | `bool` | `True` | Обновлять список моделей при старте адаптера |
| `llm_stream_read_timeout` | `float` | `60.0` | Таймаут чтения стрима, сек |
| `llm_request_timeout` | `float` | `300.0` | Таймаут нестримингового запроса, сек |

### Данные (`commamatrix.builtin.data_tools`)

| Поле | Тип | По умолчанию | Описание |
|------|-----|--------------|----------|
| `read_timeout` | `int` | `30` | Таймаут одного HTTP-запроса в `read` |
| `read_max_response_bytes` | `int` | `5242880` | Максимум байт скачиваемого URL в `read` |
| `read_max_redirects` | `int` | `5` | Максимум HTTP-редиректов в `read` |

### Веб-поиск (`commamatrix.builtin.web_utils`)

| Поле | Тип | По умолчанию | Описание |
|------|-----|--------------|----------|
| `web_search_max_limit` | `int` | `50` | Максимум результатов поиска |
| `web_search_timeout` | `int` | `10` | Таймаут одного текстового поиска, сек |
| `web_search_max_output_chars` | `int` | `20000` | Максимум символов вывода поиска |

### MCP (`commamatrix.builtin.mcp`)

| Поле | Тип | По умолчанию | Описание |
|------|-----|--------------|----------|
| `mcp_config_path` | `str` | `".commamatrix/mcp.json"` | Путь к JSON-конфигурации MCP |
| `mcp_client_name` | `str` | `"commamatrix"` | Имя клиента при MCP-инициализации |
| `mcp_client_version` | `str` | `"0.1.0"` | Версия клиента при MCP-инициализации |

### Пользовательские заголовки (`commamatrix.builtin.multi_user`)

| Поле | Тип | По умолчанию | Описание |
|------|-----|--------------|----------|
| `user_header_renderer` | `Callable \| None` | встроенный рендерер | Рендерер заголовка сообщения `(run, item) -> str \| None`; поддерживает async. Шорткаты: `%USER%`, `%DATETIME%`, `%NAME%` |
| `user_header_datetime_format` | `str` | `"%H:%M:%S %d.%m.%Y"` | strftime-формат даты в заголовке |
| `user_header_timezone` | `str` | `"Europe/Moscow"` | IANA-таймзона, если коннектор не определил её |

### Патчи (`commamatrix.builtin.apply_patch`)

| Поле | Тип | По умолчанию | Описание |
|------|-----|--------------|----------|
| `max_patch_chars` | `int` | `2000000` | Максимум символов патча для `apply_patch` |

### Файловое хранилище (`commamatrix.builtin.simple_fs`)

| Поле | Тип | По умолчанию | Описание |
|------|-----|--------------|----------|
| `files_dir` | `str` | `"files"` | Поддиректория `commamatrix_dir` для файлового хранилища |

### SQL-хранилище (`commamatrix.builtin.sql`)

| Поле | Тип | По умолчанию | Описание |
|------|-----|--------------|----------|
| `sqlite_path` | `str` | `"db.sqlite"` | Файл БД под `commamatrix_dir` |
| `postgres_dsn` | `str` | обязательное | DSN PostgreSQL: `user:password@host:port/database` |
