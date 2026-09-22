/* =========================================================
   تحميل_لدينا - الجافاسكربت الرئيسي
   ========================================================= */

// إعداد نقطة الـ API (اتركه فارغًا لوضع العرض التجريبي)
// عند تشغيل server.py استخدم: '/api/info'
const API_ENDPOINT = '/api/info';

document.addEventListener('DOMContentLoaded', () => {

    /* ---------- قائمة الموبايل ---------- */
    const navToggle = document.getElementById('navToggle');
    const mainNav = document.getElementById('mainNav');

    if (navToggle && mainNav) {
        navToggle.addEventListener('click', () => {
            mainNav.classList.toggle('open');
        });

        mainNav.querySelectorAll('a').forEach(link => {
            link.addEventListener('click', () => mainNav.classList.remove('open'));
        });
    }

    /* ---------- أداة التحميل ---------- */
    const urlInput = document.getElementById('videoUrl');
    const downloadBtn = document.getElementById('downloadBtn');
    const resultBox = document.getElementById('result');

    if (downloadBtn) {
        downloadBtn.addEventListener('click', startDownload);
        urlInput.addEventListener('keydown', e => {
            if (e.key === 'Enter') startDownload();
        });
    }

    async function startDownload() {
        const url = urlInput.value.trim();

        if (!url) {
            showError('الصق رابط الفيديو الأول.');
            return;
        }

        if (!isValidUrl(url)) {
            showError('الرابط غير صحيح. تأكد إنه رابط يوتيوب أو فيسبوك كامل.');
            return;
        }

        if (!isSupported(url)) {
            showError('الرابط لمنصة غير مدعومة. الموقع يدعم يوتيوب وفيسبوك وإنستغرام وتيك توك.');
            return;
        }

        setLoading(true);
        resultBox.hidden = true;
        resultBox.innerHTML = '';

        try {
            let data;

            if (API_ENDPOINT) {
                const res = await fetch(API_ENDPOINT, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url })
                });
                const payload = await res.json().catch(() => ({}));
                if (!res.ok || payload.error) {
                    throw new Error(payload.error || 'فشل الاتصال بالخادم.');
                }
                data = payload;
                data.source_url = data.source_url || url;
            } else {
                // وضع العرض: نحاكي رد السيرفر لعرض الواجهة
                await delay(1200);
                data = demoResponse(url);
            }

            renderResult(data);
        } catch (err) {
            showError(err.message || 'حصل خطأ أثناء جلب الفيديو. جرّب رابط تاني.');
        } finally {
            setLoading(false);
        }
    }

    /* ---------- عرض النتيجة ---------- */
    function renderResult(data) {
        let html = '';

        html += `
            <div class="result-card">
                ${data.thumbnail ? `<img class="result-thumb" src="${escapeHtml(data.thumbnail)}" alt="صورة الفيديو" loading="lazy">` : ''}
                <div class="result-info">
                    <div class="result-title">${escapeHtml(data.title || 'فيديو بدون عنوان')}</div>
                    <div class="result-meta">${escapeHtml(data.platform || '')} ${data.duration ? '· ' + escapeHtml(data.duration) : ''}</div>
                </div>
            </div>`;

        if (data.formats && data.formats.length) {
            const src = encodeURIComponent(data.source_url || urlInput.value.trim());
            html += '<div class="quality-list">';
            data.formats.forEach(f => {
                const isAudio = f.type === 'audio';
                // نمرر دائمًا عبر /api/file (بث مع الترويسات الصحيحة — مطلوب لتيك توك)
                const href = `/api/file?u=${src}&q=${encodeURIComponent(f.format_id || 'best')}`;
                html += `
                    <div class="quality-row">
                        <span class="quality-label">${escapeHtml(f.label)}</span>
                        <a class="btn-q ${isAudio ? 'mp3' : ''}" href="${escapeHtml(href)}" target="_blank" rel="noopener nofollow" download>
                            ${isAudio ? 'MP3' : 'تنزيل'}
                        </a>
                    </div>`;
            });
            html += '</div>';
            html += '<div class="result-note">اختار الجودة المناسبة وهيتنزّل مباشرة من المصدر.</div>';
        } else {
            html += '<div class="result-error">مفيش روابط تحميل متاحة للفيديو ده.</div>';
        }

        resultBox.innerHTML = html;
        resultBox.hidden = false;
        resultBox.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    function showError(msg) {
        resultBox.innerHTML = `<div class="result-error">${escapeHtml(msg)}</div>`;
        resultBox.hidden = false;
    }

    function setLoading(loading) {
        downloadBtn.disabled = loading;
        const btnText = downloadBtn.querySelector('.btn-text');
        const spinner = downloadBtn.querySelector('.btn-spinner');
        if (btnText) btnText.hidden = loading;
        if (spinner) spinner.hidden = !loading;
    }

    /* ---------- أدوات مساعدة ---------- */
    function isValidUrl(str) {
        try {
            const u = new URL(str);
            return u.protocol === 'http:' || u.protocol === 'https:';
        } catch {
            return false;
        }
    }

    function isSupported(str) {
        const s = str.toLowerCase();
        return s.includes('youtube.com') || s.includes('youtu.be') ||
               s.includes('facebook.com') || s.includes('fb.watch') ||
               s.includes('instagram.com') || s.includes('tiktok.com');
    }

    function demoResponse(url) {
        let platform = 'فيديو';
        const s = url.toLowerCase();

        if (s.includes('youtube') || s.includes('youtu.be')) platform = 'YouTube';
        else if (s.includes('facebook') || s.includes('fb.watch')) platform = 'Facebook';
        else if (s.includes('instagram')) platform = 'Instagram';
        else if (s.includes('tiktok')) platform = 'TikTok';

        return {
            title: 'تم ربط الفيديو بنجاح — واجهة تجريبية',
            platform,
            duration: '04:32',
            thumbnail: '',
            formats: [
                { label: 'فيديو MP4 — 1080p (Full HD)', type: 'video', url: '#' },
                { label: 'فيديو MP4 — 720p (HD)', type: 'video', url: '#' },
                { label: 'فيديو MP4 — 480p', type: 'video', url: '#' },
                { label: 'صوت MP3 — 320kbps', type: 'audio', url: '#' }
            ]
        };
    }

    function delay(ms) { return new Promise(r => setTimeout(r, ms)); }

    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    /* ---------- بانر الموافقة على الكوكيز ---------- */
    const banner = document.getElementById('consentBanner');
    const acceptBtn = document.getElementById('consentAccept');
    const declineBtn = document.getElementById('consentDecline');

    if (banner) {
        const consent = localStorage.getItem('cookie_consent');
        if (!consent) {
            banner.hidden = false;
        }

        acceptBtn?.addEventListener('click', () => {
            localStorage.setItem('cookie_consent', 'accepted');
            banner.hidden = true;
            loadAds();
        });

        declineBtn?.addEventListener('click', () => {
            localStorage.setItem('cookie_consent', 'declined');
            banner.hidden = true;
        });

        // لو المستخدم وافق قبل كده، حمّل الإعلانات
        if (consent === 'accepted') loadAds();
    }

    function loadAds() {
        if (typeof adsbygoogle === 'undefined' && !window.adsbygoogle) return;
        document.querySelectorAll('ins.adsbygoogle').forEach(ins => {
            try {
                (adsbygoogle = window.adsbygoogle || []).push({});
            } catch (e) { /* تجاهل */ }
        });
    }

    /* ---------- تفعيل سكربت AdSense ---------- */
    (function loadAdsenseScript() {
        if (localStorage.getItem('cookie_consent') !== 'accepted') return;
        const script = document.createElement('script');
        script.async = true;
        script.crossOrigin = 'anonymous';
        script.src = 'https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-XXXXXXXXXXXXXXXX';
        document.head.appendChild(script);
    })();

});
