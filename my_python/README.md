pip install -r requirements.txt

python app.py
curl http://localhost:8000/health

curl -X POST http://localhost:8000/api/chat/completions ^
-H "Content-Type: application/json" ^
-d "{\"input\":\"Hello!\"}"

curl -X POST http://localhost:8000/api/chat/completions -H "Content-Type: application/json" -d "@request.json"

---

01_05_02 agents

### Ogólny obraz

- **Co to jest**: `my_python/01_05_02_ agents/` to kompletny **runtime agentowy** (mini‑backend) w Pythonie – odpowiednik `4th-devs/01_05_agent` – wystawia HTTP API (FastAPI) do rozmowy z agentami, którzy mogą używać narzędzi (`tools`), delegować zadania innym agentom i MCP.

---

### Główne komponenty

- **`app.py` (FastAPI)**
  - Tworzy aplikację `FastAPI` z lifecycle (`lifespan`), CORS, logowaniem requestów.
  - Rejestruje endpointy:
    - `GET /health` – healthcheck.
    - `POST /api/chat/completions` – główny endpoint chatu (`stream` lub zwykły).
    - `GET /api/chat/agents/{id}` – status agenta.
    - `POST /api/chat/agents/{id}/deliver` – dostarczenie wyniku narzędzia „human”.
    - `POST /api/chat/agents/{id}/cancel` – anulowanie agenta.
    - `GET /api/mcp/servers`, `/api/mcp/tools` – MCP.
    - `GET /api/providers` – lista providerów modeli.
  - W `lifespan`:
    - Tworzy repozytoria (in‑memory lub SQLite, zależnie od `DATABASE_URL`).
    - Inicjuje MCP (`mcp_client`) i tracing.
    - Seeduje użytkownika domyślnego.

- **`config.py` (dla agenta)**
  - Ładuje `.env` z `my_python/.env`.
  - Importuje wspólną konfigurację LLM z `my_python/config.py` i na jej podstawie:
    - buduje `AI_CONFIG` (provider, api_key, endpoint),
    - rejestruje providery (`OpenAIProvider`, `GeminiProvider`) w `provider_registry`,
    - ustawia `DEFAULT_MODEL`, `MAX_TURNS`, limity tokenów.
  - Wspiera wielu providerów (OpenAI, OpenRouter, Gemini), wybór przez `AI_PROVIDER`.

- **`chat_service.py`**
  - Warstwa „use‑case” nad repozytoriami:
    - `create_agent_for_input` – tworzy agenta (sesja, model, tools) z inputem użytkownika.
    - `chat_once` – pojedynczy przebieg (bez streamowania eventów do klienta).
    - `chat_stream` – pełny loop z tool‑calling, MCP, wieloma turami.
  - Dobiera **listę narzędzi** na podstawie szablonu agenta (`agent_templates`) lub globalnie (`get_tool_definitions` + MCP tools).

- **`tools.py`**
  - Definiuje lokalne narzędzia:
    - `calculator` – podstawowa matematyka.
    - `ask_user` – „human in the loop” (agent czeka na odpowiedź człowieka).
    - `delegate` – delegowanie zadania do innego agenta.
    - `send_message` – wysłanie wiadomości do innego agenta.
    - **`send_email`** – (dodane przez nas) wysłanie maila przez SMTP (dane z `.env`).
    - `web_search` – specjalny typ obsługiwany przez Responses API (nie ma lokalnego handlera).
  - `TOOL_META` mapuje nazwy na typ (`sync` / `human` / `agent`) i handler.
  - `get_tool_definitions` – zwraca definicje w formacie OpenAI tools (plus `web_search`).
  - `execute_sync_tool` – wykonuje narzędzia typu `sync`.

- **`agent_templates.py` + `workspace/agents/*.agent.md`**
  - Ładuje szablony agentów z front‑matter YAML + markdown (system prompt).
  - Obecne szablony:
    - `alice_local`:
      - Tools: `calculator`, `delegate`, `ask_user`, `send_message`, `files__fs_read/write/search` + (pośrednio) `web_search`.
      - Ma w promptcie info o:
        - **bob** – agent do web search.
        - **mailer** – agent do wysyłania maili (po naszych zmianach).
      - Ma instrukcję, by przy prośbie o mail delegować zadanie do `mailer`.
    - `bob`:
      - Tools: `web_search`.
      - Specjalista od wyszukiwania w sieci.
    - `mailer` (nasz nowy):
      - Tools: `send_email`.
      - Ma prosty system prompt: wyciąga adres/temat/treść z zadania i wysyła maila.

- **Reszta plików (`domain.py`, `runner.py`, `repositories.py`, `events.py`, `tracing.py` itd.)**
  - Implementują wewnętrzny model stanu agenta (kolejne tury, „waitingFor”, głębia delegacji), przechowywanie w repozytoriach (in‑memory/SQLite), logowanie/tracing oraz obsługę delegacji i tool‑callów.

---

### Konfiguracja i wysyłanie maili

- `.env` w `my_python` zawiera:
  - Klucze do LLM (`OPENAI_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `AI_PROVIDER`…).
  - **Konfigurację SMTP** dla `send_email`:  
    `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM`.
- `send_email`:
  - Buduje wiadomość `MIMEMultipart`, wysyła przez `smtplib.SMTP` z TLS.
  - Zwraca sukces/błąd do agenta (w logach widać próby wysyłki).

---

### Jak praktycznie przetestować agenta

1. **Uruchom serwer** w katalogu `my_python/01_05_02_ agents`:

   ```bash
   python app.py
   ```

2. **Sprawdź health:**

   ```bash
   curl http://localhost:8000/health
   ```

3. **Wywołaj chat z agentem `alice_local` i poleceniem wysłania maila** (plik `request.json` w tym katalogu):

   ```bash
   curl -X POST "http://localhost:8000/api/chat/completions" \
     -H "Content-Type: application/json" \
     -d @request.json
   ```

   gdzie `request.json` zawiera m.in.:

   ```json
   {
     "input": "...prośba o wyszukanie i wysłanie maila...",
     "instructions": "...",
     "model": "gpt-4.1",
     "agent": "alice_local"
   }
   ```

Wtedy przepływ wygląda tak: klient → `/api/chat/completions` → `alice_local` → (delegacja do `bob` po web_search + delegacja do `mailer` po wysłanie maila przez `send_email`).

---

Oto uporządkowany przepływ:

---

## Scenariusz: chat bez agenta, pytanie „Jakie zadania możesz realizować”

Żądanie: `POST /api/chat/completions` z body np.  
`{"input": "Jakie zadania możesz realizować"}`  
(bez `agent`, bez `stream`, z domyślnymi `instructions`).

---

### 1. Wejście do API (`app.py`)

| Krok | Co się dzieje                                                       | Funkcja / miejsce                                                                                                                               |
| ---- | ------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| 1.1  | FastAPI przyjmuje request, waliduje body do `ChatRequest`.          | `create_completion(body: ChatRequest, ...)`                                                                                                     |
| 1.2  | Sprawdzenie auth (jeśli `AUTH_ENABLED=true`).                       | `require_auth` (Depends)                                                                                                                        |
| 1.3  | Rozbicie `body.input`: string → jeden tekst; tablica → wiele items. | `_parse_input(body.input)` → `("Jakie zadania możesz realizować", None)`                                                                        |
| 1.4  | Wywołanie chatu bez streamu.                                        | `chat_once(repos, input_text=..., input_items=None, instructions="You are a helpful assistant.", model=None, agent_name=None, session_id=None)` |

---

### 2. Utworzenie agenta i wpisanie wejścia (`chat_service.py`)

| Krok | Co się dzieje                                                                                                                       | Funkcja                                                                                    |
| ---- | ----------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| 2.1  | Tworzenie agenta pod to jedno wywołanie.                                                                                            | `create_agent_for_input(...)`                                                              |
| 2.2  | `agent_name=None` → brak szablonu.                                                                                                  | `get_agent_template(None)` → `template = None`                                             |
| 2.3  | Model: `model or template.model or DEFAULT_MODEL` → **DEFAULT_MODEL** (np. z config).                                               | —                                                                                          |
| 2.4  | Instrukcje: bez szablonu zostaje **"You are a helpful assistant."**.                                                                | —                                                                                          |
| 2.5  | Narzędzia: brak szablonu → **wszystkie** (calculator, ask_user, delegate, send_message, send_email + web_search + ewentualnie MCP). | `_get_all_tool_definitions()` → `get_tool_definitions()` + MCP                             |
| 2.6  | Sesja: brak `session_id` → tworzona **nowa sesja**.                                                                                 | `repos.sessions.create()`                                                                  |
| 2.7  | Tworzenie rekordu agenta (status `pending`, task = instructions, config z modelem i listą tools).                                   | `repos.agents.create({...})`                                                               |
| 2.8  | Zapisanie wiadomości użytkownika jako jedyny item.                                                                                  | `repos.items.create(agent.id, {"type": "message", "role": "user", "content": input_text})` |
| 2.9  | Zwracany jest **agent_id**.                                                                                                         | `return agent.id`                                                                          |

---

### 3. Uruchomienie agenta – jedna lub więcej tur (`chat_service.py` → `runner.py`)

| Krok | Co się dzieje      | Funkcja                                    |
| ---- | ------------------ | ------------------------------------------ |
| 3.1  | Wywołanie runnera. | `chat_once` → `run_agent(agent_id, repos)` |

**W `run_agent(agent_id, repos)`:**

| Krok | Co się dzieje                                       | Funkcja                                                                |
| ---- | --------------------------------------------------- | ---------------------------------------------------------------------- |
| 3.2  | Pobranie agenta z repozytorium.                     | `repos.agents.get_by_id(agent_id)`                                     |
| 3.3  | Status `pending` → przejście w **running**.         | `start_agent(agent)` → `domain.py`, potem `repos.agents.update(agent)` |
| 3.4  | Kontekst eventów (trace_id, session_id, agent_id…). | `create_event_context(...)`                                            |
| 3.5  | Emisja zdarzenia startu agenta.                     | `event_emitter.emit("agent.started", ...)`                             |
| 3.6  | Pętla tur (do `MAX_TURNS`). Dla każdej tury:        | `for _ in range(max_turns)`                                            |

---

### 4. Pojedyncza tura (np. pierwsza)

| Krok | Co się dzieje                                                         | Funkcja                                                                                           |
| ---- | --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| 4.1  | Pobranie wszystkich items agenta (na starcie: jedna wiadomość user).  | `repos.items.list_by_agent(agent.id)`                                                             |
| 4.2  | Ewentualne przycinanie kontekstu (pruning), jeśli przekroczony limit. | `needs_pruning` → `prune_conversation` (przy dłuższej rozmowie)                                   |
| 4.3  | Wywołanie modelu: instructions + items + tools.                       | `call_provider(model=..., instructions=agent.task, input_items=provider_items, tools=tools, ...)` |

**W `provider.py` → `call_provider`:**

| Krok | Co się dzieje                                              | Funkcja                                                 |
| ---- | ---------------------------------------------------------- | ------------------------------------------------------- |
| 4.4  | Wybór providera (np. OpenAI) po nazwie modelu.             | `resolve_provider(model)` / `get_default_provider()`    |
| 4.5  | Budowa requestu (model, instructions, input_items, tools). | `ProviderRequest(...)`                                  |
| 4.6  | Jedno wywołanie do API (Responses API).                    | `provider.generate(request)` (np. `provider_openai.py`) |

Model dostaje:

- **instructions:** „You are a helpful assistant.”
- **input:** jedna wiadomość user: „Jakie zadania możesz realizować”
- **tools:** pełna lista (calculator, ask_user, delegate, send_message, send_email, web_search, MCP…)

---

### 5. Odpowiedź modelu i przetworzenie wyjścia (`runner.py`)

| Krok | Co się dzieje                                                                                                                                 | Funkcja                                                                                  |
| ---- | --------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| 5.1  | Zwrot z providera: lista `output_items` (message i ewentualnie function_call) + usage.                                                        | `call_provider` → `output_items, usage`                                                  |
| 5.2  | Emisja zdarzenia zakończenia generacji.                                                                                                       | `event_emitter.emit("generation.completed", ...)`                                        |
| 5.3  | Dla każdego elementu odpowiedzi:                                                                                                              | pętla `for o in output_items`                                                            |
| 5.4  | **Message** → zapis jako item (role assistant, content).                                                                                      | `repos.items.create(agent.id, {"type": "message", "role": "assistant", "content": ...})` |
| 5.5  | **Function_call** → zapis; w zależności od typu narzędzia: sync (wykonanie od razu), human (zbieranie `waiting_for`), agent (delegacja), MCP. | `get_tool_type(name)` → `execute_sync_tool` / `WaitingFor` / `_run_delegate_child` / MCP |

Dla pytania „Jakie zadania możesz realizować” model zwykle **nie** wywołuje narzędzi, tylko odpowiada tekstem. Wtedy jest tylko **jedna wiadomość asystenta**.

| Krok | Co się dzieje                                                   | Funkcja                                                                             |
| ---- | --------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| 5.6  | Brak wywołań funkcji → agent jest oznaczany jako **completed**. | `complete_agent(agent, result=...)` w `domain.py`                                   |
| 5.7  | Zapis stanu agenta.                                             | `repos.agents.update(agent)`                                                        |
| 5.8  | Koniec pętli; zwracany wynik.                                   | `return {"status": "completed", "agent": agent, "items": items, "waiting_for": []}` |

---

### 6. Złożenie odpowiedzi HTTP (`chat_service.py` → `app.py`)

| Krok | Co się dzieje                                                                                                           | Funkcja                                                                                                    |
| ---- | ----------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| 6.1  | Z wyniku runnera budowana jest odpowiedź dla klienta.                                                                   | `chat_once` po `run_agent`                                                                                 |
| 6.2  | Z items wybierane są: wiadomości asystenta → `{"type": "text", "text": content}`; ewentualne function_calls → w output. | pętla po `result["items"]`                                                                                 |
| 6.2  | Słownik odpowiedzi: id, sessionId, status, model, output, usage.                                                        | `resp = {"id": ..., "sessionId": ..., "status": "completed", "model": ..., "output": [...], "usage": ...}` |
| 6.3  | Status 200 (completed) lub 202 (waiting).                                                                               | `status_code = 202 if resp.get("status") == "waiting" else 200`                                            |
| 6.4  | Zwrot do klienta.                                                                                                       | `JSONResponse(content=ChatResponse(**resp).model_dump(), status_code=200)`                                 |

---

### Podsumowanie – kolejność funkcji

Dla **jednego** zapytania „Jakie zadania możesz realizować” (bez agenta, bez streamu) wywołania idą mniej więcej tak:

1. **app:** `create_completion` → `_parse_input` → `chat_once`
2. **chat_service:** `create_agent_for_input` (w środku: `get_agent_template(None)`, `_get_all_tool_definitions()`, `repos.sessions.create()`, `repos.agents.create()`, `repos.items.create()`)
3. **chat_service:** `run_agent(agent_id, repos)`
4. **runner:** `repos.agents.get_by_id` → `start_agent` (domain) → `repos.agents.update` → pętla tur:
   - `repos.items.list_by_agent` → (opcjonalnie) `needs_pruning` / `prune_conversation` → `call_provider`
5. **provider:** `_resolve(model)` → `provider.generate(request)` (np. OpenAI Responses API)
6. **runner:** przetworzenie `output_items` (zapis message/function_call, ewentualnie `execute_sync_tool` / `WaitingFor` / delegacja / MCP) → `complete_agent` → `repos.agents.update` → return
7. **chat_service:** zbudowanie `output` z items → return `resp`
8. **app:** `JSONResponse(content=ChatResponse(**resp).model_dump(), status_code=200)`

**Różnica przy wyborze agenta (np. `"agent": "alice_local"`):** w `create_agent_for_input` byłoby `get_agent_template("alice_local")` → inny **task** (system prompt z pliku) i **tools** (tylko te z szablonu + MCP), a nie pełna lista. Sam przebieg w `run_agent` i dalej pozostaje taki sam.
