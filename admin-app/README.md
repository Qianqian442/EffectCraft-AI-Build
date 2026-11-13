# EffectCraft 账号管理版 APK

此 APK 是独立的管理员界面。它与主 EffectCraft APK 共用同一个 Cloudflare Workers + D1 HTTPS 账号服务；云端数据库是账号注册、登录、资料、封禁和解禁的统一数据源。

## 异地连接方式

- 主 APK 和管理版都通过 HTTPS 访问同一个 `AE_ACCOUNT_API_URL`。
- 两台手机可以处于不同城市、不同 Wi-Fi，或分别使用 Wi-Fi 和移动数据；不需要管理员手机一直开机，也不需要输入局域网 IP 或 P2P 节点 ID。
- 账号操作需要可访问 Cloudflare `workers.dev` 域名的网络。若所在运营商或 VPN 无法访问该域名，客户端会显示连接失败，不会伪装为已同步。
- 主 APK 在启动时验证一次账号状态；封禁/解禁通过云端 WebSocket 实时通知在线客户端。没有 10 秒轮询。离线期间的状态在设备重新连网或下次启动时重新核验。

## 管理员登录

管理员用户名固定为 `admin`，密码由 Cloudflare Worker 的 `ADMIN_PASSWORD` Secret 设置。管理版登录后使用短时 JWT 管理令牌，执行：

- 查询账号列表和个人资料
- 封禁账号
- 单独解除封禁

普通用户 APK 不包含管理员入口或封禁/解禁控件。请勿将管理员密码、JWT Secret 或 Cloudflare API Token 发到聊天或提交到源码。

## GitHub Actions 配置

主 APK 和管理版构建都要求仓库 Actions Variable：

- `AE_ACCOUNT_API_URL`：部署成功后自动写入，格式为 `https://ae-cloud-account-api.<你的 workers.dev 子域>.workers.dev`。

云端部署工作流要求以下三个 Repository Actions Secrets：

- `CLOUDFLARE_API_TOKEN`：Cloudflare API Token，至少具备目标账号的 Workers Scripts Edit 与 D1 Edit 权限。
- `JWT_SECRET`：至少 32 个字符的随机高强度密钥。
- `ADMIN_PASSWORD`：至少 12 个字符的私有管理员密码。

本项目 Cloudflare Account ID 已写在部署工作流中，D1 数据库 ID 已写在 `cloudflare-worker/wrangler.jsonc`。首次部署还需在 Cloudflare 控制台创建名为 `ae-cloud-account-api` 的空 Worker，并确认 `ae-accounts` D1 数据库存在。密钥只填在 GitHub Secrets 页面，不要粘贴到聊天。

## P2P 手机节点状态

管理版仍保留实验性手机节点代码，但节点发现/中继实验不承担账号数据库，也不是跨地区账号同步的依赖。异地账号互通由云端 HTTPS 服务负责。不要把局域网节点健康检查当成云端账号同步测试。
