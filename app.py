import re
import time
from collections import Counter
from urllib.parse import parse_qs, urlparse

from flask import Flask, jsonify, render_template, request
from youtube_transcript_api import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
    YouTubeTranscriptApi,
)

app = Flask(__name__)

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "but", "by",
    "for", "from", "had", "has", "have", "he", "her", "hers", "him", "his", "i",
    "if", "in", "into", "is", "it", "its", "it's", "me", "my", "of", "on", "or",
    "our", "ours", "she", "so", "that", "the", "their", "them", "they", "this", "to",
    "us", "was", "we", "were", "what", "when", "where", "which", "who", "will", "with",
    "you", "your", "yours",
}

ENGLISH_CODES = ["en", "en-US", "en-GB"]


def extract_video_id(url: str) -> str | None:
    parsed = urlparse(url.strip())

    if parsed.netloc in {"youtu.be", "www.youtu.be"}:
        return parsed.path.lstrip("/") or None

    if parsed.netloc in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            return parse_qs(parsed.query).get("v", [None])[0]
        if parsed.path.startswith("/shorts/") or parsed.path.startswith("/embed/"):
            parts = parsed.path.strip("/").split("/")
            return parts[1] if len(parts) > 1 else None

    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url.strip()):
        return url.strip()

    return None


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z']+", text.lower())
    return [w for w in words if len(w) > 2 and w not in STOPWORDS]


def pick_english_transcript(transcript_list):
    """
    Повертає кортеж: (transcript, source_label)

    Пріоритет:
    1) ручні англійські,
    2) auto-generated англійські,
    3) будь-які англійські,
    4) auto-generated будь-якою мовою + автопереклад в англійську,
    5) будь-які субтитри + автопереклад в англійську.
    """
    try:
        return transcript_list.find_manually_created_transcript(ENGLISH_CODES), "manual"
    except NoTranscriptFound:
        pass

    try:
        return transcript_list.find_generated_transcript(ENGLISH_CODES), "auto-generated"
    except NoTranscriptFound:
        pass

    try:
        transcript = transcript_list.find_transcript(ENGLISH_CODES)
        source = "auto-generated" if transcript.is_generated else "manual"
        return transcript, source
    except NoTranscriptFound:
        pass

    for transcript in transcript_list:
        if transcript.is_generated and transcript.is_translatable:
            return transcript.translate("en"), "auto-generated (translated to en)"

    for transcript in transcript_list:
        if transcript.is_translatable:
            translated = transcript.translate("en")
            source = "auto-generated (translated to en)" if transcript.is_generated else "manual (translated to en)"
            return translated, source

    raise NoTranscriptFound(video_id="", requested_language_codes=ENGLISH_CODES, transcript_data=[])


def is_rate_limited_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "too many requests" in msg
        or "429" in msg
        or "google.com/sorry" in msg
        or "request to youtube failed" in msg
    )


def fetch_transcript_with_retry(video_id: str, retries: int = 1, delay_s: float = 1.5):
    for attempt in range(retries + 1):
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            transcript, source_label = pick_english_transcript(transcript_list)
            return transcript, source_label, transcript.fetch()
        except Exception as exc:
            if attempt < retries and is_rate_limited_error(exc):
                time.sleep(delay_s)
                continue
            raise


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/analyze")
def analyze_subtitles():
    payload = request.get_json(silent=True) or {}
    url = payload.get("url", "")

    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Невірне YouTube посилання або ID відео."}), 400

    try:
        transcript, source_label, segments = fetch_transcript_with_retry(video_id)
    except NoTranscriptFound:
        return jsonify({"error": "Не знайдено придатні субтитри (включно з auto-generated/перекладом в англійську) для цього відео."}), 404
    except (TranscriptsDisabled, VideoUnavailable):
        return jsonify({"error": "Субтитри недоступні для цього відео."}), 404
    except Exception as exc:
        if is_rate_limited_error(exc):
            return jsonify(
                {
                    "error": (
                        "YouTube тимчасово обмежив запити (429 Too Many Requests). "
                        "Спробуй ще раз через 1-2 хвилини або пізніше."
                    )
                }
            ), 429
        return jsonify({"error": "Не вдалося отримати субтитри. Спробуй інше відео або повтори спробу пізніше."}), 500

    full_text = " ".join(segment.text for segment in segments)
    tokens = tokenize(full_text)

    if not tokens:
        return jsonify({"error": "Не вдалося знайти слова для аналізу у субтитрах."}), 422

    frequencies = Counter(tokens)
    top_words = [
        {"word": word, "count": count}
        for word, count in frequencies.most_common(25)
    ]

    return jsonify(
        {
            "videoId": video_id,
            "subtitleLanguage": transcript.language_code,
            "subtitleSource": source_label,
            "totalWords": len(tokens),
            "uniqueWords": len(frequencies),
            "topWords": top_words,
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
