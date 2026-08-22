# Codex Session Manager

一个轻量、彩色、零第三方运行时依赖的 Codex CLI 会话管理器。它会列出所有未归档的 CLI 会话，在终端中实时预览内容，并通过 Enter 恢复所选会话。

## 环境要求

- Linux 或其他提供 Python `curses` 的类 Unix 环境
- Python 3.10 或更高版本
- 已安装并能从 `PATH` 找到 `codex`

## 安装

在项目目录执行：

```bash
python3 -m pip install -e .
codex-session
```

也可以不安装，直接运行：

```bash
PYTHONPATH=src python3 -m codex_session_manager
```

## 界面与快捷键

宽终端使用左侧会话表、右侧内容预览的双栏布局；较窄终端自动切换为上下布局。

| 按键 | 操作 |
| --- | --- |
| `j` / `↓` | 下一个会话 |
| `k` / `↑` | 上一个会话 |
| `Ctrl-d` / `PageDown` | 预览向下滚动 |
| `Ctrl-u` / `PageUp` | 预览向上滚动 |
| `g` / `G` | 跳到第一个 / 最后一个会话 |
| `r` | 重新读取会话 |
| `Enter` | 执行 `codex resume <完整 UUID>` |
| `q` / `Esc` | 退出 |

## 数据来源

工具优先只读 Codex 的 `state_*.sqlite`，快速获得会话 ID、首问、建立时间、最近活跃时间和工作目录。数据库缺失或格式不兼容时，自动降级扫描 `sessions/**/*.jsonl`。

默认数据目录为 `~/.codex`。可通过环境变量或参数覆盖：

```bash
CODEX_HOME=/path/to/codex-home codex-session
codex-session --codex-home /path/to/codex-home
```

关闭颜色：

```bash
codex-session --no-color
```

本工具不会写入 Codex 数据库、session JSONL、索引或配置文件。

## 测试

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
