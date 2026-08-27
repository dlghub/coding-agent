# PatchPilot

PatchPilot 是一个使用 Python 实现的本地编程智能体。它通过
OpenAI-compatible 模型接口进行 Tool Calling，并自行管理对话历史、
本地工具执行、错误恢复和循环终止。

## 当前功能

- 浏览工作区目录
- 按行读取 UTF-8 文件
- 使用 ripgrep 搜索代码
- 通过精确文本匹配修改文件
- 在工作区执行测试和检查命令
- 限制工作区路径访问
- 支持只读运行模式
- 支持模型请求重试
- 终端展示 Agent 执行过程

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"