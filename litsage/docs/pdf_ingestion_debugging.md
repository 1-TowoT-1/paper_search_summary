# PDF 全文解析失败诊断说明

记录日期：2026-09-04

当导入结果显示：

```text
PDF 下载、解析或向量化失败
```

可以使用诊断脚本逐步定位问题。该脚本只读运行，不写入 PostgreSQL，也不写入 Milvus。

## 脚本位置

```bash
scripts/debug_pdf_ingestion_pipeline.py
```

## 常用命令

使用数据库中已有文献 ID：

```bash
python scripts/debug_pdf_ingestion_pipeline.py --paper-id 你的paper_id
```

使用 PDF 链接：

```bash
python scripts/debug_pdf_ingestion_pipeline.py --pdf-url "https://example.com/paper.pdf"
```

使用本地 PDF：

```bash
python scripts/debug_pdf_ingestion_pipeline.py --file "D:\path\paper.pdf"
```

只测试下载和 PNG 渲染，不调用大模型：

```bash
python scripts/debug_pdf_ingestion_pipeline.py --paper-id 你的paper_id --skip-llm
```

跳过 embedding 测试：

```bash
python scripts/debug_pdf_ingestion_pipeline.py --paper-id 你的paper_id --skip-embedding
```

## 输出会检查什么

脚本会输出：

1. 当前大模型和 embedding 配置。
2. PDF 下载状态、content-type、文件大小。
3. PDF 是否以 `%PDF-` 开头。
4. PDF 页数。
5. PyMuPDF 原生文本长度和预览。
6. 渲染出的 PNG 文件路径、大小、宽高。
7. 多模态 base64 调用是否成功。
8. 多模态返回文本长度和预览。
9. chunk 切分数量。
10. 第一段 chunk 的 embedding 维度。

## 如何判断问题

如果下载失败：

说明 PDF 链接不可访问、需要登录、被出版商拦截，或不是直接 PDF。

如果 `content_type=text/html` 或 `starts_with_pdf=False`：

说明下载到的不是 PDF，而是网页、跳转页、验证码页或 JavaScript 拦截页。此时不要继续看多模态结果，应先更换可直接下载的 PDF 链接，或改进 PDF resolver。

如果 PNG 能生成且能打开：

说明 PDF 渲染没有问题，问题更可能在大模型 API 请求格式、模型名称或网关兼容性。

如果多模态返回类似：

```text
无法看到上传的图片内容
[Unsupported Image]
[无法识别]
```

说明图片没有被模型 API 正确接收或识别。

如果使用 DeepSeek API：

图片输入必须使用视觉模型，例如 `deepseek-v4-flash-vision-exp`。普通 `deepseek-v4-flash` 是文本模型，图片内容会被替换成占位内容，导致模型回答无法识别图片。

如果多模态识别成功，但 embedding 失败：

说明 BGE-M3 embedding 服务或维度配置有问题。

如果 embedding 维度不是 1024：

需要检查 `.env` 中的 `EMBEDDING_DIM` 和 BGE-M3 服务实际输出维度是否一致。
