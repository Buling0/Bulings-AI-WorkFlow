# 独游框架参考

这份文件是「建立框架」阶段的选型依据和最小基线。目标不是做一个通用框架，而是让**后面每个功能都有地方挂**，并且挂得住。

## 一、选型

| 范式 | 适用 | 代价 | 备注 |
| --- | --- | --- | --- |
| **轻量自建（默认）** | 单人 / 2-5 人，1-3 个月内出一个可玩版本；玩法在核心循环上变化 | 要自己写 4-6 个基础系统，约 1-2 天 | 零外部依赖，和工程一起演进；本文件的第二节就是它 |
| [QFramework](https://github.com/Mu-L/QFramework) | 想要现成的 MVC / 事件 / 架构分层，团队熟悉它的用法 | 引入第三方库与它自己的命名约定；和已有代码边界要划清 | 上手快，国内 indie 常用；接入时把它的入口收在一个适配层里 |
| [UnityGameFramework](https://github.com/EllanJiang/UnityGameFramework) | 需要流程（Procedure）、资源、实体、UI 一整套现成骨架，项目偏中大型 | 体量和约定都很重，小项目容易"框架养人" | 适合已经确定要长期做大的项目 |
| 工程已有范式 | 工程里已经有框架 / 团队约定 | 无 | **优先级最高**：服从已有结构，只补缺口，不重写 |

理论参照：[Unity 官方《Level up your code with design patterns and SOLID》](https://unity.com/resources/design-patterns-solid-ebook) 和 [游戏编程模式更新说明](https://unity.com/cn/blog/game-programming-patterns-update-ebook)。里面的状态机、观察者、对象池、组件模式正好对应下面这套基线。

**选型纪律**：能用一个类解决就不要建一层；没有第二个使用者的抽象不算扩展点。先把基线跑通，再按真实需求加系统。

## 二、最小基线（默认范式）

按依赖顺序落地。前四个是必需，后面的等第一个用到它的功能再做。

### 1. 启动与生命周期（必需）

唯一入口，负责决定「先初始化什么、什么时候进游戏」。

- `GameBootstrap`（场景里唯一常驻对象，`DontDestroyOnLoad`）：依次注册服务、加载存档、进入首个状态。
- 初始化顺序显式写在代码里，不靠 `Awake` 的执行顺序碰运气。
- 退出时统一走 `Shutdown`：存档、解绑事件、释放池。

### 2. 服务注册（必需）

给跨模块使用的对象一个**唯一**取用点，替代到处 `FindObjectOfType` 和静态单例。

- 接口 + 实现分离：`IAudioService` / `AudioService`。
- 一个 `Services` 注册表：`Register<T>(T)`、`Get<T>()`；只在启动阶段注册，运行时只读。
- 允许静态访问 `Services.Get<T>()`，但**只有启动代码和边界层**可以注册。

### 3. 事件（必需）

模块之间只通过事件通信，禁止 A 模块直接调 B 模块的表现层。

- `GameEvent` 基类 + 泛型 `EventBus.Subscribe<T>` / `Send<T>`。
- 订阅必须在 `OnDisable` / `OnDestroy` 解绑；给一个 `IDisposable` 的订阅句柄，避免忘记解绑。
- 事件命名用过去式（`TowerPlaced`），只描述"发生了什么"，不带指令。

### 4. 状态 / 流程（必需）

把「主菜单 → 游戏 → 暂停 → 结算」这类整体切换收进一个状态机。

- `IGameState { Enter(); Exit(); Tick(float dt); }` + `GameStateMachine`。
- 每个状态一个文件；状态切换只由状态机发起，界面不直接切场景。
- 小型项目用一个简单字典状态机就够，不要上行为树。

### 5. 配置（第一个"有数据"的功能前必须有）

- 静态数据用 `ScriptableObject`（塔属性、关卡、掉落表），运行时只读。
- 一个 `ConfigDatabase` 负责按 id 查表；不要在脚本里写死数值，也不要到处 `Resources.Load`。
- 配表 id 用字符串常量集中定义，避免拼写漂移。

### 6. 存档（第一个"有进度"的功能前必须有）

- `SaveData` 是一个纯数据类（可序列化），加字段就是加字段，**不做版本迁移就别引入**。
- `SaveSystem`: `Load()` / `Save()` / `Delete()`，JSON 落到 `Application.persistentDataPath`。
- 存档写盘放在明确时机（状态退出、结算、手动保存），不要在每帧或每个事件里写。

### 7. 按需再加

| 系统 | 什么时候才加 |
| --- | --- |
| 对象池 | 同一预制体一局内创建/销毁超过几十次（子弹、飘字、特效） |
| 音频 | 需要 BGM 淡入淡出、音量分组、池化音源 |
| 输入 | 需要键位重绑定、多设备 |
| 场景加载 | 场景切换需要进度条或异步预加载 |
| UI 接入 | 界面超过 3 个，或需要统一的弹窗栈 / 层级管理 |
| 时间 | 需要暂停、倍速、回放（把 `Time.deltaTime` 收进一个 `IClock`） |

## 三、目录与程序集约定

小项目也一样要有稳定边界，否则第二个功能就开始互相引用。

```text
Assets/_Game/
  Core/                 框架层：Bootstrap、Services、Events、State、Save、Config、Pool
  Features/<Feature>/   功能层：每个玩法一块，只依赖 Core，不互相依赖
  Content/              ScriptableObject 资产、场景、预制体
  Editor/               编辑器工具（不进运行时程序集）
```

- asmdef：`Game.Core`（不引用任何功能）、`Game.Features`（引用 Core）、`Game.Editor`（仅编辑器）。功能之间通过事件或 Core 的接口通信，**不互相引用**。
- 命名：`Core` 里的类型用 `Game.Core.*`，功能用 `Game.Features.<Feature>.*`。
- 每个功能目录自带一个 `README.md` 或一行注释说明入口类。
- 新增第三方包一律放进 `Assets/ThirdParty/`，不混进 `_Game`。

## 四、反模式（评审框架时逐条对照）

1. **万能 GameManager**：一个类里塞输入、状态、存档、UI。超过 300 行就说明该拆了。
2. **静态单例横飞**：`XxxManager.Instance` 到处都是。除了 `Services` 这一处，其他都不允许。
3. **数值写死在代码里**：改一个平衡性数值要改代码并重新编译。
4. **每个功能自造事件系统**：A 功能一套 EventCenter，B 功能一套 MessageBus。事件只有一个。
5. **框架先于需求**：为一个还没做的功能先建三层抽象。
6. **空壳系统**：`systems` 里登记了"对象池"，点进去只有 `class ObjectPool {}`。宁可 `status: pending`，也不要挂空壳。
7. **绕过框架直接改别人的状态**：功能之间直接改对方的字段，事件和接口形同虚设。

## 五、完成标准（框架阶段自检）

- [ ] 从启动到退出有一条能跑通的最小回路（哪怕只有一个空场景 + 一个状态）。
- [ ] 新增一个状态、一个事件、一项配置、一个存档字段，都能在框架文档里找到明确的"加在哪、怎么写"。
- [ ] `Core` 不引用任何 `Features`。
- [ ] 每个 `systems[].paths` 指向的文件或目录真实存在，且不是空壳。
- [ ] 没有为了框架引入需要联网安装的第三方包（除非 `project` 配置里已经指定）。
