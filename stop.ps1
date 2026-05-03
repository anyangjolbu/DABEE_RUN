$conn = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn) {
    Stop-Process -Id $conn.OwningProcess -Force
    Write-Host "✅ :8000 프로세스 종료 (PID=$($conn.OwningProcess))" -ForegroundColor Green
} else {
    Write-Host "ℹ️ :8000 점유 프로세스 없음" -ForegroundColor Gray
}
