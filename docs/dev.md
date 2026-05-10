Проект CLenz — это Python-пакет (v0.1.0) для анализа
  C-кода, построенный на ANTLR 4.13.2 с архитектурой
  Hexagonal (Ports & Adapters). Вот полное описание:

  ---
  🏗 Архитектура

  src/clenz/
  ├── domain/          # Ядро бизнес-логики (модели, события,
   ошибки, порты)
  ├── application/     # Use Cases / сервисы приложения
  ├── infrastructure/  # Реализации портов (ANTLR, файловая
  система, рендеринг, линтинг)
  └── presentation/    # CLI-интерфейс

  ---
  📦 Что делает
  
  1. Парсинг C-кода — через ANTLR с C11-грамматикой
  (resources/grammars/c/C.g4)
  2. Nassi-диаграммы — генерирует HTML-визуализации структур
  управления (if/else, for, while, do-while, switch)
  3. Code smells — обнаруживает 12 типов проблем в коде:
    - GLOBAL_VARIABLE, LONG_FUNCTION (>60 строк),
  MAGIC_NUMBER
    - UNCHECKED_MALLOC, MEMORY_LEAK_RISK, UNSAFE_FUNCTION
    - MISSING_CONST, UNINITIALIZED_VAR, UNCHECKED_RETURN
    - SHORT_NAME, LARGE_FILE (>500 строк), MIXED_ABSTRACTION

  ---
  📁 Ключевые файлы
  
  Файл: src/clenz/domain/model.py
  Роль: Модели: SourceUnit, ParseOutcome, ParsingJob,
    StructuralElement
  ────────────────────────────────────────
  Файл: src/clenz/domain/ports.py
  Роль: Абстрактные интерфейсы (ABC): CSyntaxParser,
    SourceRepository, CControlFlowExtractor,
    NassiDiagramRenderer, CSmellScanner
  ────────────────────────────────────────
  Файл: src/clenz/domain/control_flow.py
  Роль: Модели потока управления: IfFlowStep, WhileFlowStep,
    ForFlowStep, SwitchFlowStep и т.д.
  ────────────────────────────────────────
  Файл: src/clenz/domain/events.py
  Роль: События домена: ParsingJobStarted, SourceUnitParsed,
    ParsingJobCompleted
  ────────────────────────────────────────
  Файл: src/clenz/domain/errors.py
  Роль: Кастомные ошибки
  ────────────────────────────────────────
  Файл: src/clenz/application/use_cases.py
  Роль: ParsingJobService — оркестратор парсинга
  ────────────────────────────────────────
  Файл: src/clenz/application/control_flow.py
  Роль: NassiDiagramService — генерация диаграмм
  ────────────────────────────────────────
  Файл: src/clenz/infrastructure/antlr/parser_adapter.py
  Роль: AntlrCSyntaxParser — адаптер ANTLR
  ────────────────────────────────────────
  Файл:
  src/clenz/infrastructure/antlr/control_flow_extractor.py
  Роль: AntlrCControlFlowExtractor — извлечение структуры из
    AST (1315 строк, самый большой файл)
  ────────────────────────────────────────
  Файл: src/clenz/infrastructure/linting/smell_scanner.py
  Роль: AntlrCSmellScanner — токен-сканер запахов (449 строк)
  ────────────────────────────────────────
  Файл:
  src/clenz/infrastructure/rendering/nassi_html_renderer.py
  Роль: HtmlNassiDiagramRenderer — рендеринг в HTML с
    CSS-тёмной темой
  ────────────────────────────────────────
  Файл: src/clenz/presentation/cli/main.py
  Роль: CLI с 6 командами (parse-file, parse-dir, nassi-file,

    nassi-dir, smell-file, smell-dir)
  ────────────────────────────────────────
  Файл: scripts/generate_c_parser.py
  Роль: Генерирует Python-артефакты ANTLR из .g4 грамматики

  ---
  🧪 Тесты
  
  - tests/test_parse_use_cases.py — 4 теста (parse-file,
  parse-dir, enum, CLI JSON)
  - tests/test_domain_model.py — 2 теста (ParsingJob
  validation, outcomes)
  - tests/test_nassi_diagrams.py — 17 тестов (Nassi-сервис,
  control flow extractors, depth-rendering, CSS)
  - tests/fixtures/ — valid.c, control_flow.c, invalid.c

  ---
  ⚙️  Технологический стек
  
  - Python 3.13+
  - antlr4-python3-runtime==4.13.2
  - pytest, ruff (dev-зависимости)
  - uv — управление зависимостями и виртуальным окружением

  ---
  🚀 CLI — примеры использования
  
  clenz parse-file path/to/file.c                    # 
  JSON-отчёт о парсинге
  clenz parse-dir path/to/dir/                       # 
  Парсинг всех .c в директории
  clenz nassi-file path/to/file.c --out out.html     # 
  Nassi-диаграмма → HTML
  clenz nassi-dir path/to/dir/ --out out_dir/        # 
  Nassi-диаграммы для всей директории
  clenz smell-file path/to/file.c                    # Code 
  smells → JSON
  clenz smell-dir path/to/dir/                       # Code 
  smells для всех .c

  ---
  🧩 Особенности реализации
  
  - Двухпроходный парсинг: быстрый (SLL + BailErrorStrategy),
   с откатом на полный при ошибке
  - Три уровня парсинга: compilationUnit → compoundStatement
  → statement (от наиболее полного к минимальному)
  - Hidden-токены (preprocessor): сканируются отдельно для
  #include и #define
  - Depth-coded рендеринг: 50 уровней вложенности с
  циклической цветовой схемой (blue→green→purple→teal→amber)
  - Мемоизация контейнеров: _with_container / _containers
  стек для отслеживания struct/enum/function областей
  видимости
