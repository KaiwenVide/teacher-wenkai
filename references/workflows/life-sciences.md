# 生命科学数据库

44 个数据库使用本项目的原生 Python 协议实现。`database-list` 返回允许的 API 地址、协议类型和版本；不执行或打包第三方插件客户端。`database PROVIDER --request FILE --out RESULT.json` 执行有上限的公开查询。

REST 输入可给 `base_url`（必须是登记地址）、`path`、`params`、`record_path`、`max_items`、`max_depth`、`timeout_sec`、`response_format`。默认 JSON；XML/FASTA/文本保留有限 text_head，不能当作已精读全文。需要完整响应时显式给 `save_raw:true` 和本地 `raw_output_path`。输出保留请求来源、HTTP 状态、截断路径、页数和访问时间。

| 协议/需求 | 输入重点 | 局限 |
|---|---|---|
| UniProt、Reactome、QuickGO 等 REST | 相对 path 和 params | 一次有限响应；max_items 不代表全库覆盖 |
| CIViC、gnomAD、Open Targets | query 或 query_path，variables | 仅查询操作；保留 GraphQL 错误 |
| Bgee、Rhea | SPARQL query | 禁止更新及联邦 SERVICE；保留绑定值和数据类型 |
| FinnGen、BBJ、TPMI、UKB-TOPMed、GTEx | rsid/grch37/grch38/variant 四选一 | 明确目标组装版本；多等位不猜，跨组装 indel 不做未经验证的转换 |
| Genebass | ensembl_gene_id、burden_set | 单基因关联；保留负荷类别，不当作机制证据 |
| ClinicalTrials.gov | action 或 path，params，max_pages | 已注册不等于已完成；完成不等于结果已发表 |
| ClinVar/Variation | action 和相应编号；search 用 terms | 临床解释、断言者与版本需另行核对 |
| Entrez | endpoint，params | efetch 常返回 XML；查询型端点不支持上传 |
| STRING、cBioPortal、RCSB 检索 | 允许端点的 JSON/form POST | 仅指定检索端点，禁止写入操作 |

最小示例：`{"path":"uniprotkb/search","params":{"query":"gene_exact:GPX4 AND organism_id:9606 AND reviewed:true","format":"json","size":5},"record_path":"results"}`。

数据库选择：ID/表达优先 UniProt、Ensembl、HPA；通路/功能优先 Reactome、QuickGO、STRING；化合物优先 PubChem、ChEMBL、BindingDB；独立组学验证优先 PRIDE、BioStudies、ENCODE 等。一次研究只调用与问题相关的来源。

404、限流、认证失败和空响应分别记录，不作为“生物学不存在”的证据。STRING 网络不自动等于物理结合，Reactome 成员不等于通路激活，遗传关联需核对人群、等位基因、LD、组织和共定位。检索前确认实体可以公开；原始患者与实验数据留在本地。

## 已停用的远程接口

eQTL Catalogue 官方已停止 REST API。原生处理器对旧请求返回 remote_api_retired，提供 `local_file` 与 `filters` 入口筛选独立取得的 TSV/TSV.GZ；例如 `{"local_file":"chosen-study.tsv.gz","filters":{"rsid":"rs7412"},"max_items":10}`。默认最多扫描 100000 行并明确截断，不能把局部未找到当全数据阴性。下载地址、数据集版本、组装、效应等位基因及许可需按[官方数据入口](https://www.ebi.ac.uk/eqtl/Data_access/)核对。
