# teacher Wenkai

个人科研技能：从原始实验数据到统计结果、数据库查询、原始文献、可证伪假设和证据关联写作。面向 Codex，中文优先。

版本 **3.0.0**。公开仓库不采用开源许可；查看和 GitHub Fork 依平台条款进行，其他用途须取得权利人许可。以下运行指引供权利人或另获授权的使用者使用，详见 [LICENSE](LICENSE)。

## 能做什么

- 文献：7 个统一检索来源、18 个文献 API 入口、DOI/参考文献核验、CNS 范围筛选、RIS/BibTeX/ENW/RDF 导出、带排除理由的综述台账。
- 全文：OA 和授权 URL 下载，出版商凭据接口，文件检查、哈希及续跑；PDF/JATS/Word/PPT 的来源定位，中英对照阅读包与公式结构检查。
- 数据：CSV/TSV/XLSX、长表/宽表、技术与生物重复、配对/批次、qPCR、连续组学矩阵、PyDESeq2 计数模型、实测背景 GMT 富集；PNG/SVG 与可执行 Notebook。
- 后续研究：从经过质量筛选的差异、趋势和组内关联出发，实际查询文献和公共数据库；预算、失败、重试与访问层级可追踪。
- 生命科学：44 个数据库的项目原生处理器（含已停用 eQTL REST 的状态处理和本地表替代），覆盖 REST、GraphQL、SPARQL、PheWAS、eQTL、临床和组学资源；不需要安装原数据库插件。
- 学术项目：研究问题、证据矩阵、实验设计检查、研究阶段计划、证据关联论文草稿与评审材料。Academic Research Skills 的重叠功能已经整合，写作和实验设计补入独立实现。

“原生接口”表示本仓库有实现，不表示所有远程服务随时可用，也不表示已验证每个端点。最新实际检测范围见 [检测报告](audit/VALIDATION.md)。细分能力与局限见 [功能映射](references/integration-map.md)。

## 安装与调用

Python 3.10+；验证环境为 Python 3.12。将本目录安装到 `~/.codex/skills/teacher-wenkai`，安装后在下一轮对话中调用。不要把同一技能的多份副本放进活动 skills 目录。

```bash
python3 -m venv ~/.local/share/teacher-wenkai/venv
~/.local/share/teacher-wenkai/venv/bin/python -m pip install -r ~/.codex/skills/teacher-wenkai/requirements.txt
python3 ~/.codex/skills/teacher-wenkai/scripts/run.py doctor
```

`TWK_PYTHON` 可指定运行时；迁移用户可继续使用先前的科研专用环境。入口不会自动安装依赖。通用科学计算/PDF 依赖独立安装，版权及许可属于各维护者，详见 [DEPENDENCIES.md](DEPENDENCIES.md)。

```text
$teacher-wenkai 分析这些常规实验和蛋白组数据，先检查生物重复与批次，再根据可靠信号继续研究。
$teacher-wenkai 检索这个问题，核实引用，精读有决定性的原文与反证。
$teacher-wenkai 将这些结果整理成研究计划、最小判别实验和带证据定位的论文草稿。
```

合成演示（只生成本地分析及待检索队列）：

```bash
python3 SKILL_DIR/scripts/run.py data-research SKILL_DIR/assets/examples/mixed-demo/study.json --offline --out NEW_RUN_DIR
python3 SKILL_DIR/scripts/run.py study-plan 'Which observation should be tested next?' --analysis NEW_RUN_DIR --out NEW_PLAN_DIR
python3 SKILL_DIR/scripts/run.py notebook-execute NEW_RUN_DIR/analysis.ipynb
```

将 `SKILL_DIR` 替换为技能目录，输出目录必须是新的。去掉 `--offline` 将使用示例中明确标注的公开实体进行网络检索。配置须按真实设计填写，不能直接套用演示组别或样本量。原始测量值和样本身份不作为自动检索内容上传。

## 证据边界

统计软件测试只验证实现；关联不证明机制，数据库注释不证明通路激活，检索候选不等于论文支持。论文读取、图表解释、语义核验及科学推理由使用此技能的 Codex 完成，并保留原文定位。原始计数模型不等于 FASTQ 预处理；单细胞、质谱原始谱图及复杂纵向设计需另行选定适当流程。

## 权利与来源

Copyright (c) 2026 Wenkai. All rights reserved.

本项目由 Wenkai 指导并借助 AI 开发。第三方技能作为功能需求的参照，未作为代码或文档组件分发；不能据此承诺全球范围的绝对独创性或司法认定。审查方法和范围见 [AUTHORSHIP.md](AUTHORSHIP.md)。数据库内容、论文及运行依赖不属于本项目的权利声明。
