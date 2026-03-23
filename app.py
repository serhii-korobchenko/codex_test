import html
import json
import re
import time
import urllib.request
from collections import Counter
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree

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

# Керується оператором: тематика -> перелік кандидатів.
# Застосунок фільтрує цей список і показує тільки відео, де транскрипція реально доступна.
TOPIC_VIDEO_CATALOG = {
    "technology": [
        {"id": "aircAruvnKk", "title": "How neural networks work", "subtitleLanguage": "en", "subtitleSource": "manual"},
        {"id": "rfscVS0vtbw", "title": "Python full course", "subtitleLanguage": "en", "subtitleSource": "auto-generated"},
        {"id": "8mAITcNt710", "title": "Git and GitHub crash course", "subtitleLanguage": "en", "subtitleSource": "auto-generated"},
    ],
    "science": [
        {"id": "5MgBikgcWnY", "title": "The basics of climate science", "subtitleLanguage": "en", "subtitleSource": "manual"},
        {"id": "k6U-i4gXkLM", "title": "CRISPR explained", "subtitleLanguage": "en", "subtitleSource": "auto-generated"},
        {"id": "WXuK6gekU1Y", "title": "How gravity works", "subtitleLanguage": "en", "subtitleSource": "auto-generated"},
    ],
    "business": [
        {"id": "x2qRDMHbXaM", "title": "Business model canvas", "subtitleLanguage": "en", "subtitleSource": "manual"},
        {"id": "PHe0bXAIuk0", "title": "Startup funding basics", "subtitleLanguage": "en", "subtitleSource": "auto-generated"},
        {"id": "fU-Pa3R8wT0", "title": "Marketing strategy fundamentals", "subtitleLanguage": "en", "subtitleSource": "auto-generated"},
    ],
    "education": [
        {"id": "PkZNo7MFNFg", "title": "Learn JavaScript", "subtitleLanguage": "en", "subtitleSource": "manual"},
        {"id": "Ke90Tje7VS0", "title": "React for beginners", "subtitleLanguage": "en", "subtitleSource": "auto-generated"},
        {"id": "Z1Yd7upQsXY", "title": "Data structures overview", "subtitleLanguage": "en", "subtitleSource": "auto-generated"},
    ],
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


def pick_english_transcript(transcript_list):
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
        return transcript, "auto-generated" if transcript.is_generated else "manual"
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
    return "too many requests" in msg or "429" in msg or "google.com/sorry" in msg


def _url_get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=12) as response:
        return response.read().decode("utf-8", errors="ignore")


def _extract_caption_tracks(page_html: str) -> list[dict]:
    match = re.search(r'"captions"\s*:\s*(\{.*?\})\s*,\s*"videoDetails"', page_html, re.DOTALL)
    if not match:
        return []

    try:
        captions_obj = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []

    renderer = captions_obj.get("playerCaptionsTracklistRenderer", {})
    return renderer.get("captionTracks", [])


def _segments_from_caption_xml(xml_text: str) -> list[SimpleNamespace]:
    root = ElementTree.fromstring(xml_text)
    segments: list[SimpleNamespace] = []

    for node in root.findall("text"):
        text = html.unescape("".join(node.itertext())).strip()
        if text:
            segments.append(SimpleNamespace(text=text))

    return segments


def fetch_via_watch_page(video_id: str):
    page_html = _url_get(f"https://www.youtube.com/watch?v={video_id}")
    tracks = _extract_caption_tracks(page_html)
    if not tracks:
        raise NoTranscriptFound(video_id=video_id, requested_language_codes=ENGLISH_CODES, transcript_data=[])

    english_track = None
    translatable_track = None

    for track in tracks:
        if track.get("languageCode") in ENGLISH_CODES:
            english_track = track
            break
        if track.get("isTranslatable"):
            translatable_track = track

    selected = english_track or translatable_track
    if not selected:
        raise NoTranscriptFound(video_id=video_id, requested_language_codes=ENGLISH_CODES, transcript_data=[])

    caption_url = selected.get("baseUrl")
    if not caption_url:
        raise NoTranscriptFound(video_id=video_id, requested_language_codes=ENGLISH_CODES, transcript_data=[])

    source = "auto-generated" if selected.get("kind") == "asr" else "manual"
    language = selected.get("languageCode", "unknown")

    if not english_track and translatable_track:
        if "tlang=" not in caption_url:
            caption_url += "&tlang=en"
        source = f"{source} (translated to en)"
        language = "en"

    xml_text = _url_get(caption_url)
    segments = _segments_from_caption_xml(xml_text)
    if not segments:
        raise NoTranscriptFound(video_id=video_id, requested_language_codes=ENGLISH_CODES, transcript_data=[])

    return SimpleNamespace(language_code=language, is_generated=selected.get("kind") == "asr"), source, segments


def fetch_transcript_with_retry(video_id: str, retries: int = 1, delay_s: float = 1.5):
    last_error = None

    for attempt in range(retries + 1):
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            transcript, source_label = pick_english_transcript(transcript_list)
            return transcript, source_label, transcript.fetch()
        except Exception as exc:
            last_error = exc
            if attempt < retries and is_rate_limited_error(exc):
                time.sleep(delay_s)
                continue
            break

    if last_error and isinstance(last_error, (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable)):
        try:
            return fetch_via_watch_page(video_id)
        except Exception:
            pass

    if last_error:
        raise last_error
    raise NoTranscriptFound(video_id=video_id, requested_language_codes=ENGLISH_CODES, transcript_data=[])


def build_transcript_error(exc: Exception) -> tuple[str, int]:
    if is_rate_limited_error(exc):
        return (
            "YouTube тимчасово обмежив запити (429 Too Many Requests). Спробуй ще раз через 1-2 хвилини.",
            429,
        )
    if isinstance(exc, TranscriptsDisabled):
        return (
            "YouTube API повідомляє, що субтитри вимкнені. Спробуй інше відео або повтори трохи пізніше.",
            404,
        )
    if isinstance(exc, VideoUnavailable):
        return ("Відео недоступне (private/видалене/обмежене).", 404)
    if isinstance(exc, NoTranscriptFound):
        return ("Не вдалося знайти англійські субтитри (включно з auto-generated/translated).", 404)
    if isinstance(exc, (HTTPError, URLError, ElementTree.ParseError, json.JSONDecodeError)):
        return ("Не вдалося зчитати субтитри з YouTube. Спробуй пізніше.", 502)
    return ("Не вдалося отримати субтитри. Спробуй інше відео або повтори спробу пізніше.", 500)


def get_operator_curated_videos_for_topic(topic: str) -> list[dict]:
    candidates = TOPIC_VIDEO_CATALOG.get(topic, [])
    return [
        {
            "videoId": item["id"],
            "title": item["title"],
            "url": f"https://www.youtube.com/watch?v={item['id']}",
            "subtitleLanguage": item.get("subtitleLanguage", "en"),
            "subtitleSource": item.get("subtitleSource", "operator-verified"),
        }
        for item in candidates
    ]


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/topics")
def list_topics():
    return jsonify(
        {
            "topics": [
                {"id": topic_id, "label": topic_id.capitalize()}
                for topic_id in TOPIC_VIDEO_CATALOG.keys()
            ]
        }
    )


@app.get("/topic-videos")
def list_videos_by_topic():
    topic = request.args.get("topic", "").strip().lower()
    if topic not in TOPIC_VIDEO_CATALOG:
        return jsonify({"error": "Невідома тематика."}), 400

    videos = get_operator_curated_videos_for_topic(topic)
    return jsonify({"topic": topic, "videos": videos, "source": "operator-curated"})


@app.post("/analyze")
def analyze_subtitles():
    payload = request.get_json(silent=True) or {}
    url = payload.get("url", "")

    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Невірне YouTube посилання або ID відео."}), 400

    try:
        transcript, source_label, segments = fetch_transcript_with_retry(video_id)
    except Exception as exc:
        message, status_code = build_transcript_error(exc)
        return jsonify({"error": message}), status_code

    full_text = " ".join(segment.text for segment in segments)
    tokens = tokenize(full_text)

    if not tokens:
        return jsonify({"error": "Не вдалося знайти слова для аналізу у субтитрах."}), 422

    frequencies = Counter(tokens)
    top_words = [{"word": word, "count": count} for word, count in frequencies.most_common(25)]

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
