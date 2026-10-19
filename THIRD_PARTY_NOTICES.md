# Third-party notices

teacher Wenkai 项目自身的代码、技能指引和随附文档按 [MIT License](LICENSE) 分发。第三方材料保留各自的版权、许可、署名及 NOTICE 要求；项目的 MIT 许可不替第三方提供额外授权。

## 独立依赖与外部服务

Python 依赖通过包管理器独立安装，不随发布包分发源码或二进制。已核验环境的版本和许可线索见 [依赖说明](DEPENDENCIES.md) 与 [依赖清单](audit/dependency-inventory.json)。分发包含依赖的环境或容器时，应重新核查实际取得的各包及传递依赖，并保留它们要求的完整声明。

Paperclip、Scansci、出版商接口及生命科学数据库是独立工具或服务；安装本技能不提供其账号、付费订阅、机构权限或其他服务授权。API 的公开可达性不等于所有返回内容均可任意再分发。

论文正文、图表、补充材料、原始实验数据和数据库记录不因被本工具读取而变成 MIT 作品。按相应来源的许可与访问条件使用；私人对话和未发表研究不属于公开分发内容。产品及项目名称仅用于说明兼容或参考关系，不表示官方背书。

## 设计参照与来源

本次参考 [morluto/rea](https://github.com/morluto/rea) 的开源组织方式：标准 MIT、单独第三方声明、清晰安装说明与证据驱动的调查过程。论文逆向工作流把证据定位与复核的原则用于科研分析；未移植 REA 的逆向引擎、MCP 服务、源码、资产或技能文档，也不把 REA 列作运行依赖。

标准 MIT 许可文本来源为 [GitHub MIT 模板](https://choosealicense.com/licenses/mit/)，许可含义可核对 [OSI 正文](https://opensource.org/license/mit)。其标准法律文本不属于本项目的原创实现声明。

此前科研能力的整合与独立替代范围见 [AUTHORSHIP.md](AUTHORSHIP.md) 和 [功能映射](references/integration-map.md)。后续若引入第三方实现或资产，应逐项记录来源、版本、用途及原始声明；不能通过修改项目 LICENSE 将其改称本项目原创。
