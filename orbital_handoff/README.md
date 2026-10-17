# orbital_handoff

跨隔离 AI agent 的项目交接 skill：让仓库自己携带足够的上下文，使任何 agent（无论有无 skill 框架）都能零歧义地接手。

**版本**：0.2.0（见仓库根 CHANGELOG.md）

## 安装

把本目录放入所用 agent 的 skills 目录，例如：

- OpenCode / zcode：`~/.config/opencode/skills/orbital_handoff/`
- Claude Code：`~/.claude/skills/orbital_handoff/`
- Cline：`~/.cline/skills/orbital_handoff/`

无 skill 框架时：直接使用 `references/handoff-template.md` 与 `references/resume-checklist.md`，见 `references/agent-mode-matrix.md` 的「双向都无框架时」。

## 组成

| 路径 | 用途 |
|---|---|
| `SKILL.md` | 主文档：CREATE / RESUME / CHECK 三工作流 |
| `scripts/create_handoff.py` | 脚手架生成（`--check` 预检 / `--update-pointer-only` 指针恢复） |
| `scripts/validate_handoff.py` | 完整性 + 密钥 + 交接链 + 质量分验证 |
| `scripts/check_staleness.py` | 交接新鲜度评级（`--strict` 退出码供 CI） |
| `scripts/tests/` | 回归测试：`python3 -m unittest discover -s scripts/tests` |
| `references/` | 档位矩阵 / 模板指引 / 接手核查清单 |

## 安全基线

凭证、`.env`、私钥、token 永远不进交接物。`validate_handoff.py` 检出密钥即 BLOCKED（不受分数影响）；`create_handoff.py` 落盘后即时扫描敏感文件并告警。
