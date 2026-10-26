---
name: work-feature
description: 根据策划案和 Unity 预制体整理开发任务并逐项写代码，可生成开发说明和维护用功能说明。在用户提到策划案、预制体、开发说明、功能说明、工作模式或 Unity 功能开发时使用。
---

# 工作模式功能开发

用于公司 Unity 工程。输入是一份策划案和相关预制体。先列出可逐项完成的任务，再写代码，并按配置决定要不要留下两份中文文档。

`.bulings/workflow.yaml` 的 `mode` 为 `indie` 时停止，不要在这里做独游流程。

## 配置

读取工程根目录的 `.bulings/workflow.yaml`。没有文件时：`mode` 为 `work`，开发说明写到 `Docs/AI/DevSpecs/{feature}.md`，功能说明写到 `Docs/AI/Features/{feature}.md`，两份都生成。

提示里如果写了文档路径或开关，以提示为准。

`project` 里的空字符串和空数组表示未配置。未配置的项从工程里看目录、命名空间和 asmdef，写进开发说明的「推断的项目约定」。不要把未配置项写成必须遵守的规范。

`protectedPaths` 里的文件不要改。不要创建 git commit。不要改 `.meta` 的 guid。不要启动 Unity 批处理编译。

## 知识库

项目约束里如果给出了知识库地图，分析前先读它，再读它指向的约定和架构。做具体功能时，按地图打开对应页面，并先在地图列出的代码目录里找。知识库和代码不一致时以代码为准，把差异写进开发说明。

## 听提示选阶段

- 点名分析，或只要开发说明：只做分析。
- 点名任务编号：只实现该任务。
- 点名功能说明或维护文档：只写功能说明。
- 都没点名：按顺序自己做完，一次只实现一个任务。做完一项并更新状态后，再取下一项。

命令行每一轮都会点名阶段。不要提前做下一阶段。

## 分析

不要写玩法代码。

1. 读策划案。如果项目约束给出了知识库地图，先按「知识库」一节读完再拆任务。
2. 读预制体前先看 [prefab-reading.md](prefab-reading.md)。分析提示里给出的预制体。策划案点名、且工程里真实存在的其他预制体可以一并看。
3. 策划和预制体对不上时不要脑补。该任务 `status` 写 `blocked`，并写 `blockedReason`。
4. 按依赖排序。一项任务只做一块能看完的改动：一个脚本、一处预制体绑定，或一个数据类。
5. 无论开不开发说明，都写 `.bulings/runs/<slug>/tasks.json`。提示里有路径就用那个路径。

`tasks.json`：

```json
{
  "feature": "功能名",
  "designDoc": "策划案相对工程的路径",
  "prefabs": ["预制体相对工程的路径"],
  "tasks": [
    {
      "id": "T1",
      "title": "一句话",
      "goal": "这一项完成什么",
      "dependsOn": [],
      "files": ["Assets/Scripts/Example.cs"],
      "prefabNodes": ["Canvas/Panel"],
      "acceptance": ["可核对的完成标准"],
      "status": "pending"
    }
  ]
}
```

`status` 只能是 `pending`、`in_progress`、`done`、`blocked`。`id` 不要重复。阻塞时增加 `blockedReason`。

开发说明开启时，按 [dev-spec-template.md](dev-spec-template.md) 写到指定路径。任务用 `- [ ]`，并写上编号、目标、依赖、脚本或节点、完成标准、状态。

已阻塞的任务如果后面还有不依赖它的 `pending` 任务，先做那些任务。轮到阻塞项时停下来问用户。

## 实现一个任务

只做这一项要动的文件。

1. 在 `tasks.json` 里把该任务标成 `in_progress`。开发说明里把状态改成 `in_progress`。
2. 遇到 `protectedPaths`，或必须改 `.meta` guid 才能完成时，标 `blocked` 并写 `blockedReason`，然后停止。
3. 做完后把 `tasks.json` 标成 `done`。开发说明把 `- [ ]` 改成 `- [x]`，状态改成 `done`。
4. 做不到且不应该猜测时，标 `blocked`，复选框保持未勾，写上原因。

提示如果说明这是中断后的重做，或这项上次已阻塞：只修补这一项，不要重做已经 `done` 的任务。

本轮提示点了任务编号时，做完就停。没有点名阶段时，更新状态后再取下一项。

## 功能说明

只在功能说明开启、且任务全部是 `done` 时写。按 [feature-doc-template.md](feature-doc-template.md)，依据实际改过的代码。不要把任务清单再抄一遍。这一阶段不要再改玩法代码。
