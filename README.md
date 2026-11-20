# Story · 故事短片工作台

从「老人情感陪伴」项目里抽取的**记录故事 → 生成短片故事板**功能，独立成项目。

## 功能

1. **对话记录故事**：老人说一句，小忆（LLM）顺着追问一句，讲完一键保存（原话原样入库）。
   - 支持打字 / 语音（DashScope ASR）
   - 内置 4 段演示剧本（不依赖模型，现场演示用）
2. **短片故事板**：选一段故事 → 生成 60 秒分镜脚本（代码定时长 + LLM 写旁白和画面提示词 + 后校验）。
   - 故事板播放器（TTS 念旁白）
   - 一键复制全部提示词

> **重要**：本项目**不生成真实视频**。产出止于 `prompt_package`（旁白 + 画面提示词 + 免责声明），
> `video_url` 恒为 null。提示词需复制到外部视频工具自行制作。这是从原项目原样保留的契约。

## 两种运行方式

本项目支持 **Docker（推荐，一条命令起 MySQL + 后端）** 和 **本地直接跑** 两种方式。前端一律在宿主机用 Node 跑。

### 方式 A：Docker（推荐）

用 docker-compose 起 MySQL 8.0 + 后端两个容器，MySQL 数据存在具名卷 `story-mysql-data`，不依赖本机 MySQL 服务。

前置：Docker Desktop 已启动（Linux 引擎就绪）。

```powershell
# 1. 确认系统环境变量 DASHSCOPE_API_KEY 有效（你已设好）
#    可选：设 MYSQL_PASSWORD 覆盖默认的 story123456
#    [Environment]::SetEnvironmentVariable('MYSQL_PASSWORD','自定义密码','User')

# 2. 在 E:/Story 下构建并启动（首次会拉 mysql:8.0 镜像）
cd E:/Story
docker compose up -d --build

# 3. 看日志确认后端就绪
docker compose logs -f backend
```

后端容器会自动等 MySQL 健康后启动，并自动建库建表。访问 `http://127.0.0.1:8100/api/health` 应返回 ok。

停止：`docker compose down`（加 `-v` 会连数据卷一起删，慎用）。

> 说明：`docker-compose.yml` 里 MySQL 密码默认 `story123456`，仅本地演示用；生产请通过 `MYSQL_PASSWORD` 环境变量覆盖。

### 方式 B：本地直接跑（不用 Docker）

## 前置条件

- Python 环境：`E:/elderly_companion/.venv`（含 fastapi/uvicorn/httpx/aiomysql/python-multipart）
- Node 18+（复用 `E:/elderly_companion/frontend/node_modules` 的 junction，无需重新下载）
- **系统环境变量 `DASHSCOPE_API_KEY`**（Machine 或 User 级均可）——API Key 只从这里读，仓库和代码里都没有明文 key
- **MySQL 服务已启动**（本机是 MySQL 8.4，服务名 `MySQL84`）+ 以下环境变量

### MySQL 连接配置（系统环境变量）

连接信息**不写进代码或仓库**，从系统环境变量读取。在你自己的 PowerShell 里执行一次（User 级，重开终端生效）：

```powershell
[Environment]::SetEnvironmentVariable('MYSQL_HOST','127.0.0.1','User')
[Environment]::SetEnvironmentVariable('MYSQL_PORT','3306','User')
[Environment]::SetEnvironmentVariable('MYSQL_USER','root','User')
[Environment]::SetEnvironmentVariable('MYSQL_PASSWORD','你的MySQL密码','User')
[Environment]::SetEnvironmentVariable('MYSQL_DATABASE','story','User')
```

默认值：host=127.0.0.1、port=3306、user=root、database=story、charset=utf8mb4，密码无默认（必须设）。
后端启动时会自动 `CREATE DATABASE IF NOT EXISTS story` 并创建两张表，无需手工建库。

启动 MySQL 服务（需要管理员权限，在**你自己的**终端执行）：

```powershell
net start MySQL84
```

## 启动

```bash
# 后端 :8100
cd E:/Story/backend
E:/elderly_companion/.venv/Scripts/python.exe run.py

# 前端 :3100（新开一个终端）
cd E:/Story/frontend
set NODE_OPTIONS=
npm run dev
```

浏览器打开 `http://127.0.0.1:3100`。

## 数据

- MySQL 数据库 `story`（可改 `MYSQL_DATABASE`），与原项目 `storage/companion.db` 完全隔离
- 两张表：`stories`（故事）、`compilations`（短片故事板），启动时自动建表
- 连接参数见 `backend/.env.example`（仅模板，实际值走系统环境变量）

## 目录结构

```
E:/Story/
├── docker-compose.yml          Docker 编排（MySQL + 后端）
├── backend/
│   ├── Dockerfile              后端镜像
│   ├── .dockerignore
│   ├── run.py                  启动入口
│   ├── requirements.txt
│   ├── .env.example            MySQL 连接配置模板
│   ├── app/
│   │   ├── main.py             FastAPI 路由
│   │   ├── config.py           配置（key + MySQL 连接读系统环境变量）
│   │   ├── db.py               MySQL 数据层（aiomysql，自动建库建表）
│   │   ├── llm.py              Qwen LLM 客户端
│   │   ├── speech.py           ASR/TTS
│   │   ├── story_chat.py       对话追问（原样移植）
│   │   ├── storyboard.py       分镜编排（原样移植）
│   │   ├── era_lexicon.py      时代词表
│   │   ├── time_utils.py       年份解析
│   │   ├── prompts.py          分镜 prompt
│   │   └── json_utils.py       JSON 容错解析
│   └── data/
│       └── era_lexicon.json    时代词表数据
└── frontend/
    ├── package.json / next.config.js / tailwind.config.ts
    ├── node_modules            junction → 原项目（省磁盘）
    └── src/
        ├── app/                页面（首页 / 短片列表 / 短片详情）
        ├── components/         StoryComposer / StoryboardPlayer
        ├── data/demo-stories.ts 演示剧本
        └── lib/api.ts          API 封装
```
