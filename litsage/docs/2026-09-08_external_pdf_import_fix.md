# 外部文献导入全文解析修复记录

记录日期：2026-09-08

## 问题现象

外部文献导入时勾选“自动获取全文”，部分 PubMed / PMC 文献仍然显示 PDF 下载、解析或向量化失败。

单独运行 debug 脚本测试 PMC 结构化全文时可以成功：

```bash
python scripts/debug_pdf_ingestion_pipeline.py --pdf-url https://www.ncbi.nlm.nih.gov/pmc/articles/PMC13408697/pdf/
```

测试结果显示：

```text
structured_source=pmc_oai_pmh
structured_text_length=152442
chunk_count=117
embedding_dim=1024
```

这说明 PMC 官方结构化全文获取、切片和 embedding 本身是可用的，问题不在解析能力本身。

## 根因

导入主流程 `_import_one()` 中，只有在 `imported.pdf_url` 存在时才会调用 `_try_process_pdf()`：

```text
include_pdf == true 且 imported.pdf_url 有值 -> 才进入全文处理
```

但 PubMed 候选文献可能具备 `metadata.pmc_id`，即可以通过 PMC 官方接口获取结构化全文；即使 PDF URL 解析失败，仍然应该尝试结构化全文。

原逻辑导致：

```text
有 PMCID
但 PDF URL 未解析出来
-> 不调用 _try_process_pdf()
-> 不尝试 PMC BioC / OAI-PMH
-> 全文解析被跳过
```

这会让前端表现为“勾选了自动获取全文，但没有真正写入全文 chunk”。

## 修复方式

新增判断方法：

```python
def _can_attempt_full_text(self, imported: ImportedPaper) -> bool:
    if imported.pdf_url:
        return True
    if imported.source == LiteratureSource.pubmed.value and str(imported.metadata.get("pmc_id") or "").strip():
        return True
    return False
```

然后将新文献和重复文献的全文处理入口从：

```python
if include_pdf and imported.pdf_url:
```

调整为：

```python
if include_pdf and self._can_attempt_full_text(imported):
```

这样只要 PubMed 候选中存在 `pmc_id`，即使 PDF URL 没有成功解析，也会进入 `_try_process_pdf()`，并优先调用：

```text
_resolve_structured_full_text_for_import()
```

从而走 PMC BioC / OAI-PMH 结构化全文路径。

同时补充了重复文献重试逻辑：

```text
如果文献已经存在于数据库
重新导入时先合并数据库已有 pdf_url / metadata_json
如果数据库里已有 pmc_id，候选对象没带 pmc_id，也能继续尝试 PMC 结构化全文
```

这样可以修复早期失败文献的重试场景，避免因为候选字段不完整而再次跳过全文解析。

## 增加测试

新增测试覆盖以下场景：

```text
候选文献来自 PubMed
metadata 中存在 pmc_id
pdf_url 为空
PDF URL 解析失败
仍然进入 PMC 结构化全文获取
不触发 PDF 下载
成功写入全文 chunk
```

测试名称：

```text
test_import_selected_candidate_with_pmc_id_uses_structured_full_text
```

另外新增重复文献重试测试：

```text
test_duplicate_import_reuses_existing_pmc_id_for_structured_full_text
```

## 验证结果

```bash
python -m compileall app scripts tests
pytest tests/test_app.py -q
```

结果：

```text
48 passed
```

## 后续建议

前端导入结果中目前仍可能把“PDF 失败”和“结构化全文成功”混在同一个提示里。后续可以优化导入返回信息，让用户看到更准确的状态：

```text
全文来源：PMC OAI-PMH
全文解析：成功
PDF 文件下载：未使用
chunk 数量：117
```

这样能避免用户误以为“PDF 下载失败”就等于“全文入库失败”。
