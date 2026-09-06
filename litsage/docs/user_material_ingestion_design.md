# 用户自带文献与未发表资料入库设计

## 1. 背景

LitSage 的文献入库不能只面向已发表论文和公开数据库。真实科研场景里，用户会把自己的资料放进系统：

```text
未发表论文
内部技术报告
会议投稿版本
导师或团队共享资料
PDF 文献
Word 文档
Markdown 笔记
实验记录
补充材料
图表截图
```

这些资料可能没有 DOI、没有公开 `source_id`、没有发表日期，也可能没有标准摘要。因此入库模块需要从“公开文献导入器”升级为“研究资料入库系统”。

## 2. 已确认决策

```text
1. 上传文件保存位置：本地 uploads/ 目录
2. 第一版文件格式：PDF / DOCX / Markdown
3. 用户上传资料是否必须绑定项目：否，project_id 可选
4. 未绑定项目时：进入个人资料库
5. 未发表资料默认可见性：private
6. PDF 无法解析文本：需要考虑 OCR 和多模态大模型兜底
7. 是否允许手动覆盖 title / abstract：允许
8. 后续扩展：URL 识别与检索入库
```

## 3. 新定位

建议将模块从：

```text
Paper Importer
```

升级为：

```text
Literature & Research Material Ingestion
```

也就是同时支持：

```text
公开文献检索导入
用户上传资料导入
个人资料库
项目级私有资料库
```

## 4. 核心原则

### 4.1 统一进入知识库

无论来源是 arXiv、用户上传 PDF、Word 文档还是 Markdown 笔记，最终都应能参与：

```text
语义搜索
RAG 问答
单篇理解
多论文对比
综述生成
```

### 4.2 区分来源和可信度

公开文献通常有稳定元数据：

```text
DOI
source
source_id
published_date
authors
venue
```

用户上传资料需要额外标记：

```text
source = user_upload
source_type = user_upload
publication_status = unpublished / preprint / internal / published / unknown
visibility = private
metadata_confidence = high / medium / low
text_extraction_method = native / docx / markdown / ocr / multimodal / manual
```

### 4.3 无摘要策略分来源处理

外部公开文献：

```text
无摘要则跳过，不入库
```

用户上传全文资料：

```text
允许没有摘要
但必须成功解析正文，或通过 OCR/多模态模型提取可信文本
然后由 LLM 生成 ingestion_abstract 后入库
```

用户手动创建资料：

```text
必须提供 title + abstract
```

这样既避免曲解公开文献，也支持用户的未发表资料和内部文档。

## 5. PDF 无法解析文本时是否需要接入大模型？

需要考虑，但建议做成“分层降级”，不要第一版就把所有 PDF 都交给多模态大模型。

推荐流程：

```text
1. 原生解析：PyMuPDF 提取文本
2. OCR 解析：扫描版或图片型 PDF 渲染成图片后 OCR
3. 多模态兜底：复杂页面、图表、公式或 OCR 质量差时调用多模态大模型
4. 仍失败：不入库，返回可读失败原因
```

原因：

```text
OCR 更适合大量页面文字提取，成本低、速度快、输出稳定
多模态大模型更适合理解图表、公式、复杂版面和低质量扫描件
直接用多模态模型处理整篇 PDF 成本高、速度慢，也更难做批量任务
```

因此第一版建议：

```text
必须实现：PDF 原生文本解析
建议预留：OCRExtractor 接口
建议预留：MultimodalExtractor 接口
暂不强制：完整 OCR / 多模态页面理解落地
```

后续的图表理解模块再重点接入多模态模型，用于解释图、表、流程图和公式附近上下文。

## 6. 数据模型改造建议

### 6.1 扩展 `papers` 表

建议新增字段：

```text
source_type              external / user_upload / manual
publication_status       published / preprint / unpublished / internal / unknown
visibility               private / project / public
owner_user_id            上传者
original_filename        原始文件名
file_path                本地文件路径
file_mime_type           application/pdf 等
file_sha256              文件哈希，用于去重
ingestion_status         pending / processing / completed / failed
analysis_status          pending / completed / failed
metadata_confidence      high / medium / low
text_extraction_method   native / docx / markdown / ocr / multimodal / manual
```

用户上传资料可使用：

```text
source = user_upload
source_id = file_sha256
doi = null
published_date = null
visibility = private
```

### 6.2 新增 `paper_files` 表

```sql
paper_files (
    id UUID PRIMARY KEY,
    paper_id UUID REFERENCES papers(id),
    user_id UUID REFERENCES users(id),
    original_filename TEXT,
    stored_path TEXT,
    mime_type VARCHAR,
    file_size_bytes BIGINT,
    sha256 VARCHAR,
    upload_status VARCHAR,
    created_at TIMESTAMP
)
```

建议索引：

```text
user_id + sha256
paper_id
```

### 6.3 新增或落地 `paper_chunks` 表

```sql
paper_chunks (
    id UUID PRIMARY KEY,
    paper_id UUID REFERENCES papers(id),
    chunk_index INT,
    text TEXT,
    page_start INT,
    page_end INT,
    chunk_type VARCHAR,
    metadata JSONB,
    created_at TIMESTAMP
)
```

Milvus 只负责向量检索，PostgreSQL 负责证据原文、页码、chunk 内容和权限过滤。

## 7. 文件保存策略

第一版使用本地目录：

```text
uploads/
```

建议路径：

```text
uploads/{user_id}/{sha256前2位}/{sha256}_{original_filename}
```

好处：

```text
按用户隔离
文件名稳定
方便 sha256 去重
后续迁移 MinIO 时路径结构也清晰
```

## 8. API 改造建议

### 8.1 上传用户资料

```text
POST /api/papers/upload
```

请求形式：

```text
multipart/form-data
file: PDF / DOCX / Markdown
project_id: 可选
title: 可选
abstract: 可选
authors: 可选
publication_status: unpublished / internal / preprint / unknown
visibility: 默认 private
```

如果用户提供 `title` / `abstract`：

```text
优先使用用户提供内容
模型识别结果只作为 metadata 保存
```

### 8.1.1 批量上传用户资料

```text
POST /api/papers/upload/batch
```

请求形式：

```text
multipart/form-data
files: 多个 PDF / DOCX / Markdown
project_id: 可选，批量内所有文件共用
authors_json: 可选，批量内所有文件共用
publication_status: unpublished / internal / preprint / published / unknown
visibility: 默认 private
```

批量上传规则：

```text
1. 逐个文件入库，允许部分成功
2. 单个文件失败不会阻断其他文件
3. 返回 results 列表，标记每个文件的 paper_id、状态和错误原因
4. 多文件上传时不应用 title / abstract 覆盖，避免多篇资料被写入相同元数据
5. 只有单文件上传时允许 title / abstract 覆盖自动识别结果
```

### 8.2 手动创建资料

```text
POST /api/papers/manual
```

适合用户只有标题、摘要、笔记，没有文件的情况。

要求：

```text
title 必填
abstract 必填
project_id 可选
visibility 默认 private
```

### 8.3 外部源导入保留

```text
POST /api/papers/import
POST /api/papers/import/preview
POST /api/papers/import/selected
```

### 8.4 后续 URL 入库预留

```text
POST /api/papers/import/url
```

后续支持：

```text
论文 URL
PDF URL
网页报告
GitHub README
在线技术文档
```

## 9. 入库流程

### 9.1 用户 PDF 入库

```text
用户上传 PDF
→ 保存到本地 uploads/
→ 计算 sha256
→ 用户级 sha256 去重
→ PyMuPDF 原生解析文本
→ 如果解析失败，尝试 OCR / 多模态兜底
→ 如果用户未提供 abstract，LLM 生成 ingestion_abstract
→ 保存 papers
→ 保存 paper_files
→ 分块保存 paper_chunks
→ BGE-M3 向量化 chunk
→ 写入 Milvus paper_chunks
→ 如果提供 project_id，则加入项目
→ 否则进入个人资料库
```

### 9.2 用户 DOCX 入库

```text
用户上传 DOCX
→ 保存到本地 uploads/
→ 计算 sha256
→ 解析段落、标题和表格文本
→ 如果用户未提供 abstract，LLM 生成 ingestion_abstract
→ 保存 papers / paper_files / paper_chunks
→ 写入 Milvus
→ 可选加入项目
```

第一版建议只支持 `.docx`，暂不支持老式 `.doc`。

### 9.3 用户 Markdown 入库

```text
用户上传 Markdown
→ 保存到本地 uploads/
→ 计算 sha256
→ 按标题层级解析文本
→ 如果用户未提供 abstract，LLM 生成 ingestion_abstract
→ 保存 papers / paper_files / paper_chunks
→ 写入 Milvus
→ 可选加入项目
```

## 10. 去重规则

外部文献：

```text
DOI 优先
source + source_id 次之
```

用户上传资料：

```text
同一用户下 file_sha256 相同则视为同一个文件
同一项目中相同 paper_id 不重复关联
```

不同版本策略：

```text
第一版：不同 sha256 视为不同资料
后续：增加 paper_versions 表管理版本
```

## 11. 对现有模块的影响

### 11.1 `paper_importer.py`

建议后续拆分为：

```text
ExternalPaperImporter
UserMaterialImporter
PaperIngestionService
```

第一版可以先新增 `UserMaterialImporter`，减少对现有 arXiv 导入逻辑的扰动。

### 11.2 `embedding_service.py`

需要支持：

```text
摘要 embedding
全文 chunk embedding
图表解释文本 embedding
用户笔记 embedding
```

### 11.3 `vector_store.py`

需要支持 metadata filter：

```text
project_id
user_id
source_type
publication_status
visibility
paper_id
chunk_type
```

### 11.4 `rag_service.py`

必须按权限和项目范围检索：

```text
只能检索当前用户有权限访问的 paper/chunk
项目问答只检索项目内资料
回答引用必须标明资料类型
```

### 11.5 `frontend/streamlit_app.py`

需要新增：

```text
上传资料入口
文件类型提示
项目选择，可选
发表状态选择
可见性显示，默认 private
手动 title / abstract 输入
解析状态展示
```

## 12. 第一版建议实现范围

```text
1. 本地 uploads/ 文件保存
2. PDF / DOCX / Markdown 上传
3. 用户级 sha256 去重
4. project_id 可选，未绑定进入个人资料库
5. visibility 默认 private
6. 允许用户手动 title / abstract 覆盖
7. PDF 原生解析
8. OCR / 多模态接口预留
9. LLM 生成 ingestion_abstract
10. 保存 papers
11. 保存 paper_files
12. 保存 paper_chunks
13. chunk 写入 Milvus
14. Streamlit 增加上传入口
```

## 13. 暂缓范围

```text
1. URL 识别检索入库
2. 老式 .doc 文件
3. 完整 OCR 落地
4. 完整多模态页面理解落地
5. 图表裁剪和解释
6. 文件版本管理
7. 团队权限
```

## 14. 仍需确认

```text
1. OCR 第一版是否真正接入，还是只预留接口？
2. 如果接入 OCR，优先使用哪种方案：PaddleOCR / Tesseract / 多模态模型？
3. Markdown 中的本地图片引用第一版是否解析？
4. 单个上传文件大小限制是多少？建议 50MB
5. uploads 是否按 user_id 分目录保存？建议是
```
