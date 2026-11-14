# 应用接口

服务绑定本地地址，输入输出为 UTF-8 JSON。错误输入为400，未找到对象为404，超过8MB请求为413。页面与服务端共用口径，前端不另算一份统计答案。

- `GET /health`：检查启动是否成功。
- `GET /api/context`：产品配置、默认数据和已保存材料目录（含核验存档目录）。
- `GET /api/data?revision=版本`：查看完整原始表。
- `POST /api/datasets`：传入 `label` 与完整 `data`，校验后返回不可变 `revision`。
- `POST /api/explore`：传入可选的 `revision` 和 `selection`，返回实际选择、资料指纹与 `view`。现有 view 的 summary、rows、series、notes 只用于描述。
- `POST /api/notebooks`：传入选择与 `title`，由服务端重新生成描述后保存，不接受客户端伪造结果。
- `GET /api/notebooks` 与 `GET /api/notebooks/编号`：目录以及冻结资料、选择和结果。

## 节能核验

- `POST /api/verify`：传入 `site`、可选 `revision` 与 `assumptions`，返回情景指纹 `scenario_fingerprint` 和完整 `verification`。全部统计在服务端完成，页面只渲染。
  - `assumptions.baseline_window`：`{start, stop}`，整数日期，键可省略表示沿用资料基准期全窗口；不允许跨入报告期。
  - `assumptions.holdout_days`：基准期末尾连续留时段验证天数，7–60，默认14。
  - `assumptions.approvals`：`调整编号 → 布尔值` 的批准覆盖；未列出的调整沿用资料 `approved` 字段，覆盖来源回显为 `researcher_override` 或 `dataset`。
  - `assumptions.scenario_label`：1–80字情景名称。
- `POST /api/verifications`：在 `/api/verify` 同参数基础上加 `title`，服务端重算后冻结保存，不接受客户端伪造结果。
- `GET /api/verifications` 与 `GET /api/verifications/编号`：核验存档目录与冻结结果（含假设、指纹、阻断依据与逐日表段数据）。

核验响应要点：`comparable=false` 时 `overall_savings_rate` 恒为 `null`，但表段级反事实、节省量、95%区间与诊断依据照常返回用于线索排查；`blocking_reasons` 给出每条阻止结论的资料依据。情景指纹只依赖数据版本、站点与假设，同输入必复现，供并排复核对照。

新增分析可扩展接口，但已有导入、描述和历史读取仍供业务使用，不能静默改换其含义。
