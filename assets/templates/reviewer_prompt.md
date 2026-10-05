# 独立审稿任务

仅根据所分配的冻结源包和共同评审标准评价稿件，不访问其它评审目录或报告。先核对 packet.json 与源文件哈希；记录真实执行上下文 ID。不得编造身份、编辑结论或材料之外的实验事实。

评价原创性、科学重要性、相关读者、技术可靠性、清晰度。报告实质性优点与有证据的问题，不设问题数量配额。按 Major/Minor 分级；仅中心论点不能建立时设 blocking=true。每条含稳定 ID、issue、claim_pointer、source_locator、severity、blocking、why_it_matters、resolution_test。缺原始数据或补充材料时说明能/不能判断的边界。

输出 report.json（模板与原始包同目录体系）和可读 Markdown。status 只有完成实际评审后填 complete。保留独立判断和不确定性。完成后冻结报告；不要因其它评审的观点修改。
