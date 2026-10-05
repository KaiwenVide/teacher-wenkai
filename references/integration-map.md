# 功能参照与独立实现

这些名称标识用户提出的需求来源，不表示第三方作者参与、认可或授权本项目。发布包不附带其代码、SKILL.md、专有语料或服务账户。实现可覆盖对应任务，但并非逐参数兼容所有上游版本。

| 参照能力 | 本项目实现 | 主要取舍 |
|---|---|---|
| paper-lookup | providers/http/model、JATS/arXiv/OpenAlex 转换与分页 | 7 库统一搜索，18 个 API 入口；记录失败与检索上限 |
| nature-academic-search | 检索说明、DOI 回退、书目导入导出与关联核查 | 元数据验证与论断支持分开；订阅库访问需实际权限 |
| nature-citation | citation 候选、CNS 范围与 RIS/ENW/RDF 输出 | 返回候选；语义支持由来源精读决定 |
| literature-review | 纳排协议、筛选台账、record/report/study 计数 | 不内置通用元分析模型；按研究类型另选统计方案 |
| nature-literature-pipeline | 优先级、归档版本、摘要简报与后续阅读 | 优先级不当作证据确定性；不自行定时或发送 |
| nature-reader | pypdf/PDFium 接口、文本定位、双语 MD/HTML 与结构检查 | OCR、复杂公式/图表需视觉复核；脚本不伪称阅读完成 |
| nature-downloader | 原生 OA/授权 URL、Elsevier/Wiley 接口及续跑清单 | SI 用实际授权链接；机构交互登录通过宿主浏览器 |
| scansci-pdf | 原生 DOI/arXiv 批量获取及可选合法请求桥接 | 不复刻外部服务或不可授权下载渠道 |
| nature-ref-verifier | 逐字段比较，Crossref/DataCite/Handle 回退 | 不用 DOI 年份或页差机械判假 |
| paperclip | 独立 CLI 的只读桥接 | 私有语料与认证服务不能重新实现为本地开放数据库 |
| scientific-critical-thinking | 设计/偏倚/混杂、直接证据/外推/反证判断 | 不套万能分数或把预测写成因果 |
| good-question | 问题卡、竞争解释、实验规划、可证伪标准 | 以最小判别实验收敛；模板不替代实际决策 |
| citation-check-skill | 论断 ID、来源哈希、定位、单位与舍入校验 | 数字吻合不证明文本或图像结论正确 |
| nature-reviewer | 冻结材料、独立上下文报告、综合前完整性检查 | 无独立执行条件时不能声称互盲 |
| Life Sciences Databases | 44 原生 API 协议及变异/组装解析 | 不执行原插件客户端；只读、限量、显式失败；不是全端点验证 |
| Data Analytics | 生物学单位 QC、统计模型、图表、重算 Notebook | 为实验/组学重新实现；不以商业 KPI 代替科学终点 |
| Academic Research Skills | 学术项目、实验设计、论断关联稿件与修订路线 | 共用已有检索/精读/审稿，新增 research-plan、experiment-plan、manuscript-plan 实际文件 |

已有原创文献和数据模块保留，经新版本测试。此前个人快照中复制的解析器、引用脚本、数学检查器、Node 下载器、数据库客户端及说明文档不进入此发布版。替代者是本项目的 format_tools、retrieval_tools、database_protocols、lifesciences 和对应原创文档。

保留常规实验与组学矩阵分析。FASTQ、单细胞及质谱原始谱图不在这一通用矩阵分析器的预处理范围；单细胞样本层推断、复杂嵌套/生存模型等需按真实设计使用专用方法。跨组装变异映射在多等位、indel 或链方向不确定时拒绝猜测，以降低静默误配风险。
