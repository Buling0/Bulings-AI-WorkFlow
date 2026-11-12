# Bulings AI WorkFlow

个人 Unity 开发工作流。工作模式：读策划案和预制体，整理成可逐项完成的任务，再写代码。独游模式面向小规模游戏：第一次先立框架，再按纵向切片做功能，每个切片都要挂在框架的扩展点上。开发说明和完成后的功能说明都可以单独开关、单独指定路径。

两条入口用同一份 Skill。装进 Unity 工程后，可以在 Cursor 对话里做，也可以用命令行在本机拉起 Agent。

完整的上手流程见 [使用指南](docs/使用指南.md)。

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
bulings run --project <Unity工程> --design <策划案> --prefab <预制体> [--prefab <预制体> ...] [--name <功能名>] [--dev-spec <路径>] [--feature-doc <路径>] [--no-dev-spec] [--no-feature-doc] [--no-framework] [--model <模型>]
```

Agent 在本机运行，工作目录是 Unity 工程。模型默认是 `composer-2.5`，可以用 `--model` 或 `workflow.yaml` 的 `model` 覆盖。`{feature}` 来自 `--name`，否则用策划案文件名。

- 任务列表写到 `.bulings/runs/<功能名>/tasks.json`。关掉开发说明时也会写它。
- 开发说明默认是 `Docs/AI/DevSpecs/<功能名>.md`。
- 任务全部完成后，功能说明默认是 `Docs/AI/Features/<功能名>.md`。
- 每一轮只交给 Agent 一项任务。这项结束后如果还不是 `done`，命令就停下来。
- `mode: work` 时至少要给一个 `--prefab`；`mode: indie` 时可以不给。

同一功能还有未完成的运行时，`run` 不会再开一个 Agent。接着做：

```powershell
bulings resume --project <Unity工程> --run <功能名>
```

不依赖阻塞项的任务会先做。轮到阻塞项时停下。`resume` 会把当前这项改回 `in_progress` 再做，原来的阻塞原因会带进提示。中断留下的 `in_progress` 会重做那一项。`resume` 用运行建立时的模式，`workflow.yaml` 的 `mode` 被改过会先报错。

## 独游模式

`workflow.yaml` 写 `mode: indie` 就用独游流程。它比工作模式多两道阶段：先是**策划案迭代**（`bulings design`，见下一节），然后是 **run 里的框架阶段**：

1. **建立框架**：工程里还没有可用的 `.bulings/indie/framework.json` 时，先落一套能承接新玩法的骨架（启动与生命周期、服务、事件、状态、配置、存档），写框架清单和框架文档。这一阶段不写玩法功能。
2. **拆切片**：按纵向切片拆功能，一项任务 = 一条能自己验收完的能力。每项必须写 `framework`，取值来自框架的系统 id 或扩展点名；框架里还没有的写 `new: <说明>`。
3. **实现切片**：一轮一项。优先复用已有扩展点，确实需要新的就往框架清单里追加登记。
4. **功能说明**：写清挂载了哪些框架点、新增了哪些扩展点、下一个功能从哪接。

```powershell
bulings run --project <Unity工程> --design <策划案> [--name <功能名>]
```

- 框架清单 `.bulings/indie/framework.json`（工程级，Agent 写、工作流校验）；框架文档默认 `Docs/AI/Frameworks/<工程目录名>.md`。
- 框架没写好（不存在、不合法，或 `status` 仍是 `draft`）时命令退出 2，不进入功能代码。
- 已经有可用框架时直接进分析和实现，只对登记过但磁盘上找不到的路径打警告。
- `--no-framework` 或 `indie.framework.enabled: false` 跳过框架阶段，切片仍然要写 `new:` 登记扩展点。
- 切片引用了框架里不存在的挂载点时，在写代码前就停下，并列出可用挂载点。
- 独游模式下 `bulings split` 会拒绝执行；`bulings kb` 可以照常用。

框架选型、最小基线、反模式和产物格式见 [docs/独游模式说明.md](docs/独游模式说明.md)，装进工程的规则在 `.cursor/skills/indie-feature/`。

## 策划案迭代

只有玩法灵感、还没有策划案时，先跑这条流程。一轮推进一个维度（玩法 → 剧情 → 风格 → 流程 → 收尾），每轮给你几个有代价的选项，选完再写厚一点，最后定稿：

```powershell
bulings design --project <Unity工程> --idea <灵感文件或一段文字> [--name <策划案名>]
bulings design --project <Unity工程> --name <策划案名> --decide G1[,S2]
bulings design --project <Unity工程> --name <策划案名> --note "想再休闲一点"
bulings design --project <Unity工程> --name <策划案名> --finish
```

- 每轮结束会把当前选项和「下一步该敲什么」打印出来；不带参数再跑一次可以只看进度。
- `--idea` 既可以是文件路径，也可以直接是一段文字（这时要给 `--name`）。
- 选项 id 用阶段字母加序号：玩法 `G1`、剧情 `S1`、风格 `A1`、流程 `F1`。选了不存在的 id 会直接拒绝并列出可用选项。
- 工作流会校验这一轮真的推进了：`round` 必须是上一轮 +1、迭代中的一轮至少 2 个选项、选过的 id 必须写进 `chosen`、定稿时 `status` 必须是 `done` 且不再给选项。
- 定稿后打印 `bulings run --design` 的下一步命令，直接进入框架和功能开发。

产物：设计状态 `.bulings/design/<策划案名>/design.json`、灵感原文同目录 `brief.md`、策划案正文默认 `Docs/AI/GameDesigns/<策划案名>.md`。规则在 `.cursor/skills/indie-design/`。

## 接入 Unity MCP

`bulings init` 会按 `workflow.yaml` 的 `unity.mcp` 把 Unity MCP 服务合并写入 `<工程>/.cursor/mcp.json`（已有同名条目不覆盖，`enabled: false` 则不写）。默认指向 `http://localhost:8080/mcp`；用 stdio 启动的服务，填 `command`/`args` 并清空 `url`。你需要先在 Unity 里安装并启动所选的 MCP 插件。

配置好后，Cursor 对话和命令行 Agent 都能用 MCP 刷新编译、读控制台、在编辑器里绑定预制体；规则见 Skill 里的 `unity-mcp.md`。分析阶段只读，连不上时 Agent 会如实说明，不会假装验证。

## 前端分离

策划案同时含客户端和服务端内容时，先把客户端部分分出来：

```powershell
bulings split --project <Unity工程> --design <策划案> [--name <功能名>] [--output <路径>] [--model <模型>]
```

Agent 按 `client-split` Skill 逐条归类，写出客户端需求文档，默认 `Docs/AI/ClientSpecs/{feature}.md`（`clientSplit.path` 可改）。文档含客户端需求清单（带编号和策划案出处）、服务端依赖、依赖的配置、涉及的预制体、待确认、已排除。归属不明的条目进「待确认」，不会自行归入客户端。

之后把这份文档当策划案：`bulings run --design <客户端需求文档> --prefab ...`。在 Cursor 里也可以直接说“把这份策划案的客户端部分分离出来”。

## AI 知识库

知识库是写给 Agent 看的工程说明：地图、约定、架构、模块页，默认放在 `Docs/AI/Knowledge/`（`knowledge.root` 可改）。

```powershell
bulings kb --project <Unity工程> --action init
bulings kb --project <Unity工程> --action update --name <功能名>
bulings kb --project <Unity工程> --action check
```

- `init`：读代码建立知识库，已有页面只补缺，不覆盖人工内容。
- `update`：功能做完后，按该功能的 `tasks.json` 只更新受影响的页面。
- `check`：只读核对，把过期、缺失、冲突、孤儿页写到 `CHECK.md`，由你决定是否修复。

建好后（`MAP.md` 存在），`run` 会自动把地图交给 Agent，并在功能说明写完后提示它维护受影响的页面。`knowledge.enabled: false` 可整体关闭。内容以代码为准，读不到证据的写进「待核实」。

## 配置

`.bulings/workflow.yaml` 里，空字符串和空数组表示未配置。工作流会从工程推断目录、命名空间和程序集，写进开发说明的「推断的项目约定」，不把这些推断当成必须遵守的规范。

```yaml
mode: work              # work 或 indie
model: composer-2.5
unity:
  mcp:
    enabled: true
    server: unity
    url: http://localhost:8080/mcp
    command: ""
    args: []
knowledge:
  enabled: true
  root: Docs/AI/Knowledge
clientSplit:
  path: Docs/AI/ClientSpecs/{feature}.md
indie:
  framework:            # 仅 mode: indie 时使用
    enabled: true
    plan: .bulings/indie/framework.json
    doc: Docs/AI/Frameworks/{game}.md   # {game} 取工程目录名
    paradigm: ""       # 留空由 Agent 按 frameworks.md 选型
  design:               # 仅 mode: indie 时使用，bulings design 的配置
    path: Docs/AI/GameDesigns/{feature}.md
    rounds: 4          # 建议轮次：玩法 → 剧情 → 风格 → 流程
    options: 3         # 每轮给几个选项，2-5
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

`mode: work` 是默认值，行为和之前一样。`mode: indie` 时先用 `bulings design` 迭代出策划案，`run` / `resume` 再走独游流程（先立框架，再按切片做功能），详见上文和 [独游模式说明](docs/独游模式说明.md)。

## 退出码

- `0`：完成
- `1`：没有启动（参数、配置、密钥，或启动 Agent 失败）
- `2`：已经启动但没有做完（这一轮失败或被取消、任务阻塞，或 `tasks.json` / `framework.json` / `design.json` 不合法）

## 本版本不做的事

不调用 Unity 批处理编译（编辑器内的 MCP 刷新不受此限），也不自动创建 git commit。
