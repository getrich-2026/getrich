# 前端开发指南（`apps/web`）

面向启动和维护主前端的开发者，涵盖本地启动、配置与排障。技术栈为 Vite 8、React 19、TypeScript 6、Tailwind 4；编码规范见 [AGENTS.md](../../AGENTS.md) §5。

核对日期：2026-10-28，仅静态核对源码、锁文件与 CI，未验证服务运行和数据库供数。`apps/backtest-web` 暂停维护，不在本文范围内。

## 1. 准备后端

需要 Python 3.11+、uv 和可连接的 PostgreSQL。默认 `GETRICH_WORKER_BACKEND=inproc`，此启动路径不需要 ClickHouse 或 Redis。

在仓库根目录执行：

```bash
uv sync --frozen --all-packages
# 仅首次创建；已有 .env 时跳过复制，保留原配置
cp .env.example .env
```

编辑根 `.env`，填写 `PG_*` 连接配置。已有 shell 环境变量优先于 `.env`；切换数据库前确认实际目标。随后迁移并启动 API：

```bash
uv run gr-db migrate --target pg
uv run uvicorn gr_api.main:app --reload --host 127.0.0.1 --port 8001
```

另开终端检查：

```bash
curl --fail --silent --show-error http://127.0.0.1:8001/health
```

预期返回 `{"status":"ok"}`，只表示应用可响应，不证明业务表或数据齐全。接口文档见 <http://127.0.0.1:8001/docs>；迁移只建表，不生成策略、订阅或行情数据。

## 2. 安装并配置前端

使用 Node 24，与 [前端 CI](../../.github/workflows/web.yml) 一致。当前锁文件中的 Vite 与 React 插件要求 Node `^20.19.0 || >=22.12.0`。

新终端从仓库根目录执行，后续 npm 命令均在 `apps/web` 下运行：

```bash
cd apps/web
npm ci
# 仅首次创建；已有 .env.local 时跳过复制
cp .env.example .env.local
```

**模板目前使用 `http://127.0.0.1:8000/v1`，复制后须将 `.env.local` 中的 API 基址改为 `/v1`**，才能匹配本文的 `8001` 后端与 Vite 代理：

```dotenv
VITE_API_BASE_URL=/v1
VITE_DEMO_USER_ID=
```

| 变量 | 用途 |
| --- | --- |
| `VITE_API_BASE_URL` | API 基址，包含 `/v1`；使用相对路径走同源代理 |
| `VITE_DEMO_USER_ID` | 可选的开发期用户 UUID，经 `X-User-Id` 请求头发送，启用条件见下一节 |

`VITE_` 变量会进入浏览器代码，全部公开可见，不得放数据库连接信息或密钥。前端 `.env.local` 已被 gitignore；后端配置仍放根 `.env`。

## 3. 开发期身份

未携带 JWT、也未启用 mock 身份时按匿名访问；需要登录的接口返回 `401`。本地需要模拟用户时：

1. 在已配置连接的数据库客户端中执行 `SELECT id FROM app.users LIMIT 1;`，将已有用户的 UUID 填入 `VITE_DEMO_USER_ID`。根 `.env` 不会自动导出为 shell 变量，不能直接假设 `psql` 已获得其中的连接参数。
2. 在根 `.env` 设置 `APP_ENV=dev`、`GETRICH_ALLOW_MOCK_AUTH=true`，重启后端；前端修改环境变量后确认 Vite 已重启。

有效 JWT 优先于 mock 身份；浏览器 `localStorage` 中的 `token` 无效或过期时返回 `401`，不会回退到 `X-User-Id`。切换到 mock 调试前清除旧 token。身份有效也不代表已有策略订阅，需分别检查订阅数据。

mock 认证默认关闭，仅允许在 `APP_ENV=dev` 开启；它信任可伪造的请求头，只用于受控开发环境。边界见 [D-020](../../.agents/brain/DECISIONS.md#d-020)。

## 4. 启动与远程访问

在 `apps/web` 下运行：

```bash
npm run dev
```

[vite.config.ts](../../apps/web/vite.config.ts) 当前配置如下：

| 配置 | 当前值与作用 |
| --- | --- |
| `server.port` | `3000`，访问地址以启动日志为准 |
| `server.host` | `0.0.0.0`，监听全部网卡 |
| `server.proxy` | `/v1` 转发到 `http://127.0.0.1:8001` |

浏览器通过前端地址发起 `/v1` 请求，由 Vite 转发至 API，无需为这条同源路径额外配置 CORS。后端端口变化时须同步修改代理目标；uvicorn 的 `--port` 与代理目标均不会自动读取根 `.env` 的 `WEB_PORT`。

远程开发可在本机建立 SSH 隧道，再访问 `http://127.0.0.1:3000`（替换下方用户与开发机地址）：

```bash
ssh -N -L 127.0.0.1:3000:127.0.0.1:3000 devuser@dev-host
```

若直接访问开发机的 `3000` 端口，还需网络与防火墙允许连接；后端 `8001` 可保持只监听本机。Vite 开发服务与 mock 认证不应直接对公网开放。

## 5. 日常开发与验证

在 `apps/web` 下执行：

```bash
npm run lint      # ESLint
npm run build     # tsc -b && vite build
npm run preview   # 构建后，本地预览 dist 产物
```

当前前端没有测试框架，CI 门禁为 `lint` 和 `build`。复现安装用 `npm ci`，新增依赖用 `npm install` 并同步锁文件；预览不代表已完成生产部署。

### 接口分层

| 位置 | 职责 |
| --- | --- |
| [src/api/client.ts](../../apps/web/src/api/client.ts) | 附加 JWT／mock 请求头、处理 `401`、校验业务 `code` 并剥离响应信封 |
| `src/api/<domain>.ts` | 通过统一 `http` 发请求，返回 `Promise<T>`，`T` 为后端 `data` |
| `src/types/<domain>.ts` | 按后端 service 的实际返回定义类型 |
| 组件 | 用 React Query 管理异步数据与轮询，完成视图形状转换 |

保持单一接口层，不在组件中 inline `fetch` 或用 `useEffect` + `useState` 手写轮询。取舍见 [D-007](../../.agents/brain/DECISIONS.md#d-007)；信号枚举、详情缺字段与契约生成方案见[待决问题](../plans/backlog.md)。

### 样式与组件

主题在 [src/index.css](../../apps/web/src/index.css) 维护：`@theme` 定义工具类对应的主题变量，`:root` 存放设计 token，动画也在此文件。构建使用 `@tailwindcss/vite`，不新增 `tailwind.config.js`、`postcss.config.js` 或 `autoprefixer`。`src/components/ui/` 由 shadcn CLI 管理，不手改源码。

## 6. 排障

| 现象 | 检查与处理 |
| --- | --- |
| 请求发往 `8000`、远程浏览器访问了自己的 localhost | 检查 `.env.local`，将 `VITE_API_BASE_URL` 改为 `/v1`，确认 Vite 已重启 |
| 代理报错或连接失败 | 确认 API 在 `8001` 监听，检查 Vite 代理目标；`/health` 不在 `/v1` 代理范围内，须直连后端检查 |
| 接口报 `relation "xxx" does not exist` | 先确认数据库目标，再在仓库根执行 `uv run gr-db migrate --target pg` |
| 页面可打开但列表为空 | 检查 Network 中实际响应与筛选条件，再确认目标库是否有业务数据；迁移不灌数据 |
| `401` 或订阅状态不符合预期 | 检查旧 JWT、mock 开关与用户 UUID，再核对该用户的订阅记录 |
| 修改 `.env.local` 后无变化 | 确认修改的是 `apps/web/.env.local`；未自动重启时手动重启 Vite，构建产物需重新 build |
| `3000` 被占用 | macOS／Linux 可用 `lsof -nP -iTCP:3000 -sTCP:LISTEN` 查监听进程，并核对启动日志中的实际端口 |
| 远程连不上 | 检查启动日志中的地址、网络与防火墙；使用隧道时确认 SSH 连接与端口转发生效 |

相关操作：[选股导入](pick-import.md)、[诊断 API](diagnosis-api.md)。
