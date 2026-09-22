"""
سيرفر تحميل_لدينا - Flask + yt-dlp
شغّل: python server.py  ثم افتح http://localhost:8000
"""
import os
import re
import tempfile
import threading

from flask import Flask, request, jsonify, send_file, send_from_directory
import yt_dlp

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=BASE_DIR, static_url_path="")

# منع تنزيلات متزامنة كثيرة
DOWNLOAD_LOCK = threading.Lock()

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def build_opts(extra=None):
    """خيارات yt-dlp مع ترويسات المتصفح (مطلوبة لتيك توك)."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "http_headers": {
            "User-Agent": BROWSER_UA,
            "Referer": "https://www.tiktok.com/",
            "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
        },
    }
    if extra:
        opts.update(extra)
    return opts


@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/api/info", methods=["POST"])
def api_info():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()

    if not url.startswith(("http://", "https://")):
        return jsonify({"error": "الرابط غير صحيح."}), 400

    ydl_opts = build_opts({"skip_download": True})

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        if "Private" in msg or "خاصة" in msg:
            return jsonify({"error": "الفيديو خاص أو غير متاح."}), 422
        if "Video unavailable" in msg or "Video not available" in msg:
            return jsonify({"error": "الفيديو غير متاح أو محذوف."}), 422
        if "Unsupported URL" in msg:
            return jsonify({"error": "رابط غير مدعوم. تأكد إنه رابط فيديو كامل وليس صفحة رئيسية."}), 422
        if "Sign in" in msg or "login" in msg.lower() or "cookies" in msg.lower():
            return jsonify({"error": "الفيديو يحتاج تسجيل دخول أو محمي. جرّب رابطًا عامًا."}), 422
        if "Unexpected response" in msg or "webpage request" in msg:
            return jsonify({"error": "تيك توك رفض الطلب مؤقتًا. أعد المحاولة بعد لحظات."}), 422
        return jsonify({"error": "تعذر جلب الفيديو. جرّب رابطًا آخر."}), 422
    except Exception:
        return jsonify({"error": "خطأ غير متوقع في الخادم."}), 500

    title = info.get("title") or "فيديو بدون عنوان"
    duration = info.get("duration")
    duration_str = ""
    if duration:
        m, s = divmod(int(duration), 60)
        h, m = divmod(m, 60)
        duration_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    thumb = ""
    if info.get("thumbnail"):
        thumb = info["thumbnail"]
    elif info.get("thumbnails"):
        thumb = info["thumbnails"][-1].get("url", "")

    formats = []
    seen = set()

    for f in info.get("formats", []):
        height = f.get("height")
        vcodec = f.get("vcodec")
        acodec = f.get("acodec")
        has_video = vcodec not in (None, "none")
        has_audio = acodec not in (None, "none")
        protocol = (f.get("protocol") or "")
        ext = f.get("ext") or ""
        fid = f.get("format_id", "")

        # تخطي بث HLS/DASH غير القابل للدمج المباشر
        if "m3u8" in protocol or ext in ("m3u8", "mpd") or "dash" in protocol:
            continue

        # الحالة 1: فيديو بجودة محددة (يوتيوب / تيك توك)
        if has_video and height and height >= 360:
            # يوتيوب أفقي: 1920x1080 → 1080p
            # تيك توك عمودي: 540x1024 → 540p (نستخدم الأصغر)
            width = f.get("width")
            q = min(height, width) if width else height
            # تيك توك يكتب الجودة في format_id مثل h264_540p
            m = re.search(r"(\d{3,4})p", fid)
            if m:
                q = int(m.group(1))
            key = f"v{q}"
            if key in seen:
                continue
            seen.add(key)
            fmt_str = fid if has_audio else f"{fid}+bestaudio/best"
            formats.append({
                "label": f"فيديو MP4 — {q}p",
                "type": "video",
                "quality": q,
                "format_id": fmt_str,
            })
            continue

        # الحالة 2: فيسبوك — صيغ مدمجة بدون height (hd/sd)
        if not has_video and not has_audio and ext in ("mp4", "webm") and height is None:
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
            })
            continue

        # الحالة 3: فيديو بدون صوت بأي ارتفاع
        if has_video and not has_audio and height:
            key = f"v{height}"
            if key in seen:
                continue
            seen.add(key)
            formats.append({
                "label": f"فيديو MP4 — {height}p",
                "type": "video",
                "quality": height,
                "format_id": f"{fid}+bestaudio/best",
            })

    # ترتيب تنازلي
    formats.sort(key=lambda x: x.get("quality") or 0, reverse=True)
    # MP3 في الآخر
    formats.append({"label": "صوت MP3 — 320kbps", "type": "audio", "quality": 0, "format_id": "mp3"})

    return jsonify({
        "title": title,
        "duration": duration_str,
        "thumbnail": thumb,
        "platform": _platform(url),
        "formats": formats,
        "source_url": url,
    })


@app.route("/api/file")
def api_file():
    url = request.args.get("u", "")
    fmt = request.args.get("q", "best")

    if not url.startswith(("http://", "https://")):
        return jsonify({"error": "رابط غير صالح."}), 400

    tmp = tempfile.mkdtemp()

    if fmt == "mp3":
        out = os.path.join(tmp, "audio.%(ext)s")
        ydl_opts = build_opts({
            "format": "bestaudio/best",
            "outtmpl": out,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "320",
            }],
            "merge_output_format": "mp4",
        })
        ext = "mp3"
    else:
        out = os.path.join(tmp, "video.%(ext)s")
        if fmt in ("best", ""):
            fstr = "bestvideo*+bestaudio/best"
        elif "+" in fmt or "/" in fmt:
            # السلسلة جاهزة من /api/info (تنسيق + صوت)
            fstr = fmt
        else:
            fstr = f"{fmt}[ext=mp4]+bestaudio[ext=m4a]/{fmt}/bestvideo*+bestaudio/best"
        ydl_opts = build_opts({
            "format": fstr,
            "outtmpl": out,
            "merge_output_format": "mp4",
        })
        ext = "mp4"

    try:
        with DOWNLOAD_LOCK:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                path = ydl.prepare_filename(info)
                if fmt == "mp3":
                    path = os.path.splitext(path)[0] + ".mp3"
                elif not os.path.exists(path):
                    # امتداد مختلف بعد الدمج
                    base = os.path.splitext(path)[0]
                    for e in ("mp4", "mkv", "webm"):
                        if os.path.exists(base + "." + e):
                            path = base + "." + e
                            break

        safe_name = _safe_name(info.get("title") or "video") + "." + ext
        return send_file(path, as_attachment=True, download_name=safe_name)
    except Exception:
        return jsonify({"error": "فشل تنزيل الملف. جرّب جودة أخرى."}), 500


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


def _safe_name(name):
    keep = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_ ءأإآبتثجحخدذرزسشصضطظعغفقكلمنهوي"
    out = "".join(c for c in name if c in keep)
    return (out.strip() or "video")[:80]


if __name__ == "__main__":
    import webbrowser
    import threading as _threading

    def _open_browser():
        import time
        time.sleep(1.5)
        webbrowser.open("http://127.0.0.1:8000")

    _threading.Thread(target=_open_browser, daemon=True).start()
    print("=" * 50)
    print("  موقع تحميل_لدينا يعمل الآن")
    print("  افتح المتصفح على: http://127.0.0.1:8000")
    print("  أغلق هذه النافذة لإيقاف الموقع")
    print("=" * 50)
    app.run(host="127.0.0.1", port=8000, debug=False, threaded=True)
