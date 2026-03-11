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
    try:
        return transcript_list.find_manually_created_transcript(ENGLISH_CODES)
    except NoTranscriptFound:
        pass

    try:
        return transcript_list.find_generated_transcript(ENGLISH_CODES)
    except NoTranscriptFound:
        pass

    return transcript_list.find_transcript(ENGLISH_CODES)


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
            transcript = pick_english_transcript(transcript_list)
            return transcript, transcript.fetch()
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
        transcript, segments = fetch_transcript_with_retry(video_id)
    except NoTranscriptFound:
        return jsonify({"error": "Англійські субтитри (включно з auto-generated) не знайдені для цього відео."}), 404
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
            "subtitleSource": "auto-generated" if transcript.is_generated else "manual",
            "totalWords": len(tokens),
            "uniqueWords": len(frequencies),
            "topWords": top_words,
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
