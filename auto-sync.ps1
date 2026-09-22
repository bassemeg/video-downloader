# Auto-sync: يراقب التعديلات ويرفعها تلقائيًا
# شغّله: اضغط عليه مرتين (يبدأ المراقبة)
# لإيقافه: أغلق النافذة

$repo = "D:\ads3downloadtools"
$watchPaths = @("index.html", "css", "js", "pages", "api", "sw.js", "vercel.json", "requirements.txt", "ads.txt", "robots.txt", "sitemap.xml", "*.bat", "local_server.py")

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " Auto-sync started - watching for changes" -ForegroundColor Cyan
Write-Host " Press Ctrl+C or close window to stop" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

$lastRun = Get-Date

while ($true) {
    Start-Sleep -Seconds 5

    Set-Location $repo
    $status = git status --porcelain

    if ($status) {
        $now = Get-Date
        if (($now - $lastRun).TotalSeconds -ge 5) {
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Changes detected, pushing..." -ForegroundColor Yellow
            git add -A
            git -c core.safecrlf=false commit -m "Auto-sync: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" 2>&1 | Out-Null
            $push = git push 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Pushed OK -> Vercel deploying..." -ForegroundColor Green
            } else {
                Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Push failed: $push" -ForegroundColor Red
            }
            $lastRun = $now
        }
    }
}
