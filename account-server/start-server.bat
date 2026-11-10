@echo off
cd /d "%~dp0"
if not exist ".env" (
  powershell -NoProfile -ExecutionPolicy Bypass -File ".\setup.ps1"
  if errorlevel 1 pause & exit /b 1
)
docker compose up -d --build
if errorlevel 1 (
  echo 账号服务器启动失败。请确认 Docker Desktop 已安装并正在运行。
  pause
  exit /b 1
)
echo.
echo EffectCraft 家庭账号服务器已启动，端口：8787
for /f "tokens=1,2 delims==" %%A in ('findstr /b "HOME_LAN_IP=" ".env"') do set HOME_LAN_IP=%%B
echo 家庭局域网服务器地址：http://%HOME_LAN_IP%:8787
echo 手机必须连接同一个家庭 Wi-Fi；不要在路由器上设置公网端口转发。
pause
