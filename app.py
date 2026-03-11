import re
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
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript = transcript_list.find_transcript(["en", "en-US", "en-GB"])
        segments = transcript.fetch()
    except NoTranscriptFound:
        return jsonify({"error": "Англійські субтитри не знайдені для цього відео."}), 404
    except (TranscriptsDisabled, VideoUnavailable):
        return jsonify({"error": "Субтитри недоступні для цього відео."}), 404
    except Exception as exc:
        return jsonify({"error": f"Помилка отримання субтитрів: {str(exc)}"}), 500

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
            "totalWords": len(tokens),
            "uniqueWords": len(frequencies),
            "topWords": top_words,
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
