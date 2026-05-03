# DABEE_RUN dev server stop
$conn = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn -and $conn.OwningProcess -gt 4) {
    try {
        Stop-Process -Id $conn.OwningProcess -Force -ErrorAction Stop
        Write-Host "✅ :8000 프로세스 종료 (PID=$($conn.OwningProcess))" -ForegroundColor Green
    } catch {
        Write-Host "⚠️ 종료 실패: $($_.Exception.Message)" -ForegroundColor Red
    }
} else {
    Write-Host "ℹ️ :8000 LISTEN 프로세스 없음" -ForegroundColor Gray
}
