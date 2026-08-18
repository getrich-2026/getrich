# 前端启动指南（`apps/web`）

Vite 7 + React 19 + TypeScript 5.9。本文只讲怎么把开发环境跑起来。
编码规范在 `AGENTS.md` §5。

---

## 1. 前置：后端先跑起来

前端所有数据都来自 `gr-api`，先确认后端与数据库可用。

```bash
# 数据库连接信息（首次）
cp .env.example .env      # 然后填 PG / CH / Redis 的真实连接信息

# 全新库要先建表，否则接口全 500
uv run gr-db migrate --target pg

# 启动 FastAPI。端口取 .env 的 WEB_PORT
uv run uvicorn gr_api.main:app --reload --host 0.0.0.0 --port 8001
```

> **端口以 `.env` 的 `WEB_PORT` 为准**（当前是 8001）。`AGENTS.md` 的命令示例里写的是
> 8000，那是默认值，两处不一致时以 `.env` 为准，前端代理也要跟着对上（§3）。

自检：

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8001/health   # 期望 200
```

## 2. 装依赖

```bash
cd apps/web
npm install
```

当前环境实测 Node v24.15.0 / npm 11.18.0。`package.json` 没写 `engines`，Node 20+ 即可。

## 3. 环境变量

复制模板到 `.env.local`（该文件被 gitignore，**不要**提交）：

```bash
cp .env.example .env.local
```

只有 `VITE_` 前缀的变量会被注入浏览器包，**这些值全部公开可见**，绝不能写数据库地址、
密码或任何密钥。后端连接配置在仓库根的 `.env`。

| 变量 | 值 | 说明 |
|---|---|---|
| `VITE_API_BASE_URL` | `/v1` | 相对路径，走 Vite 代理转发到本机 `gr-api`（见 §4） |
| `VITE_DEMO_USER_ID` | `app.users.id` 的 UUID | 开发期 mock 认证：后端读 `X-User-Id` 头识别用户。留空则匿名访问，`is_subscribed` 恒为 false。切到真实 JWT 后可删 |

拿一个可用的 user id：

```bash
psql -h "$PG_HOST" -U "$PG_USER" -d "$PG_DB" -tc "SELECT id FROM app.users LIMIT 1"
```

## 4. 启动

```bash
cd apps/web
npm run dev
```

服务起在 **3000**，`vite.config.ts` 里配了两件事：

```ts
server: {
  port: 3000,
  host: '0.0.0.0',                              // 监听全部网卡，外网可访问
  proxy: { '/v1': 'http://127.0.0.1:8001' },    // /v1 同源代理到 gr-api
}
```

**代理带来的好处**：前端与接口同源，浏览器不发 CORS 预检，根 `.env` 的
`WEB_CORS_ORIGINS` 不必为每个访问来源加条目，后端端口也不必对外暴露。
换 IP 或以后挂域名都不用改 `VITE_API_BASE_URL`。

改 `gr-api` 端口时，**`vite.config.ts` 的 proxy 目标要同步改**，否则前端拿到 502。

其它命令：

```bash
npm run lint      # ESLint
npm run build     # tsc -b && vite build（当前失败，见 §6）
npm run preview   # 预览生产构建产物
```

## 5. 外网访问

`host: '0.0.0.0'` 已经让 Vite 监听全部网卡，启动日志里会打出 Network 地址：

```
➜  Local:   http://localhost:3000/
➜  Network: http://<你的 IP>:3000/
```

还需要防火墙放行 3000。因为走同源代理，**只需要开这一个端口**，后端 8001 可以只对
本机开放（`sudo ufw deny 8001`，或用 `--host 127.0.0.1` 启动 uvicorn）。

> **别长期对公网敞着**。这是明文 HTTP，认证还是 `X-User-Id` 头的 mock 模式——任何能
> 访问 3000 的人都可以填任意 UUID 冒充任意用户，Vite dev server 本身也不是为公网设计的。
> 临时给人看没问题；要长期开放，前面套 Nginx + HTTPS + Basic Auth，或者干脆走 SSH 隧道：
>
> ```bash
> ssh -L 3000:127.0.0.1:3000 user@<服务器 IP>    # 一个端口都不用开
> ```

## 6. 已知问题

- **`npm run build` 当前失败**：`tsconfig.app.json` 里 `"ignoreDeprecations": "6.0"` 在
  TS 5.9 下非法（TS5103）。去掉那行后还会暴露 2 个既有类型错误
  （`PortfolioDiagnosisPage.tsx` 的 `RefObject` 可空性、`StrategiesPage.tsx` 未使用的
  `navigate`）。`npm run dev` 不走 `tsc`，**不受影响**。
- **`npm run lint` 有 45 个既有错误**，都是历史遗留，不是新引入的。
- **`apps/backtest-web` 暂停维护**（缺 `src/lib/utils`、`src/lib/sanitize`），
  等 API 稳定后重做，现在不用管它。

## 7. 排查

| 现象 | 原因与处理 |
|---|---|
| 接口 500，报 `relation "xxx" does not exist` | 库没建表，跑 `uv run gr-db migrate --target pg` |
| 接口 502 / 代理报错 | 后端没起，或 `vite.config.ts` 的 proxy 目标端口与实际不符 |
| 页面能开但列表全空 | 库是空的，没有策略数据；`is_subscribed` 恒 false 则是 `VITE_DEMO_USER_ID` 没填 |
| 改了 `.env.local` 不生效 | Vite 会自动重启并打印 `.env.local changed, restarting server...`；没看到就手动重启 |
| 端口被占 | `ss -ltnp \| grep 3000` 找到进程，或改 `vite.config.ts` 的 `port` |
| 外网连不上 | 确认 `host: '0.0.0.0'` 生效（看启动日志有没有 Network 行）+ 防火墙放行 |

## 8. 接口速查

前端的接口函数都在 `src/api/`，走 `src/api/client.ts`（axios 实例，自动带
`Authorization` 与开发期的 `X-User-Id` 头）。组件一律用 `@tanstack/react-query` 管理
异步数据，**禁止** `useEffect` + `useState` 手写轮询或 inline `fetch`。

后端接口文档：<http://127.0.0.1:8001/docs>

选股标的池怎么导入见 [`pick-import.md`](./pick-import.md)。
