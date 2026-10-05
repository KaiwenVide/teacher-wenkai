# 中英对照与逐图精读

目标区分：快速阅读卡、重点章节精读、完整中英对照。用户要完整时不能用摘要替代。保留可访问全文版本、来源时间、文件哈希和补充材料范围。

1. PDF/DOCX/PPTX/TXT/MD/JATS 用 `reader-prepare` 建 source_map.json 和 translations.json。PDF 建议 `--render-pages`，产出页图用于验证布局、公式、图表。图像/扫描 PDF 无有效文字时进入 OCR/手工提取，不能空文本算全文完成。
2. 原文 block_id 和 locator 稳定，译文逐块写 translation；解释写 explanation，不混入译文。语气与因果强度不升级，数值、单位、公式符号、否定词与限定条件逐项核对。
3. 页面提取可能出现页眉页脚、双栏顺序、断字、重复图注；用页图对照后修订提取版本并重新记录哈希。JATS 文本工具可能跳过图形/表格/公式，这些仍需从 XML/HTML/PDF 单独读取。
4. 每幅图/表建条目：源页/图号/panel、坐标/单位、组别与样本单位、n、误差表示、统计方法、主要观察、作者解释、你的判断、反证/局限。用原图或从源文件裁切，不以重绘替代数据核验。render-pages 的整页图不是已完成图表解释。
5. 公式保留原始表达、变量、适用条件；`reader-math` 检查转义/数学定界符与结构，不证明数学推导正确。需要时实际渲染并检查。
6. 填写 reading_notes.md 的研究问题、方法、关键结果、证据链、竞争解释及最小判别实验；模板空白不算精读完成。
7. `reader-render` 生成 Markdown 与本地 HTML 对照视图。只有真实复核后将 translations.status=reviewed，填写 qa.assessor 与 qa.source_fidelity_checked=true；`reader-check` 校验覆盖/哈希及复核声明。它不能代替内容复核。
8. 交付原文定位、译文、逐图逐表笔记、访问/提取限制；完整双语包未完成时明确草稿，不以“生成文件成功”冒充完成精读。
