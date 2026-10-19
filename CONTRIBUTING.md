# 参与 teacher Wenkai

欢迎通过 [Issues](https://github.com/KaiwenVide/teacher-wenkai/issues) 提交可复现问题或功能需求，通过 Pull Request 改进代码和文档。

提交问题时提供版本、Python/操作系统、最小重现命令、预期与实际行为、经过脱敏的日志。研究问题说明实际设计和测量单位；使用合成或有公开许可的数据，避免上传患者身份、认证信息或未发表课题。

## 开发与核验

Python 3.12 是当前验证环境。使用独立虚拟环境安装 requirements.txt；requirements-lock.txt 是既有验证快照，不代表每个平台均已测试。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/research.py doctor
```

让测试覆盖可观察的错误或关键科学边界，例如配对/生物重复、缺失数据、原文定位、首次发表日期、跨月去重和部分检索失败。修改报告结构时实际查看输出；仅模板字段完整不能证明论文或趋势判断正确。联网测试单独标明执行日期、真实范围和失败，避免把模拟响应写成服务可用性。

发布前更新版本、来源/依赖记录和 audit/source-manifest.json，运行 scripts/verify_release.py，核对发布包与安装文件一致。生成的清单只证明与该清单一致，不是数字签名或权利认证。

## 许可与贡献来源

提交你有权以本项目 MIT 许可提供的贡献。新贡献默认按 MIT 提供，贡献者保留其依法拥有的版权，不要求转让给维护者。引入第三方内容须说明来源与许可，并更新 THIRD_PARTY_NOTICES.md，保留必须的原始声明；可说明 AI 辅助生成及你实际执行的验证。重要署名不应因格式调整被删除。
