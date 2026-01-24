from typing import List

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from telegram import Bot

from config import settings
from storage import Storage


storage = Storage(settings.DB_PATH)
bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)

app = FastAPI(title="TG Bot Dashboard")


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
        </div>
      </nav>

      <div class="container">
        <div class="row">
          <!-- 左侧：群组列表 -->
          <div class="col-lg-8">
            <div class="card">
              <div class="card-header d-flex justify-content-between align-items-center">
                <span><i class="bi bi-people me-2"></i>已激活群组列表</span>
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
                    <button class="btn btn-outline-danger btn-sm" onclick="deleteSelected()">
                      <i class="bi bi-trash me-1"></i>退出并移除选中
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
            <div class="card sticky-top" style="top: 20px; z-index: 100;">
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

      <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
      <script>
        const toastEl = document.getElementById('liveToast');
        const toast = new bootstrap.Toast(toastEl);

        function showToast(title, message, type='info') {
          document.getElementById('toast-title').textContent = title;
          document.getElementById('toast-body').textContent = message;
          const header = toastEl.querySelector('.toast-header');
          
          // Reset classes
          header.className = 'toast-header';
          if (type === 'error') header.classList.add('bg-danger', 'text-white');
          else if (type === 'success') header.classList.add('bg-success', 'text-white');
          
          toast.show();
        }

        async function loadGroups() {
          try {
            const res = await fetch("/api/groups");
            const data = await res.json();
            const tbody = document.querySelector("#groups-table tbody");
            tbody.innerHTML = "";
            
            if (data.length === 0) {
              tbody.innerHTML = '<tr><td colspan="4" class="text-center py-4 text-muted">暂无已激活群组</td></tr>';
            } else {
              for (const g of data) {
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
            document.getElementById("group-count-badge").textContent = data.length + " 个";
            updateSelectAllState();
          } catch (err) {
            showToast('错误', '加载群组失败: ' + err, 'error');
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
                textInput.value = ''; // Clear input on full success
            }
          } catch (err) {
            showToast('错误', '广播请求失败: ' + err, 'error');
          } finally {
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-send me-1"></i> 发送广播';
          }
        }

        // Add event listener to checkboxes for updating "Select All" state
        document.addEventListener('change', function(e) {
            if (e.target.classList.contains('group-checkbox')) {
                updateSelectAllState();
            }
        });

        loadGroups();
      </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

