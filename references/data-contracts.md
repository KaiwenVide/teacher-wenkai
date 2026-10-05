# 统一数据约定

schema_version=1.0。JSON Schema 采用 Draft 2020-12；结构合法不是科学正确。

- `schemas/record.schema.json`：record_id、title、identifiers、authors、year、journal、provenance、oa_locations。doi 规范小写；arXiv 版本保留。作者结构可 given/family、literal（团体）或 display/unparsed。页码与文章号分开。
- `schemas/claim.schema.json`：claims 内每项稳定 claim_id、原论断、共享状态、evidence_type、sources、semantic_review、numeric_checks、limitations。sources 有 path 或 url、locator、短 excerpt/视觉转录、source_sha256（本地文件）、访问层级。引用外部原文遵守版权；可用精确定位与短摘录代替长段复制。
- `schemas/screening.schema.json`：records 中 record_id 唯一；duplicate_of 指向保留记录；title_abstract_decision；report_id；retrieval；fulltext_decision；exclusion_reason；study_id；assessors。pending 是明确状态，不能当排除。全文未检索到与全文已读后排除不同。
- `schemas/reviewer.schema.json`：packet_sha256、reviewer_id、isolated_context_id、status、findings。上下文 ID 只能来自真实宿主执行，不可任填 UUID 假装隔离。
- 阅读材料范围用 translations.scope，缺失列表用 translations.missing_materials；兼容读取 qa.missing_materials 并合并显示。有声明缺失材料时保持未完成，不用 reviewed 掩盖缺口。
- reader source_map 原文件 SHA-256 与所有 block_id；translations 指向相同 source_sha256，逐块填写。qa 声明是实际复核记录，不是绕过缺失的按钮。

状态不混用：searches[].status 为 ok/partial/failed；download status 为实际获取状态；claim status 是支持性判断；reading_priority 只是阅读排序；访问层级标 metadata/abstract/full_text。任一模块成功不能替代其它模块的核验。

下载队列例（必须换成真实、已授权地址）：
```json
[
  {"doi":"10.xxxx/actual-doi","kind":"main"},
  {"url":"https://publisher.example/real-supplement.zip","access":"user_authorized","kind":"supplement"}
]
```

原始响应、清洗后的记录、人工判断与导出文件分开保存。每次修订来源保留旧版并重新核对受影响 claims，不静默迁移“已支持”的状态。
