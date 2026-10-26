# 读取 Unity 预制体

`.prefab` 是 YAML。文件头通常是 `%YAML 1.1` 和 `%TAG !u! tag:unity3d.com,2011:`。每个对象一段，形式为 `--- !u!<classId> &<fileID>`。

看这些 classId：

- `1` GameObject：`m_Name`，`m_Component` 里是组件的 fileID
- `4` Transform、`224` RectTransform：`m_GameObject`、`m_Father`、`m_Children`，用来还原层级
- `114` MonoBehaviour：`m_Script` 和序列化字段
- `1001` PrefabInstance：嵌套预制体，`m_SourcePrefab` 是来源，改动在 `m_Modifications`

脚本引用形如 `m_Script: {fileID: 11500000, guid: <32位>, type: 3}`。`fileID: 11500000` 表示资源引用。在工程的 `.meta` 里搜 `guid: <同一 guid>`，`guid` 上一行附近的文件名就是脚本。对不上任何 `.meta`，或 `guid` 为空、`fileID: 0`，视为缺失脚本。

`stripped: 1` 的对象不完整，以对应 PrefabInstance 的修改为准。

不要改 `.meta` 的 guid。任务没有明确要求改预制体时，改预制体已经引用的脚本，不要重写预制体 YAML。
