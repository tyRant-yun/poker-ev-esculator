# 第一版单节点计算器归档

此目录保存项目第一版功能，归档日期为 2026-06-10。

归档内容包括：

- `gto_ev.py`：单节点权益及简化动作 EV 计算器。
- `test_gto_ev.py`：第一版计算器测试。
- `configure_ai.ps1`、`.env.example`：旧 AI 视觉配置。
- `windows_ocr.ps1`：旧 Windows OCR。
- `table_state.example.json`：旧单节点状态示例。
- `README.md`、`USER_GUIDE.md`、`RELEASE_RECORD.md`：第一版文档。
- `.github/workflows/release-v1.0.0.yml`：第一版发布流程。

第一版原始 Web 页面和服务代码仍可从 Git 历史中的提交 `9bc505e` 及更早提交恢复。当前主分支中的
`web/` 与 `web_app.py` 已清理为完整手牌工作台，不再保留旧 UI 混合代码。

第一版存在以下限制，因此不再作为主产品：

- 所有对手共用一个范围比例。
- 没有逐玩家筹码、行动历史、有效筹码和边池。
- 动作 EV 假设跟注后直接摊牌。
- 混合策略频率并非博弈均衡结果。
- OCR/视觉录入服务于旧单节点字段，无法可靠构建完整牌局状态。

归档文件不再由当前测试和 Web 服务引用。
