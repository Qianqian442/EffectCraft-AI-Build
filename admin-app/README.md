# Ae账号管理（云端版）

该 APK 是独立的管理员客户端，不再把管理手机当作局域网服务器。账号数据保存在 Cloudflare D1，接口由 Cloudflare Workers 提供。

## 首次配置

1. 在 Cloudflare Worker 部署完成后，取得实际 HTTPS 地址，格式为 `https://ae-cloud-account-api.<账户子域名>.workers.dev`。
2. 打开「Ae账号管理」，在「服务器地址」填写该完整 HTTPS 地址。
3. 管理员账号固定为 `admin`；密码使用 Cloudflare Worker 的 `ADMIN_PASSWORD` Secret。
4. 登录后可以搜索账号、查看资料、封禁和解禁。

## 封禁与解禁通知

- 管理员提交封禁/解禁后，云端先立即更新 D1 状态。
- 云端随后向该账号所有在线 Ae 会话推送一次 WebSocket 状态变化事件。
- 在线 Ae 收到事件后会请求一次 `GET /v1/me` 核验；核验为封禁时立即锁定，解禁时恢复。
- 离线、断网或被 Android 挂起的 Ae 无法保证立即收到推送；重新联网/打开 Ae 时会再次核验。

## 每日额度

- 管理员端登录、搜索、查看资料、封禁/解禁会产生云端请求。
- Ae 每次启动只核验一次；登录、注册、资料修改分别按用户操作请求。
- 正常剪辑、导出和本地 AI 运算不会访问这个账号 Worker。
- Worker、D1 和 Durable Objects 都有免费层使用上限；额度以 Cloudflare 控制台实时显示为准，不能保证永久免费。

## 安全

- 管理接口必须通过 HTTPS 访问。
- 不要把 `ADMIN_PASSWORD`、`JWT_SECRET` 或 Cloudflare API Token 发到聊天或提交到 GitHub 源码。
- 管理设备无需保持开机供普通用户连接，也不需要和用户处于同一个 Wi-Fi。
