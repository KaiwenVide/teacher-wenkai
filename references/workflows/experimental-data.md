# 常规实验＋组学数据

## 输入与适用范围

先用 `data-profile` 看真实文件结构。原始 CSV/TSV/XLSX（含非首行表头与多工作表）按文件 SHA-256、工作表、物理行、样本列留痕。样本清单有唯一 sample ID；明确生物学实验单位 unit，不能将同一次培养的孔、视野、测序细胞或仪器复测当作独立生物重复。供体、动物、独立培养批次的嵌套关系不能用任意编号消除。

原生路线：

| 数据 | 处理和推断 | 限制 |
|---|---|---|
| qPCR Ct | 明确技术复测聚合；多内参平均 Ct；负 ΔCt 作为 log2 表达代理；在 ΔCt 尺度比较，报告 2 的 log2FC 次方 | 必须确认扩增效率相当与内参稳定；不同效率需要专门模型；未检出 Ct 不填 0/40 |
| WB 定量、细胞活性、ELISA 浓度等 | 生物学单位聚合、均值/中位数、配对 t/Welch/秩检验或带批次 OLS HC3；显式线性或 log2 尺度 | WB 需已做背景校正的数值；ratio 在单位聚合后按内参归一。若需逐 lane 比值须先在可追溯预处理脚本完成；ELISA 原始 OD 需按本试剂盒标准曲线、空白、稀释倍数和检测限先定量 |
| 蛋白质组/代谢组强度 | wide matrix＋sample sheet；明示技术聚合、归一化及变换；逐特征比较、BH、检出率；不自动填补缺失 | 蛋白组、多重映射、重复 accession 先解决；不把低检出倍数当机制。复杂协变量、肽到蛋白归并需专门流程 |
| bulk RNA-seq 原始 gene counts | PyDESeq2 负二项模型，预设组别比较，可加 batch 或 pair；Cook 过滤；低总 counts 预过滤清单；Wald CI 与显式 BH | 非负整数且矩阵完整；TPM/FPKM 不当 counts；不自动替换离群值；配对需完整；时间交互需专门模型 |
| 数值时间序列 | 组内线性时间斜率；同单位反复测量用 random-intercept mixed model，否则 OLS HC3 | 不是组间 time×treatment 交互检验；非线性、剂量反应、交叉设计单独建模；报告时间单位和模型收敛 |
| 相关性 | 同组、同时间、同批次内按 unit 对齐的 Spearman；完整配对数和 BH | 小样本 p 为近似，仅探索；默认最多 30 特征，更多须预先限定 ≤50；不在组间混合后解释机制 |

FASTQ、质谱 RAW、FCS、显微图像或单细胞 h5ad 的仪器级预处理没有冒充成已实现的表格分析。实际遇到它们时，读取对应格式、安装环境及实验方案，创建可复现的专门预处理（例如 bulk counts、供体级 pseudobulk、已门控事件统计或盲法图像定量），校验中间产物后接入本流程。不能将每个细胞当作独立供体。新装依赖只在所需任务的独立环境完成。

## 配置

`assets/templates/experiment-config.json` 是可填模板。`assets/examples/mixed-demo/` 是可运行的**合成**演示，不代表用户实验结果。

- `input`: data、layout（long/wide）、sheet、header_row（1-based）、samples、sample_sheet、sample_header_row；相对路径相对于配置文件。
- `columns` / `sample_columns`：规范字段→实际列名，例如 `{"feature":"Gene","value":"Intensity","sample":"SampleID","unit":"Donor","group":"Treatment"}`。可选 technical、pair、batch、time、symbol、accession。注释只能来自一个表；join 必须 many-to-one。
- `study`: design 为 independent/paired/longitudinal，data_scale 为 linear/log2/ct/raw_counts，independent_units_confirmed，sample_is_biological_unit（只有确实如此时），time_unit、organism、taxon_id、feature_namespace。
- `comparisons`: 每个 `{name,test,reference}` 的方向都是 test − reference / test ÷ reference。分析前根据问题固定比较；不要看完结果才换参照和检验。
- `analysis`: technical_aggregation none/mean/median（counts 可 sum）、test、transform none/log2、adjust_batch、min_n（默认 3，底线 2）、alpha（默认 .05）、minimum_effect（分析尺度）、min_detection（默认 .7）、missing_values、fdr_family all（默认）/per_contrast。
- `qpcr`: reference_features、equal_efficiency_confirmed。`normalization`: method ratio、reference_features。所有预处理规则写入配置，不隐式 log、归一化、填零或删点。
- `counts`: min_total_count（默认 10，分析前明确）；PyDESeq2 关闭自动 Cook 替换及 independent filtering，保留 Cook p 过滤，便于全部比较的统一 BH。`deseq2_padj` 是工具每个比较的原生值，最终 q 是所声明的校正族。
- `correlations`: enabled、features、min_n。`plots.features` 选择展示特征；选择展示不改变完整检验集合。
- `reversal`: model_vs_control/treatment_vs_model/treatment_vs_control 三个值必须是已有比较名。三组都保留，不把 p>.05 叫完全恢复或等效。
- `research`: 见 [后续研究](data-driven-research.md)。

多组/多时间点默认 BH 族为所有可估计 feature×contrast×time；相关性、组内趋势各自是另一个探索性检验族，并非联合确认性分析。若检验因缺失、低检出、零方差、秩亏、样本不足失败，保留状态；不得将 None 改成 p=1 或 p=0。多批次无调整、组别与批次完全混杂、单位定义缺失阻止推断，仍输出有用 QC。

标准 CLI：

```bash
python3 /path/to/teacher-wenkai/scripts/run.py data-profile raw.xlsx
python3 /path/to/teacher-wenkai/scripts/run.py analyze study.json --out analysis/run-01
python3 /path/to/teacher-wenkai/scripts/run.py data-research study.json --out analysis/run-02
python3 /path/to/teacher-wenkai/scripts/run.py notebook-execute analysis/run-01/analysis.ipynb
python3 /path/to/teacher-wenkai/scripts/run.py enrich --selected hits.txt --universe measured.txt --gmt pathways.gmt --out enrichment.json
```

每次使用新输出目录，保留旧结果。`--no-figures` / `--no-notebook` 可减负。analyze 本地执行；data-research 默认真正调用检索；`--offline` 只建立待执行卡片，必须标注没有联网。`reproduce.py NEW_DIRECTORY` 校验输入/代码哈希后重算。Notebook 默认生成未执行；执行成功才称已验证。

富集使用相同物种、相同 ID namespace 与版本化 GMT。背景集必须是**实际测量且有资格进入选择**的特征，不能默认整个基因组；选择阈值、ID 映射覆盖与未映射列表随报告保存。GMT 中所有与背景相交的通路都参与 BH，零重叠项不删掉；富集不等于激活。

## 交付与检查

交付 analysis.json、原始定位表、生物学单位表、全部比较、检出/缺失表、相关性、趋势、配置、图、复现脚本及 Notebook。检查图中标签、样本量、CI、尺度、比较方向与实际结果一致；PNG/SVG 必须打开抽查。研究报告对直接数据事实、模型推断、数据库注释、跨模型文献和假设分别陈述。

方法依据：[SciPy t 检验](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ttest_ind.html)、[statsmodels 多重校正](https://www.statsmodels.org/stable/generated/statsmodels.stats.multitest.multipletests.html)、[PyDESeq2](https://pydeseq2.readthedocs.io/en/stable/auto_examples/plot_minimal_pydeseq2_pipeline.html)。环境版本和当前实现以 analysis.json 为准。
