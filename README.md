# PatchPilot

PatchPilot 是一个使用 Python 实现的本地编码 Agent。它通过
OpenAI-compatible Chat Completions 接口进行 Tool Calling，自行管理模型循环、
工作区工具、上下文压缩、错误恢复、执行审批、Docker 沙箱、会话恢复和结果验证。

项目没有使用现成 Agent 框架，核心调度、工具协议和安全边界均在项目内实现。

## 已实现能力

- 列举目录、分段读取 UTF-8 文件和使用 ripgrep 搜索代码
- 通过唯一文本匹配修改已有文件，并安全创建新文件
- 运行测试、静态检查和 Git 只读命令
- 工作区路径约束和敏感文件过滤
- `--read-only` 只读分析模式
- 写入与普通命令的交互审批，以及 `--yes` 自动审批
- API 超时、连接错误和无效模型响应的指数退避重试
- 重复失败工具调用去重，避免反复执行相同副作用
- 字符预算驱动的历史压缩，保留最近完整 assistant/tool 回合
- 权限受限的 JSONL 日志与异常退出 checkpoint
- `patchpilot resume` 跨进程继续任务
- `patchpilot chat` 启动一次后持续输入多轮需求
- 基于真实工具记录的完成状态、测试证据和 Git 工作树审查
- Docker 命令沙箱：禁网、只读根文件系统和资源限制
- `patchpilot eval` 端到端编码修复评测

## 架构

```text
CLI (run / chat / resume / eval)
│
├── Configuration ── 外置 .env、超时、上下文与沙箱配置
├── Model Client ─── OpenAI-compatible 适配、协议校验与重试
├── Agent Loop
│   ├── Context Manager ── 消息配对、字符预算、历史摘要
│   ├── Tool Registry ──── 审批、执行、错误标准化
│   ├── Evidence Collector ── 修改与测试证据
│   └── Checkpoint ──────── 异常退出恢复
├── Workspace Guard ─────── 路径边界与敏感文件保护
├── Docker Sandbox ──────── 无网络、受限本地命令执行
└── Events ──────────────── Rich 终端、JSONL 日志、Git 审查
```

模型不会直接操作文件系统。它只能请求 PatchPilot 暴露的工具，工具调用经过参数校验、
工作区检查、安全策略和必要的用户审批后才能执行。

## 环境要求

- Linux 或 WSL2
- Python 3.10 或更高版本
- Git
- ripgrep
- Docker daemon
- 本地已有 `ubuntu:22.04` 镜像
- 可用的 OpenAI-compatible 模型 API

确认 Docker 环境：

```bash
docker info
docker image inspect ubuntu:22.04 >/dev/null
```

PatchPilot 使用 `--pull never`，运行过程中不会自动下载镜像。

## 安装

```bash
cd ~/coding-agent
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

确认 CLI：

```bash
patchpilot --help
patchpilot run --help
patchpilot chat --help
patchpilot resume --help
patchpilot eval --help
```

## 模型配置

真实凭据放在仓库外部：

```text
~/.config/patchpilot/.env
```

示例：

```dotenv
AGENT_API_KEY=replace-with-your-key
AGENT_BASE_URL=https://example.com/v1
AGENT_MODEL=your-model-id

AGENT_TIMEOUT=180
AGENT_MAX_STEPS=20
AGENT_MAX_CONTEXT_CHARS=120000

AGENT_SANDBOX_MODE=docker
AGENT_SANDBOX_IMAGE=ubuntu:22.04
```

也可以通过 `PATCHPILOT_CONFIG` 指定其他配置路径：

```bash
export PATCHPILOT_CONFIG=/absolute/path/to/patchpilot.env
```

完整模式会拒绝位于可写 workspace 内部的配置文件，避免 Agent 读取或修改自己的密钥。

## 基本使用

### 持续对话模式

只启动一次，之后直接逐轮输入需求：

```bash
patchpilot chat --workspace ~/target-project
```

```text
你 > 检查项目结构并总结功能
你 > 运行测试并修复失败
你 > 再补一个边界测试
你 > /exit
```

后续输入会复用之前的对话上下文，但每轮重新收集修改、测试和 Git 证据。可用命令：

```text
/help          显示帮助
/status        显示工作区、模型、审批和上下文预算
/new           立即清空上下文，开始新对话
/history       显示本次终端会话的输入历史
/yes on|off    动态切换普通操作自动审批
/clear         清屏
/exit          退出
```

启动时也可以固定只读或自动审批：

```bash
patchpilot chat --workspace ~/target-project --read-only
patchpilot chat --workspace ~/target-project --yes
```

### 只读分析

```bash
patchpilot run \
  "检查项目结构和 README，用中文总结当前功能，不要修改文件。" \
  --workspace ~/target-project \
  --read-only
```

### 修改并验证项目

```bash
patchpilot run \
  "运行测试，定位失败原因，做最小修复并重新运行相关测试。" \
  --workspace ~/target-project
```

修改文件和普通命令会请求确认。对于独立、可丢弃的测试项目，可以自动批准：

```bash
patchpilot run \
  "修复失败测试并验证结果。" \
  --workspace ~/target-project \
  --yes
```

`--yes` 不会绕过命令黑名单、工作区限制或 Docker 隔离。

### 日志和恢复

默认会话目录：

```text
~/.local/state/patchpilot/sessions/
```

JSONL 日志经过补丁正文脱敏，checkpoint 则包含恢复所需的完整上下文；目录权限为
`0700`，文件权限为 `0600`。任务正常完成后 checkpoint 自动删除，异常退出时保留。

```bash
patchpilot resume 20260828-120000-abcd1234
patchpilot resume abcd1234 --max-steps 30 --yes
```

使用 `--no-log` 会同时禁用本次任务的 checkpoint。

## 命令沙箱

生产 CLI 默认使用 Docker 执行 `run_command`：

- workspace 挂载到 `/workspace`，是唯一可写的持久目录
- 根文件系统和 Python 虚拟环境只读
- `--network none`
- 删除全部 Linux capabilities
- `no-new-privileges`
- 1 CPU、512 MB 内存、128 个进程
- `/tmp` 使用 64 MB 临时内存文件系统
- 超时后按随机容器名精确清理

如果 Docker 不可用，可以显式设置：

```dotenv
AGENT_SANDBOX_MODE=host
```

`host` 仅为兼容模式，不具备操作系统级文件隔离，不建议用于不可信任务。

## 可信结果报告

Agent 的自然语言结论不是唯一依据。PatchPilot 会独立记录：

- 成功修改的文件
- 实际运行的测试命令和退出码
- 最后一次成功验证是否晚于最后一次修改
- `git status --short`
- 已暂存和未暂存的 `git diff --stat`
- `git diff --check`

修改后未验证、最新测试失败或 `git diff --check` 失败时，可信状态会显示为
“部分完成”，即使模型声称任务已经完成。

## 端到端评测

运行内置用例：

```bash
patchpilot eval \
  --max-steps 15 \
  --case-timeout 600 \
  --output eval-results/smoke.json
```

评测流程：

1. 将每个 fixture 复制到独立临时目录
2. 确认修复前测试失败
3. 调用真实 PatchPilot 完成任务
4. 在 Docker 沙箱中重新验证
5. 生成 JSON 指标报告并清理临时目录

当前内置 smoke 结果：

| Case | 结果 | 步骤 | 工具调用 | Agent 耗时 |
| --- | ---: | ---: | ---: | ---: |
| off-by-one | 通过 | 6 | 7 | 17.23 s |
| slugify-todo | 通过 | 5 | 6 | 20.41 s |
| 总计 | 2/2（100%） | 11 | 13 | 37.64 s |

完整评测总耗时为 38.93 秒。评测会把 fixture 中的代码发送给配置的第三方模型，
可能消耗 API 配额。`eval-results/` 默认不提交到 Git。

## 测试

```bash
python -m pytest -q
git diff --check
```

当前离线测试结果：

```text
118 passed
```

## 项目结构

```text
src/patchpilot/
├── agent.py          # Agent 主循环、重复失败检测、恢复入口
├── approvals.py      # 用户审批策略
├── checkpoint.py     # 原子 checkpoint 持久化
├── chat.py           # 多轮终端对话与斜杠命令
├── cli.py            # run / chat / resume / eval 命令
├── config.py         # 外置环境配置
├── context.py        # 上下文预算与历史压缩
├── evaluation.py     # 端到端评测框架
├── events.py         # Rich 与 JSONL 事件
├── git_review.py     # 最终 Git 工作树审查
├── model.py          # OpenAI-compatible 模型适配器
├── outcome.py        # 结构化证据与可信状态
├── sandbox.py        # Docker 命令沙箱
├── workspace.py      # 路径与敏感文件边界
└── tools/            # 文件、搜索、补丁和命令工具

evals/cases/          # 固定端到端评测用例
tests/                # 离线单元与集成测试
```

## 安全边界与局限

- 模型 API 会接收任务描述、相关源码和工具结果；Docker 沙箱不会阻止这类模型请求。
- workspace 内的文件属于 Agent 授权范围，不应把真实密钥放在目标项目中。
- 命令沙箱依赖 Docker daemon 和预先存在的镜像。
- 工具黑名单是纵深防御，不能替代容器隔离。
- 字符预算是 tokenizer 无关的近似值，不等于模型的精确 Token 数。
- 内置 smoke 只有两个小型 Python 用例，100% 不代表对大型真实仓库同样有效。

## License

本项目当前未声明开源许可证；如需公开发布，请先选择并添加合适的 LICENSE。
