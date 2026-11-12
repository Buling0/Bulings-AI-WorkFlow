# 框架产物格式

框架阶段产出两份东西：机器读的 `framework.json`，和人读的框架文档。两份都要写，缺一份算没做完。

## 一、framework.json

路径由 `indie.framework.plan` 决定，默认 `.bulings/indie/framework.json`。工作流会严格校验，不合法就等于没写。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `game` | string | 是 | 游戏标识，一般用工程目录名 |
| `paradigm` | string | 是 | 采用的范式，一句话。例如"轻量自建：Bootstrap + EventBus + 状态机" |
| `root` | string | 是 | 代码根目录，相对工程根，例如 `Assets/_Game` |
| `assemblies` | string[] | 否 | 程序集名 |
| `systems` | object[] | 是 | 至少一项 |
| `systems[].id` | string | 是 | 短、稳定、唯一。后面切片的 `framework` 字段会引用它 |
| `systems[].title` | string | 是 | 一句话职责 |
| `systems[].paths` | string[] | 否 | 真实存在的目录或文件，相对工程根 |
| `systems[].status` | `pending` / `done` | 是 | 没做完就是 `pending` |
| `systems[].notes` | string | 否 | 入口类名之类的补充 |
| `extensionPoints` | object[] | 否 | 扩展点，越具体越好 |
| `extensionPoints[].name` | string | 是 | 切片引用时用的名字，例如 `EventBus`、`GameStateMachine` |
| `extensionPoints[].howTo` | string | 是 | 怎么用它新增东西，一句话能照做 |
| `extensionPoints[].path` | string | 否 | 相关文件 |
| `conventions` | string[] | 否 | 目录、命名、依赖方向的约定 |
| `status` | `draft` / `done` | 是 | 只有全部系统可运行才算 `done` |

示例：

```json
{
  "game": "tower-defense",
  "paradigm": "轻量自建：Bootstrap + EventBus + 状态机",
  "root": "Assets/_Game",
  "assemblies": ["Game.Core", "Game.Features"],
  "systems": [
    { "id": "bootstrap", "title": "启动与生命周期", "paths": ["Assets/_Game/Core/Bootstrap"], "status": "done" },
    { "id": "services", "title": "服务注册", "paths": ["Assets/_Game/Core/Services"], "status": "done" },
    { "id": "events", "title": "事件总线", "paths": ["Assets/_Game/Core/Events"], "status": "done" },
    { "id": "state", "title": "游戏状态机", "paths": ["Assets/_Game/Core/State"], "status": "done" },
    { "id": "config", "title": "SO 配置", "paths": ["Assets/_Game/Core/Config"], "status": "pending" }
  ],
  "extensionPoints": [
    { "name": "EventBus", "howTo": "定义 XxxEvent : GameEvent，用 EventBus.Send / Subscribe<T>，订阅处 OnDisable 解绑", "path": "Assets/_Game/Core/Events/EventBus.cs" },
    { "name": "GameStateMachine", "howTo": "新建 XxxState : IGameState，在 Bootstrap 里 Register 后 SwitchTo", "path": "Assets/_Game/Core/State/GameStateMachine.cs" },
    { "name": "Config", "howTo": "新建 XxxConfig : ScriptableObject，在 ConfigDatabase 里按 id 登记", "path": "Assets/_Game/Core/Config/ConfigDatabase.cs" },
    { "name": "SaveSystem", "howTo": "给 SaveData 加字段，读档时做兼容（没有兼容逻辑就不删改旧字段）", "path": "Assets/_Game/Core/Save/SaveSystem.cs" }
  ],
  "conventions": [
    "功能代码放 Assets/_Game/Features/<Feature>/，只依赖 Core",
    "跨模块通信只走 EventBus",
    "Core 不引用任何 Features"
  ],
  "status": "done"
}
```

校验规则（不满足即视为不可用）：

- `game`、`paradigm`、`root` 非空；`status` 只能是 `draft` / `done`。
- `systems` 至少一项；`id` 唯一且非空；每项都有 `title` 和合法 `status`。
- `extensionPoints[].name` / `howTo` 非空，`name` 不重复。
- `status: done` 时至少有一个系统是 `done`；留空壳不算完成。

## 二、框架文档

路径由 `indie.framework.doc` 决定，默认 `Docs/AI/Frameworks/{game}.md`（`{game}` 取工程目录名）。用下面这个骨架，别写成长篇设计文档。

```markdown
# {游戏名} 框架

## 范式

一句话说明选了哪套、为什么够用。

## 分层与依赖方向

Core → Features 单向依赖；功能之间只通过事件/接口。

## 目录与程序集

目录树 + asmdef 清单 + 各自该放什么。

## 系统

每个系统一小节：职责、入口类型、生命周期、被谁用、落地状态。

## 扩展点

| 扩展点 | 怎么加 | 位置 |
| --- | --- | --- |
| 新状态 | 新建 XxxState : IGameState，在 Bootstrap 注册 | Core/State |
| 新事件 | 定义 XxxEvent : GameEvent，Send/Subscribe<T> | Core/Events |
| 新配置 | 新建 SO + 在 ConfigDatabase 登记 | Core/Config |
| 新存档字段 | 加字段到 SaveData，注意读档兼容 | Core/Save |

## 新增一个功能时

1. 在 Features/ 下建目录
2. 需要的通信走 EventBus
3. 数据走 SO 配置
4. 需要新扩展点时先登记，再实现

## 约定与反模式

自己的约定，加上明确不做的方向。

## 还没做的

`status: pending` 的系统，以及下一步打算做什么。
```

## 三、完成标准

- [ ] `framework.json` 能被校验通过。
- [ ] 框架文档的四类扩展点（新状态 / 新事件 / 新配置 / 新存档字段）都能照着做。
- [ ] 每个 `systems[].paths` 真实存在，且不是空壳类。
- [ ] 下一个功能不需要再改框架就能开始写。
