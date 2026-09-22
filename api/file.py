"""
Vercel Serverless — تحميل الملف عبر بث (stream)
GET /api/file?u=<video_url>&q=<format_id>

يجلب الرابط المباشر ثم يبث المحتوى مع الترويسات الصحيحة
(بديل عن 302 redirect الذي يُرفض من TikTok/YouTube).
"""
import json
import re
import urllib.request
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote, unquote

import yt_dlp

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def get_media_info(url, fmt):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "socket_timeout": 20,
        "http_headers": {
            "User-Agent": BROWSER_UA,
            "Referer": "https://www.tiktok.com/",
            "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
        },
    }

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    target = ""
    ext = "mp4"
    formats = info.get("formats") or []
    title = info.get("title") or "video"

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
        ext = (best or {}).get("ext") or "mp3"
    else:
        for f in formats:
            fid = f.get("format_id") or ""
            if fid == fmt or fid.startswith(fmt.split("+")[0]):
                if f.get("url"):
                    target = f["url"]
                    ext = f.get("ext") or "mp4"
                    break
        if not target:
            combined = [
                x for x in formats
                if x.get("vcodec") not in (None, "none")
                and x.get("acodec") not in (None, "none")
                and x.get("url")
            ]
            combined.sort(key=lambda x: x.get("height") or 0, reverse=True)
            if combined:
                target = combined[0]["url"]
                ext = combined[0].get("ext") or "mp4"
        if not target:
            for f in formats:
                if f.get("vcodec") not in (None, "none") and f.get("url"):
                    target = f["url"]
                    ext = f.get("ext") or "mp4"
                    break

    return target, title, ext


def safe_filename(title, ext):
    keep = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_ ءأإآبتثجحخدذرزسشصضطظعغفقكلمنهوي"
    name = "".join(c for c in title if c in keep).strip() or "video"
    name = name[:70]
    if not name.lower().endswith("." + ext.lower()):
        name = name + "." + ext
    return name


class handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

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

        try:
            media_url, title, ext = get_media_info(url, fmt)
        except Exception:
            self._error("تعذر تجهيز التحميل. أعد المحاولة.", 422)
            return

        if not media_url:
            self._error("لم أجد رابط تنزيل.", 422)
            return

        if ext not in ("mp4", "webm", "mkv", "mp3", "m4a", "aac"):
            ext = "mp3" if fmt in ("mp3", "audio") else "mp4"

        filename = safe_filename(title, ext)

        # جلب المحتوى مع ترويسات المتصفح (مهم لتيك توك)
        req = urllib.request.Request(media_url, headers={
            "User-Agent": BROWSER_UA,
            "Referer": "https://www.tiktok.com/",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
        })

        try:
            upstream = urllib.request.urlopen(req, timeout=55)
        except Exception:
            self._error("فشل الاتصال بمصدر الفيديو.", 502)
            return

        content_type = upstream.headers.get("Content-Type") or "application/octet-stream"
        content_length = upstream.headers.get("Content-Length")

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        if content_length:
            self.send_header("Content-Length", content_length)
        else:
            # بث بلا طول معروف
            self.send_header("Transfer-Encoding", "chunked")
        fname_ascii = filename.encode("ascii", "ignore").decode("ascii") or "video.mp4"
        self.send_header(
            "Content-Disposition",
            f"attachment; filename=\"{fname_ascii}\"; filename*=UTF-8''{quote(filename)}",
        )
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        chunked = not content_length

        try:
            while True:
                chunk = upstream.read(64 * 1024)
                if not chunk:
                    break
                if chunked:
                    self.wfile.write(f"{len(chunk):X}\r\n".encode())
                    self.wfile.write(chunk)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()
                else:
                    self.wfile.write(chunk)
                    self.wfile.flush()
            if chunked:
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
        except Exception:
            pass  # المتصفح أغلق الاتصال
        finally:
            try:
                upstream.close()
            except Exception:
                pass

    def log_message(self, format, *args):
        pass
