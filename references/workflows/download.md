# 合法全文与补充材料获取

先确定实际 DOI/arXiv 版本和访问路径。`download` 从 OA 位置或声明为 `user_authorized` 的 URL 获取 PDF/JATS；批量输入为 JSON items，逐项记录来源、检查结果、失败、哈希和续跑状态。HTML 登录页不能当 PDF，JATS 须有 body；文件有效不等于文章身份正确，仍需核首页题名/DOI。

`publisher-download` 为原创 Python 下载入口：OA/Springer Nature 路由使用公开 OA 解析；Elsevier 与 Wiley 路由使用用户配置的合法凭据。Elsevier 使用 ELSEVIER_API_KEY、可选 ELSEVIER_INST_TOKEN；Wiley 使用 WILEY_TDM_TOKEN。密钥不写入请求文件、命令行或结果，跨域重定向移除凭据头。凭据存在不代表拥有某篇全文权限。

补充材料需要实际链接和文章对应关系；`--supplements FILE` 接收 kind=supplement 的授权 URL 队列。不能按 DOI 猜测 SI，也不把只下载正文声称为全文加 SI 完整获取。

需要机构交互登录时，交由宿主已授权浏览器读取/下载并保留来源；本仓库没有自行启动浏览器、搬运账户状态或绕过付费墙的脚本。下载后以 pypdf 结构检查和人工/代理视觉核对区分“文件存在、可解析、身份正确、阅读完成”四个状态。
