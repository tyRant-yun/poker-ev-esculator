# 德州扑克 GTO / EV 近似计算器

这是一个无第三方依赖的 Python 命令行脚本。它接收人数、位置、手牌和对手策略，
通过蒙特卡洛模拟计算权益，再估算 `fold`、`check/call`、`bet/raise` 的净 EV，
并输出一个基于 EV 的近似混合策略、推荐加注范围和推荐投入额。

> 完整 GTO 求解需要构建下注树、范围和效用矩阵并运行 CFR 等算法。本工具计算的是
> 当前单个决策节点的近似最佳响应，不能替代完整 GTO solver。

## 使用

需要 Python 3.10 或更高版本。

```powershell
python .\gto_ev.py `
  --players 6 `
  --position BTN `
  --hand "As Kh" `
  --pot 10 `
  --to-call 2 `
  --raise-size 8 `
  --strategy balanced `
  --simulations 10000 `
  --seed 42
```

翻牌后示例：

```powershell
python .\gto_ev.py --players 2 --position CO --hand "Ah Qh" `
  --board "Jh 8h 2c" --pot 12 --to-call 4 --raise-size 14 `
  --opponent-range 0.25 --fold-to-raise 0.38
```

机器可读输出：

```powershell
python .\gto_ev.py --players 2 --position BTN --hand "As Ah" --json
```

## 参数含义

| 参数 | 含义 |
|---|---|
| `--players` | 仍在牌局中的总人数，2-9 |
| `--position` | `UTG/UTG+1/MP/HJ/CO/BTN/SB/BB` |
| `--hand` | 两张手牌，花色为 `c/d/h/s` |
| `--board` | 0、3、4 或 5 张公共牌 |
| `--strategy` | `tight/balanced/loose` 对手策略预设 |
| `--opponent-range` | 覆盖预设的对手入池范围，`0.25` 表示前 25% |
| `--fold-to-raise` | 覆盖预设的面对加注弃牌率 |
| `--pot` | Hero 行动前的底池 |
| `--to-call` | Hero 跟注所需投入 |
| `--raise-size` | Hero 加注或下注的总投入 |

EV 均为从当前决策点开始计算的净筹码：

- `call EV = equity × (pot + to_call) - to_call`
- `raise EV = fold% × pot + call% × (equity × called_final_pot - raise_size)`

位置用于在未指定 `--opponent-range` 时估算默认范围。多人底池中，
`--fold-to-raise` 被视作所有对手均弃牌的聚合概率。

## 测试

```powershell
python -m unittest -v
```

## 浏览器图形界面

启动本地服务：

```powershell
python .\web_app.py
```

然后访问 `http://127.0.0.1:8000`。界面和 API 均在本机运行，不会上传牌局数据。

界面下方提供“桌面视觉检测与策略脚本”：

- 使用浏览器桌面共享捕获牌桌窗口，或导入截图。
- 浏览器支持原生 `TextDetector` 时自动 OCR；不支持时可在识别文本区校准。
- 识别文本使用 `hand As Kh`、`board Qs Jh 2c`、`pot 10`、`call 2` 等格式。
- 应用识别结果后自动计算，并生成包含推荐动作、动作频率和 EV 的策略脚本。
- 策略脚本仅用于建议，不会自动操作扑克客户端。

### 配置 AI 视觉 API

视觉识别使用 OpenAI 兼容的 `chat/completions` 接口。API Key 仅由本地 Python 服务读取，
不会暴露给浏览器。选择牌桌窗口和发送截图都需要用户主动操作。

```powershell
$env:AI_API_KEY="your-api-key"
$env:AI_MODEL="your-vision-model"
$env:AI_BASE_URL="https://your-provider.example/v1"
python .\web_app.py
```

若使用默认 OpenAI 地址，可省略 `AI_BASE_URL`。所选模型必须支持图片输入。

推荐使用交互式配置脚本，配置会保存在本机项目目录的 `.env` 中，不受 PowerShell
会话切换影响：

```powershell
.\configure_ai.ps1
```

`.env` 已加入 `.gitignore`。可访问 `http://127.0.0.1:8000/api/health` 检查配置是否
被服务读取；健康接口只显示模型、地址和缺失字段，绝不会返回 API Key。

`AI_BASE_URL` 可填写基础地址（例如 `https://example.com/v1`）或完整的
`https://example.com/v1/chat/completions` 地址。

### 无 AI API 的离线替代方案

AI API 不可用时，界面会自动进入离线模式，截图不会上传：

- 选择桌面窗口或导入截图，然后用离线快速校准字段录入人数、位置、手牌和底池。
- 浏览器支持本地 `TextDetector` 时，“离线检测当前画面”会尝试本地 OCR。
- Windows 环境会优先调用系统内置 OCR，因此不要求浏览器支持 `TextDetector`。
- 可导入 `.json` 或 `.txt` 状态文件。JSON 格式参考 `table_state.example.json`。
- 可点击“从当前参数生成状态”复用已有输入，再应用状态并生成策略脚本。
