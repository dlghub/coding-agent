# PatchPilot 端到端评测

每个用例包含 `case.json` 和一个会被复制到临时目录的 `workspace/`。
基线测试必须失败；PatchPilot 返回成功且修复后测试通过时，该用例才计为成功。

运行全部用例：

```bash
patchpilot eval
```

保留评测工作区用于排查：

```bash
patchpilot eval --keep-workspaces
```

评测会调用真实模型并产生 API 消耗，结果写入 `eval-results/`。
