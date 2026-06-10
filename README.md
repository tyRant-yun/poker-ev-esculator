# 德州策略工作台

本项目是一个本地运行的完整德州扑克单手牌策略分析器。

## 当前功能

- 2–9 人 No-Limit Texas Hold'em 规则状态机。
- 自动处理行动顺序、有效加注、全下、主池与边池。
- 每位对手独立的加权范围与行动后范围更新。
- 多人互斥手牌抽样和有限深度 EV 策略分析。
- 浏览器牌桌、可视化选牌、范围矩阵、EV 图表、撤销与节点分支。
- 基准策略与针对对手画像的利用性策略对比。

当前策略模型是一层对手响应加摊牌 roll-out，不是 CFR/GTO Solver。遭遇对手加注的分支暂按 Hero 弃牌处理，因此部分主动动作 EV 偏保守。

## 启动

需要 Python 3.10 或更高版本：

推荐直接双击项目根目录中的：

```text
启动德州策略工作台.cmd
```

启动器不依赖 PowerShell 当前工作目录，会自动后台启动服务、等待服务就绪并打开浏览器。也可以为该文件创建桌面快捷方式。
若系统命令行对中文文件名兼容不佳，也可以双击同目录的 `start_poker_lab.cmd`。

手动启动方式：

```powershell
python .\web_app.py
```

浏览器访问：

```text
http://127.0.0.1:8000
```

推荐始终通过上述地址使用工作台。直接打开 `web/index.html` 也能加载界面和选牌器，但创建牌局仍需要 `web_app.py` 服务正在运行；页面顶部会在服务未连接时显示启动提示。

## 验证

```powershell
python -m unittest -q
python -m compileall -q .\poker .\web_app.py .\test_hand_state.py .\test_ranges_equity.py .\test_strategy.py .\test_web_app.py
node --check .\web\app.js
git diff --check
```

## 项目结构

```text
poker/
  cards.py       牌组、牌面解析和牌力评估
  models.py      完整牌局状态模型
  engine.py      合法动作与状态转换
  settlement.py  主池、边池和摊牌结算
  ranges.py      逐玩家加权范围
  equity.py      多人范围权益模拟
  strategy.py    候选尺寸与有限深度 EV 分析
web/
  index.html     工作台页面
  app.js         浏览器交互
  styles.css     页面样式
web_app.py       本地 Web 服务和牌局会话 API
```

旧单节点 EV、OCR/AI 视觉录入和旧版文档位于 `archive/v1_single_node/`，不参与当前主应用运行。
