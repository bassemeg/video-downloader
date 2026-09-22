"""
Vercel Serverless — جلب معلومات الفيديو
POST /api/info  { "url": "..." }

الشكل المدعوم: class handler(BaseHTTPRequestHandler)
"""
import json
import re
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import yt_dlp

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def build_opts(extra=None):
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
    if extra:
        opts.update(extra)
    return opts


def _is_youtube(url):
    s = url.lower()
    return "youtube.com" in s or "youtu.be" in s


def _try_extract(url, extractor_args=None):
    extra = {}
    if extractor_args:
        extra["extractor_args"] = extractor_args
    with yt_dlp.YoutubeDL(build_opts(extra)) as ydl:
        return ydl.extract_info(url, download=False)


def extract_formats(url):
    """يجلب معلومات الفيديو ويحوّلها لاستجابة JSON."""
    info = None
    last_err = None

    # على Vercel IP محجوب أحيانًا — نجرب عملاء متتاليين
    attempts = [None]
    if _is_youtube(url):
        attempts += [
            {"youtube": {"player_client": ["android"]}},
            {"youtube": {"player_client": ["tv_embedded"]}},
            {"youtube": {"player_client": ["android_embedded"]}},
            {"youtube": {"player_client": ["ios"]}},
        ]

    for args in attempts:
        try:
            info = _try_extract(url, args)
            last_err = None
            break
        except yt_dlp.utils.DownloadError as e:
            last_err = e
            continue
        except Exception as e:
            last_err = e
            continue

    if info is None:
        msg = str(last_err) if last_err else ""
        if "Private" in msg:
            return None, "الفيديو خاص أو غير متاح.", 422
        if "Video unavailable" in msg or "Video not available" in msg:
            return None, "الفيديو غير متاح أو محذوف.", 422
        if "Unsupported URL" in msg:
            return None, "رابط غير مدعوم. تأكد إنه رابط فيديو كامل.", 422
        if "Sign in" in msg or "login" in msg.lower() or "not a bot" in msg:
            return None, "تعذر الوصول للفيديو الآن. أعد المحاولة بعد لحظات.", 422
        if "Unexpected response" in msg or "webpage request" in msg:
            return None, "المنصة رفضت الطلب مؤقتًا. أعد المحاولة بعد لحظات.", 422
        return None, "تعذر جلب الفيديو. جرّب رابطًا آخر.", 422

    title = info.get("title") or "فيديو بدون عنوان"
    duration = info.get("duration")
    duration_str = ""
    if duration:
        m, s = divmod(int(duration), 60)
        h, m = divmod(m, 60)
        duration_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    thumb = info.get("thumbnail") or ""
    if not thumb and info.get("thumbnails"):
        thumb = info["thumbnails"][-1].get("url", "")

    formats = []
    seen = set()
    audio_url = ""

    for f in info.get("formats", []):
        height = f.get("height")
        vcodec = f.get("vcodec")
        acodec = f.get("acodec")
        has_video = vcodec not in (None, "none")
        has_audio = acodec not in (None, "none")
        protocol = (f.get("protocol") or "")
        ext = f.get("ext") or ""
        fid = f.get("format_id", "")
        furl = f.get("url") or ""

        if "m3u8" in protocol or ext in ("m3u8", "mpd") or "dash" in protocol:
            continue

        # فيديو: مدمج أو DASH (ندمج الصوت في file.py بـ FFmpeg)
        if has_video and height and height >= 360 and furl:
            width = f.get("width")
            q = min(height, width) if width else height
            m = re.search(r"(\d{3,4})p", fid)
            if m:
                q = int(m.group(1))
            key = f"v{q}"
            if key in seen:
                continue
            seen.add(key)
            formats.append({
                "label": f"فيديو MP4 — {q}p",
                "type": "video",
                "quality": q,
                "format_id": fid,
                "direct_url": furl,
            })
            continue

        # فيسبوك: صيغ بدون height (hd/sd) وبدون codecs معلنة
        if not has_video and not has_audio and ext in ("mp4", "webm") and height is None and furl:
            qname = "HD" if fid.lower() == "hd" else "SD" if fid.lower() == "sd" else fid.upper()
            key = f"fb{fid}"
            if key in seen:
                continue
            seen.add(key)
            formats.append({
                "label": f"فيديو MP4 — {qname}",
                "type": "video",
                "quality": 720 if fid.lower() == "hd" else 480,
                "format_id": fid,
                "direct_url": furl,
            })
            continue

        # صوت فقط
        if (not has_video and has_audio and not audio_url and furl
                and ext in ("mp3", "m4a", "mp4", "webm", "aac")):
            audio_url = furl

    if audio_url:
        formats.append({
            "label": "صوت — MP3 / M4A",
            "type": "audio",
            "quality": 0,
            "format_id": "mp3",
            "direct_url": audio_url,
        })
    else:
        for f in info.get("formats", []):
            if (f.get("acodec") not in (None, "none")
                    and f.get("vcodec") in (None, "none")
                    and f.get("url")):
                formats.append({
                    "label": "صوت — MP3 / M4A",
                    "type": "audio",
                    "quality": 0,
                    "format_id": "mp3",
                    "direct_url": f["url"],
                })
                break

    formats.sort(key=lambda x: x.get("quality") or 0, reverse=True)

    if not formats:
        return None, "مفيش جودات متاحة لهذا الفيديو.", 422

    return {
        "title": title,
        "duration": duration_str,
        "thumbnail": thumb,
        "platform": _platform(url),
        "formats": formats,
        "source_url": url,
    }, None, 200


def _platform(url):
    s = url.lower()
    if "youtube" in s or "youtu.be" in s:
        return "YouTube"
    if "facebook" in s or "fb.watch" in s:
        return "Facebook"
    if "instagram" in s:
        return "Instagram"
    if "tiktok" in s:
        return "TikTok"
    return "فيديو"


class handler(BaseHTTPRequestHandler):
    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw.decode("utf-8", errors="replace") or "{}")
        except Exception:
            self._send_json({"error": "طلب غير صالح."}, 400)
            return

        url = (data.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            self._send_json({"error": "الرابط غير صحيح."}, 400)
            return

        payload, err, status = extract_formats(url)
        if err:
            self._send_json({"error": err}, status)
        else:
            self._send_json(payload, 200)

    def do_GET(self):
        self._send_json({"error": "استخدم POST على /api/info"}, 405)

    def log_message(self, format, *args):
        pass  # تقليل السجلات على Vercel
