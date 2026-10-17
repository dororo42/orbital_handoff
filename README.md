# orbital_handoff — 审查与项目化

本仓库包含 **orbital_handoff.skill**（跨隔离 agent 项目交接 skill）的完整源码与发布包。2026-10-17 的独立代码审查产出仅保存在本地 `review/` 目录（已排除出版本库，不随仓库上传）。

> **当前状态**：审查发现的全部 P0/P1 缺陷已在 **v0.2.0** 修复并通过 16 项回归测试；**v0.2.1** 增加「交接文档不上传」硬政策，见 [CHANGELOG.md](CHANGELOG.md)。`orbital_handoff/` 目录即最新源码；`dist/orbital_handoff.skill` 为修复前的原始包（v0.1 存档），`dist/orbital_handoff-0.2.0.skill` / `dist/orbital_handoff-0.2.1.skill` 为对应版本发布包。

## 目录结构

```
.
├── orbital_handoff/                     # skill 源码（v0.2.1）
│   ├── SKILL.md                         # 主文档：CREATE / RESUME / CHECK 三工作流
│   ├── README.md                        # 包内说明（安装路径 / 组成 / 安全基线）
│   ├── references/                      # 档位矩阵 / 交接模板 / 接手核查清单
│   └── scripts/                         # create / validate / check_staleness
│       └── tests/                       # 回归测试（unittest，16 项，零依赖）
├── dist/
│   ├── orbital_handoff.skill            # 原始 .skill 包（v0.1 存档，未改动）
│   ├── orbital_handoff-0.2.0.skill      # v0.2.0 发布包
│   └── orbital_handoff-0.2.1.skill      # v0.2.1 发布包（含交接文档不上传政策）
└── review/                              # 审查产出——仅本地保留，不入库、不随仓库上传
    ├── orbital-handoff-独立审查报告-2026-10-17.md   # 1 阻塞 / 5 重要 / 4 次要 / 5 建议 + 6 亮点
    ├── orbital-handoff-优化建议-2026-10-17.md       # P0/P1/P2 修复路线 + 补丁草图 + 发布清单
    └── evidence-2026-10-17.md                        # 15 项动态测试的实测证据
```

## 审查结论速览

**决策：Request Changes（修改后可发布）→ 已在 0.2.0 完成修改。**

- 🔴 1 项阻塞：`create_handoff.py` 先建 kit 目录再找前驱 → **每份交接的 `Continues from` 都指向自己**，交接链与跨代闭环检查双双失效（必现）。**已修复**（`find_previous` 增加 exclude + HANDOFF.md 存在性过滤）。
- 🟡 5 项重要：untracked 遗漏 / 断链静默 / 同分钟撞名三连 / staleness 分级过宽 / ABORT 残留。**已全部修复**。
- 亮点同样明确：写姿势契约、原子写 + 乐观并发、密钥硬闸、归档不删除。
- 修复过程中另发现并修复一个审查外缺陷：staleness 的「HEAD 不可达」检测在 orphan/rebase 场景漏报（`rev-list A..B` 对对象仍存在的非祖先不报错），改用 `merge-base --is-ancestor`。

## 复现审查 / 运行测试

```bash
# 回归测试（零依赖）
python3 -m unittest discover -s orbital_handoff/scripts/tests -v

# 动态验证沙盒（照 evidence 文档可完整重放）
python3 orbital_handoff/scripts/create_handoff.py --check
python3 orbital_handoff/scripts/create_handoff.py demo --target all
python3 orbital_handoff/scripts/validate_handoff.py handoffs/*/HANDOFF.md
python3 orbital_handoff/scripts/check_staleness.py handoffs/*/HANDOFF.md
```

## 许可

skill 源码许可随上游发布包（建议添加 LICENSE）。
