---
name: delivery
description: 使用 Bulings 交付流推进需要分步实施和独立评审的 Unity 功能。仅在用户显式要求交付流、bulings delivery 或长任务交付时使用。
disable-model-invocation: true
---

# Bulings 交付流（协调者）

用于跨多轮、需要独立评审和最终验证的 Unity 功能。局部小改、单轮能做完的改动不要走本 Skill。

## 何时不用本 Skill

1. 用户**没有明确要求**走交付流、`bulings delivery` 或长任务交付时，改用 `work-feature`；若只是一点局部修改，停在普通编辑，**不要**运行 `bulings delivery init`。
2. `mode: indie` 时**不要启动 Agent**（含子 Agent）。`bulings delivery open` 与 `bulings delivery rules` 仍可查询。

## 对话范围

3. **当前对话只处理一个** `feature-id`。切换功能前请用户确认结束或另开对话。

## 进入流程

4. 进入时运行：

   ```powershell
   bulings delivery open --project <Unity工程根> --query <用户给的标题或标识片段>
   ```

   - **唯一匹配**：继续该交付项。
   - **多个匹配**：列出 `candidates` 里的标题，请用户选定后再用 `--query` 或 `--feature-id` 查状态。
   - **没有匹配**且用户已说明要做的功能：再运行 `bulings delivery init --project ... --feature-id ... --title ...`。
   - **没有匹配**且用户未给出功能目标：不要擅自 `init`，先问清。

5. 接着运行：

   ```powershell
   bulings delivery status --project <工程> --feature-id <标识>
   ```

   若 JSON 里 `documentErrors` 非空，先按错误修正档案或正文，再继续。

6. 读取协调者规则（**唯一来源**，不要在 Skill 里再写一份阶段说明）：

   ```powershell
   bulings delivery rules --project <工程> --action coordinator
   ```

   只使用返回 JSON 中 `rules[].body` 的正文。

## 推进方式

7. **一次只推进**状态与规则给出的**当前阶段**。阶段顺序：需求 → 调查 → 设计 → 计划 → 实施 → 验证。判断当前阶段：六份阶段总览里第一份仍含「待填写」的即为当前；若都已写过，停在验证并说明后续验收/封存命令可能尚未安装。

8. 禁止事项：不创建 git commit；不改 `.meta` guid；不启动 Unity 批处理；不修改 `workflow.yaml` 的 `protectedPaths`。

## 档案位置

正式材料仅在 `.bulings/deliveries/<feature-id>/` 下六段目录。本任务不调用 `confirm-change`；用户或后续流程改正文后，由对应命令登记语义变化。
