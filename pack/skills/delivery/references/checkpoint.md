# 检查点

- 最后一条通过的检查点必须覆盖任务包中的全部 `validation` 条目（使用 `coveredValidation` 或写在 summary 中）。
- 验证失败时在原 `execution-id` 下继续修改并再记检查点；不要擅自换执行标识。
