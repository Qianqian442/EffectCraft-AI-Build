$ErrorActionPreference = "Stop"
$envPath = Join-Path $PSScriptRoot ".env"
if (Test-Path $envPath) {
    Write-Host "账号服务器配置已存在：$envPath"
    exit 0
}
Write-Host "首次配置 EffectCraft 家庭账号服务器。"
$adminPassword = Read-Host "设置管理员密码（至少12位，请记住，用于管理员APK登录）"
if ($adminPassword.Length -lt 12) {
    throw "管理员密码至少需要12位。"
}
$bytes = New-Object byte[] 48
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($bytes)
$secret = [Convert]::ToHexString($bytes)
$content = @"
JWT_SECRET=$secret
ADMIN_USERNAME=admin
ADMIN_PASSWORD=$adminPassword
"@
[System.IO.File]::WriteAllText($envPath, $content, [System.Text.UTF8Encoding]::new($false))
Write-Host "已创建 .env。请不要把此文件上传或分享给他人。"
