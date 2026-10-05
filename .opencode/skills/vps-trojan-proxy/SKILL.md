---
name: vps-trojan-proxy
description: 在 Linux VPS 上搭建/维护 trojan 代理（VPN）并配 Jrohy 管理面板 + nginx 网站 + Let's Encrypt 证书。当用户提到搭建 vpn、trojan、v2ray、代理服务器、证书续期、科学上网连不上、加签名面板、翻墙服务时使用。
---

# VPS trojan 代理搭建与排障

在 VPS 上部署 **trojan 代理 + Jrohy 用户管理面板 + nginx 网站**，并解决证书、数据库、客户端连不上等常见问题。

## 架构总览（本次实战最终形态）

```
公网
 |-- 443  nginx(SSL)  -> /            → trojan-web 面板 (127.0.0.1:8080)
 |                       /study/      → 学习站静态页
 |                       /.well-known/acme-challenge/ → 证书续期
 |-- 80   nginx        -> 同上（用于 HTTP 跳转/acme 验证）
 |-- 444  trojan 主代理（0.0.0.0:444, SNI=域名, fallback→127.0.0.1:80）
 |-- 22   SSH
 |-- 33609 MariaDB Docker（trojan 多用户认证，公网可达=安全风险，至少改 bind/防火墙）
- VPS IP：`134.122.190.35`（域名 `aiwanxiang.top` 已解析到此 IP）
```

- **trojan 认证模式**: 密码存 MySQL（`password: null`），从 `mysql.users` 表按 `sha224(密码hex)` 校验配额。
- **伪装**: trojan 只要认证失败/非 trojan 流量，就转发给 `remote_addr: 127.0.0.1:80`，由 nginx 呈现网站 → 被动探测看到的是普通网站。

## 关键路径 / 配置

| 组件 | 位置 |
|---|---|
| trojan 服务 | `/etc/systemd/system/trojan.service`, 二进制 `/usr/local/bin/trojan` |
| trojan 配置 | `/usr/local/etc/trojan/config.json` |
| trojan-web 面板 | `/etc/systemd/system/trojan-web.service`（改到 `--host 127.0.0.1 --port 8080`） |
| nginx 80 站点 | `/etc/nginx/conf.d/study.conf` |
| nginx 443 站点 | `/etc/nginx/conf.d/webssl.conf` |
| 证书源 | `/root/.acme.sh/<域名>_ecc/` |
| 证书副本(nginx) | `/etc/nginx/ssl/{fullchain.cer,<域名>.key}` |
| acme.sh | `/root/.acme.sh/acme.sh`（**不在 PATH**，必须用全路径） |
| MariaDB | Docker 容器 `trojan-mariadb`，`0.0.0.0:33609→3306`，库 `trojan` 表 `users` |
| 学习站源码母本 | `/root/ai/learning-site/`（覆盖前先确认母本，别乱覆盖源站） |

## 建站步骤（从零）

1. 安装 trojan / trojan-web（Jrohy 面板，自带打包脚本），nginx、acme.sh、Docker+MariaDB。
2. 域名 DNS 指向 VPS IP；云厂商安全组/iptables 放行 22、80、443、444（必要时 33609）。
3. `systemctl start trojan && systemctl enable trojan`；trojan-web 改到 8080 避开 nginx 的 80。
4. nginx 先写纯 80 站点：`/`→8080 面板、`/study/`→静态、`/.well-known/acme-challenge/`→静态目录。
5. 签证书（见下），装到 nginx 443，写 `webssl.conf` 并 `systemctl reload nginx`。
6. MySQL 里建用户（trojan 面板 UI 能添加）；客户端填 域名:444:密码 即可通。

## 证书申请与续期（webroot 模式）

- `acme.sh` 的三处坑：**standalone 占 443 没用，要的是 80**；本机 nginx/面板若占 80 会失败；默认 CA（ZeroSSL）会卡 Pending → 加 `--server letsencrypt`。
- 命令（webroot，用 nginx 的 acme-challenge 目录）：
  ```bash
  /root/.acme.sh/acme.sh --issue -d <域名> --webroot /usr/share/nginx/html --server letsencrypt --keylength ec-256
  ```
- 续期直接自动走 `--cron`；若 nginx 需要新证书副本，配置 `--install-cert` 到 `/etc/nginx/ssl/` 并指定 `--reloadcmd "systemctl reload nginx"`。
- 校验：`openssl x509 -in fullchain.cer -noout -dates`（别只看 notAfter，先确认**当前时间**没过期）。

## 客户端（v2rayN 等）关键配置

- **地址必须填域名（如 `aiwanxiang.top`），不要填 IP**。证书只签给域名，填 IP 时 TLS 校验必然失败，服务器日志表现为 `sslv3 alert bad certificate`，客户端表现为握手即断。同理 SNI/serverName 也填域名。
- 端口 444、密码与 MySQL `passwordShow` 一致（那是明文密码，直接填）。
- allowInsecure 保持关（证书有效）。想用 IP 临时测试才开。
- 独立验证隧道：自己写 e2e 脚本，协议 = `sha224(密码)hex\r\n + 0x01(CMD) + 0x03(ATYP) + len(1B)+域名 + 端口(2B BE) + \r\n + 载荷`，然后收 HTTP 响应（200 即通）。

## 排障速查表

| 症状 | 根因 | 处理 |
|---|---|---|
| 客户端连不上，日志 `sslv3 alert bad certificate` | 客户端地址/SNI 用的是 IP | 改填域名 + SNI=域名 |
| 密码"正确"仍被拒，日志 `Lost connection to MySQL server during query` | MariaDB 空闲连接超时被回收，trojan 复用死连接 | 容器 `50-server.cnf` 加 `wait_timeout=86400 interactive_timeout=86400 connect_timeout=30 max_connections=500`，重启容器 |
| 日志 `valid trojan request structure but possibly incorrect password` | 只有两种：真密码错，或 MySQL 连接中断（见上） | 先查 DB 再怀疑密码 |
| 日志 `not trojan request, connecting to 127.0.0.1:80` + nginx 200 | 这是**正常伪装回落**，不是故障 | 忽略；若确认来自自家客户端，按上面两条查 |
| 证书已过期（页面/小程序报不安全） | LE 证书 90 天 | 走"证书续期"流程 |
| 80 端口没配好/面板打不开网站 | 老面板默认绑 80 和 nginx 抢 | `--host 127.0.0.1 --port 8080`，nginx `/` 反代到 8080 |
| 每天固定时刻面板闪断 | 旧 cron 里有 `systemctl stop trojan-web` + acme cron | 清理 cron，仅保留 acme `--cron` |
| 443 外部打不开 | 云安全组/iptables 没放行，或 webssl.conf 没写 | 放行 + 写 443 ssl 站点 |

## 注意事项 / 经验教训

- **改任何线上内容前先备份/确认母本**：别人站点内容被覆盖是事故（本次 `/study/` 和 `/usr/share/testpage/` 曾被 echo/符号链接覆盖，靠 `/root/ai/learning-site/` 才恢复）。
- MySQL `33609` 暴露公网是隐患：至少区域限制 IP 或加防火墙，别裸奔。
- trojan 与面板的 MySQL 连接会因 MariaDB 空闲超时而失效 → 改大超时并持久化到容器配置里，别只 `SET GLOBAL`（重启即丢）。
- Windows PowerShell 里裸 `curl` 是 `Invoke-WebRequest` 别名，要用 `curl.exe`。
- E2E 自测脚本放本地临时目录即可；改脚本后记得一次改对协议字节再跑。

## 自带脚本（scripts/ 目录）

| 脚本 | 用途 | 运行示例 |
|---|---|---|
| `scripts/check_vps.py` | 一键检查服务状态、端口、trojan 配置、nginx 配置 | `python scripts/check_vps.py` |
| `scripts/check_certs.py` | 检查证书有效期、nginx SSL 证书同步、学习站文件、trojan-web 服务、Docker | `python scripts/check_certs.py` |
| `scripts/check_db.py` | 检查 MariaDB 容器、trojan 用户表记录数 | `python scripts/check_db.py` |

> 运行前需确保本机已装 `paramiko`：`pip install paramiko`。脚本里硬编码了 SSH 凭据（`root / Brian52026$$ @ 134.122.190.35:22`），复用时改成你的 VPS 信息即可。