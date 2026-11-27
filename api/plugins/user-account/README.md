# 用户账号管理（user-account）

为豪源站点添加一层本地账号密码保护，适合在个人电脑、局域网或公网部署时保护隐私内容。

## 功能

- 插件启用后，首次使用需要设置用户名、密码和**找回密码邮箱**
- 设置完成后，所有前端页面与 `/api` 接口都需要登录
- 登录后可在侧栏账号入口修改用户名、密码和找回密码邮箱
- 忘记密码时，可在登录页点击「忘记密码？」通过预留邮箱接收验证码并重置密码
- 使用本地 PBKDF2-SHA256 加盐哈希保存密码，密码不以明文落盘
- 登录态使用 HMAC 签名的 HttpOnly Cookie，默认 7 天有效
- 连续登录失败达到上限会锁定 5 分钟；锁定到期后重新计数，再次达到上限会再次锁定 5 分钟
- 失败次数上限可在「账号与安全」中配置（1-20 次，默认 5 次）
- 登录成功后会清零失败次数

## 使用

1. 在豪源前端「插件」页启用「用户账号管理」
2. 首次启用会弹出账号设置，设置用户名、密码和找回密码邮箱
3. 之后访问豪源任意页面会先进入登录页
4. 登录后在左下角账号入口可以修改账号信息，并配置邮件发送服务（SMTP）

## 找回密码与邮件服务

忘记密码时，在登录页点击「忘记密码？」，输入用户名或预留邮箱获取验证码，验证后即可设置新密码。验证码 10 分钟内有效，连续输错 5 次需重新获取，重新发送间隔 60 秒。

**用户只需要提供自己的找回邮箱，不需要、也不应该配置 SMTP。** 邮件发送属于部署者（开发者）负责的服务器基础设施，通过环境变量注入，不写入数据库、不进入网页设置、不提交到 Git。

部署者在服务器上配置（以 systemd 为例）：

1. 新建受保护的环境文件 `/etc/hao-yuan/smtp.env`（权限 600）：

   ```bash
   sudo install -d -m 700 /etc/hao-yuan
   sudo tee /etc/hao-yuan/smtp.env >/dev/null <<'EOF'
   HAOYUAN_SMTP_HOST=smtp.example.com
   HAOYUAN_SMTP_PORT=465
   HAOYUAN_SMTP_USER=noreply@example.com
   HAOYUAN_SMTP_PASSWORD=your-app-password
   HAOYUAN_SMTP_FROM=noreply@example.com
   HAOYUAN_SMTP_SECURITY=ssl
   EOF
   sudo chmod 600 /etc/hao-yuan/smtp.env
   ```

2. 在服务的 systemd unit 中引入该文件：

   ```ini
   [Service]
   EnvironmentFile=-/etc/hao-yuan/smtp.env
   ```

3. `systemctl daemon-reload && systemctl restart haoyuan`。

环境变量说明：

| 变量 | 说明 |
| --- | --- |
| `HAOYUAN_SMTP_HOST` | SMTP 服务器地址，例如 `smtp.example.com` |
| `HAOYUAN_SMTP_PORT` | 端口，默认 `465` |
| `HAOYUAN_SMTP_USER` | SMTP 用户名 |
| `HAOYUAN_SMTP_PASSWORD` | SMTP 密码或授权码 |
| `HAOYUAN_SMTP_FROM` | 发件人邮箱 |
| `HAOYUAN_SMTP_SECURITY` | `ssl`（默认）或 `starttls` 或 `none` |

> 若未配置，用户点击找回密码时会看到「邮件服务未启用，请联系部署者配置 SMTP」。开源仓库不包含任何 SMTP 凭据，请勿把真实账号密码提交到 Git。

## 数据与重置

账号数据保存在：

```
api/data/user_account.json
```

如果既未配置邮件服务、也忘记了密码，可停止后端后删除该文件（或把 `configured` 改为 `false`），重启后即可重新设置账号。

## 开发说明

- `plugin.py` 同时包含账号存储、鉴权中间件、找回密码/邮件服务路由
- 通过 `ctx.add_middleware(...)` 注册全局访问门禁
- 通过 `ctx.on("plugin.toggled", ...)` 实现启用/停用的即时生效
