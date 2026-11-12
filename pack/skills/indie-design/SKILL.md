---
name: indie-design
description: 独游模式的策划案迭代：从一段玩法灵感出发，按玩法、剧情、风格、游戏流程逐轮给出开发者选项，边选边把策划案写厚，最后定稿成可以直接开发的一版。在用户提到策划案、GDD、玩法灵感、立项、把想法整理成策划案，或运行 bulings design 时使用。
---

# 独游策划案迭代

输入是**一段玩法灵感**（可以是几句话），输出是**一份能直接拿去做功能的策划案**。中间按轮次推进：每一轮只把一个维度想深，给开发者 3 个真正不同的选项，选完再把结果写进策划案。

这件事的价值不在"写得多"，而在**每个决定都是开发者选的、而且选项是真的有代价**。所以每轮都必须给选项，不能自己替开发者拍板。

`.bulings/workflow.yaml` 的 `mode` 不是 `indie` 时不要用本 Skill。

## 配置

```yaml
indie:
  design:
    path: Docs/AI/GameDesigns/{feature}.md   # 策划案正文
    rounds: 4                                # 建议轮次（玩法→剧情→风格→流程）
    options: 3                               # 每轮给几个选项
```

## 文件

- 灵感原文：`.bulings/design/<策划案名>/brief.md`（只读，不要改写）
- 设计状态：`.bulings/design/<策划案名>/design.json`（**每轮必须更新**，工作流会校验）
- 策划案正文：`indie.design.path` 指定的路径（每轮必须更新）

不要写代码、不要建 `tasks.json`、不要动工程里已有的资源。

## 一轮做三件事

### 1. 落实上一轮的选择

- 上一轮开发者选的选项，写进策划案对应章节，并在 `design.json` 的 `chosen` 里追加一条。
- 上一轮没选、只给了 `--note` 的，按说明调整，`chosen` 里记录这一轮（`ids` 可以是空数组）。
- 上一轮没定、这轮也定不下来的，留在「还没定的地方」，写清缺什么、什么时候必须定。不要用空话填坑。

### 2. 推进当前维度

轮次顺序是 **玩法核心循环 → 剧情与世界观 → 美术风格与音频 → 游戏流程与关卡节奏 → 收尾（数值、范围、里程碑）**。当前该推哪个维度，提示词里会写；有充分理由时可以提前或跳过一个维度，但要在策划案里说明原因。

每个维度问什么、问到多深，看 [dimensions.md](dimensions.md)。

### 3. 给出本轮选项

给 `indie.design.options` 个选项（默认 3 个），写进 `design.json` 的 `options`，同时在策划案对应章节末尾列出，方便在编辑器里看。

选项的硬要求：

- **互斥**：选了一个就基本排除另一个。不要给"都要""看情况""结合两者"这类假选项。
- **有代价**：每个选项都要写 `tradeoff`，说清它牺牲了什么（成本、上手门槛、内容量、可扩展性、美术工作量）。
- **能改变游戏长什么样**：选项之间玩家体验应该明显不同，不是同一件事的措辞差异。
- **落在工程做得到的范围里**：项目约束会一起给，选项不要假设做不到的技术或美术资源。
- **id 稳定可点**：阶段字母 + 序号（玩法 `G1/G2`、剧情 `S1/S2`、风格 `A1/A2`、流程 `F1/F2`），本轮内唯一，不要和上一轮重名。

## design.json

每轮整体重写这个文件（不是追加），字段全部必填（`chosen`、`options` 可以为空数组）：

| 字段 | 说明 |
| --- | --- |
| `slug` | 策划案名（英文/数字/连字符），和目录名一致 |
| `title` | 中文标题 |
| `round` | 本轮轮次，第一轮是 1，之后每轮 +1 |
| `stage` | `core` / `story` / `style` / `flow` / `polish` / `done` |
| `status` | `iterating`（还在迭代）或 `done`（定稿） |
| `dimensions` | 必须含 `gameplay`、`story`、`style`、`flow` 四项，每项 `{summary, confirmed}` |
| `options` | 本轮选项：`{id, dimension, label, detail, tradeoff}`，`dimension` 取四个维度之一 |
| `chosen` | 选择历史：`{round, ids, note}` |

```json
{
  "slug": "tower-defense",
  "title": "塔防 + 建造",
  "round": 2,
  "stage": "story",
  "status": "iterating",
  "dimensions": {
    "gameplay": { "summary": "白天建造、夜里守塔的循环", "confirmed": true },
    "story": { "summary": "", "confirmed": false },
    "style": { "summary": "", "confirmed": false },
    "flow": { "summary": "", "confirmed": false }
  },
  "options": [
    {
      "id": "S1",
      "dimension": "story",
      "label": "无剧情，纯系统驱动",
      "detail": "没有角色和台词，靠关卡与数值变化推进",
      "tradeoff": "省一半内容量，但缺少记忆点，宣传不好讲"
    }
  ],
  "chosen": [{ "round": 1, "ids": ["G1"], "note": "" }]
}
```

校验规则（不满足工作流会拒绝这一轮）：

- `round` 必须是上一轮 +1，第一轮必须是 1。
- `status` 是 `iterating` 时，`options` 至少 2 个。
- `status` 是 `done` 时，`options` 必须为空。
- 开发者通过 `--decide` 选的 id，必须出现在本轮 `chosen` 里。

## 策划案正文

按 [design-template.md](design-template.md) 写。要求：

- 一页概览能让人在 30 秒内说出"这游戏在玩什么、为什么好玩"。
- 核心循环写成玩家视角的动作序列，不是系统名词堆砌。
- 剧情部分在有剧情时才展开；无剧情就把"为什么不做剧情"写清。
- 风格部分写能落到美术和音频上的描述（2D/3D、视角、色板倾向、参考气质、音乐基调），不要写"画面精美"。
- 流程部分写一次完整的游戏进程：开局 → 中期 → 收尾 → 重开，包括节奏和关卡数量级。
- 每轮把正文写厚一点，但不要把选项列表抄进去。

## 定稿

`--finish` 那一轮：

1. 不再给新选项，`options` 清空，`stage` 和 `status` 都写 `done`。
2. 按骨架补齐所有章节，四个维度都写 `summary` 并 `confirmed: true`；确实没定的放进「还没定的地方」。
3. 「范围与里程碑」按**功能粒度**给，能直接对上下一步的 `bulings run`。
4. 定稿后不再改正文，除非开发者明确要求。

## 红线

- 不写代码、不建 `tasks.json`、不改已有代码和资源。
- 不改 `protectedPaths` 里的路径，不改 `.meta` 的 guid，不建 git commit。
- 不替开发者做选择：有分歧就变成选项，而不是在正文里直接定。
