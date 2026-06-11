# Poker Strategy Workbench v2.0.1

这是德州策略工作台的文档与发布体验补丁版本。

完整安装、操作和故障排查说明见 `RELEASE_USER_GUIDE.md`。

## 本次更新

- 新增面向 Release ZIP 下载者的完整使用说明。
- 重写 README，整理当前功能、依赖、数据、API 和策略边界。
- 明确应用仅依赖 Python 标准库，无需执行 `pip install`。
- 补充 Windows、macOS 和 Linux 启动说明。
- 补充数据备份、服务停止和常见问题处理方式。

## 启动

需要 Python 3.10 或更高版本。

Windows 推荐双击：

```text
启动德州策略工作台.cmd
```

或：

```text
start_poker_lab.cmd
```

也可以手动运行：

```powershell
python .\web_app.py
```

浏览器访问 `http://127.0.0.1:8000`。

## 数据

完成牌局会保存至本地 `data/poker_workbench.db`。该目录不会包含在 Git 或发布包中。

## 后续计划

人机对战方案已记录在 `undo.md`。
