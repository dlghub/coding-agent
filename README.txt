PatchPilot - 本地编码智能体

PatchPilot 是一个使用 Python 实现的本地编码 Agent。用户可以通过自然语言描述编码需求，
Agent 会在受控工作区内自主读取文件、搜索代码、修改文件、执行命令并运行测试，
再根据真实执行结果继续分析和修复。

核心功能：

1. 单次编码任务与持续多轮对话
2. 文件读取、文本搜索、增量补丁和命令执行工具
3. 工作区路径保护、敏感文件保护和操作审批
4. Docker 命令沙箱与资源限制
5. 模型超时、协议异常和失败工具调用恢复
6. 会话日志、上下文压缩和 Checkpoint 断点恢复
7. 只读代码分析模式
8. 自动化测试与端到端编码能力评测
9. GitHub Actions 多 Python 版本测试和安装包构建

主要命令：

patchpilot run       执行单次编码任务
patchpilot chat      启动持续多轮编码会话
patchpilot resume    恢复异常中断的任务
patchpilot eval      运行端到端评测

项目使用 OpenAI-compatible Chat Completions API。

GitHub 仓库：
https://github.com/dlghub/coding-agent

更完整的安装方法、配置说明、命令示例和架构介绍请查看项目根目录中的 README.md。
