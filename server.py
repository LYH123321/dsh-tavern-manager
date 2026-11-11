import os
import sys
import json
import re
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse

DATA_DIR = "/sdcard/Download/st"
CONFIG_FILE = os.path.join(DATA_DIR, "tavern_config.json")
DEFAULT_MAX_ENTRIES = 4
DEFAULT_MAX_CHARS = 2500

class TavernManager:
    def __init__(self, data_dir=DATA_DIR):
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        self.load_config()

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    self.config = json.load(f)
            except Exception:
                self.config = {"active_books": [], "max_entries": DEFAULT_MAX_ENTRIES, "max_chars": DEFAULT_MAX_CHARS, "regex_presets": []}
        else:
            self.config = {"active_books": [], "max_entries": DEFAULT_MAX_ENTRIES, "max_chars": DEFAULT_MAX_CHARS, "regex_presets": []}
            self.save_config()

    def save_config(self):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)

    def list_books(self):
        books = []
        for root, _, files in os.walk(self.data_dir):
            for file in files:
                if file.endswith(".json") and file != "tavern_config.json":
                    p = os.path.join(root, file)
                    books.append({"path": p, "name": file, "active": p in self.config.get("active_books", [])})
        return books

    def read_book(self, path):
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_book(self, path, data):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def auto_import(self, query_text):
        """
        基于用户输入或上下文，代码级扫描匹配世界书条目。
        严格控额：先常驻、后关键词，硬锁 max_entries 和 max_chars，避免撑爆网关。
        """
        active_books = self.config.get("active_books", [])
        if not active_books:
            # 默认选用扫到的第一本
            all_b = self.list_books()
            if all_b:
                active_books = [all_b[0]["path"]]

        matched_entries = []
        current_chars = 0
        max_entries = self.config.get("max_entries", DEFAULT_MAX_ENTRIES)
        max_chars = self.config.get("max_chars", DEFAULT_MAX_CHARS)

        # 1. 扫描所有激活的书籍
        all_entries = []
        for b_path in active_books:
            data = self.read_book(b_path)
            if not data:
                continue
            entries = data.get("entries", {})
            if isinstance(entries, dict):
                entries = list(entries.values())
            for e in entries:
                if not e.get("enabled", True):
                    continue
                all_entries.append(e)

        # 2. 先收集常驻条目（constant）
        for e in all_entries:
            if e.get("constant", False):
                content = e.get("content", "").strip()
                if content and current_chars + len(content) <= max_chars:
                    matched_entries.append({"title": e.get("comment", "常驻设定"), "content": content, "type": "constant"})
                    current_chars += len(content)
                    if len(matched_entries) >= max_entries:
                        break

        # 3. 关键词匹配动态条目
        if len(matched_entries) < max_entries and query_text:
            query_lower = query_text.lower()
            for e in all_entries:
                if e.get("constant", False):
                    continue
                keys = e.get("key", [])
                if isinstance(keys, str):
                    keys = [k.strip() for k in keys.split(",") if k.strip()]
                
                # 判断是否命中任一关键词
                hit = False
                for k in keys:
                    if k.lower() in query_lower:
                        hit = True
                        break
                
                if hit:
                    content = e.get("content", "").strip()
                    if content and current_chars + len(content) <= max_chars:
                        matched_entries.append({"title": e.get("comment", "触发设定"), "content": content, "type": "selective"})
                        current_chars += len(content)
                        if len(matched_entries) >= max_entries:
                            break

        return {
            "total_matched": len(matched_entries),
            "total_chars": current_chars,
            "entries": matched_entries,
            "context_prompt": "\n".join([f"【{e['title']}】\n{e['content']}" for e in matched_entries])
        }

    def apply_regex(self, text):
        """应用预设正则处理文本"""
        res = text
        for p in self.config.get("regex_presets", []):
            if not p.get("enabled", True):
                continue
            pat = p.get("pattern", "")
            sub = p.get("replacement", "")
            if pat:
                try:
                    res = re.sub(pat, sub, res)
                except Exception:
                    pass
        return res

HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>酒馆世界书与自导入工作台</title>
<style>
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; padding: 15px; background: #121212; color: #e0e0e0; }
h1, h2, h3 { color: #4dabf7; margin-top: 0; }
.card { background: #1e1e1e; border-radius: 8px; padding: 15px; margin-bottom: 15px; box-shadow: 0 2px 8px rgba(0,0,0,0.5); }
.btn { background: #1971c2; color: white; border: none; padding: 8px 14px; border-radius: 4px; cursor: pointer; font-size: 14px; }
.btn-save { background: #2f9e44; }
.btn-del { background: #e03131; }
input, textarea, select { width: 100%; background: #2b2b2b; color: white; border: 1px solid #444; border-radius: 4px; padding: 8px; box-sizing: border-box; margin-bottom: 10px; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 12px; background: #343a40; margin-right: 5px; }
.entry-item { background: #252525; border-left: 4px solid #1971c2; padding: 10px; margin-bottom: 10px; border-radius: 4px; }
.flex-row { display: flex; gap: 10px; align-items: center; }
</style>
</head>
<body>
<h1>📖 SillyTavern 自导入 & 世界书工作台</h1>

<div class="card">
  <h2>⚙️ 自导入预算硬锁（防网关超限）</h2>
  <div class="flex-row">
    <div style="flex:1">
      <label>单轮最多导入条目数：</label>
      <input type="number" id="max_entries" value="4">
    </div>
    <div style="flex:1">
      <label>最大字符数硬上限：</label>
      <input type="number" id="max_chars" value="2500">
    </div>
  </div>
  <button class="btn btn-save" onclick="saveSettings()">保存自导入规则</button>
</div>

<div class="card">
  <h2>🔍 实时自导入测试（输入你的对话内容）</h2>
  <textarea id="test_input" placeholder="输入一句话测试是否触发世界书，例如：'我想打听一下魔王城或者工会的事情'"></textarea>
  <button class="btn" onclick="testAutoImport()">运行关键词匹配</button>
  <div id="test_result" style="margin-top:10px; white-space:pre-wrap; background:#181818; padding:10px; border-radius:4px; font-size:13px; color:#a5d8ff;"></div>
</div>

<div class="card">
  <h2>📚 本地世界书列表 (/sdcard/Download/st)</h2>
  <div id="books_list">加载中...</div>
</div>

<div class="card" id="editor_card" style="display:none;">
  <h2 id="editing_book_title">📝 编辑世界书</h2>
  <div id="entries_container"></div>
  <button class="btn" onclick="addNewEntry()">+ 新增条目</button>
  <button class="btn btn-save" onclick="saveCurrentBook()">保存整本修改</button>
</div>

<script>
let currentBookPath = "";
let currentBookData = null;

async function loadInit() {
  const res = await fetch('/api/init').then(r => r.json());
  document.getElementById('max_entries').value = res.config.max_entries || 4;
  document.getElementById('max_chars').value = res.config.max_chars || 2500;
  
  let html = '';
  res.books.forEach(b => {
    const checked = res.config.active_books && res.config.active_books.includes(b.path) ? 'checked' : '';
    html += `<div class="entry-item flex-row">
      <input type="checkbox" style="width:20px" ${checked} onchange="toggleBook('${b.path}', this.checked)">
      <div style="flex:1"><b>${b.name}</b><br><small style="color:#888">${b.path}</small></div>
      <button class="btn" onclick="openBook('${b.path}')">打开条目编辑</button>
    </div>`;
  });
  document.getElementById('books_list').innerHTML = html || '暂无世界书，请放入 /sdcard/Download/st 目录';
}

async function saveSettings() {
  const max_entries = parseInt(document.getElementById('max_entries').value);
  const max_chars = parseInt(document.getElementById('max_chars').value);
  await fetch('/api/config', {
    method: 'POST',
    body: JSON.stringify({max_entries, max_chars})
  });
  alert('自导入预算配置已保存！dsh-Go 将严格按此标准导入');
}

async function toggleBook(path, active) {
  await fetch('/api/toggle_book', {
    method: 'POST',
    body: JSON.stringify({path, active})
  });
}

async function testAutoImport() {
  const text = document.getElementById('test_input').value;
  const res = await fetch('/api/auto_import', {
    method: 'POST',
    body: JSON.stringify({text})
  }).then(r => r.json());
  document.getElementById('test_result').innerText = `命中条目: ${res.total_matched} 个 | 占用字符: ${res.total_chars} / 上限\n\n【送入网关的内容预览】：\n${res.context_prompt || '(未命中任何条目，零 Token 消耗)'}`;
}

async function openBook(path) {
  currentBookPath = path;
  const res = await fetch('/api/read_book?path=' + encodeURIComponent(path)).then(r => r.json());
  currentBookData = res;
  document.getElementById('editor_card').style.display = 'block';
  document.getElementById('editing_book_title').innerText = '📝 正在编辑：' + path.split('/').pop();
  renderEntries();
}

function renderEntries() {
  let entries = currentBookData.entries;
  if (!Array.isArray(entries)) {
    entries = Object.values(entries || {});
  }
  let html = '';
  entries.forEach((e, idx) => {
    const keys = Array.isArray(e.key) ? e.key.join(', ') : (e.key || '');
    html += `<div class="entry-item" id="entry_${idx}">
      <div class="flex-row">
        <label>条目标题：</label>
        <input type="text" value="${e.comment || '未命名'}" onchange="updateEntryField(${idx}, 'comment', this.value)">
        <label><input type="checkbox" ${e.constant ? 'checked' : ''} onchange="updateEntryField(${idx}, 'constant', this.checked)"> 常驻</label>
        <button class="btn btn-del" onclick="deleteEntry(${idx})">删除</button>
      </div>
      <label>触发关键词（英文逗号隔开）：</label>
      <input type="text" value="${keys}" onchange="updateEntryField(${idx}, 'key', this.value.split(',').map(s=>s.trim()))">
      <label>设定内容（Content）：</label>
      <textarea rows="4" onchange="updateEntryField(${idx}, 'content', this.value)">${e.content || ''}</textarea>
    </div>`;
  });
  document.getElementById('entries_container').innerHTML = html;
}

function updateEntryField(idx, field, val) {
  let entries = Array.isArray(currentBookData.entries) ? currentBookData.entries : Object.values(currentBookData.entries);
  entries[idx][field] = val;
  currentBookData.entries = entries;
}

function deleteEntry(idx) {
  let entries = Array.isArray(currentBookData.entries) ? currentBookData.entries : Object.values(currentBookData.entries);
  entries.splice(idx, 1);
  currentBookData.entries = entries;
  renderEntries();
}

function addNewEntry() {
  let entries = Array.isArray(currentBookData.entries) ? currentBookData.entries : Object.values(currentBookData.entries || {});
  entries.unshift({
    comment: "新设定条目",
    key: ["关键词"],
    content: "设定内容描述...",
    constant: false,
    enabled: true
  });
  currentBookData.entries = entries;
  renderEntries();
}

async function saveCurrentBook() {
  await fetch('/api/save_book', {
    method: 'POST',
    body: JSON.stringify({path: currentBookPath, data: currentBookData})
  });
  alert('世界书修改已成功写回本地文件！');
}

window.onload = loadInit;
</script>
</body>
</html>
"""

class RequestHandler(BaseHTTPRequestHandler):
    manager = TavernManager()

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path == "/" or url.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
        elif url.path == "/api/init":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            res = {"config": self.manager.config, "books": self.manager.list_books()}
            self.wfile.write(json.dumps(res).encode("utf-8"))
        elif url.path == "/api/read_book":
            query = urllib.parse.parse_qs(url.query)
            path = query.get("path", [""])[0]
            data = self.manager.read_book(path)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data or {}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        data = json.loads(body) if body else {}

        if url.path == "/api/config":
            self.manager.config["max_entries"] = data.get("max_entries", DEFAULT_MAX_ENTRIES)
            self.manager.config["max_chars"] = data.get("max_chars", DEFAULT_MAX_CHARS)
            self.manager.save_config()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        elif url.path == "/api/toggle_book":
            p = data.get("path")
            active = data.get("active")
            cur = self.manager.config.get("active_books", [])
            if active and p not in cur:
                cur.append(p)
            elif not active and p in cur:
                cur.remove(p)
            self.manager.config["active_books"] = cur
            self.manager.save_config()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        elif url.path == "/api/auto_import":
            res = self.manager.auto_import(data.get("text", ""))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
        elif url.path == "/api/save_book":
            self.manager.save_book(data.get("path"), data.get("data"))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

def main():
    parser = argparse.ArgumentParser(description="Tavern Auto-Import & Manager")
    parser.add_argument("--server", action="store_true", help="Start web manager")
    parser.add_argument("--port", type=int, default=18790, help="Web manager port")
    parser.add_argument("--query", type=str, help="CLI auto-import query text")
    args = parser.parse_args()

    tm = TavernManager()

    if args.query is not None:
        res = tm.auto_import(args.query)
        print(json.dumps(res, ensure_ascii=False))
        return

    if args.server:
        server = HTTPServer(("0.0.0.0", args.port), RequestHandler)
        print(f"Server started on http://127.0.0.1:{args.port}")
        server.serve_forever()

if __name__ == "__main__":
    main()
