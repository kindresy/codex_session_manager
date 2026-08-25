# Codex Session Manager

一个轻量、彩色、零第三方运行时依赖的 Codex CLI 会话浏览器。它可以列出所有未归档的 CLI 会话，使用 `j/k` 实时预览内容，并通过 Enter 恢复所选会话。

这是社区项目，并非 OpenAI 官方工具。

## 功能

- 显示会话 ID、第一条问题、建立时间、最近打开时间和工作目录。
- 宽终端使用左表右预览布局，窄终端自动切换为上下布局。
- 优先从 SQLite 快速读取元数据，格式不兼容时自动降级到 JSONL。
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

默认安装到 `~/.local`。如果 `~/.local/bin` 不在 `PATH` 中，安装器会打印可直接复制的 `export PATH="~/.local/bin:$PATH"` 配置；运行该命令后即可直接使用 `codex-session`。安装到其他用户目录或指定版本：

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

## 数据兼容与隐私

Codex 的 session 数据库属于内部格式，未来版本可能发生变化。工具会动态检查 `state_*.sqlite` 的字段；数据库不可用或不兼容时，自动降级扫描 `sessions/**/*.jsonl`。

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
