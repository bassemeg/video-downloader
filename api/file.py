"""
Vercel Serverless — تحميل الملف
GET /api/file?u=<video_url>&q=<format_id>

- يوتيوب: يمر عبر Cobalt الخارجي (COBALT_API_URL) ثم نبث الرابط للمستخدم.
- باقي المنصات: yt-dlp محليًا ثم بث الملف المؤقت (نفس السلوك القديم).
"""
import json
import os
import re
import tempfile
import urllib.request
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote

import yt_dlp

try:
    import imageio_ffmpeg
    _FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    _FFMPEG = None

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def is_youtube_url(url):
    """يتأكد إن الرابط من يوتيوب (يشمل youtube.com, youtu.be, m.youtube.com, music.youtube.com)."""
    s = url.lower()
    return (
        "youtube.com" in s
        or "youtu.be" in s
        or "m.youtube.com" in s
        or "music.youtube.com" in s
    )


def _cobalt_request(url, extra_body=None):
    """يطلب Cobalt ويعيد (status, download_url, filename, error_msg)."""
    import urllib.error

    cobalt_base = os.environ.get("COBALT_API_URL", "").strip()
    if not cobalt_base:
        return None, None, None, "COBALT_API_URL غير مضبوط."

    body = {"url": url}
    if extra_body:
        body.update(extra_body)

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        cobalt_base.rstrip("/") + "/",
        data=data,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": BROWSER_UA,
        },
        method="POST",
    )

    try:
        resp = urllib.request.urlopen(req, timeout=30)
        raw = resp.read().decode("utf-8", errors="replace")
        result = json.loads(raw)
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")
            err_json = json.loads(err_body)
            return None, None, None, err_json.get("error", {}).get("message", str(e))
        except Exception:
            return None, None, None, f"Cobalt HTTP {e.code}"
    except urllib.error.URLError as e:
        return None, None, None, f"Cobalt connection error: {e.reason}"
    except Exception as e:
        return None, None, None, f"Cobalt error: {type(e).__name__}: {str(e)[:200]}"

    status = result.get("status")
    if status in ("tunnel", "redirect"):
        dl_url = result.get("url", "")
        filename = result.get("filename", "")
        return status, dl_url, filename, None

    err_obj = result.get("error") or {}
    msg = ""
    if isinstance(err_obj, dict):
        msg = err_obj.get("message") or err_obj.get("code") or ""
    elif isinstance(err_obj, str):
        msg = err_obj
    if not msg:
        msg = str(result.get("status", "unknown error"))
    return None, None, None, f"Cobalt: {msg}"


def _cobalt_params_for_format(fmt):
    """يحول format_id القادم من info.py إلى body يناسب Cobalt."""
    # yt_1080 / yt_720 / yt_mp3
    if fmt == "yt_1080":
        return {"videoQuality": "1080"}
    if fmt == "yt_720":
        return {"videoQuality": "720"}
    if fmt == "yt_mp3":
        return {"downloadMode": "audio", "audioFormat": "mp3"}
    # fallback: أفضل جودة
    return {"videoQuality": "max"}


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
            fid = best_audio.get("format_id")
            return f"{fid}[ext=m4a]/{fid}/bestaudio[ext=m4a]/bestaudio/best"
        return "bestaudio[ext=m4a]/bestaudio/best"

    # مطابقة format_id مباشرة
    target = None
    for f in formats:
        fid = f.get("format_id") or ""
        if fid == fmt or fid.startswith(fmt.split("+")[0]):
            target = f
            break

    if target:
        has_v = target.get("vcodec") not in (None, "none")
        has_a = target.get("acodec") not in (None, "none")
        tid = target.get("format_id")
        if has_v and has_a:
            return tid
        if has_v and not has_a and _FFMPEG:
            return f"{tid}+bestaudio/{tid}/bestvideo+bestaudio/best"
        return tid

    # أفضل فيديو+صوت مدمج
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

    # فيديو DASH + دمج
    dash = [
        f for f in formats
        if f.get("vcodec") not in (None, "none")
        and f.get("acodec") in (None, "none")
        and f.get("url")
        and f.get("height")
    ]
    if dash:
        dash.sort(key=lambda x: x.get("height") or 0, reverse=True)
        fid = dash[0].get("format_id")
        if fid and _FFMPEG:
            return f"{fid}+bestaudio/{fid}/best"

    # فيديو فقط
    for f in formats:
        if f.get("vcodec") not in (None, "none") and f.get("url"):
            fid = f.get("format_id")
            if fid:
                return fid

    return "best"


def _extract_info(url, extractor_args=None):
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
    if extractor_args:
        info_opts["extractor_args"] = extractor_args
    with yt_dlp.YoutubeDL(info_opts) as ydl:
        return ydl.extract_info(url, download=False)


def _download_youtube_cobalt(url, fmt):
    """يوتيوب عبر Cobalt: يرجع (tunnel_url, filename, error)."""
    params = _cobalt_params_for_format(fmt)
    status, dl_url, filename, err = _cobalt_request(url, params)
    if err:
        return None, None, err
    if not dl_url:
        return None, None, "Cobalt لم يرجع رابط تحميل."
    return dl_url, filename, None


def _download(url, fmt):
    """باقي المنصات (yt-dlp محليًا): يحمّل لملف مؤقت ويعيد (path, title, ext, tmpdir)."""
    tmpdir = tempfile.mkdtemp(prefix="vd_")
    outtmpl = os.path.join(tmpdir, "out.%(ext)s")

    attempts = [None]
    info = None
    for args in attempts:
        try:
            info = _extract_info(url, args)
            break
        except Exception:
            continue

    if info is None:
        raise RuntimeError("extract_failed")

    selector = _pick_format(fmt, info.get("formats") or [])
    title = info.get("title") or "video"

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

    if _FFMPEG:
        dl_opts["ffmpeg_location"] = _FFMPEG
        dl_opts["merge_output_format"] = "mp4"

    if fmt in ("mp3", "audio"):
        if _FFMPEG:
            dl_opts["format"] = "bestaudio/best"
            dl_opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
        else:
            dl_opts["format"] = "bestaudio[ext=m4a]/bestaudio/best"

    last_exc = None
    for args in attempts:
        try:
            opts = dict(dl_opts)
            if args:
                opts["extractor_args"] = args
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            last_exc = None
            break
        except Exception as e:
            last_exc = e
            continue

    if last_exc is not None:
        raise last_exc

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

    def _proxy_youtube(self, url, fmt):
        """يوتيوب: يحصل على tunnel من Cobalt ثم يحوّل المتصفح إليه (302).

        Cobalt tunnel مصمم ليُفتح مباشرة من متصفح المستخدم،
        والبث عبر Vercel كان يرجع محتوى فارغًا.
        """
        tunnel_url, filename, err = _download_youtube_cobalt(url, fmt)
        if err:
            self._error(err, 422)
            return

        # 302 redirect — المتصفح يفتح الرابط مباشرة
        self.send_response(302)
        self.send_header("Location", tunnel_url)
        self.send_header("Content-Length", "0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def _proxy_local_file(self, path, title, ext, tmpdir):
        """باقي المنصات: بث الملف المؤقت ثم التنظيف."""
        try:
            filename = _safe_filename(title, ext)
            size = os.path.getsize(path)

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

            with open(path, "rb") as fp:
                while True:
                    chunk = fp.read(64 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except Exception:
            pass
        finally:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
                if tmpdir and os.path.isdir(tmpdir):
                    os.rmdir(tmpdir)
            except Exception:
                pass

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        url = (qs.get("u") or [""])[0].strip()
        fmt = (qs.get("q") or ["best"])[0].strip()

        if not url.startswith(("http://", "https://")):
            self._error("رابط غير صالح.", 400)
            return

        # يوتيوب → Cobalt
        if is_youtube_url(url):
            self._proxy_youtube(url, fmt)
            return

        # باقي المنصات → yt-dlp محليًا (نفس السلوك القديم تمامًا)
        path = None
        tmpdir = None
        try:
            path, title, ext, tmpdir = _download(url, fmt)
        except Exception:
            self._error("تعذر تجهيز التحميل. أعد المحاولة.", 422)
            return

        self._proxy_local_file(path, title, ext, tmpdir)

    def log_message(self, format, *args):
        pass
