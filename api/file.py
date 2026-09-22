"""
Vercel Serverless — تحميل الملف عبر yt-dlp ثم بثه
GET /api/file?u=<video_url>&q=<format_id>

yt-dlp يتجاوز حجب TikTok/YouTube (TLS impersonation)؛
ثم نبث الملف المؤقت للمتصفح مع Content-Disposition.
"""
import json
import os
import re
import tempfile
import urllib.request
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote

import yt_dlp

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def _safe_filename(title, ext):
    keep = (
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        " ءأإآبتثجحخدذرزسشصضطظعغفقكلمنهوي"
    )
    name = "".join(c for c in title if c in keep).strip() or "video"
    name = name[:70]
    if not name.lower().endswith("." + ext.lower()):
        name = name + "." + ext
    return name


def _pick_format(fmt, formats):
    """يعيد format selector المناسب لـ yt-dlp."""
    if fmt in ("mp3", "audio"):
        best_audio = None
        for f in formats:
            if (f.get("acodec") not in (None, "none")
                    and f.get("vcodec") in (None, "none")):
                best_audio = f
                if (f.get("ext") or "") == "mp3":
                    break
        if best_audio:
            return best_audio.get("format_id")
        return "bestaudio/best"

    # مطابقة format_id مباشرة
    for f in formats:
        fid = f.get("format_id") or ""
        if fid == fmt or fid.startswith(fmt.split("+")[0]):
            return fid

    # أفضل فيديو+صوت بدون دمج (FFmpeg غير متوفر على Vercel)
    combined = [
        f for f in formats
        if f.get("vcodec") not in (None, "none")
        and f.get("acodec") not in (None, "none")
        and f.get("url")
    ]
    if combined:
        combined.sort(key=lambda x: x.get("height") or 0, reverse=True)
        fid = combined[0].get("format_id")
        if fid:
            return fid

    # فيديو فقط
    for f in formats:
        if f.get("vcodec") not in (None, "none") and f.get("url"):
            fid = f.get("format_id")
            if fid:
                return fid

    return "best"


def _download(url, fmt):
    """يحمّل الملف إلى مسار مؤقت ويعيد (path, title, ext)."""
    tmpdir = tempfile.mkdtemp(prefix="vd_")
    outtmpl = os.path.join(tmpdir, "out.%(ext)s")

    # استخراج أولاً لتحديد الصيغة
    info_opts = {
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
    with yt_dlp.YoutubeDL(info_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    selector = _pick_format(fmt, info.get("formats") or [])
    title = info.get("title") or "video"

    # تحديد الامتداد المتوقع لاسم الملف
    if fmt in ("mp3", "audio"):
        ext_guess = "mp3"
    else:
        ext_guess = "mp4"
        for f in info.get("formats") or []:
            if (f.get("format_id") or "") == selector:
                ext_guess = f.get("ext") or "mp4"
                break

    dl_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "outtmpl": outtmpl,
        "format": selector,
        "socket_timeout": 30,
        "retries": 2,
        "http_headers": {
            "User-Agent": BROWSER_UA,
            "Referer": "https://www.tiktok.com/",
        },
    }

    if fmt in ("mp3", "audio"):
        # بدون FFmpeg: ننزّل أفضل صوت فقط (m4a/aac عادةً)
        dl_opts["format"] = "bestaudio[ext=m4a]/bestaudio/best"

    with yt_dlp.YoutubeDL(dl_opts) as ydl:
        ydl.download([url])

    # إيجاد الملف الناتج
    path = None
    for fn in os.listdir(tmpdir):
        if fn.startswith("out."):
            path = os.path.join(tmpdir, fn)
            ext_guess = fn.split(".", 1)[-1] or ext_guess
            break

    if not path or not os.path.exists(path):
        raise RuntimeError("download_failed")

    return path, title, ext_guess, tmpdir


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

        path = None
        tmpdir = None
        try:
            path, title, ext, tmpdir = _download(url, fmt)
        except Exception:
            self._error("تعذر تجهيز التحميل. أعد المحاولة.", 422)
            return

        try:
            filename = _safe_filename(title, ext)
            size = os.path.getsize(path)

            # نوع المحتوى
            if ext in ("m4a", "aac", "mp3"):
                ctype = "audio/mpeg" if ext == "mp3" else "audio/mp4"
            elif ext in ("webm",):
                ctype = "video/webm"
            else:
                ctype = "video/mp4"

            fname_ascii = filename.encode("ascii", "ignore").decode("ascii") or "video.mp4"

            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size))
            self.send_header(
                "Content-Disposition",
                f"attachment; filename=\"{fname_ascii}\"; filename*=UTF-8''{quote(filename)}",
            )
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

            # بث الملف على دفعات
            with open(path, "rb") as fp:
                while True:
                    chunk = fp.read(64 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except Exception:
            pass  # المتصفح أغلق الاتصال
        finally:
            # تنظيف الملفات المؤقتة
            try:
                if path and os.path.exists(path):
                    os.remove(path)
                if tmpdir and os.path.isdir(tmpdir):
                    os.rmdir(tmpdir)
            except Exception:
                pass

    def log_message(self, format, *args):
        pass
