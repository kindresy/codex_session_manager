# Codex Session Manager

一个轻量、彩色、零第三方运行时依赖的 Codex CLI 会话浏览器。它可以列出所有未归档的 CLI 会话，使用 `j/k` 实时预览内容，并通过 Enter 恢复所选会话。

这是社区项目，并非 OpenAI 官方工具。

## 功能

- 显示会话 ID、第一条问题、建立时间、最近打开时间和工作目录。
- 宽终端使用左表右预览布局，窄终端自动切换为上下布局。
- 优先通过 Codex App Server 读取会话元数据和预览；App Server 不可用时自动切换到本地 SQLite/JSONL 兼容模式。
- 仅在选中会话时读取预览，并按文件修改时间缓存。
- 支持彩色和单色终端。
- 对 Codex 数据保持只读。

## 支持的平台

- Linux
- macOS
- WSL（Windows Subsystem for Linux）
- 通过 SSH 使用的 Linux 主机

原生 Windows 当前不受支持，因为 Windows Python 默认不包含 `curses`。Windows 用户请在 WSL 中安装和运行。

## 环境要求

- 支持 UTF-8 的终端
- 已安装 Codex CLI，并且 `PATH` 中能够找到 `codex`

缺少 `codex` 时仍可浏览和预览会话，但不能通过 Enter 恢复。

独立程序不需要 Python。使用 pip 或直接从源码运行时，需要 Python 3.10 或更高版本，以及 Python `curses` 和 `sqlite3` 标准库。

## 推荐安装：Linux/WSL 独立程序

Linux 或 WSL x86_64 用户可以直接安装自包含版本，无需安装或升级 Python、pip、venv 或 setuptools，也不需要 `sudo`。支持 Ubuntu 20.04 或其他 glibc 2.31 及以上的发行版。

```bash
curl -fsSLO \
  https://github.com/kindresy/codex_session_manager/releases/latest/download/install.sh
less install.sh
bash install.sh
~/.local/bin/codex-session --version
```

默认安装到 `~/.local`。如果 `~/.local/bin` 不在 `PATH` 中，安装器会打印可直接复制的 `export PATH="$HOME/.local/bin:$PATH"` 配置；运行该命令后即可直接使用 `codex-session`。安装到其他用户目录或指定版本：

```bash
bash install.sh --prefix /path/to/prefix
bash install.sh --version v0.1.0
```

也可以从 GitHub Release 手动下载 `codex-session-manager-linux-x86_64.tar.gz` 和对应的 `.sha256` 文件，校验并解压后直接运行其中的 `codex-session`。

### 升级、回退和卸载

重新运行 `bash install.sh` 即可升级。安装器保留当前版本和上一个版本；需要回退时，将 `current` 链接指向保留的旧版本：

```bash
ln -sfn ~/.local/lib/codex-session-manager/versions/0.1.0 \
  ~/.local/lib/codex-session-manager/current
```

卸载只删除本工具管理的用户目录和命令链接：

```bash
rm ~/.local/bin/codex-session
rm -r ~/.local/lib/codex-session-manager
```

## 使用 Python/pip 安装

Python 用户和开发者仍可以从 GitHub 直接安装；这种方式要求 Python 3.10 或更高版本。建议先进入虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install "git+https://github.com/kindresy/codex_session_manager.git"
codex-session
```

## Clone 后安装

```bash
git clone https://github.com/kindresy/codex_session_manager.git
cd codex_session_manager
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install .
codex-session
```

以上过程不需要修改任何源码。

## 直接从源码运行

不安装也可以运行：

```bash
git clone https://github.com/kindresy/codex_session_manager.git
cd codex_session_manager
PYTHONPATH=src python3 -m codex_session_manager
```

## 使用方法

启动：

```bash
codex-session
```

| 按键 | 操作 |
| --- | --- |
| `j` / `↓` | 选择下一个会话 |
| `k` / `↑` | 选择上一个会话 |
| `Ctrl-d` / `PageDown` | 预览向下滚动 |
| `Ctrl-u` / `PageUp` | 预览向上滚动 |
| `g` / `G` | 跳到第一个 / 最后一个会话 |
| `/` | 搜索首问、完整 session ID 和工作目录 |
| `n` / `N` | 跳到下一个 / 上一个搜索结果 |
| `r` | 重新读取会话列表 |
| `Enter` | 执行 `codex resume <完整 UUID>` |
| `q` / `Esc` | 退出 |

搜索采用不区分大小写的子串匹配，只检查列表中已经加载的信息，不扫描完整会话内容。输入关键词后按 Enter 确认，按 Esc 取消。

查看帮助和版本：

```bash
codex-session --help
codex-session --version
```

## 配置

默认读取 `$CODEX_HOME`；环境变量未设置时使用 `~/.codex`。也可以通过参数指定：

```bash
CODEX_HOME=/path/to/codex-home codex-session
codex-session --codex-home /path/to/codex-home
```

关闭颜色：

```bash
codex-session --no-color
```

## 可选：Cloud 会话同步

Cloud 功能把本机 Codex 会话手动上传到你自己的 Cloudflare Worker 和 private R2 bucket，并提供同源 PWA 与只读终端浏览。它依赖 [Codex App Server](https://developers.openai.com/codex/app-server/) 的 `thread/list` 与 `thread/read` 接口；Cloudflare 侧使用官方的 [R2 Workers API](https://developers.cloudflare.com/r2/get-started/workers-api/) 和 [Workers Static Assets](https://developers.cloudflare.com/workers/static-assets/)。

### 部署前提

- 一个启用了 Workers、R2 和 `workers.dev` 的 Cloudflare 账户。
- 已安装 Node.js 20 或更高版本及 npm；它们只用于首次部署和更新 Cloud 组件。
- 已 clone 本仓库，并能在本机运行 `codex-session` 和 Codex CLI。
- 一个由密码管理器生成、只供自己使用的强随机 Bearer token。不要使用 OpenAI API key 或 Cloudflare API token。

部署 Worker、private R2 和 PWA：

```bash
git clone https://github.com/kindresy/codex_session_manager.git
cd codex_session_manager/cloud
npm ci
./deploy.sh
```

脚本会打开 Cloudflare 登录、创建或复用 `codex-session-history` R2 bucket、确认 bucket 没有公开开发 URL 或自定义域名、读取 Bearer token、保存为 Worker secret，然后一起部署 API 与静态 PWA。它不会部署或读取本机 Codex 数据。保存 Wrangler 输出的 Worker URL，然后配置 CLI：

```bash
codex-session sync setup
# Worker URL: https://codex-session-cloud.<account>.workers.dev
# Access token: <上一步输入的同一个 token>
```

配置保存在 `~/.config/codex-session/sync.json`。该文件包含明文 Worker URL 和 token，请保持用户私有权限，不要提交或分享。

### 同步与浏览

```bash
codex-session sync          # 只上传新增或 updated_at 更新的会话
codex-session sync --all    # 重传所有未被删除标记保护的本地会话
codex-session sync status   # 只检查服务、远端数量和索引更新时间
codex-session cloud         # 在终端中只读浏览云端会话
```

同步是 manual only（仅手动触发），没有后台守护进程或自动计划任务。普通同步会保留只存在于云端的历史（retention）；网页删除会移除对象，并在索引写入 tombstone。tombstone 防止同一 ID 在以后执行 `sync` 或 `sync --all` 时重新出现。

终端 Cloud 模式支持列表、搜索、预览和刷新，但 Enter 不会恢复会话；当前版本不支持 remote resume。它也不会修改本地会话。

### PWA、存储与隐私

在手机或桌面浏览器打开部署时 Wrangler 显示的同一个 Worker URL，即为 PWA URL。首次打开时输入相同 Bearer token；浏览器把它保存在该站点的 local storage 中。不要在公用设备上保存 token；清除该站点数据即可移除。PWA service worker 只缓存应用外壳，不缓存会话 API 响应。

上传内容在你自己的 private R2 中保存为 plaintext JSON（未做端到端加密），包括用户/助手消息、命令输出、文件变更摘要、时间戳和工作目录。系统提示、注入的环境上下文、内部推理、认证配置和未知内部事件不会进入项目 Cloud schema。Bearer token 保护 Worker API，但不替代 Cloudflare 账户安全；请启用账户 MFA，并把 bucket 保持为私有。

### Cloud 故障排查

- `sync setup` 后提示认证失败：确认 CLI 与 PWA 使用部署时输入的同一个 Bearer token；重新部署或更新 Worker secret 后也要重新配置客户端。
- 无法连接 Worker：运行 `codex-session sync status`，并确认保存的是完整 `https://...workers.dev` URL，未附加 `/api`、query 或 fragment。
- 同步提示找不到 `codex` 或 App Server 错误：确认 `command -v codex` 和 `codex --version` 正常；完整同步必须由 App Server 返回 thread turns，本地 SQLite/JSONL 只作为普通浏览的兼容后备。
- PWA 显示空列表：先成功运行一次 `codex-session sync`，再在网页刷新；Cloud 部署本身不会上传数据。
- 被删除的会话没有重新上传：这是 tombstone 的预期行为。第一版不提供清除 tombstone 的命令，避免误恢复私人历史。

## 数据兼容与隐私

Codex 的本地 session 数据属于内部格式，未来版本可能发生变化。会话读取按以下层级工作：首先使用 Codex App Server；若 App Server 启动、通信或响应格式不兼容，工具会自动切换到本地 SQLite/JSONL 兼容模式。本地模式会动态检查 `state_*.sqlite` 的字段，数据库不可用或不兼容时再扫描 `sessions/**/*.jsonl`。成功返回空的 App Server 会话列表时不会切换到本地模式。

切换到本地模式后，界面会显示非致命的降级提示；如果 App Server 不可用且本地会话也不可读，提示会建议升级 codex-session-manager。如果未来不兼容的 Codex 发布导致此情况，请更新软件包，无需修改源码：

```bash
python3 -m pip install --upgrade codex-session-manager
```

`$CODEX_HOME`（或 `--codex-home` 指定的目录）会传递给 Codex App Server，并同样用于本地兼容模式，因此两种读取方式查看的是同一份 Codex 数据。

本工具对 Codex 数据完全只读，不会修改数据库、session JSONL、索引、认证信息或配置文件。仓库中的自动测试只使用合成 fixture，不包含真实对话或凭据。

## 故障排查

### 提示“找不到 codex”

确认 Codex CLI 已安装并位于 `PATH`：

```bash
command -v codex
codex --version
```

此时会话仍可浏览，但 Enter 不会启动恢复操作。

### 显示“没有找到可恢复的 Codex CLI 会话”

确认数据目录存在：

```bash
ls "${CODEX_HOME:-$HOME/.codex}"
codex-session --codex-home "${CODEX_HOME:-$HOME/.codex}"
```

工具只显示未归档的 Codex CLI 会话，不显示 VS Code 和子代理会话。

### `curses` 或终端显示异常

请确认使用 Linux、macOS 或 WSL，并检查 UTF-8 locale：

```bash
python3 -c "import curses; print('curses ok')"
locale
codex-session --no-color
```

## 开发

开发模式安装：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
```

运行测试和编译检查：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
```

构建 wheel 和源码包：

```bash
python3 -m pip install build
python3 -m build
```

发布标签前，还需要在 WSL Ubuntu 20.04 x86_64 中手动下载候选压缩包，运行 `codex-session --version`，并打开一次 TUI 后按 `q` 正常退出。GitHub Actions 中的 Linux 容器测试不能替代这项 WSL 集成检查。

## 报告问题

请在 [GitHub Issues](https://github.com/kindresy/codex_session_manager/issues) 中描述复现步骤，并附上以下信息：

```bash
python3 --version
codex --version
codex-session --version
```

同时注明操作系统、终端类型，以及是否设置了 `$CODEX_HOME`。请勿上传包含私人对话或认证信息的 session 文件。

## License

[MIT](LICENSE) © 2026 kindresy
