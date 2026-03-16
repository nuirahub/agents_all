# 01_05_01 — File & Email Agent (confirmation)

Port w Pythonie zadania **01_05_confirmation**: agent z operacjami na plikach i wysyłką e-maili z **wymaganą potwierdzeniem w terminalu** przed wysłaniem.

## Uruchomienie

Z katalogu `git/my_python`:

```bash
python 01_05_01/app.py
```

Albo z `01_05_01`:

```bash
python app.py
```

## Wymagana konfiguracja

1. W `git/my_python/.env` ustaw:
   - **API LLM:** `OPENAI_API_KEY` lub `OPENROUTER_API_KEY` (oraz opcjonalnie `AI_PROVIDER=openai` / `openrouter`)
   - **Resend:** `RESEND_API_KEY`, `RESEND_FROM` (np. `noreply@twoja-domena.com`)

2. Białe listy adresów e-mail w `01_05_01/workspace/whitelist.json`:
   - dokładne adresy, np. `user@example.com`,
   - lub domeny, np. `@example.com`.

## Zachowanie

1. **Narzędzia plikowe** (względem `workspace/`): `fs_list`, `fs_read`, `fs_write`, `fs_search`.
2. **E-mail:** `send_email` — przed wysłaniem pojawia się potwierdzenie w terminalu (Y / T=trust / N).
3. Komendy REPL: `exit` — wyjście, `clear` — wyczyszczenie konwersacji i zaufania, `untrust` — cofnięcie zaufania do narzędzi.

## Różnice względem oryginału (JS)

- Zamiast serwera MCP dla plików używane są natywne narzędzia Pythona w obrębie `workspace/`.
- Resend i Responses API (OpenAI/OpenRouter) jak w oryginale; potwierdzenie e-maila (Y/T/N) działa tak samo.
