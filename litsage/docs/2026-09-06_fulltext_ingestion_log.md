# 2026-09-06 全文获取与在线检索入库优化日志

## 1. 今日背景

今天主要围绕“在线检索文献后直接入库全文”这条链路进行排查和优化。

原来的使用体验是：用户在文献获取模块检索到 PubMed 文献后，即使勾选了获取全文，系统仍可能只入库摘要，或者在自动下载 PDF 时遇到跳转、验证码、权限限制等问题。这样会导致后续项目问答只能看到标题、摘要，无法真正基于全文回答研究方法、实验设计、结果和图表相关问题。

本轮优化的目标是：尽量让 PubMed/PMC 文献可以从检索结果直接进入知识库，不要求用户先手动下载 PDF 再上传。

## 2. 遇到的问题

### 2.1 PMC PDF 链接存在跳转

数据库中保存的 PDF 地址可能是：

```text
https://www.ncbi.nlm.nih.gov/pmc/articles/PMC13408697/pdf/
```

但浏览器实际访问时会跳转到更具体的 PDF 文件地址：

```text
https://pmc.ncbi.nlm.nih.gov/articles/PMC13408697/pdf/41467_2026_Article_74360.pdf
```

这说明仅保存 `/pdf/` 目录型链接并不总是等价于真实 PDF 文件链接。程序如果没有正确处理跳转和最终 URL，后续可能无法稳定下载 PDF。

### 2.2 程序访问 PMC PDF 时可能遇到验证码页面

测试脚本曾经访问 PMC PDF 地址时，返回的不是 PDF，而是 HTML 页面，其中包含 reCAPTCHA/challenge 信息。

这类问题通常不是代码解析错误，而是网站侧的自动化访问限制。即使 Selenium 可以模拟浏览器，也不适合作为科研系统的默认方案，因为它可能不稳定，也可能触碰站点访问策略。

### 2.3 直接依赖 PDF 下载不够可靠

PDF 下载链路容易受到以下因素影响：

```text
站点跳转
验证码
反爬策略
权限限制
出版社页面结构变化
PDF 链接隐藏在 HTML 页面中
```

因此，如果把“全文入库”完全绑定到 PDF 下载，就会导致可用性不稳定。

### 2.4 多模态解析不能解决所有下载问题

DeepSeek 视觉模型或其他多模态模型可以识别图片/PDF 页面，但前提是程序已经拿到了有效 PDF，并且能够把页面渲染成清晰 PNG。

如果下载阶段拿到的是验证码 HTML，而不是 PDF，多模态模型看到的自然不是论文页面，也就无法提取正文、摘要或图表信息。

### 2.5 RAG 问答质量依赖全文 chunk

此前项目问答出现“只能看到标题，没有正文或方法部分”的回答，本质原因是知识库里缺少可用全文分块。

只要 `paper_chunks` 中没有正文内容，RAG 检索阶段就只能退化到标题、摘要或无效占位文本，无法支持对研究方法、实验结果、疾病进展等细节问题的回答。

## 3. 解决思路

### 3.1 PubMed/PMC 文献优先走官方结构化全文

今天确定的新策略是：

```text
PubMed 检索元数据
识别 PMCID
优先尝试 PMC BioC / PMC OAI-PMH 结构化全文
结构化全文成功后直接分块、向量化、入库
结构化全文失败后再尝试 PDF 下载
PDF 下载失败时标记需要用户手动补 PDF
```

这样可以绕开一部分 PDF 下载、跳转和验证码问题。

对于 PMC 开放全文文献，官方结构化接口比模拟浏览器下载 PDF 更适合程序化处理，也更稳定、更容易解析为正文片段。

### 3.2 PDF 下载改为后备策略

PDF 下载不再是 PubMed/PMC 全文入库的唯一入口，而是作为结构化全文失败后的补充手段。

后备 PDF 策略仍然保留：

```text
DOI landing page 查找 citation_pdf_url
PMC OA Service 查找 PDF
Europe PMC PDF endpoint 尝试解析
PMC /pdf/ fallback
带 Chrome 风格请求头访问
记录最终跳转 URL
```

但系统不会把验证码 HTML、错误提示、无法识别图片等内容写入知识库。

### 3.3 自动失败时给出手动补全文入口

如果自动获取全文被验证码、权限或站点策略阻断，系统会记录：

```text
manual_pdf_required = true
manual_pdf_required_papers = [...]
```

这表示文献元数据可以先保留，但全文需要用户手动上传 PDF 后补充。

这样可以避免“自动流程失败就完全不可用”，同时也避免污染向量库。

## 4. 今日代码优化点

### 4.1 PDFResolver 新增 PMC 结构化全文解析能力

新增了 PMC 结构化全文结果模型：

```text
StructuredFullTextResult
```

新增结构化全文获取入口：

```text
resolve_pmc_full_text(pmc_id)
```

内部优先级：

```text
PMC BioC JSON
PMC OAI-PMH JATS/XML
```

其中 OAI-PMH 能够返回 PMC 的 JATS XML，适合提取标题、摘要、正文段落、章节标题和图表题注等内容。

### 4.2 PaperImporter 优先使用结构化全文

`paper_importer.py` 的 PDF/全文处理流程调整为：

```text
如果 imported.metadata 或 pdf_url 中存在 PMCID
先调用 PDFResolver.resolve_pmc_full_text
如果拿到可用全文，直接进入 chunk + embedding + Milvus upsert
不再继续下载 PDF
如果结构化全文不可用，再执行原 PDF 下载解析链路
```

这样“在线检索文献直接入库全文”成为主流程，而不是依赖用户后续手动上传。

### 4.3 调试脚本增强

`scripts/debug_pdf_ingestion_pipeline.py` 增加了：

```text
--pmc-id
```

同时，当传入 `--pdf-url` 且 URL 中能识别到 PMCID 时，调试脚本也会先测试 PMC 结构化全文路径。

这样后续遇到 PubMed/PMC 全文问题时，可以快速判断：

```text
是结构化全文不可用
还是 PDF 下载被阻断
还是多模态/embedding 阶段出错
```

### 4.4 测试覆盖补充

新增测试覆盖：

```text
BioC JSON 正文抽取
OAI-PMH JATS/XML 正文抽取
结构化全文成功时不再下载 PDF
```

其中“结构化全文成功时不再下载 PDF”是今天最关键的保护测试，可以防止后续改动把流程又退回到不稳定的 PDF 下载优先。

## 5. 今日验证结果

本地编译通过：

```text
python -m compileall app tests frontend scripts
```

单元测试通过：

```text
.venv\Scripts\python.exe -m pytest tests\test_app.py -q
39 passed
```

使用用户提供的 PMC PDF 地址测试：

```text
.venv\Scripts\python.exe scripts\debug_pdf_ingestion_pipeline.py --pdf-url https://www.ncbi.nlm.nih.gov/pmc/articles/PMC13408697/pdf/ --skip-embedding
```

测试结果显示：

```text
structured_source=pmc_oai_pmh
structured_text_length=152442
chunk_count=117
is_unusable_text=False
```

这说明该文献已经可以通过 PMC OAI-PMH 官方结构化全文接口直接拿到完整正文，并成功切分为可入库的 chunk。

## 6. 当前推荐使用方式

对于 PubMed/PMC 文献，建议优先使用“在线检索文献 -> 勾选获取全文 -> 直接入库”的方式。

如果文献存在 PMCID，系统会优先尝试结构化全文；如果没有 PMCID，或者结构化全文不可用，再尝试 DOI/PDF 解析。

如果自动全文获取失败，前端或接口返回中需要关注：

```text
manual_pdf_required
manual_pdf_required_papers
pdf_skipped
errors
```

这些字段可以帮助判断是否需要用户手动上传 PDF 补全文。

## 7. 后续优化方向

后续可以继续完善以下方向：

```text
前端导入结果展示中突出 PMC 结构化全文命中数量
为需要手动补 PDF 的文献提供一键补全文入口
为 paper_chunks 增加 extraction_method 筛选与诊断页面
对 PMC 结构化全文中的 figure/table caption 做更细粒度分块
对开放获取状态、版权状态和可复用权限做更明确标记
对非 PMC 文献继续增强 DOI landing page 和出版社 PDF 解析
```

总体而言，今天的核心优化是：把 PubMed/PMC 全文入库从“模拟下载 PDF”转向“官方结构化全文优先”。这会明显提升公开医学文献入库的稳定性，也能改善项目级 RAG 问答只能看到标题或摘要的问题。

## 8. 阶段性总结 500 问题处理

今天测试“研究项目 -> 阶段性总结”时，发现一个项目可以正常返回，另一个项目返回：

```text
500 Internal Server Error
```

排查后判断，这类问题通常和项目内数据形态有关，而不是阶段性总结路由本身不可用。可能触发点包括：

```text
历史问答记录中的 answer 为空
旧数据中的 authors / abstract 字段为空或格式不符合当前代码预期
某个项目绑定文献较多，摘要和历史问答拼接后提示词过长
LLM API 调用失败、超时或上下文超限
```

为避免单个项目数据异常导致接口直接 500，今天对 `summary_service.py` 做了防御性优化：

```text
限制阶段性总结读取的文献数量和问答数量
限制每篇摘要和每条历史回答进入提示词的长度
对空 title / abstract / answer / authors 做默认值兜底
对最终 user_prompt 做总长度截断
LLM 生成失败时返回本地兜底 Markdown 总结
```

优化后，即使大模型调用失败，接口也应返回一份可展示的阶段性总结，而不是直接向前端暴露 500。

新增测试覆盖：

```text
阶段性总结格式化逻辑兼容旧空字段
LLM 调用失败时返回兜底 Markdown
```

验证结果：

```text
python -m compileall app tests frontend scripts
.venv\Scripts\python.exe -m pytest tests\test_app.py -q
41 passed
```

后续如果仍遇到 500，需要优先查看 FastAPI 后端控制台 traceback。若错误来自数据库连接、模型字段缺失或响应模型校验，再针对具体 traceback 继续处理。

## 9. 阶段性总结功能调整

根据新的产品定位，阶段性总结不再作为“项目管理”中的独立汇总按钮，而是移动到“研究问答”模块下方。

这样调整的原因是：阶段性总结本质上不是简单把项目资料切片丢给大模型，而是用户围绕某个研究阶段提出复盘问题，例如：

```text
当前项目已经形成了哪些研究思路？
这些文献能支持哪些实验设计？
下一阶段应该优先补哪些证据？
当前项目对某个疾病方向有哪些可跟进的方法？
```

因此，前端新增了“本阶段总结问题”输入框，用户必须输入本次想总结的阶段目标或问题，后端再基于：

```text
项目内绑定文献
被判定为高价值的历史项目问答
用户本次输入的阶段性总结问题
```

生成阶段性总结。

同时，为了避免无意义问题污染项目阶段总结，项目问答保存逻辑也做了调整：

```text
所有项目问答仍然保存，用于保留完整客户沟通过程
每条项目问答额外记录是否进入阶段性总结上下文
优先由大模型判断问答是否具备研究价值
如果大模型判断失败，则使用本地启发式规则兜底
阶段性总结只读取 include_in_summary_context = true 的问答记录
```

新增数据库字段：

```text
project_qas.include_in_summary_context
project_qas.summary_context_reason
```

新增迁移脚本：

```text
migrations/versions/0004_project_qa_summary_context.py
```

本次验证结果：

```text
python -m compileall app tests frontend scripts migrations
.venv\Scripts\python.exe -m pytest tests\test_app.py -q
43 passed
```

上线或本地继续测试前，需要执行数据库迁移：

```text
alembic upgrade head
```

## 10. 阶段性总结全量 500 的兼容修复

阶段性总结调整后，前端出现“不论输入什么都返回 500 Internal Server Error”的情况。

原因判断：

```text
代码新增了 project_qas.include_in_summary_context 和 project_qas.summary_context_reason 字段
但本地 PostgreSQL 中的 project_qas 表可能还没有执行 0004 迁移
summary_service.py 查询 ProjectQA 时直接过滤新字段
真实数据库字段不存在时，SQL 会报错并导致接口 500
```

修复方式：

```text
阶段总结查询前先检查 project_qas 表是否存在新字段
如果新字段存在，继续只读取 include_in_summary_context = true 的高价值问答
如果新字段不存在，则按旧表结构读取 question / answer / created_at，避免接口 500
研究问答保存时也做同样兼容
如果新字段还没迁移，先按旧表字段保存完整问答
如果新字段已迁移，则保存大模型判定结果和判定原因
```

这样做以后，即使用户暂时没有执行：

```text
alembic upgrade head
```

阶段性总结和研究问答也不会因为缺少新字段直接崩溃。

但如果希望启用“无意义问题不进入阶段性总结上下文”的完整能力，仍然需要执行数据库迁移。未迁移状态下，系统会兼容旧表，但无法把每条问答的筛选结果持久化到数据库。

验证结果：

```text
python -m compileall app tests frontend scripts migrations
.venv\Scripts\python.exe -m pytest tests\test_app.py -q
43 passed
```

## 11. 项目管理内容查看与问答清理

研究项目模块新增了项目内容管理能力，目标是让用户可以看到一个项目到底收录了哪些资料，以及项目研究过程中沉淀了哪些问答。

新增能力：

```text
查看指定项目下已绑定的文献
从指定项目中移除单篇或多篇已绑定文献
查看指定项目下历史提问与 AI 回答
查看每条问答是否被纳入阶段性总结上下文
查看大模型或兜底规则给出的纳入/排除原因
删除单条历史问答
批量删除历史问答
```

这个功能用于人工控制项目研究过程中的噪声。即使系统已经通过大模型判断无意义问题是否进入阶段性总结上下文，用户仍然可以手动删除测试问题、闲聊问题、重复问题或不希望保留的问答记录。

新增后端接口：

```text
GET /api/projects/{project_id}/papers
DELETE /api/projects/{project_id}/papers/{paper_id}
POST /api/projects/{project_id}/papers/delete
GET /api/projects/{project_id}/qas
DELETE /api/projects/{project_id}/qas/{qa_id}
POST /api/projects/{project_id}/qas/delete
```

前端调整：

```text
研究项目模块中增加“项目内容”区域
用户选择项目后可分别查看项目文献和历史问答
项目文献支持勾选并批量从当前项目移除
移除项目文献只解除 project_papers 绑定，不删除 papers 原始文献和向量库内容
历史问答表格支持勾选
提供删除第一条选中问答和批量删除选中问答按钮
删除后自动刷新历史问答列表
```

验证结果：

```text
python -m compileall app tests frontend scripts migrations
.venv\Scripts\python.exe -m pytest tests/test_app.py -q
43 passed
```
