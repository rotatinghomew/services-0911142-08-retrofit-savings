# 服务设施改造节能核算台

这是供服务规划人员核对资料、查看业务范围和留存讨论依据的本地应用。当前提供分表能耗与改造事件时间线，并支持导入、图表、原始记录、保存与重新打开；在此基础上新增节能核验：按改造前资料建立可解释的用能基线，结合报告期室外温度、服务时长与使用人数测算反事实用量、节省量及不确定性，并在无法比较时停止给出整体节能率。示例为独立生成的虚构数据，不含真实家庭、医疗资料或对外服务凭据。

## 使用环境

使用 Python 3.11，独立容器镜像锁定到 3.11.14。页面为原生浏览器界面，数据处理通过本地 HTTP 服务完成，持久化使用应用内置数据库。基础浏览不依赖数值库；研究扩展所需的数值计算和建模库已按 `requirements.txt` 固定所有传递版本。依赖安装及镜像构建只在环境准备时做，启动和检查不访问网络。

```bash
python3 -m pip install -r requirements.txt -r requirements-build.txt -r requirements-test.txt
python3 -m playwright install --with-deps chromium
python3 -m retrofit_savings --host 127.0.0.1 --port 8080
```

浏览器打开本地8080端口。容器方式先准备镜像，运行时不需要其他服务：

```bash
docker build -t retrofit_savings:local .
docker run --rm -p 8080:8080 -v retrofit_savings-state:/app/.state retrofit_savings:local
```

## 验证

```bash
python3 -m unittest discover -s tests -v
python3 -m build --wheel --no-isolation
python3 tests/browser_smoke.py
python3 tests/browser_verification.py
```

检查包含真实领域字段、非法导入、边界数据保留、HTTP交互、版本指纹及重启后存档。节能核验回归覆盖计量纪律（倍率、重置、缺测不补零）、基线只用改造前资料、留时段验证、异常残差、外推阻断、调整批准与双重计算防护、情景指纹复现与页面钻取。新增能力需要补充针对统计识别、支持范围和页面一致性的回归。运行检查使用临时状态，不改动资料。

字段语义与现有接口分别见 `docs/data-contract.md` 和 `docs/http.md`。短时操作见 `docs/walkthrough.md`，环境准备不包含在正式操作中。

## 核验纪律

基线模型只用 `period=baseline` 的观测拟合，报告期实际用电只用于事后对照，不可能由报告期数据倒推"总能节能"的基线。倍率、换表重置与序列水平漂移属例行计量条件，在规范化阶段处理；停楼与新增托育等属单独调整，逐条批准留痕且只路由到一个表段。总表与分表覆盖范围不同，站点合计只取总表口径。覆盖率、留时段验证、外推范围、异常残差或未估计调整任一不满足时，页面显示停止给出整体节能率，只保留表段级线索与依据。
