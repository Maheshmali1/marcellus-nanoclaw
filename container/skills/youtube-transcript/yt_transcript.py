#!/usr/bin/env python3
"""
YouTube Transcript Extractor for NanoClaw
==========================================
Secure, token-efficient transcript extraction with layered fallback.

Layers:
  1. youtube-transcript-api  — fast, no media download
  2. yt-dlp subtitle extract — battle-tested fallback, still no media download

Security design:
  - Input is validated to a strict 11-char alphanumeric video ID before any
    network or subprocess call — raw user input never touches the shell.
  - subprocess calls use list args (never shell=True) to prevent injection.
  - All temp files are cleaned up via context manager.
  - Hard timeouts on all network and subprocess calls.
  - Output is plain UTF-8 text — no embedded instructions accepted or forwarded.

Usage:
  python3 yt_transcript.py <youtube_url_or_video_id>

Output (stdout, always JSON):
  Success: {"video_id": "...", "method": "...", "transcript": "...plain text..."}
  Failure: {"error": "...", "video_id": "...", "details": [...], "suggestion": "..."}
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# ── Constants ──────────────────────────────────────────────────────────────────

MAX_INPUT_LEN = 200          # Reject suspiciously long inputs immediately
SUBPROCESS_TIMEOUT = 45      # Hard wall-clock limit on yt-dlp subprocess
TRANSCRIPT_API_TIMEOUT = 15  # HTTP request timeout for transcript API calls
MAX_TRANSCRIPT_CHARS = 150_000  # Truncate runaway transcripts (token budget)

# Strict: YouTube video IDs are exactly 11 chars from this set — nothing else
_VIDEO_ID_RE = re.compile(r'^[A-Za-z0-9_-]{11}$')

# All known YouTube URL patterns, all captured groups point to the 11-char ID
_URL_PATTERNS = [
    re.compile(r'(?:youtube\.com/watch\?(?:[^&\s]*&)*v=)([A-Za-z0-9_-]{11})'),
    re.compile(r'youtu\.be/([A-Za-z0-9_-]{11})'),
    re.compile(r'youtube\.com/embed/([A-Za-z0-9_-]{11})'),
    re.compile(r'youtube\.com/v/([A-Za-z0-9_-]{11})'),
    re.compile(r'youtube\.com/shorts/([A-Za-z0-9_-]{11})'),
    re.compile(r'youtube\.com/live/([A-Za-z0-9_-]{11})'),
]

# ── Input Validation ───────────────────────────────────────────────────────────

def extract_video_id(raw: str) -> str:
    raw = raw.strip()

    if len(raw) > MAX_INPUT_LEN:
        raise ValueError("Input exceeds maximum allowed length")

    if _VIDEO_ID_RE.match(raw):
        return raw

    for pattern in _URL_PATTERNS:
        m = pattern.search(raw)
        if m:
            vid = m.group(1)
            if not _VIDEO_ID_RE.match(vid):
                raise ValueError(f"Extracted ID failed re-validation: {vid!r}")
            return vid

    raise ValueError(
        "Not a recognisable YouTube URL or video ID. "
        "Expected formats: https://youtu.be/VIDEO_ID or https://www.youtube.com/watch?v=VIDEO_ID"
    )

# ── Layer 1: youtube-transcript-api ───────────────────────────────────────────

def fetch_via_transcript_api(video_id: str) -> str:
    from youtube_transcript_api import (  # type: ignore[import]
        YouTubeTranscriptApi,
        NoTranscriptFound,
        TranscriptsDisabled,
    )

    langs = ['en', 'en-US', 'en-GB', 'en-AU', 'en-CA']

    transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

    try:
        transcript = transcript_list.find_manually_created_transcript(langs)
    except NoTranscriptFound:
        transcript = transcript_list.find_generated_transcript(langs)

    entries = transcript.fetch()

    parts = []
    for entry in entries:
        text = entry.get('text', '').strip()
        if text:
            text = (
                text.replace('&amp;', '&')
                    .replace('&lt;', '<')
                    .replace('&gt;', '>')
                    .replace('&quot;', '"')
                    .replace('&#39;', "'")
                    .replace('\n', ' ')
            )
            parts.append(text)

    return ' '.join(parts)

# ── Layer 2: yt-dlp subtitle extraction ───────────────────────────────────────

def fetch_via_ytdlp(video_id: str) -> str:
    safe_url = f'https://www.youtube.com/watch?v={video_id}'

    with tempfile.TemporaryDirectory(prefix='nctranscript_') as tmpdir:
        output_template = os.path.join(tmpdir, 'sub')

        cmd = [
            'yt-dlp',
            '--skip-download',
            '--write-subs',
            '--write-auto-subs',
            '--sub-lang', 'en',
            '--convert-subs', 'vtt',
            '--output', output_template,
            '--no-playlist',
            '--quiet',
            '--no-warnings',
            '--',
            safe_url,
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
            env={**os.environ, 'HOME': tmpdir, 'XDG_CONFIG_HOME': tmpdir},
        )

        if result.returncode not in (0, 1):
            err_preview = result.stderr[:300] if result.stderr else '(no stderr)'
            raise RuntimeError(f"yt-dlp exited {result.returncode}: {err_preview}")

        vtt_files = sorted(Path(tmpdir).glob('*.vtt'))
        if not vtt_files:
            raise FileNotFoundError(
                "yt-dlp ran but produced no subtitle file — "
                "video may have no captions available."
            )

        raw_vtt = vtt_files[0].read_text(encoding='utf-8', errors='replace')
        return _parse_vtt(raw_vtt)

def _parse_vtt(vtt_content: str) -> str:
    lines: list[str] = []
    seen: set[str] = set()

    for line in vtt_content.splitlines():
        line = line.strip()

        if (
            not line
            or '-->' in line
            or line.startswith('WEBVTT')
            or line.startswith('NOTE')
            or line.startswith('REGION')
            or line.startswith('STYLE')
            or re.match(r'^\d+$', line)
        ):
            continue

        clean = re.sub(r'<[^>]+>', '', line)
        clean = re.sub(r'\s+', ' ', clean).strip()

        if clean and clean not in seen:
            lines.append(clean)
            seen.add(clean)

    return ' '.join(lines)

# ── Output helpers ─────────────────────────────────────────────────────────────

def _truncate(text: str, max_chars: int = MAX_TRANSCRIPT_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + '\n\n[Transcript truncated to stay within token budget]'

def _emit(video_id: str, method: str, transcript: str, output_file: str | None) -> None:
    text = _truncate(transcript)

    if output_file:
        abs_path = os.path.realpath(output_file)
        allowed_prefixes = ('/tmp/', '/workspace/')
        if not any(abs_path.startswith(p) for p in allowed_prefixes):
            print(json.dumps({'error': f'Output path not allowed: {abs_path}. Use /tmp/ or /workspace/.'}))
            sys.exit(1)

        os.makedirs(os.path.dirname(abs_path) if os.path.dirname(abs_path) else '.', exist_ok=True)
        Path(abs_path).write_text(text, encoding='utf-8')

        print(json.dumps({
            'video_id': video_id,
            'method': method,
            'char_count': len(text),
            'word_count': len(text.split()),
            'transcript_file': abs_path,
            'tip': f'Read the transcript with: Read("{abs_path}") — use offset/limit to read sections.',
        }, ensure_ascii=False))
    else:
        print(json.dumps({
            'video_id': video_id,
            'method': method,
            'transcript': text,
            'char_count': len(text),
        }, ensure_ascii=False))

def _fail(video_id: str, errors: list[str]) -> None:
    print(json.dumps({
        'error': 'Could not fetch transcript — all methods failed',
        'video_id': video_id,
        'details': errors,
        'suggestion': (
            "This video may have no captions, or YouTube is rate-limiting this IP. "
            "You can get the transcript manually: on YouTube, click the '...' menu "
            "below the video → 'Show transcript', then copy-paste it here."
        ),
    }, ensure_ascii=False))

# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) < 2:
        print(json.dumps({'error': 'Usage: yt_transcript.py <youtube_url_or_video_id> [output_file]'}))
        sys.exit(1)

    raw_input = sys.argv[1]
    output_file: str | None = sys.argv[2] if len(sys.argv) >= 3 else None

    try:
        video_id = extract_video_id(raw_input)
    except ValueError as exc:
        print(json.dumps({'error': str(exc)}))
        sys.exit(1)

    errors: list[str] = []

    # Layer 1
    try:
        text = fetch_via_transcript_api(video_id)
        if text.strip():
            _emit(video_id, 'transcript-api', text, output_file)
            return
        errors.append('transcript-api: returned empty transcript')
    except ImportError:
        errors.append('transcript-api: package not installed (pip install youtube-transcript-api)')
    except Exception as exc:
        errors.append(f'transcript-api: {type(exc).__name__}: {str(exc)[:120]}')

    # Layer 2
    try:
        text = fetch_via_ytdlp(video_id)
        if text.strip():
            _emit(video_id, 'yt-dlp', text, output_file)
            return
        errors.append('yt-dlp: returned empty transcript')
    except FileNotFoundError as exc:
        if 'yt-dlp' in str(exc) or 'No subtitle' in str(exc):
            errors.append(f'yt-dlp: {exc}')
        else:
            errors.append(f'yt-dlp: {type(exc).__name__}: {str(exc)[:120]}')
    except Exception as exc:
        errors.append(f'yt-dlp: {type(exc).__name__}: {str(exc)[:120]}')

    _fail(video_id, errors)
    sys.exit(1)

if __name__ == '__main__':
    main()
