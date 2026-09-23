from __future__ import annotations

import json
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
        ("PDF 链接", "pdf_resolved"),
        ("PDF 未找到", "pdf_unresolved"),
        ("PDF 补跑", "pdf_retried"),
        ("PDF 已存在", "pdf_already_processed"),
        ("PDF 成功", "pdf_processed"),
        ("PDF 失败", "pdf_skipped"),
        ("需手动补 PDF", "manual_pdf_required"),
        ("项目绑定", "project_linked"),
        ("失败", "failed"),
    ]
    columns = st.columns(3)
    for index, (label, key) in enumerate(metric_items):
        columns[index % 3].metric(label, stats.get(key, 0))

    messages = []
    if stats.get("created", 0):
        messages.append(f"{stats['created']} 篇新文献已写入 PostgreSQL，并已写入摘要向量。")
    if stats.get("pdf_resolved", 0):
        messages.append(f"{stats['pdf_resolved']} 篇文献已解析到全文 PDF 链接。")
    if stats.get("pdf_unresolved", 0):
        messages.append(f"{stats['pdf_unresolved']} 篇文献未找到可直接下载的全文 PDF，已保留摘要入库流程。")
    if stats.get("skipped_duplicate", 0) and stats.get("pdf_already_processed", 0):
        messages.append(f"{stats['pdf_already_processed']} 篇文献已存在，且 PDF 全文分块也已存在，因此完全跳过。")
    if stats.get("skipped_duplicate", 0) and stats.get("pdf_retried", 0):
        messages.append(f"{stats['pdf_retried']} 篇文献已存在，但缺少 PDF 全文分块，系统已尝试补跑 PDF 解析。")
    if stats.get("pdf_processed", 0):
        messages.append(f"{stats['pdf_processed']} 篇文献的 PDF 已解析并写入全文分块向量。")
    if stats.get("pdf_skipped", 0):
        messages.append(f"{stats['pdf_skipped']} 篇文献 PDF 下载、解析或向量化失败；文献元数据可能仍已入库。")
    if stats.get("manual_pdf_required", 0):
        messages.append(
            f"{stats['manual_pdf_required']} 篇文献自动获取全文被验证码、权限或站点策略阻断，需要用户手动下载 PDF 后上传补全文。"
        )
    if stats.get("project_linked", 0):
        messages.append(f"{stats['project_linked']} 篇文献已绑定到所选项目。")
    if stats.get("project_already_linked", 0):
        messages.append(f"{stats['project_already_linked']} 篇文献此前已在所选项目中。")
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

    manual_papers = stats.get("manual_pdf_required_papers") or []
    if manual_papers:
        with st.expander("需要手动补 PDF 的文献"):
            for item in manual_papers:
                st.write(f"- {item}")


def request(method: str, path: str, **kwargs: Any) -> requests.Response:
    headers = kwargs.pop("headers", {})
    timeout = kwargs.pop("timeout", 30)
    headers.update(auth_headers())
    return local_request(method, api_url(path), headers=headers, timeout=timeout, **kwargs)


def doi_to_url(doi: str | None) -> str:
    value = str(doi or "").strip()
    if not value:
        return ""
    if value.lower().startswith(("http://", "https://")):
        return value
    return f"https://doi.org/{value}"


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


def fetch_projects(show_error: bool = False) -> list[dict[str, Any]]:
    try:
        response = request("GET", "/api/projects", timeout=15)
        if response.ok:
            body = response.json()
            if isinstance(body, list):
                st.session_state["projects"] = body
                return body
        elif show_error:
            show_response(response)
    except requests.RequestException as exc:
        if show_error:
            st.error(f"获取项目失败: {exc}")
    return st.session_state.get("projects", [])


def render_project_selector(label: str, key: str) -> str:
    projects = fetch_projects()
    options = ["个人资料库（不绑定项目）"] + [
        f"{project.get('name', '未命名项目')} | {project.get('id', '')}" for project in projects
    ]
    selected = st.selectbox(label, options, key=key)
    if selected == options[0]:
        return ""
    return selected.rsplit(" | ", 1)[-1]


def render_searchable_project_selector(prefix: str = "qa", optional: bool = False) -> str:
    col_search, col_refresh = st.columns([4, 1])
    keyword = col_search.text_input("搜索项目库", key=f"{prefix}_project_search", placeholder="输入项目名称关键词")
    if col_refresh.button("刷新", use_container_width=True, key=f"{prefix}_refresh_projects"):
        fetch_projects(show_error=True)

    projects = fetch_projects()
    if keyword.strip():
        query = keyword.strip().lower()
        projects = [project for project in projects if query in str(project.get("name", "")).lower()]

    if not projects:
        st.info("当前没有可选择的项目。请先在“项目”页面创建项目，或调整搜索关键词。")
        return ""

    options = [f"{project.get('name', '未命名项目')} | {project.get('id', '')}" for project in projects]
    if optional:
        options = ["不绑定项目"] + options
    selected = st.selectbox("选择项目", options, key=f"{prefix}_project_selector")
    if optional and selected == "不绑定项目":
        return ""
    return selected.rsplit(" | ", 1)[-1]


def search_database_papers(prefix: str) -> list[dict[str, Any]]:
    q = st.text_input("检索我的文献", placeholder="标题、摘要、DOI、作者、来源 ID", key=f"{prefix}_paper_q")
    col_source, col_limit = st.columns([2, 1])
    source = col_source.selectbox(
        "来源",
        ["", "pubmed", "arxiv", "semantic_scholar", "user_upload", "manual"],
        key=f"{prefix}_paper_source",
    )
    limit = col_limit.slider("返回数量", 1, 100, 20, key=f"{prefix}_paper_limit")

    if st.button("搜索文献", key=f"{prefix}_paper_search_button", use_container_width=True):
        params: dict[str, Any] = {"limit": limit, "offset": 0}
        if q.strip():
            params["q"] = q.strip()
        if source:
            params["source"] = source
        try:
            body = show_response(request("GET", "/api/papers", params=params), show_body=False)
            if isinstance(body, dict):
                st.session_state[f"{prefix}_paper_results"] = body.get("results", [])
        except requests.RequestException as exc:
            st.error(f"检索文献失败: {exc}")

    return st.session_state.get(f"{prefix}_paper_results", [])


def render_paper_selection_table(papers: list[dict[str, Any]], key: str) -> list[str]:
    if not papers:
        return []

    rows = []
    for index, paper in enumerate(papers):
        authors = ", ".join(
            author_item.get("name", "")
            for author_item in paper.get("authors", [])
            if isinstance(author_item, dict)
        )
        rows.append(
            {
                "select": False,
                "index": index,
                "title": paper.get("title", ""),
                "authors": authors,
                "source": paper.get("source", ""),
                "doi": paper.get("doi", ""),
                "paper_id": paper.get("id", ""),
            }
        )

    edited_rows = st.data_editor(
        rows,
        use_container_width=True,
        hide_index=True,
        disabled=["index", "title", "authors", "source", "doi", "paper_id"],
        column_config={
            "select": st.column_config.CheckboxColumn("选择"),
            "index": st.column_config.NumberColumn("序号"),
            "title": st.column_config.TextColumn("标题", width="large"),
            "authors": st.column_config.TextColumn("作者", width="medium"),
            "source": st.column_config.TextColumn("来源"),
            "doi": st.column_config.TextColumn("DOI"),
            "paper_id": st.column_config.TextColumn("文献 ID"),
        },
        key=key,
    )
    return [papers[row["index"]]["id"] for row in edited_rows if row.get("select")]


def bind_papers_to_project(project_id: str, paper_ids: list[str]) -> dict[str, Any] | None:
    if not project_id or not paper_ids:
        return None
    try:
        body = show_response(
            request(
                "POST",
                f"/api/projects/{project_id}/papers/batch",
                json={"paper_ids": paper_ids},
                timeout=60,
            ),
            show_body=False,
        )
        return body if isinstance(body, dict) else None
    except requests.RequestException as exc:
        st.error(f"绑定文献失败: {exc}")
        return None


def delete_selected_papers(paper_ids: list[str]) -> tuple[int, list[dict[str, Any]]]:
    deleted_count = 0
    failures: list[dict[str, Any]] = []
    for paper_id in paper_ids:
        try:
            response = request("DELETE", f"/api/papers/{paper_id}", timeout=60)
            if response.ok:
                deleted_count += 1
            else:
                failures.append(
                    {
                        "paper_id": paper_id,
                        "status_code": response.status_code,
                        "message": response.text[:500],
                    }
                )
        except requests.RequestException as exc:
            failures.append({"paper_id": paper_id, "status_code": None, "message": str(exc)})
    return deleted_count, failures


def fetch_project_papers(project_id: str) -> list[dict[str, Any]]:
    if not project_id:
        return []
    try:
        body = show_response(request("GET", f"/api/projects/{project_id}/papers", timeout=60), show_body=False)
        if isinstance(body, dict):
            return body.get("results", [])
    except requests.RequestException as exc:
        st.error(f"获取项目文献失败: {exc}")
    return []


def fetch_project_qas(project_id: str) -> list[dict[str, Any]]:
    if not project_id:
        return []
    try:
        body = show_response(request("GET", f"/api/projects/{project_id}/qas", timeout=60), show_body=False)
        if isinstance(body, dict):
            return body.get("results", [])
    except requests.RequestException as exc:
        st.error(f"获取项目问答失败: {exc}")
    return []


def delete_project_qas(project_id: str, qa_ids: list[str]) -> dict[str, Any] | None:
    if not project_id or not qa_ids:
        return None
    try:
        body = show_response(
            request(
                "POST",
                f"/api/projects/{project_id}/qas/delete",
                json={"qa_ids": qa_ids},
                timeout=60,
            ),
            show_body=False,
        )
        return body if isinstance(body, dict) else None
    except requests.RequestException as exc:
        st.error(f"删除项目问答失败: {exc}")
    return None


def delete_project_qa(project_id: str, qa_id: str) -> dict[str, Any] | None:
    if not project_id or not qa_id:
        return None
    try:
        body = show_response(
            request("DELETE", f"/api/projects/{project_id}/qas/{qa_id}", timeout=60),
            show_body=False,
        )
        return body if isinstance(body, dict) else None
    except requests.RequestException as exc:
        st.error(f"删除项目问答失败: {exc}")
    return None


def remove_project_papers(project_id: str, paper_ids: list[str]) -> dict[str, Any] | None:
    if not project_id or not paper_ids:
        return None
    try:
        body = show_response(
            request(
                "POST",
                f"/api/projects/{project_id}/papers/delete",
                json={"paper_ids": paper_ids},
                timeout=60,
            ),
            show_body=False,
        )
        return body if isinstance(body, dict) else None
    except requests.RequestException as exc:
        st.error(f"从项目移除文献失败: {exc}")
    return None


def render_project_content_manager() -> None:
    st.divider()
    st.subheader("项目内容")
    project_id = render_searchable_project_selector(prefix="project_content")
    if not project_id:
        return

    col_papers, col_qas = st.columns(2)
    if col_papers.button("查看项目文献", use_container_width=True):
        st.session_state["project_content_papers"] = fetch_project_papers(project_id)
        st.session_state["project_content_project_id"] = project_id
    if col_qas.button("查看历史问答", use_container_width=True):
        st.session_state["project_content_qas"] = fetch_project_qas(project_id)
        st.session_state["project_content_project_id"] = project_id

    if st.session_state.get("project_content_project_id") != project_id:
        st.session_state["project_content_papers"] = []
        st.session_state["project_content_qas"] = []

    papers = st.session_state.get("project_content_papers", [])
    if papers:
        st.markdown("### 已收录文献")
        rows = []
        for paper in papers:
            rows.append(
                {
                    "标题": paper.get("title", ""),
                    "来源": paper.get("source", ""),
                    "来源 ID": paper.get("source_id", ""),
                    "DOI": paper.get("doi", ""),
                    "发表日期": paper.get("published_date", ""),
                    "文献 ID": paper.get("id", ""),
                }
            )
        st.dataframe(rows, use_container_width=True, hide_index=True)

    if papers:
        st.markdown("### 移除项目文献")
        paper_remove_rows = []
        for index, paper in enumerate(papers):
            paper_remove_rows.append(
                {
                    "选择": False,
                    "序号": index,
                    "标题": paper.get("title", ""),
                    "来源": paper.get("source", ""),
                    "DOI": paper.get("doi", ""),
                    "文献 ID": paper.get("id", ""),
                }
            )
        edited_paper_remove_rows = st.data_editor(
            paper_remove_rows,
            use_container_width=True,
            hide_index=True,
            disabled=["序号", "标题", "来源", "DOI", "文献 ID"],
            column_config={
                "选择": st.column_config.CheckboxColumn("选择"),
                "标题": st.column_config.TextColumn("标题", width="large"),
                "DOI": st.column_config.TextColumn("DOI"),
                "文献 ID": st.column_config.TextColumn("文献 ID"),
            },
            key="project_content_remove_papers_editor",
        )
        selected_paper_ids = [papers[row["序号"]]["id"] for row in edited_paper_remove_rows if row.get("选择")]
        st.caption(f"已选择 {len(selected_paper_ids)} 篇文献")
        with st.expander("从当前项目移除文献", expanded=bool(selected_paper_ids)):
            st.warning("该操作只会解除文献与当前项目的绑定，不会删除文献库中的原始文献和向量。")
            confirm_remove_papers = st.checkbox("确认从当前项目移除选中文献", key="project_content_confirm_remove_papers")
            if st.button(
                "批量移除选中文献",
                disabled=not confirm_remove_papers or not selected_paper_ids,
                use_container_width=True,
            ):
                result = remove_project_papers(project_id, selected_paper_ids)
                if result:
                    st.success(f"已从项目移除 {result.get('removed', 0)} 篇文献")
                    st.session_state["project_content_papers"] = fetch_project_papers(project_id)
                    st.rerun()

    qas = st.session_state.get("project_content_qas", [])
    if qas:
        st.markdown("### 历史问答")
        qa_rows = []
        for index, qa in enumerate(qas):
            qa_rows.append(
                {
                    "选择": False,
                    "序号": index,
                    "问题": qa.get("question", ""),
                    "回答": qa.get("answer", ""),
                    "纳入总结": bool(qa.get("include_in_summary_context", True)),
                    "判定原因": qa.get("summary_context_reason") or "",
                    "创建时间": qa.get("created_at", ""),
                    "问答 ID": qa.get("id", ""),
                }
            )
        edited_rows = st.data_editor(
            qa_rows,
            use_container_width=True,
            hide_index=True,
            disabled=["序号", "问题", "回答", "纳入总结", "判定原因", "创建时间", "问答 ID"],
            column_config={
                "选择": st.column_config.CheckboxColumn("选择"),
                "问题": st.column_config.TextColumn("问题", width="large"),
                "回答": st.column_config.TextColumn("AI 回答", width="large"),
                "纳入总结": st.column_config.CheckboxColumn("纳入总结"),
                "问答 ID": st.column_config.TextColumn("问答 ID"),
            },
            key="project_content_qas_editor",
        )
        selected_qa_ids = [qas[row["序号"]]["id"] for row in edited_rows if row.get("选择")]
        st.caption(f"已选择 {len(selected_qa_ids)} 条问答")

        col_delete_one, col_delete_many = st.columns(2)
        confirm_delete_qas = st.checkbox("确认删除选中的历史问答", key="project_content_confirm_delete_qas")
        if col_delete_one.button(
            "删除第一条选中问答",
            disabled=not confirm_delete_qas or len(selected_qa_ids) != 1,
            use_container_width=True,
        ):
            result = delete_project_qa(project_id, selected_qa_ids[0])
            if result:
                st.success(f"已删除 {result.get('deleted', 0)} 条问答")
                st.session_state["project_content_qas"] = fetch_project_qas(project_id)
                st.rerun()
        if col_delete_many.button(
            "批量删除选中问答",
            disabled=not confirm_delete_qas or not selected_qa_ids,
            use_container_width=True,
        ):
            result = delete_project_qas(project_id, selected_qa_ids)
            if result:
                st.success(f"已删除 {result.get('deleted', 0)} 条问答")
                st.session_state["project_content_qas"] = fetch_project_qas(project_id)
                st.rerun()


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
    source = col4.selectbox("来源", ["", "pubmed", "arxiv", "semantic_scholar", "user_upload", "manual"])
    col5, col6, col7 = st.columns(3)
    journal = col5.text_input("期刊")
    citation_min = col6.number_input("最低引用数", min_value=0, value=None, step=1)
    citation_max = col7.number_input("最高引用数", min_value=0, value=None, step=1)
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
        if journal:
            params["journal"] = journal
        if citation_min is not None:
            params["citation_min"] = int(citation_min)
        if citation_max is not None:
            params["citation_max"] = int(citation_max)

        try:
            body = show_response(request("GET", "/api/search", params=params))
            if isinstance(body, dict):
                st.session_state["last_search_results"] = body.get("results", [])
                render_search_results(body)
        except requests.RequestException as exc:
            st.error(f"搜索请求失败: {exc}")

    with st.expander("查询改写调试"):
        rewrite_query = st.text_input("待改写查询", key="rewrite_query")
        if st.button("生成改写"):
            try:
                show_response(local_request("POST", api_url("/api/search/rewrite"), params={"q": rewrite_query}, timeout=30))
            except requests.RequestException as exc:
                st.error(f"查询改写失败: {exc}")


def render_search_results(body: dict[str, Any]) -> None:
    results = body.get("results") or []
    external_results = body.get("external_results") or []
    if not results and not external_results:
        st.info("没有检索到匹配文献")
        return

    st.caption(
        f"命中 {body.get('total', len(results))} 篇候选文献，返回 {len(results)} 篇；"
        f"外部补充 {body.get('external_total', len(external_results))} 篇；"
        f"缓存命中：{'是' if body.get('cache_hit') else '否'}"
    )
    rewritten = body.get("rewritten_queries") or []
    if rewritten:
        st.write("改写查询：", " / ".join(rewritten))
    external_stats = body.get("external_stats") or {}
    if external_stats:
        st.caption(
            "外部补充统计："
            f"需要补 {external_stats.get('needed', 0)}，"
            f"抓取候选 {external_stats.get('fetched', 0)}，"
            f"通过过滤 {external_stats.get('accepted', 0)}，"
            f"年份过滤 {external_stats.get('filtered_year', 0)}，"
            f"作者过滤 {external_stats.get('filtered_author', 0)}，"
            f"期刊过滤 {external_stats.get('filtered_journal', 0)}。"
        )

    rows = []
    for item in results:
        paper = item.get("paper", {})
        authors = ", ".join(author.get("name", "") for author in paper.get("authors", [])[:3])
        rows.append(
            {
                "分数": round(float(item.get("score", 0)), 4),
                "标题": paper.get("title", ""),
                "作者": authors,
                "年份": (paper.get("published_date") or "")[:4],
                "来源": paper.get("source", ""),
                "文献ID": paper.get("source_id", ""),
                "DOI": paper.get("doi", ""),
                "引用数": paper.get("citation_count", 0),
                "摘要片段": " ".join(item.get("highlights", [])[1:]) or (paper.get("abstract") or "")[:220],
            }
        )
    if rows:
        st.markdown("**本地数据库结果**")
        st.dataframe(rows, use_container_width=True, hide_index=True)

    if external_results:
        st.markdown("**在线检索补充结果**")
        external_rows = []
        for item in external_results:
            paper = item.get("paper", {})
            authors = ", ".join(author.get("name", "") for author in paper.get("authors", [])[:3])
            external_rows.append(
                {
                    "来源": item.get("source", paper.get("source", "")),
                    "标题": paper.get("title", ""),
                    "作者": authors,
                    "年份": (paper.get("published_date") or "")[:4],
                    "文献ID": paper.get("source_id", ""),
                    "DOI": paper.get("doi", ""),
                    "PDF": paper.get("pdf_url", ""),
                    "摘要": (paper.get("abstract") or "")[:260],
                }
            )
        st.dataframe(external_rows, use_container_width=True, hide_index=True)


def render_import() -> None:
    st.subheader("文献获取")
    external_tab, upload_tab, manual_tab = st.tabs(["在线检索", "本地资料上传", "手动录入"])

    with external_tab:
        render_external_import()

    with upload_tab:
        render_material_upload()

    with manual_tab:
        render_manual_material()


def render_external_import() -> None:
    query = st.text_input("导入查询", key="import_query")
    sources = st.multiselect("数据源", ["pubmed", "arxiv", "semantic_scholar"], default=["pubmed"])
    limit = st.slider("候选数量", 1, 100, 20, key="import_limit")

    if st.button("搜索文献", type="primary"):
        payload = {"query": query, "sources": sources, "limit": limit, "include_pdf": False}
        try:
            body = show_response(request("POST", "/api/papers/import/preview", json=payload, timeout=90))
            if isinstance(body, dict):
                st.session_state["import_candidates"] = body.get("candidates", [])
                rewrites = (body.get("stats") or {}).get("query_rewrites") or []
                if rewrites:
                    st.info(f"PubMed 已使用英文查询：{rewrites[-1]}")
        except requests.RequestException as exc:
            st.error(f"文献搜索失败: {exc}")

    candidates = st.session_state.get("import_candidates", [])
    if not candidates:
        return

    st.divider()
    st.subheader("检索结果筛选")
    sort_by = st.selectbox("排序", ["发布时间", "标题", "来源 ID"], key="import_sort_by")
    reverse_sort = st.checkbox("倒序", value=True, key="import_sort_desc")
    select_all = st.checkbox("全选当前结果", key="import_select_all")
    include_pdf = st.checkbox("自动获取全文", key="import_include_pdf_selected")
    bind_project_id = render_searchable_project_selector(prefix="import_bind", optional=True)
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
        doi = paper.get("doi")
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
                "doi": doi,
                "doi_url": doi_to_url(doi),
                "source": paper.get("source"),
                "source_id": paper.get("source_id"),
                "abstract": paper.get("abstract", "")[:500],
            }
        )

    edited_rows = st.data_editor(
        rows,
        use_container_width=True,
        hide_index=True,
        disabled=["index", "title", "authors", "published_date", "doi", "doi_url", "source", "source_id", "abstract"],
        column_config={
            "select": st.column_config.CheckboxColumn("入库"),
            "index": st.column_config.NumberColumn("序号"),
            "title": st.column_config.TextColumn("标题", width="large"),
            "authors": st.column_config.TextColumn("作者", width="medium"),
            "published_date": st.column_config.TextColumn("发布时间"),
            "doi": st.column_config.TextColumn("DOI"),
            "doi_url": st.column_config.LinkColumn("DOI链接"),
            "source": st.column_config.TextColumn("来源"),
            "source_id": st.column_config.TextColumn("来源 ID"),
            "abstract": st.column_config.TextColumn("摘要预览", width="large"),
        },
        key="import_candidates_editor",
    )
    selected = [sorted_candidates[row["index"]] for row in edited_rows if row.get("select")]
    st.caption(f"已选择 {len(selected)} / {len(sorted_candidates)} 篇")

    if st.button("导入选中文献", disabled=not selected, use_container_width=True):
        payload = {"papers": selected, "include_pdf": include_pdf, "project_id": bind_project_id or None}
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
            st.error(f"选中文献入库失败: {exc}")


def render_material_upload() -> None:
    st.caption("支持 PDF、DOCX 和 Markdown。未选择项目时，资料会进入个人资料库；未发表资料默认 private。")
    uploaded_files = st.file_uploader(
        "选择资料文件",
        type=["pdf", "docx", "md", "markdown"],
        accept_multiple_files=True,
    )
    uploaded_count = len(uploaded_files) if uploaded_files else 0
    if uploaded_count:
        st.caption(f"已选择 {uploaded_count} 个文件")

    project_id = render_project_selector("绑定项目，可选", "upload_project_selector")
    publication_status = st.selectbox(
        "发表状态",
        ["unpublished", "internal", "preprint", "published", "unknown"],
        key="upload_publication_status",
    )
    visibility = st.selectbox("可见性", ["private", "project", "public"], index=0, key="upload_visibility")
    title = st.text_input(
        "标题，可选；单文件上传时覆盖自动识别",
        key="upload_title",
        disabled=uploaded_count > 1,
    )
    abstract = st.text_area(
        "摘要，可选；单文件上传时覆盖模型生成摘要",
        key="upload_abstract",
        disabled=uploaded_count > 1,
    )
    if uploaded_count > 1:
        st.info("批量上传时不会应用标题和摘要覆盖，系统会分别识别每篇资料。")
    authors_json = st.text_area(
        "作者 JSON，可选",
        value="[]",
        help='例如：[{"name": "Alice"}, {"name": "Bob"}]',
        key="upload_authors_json",
    )

    if st.button("上传并入库", type="primary", disabled=not uploaded_files, use_container_width=True):
        data = {
            "publication_status": publication_status,
            "visibility": visibility,
            "authors_json": authors_json or "[]",
        }
        if project_id.strip():
            data["project_id"] = project_id.strip()
        if uploaded_count == 1 and title.strip():
            data["title"] = title.strip()
        if uploaded_count == 1 and abstract.strip():
            data["abstract"] = abstract.strip()

        try:
            with st.spinner("正在保存、解析、分块、向量化并写入知识库。"):
                if uploaded_count == 1:
                    uploaded_file = uploaded_files[0]
                    files = {
                        "file": (
                            uploaded_file.name,
                            uploaded_file.getvalue(),
                            uploaded_file.type or "application/octet-stream",
                        )
                    }
                    body = show_response(request("POST", "/api/papers/upload", data=data, files=files, timeout=1800))
                else:
                    files = [
                        (
                            "files",
                            (
                                uploaded_file.name,
                                uploaded_file.getvalue(),
                                uploaded_file.type or "application/octet-stream",
                            ),
                        )
                        for uploaded_file in uploaded_files
                    ]
                    body = show_response(
                        request("POST", "/api/papers/upload/batch", data=data, files=files, timeout=3600),
                    )
            if isinstance(body, dict):
                if uploaded_count == 1:
                    st.session_state["last_uploaded_paper_id"] = body.get("paper_id")
                else:
                    st.session_state["last_batch_upload_results"] = body.get("results", [])
                    st.metric("成功入库", body.get("succeeded", 0), help=f"总计 {body.get('total', 0)} 个文件")
                    if body.get("failed", 0):
                        st.warning(f"{body.get('failed', 0)} 个文件入库失败，请查看结果表。")
                    rows = [
                        {
                            "文件名": item.get("filename", ""),
                            "结果": "成功" if item.get("ok") else "失败",
                            "文献 ID": item.get("paper_id") or "",
                            "状态": item.get("status", ""),
                            "说明": item.get("message", ""),
                        }
                        for item in body.get("results", [])
                    ]
                    if rows:
                        st.dataframe(rows, use_container_width=True, hide_index=True)
                    with st.expander("原始 JSON"):
                        st.json(body)
        except requests.RequestException as exc:
            st.error(f"上传资料失败: {exc}")


def render_manual_material() -> None:
    st.caption("用于没有文件的内部资料、实验记录或未发表内容。标题和摘要必填。")
    title = st.text_input("标题", key="manual_title")
    abstract = st.text_area("摘要", key="manual_abstract")
    content = st.text_area("正文/笔记，可选；留空则使用摘要作为正文", key="manual_content")
    project_id = render_project_selector("绑定项目，可选", "manual_project_selector")
    publication_status = st.selectbox(
        "发表状态",
        ["unpublished", "internal", "preprint", "published", "unknown"],
        key="manual_publication_status",
    )
    visibility = st.selectbox("可见性", ["private", "project", "public"], index=0, key="manual_visibility")
    authors_json = st.text_area(
        "作者 JSON，可选",
        value="[]",
        help='例如：[{"name": "Alice"}]',
        key="manual_authors_json",
    )

    if st.button("创建手动记录", type="primary", use_container_width=True):
        try:
            authors = json.loads(authors_json or "[]")
        except ValueError:
            st.error("作者 JSON 格式不正确")
            return
        payload = {
            "title": title,
            "abstract": abstract,
            "content": content or None,
            "authors": authors,
            "project_id": project_id.strip() or None,
            "publication_status": publication_status,
            "visibility": visibility,
            "metadata": {},
        }
        try:
            with st.spinner("正在创建资料并写入向量库。"):
                show_response(request("POST", "/api/papers/manual", json=payload, timeout=900))
        except requests.RequestException as exc:
            st.error(f"创建手动记录失败: {exc}")


def render_projects() -> None:
    st.subheader("研究项目")
    with st.expander("创建项目时绑定文献", expanded=False):
        create_bind_papers = search_database_papers("create_project_bind")
        create_bind_paper_ids = render_paper_selection_table(create_bind_papers, "create_project_bind_editor")
        st.caption(f"已选择 {len(create_bind_paper_ids)} 篇文献用于新项目")

    with st.form("create_project"):
        name = st.text_input("项目名称")
        description = st.text_area("项目描述")
        submitted = st.form_submit_button("创建项目")
    if submitted:
        try:
            body = show_response(request("POST", "/api/projects", json={"name": name, "description": description or None}))
            if isinstance(body, dict):
                fetch_projects()
                if create_bind_paper_ids:
                    bind_result = bind_papers_to_project(body.get("id", ""), create_bind_paper_ids)
                    if bind_result:
                        st.success(
                            f"已为新项目绑定 {bind_result.get('added', 0)} 篇文献，"
                            f"{bind_result.get('already_linked', 0)} 篇已存在。"
                        )
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
        st.caption("管理已有研究项目")

    projects = st.session_state.get("projects", [])
    if projects:
        st.dataframe(projects, use_container_width=True)

    render_project_content_manager()

def render_project_summary_response(body: dict[str, Any]) -> None:
    markdown = str(body.get("markdown") or "").strip()
    st.markdown("### 阶段总结")
    st.caption(
        f"项目：{body.get('project_name', '')} | "
        f"文献数：{body.get('paper_count', 0)} | "
        f"问答记录数：{body.get('qa_count', 0)}"
    )
    if markdown:
        st.markdown(markdown)
    else:
        st.info("本次没有生成可展示的项目总结。")

    with st.expander("调试信息"):
        st.json(body)


def render_project_summary() -> None:
    st.subheader("阶段总结")
    project_id = render_searchable_project_selector(prefix="summary")
    if st.button("生成阶段总结", type="primary", disabled=not project_id, use_container_width=True):
        try:
            with st.spinner("正在基于项目文献和历史问答生成阶段性总结。"):
                body = show_response(request("POST", f"/api/projects/{project_id}/summary", timeout=1800), show_body=False)
            if isinstance(body, dict):
                render_project_summary_response(body)
        except requests.RequestException as exc:
            st.error(f"项目总结失败: {exc}")


def render_stage_summary() -> None:
    st.subheader("阶段性总结")
    project_id = render_searchable_project_selector(prefix="summary")
    summary_question = st.text_area(
        "本阶段总结问题",
        placeholder="例如：请总结当前项目已经形成的研究思路、可采用的方法、关键证据和下一步推进方向。",
        key="summary_question",
    )
    if st.button(
        "生成阶段性总结",
        type="primary",
        disabled=not project_id or not summary_question.strip(),
        use_container_width=True,
    ):
        try:
            with st.spinner("正在基于项目文献和高价值历史问答生成阶段性总结..."):
                body = show_response(
                    request(
                        "POST",
                        f"/api/projects/{project_id}/summary",
                        json={"question": summary_question.strip()},
                        timeout=1800,
                    ),
                    show_body=False,
                )
            if isinstance(body, dict):
                render_project_summary_response(body)
        except requests.RequestException as exc:
            st.error(f"项目总结失败: {exc}")


def render_qa_response(body: dict[str, Any]) -> None:
    answer = str(body.get("answer") or "").strip()
    citations = body.get("citations") or []

    st.divider()
    st.markdown("### 回答")
    if answer:
        st.markdown(answer)
    else:
        st.info("本次没有生成可展示的回答。")

    if citations:
        st.markdown("### 引用来源")
        rows = []
        for index, citation in enumerate(citations, start=1):
            rows.append(
                {
                    "序号": index,
                    "文献标题": citation.get("title", ""),
                    "位置": citation.get("locator") or "",
                    "文献 ID": citation.get("paper_id", ""),
                    "片段 ID": citation.get("chunk_id") or "",
                }
            )
        st.dataframe(rows, use_container_width=True, hide_index=True)

    with st.expander("调试信息"):
        st.json(body)


def render_qa() -> None:
    st.subheader("研究问答")
    project_id = render_searchable_project_selector(prefix="qa")
    question = st.text_area("问题", placeholder="例如：这个项目中的文献主要讨论了哪些研究方向？")

    if st.button("提交问题", type="primary", disabled=not project_id or not question.strip()):
        payload = {
            "question": question,
            "scope": "project",
            "project_id": project_id,
            "paper_id": None,
            "paper_ids": [],
            "session_id": None,
        }
        try:
            body = show_response(request("POST", "/api/qa", json=payload), show_body=False)
            if isinstance(body, dict):
                render_qa_response(body)
        except requests.RequestException as exc:
            st.error(f"问答请求失败: {exc}")


    st.divider()
    render_stage_summary()


def render_papers() -> None:
    st.subheader("我的文献库")
    with st.expander("检索我的文献", expanded=True):
        q = st.text_input("综合关键词", placeholder="标题、摘要、DOI、作者、来源 ID", key="paper_catalog_q")
        col_a, col_b, col_c = st.columns(3)
        title = col_a.text_input("标题包含", key="paper_catalog_title")
        doi = col_b.text_input("DOI 包含", key="paper_catalog_doi")
        author = col_c.text_input("作者包含", key="paper_catalog_author")
        col_d, col_e, col_f, col_g = st.columns(4)
        source = col_d.selectbox("来源", ["", "pubmed", "arxiv", "semantic_scholar", "user_upload", "manual"], key="paper_catalog_source")
        source_id = col_e.text_input("来源 ID", key="paper_catalog_source_id")
        year_from = col_f.text_input("起始年份", key="paper_catalog_year_from")
        year_to = col_g.text_input("结束年份", key="paper_catalog_year_to")
        limit = st.slider("查询数量", 1, 100, 20, key="paper_catalog_limit")

        if st.button("检索文献", type="primary"):
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
                st.error(f"检索文献失败: {exc}")

        results = st.session_state.get("paper_catalog_results", [])
        if results:
            selected_paper_ids = render_paper_selection_table(results, "paper_catalog_bind_editor")
            st.caption(f"已选择 {len(selected_paper_ids)} 篇文献")

            with st.expander("加入研究项目", expanded=bool(selected_paper_ids)):
                target_project_id = render_searchable_project_selector(prefix="paper_bind")
                if st.button(
                    "将所选文献加入研究项目",
                    type="primary",
                    disabled=not target_project_id or not selected_paper_ids,
                    use_container_width=True,
                ):
                    bind_result = bind_papers_to_project(target_project_id, selected_paper_ids)
                    if bind_result:
                        st.success(
                            f"新增绑定 {bind_result.get('added', 0)} 篇，"
                            f"{bind_result.get('already_linked', 0)} 篇已在项目中，"
                            f"{bind_result.get('skipped_inaccessible', 0)} 篇不可访问或不存在。"
                        )

            with st.expander("删除所选文献", expanded=False):
                st.warning("删除会清理数据库中文献资料、项目关联和 Milvus 向量。该操作不可撤销。")
                confirm_batch_delete = st.checkbox("确认删除已勾选的文献", key="paper_catalog_delete_confirm")
                delete_selected_disabled = (
                    not st.session_state.access_token
                    or not selected_paper_ids
                    or not confirm_batch_delete
                )
                if st.button(
                    "删除已勾选文献",
                    type="primary",
                    disabled=delete_selected_disabled,
                    use_container_width=True,
                ):
                    deleted_count, failures = delete_selected_papers(selected_paper_ids)
                    if deleted_count:
                        st.success(f"已删除 {deleted_count} 篇文献。")
                        deleted_ids = set(selected_paper_ids)
                        st.session_state["paper_catalog_results"] = [
                            paper for paper in results if str(paper.get("id", "")) not in deleted_ids
                        ]
                    if failures:
                        st.error(f"{len(failures)} 篇文献删除失败。")
                        st.dataframe(failures, use_container_width=True, hide_index=True)

    st.subheader("文献详情")
    paper_id = st.text_input("系统文献 ID", help="先在上方检索我的文献，再复制 system_id。DOI 保存在 papers.doi 中，不作为当前接口路径参数。", key="paper_detail_id")
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
    st.subheader("处理进度")
    task_id = st.text_input("处理 ID")
    if st.button("查询进度"):
        try:
            show_response(request("GET", f"/api/tasks/{task_id}"))
        except requests.RequestException as exc:
            st.error(f"进度查询失败: {exc}")


def main() -> None:
    st.set_page_config(page_title="LitSage", layout="wide")
    init_state()
    render_sidebar()

    st.title("LitSage 文献智能搜索与总结系统")
    st.caption("Streamlit 前端控制台，用于调试和演示 FastAPI Agent 后端能力。")

    tabs = st.tabs(["文献获取", "研究项目", "研究问答", "我的文献库", "处理进度"])
    with tabs[0]:
        render_import()
    with tabs[1]:
        render_projects()
    with tabs[2]:
        render_qa()
    with tabs[3]:
        render_papers()
    with tabs[4]:
        render_tasks()


if __name__ == "__main__":
    main()
