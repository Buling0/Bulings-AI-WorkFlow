# Bulings AI WorkFlow

个人 Unity 开发工作流。当前版本是工作模式：读策划案和预制体，整理成可逐项完成的任务，再写代码。开发说明和完成后的功能说明都可以单独开关、单独指定路径。独游模式只保留入口，调用时会停止。

两条入口用同一份 Skill。装进 Unity 工程后，可以在 Cursor 对话里做，也可以用命令行在本机拉起 Agent。

## 准备

需要 Python 3.10 或更高版本，以及环境变量 `CURSOR_API_KEY`（Cursor Dashboard → Integrations 里的用户 API key）。命令行使用 Cursor Python SDK，只在本机运行，工作目录是 Unity 工程，并且只加载该工程里的项目配置。

在仓库根目录：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

激活虚拟环境后可以直接用 `bulings`。未激活时用：

```powershell
.\.venv\Scripts\python.exe -m bulings
```

运行前设置密钥：

```powershell
$env:CURSOR_API_KEY = "cursor_..."
```

## 装进 Unity 工程

目标目录要有 `Assets` 和 `ProjectSettings`。

```powershell
bulings init --project <Unity工程>
```

这会把 Skill 复制到 `<工程>/.cursor/skills/`。如果还没有 `<工程>/.bulings/workflow.yaml`，会写入一份示例。再次执行会更新 Skill，不会覆盖已经存在的配置。

## 在 Cursor 里用

用 Cursor 打开这个 Unity 工程，直接给出策划案和预制体路径。工作模式会先分析，再一次做一项任务，全部完成后再写功能说明。

提示里如果点了阶段或任务编号，就只做那一段。例如只写开发说明，或只重做 `T3`。

## 命令行

```powershell
bulings run --project <Unity工程> --design <策划案> --prefab <预制体> [--prefab <预制体> ...] [--name <功能名>] [--dev-spec <路径>] [--feature-doc <路径>] [--no-dev-spec] [--no-feature-doc] [--model <模型>]
```

Agent 在本机运行，工作目录是 Unity 工程。模型默认是 `composer-2.5`，可以用 `--model` 或 `workflow.yaml` 的 `model` 覆盖。`{feature}` 来自 `--name`，否则用策划案文件名。

- 任务列表写到 `.bulings/runs/<功能名>/tasks.json`。关掉开发说明时也会写它。
- 开发说明默认是 `Docs/AI/DevSpecs/<功能名>.md`。
- 任务全部完成后，功能说明默认是 `Docs/AI/Features/<功能名>.md`。
- 每一轮只交给 Agent 一项任务。这项结束后如果还不是 `done`，命令就停下来。

同一功能还有未完成的运行时，`run` 不会再开一个 Agent。接着做：

```powershell
bulings resume --project <Unity工程> --run <功能名>
```

不依赖阻塞项的任务会先做。轮到阻塞项时停下。`resume` 会把当前这项改回 `in_progress` 再做，原来的阻塞原因会带进提示。中断留下的 `in_progress` 会重做那一项。

## 配置

`.bulings/workflow.yaml` 里，空字符串和空数组表示未配置。工作流会从工程推断目录、命名空间和程序集，写进开发说明的「推断的项目约定」，不把这些推断当成必须遵守的规范。

```yaml
mode: work              # work 或 indie
model: composer-2.5
docs:
  devSpec:
    enabled: true
    path: Docs/AI/DevSpecs/{feature}.md
  featureDoc:
    enabled: true
    path: Docs/AI/Features/{feature}.md
project:
  codeRoots: []
  namespaces: []
  asmdefs: []
  ui:
    framework: ""
    binding: ""
    notes: ""
  architecture: ""
  style: ""
  protectedPaths: []    # 这些路径不允许改
```

`mode: indie` 时，命令行会在创建或恢复 Agent 之前停止。

## 退出码

- `0`：完成
- `1`：没有启动（参数、配置、密钥、独游模式，或启动 Agent 失败）
- `2`：已经启动但没有做完（这一轮失败或被取消、任务阻塞，或没有合法的 `tasks.json`）

## 本版本不做的事

不实现独游模式的开发流程，不调用 Unity 批处理编译，也不自动创建 git commit。
