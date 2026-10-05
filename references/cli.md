# 命令入口

以下 `SKILL_DIR` 为安装目录，输出用新路径。`run.py` 优先使用 TWK_PYTHON，然后选择个人运行环境；`research.py` 为直接入口。命令输出 JSON，失败通常退出码 2；退出 0 也不等于科学判断已通过。

```bash
python3 SKILL_DIR/scripts/run.py doctor
python3 SKILL_DIR/scripts/run.py init NEW_PROJECT --question '研究问题' --type targeted
python3 SKILL_DIR/scripts/run.py search 'airway epithelial senescence' --sources pubmed,europepmc,crossref --limit 20 --out results.json
python3 SKILL_DIR/scripts/run.py lookup '10.1038/nature12373'
python3 SKILL_DIR/scripts/run.py verify results.json --out metadata-check.json
python3 SKILL_DIR/scripts/run.py export results.json --format bib --out references.bib
python3 SKILL_DIR/scripts/run.py citation --claim 'A source-checkable claim' --scope cns --output-file candidates.ris
python3 SKILL_DIR/scripts/run.py download --arxiv '1706.03762' --out NEW_DOWNLOAD_DIR
python3 SKILL_DIR/scripts/run.py claims-init manuscript.md --out claims.json
python3 SKILL_DIR/scripts/run.py claims-check claims.json --base . --mode doc-only
python3 SKILL_DIR/scripts/run.py reader-prepare paper.pdf --out NEW_READER_DIR --render-pages
python3 SKILL_DIR/scripts/run.py reader-render source_map.json translations.json --out reader.md
python3 SKILL_DIR/scripts/run.py reader-check source_map.json translations.json
python3 SKILL_DIR/scripts/run.py reader-math reader.md --json
python3 SKILL_DIR/scripts/run.py screen-init results.json --out screening.json
python3 SKILL_DIR/scripts/run.py flow screening.json
python3 SKILL_DIR/scripts/run.py review-packet manuscript.pdf --reviewers 3 --out NEW_REVIEW_DIR
python3 SKILL_DIR/scripts/run.py rank results.json --keywords senescence epithelial --out ranked.json
python3 SKILL_DIR/scripts/run.py archive ranked.json --workspace NEW_PROJECT
python3 SKILL_DIR/scripts/run.py digest ranked.json --out digest.md
```

`claims-init` 只建立草稿；需实际拆分原子论断、精读来源并填写判断。`reader-prepare` 不执行翻译；Codex 填写逐块译文与复核后再渲染。`review-packet` 不代替独立审稿。

```bash
python3 SKILL_DIR/scripts/run.py data-profile raw.xlsx
python3 SKILL_DIR/scripts/run.py analyze study.json --out NEW_RUN_DIR
python3 SKILL_DIR/scripts/run.py data-research study.json --out NEW_RESEARCH_RUN
python3 SKILL_DIR/scripts/run.py research-followup NEW_RESEARCH_RUN
python3 SKILL_DIR/scripts/run.py notebook-execute NEW_RUN_DIR/analysis.ipynb
python3 SKILL_DIR/scripts/run.py enrich --selected hits.txt --universe measured.txt --gmt pathways.gmt --out enrichment.json
python3 SKILL_DIR/scripts/run.py database-list
python3 SKILL_DIR/scripts/run.py database uniprot --request request.json --out annotation.json
python3 SKILL_DIR/scripts/run.py study-plan '候选关联能否在独立样本中重现？' --analysis NEW_RUN_DIR --out NEW_PLAN_DIR
python3 SKILL_DIR/scripts/run.py experiment-check NEW_PLAN_DIR/experiment-plan.json
python3 SKILL_DIR/scripts/run.py manuscript-build NEW_PLAN_DIR/manuscript-plan.json --claims NEW_PLAN_DIR/claims.json --out NEW_DRAFT.md
```

数据配置见 [实验分析](workflows/experimental-data.md)，生命周期见 [后续研究](workflows/data-driven-research.md)。`--offline` 保留待检索队列，不能报告联网完成。默认后续检索预算为至多 3 个候选、12 次逻辑查询，一次逻辑查询可能有多个 HTTP 请求。

API、分页、转换与出版商入口各有 `--help`。例如：

```bash
python3 SKILL_DIR/scripts/run.py api europepmc PMC123456/fullTextXML --raw --out article.xml
python3 SKILL_DIR/scripts/run.py paginate crossref works --params '{"query":"senescence"}' --record-path message.items --mode cursor --page-key cursor --size-key rows --cursor-path message.next-cursor --pages 2 --limit 50 --out pages.json
python3 SKILL_DIR/scripts/run.py publisher-download --dois '10.1038/nature12373' --route oa --out NEW_DOWNLOAD_DIR --no-si
python3 SKILL_DIR/scripts/run.py jats article.xml --text-only
```

示例中的 PMC123456、claim 和本地文件名是形式占位符，不是已核实材料。`max_pages` 和截断字段必须保留；不要宣称示例检索穷尽。

可选凭据只通过环境变量：NCBI_API_KEY、NCBI_EMAIL、OPENALEX_API_KEY、CROSSREF_MAILTO、UNPAYWALL_EMAIL、S2_API_KEY、CORE_API_KEY、ELSEVIER_API_KEY、ELSEVIER_INST_TOKEN、WILEY_TDM_TOKEN、PAPERCLIP_API_KEY。不要把它们写进公开配置、命令参数或提交记录。

离线回归：`python3 -m unittest discover -s SKILL_DIR/tests -v`。精确验证结果见 audit/VALIDATION.md。
