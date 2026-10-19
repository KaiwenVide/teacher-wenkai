# 论文逆向研究

把作者公开报告的结果反推为可检查的研究设计与证据链，再决定怎样复现或开展有区分力的下一步实验。借鉴 [REA 的证据驱动调查思路](https://github.com/morluto/rea)，本工作流处理科研材料；不恢复未公开的原始数据，不把推测的作者决策过程当作事实。

## 实际执行

先获取用户给定论文、图表、方法和补充材料，沿用合法全文获取路线。只有 DOI 时先核验元数据并获取可访问材料。只有摘要时做摘要级拆解，明确无法完成逐图与方法复现。当前问题限定某个 Figure/panel 时聚焦该范围。

```bash
python3 SKILL_DIR/scripts/run.py paper-reverse-init paper.pdf supplement.pdf --question '这个结果怎样排除替代解释？' --doi '论文真实 DOI' --render-pages --out NEW_REVERSE_DIR
```

这一步只提取材料和建立锚点。继续实际阅读正文、方法、图和补充材料，填写 reconstruction.json；不要把初始化成功报告为精读完成。扫描图页先做 OCR 或图像阅读，保留原页位置。

从研究问题、关键结论向后追踪到每项实验。逐项记录模型、独立生物学单位、分组、干预、剂量/时间、主要读数、对照、统计、结果和未报告条件。观察事实、作者解释与我们的推断分别写入 evidence；不要因为论文编排顺序就断言实验发生顺序或真实探索历史。

每项 claims 说明证据判断、竞争解释、外推边界和最小判别实验。优先方向、细胞/区室定位与目标依赖，再考虑扩展支路；扰动、救援、时间顺序、正交读数解决哪些不确定性应具体说明。原始数据或关键试剂不可得时，把它列为复现缺口。

最后给出复现所需材料、操作步骤、可行性、成功判据和不同结果的解释。复现方案是计划；仅在有实际运行及结果证据时报告复现成功。

## 数据填写约定

- paper：title、doi、question。
- evidence：evidence_id、statement、kind（observation / author_interpretation / inference）、anchors。
- 文本 anchors：source_id、block_id、quote；短引文须能在该原文块中找到。
- 视觉 anchors：source_id、page、visual_description、visual_checked=true；页必须已渲染并实际查看。
- experiments：experiment_id、question、model、groups、biological_unit、sample_size、intervention、readout、statistics、outcome、evidence_ids、not_reported。未知项目保留空值并在 not_reported 中列出字段名，不能补造样本量。
- claims：claim_id、text、status、evidence_ids、rationale、boundary、alternative_explanations、decisive_test。status 使用技能共享的证据判断词表。
- reproduction：requirements、steps、minimum_discriminating_experiment、success_criterion、alternative_outcomes、feasibility。
- missing_materials 和 review.limitations 记录材料缺口与限制；review.assessor、source_fidelity_checked 仅在实际复核后填写。

```bash
python3 SKILL_DIR/scripts/run.py paper-reverse-report NEW_REVERSE_DIR --out NEW_REPORT.md
```

报告包括逐实验拆解、论断与竞争解释、来源定位、复现方案和未解决问题。结构检查失败时继续修正或如实交付草稿。哈希、短引文和引用关系校验不能证明科学结论或视觉转录正确，仍需实际阅读复核。对原论文的表达只作必要短引与概括。
