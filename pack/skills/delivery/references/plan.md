# 计划阶段规则

协调者维护 `04-plan/README.md`（计划总览）与 `04-plan/slice-plan.json`（切片方案草稿）。批准后的方案在 `slice-plan.approved.json`，供后续启动切片使用。

## 计划总览正文

前置之后须包含：

```markdown
# 计划

## 拆分

- 结果：<可单独验收的结果>
  切片：<slice-id>
  场景：<需求场景名>
  理由：<为什么能分开验收，或为什么和另一结果放在一起>

## 共同依赖

没有则写「无」。有则写明决定和依据来自设计总览的哪一个变化名。
```

- 编码、配置和测试**不要**因文件不同就拆成多个切片。
- 两个结果必须一起改同一责任时，写成一个切片，并在「理由」里说明。
- 每个 `slice-plan.json` 里的切片标识必须在「拆分」中出现一次；每个需求场景名至少被一个切片的「场景」引用。

## 依赖

第一次确认计划总览变更前，运行 `bulings delivery prepare-plan`，把计划总览的 `dependencies` 设为设计总览并记录其语义版本。

## 方案流程

1. `design-ready` 通过后再 `prepare-slice-plan` 生成草稿（若尚不存在）。
2. 编辑 `slice-plan.json` 与计划总览，使二者一致。
3. `check-slice-plan` 通过后，用返回的 `digest` 调用 `approve-slice-plan`。
4. 改草稿后须把 `version` 加 1 再批准；同版本摘要不同会被拒绝。
