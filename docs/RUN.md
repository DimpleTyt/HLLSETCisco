# Этап 3 — запуск модели HLLSet на SBC

## Какой файл куда

На каждом SBC: **Programming → New → Template: Empty - Python3 → Create** → открыть `main.py` → удалить всё → вставить файл целиком → **Run**.

**Файл обязательно должен называться `main.py`** — PT запускает проект с него; файл с другим именем не стартует (в консоли только `Starting ...`).

| SBC | Файл из `scripts/` | Порт | Роль на чертеже |
|---|---|---|---|
| GRID | `GRID.py` | 5200 | Grid + User's lookup table |
| FPGA 1 … FPGA 5 | `FPGA1.py` … `FPGA5.py` | 5100 | рой плат |
| DATA | `DATA.py` | 5001 | идентификация 🟢 / доступ 🟠 |
| Dispatcher | `DISPATCHER.py` | 5000 | Router (планировщик роя) |
| user 1 / 2 / 3 | `USER1.py` / `USER2.py` / `USER3.py` | — | PC + «LLM» (клиент модели) |

Файлы FPGA отличаются только строкой `BOARD = "FPGAn"`, USER — только логином и паролем.

## Порядок запуска

1. **GRID** → в консоли `[NET] GRID listening on 5200`.
2. **FPGA 1–5** → `listening on 5100`, через пару секунд `connected to GRID`.
3. **DATA** → `listening on 5001`.
4. **Dispatcher** → `connected to DATA`, `connected to FPGA1` … `FPGA5`.
5. **user 1**, потом **user 2**, потом **user 3** — у каждого сценарий идёт сам, в конце `scenario finished`.

Серверы можно запускать в любом порядке — клиенты переподключаются сами каждые ~3 с. Но по порядку логи читаются проще.

## Что покажет каждый пользователь

**user 1 — полный проход модели:**

```
STATUS -> OK | data=up | boards=FPGA1,FPGA2,FPGA3,FPGA4,FPGA5
LOGIN -> OK | token xxxxxx...
INGEST doc1 -> OK | doc1 | tokens=9 | cid=h:9229c0b27ac1... | bits=8 | boards=FPGA1:2 FPGA2:2 FPGA3:2 FPGA4:2 FPGA5:1
INGEST doc2 -> OK | ... cid=h:faec65f77d48... | bits=8
QUERY UNION doc1 doc2     -> doc1+doc2 | h:a32ffb02b01d... | 13
QUERY INTERSECT doc1 doc2 -> doc1*doc2 | h:eb184778926c... | 3        (R-link)
QUERY DRN doc1 doc2       -> D=5@... | R=3@h:eb184778926c | N=5@...
QUERY HIST doc1           -> c_s=6,1,1,0,... card~8
QUERY LOOKUP doc1*doc2    -> 3 | fox quick the                         (материализация)
```

**user 2 — изоляция миров:** загружает тот же текст, что user1/doc1, но со своим seed (102): CID другой (`h:7b0bc8c0f0c5...`), а LOOKUP через свою LUT возвращает свои токены.

**user 3 — безопасность:** неверный пароль → `DENY`, поддельный токен → `DENY`, прямое подключение к FPGA1:5100 → `BLOCKED` (ACL), потом нормальный вход и загрузка.

CID в примере совпадут с твоими бит в бит: хеш и SHA-1 детерминированы. Токены доступа — случайные.

## Что видно в консолях серверов (для скриншотов в документацию)

| Узел | Строки | Поток на чертеже |
|---|---|---|
| DATA | `[GREEN] AUTH ...`, `[ORANGE] AUTH user1 -> token ... world seed=101` | идентификация / доступ |
| Dispatcher | `[GREEN] LOGIN`, `[ORANGE] access granted`, `[RED] INGEST ... -> 5 boards` | все три цвета |
| FPGA | `[RED] FPGA3 INGEST user1/doc1 2 tokens seed=101 -> 2 bits` | использование модели |
| GRID | `[BLUE] MERGE user1/doc1 +2 bits -> h:... pop=5` | линии FPGA → Grid |

## Что демонстрирует модель (связь со статьями)

- **Рой одинаковых плат:** загрузка текста делится на 5 частей, каждая плата ORит свою часть в один узел Grid. Итоговый CID тот же, что при обработке на одной плате (проверено) — union не зависит от порядка (Principle 2.1).
- **Existence is registration:** каждый результат (`doc1+doc2`, `doc1*doc2`, D/R/N) регистрируется в Grid и получает CID.
- **Content addressing:** `doc1*doc2` и `R.doc1.doc2` — один и тот же узел с одним CID.
- **Миры:** пользователь = seed; один текст → разные биты у разных пользователей; чтение только через свою LUT.
- **Float на хосте:** FPGA отдаёт только целые `c_s`, кардинальность (логарифмы) считает клиент.

## Упрощения модели (честно указать в документации)

- CID = SHA-1 канонического списка позиций, а не сериализованного Roaring-битмапа, как в hllset-core.
- Только униграммы; 3-граммы, TF-ранги, временная пирамида L0–L6 — следующие итерации.
- Токены доступа без срока жизни; пароли в открытом виде в DATA.py.
- Grid хранит всё в памяти SBC: после перезапуска Packet Tracer данные пропадают, скрипты нужно запустить заново.

## Если что-то не так

Пришли вывод консоли того узла, где ошибка (строки `[ERR]` или текст исключения PT). Самые вероятные места — названия функций сетевого API PT (`onReceive`, `onNewClient`, `connect`); скрипты проверены на эмуляторе этого API, но не на самом PT.
