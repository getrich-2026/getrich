# GetRich — Claude Code 入口

本项目的全部约束写在 `AGENTS.md`（唯一真源，与 Codex、DeepSeek 等 harness 共用）。下面一行会把它整体导入本次会话，不要在本文件里重复内容 —— 要改规则请改 `AGENTS.md`。

@AGENTS.md

## Claude Code 专属

- 权限规则在 `.claude/settings.json`（团队共享，已提交）。个人覆盖写 `.claude/settings.local.json`，该文件被 gitignore。
- 会话开始先读 `.agent/brain/NOTES.md` 恢复状态，再读 `.agent/brain/DECISIONS.md`；会话结束按 `AGENTS.md` 第 7 节更新。
