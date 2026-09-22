"""
Vercel Serverless — توجيه التحميل
GET /api/file?u=<video_url>&q=<format_id>

يعيد 302 Redirect إلى الرابط المباشر (يتجاوز حد 4.5MB على Vercel).
"""
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import yt_dlp

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def get_redirect_url(url, fmt):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "socket_timeout": 20,
        "http_headers": {
            "User-Agent": BROWSER_UA,
            "Referer": "https://www.tiktok.com/",
        },
    }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:
        return None

    target = ""
    formats = info.get("formats") or []

    if fmt in ("mp3", "audio"):
        best = None
        for f in formats:
            if (f.get("acodec") not in (None, "none")
                    and f.get("vcodec") in (None, "none")
                    and f.get("url")):
                best = f
                if (f.get("ext") or "") == "mp3":
                    break
        if not best:
            for f in formats:
                if f.get("acodec") not in (None, "none") and f.get("url"):
                    best = f
                    break
        target = (best or {}).get("url", "")
    else:
        for f in formats:
            fid = f.get("format_id") or ""
            if fid == fmt or fid.startswith(fmt):
                if f.get("url"):
                    target = f["url"]
                    break
        if not target:
            # فيديو مدمج الصوت الأعلى
            combined = [
                x for x in formats
                if x.get("vcodec") not in (None, "none")
                and x.get("acodec") not in (None, "none")
                and x.get("url")
            ]
            combined.sort(key=lambda x: x.get("height") or 0, reverse=True)
            if combined:
                target = combined[0]["url"]
        if not target:
            for f in formats:
                if f.get("vcodec") not in (None, "none") and f.get("url"):
                    target = f["url"]
                    break

    return target or None


class handler(BaseHTTPRequestHandler):
    def _redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(b"")

    def _error(self, msg, status=400):
        body = json.dumps({"error": msg}, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        url = (qs.get("u") or [""])[0].strip()
        fmt = (qs.get("q") or ["best"])[0].strip()

        if not url.startswith(("http://", "https://")):
            self._error("رابط غير صالح.", 400)
            return

        target = get_redirect_url(url, fmt)
        if not target:
            self._error("تعذر تجهيز التحميل. أعد المحاولة.", 422)
            return

        self._redirect(target)

    def log_message(self, format, *args):
        pass
