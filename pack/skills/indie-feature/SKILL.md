---
name: indie-feature
description: 独游模式（小规模游戏）的功能开发：先把可扩展的框架立起来，再按纵向切片逐项实现，最后写功能说明。在用户提到独游模式、独立游戏、小游戏框架、先搭框架再做功能，或 workflow.yaml 的 mode 为 indie 时使用。
---

# 独游模式功能开发

用于个人 / 小团队的 Unity 小型游戏：功能少、迭代快、没有服务端和独立评审环节，但代码要经得起后续加内容。所以顺序是**先立框架，再做功能**：先有一套能承接新玩法的骨架（生命周期、事件、状态、配置、存档），再按纵向切片往里填。

`.bulings/workflow.yaml` 的 `mode` 为 `work` 时改用 `work-feature`，不要在这里做公司工程的流程。

## 配置

读取工程根目录的 `.bulings/workflow.yaml`。没有文件时：`mode` 为 `work`，开发说明写 `Docs/AI/DevSpecs/{feature}.md`，功能说明写 `Docs/AI/Features/{feature}.md`。

还没有策划案时，先用 `indie-design` Skill（命令行 `bulings design`）从玩法灵感迭代出一份：按玩法、剧情、风格、流程逐轮给开发者选项，选完定稿，再把定稿的策划案当作 `--design` 输入拿到这里做功能。策划案里没定下来的地方，在「拆切片」时变成 `blocked` 任务并写清缺什么。

独游相关：

```yaml
indie:
  framework:
    enabled: true                          # false 时不做框架阶段
    plan: .bulings/indie/framework.json    # 框架清单，Agent 写，工作流校验
    doc: Docs/AI/Frameworks/{game}.md      # 框架文档，{game} 取工程目录名
    paradigm: ""                           # 留空按 frameworks.md 选型；填了就照它做
```

`project` 里的空字符串和空数组表示未配置。未配置的项从工程里看目录、命名空间和 asmdef。

`protectedPaths` 里的文件不要改。不创建 git commit。不改 `.meta` 的 guid。不启动 Unity 批处理编译。

## Unity MCP

配置了 Unity MCP 并且连得上时，可以用它读工程现状、刷新编译、读控制台、在编辑器里接线。用法和边界见 [unity-mcp.md](../work-feature/unity-mcp.md)。连不上就如实说，不要假装验证过。

## 知识库

项目约束里如果给出了知识库地图，开工前先读它，再读它指向的约定和架构。知识库和代码不一致时以代码为准。建立和维护见 `knowledge-base` Skill。

## 听提示选阶段

- 点名框架：只做「建立框架」。
- 点名分析或切片：只做「拆切片」。
- 点名任务编号：只实现该切片。
- 点名功能说明：只写功能说明。
- 都没点名：按 建立框架 → 拆切片 → 逐个实现 → 功能说明 的顺序自己做完，一次只实现一个切片。

命令行每一轮都会点名阶段，不要提前做下一阶段。

## 建立框架

只在还没有可用框架时做（`framework.json` 不存在、不合法，或 `status` 还是 `draft`）。这一阶段**不写玩法功能**。

1. 先读 [frameworks.md](frameworks.md)：选型、最小基线、目录与程序集约定、反模式。
2. 再看工程现状：已有代码、程序集、`project.architecture` / `project.ui`。工程已有范式就服从它，不为了"规范"重写已有代码。
3. 选一个**够用就停**的范式：默认零外部依赖的轻量自建基线。不要为了框架引入需要联网安装的包，也不要一上来就做 ECS、事件溯源这类超规格结构。
4. 先目录与 asmdef，再逐个系统落地最小可运行实现：启动与生命周期、服务注册、事件、状态、配置、存档，需要时才加对象池、音频、输入、场景加载、UI 接入。
5. 每个系统落地后写进 `framework.json` 的 `systems`（`id` 短、稳定、后面切片要引用；`paths` 写真实目录或文件；没做完的 `status` 写 `pending`）。
6. `extensionPoints` 至少回答四件事：怎么加一个新状态、怎么加一个新事件、怎么加一项新配置、怎么给存档加一个字段。这些是后面切片唯一允许挂载的地方。
7. 按 [framework-template.md](framework-template.md) 写框架文档到 `doc` 指定的路径。
8. 全部系统可运行后，把 `framework.json` 的 `status` 改成 `done`。留空壳（只有类名、没有职责）不算完成。
9. MCP 可用时刷新编译并读控制台，确认骨架没有编译错误。

`framework.json` 示例：

```json
{
  "game": "tower-defense",
  "paradigm": "轻量自建：Bootstrap + EventBus + 状态机",
  "root": "Assets/_Game",
  "assemblies": ["Game.Core", "Game.Features"],
  "systems": [
    {
      "id": "bootstrap",
      "title": "启动与生命周期",
      "paths": ["Assets/_Game/Core/Bootstrap"],
      "status": "done",
      "notes": "GameBootstrap 是唯一入口"
    }
  ],
  "extensionPoints": [
    {
      "name": "EventBus",
      "howTo": "定义 GameEvent 子类，Send/Subscribe",
      "path": "Assets/_Game/Core/Events/EventBus.cs"
    }
  ],
  "conventions": ["新功能代码放 Assets/_Game/Features/<Feature>/", "跨模块通信只走 EventBus"],
  "status": "done"
}
```

`status` 只有 `draft`、`done`；系统状态只有 `pending`、`done`。校验不过就修到过为止。

## 拆切片

不写玩法代码。

1. 读策划案，读 `framework.json` 和框架文档，确认这次要挂在哪几个扩展点上。
2. 按**纵向切片**拆：一项任务 = 一条能自己验收完的能力（数据、逻辑、表现、接线留在同一切片）。不要按「先数据层再界面」这种技术层拆。
3. 每项任务必须写 `framework`：取值来自 `systems[].id` 或 `extensionPoints[].name`。要加框架里还没有的东西，写 `"new: 一句话说明"`，实现阶段再登记。
4. 同一能力的任务用同一个 `slice` 名；`dependsOn` 写真实前置，不写"看起来有依赖"。
5. 一项任务只做一块能看完的改动：一个脚本、一处接线，或一个数据类。
6. 无论开不开发说明，都写 `.bulings/runs/<slug>/tasks.json`。

```json
{
  "feature": "功能名",
  "designDoc": "策划案相对工程的路径",
  "prefabs": [],
  "tasks": [
    {
      "id": "T1",
      "title": "一句话",
      "slice": "放置炮塔",
      "goal": "这一项完成什么",
      "dependsOn": [],
      "files": ["Assets/_Game/Features/Tower/TowerPlacer.cs"],
      "prefabNodes": [],
      "framework": ["EventBus", "new: 塔位格子坐标服务"],
      "acceptance": ["可核对的完成标准"],
      "status": "pending"
    }
  ]
}
```

`status` 只能是 `pending`、`in_progress`、`done`、`blocked`。阻塞时增加 `blockedReason`。没写 `framework` 或被引用到框架里不存在的挂载点时，命令行会在写代码前停下。

开发说明开启时，按 [slice-spec-template.md](slice-spec-template.md) 写到指定路径。任务用 `- [ ]`。

## 实现一个切片

只做这一项要动的文件。

1. 在 `tasks.json` 里把该任务标成 `in_progress`；开发说明同步状态。
2. 先复用：事件走 `EventBus`，状态走状态机，配置走 SO，存档走存档系统。不要为这一个切片另造一套。
3. 确实需要新扩展点时，在 `framework.json` 的 `extensionPoints` **追加**一项（`name` / `howTo` / `path`），不改已有项，不把 `status` 改回 `draft`。
4. 遇到 `protectedPaths`，或必须改 `.meta` guid 才能完成时，标 `blocked` 并写 `blockedReason`，然后停止。
5. 做完把任务标 `done`，开发说明把 `- [ ]` 改成 `- [x]`。
6. 做不到且不应该猜测时标 `blocked`，复选框保持未勾，写上原因。

提示如果说明这是中断后的重做，或这项上次已阻塞：只修补这一项，不要重做已经 `done` 的任务。

## 功能说明

只在功能说明开启、且任务全部是 `done` 时写。按 [feature-doc-template.md](feature-doc-template.md)，依据实际改过的代码。不要把任务清单再抄一遍，这一阶段不要再改玩法代码。

写清挂载了哪些框架点、新增了哪些扩展点、下一个功能该从哪里接。切片里用过 `new:` 但 `framework.json` 还没登记的，先在扩展点里补登记。

提示点名要维护知识库时，写完功能说明后按 `knowledge-base` Skill 的 update 动作只更新受影响的页面。
