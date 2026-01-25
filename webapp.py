import uuid
from typing import List

from fastapi import FastAPI, HTTPException, Request, Response, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
from telegram import Bot

from config import settings
from storage import Storage


storage = Storage(settings.DB_PATH)
bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)

app = FastAPI(title="TG Bot Dashboard")

# Simple in-memory session store
SESSIONS = set()

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # Skip auth for login page and static assets if any (none here)
    if request.url.path in ["/login", "/docs", "/openapi.json"]:
        return await call_next(request)
    
    # Check auth for API and Root
    if request.url.path.startswith("/api/") or request.url.path == "/":
        session_id = request.cookies.get("session_id")
        if not session_id or session_id not in SESSIONS:
            if request.url.path.startswith("/api/"):
                return Response(content="Unauthorized", status_code=401)
            else:
                return RedirectResponse(url="/login")
    
    response = await call_next(request)
    return response

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    html = """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>登录 - Telegram Bot 管理后台</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body { background-color: #f8f9fa; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
            .login-card { width: 100%; max-width: 400px; padding: 2rem; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); background: #fff; }
            .btn-primary { width: 100%; }
        </style>
    </head>
    <body>
        <div class="login-card">
            <h4 class="text-center mb-4">Telegram Bot 管理后台</h4>
            <form action="/login" method="post">
                <div class="mb-3">
                    <label class="form-label">账号</label>
                    <input type="text" name="username" class="form-control" required autofocus>
                </div>
                <div class="mb-3">
                    <label class="form-label">密码</label>
                    <input type="password" name="password" class="form-control" required>
                </div>
                <button type="submit" class="btn btn-primary py-2">登 录</button>
            </form>
        </div>
    </body>
    </html>
    """
    return html

@app.post("/login")
async def login(username: str = Form(...), password: str = Form(...)):
    if username == settings.DASHBOARD_USERNAME and password == settings.DASHBOARD_PASSWORD:
        session_id = str(uuid.uuid4())
        SESSIONS.add(session_id)
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(key="session_id", value=session_id, httponly=True, max_age=86400)
        return response
    
    # Return login page with error
    html = """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>登录失败</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body class="d-flex align-items-center justify-content-center vh-100 bg-light">
        <div class="text-center">
            <div class="alert alert-danger">账号或密码错误</div>
            <a href="/login" class="btn btn-secondary">返回重试</a>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html, status_code=401)

@app.get("/logout")
async def logout(request: Request):
    session_id = request.cookies.get("session_id")
    if session_id and session_id in SESSIONS:
        SESSIONS.remove(session_id)
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("session_id")
    return response

class Group(BaseModel):
    chat_id: int
    title: str
    activated_at: str = Field(alias="activatedAt")

    class Config:
        populate_by_name = True


class DeleteGroupsRequest(BaseModel):
    group_ids: List[int] = Field(alias="groupIds")


class BroadcastRequest(BaseModel):
    group_ids: List[int] = Field(alias="groupIds")
    text: str


class Tag(BaseModel):
    id: int
    name: str
    member_count: int = Field(alias="memberCount")


class CreateTagRequest(BaseModel):
    name: str


class AddToTagRequest(BaseModel):
    tag_id: int = Field(alias="tagId")
    group_ids: List[int] = Field(alias="groupIds")


class DeleteTagRequest(BaseModel):
    tag_id: int = Field(alias="tagId")


@app.get("/api/groups", response_model=List[Group])
async def list_groups() -> List[Group]:
    groups = storage.get_all_active_groups()
    return [Group(chat_id=g[0], title=g[1], activatedAt=g[2]) for g in groups]


@app.post("/api/groups/delete")
async def delete_groups(payload: DeleteGroupsRequest):
    if not payload.group_ids:
        raise HTTPException(status_code=400, detail="group_ids is empty")
    deleted = 0
    for gid in payload.group_ids:
        try:
            await bot.leave_chat(gid)
        except Exception:
            pass
        storage.deactivate_group(gid)
        deleted += 1
    return {"deleted": deleted}


@app.post("/api/broadcast")
async def broadcast(payload: BroadcastRequest):
    if not payload.group_ids:
        raise HTTPException(status_code=400, detail="group_ids is empty")
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is empty")

    success = 0
    failure = 0
    for gid in payload.group_ids:
        try:
            await bot.send_message(chat_id=gid, text=text)
            success += 1
        except Exception:
            failure += 1

    return {"total": len(payload.group_ids), "success": success, "failure": failure}


@app.get("/api/tags", response_model=List[Tag])
async def list_tags():
    tags = storage.get_all_tags()
    return [Tag(id=t[0], name=t[1], memberCount=t[2]) for t in tags]


@app.post("/api/tags/create")
async def create_tag(payload: CreateTagRequest):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is empty")
    tag_id = storage.create_tag(name)
    return {"id": tag_id, "name": name}


@app.post("/api/tags/delete")
async def delete_tag(payload: DeleteTagRequest):
    storage.delete_tag(payload.tag_id)
    return {"success": True}


@app.post("/api/tags/members/add")
async def add_to_tag(payload: AddToTagRequest):
    if not payload.group_ids:
        raise HTTPException(status_code=400, detail="groupIds is empty")
    storage.add_members_to_tag(payload.tag_id, payload.group_ids)
    return {"success": True}


@app.get("/api/tags/{tag_id}/members")
async def get_tag_members(tag_id: int):
    members = storage.get_tag_members(tag_id)
    return {"groupIds": members}


@app.get("/", response_class=HTMLResponse)
async def dashboard_page():
    html = """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Telegram Bot 管理后台</title>
      <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
      <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.0/font/bootstrap-icons.css">
      <style>
        body { background-color: #f8f9fa; }
        .card { box-shadow: 0 4px 6px rgba(0,0,0,0.1); border: none; margin-bottom: 24px; }
        .card-header { background-color: #fff; border-bottom: 1px solid #eee; padding: 16px 20px; font-weight: 600; }
        .table th { font-weight: 600; color: #555; }
        .status-badge { font-size: 0.85em; }
        #broadcast-text { resize: vertical; min-height: 120px; }
        .btn-group-sm > .btn { border-radius: 4px; }
        .toolbar { display: flex; gap: 8px; align-items: center; }
        .spinner-border-sm { margin-right: 5px; }
      </style>
    </head>
    <body>
      <nav class="navbar navbar-expand-lg navbar-dark bg-primary mb-4 shadow-sm">
        <div class="container">
          <a class="navbar-brand" href="#"><i class="bi bi-robot me-2"></i>Telegram Bot 管理后台</a>
          <a href="/logout" class="btn btn-outline-light btn-sm"><i class="bi bi-box-arrow-right me-1"></i>退出登录</a>
        </div>
      </nav>

      <div class="container">
        <div class="row">
          <!-- 左侧：群组列表 -->
          <div class="col-lg-8">
            <div class="card">
              <div class="card-header d-flex justify-content-between align-items-center">
                <span><i class="bi bi-people me-2"></i>群组列表</span>
                <span class="badge bg-secondary" id="group-count-badge">加载中...</span>
              </div>
              <div class="card-body p-0">
                <div class="p-3 border-bottom bg-light d-flex justify-content-between align-items-center">
                  <div class="toolbar">
                    <div class="form-check ms-2">
                      <input class="form-check-input" type="checkbox" id="select-all" onclick="toggleAll()">
                      <label class="form-check-label user-select-none" for="select-all">全选</label>
                    </div>
                  </div>
                  <div class="toolbar">
                    <button class="btn btn-outline-primary btn-sm" onclick="showAddToTagModal()">
                      <i class="bi bi-folder-plus me-1"></i>添加到分组
                    </button>
                    <button class="btn btn-outline-danger btn-sm" onclick="deleteSelected()">
                      <i class="bi bi-trash me-1"></i>退出并移除
                    </button>
                  </div>
                </div>
                <div class="table-responsive" style="max-height: 600px; overflow-y: auto;">
                  <table class="table table-hover align-middle mb-0" id="groups-table">
                    <thead class="table-light sticky-top">
                      <tr>
                        <th style="width: 50px;"></th>
                        <th>Chat ID</th>
                        <th>群组名称</th>
                        <th>激活时间</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr><td colspan="4" class="text-center py-4 text-muted">加载中...</td></tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </div>

          <!-- 右侧：广播控制 -->
          <div class="col-lg-4">
            <!-- 分组管理卡片 -->
            <div class="card shadow-sm mb-3">
              <div class="card-header bg-white d-flex justify-content-between align-items-center">
                <span class="fw-bold text-primary"><i class="bi bi-tags me-2"></i>我的分组</span>
                <button class="btn btn-sm btn-link text-decoration-none p-0" onclick="showCreateTagModal()">
                  <i class="bi bi-plus-lg"></i> 新建
                </button>
              </div>
              <div class="card-body p-2">
                <div id="tags-container" class="d-flex flex-wrap gap-2">
                  <span class="text-muted small p-2">加载中...</span>
                </div>
              </div>
            </div>

            <div class="card shadow-sm sticky-top" style="top: 20px; z-index: 100;">
              <div class="card-header bg-primary text-white">
                <i class="bi bi-megaphone me-2"></i>消息广播
              </div>
              <div class="card-body">
                <div class="alert alert-info py-2 small">
                  <i class="bi bi-info-circle me-1"></i> 将对左侧<b>勾选的群组</b>发送消息
                </div>
                <div class="mb-3">
                  <label for="broadcast-text" class="form-label fw-bold">广播内容</label>
                  <textarea class="form-control" id="broadcast-text" placeholder="在此输入要发送的文案..."></textarea>
                </div>
                <div class="d-grid gap-2">
                  <button class="btn btn-primary" onclick="broadcastToSelected()" id="btn-broadcast">
                    <i class="bi bi-send me-1"></i> 发送广播
                  </button>
                </div>
                <div id="broadcast-result" class="mt-3"></div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Toast 提示容器 -->
      <div class="toast-container position-fixed bottom-0 end-0 p-3">
        <div id="liveToast" class="toast" role="alert" aria-live="assertive" aria-atomic="true">
          <div class="toast-header">
            <strong class="me-auto" id="toast-title">提示</strong>
            <button type="button" class="btn-close" data-bs-dismiss="toast" aria-label="Close"></button>
          </div>
          <div class="toast-body" id="toast-body">
            Hello, world!
          </div>
        </div>
      </div>

      <!-- Add to Tag Modal -->
      <div class="modal fade" id="addToTagModal" tabindex="-1">
        <div class="modal-dialog">
          <div class="modal-content">
            <div class="modal-header">
              <h5 class="modal-title">添加到分组</h5>
              <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
              <div class="mb-3">
                <label class="form-label">选择现有分组</label>
                <select class="form-select" id="tag-select">
                  <option value="">-- 请选择 --</option>
                </select>
              </div>
              <div class="text-center text-muted my-2">- 或 -</div>
              <div class="mb-3">
                <label class="form-label">创建新分组并添加</label>
                <div class="input-group">
                  <input type="text" class="form-control" id="new-tag-name" placeholder="输入分组名称">
                  <button class="btn btn-outline-primary" onclick="createTagInModal()">创建</button>
                </div>
              </div>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">取消</button>
              <button type="button" class="btn btn-primary" onclick="confirmAddToTag()">确定添加</button>
            </div>
          </div>
        </div>
      </div>

      <!-- Create Tag Modal (Simple) -->
      <div class="modal fade" id="createTagModal" tabindex="-1">
        <div class="modal-dialog">
          <div class="modal-content">
            <div class="modal-header">
              <h5 class="modal-title">新建分组</h5>
              <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
              <input type="text" class="form-control" id="simple-new-tag-name" placeholder="输入分组名称">
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-primary" onclick="createTagSimple()">创建</button>
            </div>
          </div>
        </div>
      </div>

      <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
      <script>
        const toastEl = document.getElementById('liveToast');
        const toast = new bootstrap.Toast(toastEl);
        const addToTagModal = new bootstrap.Modal(document.getElementById('addToTagModal'));
        const createTagModal = new bootstrap.Modal(document.getElementById('createTagModal'));

        let allGroups = [];
        let currentTagFilter = null; // null = all

        function showToast(title, message, type='info') {
          document.getElementById('toast-title').textContent = title;
          document.getElementById('toast-body').textContent = message;
          const header = toastEl.querySelector('.toast-header');
          header.className = 'toast-header';
          if (type === 'error') header.classList.add('bg-danger', 'text-white');
          else if (type === 'success') header.classList.add('bg-success', 'text-white');
          toast.show();
        }

        async function loadGroups() {
          try {
            const res = await fetch("/api/groups");
            allGroups = await res.json();
            await renderGroupsTable();
          } catch (err) {
            showToast('错误', '加载群组失败: ' + err, 'error');
          }
        }

        async function renderGroupsTable() {
            const tbody = document.querySelector("#groups-table tbody");
            tbody.innerHTML = "";
            
            let displayGroups = allGroups;
            let filterText = "全部";

            if (currentTagFilter) {
                try {
                    const res = await fetch(`/api/tags/${currentTagFilter}/members`);
                    const data = await res.json();
                    const memberIds = new Set(data.groupIds);
                    displayGroups = allGroups.filter(g => memberIds.has(g.chat_id));
                    
                    // Find tag name
                    const tagBtn = document.querySelector(`#tags-container button[data-id='${currentTagFilter}']`);
                    if (tagBtn) filterText = tagBtn.textContent.split(' ')[0];
                } catch(err) {
                    showToast('错误', '加载分组成员失败', 'error');
                }
            }

            const badge = document.getElementById("group-count-badge");
            badge.textContent = `${filterText} (${displayGroups.length})`;
            badge.className = currentTagFilter ? "badge bg-info" : "badge bg-secondary";

            if (displayGroups.length === 0) {
              tbody.innerHTML = '<tr><td colspan="4" class="text-center py-4 text-muted">暂无数据</td></tr>';
            } else {
              for (const g of displayGroups) {
                const tr = document.createElement("tr");
                tr.innerHTML = `
                  <td class="text-center"><input type="checkbox" class="form-check-input group-checkbox" data-id="${g.chat_id}"></td>
                  <td><small class="font-monospace text-muted">${g.chat_id}</small></td>
                  <td class="fw-bold text-truncate" style="max-width: 200px;" title="${g.title}">${g.title}</td>
                  <td><small class="text-muted">${g.activatedAt.replace('T', ' ').substring(0, 16)}</small></td>
                `;
                tr.onclick = (e) => {
                   if (e.target.type !== 'checkbox') {
                     const cb = tr.querySelector('.group-checkbox');
                     cb.checked = !cb.checked;
                     updateSelectAllState();
                   }
                };
                tbody.appendChild(tr);
              }
            }
            updateSelectAllState();
        }

        async function loadTags() {
            try {
                const res = await fetch("/api/tags");
                const tags = await res.json();
                const container = document.getElementById("tags-container");
                container.innerHTML = "";
                
                // Add "All" button
                const allBtn = document.createElement("button");
                allBtn.className = currentTagFilter === null ? "btn btn-primary btn-sm" : "btn btn-outline-secondary btn-sm";
                allBtn.textContent = "全部";
                allBtn.onclick = () => { currentTagFilter = null; loadTags(); renderGroupsTable(); };
                container.appendChild(allBtn);

                if (tags.length > 0) {
                    tags.forEach(tag => {
                        const badge = document.createElement("button");
                        badge.className = currentTagFilter === tag.id ? "btn btn-primary btn-sm" : "btn btn-outline-secondary btn-sm";
                        badge.setAttribute("data-id", tag.id);
                        badge.innerHTML = `${tag.name} <span class="badge text-bg-light ms-1">${tag.memberCount}</span>`;
                        badge.onclick = () => { currentTagFilter = tag.id; loadTags(); renderGroupsTable(); };
                        container.appendChild(badge);
                    });
                }
            } catch (err) {
                console.error(err);
            }
        }

        function getSelectedIds() {
          const boxes = document.querySelectorAll(".group-checkbox:checked");
          return Array.from(boxes).map(b => parseInt(b.getAttribute("data-id")));
        }

        function toggleAll() {
          const checked = document.getElementById("select-all").checked;
          document.querySelectorAll(".group-checkbox").forEach(b => b.checked = checked);
        }
        
        function updateSelectAllState() {
           const all = document.querySelectorAll(".group-checkbox");
           const checked = document.querySelectorAll(".group-checkbox:checked");
           const selectAllCb = document.getElementById("select-all");
           if (all.length > 0 && all.length === checked.length) {
               selectAllCb.checked = true;
               selectAllCb.indeterminate = false;
           } else if (checked.length > 0) {
               selectAllCb.checked = false;
               selectAllCb.indeterminate = true;
           } else {
               selectAllCb.checked = false;
               selectAllCb.indeterminate = false;
           }
        }

        async function deleteSelected() {
          const ids = getSelectedIds();
          if (!ids.length) {
            showToast('提示', '请先勾选要删除的群组', 'info');
            return;
          }
          if (!confirm(`确认删除选中的 ${ids.length} 个群组？Bot 将自动退出这些群组。`)) {
            return;
          }
          try {
            const res = await fetch("/api/groups/delete", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ groupIds: ids })
            });
            const data = await res.json();
            showToast('成功', `已删除 ${data.deleted} 个群组`, 'success');
            await loadGroups();
            await loadTags(); // Refresh tags as counts might change (though backend might not update counts automatically unless triggered)
          } catch (err) {
            showToast('错误', '删除失败: ' + err, 'error');
          }
        }

        async function broadcastToSelected() {
          const ids = getSelectedIds();
          const textInput = document.getElementById("broadcast-text");
          const text = textInput.value;
          const btn = document.getElementById("btn-broadcast");
          const resultDiv = document.getElementById("broadcast-result");

          if (!ids.length) {
            showToast('提示', '请先在左侧勾选要广播的群组', 'info');
            return;
          }
          if (!text.trim()) {
            showToast('提示', '请输入要广播的文案', 'info');
            textInput.focus();
            return;
          }

          btn.disabled = true;
          btn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> 发送中...';
          resultDiv.innerHTML = '';

          try {
            const res = await fetch("/api/broadcast", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ groupIds: ids, text })
            });
            const data = await res.json();
            
            resultDiv.innerHTML = `
              <div class="alert ${data.failure > 0 ? 'alert-warning' : 'alert-success'} mb-0">
                <h6 class="alert-heading mb-1">${data.failure > 0 ? '广播完成 (有失败)' : '广播成功'}</h6>
                <small>总数: <b>${data.total}</b> | 成功: <b class="text-success">${data.success}</b> | 失败: <b class="text-danger">${data.failure}</b></small>
              </div>
            `;
            if (data.failure === 0) {
                textInput.value = ''; 
            }
          } catch (err) {
            showToast('错误', '广播请求失败: ' + err, 'error');
          } finally {
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-send me-1"></i> 发送广播';
          }
        }

        async function showAddToTagModal() {
            const ids = getSelectedIds();
            if (!ids.length) {
                showToast('提示', '请先勾选要添加到分组的群组', 'info');
                return;
            }
            
            const select = document.getElementById('tag-select');
            select.innerHTML = '<option value="">-- 请选择 --</option>';
            try {
                const res = await fetch("/api/tags");
                const tags = await res.json();
                tags.forEach(t => {
                    const opt = document.createElement('option');
                    opt.value = t.id;
                    opt.textContent = `${t.name} (${t.memberCount})`;
                    select.appendChild(opt);
                });
            } catch(e) {
                showToast('错误', '加载分组失败', 'error');
                return;
            }
            
            document.getElementById('new-tag-name').value = '';
            addToTagModal.show();
        }

        async function createTagInModal() {
            const nameInput = document.getElementById('new-tag-name');
            const name = nameInput.value.trim();
            if(!name) return;
            
            try {
                const res = await fetch("/api/tags/create", {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({name})
                });
                if(res.ok) {
                    const newTag = await res.json();
                    const select = document.getElementById('tag-select');
                    const opt = document.createElement('option');
                    opt.value = newTag.id;
                    opt.textContent = `${newTag.name} (0)`;
                    opt.selected = true;
                    select.appendChild(opt);
                    
                    nameInput.value = '';
                    loadTags();
                }
            } catch(e) {
                showToast('错误', '创建分组失败', 'error');
            }
        }

        async function confirmAddToTag() {
            const select = document.getElementById('tag-select');
            const tagId = select.value;
            if (!tagId) {
                showToast('提示', '请选择一个分组', 'warning');
                return;
            }
            
            const groupIds = getSelectedIds();
            try {
                const res = await fetch("/api/tags/members/add", {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({tagId: parseInt(tagId), groupIds})
                });
                
                if (res.ok) {
                    showToast('成功', '已添加到分组', 'success');
                    addToTagModal.hide();
                    loadTags();
                    document.querySelectorAll(".group-checkbox").forEach(b => b.checked = false);
                    updateSelectAllState();
                } else {
                     showToast('错误', '添加失败', 'error');
                }
            } catch(e) {
                showToast('错误', '请求失败', 'error');
            }
        }

        function showCreateTagModal() {
            document.getElementById('simple-new-tag-name').value = '';
            createTagModal.show();
        }

        async function createTagSimple() {
            const name = document.getElementById('simple-new-tag-name').value.trim();
            if(!name) return;
             try {
                const res = await fetch("/api/tags/create", {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({name})
                });
                if(res.ok) {
                    createTagModal.hide();
                    loadTags();
                    showToast('成功', '创建分组成功', 'success');
                }
            } catch(e) {
                showToast('错误', '创建失败', 'error');
            }
        }

        document.addEventListener('change', function(e) {
            if (e.target.classList.contains('group-checkbox')) {
                updateSelectAllState();
            }
        });

        loadGroups();
        loadTags();
      </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

