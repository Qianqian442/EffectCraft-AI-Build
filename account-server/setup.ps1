$ErrorActionPreference = "Stop"
$envPath = Join-Path $PSScriptRoot ".env"

# Select an active IPv4 interface with a default gateway (home Wi-Fi or Ethernet).
$homeLanIp = $null
try {
    $configs = Get-NetIPConfiguration | Where-Object {
        $_.NetAdapter.Status -eq "Up" -and $_.IPv4DefaultGateway -and $_.IPv4Address
    }
    foreach ($config in $configs) {
        $candidate = $config.IPv4Address | Where-Object {
            $_.IPAddress -and $_.IPAddress -notlike "169.254.*" -and $_.IPAddress -ne "127.0.0.1"
        } | Select-Object -First 1
        if ($candidate) {
            $homeLanIp = [string]$candidate.IPAddress
            break
        }
    }
} catch {
    throw "无法读取本机局域网 IPv4 地址。请确认 Windows 网络服务正常。"
}
if (-not $homeLanIp) {
    throw "没有找到已连接路由器的 IPv4 网络。请先连接家庭 Wi-Fi，再重新运行。"
}
$octets = @($homeLanIp.Split(".") | ForEach-Object { [int]$_ })
if ($octets.Count -ne 4) {
    throw "检测到的地址不是有效 IPv4 地址：$homeLanIp"
}
$a = $octets[0]
$b = $octets[1]
$isPrivateLan = ($a -eq 10) -or
    ($a -eq 192 -and $b -eq 168) -or
    ($a -eq 172 -and $b -ge 16 -and $b -le 31) -or
    ($a -eq 100 -and $b -ge 64 -and $b -le 127)
if (-not $isPrivateLan) {
    throw "检测到的地址不是家庭/私有局域网 IPv4（$homeLanIp）。为避免暴露公网，请检查当前网络后重试。"
}

if (Test-Path $envPath) {
    $lines = @(Get-Content $envPath)
    if ($lines -match '^HOME_LAN_IP=') {
        $lines = @($lines | ForEach-Object {
            if ($_ -match '^HOME_LAN_IP=') { "HOME_LAN_IP=$homeLanIp" } else { $_ }
        })
    } else {
        $lines += "HOME_LAN_IP=$homeLanIp"
    }
    [System.IO.File]::WriteAllLines($envPath, $lines, [System.Text.UTF8Encoding]::new($false))
    Write-Host "已将账号服务器绑定到当前局域网地址：$homeLanIp"
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

$salt = New-Object byte[] 16
$rng.GetBytes($salt)
$kdf = [System.Security.Cryptography.Rfc2898DeriveBytes]::new(
    $adminPassword, $salt, 310000, [System.Security.Cryptography.HashAlgorithmName]::SHA256
)
$adminHash = $kdf.GetBytes(32)
$saltB64 = [Convert]::ToBase64String($salt)
$hashB64 = [Convert]::ToBase64String($adminHash)
$content = @"
JWT_SECRET=$secret
ADMIN_USERNAME=admin
ADMIN_PASSWORD_HASH=pbkdf2-sha256:310000:$saltB64:$hashB64
HOME_LAN_IP=$homeLanIp
"@
[System.IO.File]::WriteAllText($envPath, $content, [System.Text.UTF8Encoding]::new($false))
Write-Host "已创建 .env。管理员密码以PBKDF2哈希保存；请不要把此文件上传或分享给他人。"
Write-Host "账号服务器只绑定当前局域网地址：$homeLanIp"
