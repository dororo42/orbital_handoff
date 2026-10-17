# orbital_handoff — 审查与项目化

本仓库包含 **orbital_handoff.skill**（跨隔离 agent 项目交接 skill）的完整源码、原始发布包，以及 2026-10-17 的独立代码审查产出。

## 目录结构

```
.
├── orbital_handoff/                     # skill 源码（与 dist 内 .skill 包逐字节一致）
│   ├── SKILL.md                         # 主文档：CREATE / RESUME / CHECK 三工作流
│   ├── references/                      # 档位矩阵 / 交接模板 / 接手核查清单
│   └── scripts/                         # create / validate / check_staleness 三个脚本
├── dist/
│   └── orbital_handoff.skill            # 原始 .skill 发布包（zip，未改动）
└── review/
    ├── orbital-handoff-独立审查报告-2026-10-17.md   # 1 阻塞 / 5 重要 / 4 次要 / 5 建议 + 6 亮点
    ├── orbital-handoff-优化建议-2026-10-17.md       # P0/P1/P2 修复路线 + 补丁草图 + 发布清单
    └── evidence-2026-10-17.md                        # 15 项动态测试的实测证据
```

## 审查结论速览

**决策：Request Changes（修改后可发布）。**

- 🔴 1 项阻塞：`create_handoff.py` 先建 kit 目录再找前驱 → **每份交接的 `Continues from` 都指向自己**，交接链与跨代闭环检查双双失效（必现，修复约 5 行）。
- 🟡 5 项重要：untracked 文件被“未提交修改”遗漏；断链静默通过；同分钟撞名导致归档顺序错/目录静默覆盖；staleness 对“少提交多改文件”分级过宽；ABORT 残留半成品。
- 亮点同样明确：写姿势契约、原子写 + 乐观并发、密钥硬闸、归档不删除。

修复路线与验收清单见 `review/orbital-handoff-优化建议-2026-10-17.md`（P0 合计约半天工作量）。

## 复现审查

```bash
# 动态测试沙盒（照 evidence 文档可完整重放）
python3 orbital_handoff/scripts/create_handoff.py --check
python3 orbital_handoff/scripts/create_handoff.py demo --target all
python3 orbital_handoff/scripts/validate_handoff.py handoffs/*/HANDOFF.md
python3 orbital_handoff/scripts/check_staleness.py handoffs/*/HANDOFF.md
```

## 许可

skill 源码许可随上游发布包；审查文档部分按仓库整体许可处理（建议添加 LICENSE）。
