# YouTube Subtitles Word Analyzer

Односторінковий web-застосунок для Railway: приймає YouTube URL (або video ID), завантажує **англійські** субтитри та показує найчастіші слова.

## Локальний запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Відкрий `http://localhost:8080`.

## Deploy на Railway

Railway автоматично підхопить `Procfile`:

```txt
web: gunicorn app:app
```

## Що робить аналіз

- Дістає англійські субтитри (`en`, `en-US`, `en-GB`) з підтримкою auto-generated від YouTube та fallback на автопереклад в англійську
- Токенізує текст
- Відкидає короткі/стоп-слова
- Повертає топ-25 слів з частотами

- Показує, чи субтитри manual чи auto-generated

## Обробка обмежень YouTube

- Якщо YouTube повертає `429 Too Many Requests`, API повертає зрозуміле повідомлення без технічного stack trace та статус `429`.
- Додано короткий retry при тимчасовому rate-limit.
