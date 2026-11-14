# 资料与统计口径

`readings.cumulative` 为原始表盘累计量，不是日耗。`meters` 指定覆盖范围、换表日和前后倍率，换表日开始新累计序列，不能跨重置直接差分。`quality=missing` 和 null 对应未读表，不是零。总表含分表，不能相加当全站。`operations` 是每天独立记录的温度、营业小时和服务人数，`period` 标出改造前及报告期；不能从报告期用电训练原本应发生的基线。`adjustments` 记录停楼和新增服务，`approved` 只是业务批准，`impact_kwh=null` 表示影响尚待估计不是没有影响。预备材料有未批调整和计量缺口。当前仅浏览读数与原始差分，未测算节省量。

## 原始表

- `readings`：1460条示例，主键为 `reading`。字段：`reading`, `meter_id`, `day`, `cumulative`, `quality`。
- `operations`：730条示例，主键为 `operation`。字段：`operation`, `site`, `day`, `temperature`, `service_hours`, `users`, `period`。
- `meters`：4条示例，主键为 `meter_id`。字段：`meter_id`, `site`, `meter`, `boundary`, `multiplier_before`, `multiplier_after`, `replacement_day`, `sub_of`。
- `adjustments`：4条示例，主键为 `adjustment`。字段：`adjustment`, `site`, `start`, `stop`, `kind`, `approved`, `impact_kwh`。

## 版本与扩展

`fixtures/data.json` 是完整导入材料，`product.json` 是当前浏览器默认选择。全量导入校验后按规范化内容指纹保存，相同内容不重复建版本。原始事实不原地修改；资料修订形成新版本。`null` 表示明确未观测，不因筛选或合计自动变为0。

`retrofit_savings/domain.py` 是领域入口，现阶段仅做字段校验及资料描述；`service.py` 连接范围选择、数据版本与服务端计算后的存档；`storage.py` 管理不可变数据和保存材料；`web/app.js` 提供浏览和导出交互。保存的材料同时包含原数据与选择，打开旧材料不重算为新数据。新增分析不限内部组织方式，但不能丢失现有原始记录核对与历史材料读取能力。统计方法、模型选择和业务结论没有预设答案。
