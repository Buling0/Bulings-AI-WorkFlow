---
name: buling-ai
description: >-
  用 /buling-ai 或 /BulingAI 按工作模式做功能。用户贴上策划案和预制体，或写出
  --design、--prefab、--name 时使用。
disable-model-invocation: true
---

# BulingAI

在当前 Unity 工程里做功能。先读 `.cursor/skills/work-feature/SKILL.md` 并按它执行。`.bulings/workflow.yaml` 的 `mode` 为 `indie` 时改读 `.cursor/skills/indie-feature/SKILL.md`。不要另起 `bulings run`。当前对话就是执行者。

当前目录没有 `Assets` 和 `ProjectSettings` 时停下来，请用户用 Cursor 打开 Unity 工程后再发这条指令。

## 输入

同一条消息里两种写法都可以，也可以混用。`--prefab` 可以写多次。

```text
--design <策划案路径>
--prefab <预制体路径>
--name <功能名>
```

直接贴入时：

- 策划案是去掉参数行之后的正文，或消息里的策划文档。
- 预制体是 `@` 引用、附件、以 `.prefab` 结尾的路径，或整段以 `%YAML` 开头的预制体文本。可以有多个。

## 整理成路径

- 有 `--design` 或策划文档路径：用那个路径。
- 只有贴进来的正文：写入策划案文件。工程里已有 `docs/AI` 或 `Docs/AI` 时跟已有目录，否则用 `docs/AI/Designs/<功能名>.md`。已存在则覆盖这一次贴入的正文，并在回复里写明路径。
- 预制体优先用工程里的 `.prefab`。只有 YAML、对不上已有文件时，不要写入 `Assets`，停下来问要改哪一个预制体。
- 功能名用 `--name`。没有则用策划案文件名（不含扩展名）。贴入正文时用第一个一级标题；还没有就用 `未命名功能`，并在回复里写明这个名字。

策划案和至少一个预制体都缺时停下来，说明缺什么。不要猜内容。

## 阶段

消息里点了阶段或任务编号时，只做那一段，规则与对应 Skill 相同。没点名就从分析做到完成，一次一项任务。
