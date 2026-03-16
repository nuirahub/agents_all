# my_python – odpowiednik 01_01_interaction

1. Jak wywołać Responses API z Pythona (z wykorzystaniem `requests`).
2. Jak budować historię rozmowy (multi‑turn) tak jak w `app.js`.
3. Jak wyciągać tekst odpowiedzi i liczbę tokenów rozumowania.

## Wymagania

- Python 3.10+
- Zainstalowane zależności:

```bash
pip install -r requirements.txt
```

- Ustawione zmienne środowiskowe (tak jak dla wersji Node):
  - `OPENAI_API_KEY` **lub** `OPENROUTER_API_KEY`
  - opcjonalnie `AI_PROVIDER` (`openai` lub `openrouter`)
  - opcjonalnie `OPENROUTER_HTTP_REFERER`, `OPENROUTER_APP_NAME`

Skrypt spróbuje też wczytać plik `.env` z katalogu `4th-devs` (tak jak `config.js` w wersji Node), jeśli taki plik istnieje.

## Uruchomienie

Z poziomu katalogu `my_python`:

```bash
python app.py
```

Po poprawnej konfiguracji zobaczysz dwa pytania i odpowiedzi modelu:

1. `What is 25 * 48?`
2. `Divide that by 4.`

…wraz z liczbą tokenów rozumowania dla każdej odpowiedzi.
