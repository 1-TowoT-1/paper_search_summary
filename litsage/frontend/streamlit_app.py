from __future__ import annotations

from typing import Any

import requests
import streamlit as st


DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"
IMPORT_SELECTED_TIMEOUT_SECONDS = 1800


def local_request(method: str, url: str, **kwargs: Any) -> requests.Response:
    with requests.Session() as session:
        session.trust_env = False
        return session.request(method, url, **kwargs)


def init_state() -> None:
    st.session_state.setdefault("api_base_url", DEFAULT_API_BASE_URL)
    token_from_url = st.query_params.get("access_token", "")
    token_type_from_url = st.query_params.get("token_type", "bearer")
    st.session_state.setdefault("access_token", token_from_url)
    st.session_state.setdefault("token_type", token_type_from_url)
    st.session_state.setdefault("current_username", "")
    st.session_state.setdefault("current_email", "")


def api_url(path: str) -> str:
    return f"{st.session_state.api_base_url.rstrip('/')}{path}"


def auth_headers() -> dict[str, str]:
    if not st.session_state.access_token:
        return {}
    token_type = st.session_state.token_type or "bearer"
    return {"Authorization": f"{token_type} {st.session_state.access_token}"}


def show_response(response: requests.Response, show_body: bool = True) -> Any | None:
    try:
        body = response.json()
    except ValueError:
        body = response.text

    if response.ok:
        st.success(f"{response.status_code} {response.reason}")
    else:
        st.error(f"{response.status_code} {response.reason}")

    if show_body:
        if isinstance(body, (dict, list)):
            st.json(body)
        else:
            st.code(str(body))
    return body if response.ok else None


def render_import_status_summary(body: dict[str, Any]) -> None:
    stats = body.get("stats") if isinstance(body, dict) else None
    if not isinstance(stats, dict):
        return

    st.subheader("导入结果解读")
    metric_items = [
        ("抓取", "fetched"),
        ("新入库", "created"),
        ("重复跳过", "skipped_duplicate"),
        ("摘要向量", "abstract_vectorized"),
        ("PDF 补跑", "pdf_retried"),
        ("PDF 已存在", "pdf_already_processed"),
        ("PDF 成功", "pdf_processed"),
        ("PDF 失败", "pdf_skipped"),
        ("失败", "failed"),
    ]
    columns = st.columns(3)
    for index, (label, key) in enumerate(metric_items):
        columns[index % 3].metric(label, stats.get(key, 0))

    messages = []
    if stats.get("created", 0):
        messages.append(f"{stats['created']} 篇新文献已写入 PostgreSQL，并已写入摘要向量。")
    if stats.get("skipped_duplicate", 0) and stats.get("pdf_already_processed", 0):
        messages.append(f"{stats['pdf_already_processed']} 篇文献已存在，且 PDF 全文分块也已存在，因此完全跳过。")
    if stats.get("skipped_duplicate", 0) and stats.get("pdf_retried", 0):
        messages.append(f"{stats['pdf_retried']} 篇文献已存在，但缺少 PDF 全文分块，系统已尝试补跑 PDF 解析。")
    if stats.get("pdf_processed", 0):
        messages.append(f"{stats['pdf_processed']} 篇文献的 PDF 已解析并写入全文分块向量。")
    if stats.get("pdf_skipped", 0):
        messages.append(f"{stats['pdf_skipped']} 篇文献 PDF 下载、解析或向量化失败；文献元数据可能仍已入库。")
    if stats.get("skipped_embedding_failed", 0):
        messages.append(f"{stats['skipped_embedding_failed']} 篇文献摘要向量化失败，因此没有完成入库。")
    if stats.get("skipped_no_abstract", 0):
        messages.append(f"{stats['skipped_no_abstract']} 篇候选文献没有摘要，已跳过。")
    if stats.get("failed", 0):
        messages.append(f"{stats['failed']} 个步骤失败，请查看下方 JSON 里的 errors。")
    if not messages:
        messages.append("本次没有新增或变更内容。")

    for message in messages:
        st.write(f"- {message}")


def request(method: str, path: str, **kwargs: Any) -> requests.Response:
    headers = kwargs.pop("headers", {})
    timeout = kwargs.pop("timeout", 30)
    headers.update(auth_headers())
    return local_request(method, api_url(path), headers=headers, timeout=timeout, **kwargs)


def remember_auth(access_token: str, token_type: str, username: str = "") -> None:
    st.session_state.access_token = access_token
    st.session_state.token_type = token_type or "bearer"
    st.session_state.current_username = username
    st.query_params["access_token"] = access_token
    st.query_params["token_type"] = st.session_state.token_type


def clear_auth() -> None:
    st.session_state.access_token = ""
    st.session_state.token_type = "bearer"
    st.session_state.current_username = ""
    st.session_state.current_email = ""
    st.query_params.clear()


def refresh_current_user() -> None:
    if not st.session_state.access_token:
        return
    try:
        response = request("GET", "/api/auth/me", timeout=15)
        if response.ok:
            body = response.json()
            st.session_state.current_username = body.get("username", st.session_state.current_username)
            st.session_state.current_email = body.get("email", st.session_state.current_email)
        elif response.status_code == 401:
            clear_auth()
    except requests.RequestException:
        pass


def render_sidebar() -> None:
    with st.sidebar:
        st.header("LitSage")
        st.text_input("FastAPI 地址", key="api_base_url")

        if st.button("检查后端健康状态", use_container_width=True):
            try:
                show_response(local_request("GET", api_url("/health"), timeout=10))
            except requests.RequestException as exc:
                st.error(f"无法连接后端: {exc}")

        st.divider()
        if st.session_state.access_token:
            if not st.session_state.current_username:
                refresh_current_user()
            st.success("已登录")
            if st.session_state.current_username:
                st.write(f"当前用户：{st.session_state.current_username}")
            if st.session_state.current_email:
                st.write(f"邮箱：{st.session_state.current_email}")
            st.caption(st.session_state.access_token[:36] + "...")
            if st.button("退出登录", use_container_width=True):
                clear_auth()
                st.rerun()

            with st.expander("账号设置"):
                new_email = st.text_input("新邮箱", key="account_new_email")
                col_code, col_apply = st.columns(2)
                if col_code.button("发送邮箱验证码", use_container_width=True):
                    try:
                        body = show_response(
                            local_request(
                                "POST",
                                api_url("/api/auth/email/verification-code"),
                                json={"email": new_email},
                                timeout=30,
                            )
                        )
                        if isinstance(body, dict) and body.get("dev_code"):
                            st.session_state["last_email_code"] = body["dev_code"]
                    except requests.RequestException as exc:
                        st.error(f"验证码请求失败: {exc}")
                email_code = st.text_input("邮箱验证码", key="account_email_code")
                if st.session_state.get("last_email_code"):
                    st.caption(f"开发验证码：{st.session_state['last_email_code']}")
                if col_apply.button("修改邮箱", use_container_width=True):
                    try:
                        body = show_response(
                            request(
                                "PATCH",
                                "/api/auth/me/email",
                                json={"new_email": new_email, "verification_code": email_code},
                            )
                        )
                        if isinstance(body, dict):
                            st.session_state.current_email = body.get("email", "")
                    except requests.RequestException as exc:
                        st.error(f"修改邮箱失败: {exc}")

                st.divider()
                old_password = st.text_input("旧密码", type="password", key="account_old_password")
                new_password = st.text_input("新密码", type="password", key="account_new_password")
                if st.button("修改密码", use_container_width=True):
                    try:
                        show_response(
                            request(
                                "PATCH",
                                "/api/auth/me/password",
                                json={"old_password": old_password, "new_password": new_password},
                            )
                        )
                    except requests.RequestException as exc:
                        st.error(f"修改密码失败: {exc}")
        else:
            login_tab, register_tab = st.tabs(["登录", "注册"])

            with login_tab:
                username = st.text_input("用户名", key="login_username")
                password = st.text_input("密码", type="password", key="login_password")
                if st.button("登录", use_container_width=True):
                    payload = {"username": username, "password": password}
                    try:
                        response = local_request("POST", api_url("/api/auth/login"), json=payload, timeout=30)
                        body = show_response(response)
                        if isinstance(body, dict) and body.get("access_token"):
                            remember_auth(body["access_token"], body.get("token_type", "bearer"), username)
                            refresh_current_user()
                            st.rerun()
                    except requests.RequestException as exc:
                        st.error(f"登录请求失败: {exc}")

            with register_tab:
                username = st.text_input("用户名", key="register_username")
                email = st.text_input("邮箱", key="register_email")
                password = st.text_input("密码", type="password", key="register_password")
                if st.button("注册", use_container_width=True):
                    payload = {"username": username, "email": email, "password": password}
                    try:
                        show_response(local_request("POST", api_url("/api/auth/register"), json=payload, timeout=30))
                    except requests.RequestException as exc:
                        st.error(f"注册请求失败: {exc}")

            st.divider()
            st.info("请先登录再调用需要认证的接口")


def render_search() -> None:
    st.subheader("文献搜索")
    query = st.text_input("自然语言检索", placeholder="例如：transformer 在时间序列预测中的应用")
    col1, col2, col3, col4 = st.columns(4)
    year_from = col1.number_input("起始年份", min_value=1900, max_value=2100, value=None, step=1)
    year_to = col2.number_input("结束年份", min_value=1900, max_value=2100, value=None, step=1)
    author = col3.text_input("作者")
    source = col4.selectbox("来源", ["", "arxiv", "semantic_scholar", "pubmed"])
    limit = st.slider("返回数量", 1, 50, 20)

    if st.button("开始搜索", type="primary"):
        params: dict[str, Any] = {"q": query, "limit": limit}
        if year_from:
            params["year_from"] = int(year_from)
        if year_to:
            params["year_to"] = int(year_to)
        if author:
            params["author"] = author
        if source:
            params["source"] = source

        try:
            body = show_response(request("GET", "/api/search", params=params))
            if isinstance(body, dict):
                st.session_state["last_search_results"] = body.get("results", [])
        except requests.RequestException as exc:
            st.error(f"搜索请求失败: {exc}")

    with st.expander("查询改写调试"):
        rewrite_query = st.text_input("待改写查询", key="rewrite_query")
        if st.button("生成改写"):
            try:
                show_response(local_request("POST", api_url("/api/search/rewrite"), params={"q": rewrite_query}, timeout=30))
            except requests.RequestException as exc:
                st.error(f"查询改写失败: {exc}")


def render_import() -> None:
    st.subheader("文献导入")
    query = st.text_input("导入查询", key="import_query")
    sources = st.multiselect("数据源", ["arxiv", "semantic_scholar", "pubmed"], default=["arxiv"])
    limit = st.slider("候选数量", 1, 100, 20, key="import_limit")

    if st.button("搜索候选文献", type="primary"):
        payload = {"query": query, "sources": sources, "limit": limit, "include_pdf": False}
        try:
            body = show_response(request("POST", "/api/papers/import/preview", json=payload, timeout=90))
            if isinstance(body, dict):
                st.session_state["import_candidates"] = body.get("candidates", [])
        except requests.RequestException as exc:
            st.error(f"候选文献搜索失败: {exc}")

    candidates = st.session_state.get("import_candidates", [])
    if not candidates:
        return

    st.divider()
    st.subheader("候选文献筛选")
    sort_by = st.selectbox("排序", ["发布时间", "标题", "来源 ID"], key="import_sort_by")
    reverse_sort = st.checkbox("倒序", value=True, key="import_sort_desc")
    select_all = st.checkbox("全选当前候选文献", key="import_select_all")
    include_pdf = st.checkbox("导入时尝试解析 PDF 全文", key="import_include_pdf_selected")
    sorted_candidates = sorted(
        candidates,
        key=lambda paper: {
            "发布时间": paper.get("published_date") or "",
            "标题": paper.get("title") or "",
            "来源 ID": paper.get("source_id") or "",
        }[sort_by],
        reverse=reverse_sort,
    )

    rows = []
    for index, paper in enumerate(sorted_candidates):
        authors = ", ".join(
            author_item.get("name", "")
            for author_item in paper.get("authors", [])
            if isinstance(author_item, dict)
        )
        rows.append(
            {
                "select": select_all,
                "index": index,
                "title": paper.get("title", ""),
                "authors": authors,
                "published_date": paper.get("published_date"),
                "doi": paper.get("doi"),
                "source": paper.get("source"),
                "source_id": paper.get("source_id"),
                "abstract": paper.get("abstract", "")[:500],
            }
        )

    edited_rows = st.data_editor(
        rows,
        use_container_width=True,
        hide_index=True,
        disabled=["index", "title", "authors", "published_date", "doi", "source", "source_id", "abstract"],
        column_config={
            "select": st.column_config.CheckboxColumn("入库"),
            "index": st.column_config.NumberColumn("序号"),
            "title": st.column_config.TextColumn("标题", width="large"),
            "authors": st.column_config.TextColumn("作者", width="medium"),
            "published_date": st.column_config.TextColumn("发布时间"),
            "doi": st.column_config.TextColumn("DOI"),
            "source": st.column_config.TextColumn("来源"),
            "source_id": st.column_config.TextColumn("来源 ID"),
            "abstract": st.column_config.TextColumn("摘要预览", width="large"),
        },
        key="import_candidates_editor",
    )
    selected = [sorted_candidates[row["index"]] for row in edited_rows if row.get("select")]
    st.caption(f"已选择 {len(selected)} / {len(sorted_candidates)} 篇")

    if st.button("导入勾选文献", disabled=not selected, use_container_width=True):
        payload = {"papers": selected, "include_pdf": include_pdf}
        try:
            with st.spinner("正在入库；如果勾选了 PDF 全文解析，可能需要数分钟。"):
                body = show_response(
                    request(
                        "POST",
                        "/api/papers/import/selected",
                        json=payload,
                        timeout=IMPORT_SELECTED_TIMEOUT_SECONDS,
                    ),
                    show_body=False,
                )
            if isinstance(body, dict):
                render_import_status_summary(body)
                with st.expander("原始 JSON"):
                    st.json(body)
        except requests.RequestException as exc:
            st.error(f"勾选文献入库失败: {exc}")


def render_projects() -> None:
    st.subheader("研究项目")
    with st.form("create_project"):
        name = st.text_input("项目名称")
        description = st.text_area("项目描述")
        submitted = st.form_submit_button("创建项目")
    if submitted:
        try:
            show_response(request("POST", "/api/projects", json={"name": name, "description": description or None}))
        except requests.RequestException as exc:
            st.error(f"创建项目失败: {exc}")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("刷新项目列表", use_container_width=True):
            try:
                body = show_response(request("GET", "/api/projects"))
                if isinstance(body, list):
                    st.session_state["projects"] = body
            except requests.RequestException as exc:
                st.error(f"获取项目失败: {exc}")

    with col2:
        project_id = st.text_input("项目 ID", key="summary_project_id")
        if st.button("项目批量总结", use_container_width=True):
            try:
                show_response(request("POST", f"/api/projects/{project_id}/summary"))
            except requests.RequestException as exc:
                st.error(f"项目总结失败: {exc}")

    projects = st.session_state.get("projects", [])
    if projects:
        st.dataframe(projects, use_container_width=True)


def render_qa() -> None:
    st.subheader("RAG 文献问答")
    question = st.text_area("问题", placeholder="例如：这些论文的主要方法差异是什么？")
    scope = st.selectbox("问答范围", ["paper", "project", "search_results"])
    paper_id = st.text_input("单篇文献 ID")
    project_id = st.text_input("项目 ID")
    paper_ids_text = st.text_area("多个文献 ID，每行一个")
    session_id = st.text_input("会话 ID，可留空")

    if st.button("提交问题", type="primary"):
        paper_ids = [line.strip() for line in paper_ids_text.splitlines() if line.strip()]
        payload = {
            "question": question,
            "scope": scope,
            "paper_id": paper_id or None,
            "project_id": project_id or None,
            "paper_ids": paper_ids,
            "session_id": session_id or None,
        }
        try:
            show_response(request("POST", "/api/qa", json=payload))
        except requests.RequestException as exc:
            st.error(f"问答请求失败: {exc}")


def render_papers() -> None:
    st.subheader("数据库文献")
    with st.expander("检索已入库文献", expanded=True):
        q = st.text_input("综合关键词", placeholder="标题、摘要、DOI、作者、来源 ID", key="paper_catalog_q")
        col_a, col_b, col_c = st.columns(3)
        title = col_a.text_input("标题包含", key="paper_catalog_title")
        doi = col_b.text_input("DOI 包含", key="paper_catalog_doi")
        author = col_c.text_input("作者包含", key="paper_catalog_author")
        col_d, col_e, col_f, col_g = st.columns(4)
        source = col_d.selectbox("来源", ["", "arxiv", "semantic_scholar", "pubmed"], key="paper_catalog_source")
        source_id = col_e.text_input("来源 ID", key="paper_catalog_source_id")
        year_from = col_f.text_input("起始年份", key="paper_catalog_year_from")
        year_to = col_g.text_input("结束年份", key="paper_catalog_year_to")
        limit = st.slider("查询数量", 1, 100, 20, key="paper_catalog_limit")

        if st.button("查询数据库文献", type="primary"):
            params: dict[str, Any] = {"limit": limit, "offset": 0}
            for key, value in {
                "q": q,
                "title": title,
                "doi": doi,
                "author": author,
                "source": source,
                "source_id": source_id,
            }.items():
                if value:
                    params[key] = value
            if year_from.strip().isdigit():
                params["year_from"] = int(year_from)
            if year_to.strip().isdigit():
                params["year_to"] = int(year_to)

            try:
                body = show_response(request("GET", "/api/papers", params=params))
                if isinstance(body, dict):
                    st.session_state["paper_catalog_results"] = body.get("results", [])
            except requests.RequestException as exc:
                st.error(f"查询文献失败: {exc}")

        results = st.session_state.get("paper_catalog_results", [])
        if results:
            rows = []
            for paper in results:
                authors = ", ".join(
                    author_item.get("name", "")
                    for author_item in paper.get("authors", [])
                    if isinstance(author_item, dict)
                )
                rows.append(
                    {
                        "system_id": paper.get("id"),
                        "title": paper.get("title"),
                        "doi": paper.get("doi"),
                        "authors": authors,
                        "source": paper.get("source"),
                        "source_id": paper.get("source_id"),
                        "published_date": paper.get("published_date"),
                    }
                )
            st.dataframe(rows, use_container_width=True)

    st.subheader("文献详情、总结与删除")
    paper_id = st.text_input("系统文献 ID", help="先在上方检索数据库文献，再复制 system_id。DOI 保存在 papers.doi 中，不作为当前接口路径参数。", key="paper_detail_id")
    col1, col2 = st.columns(2)
    if col1.button("获取详情", use_container_width=True):
        try:
            show_response(request("GET", f"/api/papers/{paper_id}"))
        except requests.RequestException as exc:
            st.error(f"获取文献详情失败: {exc}")
    if col2.button("生成/获取总结", use_container_width=True):
        try:
            show_response(request("GET", f"/api/papers/{paper_id}/summary"))
        except requests.RequestException as exc:
            st.error(f"获取文献总结失败: {exc}")

    with st.expander("删除文献与向量"):
        st.warning("删除会先清理 Milvus 向量，再删除项目关联和 PostgreSQL 元数据。只有自己项目目录中的文献允许删除。")
        confirm_delete = st.checkbox("确认删除该系统文献 ID 对应的文献和向量", key="delete_paper_confirm")
        delete_disabled = not st.session_state.access_token or not paper_id.strip() or not confirm_delete
        if delete_disabled:
            st.caption("请先登录、填写系统文献 ID，并勾选确认后再删除。")
        if st.button("删除文献与向量", type="primary", use_container_width=True, disabled=delete_disabled):
            try:
                show_response(request("DELETE", f"/api/papers/{paper_id}", timeout=60))
            except requests.RequestException as exc:
                st.error(f"删除文献失败: {exc}")


def render_tasks() -> None:
    st.subheader("任务状态")
    task_id = st.text_input("任务 ID")
    if st.button("查询任务"):
        try:
            show_response(request("GET", f"/api/tasks/{task_id}"))
        except requests.RequestException as exc:
            st.error(f"任务查询失败: {exc}")


def main() -> None:
    st.set_page_config(page_title="LitSage", layout="wide")
    init_state()
    render_sidebar()

    st.title("LitSage 文献智能搜索与总结系统")
    st.caption("Streamlit 前端控制台，用于调试和演示 FastAPI Agent 后端能力。")

    tabs = st.tabs(["搜索", "导入", "项目", "问答", "文献", "任务"])
    with tabs[0]:
        render_search()
    with tabs[1]:
        render_import()
    with tabs[2]:
        render_projects()
    with tabs[3]:
        render_qa()
    with tabs[4]:
        render_papers()
    with tabs[5]:
        render_tasks()


if __name__ == "__main__":
    main()
