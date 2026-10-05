# 独立运行依赖

这些依赖通过包管理器独立安装，未作为源代码或二进制放入本仓库。项目 LICENSE 不覆盖它们，使用和再分发时须遵守各自许可。下表为已验证环境的元数据摘记；完整声明和文件位置列于 audit/dependency-inventory.json。

| 直接依赖 | 验证版本 | 包元数据中的许可 |
|---|---|---|
| pypdf | 6.19.0 | BSD-3-Clause |
| pypdfium2 | 5.14.0 | BSD-3-Clause, Apache-2.0, dependency licenses |
| Pillow | 12.3.0 | MIT-CMU |
| jsonschema | 4.26.0 | MIT |
| PyYAML | 6.0.3 | MIT |
| bibtexparser | 1.4.4 | LGPLv3 or BSD |
| numpy | 2.5.3 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| pandas | 2.3.3 | BSD 3-Clause License |
| scipy | 1.18.1 | 见该分发包完整许可；审计 JSON 保留元数据声明 |
| statsmodels | 0.14.6 | BSD License |
| matplotlib | 3.11.2 | 见该分发包完整许可；审计 JSON 保留元数据声明 |
| openpyxl | 3.1.5 | MIT |
| nbformat | 5.11.1 | BSD 3-Clause License |
| nbclient | 0.11.0 | BSD 3-Clause License |
| ipykernel | 7.4.0 | BSD-3-Clause |
| pydeseq2 | 0.5.4 | MIT License |

本版本 PDF 接口使用 pypdf 与 pypdfium2，不要求 PyMuPDF。PDFium 自身及其依赖有单独许可，不能只看 Python 包顶层许可。bibtexparser 提供 LGPLv3 或 BSD 双许可声明；具体可选条款以发行包为准。

requirements-lock.txt 记录本次验证所需依赖闭包（不含旧环境无关包）；不同平台可按 requirements.txt 解析兼容版本。依赖升级可能改变数值或 API 行为，需重新验证。

Paperclip/Scansci 是可选独立服务，既不内嵌也不在上述运行依赖中。数据库与出版商使用条款独立于本项目版权声明。
