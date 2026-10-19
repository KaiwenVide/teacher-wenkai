# CNS 主刊生命科学月度研读

范围为 Nature、Science、Cell 三本主刊中的生命科学文章。包括基础生物学、医学、生态与进化等相关研究，依当次内容筛选；不把子刊、新闻、社论、撤稿或更正当成独立原始研究。综述可作背景，不能充当趋势所需的独立原始研究数量。

默认处理北京时间上一个完整自然月。日期优先首次在线发表或数据库 firstPublicationDate，记录在线/印刷日期冲突；不要按抓取日期或未来期号重复计数。

## 采集与研读

```bash
python3 SKILL_DIR/scripts/run.py cns-month --out NEW_MONTH_DIR
python3 SKILL_DIR/scripts/run.py cns-month --month 2026-09 --out NEW_MONTH_DIR
```

脚本按主刊 ISSN 查询 Crossref 与 Europe PMC，分页保留原始响应、来源哈希、结果数、上限与失败。默认每来源每刊最多 20 页，每页 100 条；达到上限是覆盖限制，不能宣称穷尽。两库去重后产生 corpus.json、screening.json 和 synthesis.json。候选集合尚未完成生命科学筛选，也不等于已读全文。

继续核对三刊的当月目录和在线发表页面，检查数据库滞后、遗漏与文章类型。参考入口：[Nature](https://www.nature.com/nature/research-articles)、[Science](https://www.science.org/toc/science/current)、[Cell](https://www.cell.com/cell/issues)。页面打不开时记录失败，不虚构目录已核对；发现漏项时以新目录重跑或保存带来源的补查，重新生成筛选与综合文件的 corpus_sha256，保留上一轮记录。

逐篇筛选全部候选，分批读标题与摘要并保存纳入/排除理由。对纳入文章写明发现、方法、局限和实际阅读层级。决定趋势的论文优先获取并精读全文/补充材料，再用论文逆向路线分析关键实验。只读摘要的文章只能支持摘要层级判断；metadata 不支持结果总结。

## 研读与综合格式

screening.json 的 papers 按 record_id 与全部候选一一对应：
- include、life_sciences、month_verified 为布尔值；reason 记录实际筛选依据。
- article_type 为 primary_research / review，排除项可注明 news / editorial / correction / non_life_sciences 等。
- study_key 标识独立研究；同一研究的伴随报告共用一个 key，不能重复算独立支持。
- reading_level 为 abstract / fulltext；finding、methods、limitations、source_locator 为实际阅读所得。
- fulltext_sources 每项记录本地 path、sha256、locator；全文须实际获取、阅读，不能只登记 URL。原文保存在本地，不随开源包发布。

synthesis.json 记录 assessor、summary、coverage_notes、publisher_checks；后者逐刊记录 journal、url、status（checked / unavailable）和 note。实际核对结果包括哪些目录、日期及有无发现漏项。

每个 trends 项包含 title、kind、finding、paper_ids、limitations、next_experiment。一个综合信号至少有两项已阅读、独立的原始研究；仅一篇支持时放入 single_paper_signals（paper_id、finding、limitation）。这些数量条件不能替代主题连贯性或证据质量判断。

kind=monthly_signal 描述当月共同问题、方法转变或机制线索；不要凭标题关键词计数制造趋势。kind=change_over_baseline 须提供此前已复核的月份目录、相同 scope 和 taxonomy_id，并写清 comparison_basis、可比性、分母及检索/分类差异。首次月报没有基线时仅总结当月信号；两个月差异不自动成为长期趋势。主题分类可以调整，但调整后需对基线重编码，不能直接拼接旧分类。

```bash
python3 SKILL_DIR/scripts/run.py cns-report NEW_MONTH_DIR --out NEW_MONTH_REPORT.md
python3 SKILL_DIR/scripts/run.py cns-report NEW_MONTH_DIR --baseline PRIOR_REVIEWED_MONTH_DIR --out NEW_COMPARISON_REPORT.md
```

生成报告后检查来源链接、日期、数字、文章类型、阅读层级与竞争解释，修正失败项。交付中文简报和本地完整台账，关键术语中英对应，说明研究发现会改变哪项实验、模型或判断。没有足够证据时如实报告未发现稳定信号。

## 定时运行边界

技能本身不自建后台服务。用户明确授权月度运行时，用当前应用的自动化能力建立或更新该任务，并核对周期与时区；已有授权无需重复询问。自动化在本对话交付，输出留在本地科研工作区，不上传私有原始数据。API 失败、全文受限或工作目录不可用时报告具体未完成范围；后续重跑使用新目录保留失败记录。

接口依据：[Crossref REST 官方文档](https://github.com/Crossref/rest-api-doc)、[Europe PMC 检索帮助](https://europepmc.org/help)。日期字段与分页行为以当次响应为准，原始响应随本地运行记录保存。
