"""
PC 远程控制 - 主服务端
手机通过 WebSocket 实时控制电脑的鼠标、键盘、音量等
"""
import asyncio
import json
import socket
import os
import sys
import time
import subprocess
from aiohttp import web
import pyautogui

# ==================== 配置 ====================
PORT = 5000
MOUSE_SENSITIVITY = 2.5  # 鼠标移动灵敏度

# 安全设置：pyautogui 的全局配置
pyautogui.FAILSAFE = True   # 鼠标移到屏幕左上角时中止
pyautogui.PAUSE = 0         # 命令间不延迟（WebSocket 本身控制频率）

# ==================== PC 控制函数 ====================

def do_mouse_move(dx: float, dy: float):
    """相对移动鼠标"""
    pyautogui.moveRel(dx * MOUSE_SENSITIVITY, dy * MOUSE_SENSITIVITY, _pause=False)

def do_mouse_click(button: str = "left"):
    """鼠标点击"""
    pyautogui.click(button=button, _pause=False)

def do_mouse_double_click(button: str = "left"):
    """鼠标双击"""
    pyautogui.doubleClick(button=button, _pause=False)

def do_mouse_down(button: str = "left"):
    """鼠标按下（用于拖拽）"""
    pyautogui.mouseDown(button=button, _pause=False)

def do_mouse_up(button: str = "left"):
    """鼠标松开"""
    pyautogui.mouseUp(button=button, _pause=False)

def do_scroll(amount: int):
    """滚动滚轮，正数向上，负数向下"""
    pyautogui.scroll(amount, _pause=False)

def do_key_press(key: str):
    """按下单个按键"""
    pyautogui.press(key, _pause=False)

def do_key_combo(keys: list):
    """组合键，如 ['ctrl', 'c']"""
    pyautogui.hotkey(*keys, _pause=False)

def do_type_text(text: str):
    """输入文本（支持中文）"""
    # 对于非 ASCII 文本，使用剪贴板 + 粘贴方式
    if text.isascii():
        pyautogui.write(text, interval=0.01, _pause=False)
    else:
        # 中文等 unicode 文本：通过剪贴板粘贴
        import tempfile
        try:
            import pyperclip
            old = pyperclip.paste()
            pyperclip.copy(text)
            pyautogui.hotkey('ctrl', 'v', _pause=False)
            # 恢复剪贴板是异步的，简单处理
        except ImportError:
            # 如果没有 pyperclip，回退到逐字符输入（可能不支持中文）
            pyautogui.write(text, interval=0.01, _pause=False)

def do_volume_set(level: float):
    """设置音量 0.0 ~ 1.0"""
    # Windows: 使用 pyautogui 模拟按键
    # 先静音再取消静音以获取当前状态，然后调整
    current_muted = False
    for _ in range(int(level * 50)):
        pyautogui.press('volumeup', _pause=False)
    # 简化方案：直接用 nircmd 或 powershell
    try:
        import comtypes.client
        # 更精确的方式用 pycaw，这里做 fallback
        raise ImportError
    except:
        pass

def do_volume_up():
    pyautogui.press('volumeup', _pause=False)

def do_volume_down():
    pyautogui.press('volumedown', _pause=False)

def do_volume_mute():
    pyautogui.press('volumemute', _pause=False)

def do_media(cmd: str):
    """媒体控制"""
    key_map = {
        'play_pause': 'playpause',
        'next': 'nexttrack',
        'prev': 'prevtrack',
        'stop': 'stop'
    }
    key = key_map.get(cmd)
    if key:
        pyautogui.press(key, _pause=False)

def do_system(cmd: str):
    """系统命令"""
    if cmd == 'lock':
        # Windows 锁屏
        subprocess.run(['rundll32.exe', 'user32.dll,LockWorkStation'], shell=False)
    elif cmd == 'sleep':
        subprocess.run(['rundll32.exe', 'powrprof.dll,SetSuspendState', '0,1,0'], shell=False)
    elif cmd == 'show_desktop':
        pyautogui.hotkey('win', 'd', _pause=False)
    elif cmd == 'task_view':
        pyautogui.hotkey('win', 'tab', _pause=False)
    elif cmd == 'start_menu':
        pyautogui.press('win', _pause=False)

def do_get_screen_size():
    """获取屏幕尺寸"""
    return {'width': pyautogui.size().width, 'height': pyautogui.size().height}

# ==================== HTML 前端 ====================

HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no, viewport-fit=cover">
<title>PC 远程控制</title>
<style>
:root {
  --bg: #0d0d0d;
  --card: #1a1a1a;
  --border: #2a2a2a;
  --text: #eee;
  --text-dim: #888;
  --accent: #4ade80;
  --danger: #ef4444;
  --warn: #f59e0b;
  --blue: #3b82f6;
  --radius: 14px;
}
* { margin:0; padding:0; box-sizing:border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: var(--bg); color: var(--text);
  height: 100dvh; overflow: hidden;
  display: flex; flex-direction: column;
  touch-action: none;
  -webkit-user-select: none; user-select: none;
  -webkit-tap-highlight-color: transparent;
}

/* ---- 顶部状态栏 ---- */
#status-bar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 16px; background: var(--card);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
#status-bar .left { display: flex; align-items: center; gap: 8px; }
#status-dot {
  width: 10px; height: 10px; border-radius: 50%;
  background: var(--accent);
  animation: pulse 2s infinite;
}
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
#latency { font-size: 12px; color: var(--text-dim); }
#screen-info { font-size: 12px; color: var(--text-dim); }

/* ---- 主内容区 ---- */
#main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }

/* ---- 触摸板 ---- */
#touchpad-panel { flex: 1; display: flex; flex-direction: column; }
#touchpad {
  flex: 1; margin: 10px; border-radius: var(--radius);
  background: var(--card); border: 2px solid var(--border);
  position: relative; overflow: hidden;
  touch-action: none;
}
#touchpad-hint {
  position: absolute; inset: 0; display: flex;
  align-items: center; justify-content: center;
  color: var(--text-dim); font-size: 14px; pointer-events: none;
  transition: opacity 0.5s;
}
#touchpad-indicator {
  position: absolute; width: 40px; height: 40px;
  border-radius: 50%; background: rgba(74,222,128,0.2);
  border: 2px solid rgba(74,222,128,0.5);
  transform: translate(-50%,-50%); pointer-events: none;
  opacity: 0; transition: opacity 0.15s;
}
.touch-buttons {
  display: flex; gap: 8px; padding: 0 10px 10px;
}
.touch-btn {
  flex: 1; padding: 12px; border-radius: 10px;
  border: 1px solid var(--border); background: var(--card);
  color: var(--text); font-size: 14px; text-align: center;
  cursor: pointer; transition: background 0.15s;
}
.touch-btn:active { background: #333; }
.touch-btn.left-btn { border-color: var(--accent); color: var(--accent); }
.touch-btn.right-btn { border-color: var(--blue); color: var(--blue); }

/* ---- 底部导航 ---- */
#nav {
  display: flex; background: var(--card);
  border-top: 1px solid var(--border); flex-shrink: 0;
  padding-bottom: env(safe-area-inset-bottom);
}
.nav-item {
  flex: 1; padding: 12px 8px 8px;
  text-align: center; font-size: 11px; color: var(--text-dim);
  cursor: pointer; transition: color 0.2s;
  border: none; background: none;
}
.nav-item.active { color: var(--accent); }
.nav-item .icon { font-size: 22px; display: block; margin-bottom: 2px; }

/* ---- 面板通用 ---- */
.panel { flex: 1; padding: 12px; overflow-y: auto; display: none; }
.panel.active { display: flex; flex-direction: column; }

/* ---- 键盘面板 ---- */
#keyboard-panel { gap: 10px; }
#text-input {
  width: 100%; padding: 14px; border-radius: var(--radius);
  border: 1px solid var(--border); background: var(--card);
  color: var(--text); font-size: 16px; outline: none;
}
#text-input:focus { border-color: var(--accent); }
.key-grid {
  display: grid; grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}
.key-btn {
  padding: 12px 6px; border-radius: 10px; font-size: 13px;
  border: 1px solid var(--border); background: var(--card);
  color: var(--text); cursor: pointer; transition: all 0.1s;
}
.key-btn:active { background: #333; transform: scale(0.95); }
.key-btn.wide { grid-column: span 2; }
.key-btn.send { background: var(--accent); color: #000; font-weight: 700; border: none; }
.key-btn.danger { border-color: var(--danger); color: var(--danger); }

/* ---- 媒体面板 ---- */
.media-section { margin-bottom: 16px; }
.media-section h3 {
  font-size: 13px; color: var(--text-dim); margin-bottom: 8px;
  text-transform: uppercase; letter-spacing: 1px;
}
.volume-row {
  display: flex; align-items: center; gap: 10px;
  background: var(--card); padding: 14px; border-radius: var(--radius);
}
.volume-row input[type=range] { flex: 1; accent-color: var(--accent); }
.volume-row .vol-icon { font-size: 20px; }
.media-buttons {
  display: flex; gap: 8px;
}
.media-btn {
  flex: 1; padding: 16px; border-radius: var(--radius);
  border: 1px solid var(--border); background: var(--card);
  color: var(--text); font-size: 20px; text-align: center;
  cursor: pointer; transition: background 0.15s;
}
.media-btn:active { background: #333; }
.media-btn.main-btn { background: var(--accent); color: #000; border: none; }

/* ---- 系统面板 ---- */
.sys-grid { display: flex; flex-direction: column; gap: 8px; }
.sys-btn {
  display: flex; align-items: center; gap: 12px;
  padding: 16px; border-radius: var(--radius);
  border: 1px solid var(--border); background: var(--card);
  color: var(--text); font-size: 15px; cursor: pointer;
  transition: background 0.15s; text-align: left;
}
.sys-btn:active { background: #333; }
.sys-btn .sys-icon { font-size: 24px; width: 36px; text-align: center; }
.sys-btn.warn { border-color: var(--warn); color: var(--warn); }
.sys-btn.danger { border-color: var(--danger); color: var(--danger); }

/* ---- Toast ---- */
#toast {
  position: fixed; bottom: 100px; left: 50%; transform: translateX(-50%);
  background: #333; color: #fff; padding: 10px 20px; border-radius: 20px;
  font-size: 14px; opacity: 0; transition: opacity 0.3s; z-index: 100;
  pointer-events: none;
}
#toast.show { opacity: 1; }
</style>
</head>
<body>

<!-- 状态栏 -->
<div id="status-bar">
  <div class="left">
    <div id="status-dot"></div>
    <span id="latency">--</span>
  </div>
  <span id="screen-info"></span>
</div>

<!-- 主内容 -->
<div id="main">

  <!-- 触摸板面板 -->
  <div class="panel active" id="touchpad-panel">
    <div id="touchpad">
      <div id="touchpad-hint">🖱️ 在此区域滑动控制鼠标</div>
      <div id="touchpad-indicator"></div>
    </div>
    <div class="touch-buttons">
      <button class="touch-btn left-btn" id="btn-left">🖱️ 左键</button>
      <button class="touch-btn right-btn" id="btn-right">🖱️ 右键</button>
      <button class="touch-btn" id="btn-dbclick">🔁 双击</button>
    </div>
  </div>

  <!-- 键盘面板 -->
  <div class="panel" id="keyboard-panel">
    <input type="text" id="text-input" placeholder="输入文字后点发送..." autocomplete="off" autocorrect="off">
    <div class="key-grid">
      <button class="key-btn wide send" id="btn-send">📤 发送</button>
      <button class="key-btn" data-key="enter">Enter</button>
      <button class="key-btn" data-key="space">Space</button>
      <button class="key-btn" data-key="backspace">⌫</button>
      <button class="key-btn" data-key="escape">Esc</button>
      <button class="key-btn" data-key="tab">Tab</button>
      <button class="key-btn" data-key="delete">Del</button>
      <button class="key-btn" data-key="up">↑</button>
      <button class="key-btn" data-key="left">←</button>
      <button class="key-btn" data-key="down">↓</button>
      <button class="key-btn" data-key="right">→</button>
      <button class="key-btn wide" data-combo="ctrl,c">Ctrl+C</button>
      <button class="key-btn wide" data-combo="ctrl,v">Ctrl+V</button>
      <button class="key-btn" data-combo="ctrl,z">Ctrl+Z</button>
      <button class="key-btn" data-combo="alt,f4">Alt+F4</button>
    </div>
  </div>

  <!-- 媒体面板 -->
  <div class="panel" id="media-panel">
    <div class="media-section">
      <h3>🔊 音量控制</h3>
      <div class="volume-row">
        <span class="vol-icon">🔈</span>
        <input type="range" id="volume-slider" min="0" max="100" value="50">
        <span class="vol-icon">🔊</span>
      </div>
      <div class="media-buttons" style="margin-top:8px;">
        <button class="media-btn" id="btn-vol-down">🔉</button>
        <button class="media-btn" id="btn-mute">🔇</button>
        <button class="media-btn" id="btn-vol-up">🔊</button>
      </div>
    </div>
    <div class="media-section">
      <h3>🎵 媒体播放</h3>
      <div class="media-buttons">
        <button class="media-btn" data-media="prev">⏮</button>
        <button class="media-btn main-btn" data-media="play_pause">⏯️</button>
        <button class="media-btn" data-media="next">⏭</button>
      </div>
    </div>
  </div>

  <!-- 系统面板 -->
  <div class="panel" id="system-panel">
    <div class="sys-grid">
      <button class="sys-btn" data-system="lock">
        <span class="sys-icon">🔒</span> 锁屏
      </button>
      <button class="sys-btn" data-system="show_desktop">
        <span class="sys-icon">🖥️</span> 显示桌面
      </button>
      <button class="sys-btn" data-system="task_view">
        <span class="sys-icon">📋</span> 任务视图
      </button>
      <button class="sys-btn" data-system="start_menu">
        <span class="sys-icon">🪟</span> 开始菜单
      </button>
      <button class="sys-btn warn" data-system="sleep">
        <span class="sys-icon">😴</span> 休眠
      </button>
    </div>
  </div>
</div>

<!-- 底部导航 -->
<div id="nav">
  <button class="nav-item active" data-panel="touchpad-panel" id="nav-touch">
    <span class="icon">🖱️</span>触摸板
  </button>
  <button class="nav-item" data-panel="keyboard-panel" id="nav-keyboard">
    <span class="icon">⌨️</span>键盘
  </button>
  <button class="nav-item" data-panel="media-panel" id="nav-media">
    <span class="icon">🎵</span>媒体
  </button>
  <button class="nav-item" data-panel="system-panel" id="nav-system">
    <span class="icon">⚙️</span>系统
  </button>
</div>

<!-- Toast -->
<div id="toast"></div>

<script>
// ==================== 全局状态 ====================
let ws = null;
let currentPanel = 'touchpad-panel';
let screenW = 1920, screenH = 1080;

// ==================== WebSocket ====================
function connect() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(`${proto}//${location.host}/ws`);

  ws.onopen = () => {
    document.getElementById('status-dot').style.background = 'var(--accent)';
    toast('已连接');
  };

  ws.onclose = () => {
    document.getElementById('status-dot').style.background = 'var(--danger)';
    setTimeout(connect, 2000);
  };

  ws.onerror = () => ws.close();

  ws.onmessage = (e) => {
    const data = JSON.parse(e.data);
    if (data.type === 'pong') {
      const latency = Date.now() - data.sent;
      document.getElementById('latency').textContent = latency + 'ms';
    } else if (data.type === 'screen') {
      screenW = data.width;
      screenH = data.height;
      document.getElementById('screen-info').textContent = screenW + '×' + screenH;
    }
  };
}

function send(data) {
  // 优先用 HTTP POST（穿透隧道最可靠），WebSocket 作备用
  fetch('/cmd', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  }).catch(() => {
    // HTTP 失败时回退到 WebSocket
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(data));
    }
  });
}

// 心跳
setInterval(() => {
  send({ action: 'ping', sent: Date.now() });
}, 3000);

function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('show'), 1500);
}

// ==================== 面板切换 ====================
document.querySelectorAll('.nav-item').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const panelId = btn.dataset.panel;
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    document.getElementById(panelId).classList.add('active');
    currentPanel = panelId;
  });
});

// ==================== 触摸板 ====================
const touchpad = document.getElementById('touchpad');
const indicator = document.getElementById('touchpad-indicator');
const hint = document.getElementById('touchpad-hint');

let touchState = {
  active: false,
  startX: 0, startY: 0,
  lastX: 0, lastY: 0,
  startTime: 0,
  moved: false,
  longPress: false,
  longPressTimer: null,
  touchCount: 0,
  prevDx: 0, prevDy: 0,
};

touchpad.addEventListener('touchstart', (e) => {
  e.preventDefault();
  const touch = e.touches[0];
  touchState.active = true;
  touchState.startX = touch.clientX;
  touchState.startY = touch.clientY;
  touchState.lastX = touch.clientX;
  touchState.lastY = touch.clientY;
  touchState.startTime = Date.now();
  touchState.moved = false;
  touchState.longPress = false;
  touchState.touchCount = e.touches.length;
  touchState.prevDx = 0;
  touchState.prevDy = 0;

  hint.style.opacity = '0';
  // 视觉反馈：触摸时边框变亮
  touchpad.style.borderColor = '#4ade80';
  touchpad.style.background = '#1e1e1e';

  // 长按检测
  clearTimeout(touchState.longPressTimer);
  touchState.longPressTimer = setTimeout(() => {
    touchState.longPress = true;
    indicator.style.borderColor = 'rgba(239,68,68,0.8)';
    indicator.style.background = 'rgba(239,68,68,0.2)';
    touchpad.style.borderColor = '#ef4444';
    toast('拖拽模式');
  }, 500);
}, { passive: false });

touchpad.addEventListener('touchmove', (e) => {
  e.preventDefault();
  if (!touchState.active) return;

  const touch = e.touches[0];
  const dx = touch.clientX - touchState.lastX;
  const dy = touch.clientY - touchState.lastY;

  if (Math.abs(dx) > 0 || Math.abs(dy) > 0) {
    touchState.moved = true;
    touchState.prevDx = dx;
    touchState.prevDy = dy;

    // 显示指示器
    indicator.style.left = touch.clientX - touchpad.getBoundingClientRect().left + 'px';
    indicator.style.top = touch.clientY - touchpad.getBoundingClientRect().top + 'px';
    indicator.style.opacity = '1';

    if (touchState.longPress) {
      // 长按拖拽模式
      send({ action: 'mouse_move', dx: dx, dy: dy });
    } else if (e.touches.length >= 2) {
      // 双指滚动
      send({ action: 'mouse_scroll', dy: -dy * 2 });
    } else {
      // 普通移动
      send({ action: 'mouse_move', dx: dx, dy: dy });
    }

    touchState.lastX = touch.clientX;
    touchState.lastY = touch.clientY;
  }
}, { passive: false });

touchpad.addEventListener('touchend', (e) => {
  e.preventDefault();
  clearTimeout(touchState.longPressTimer);
  indicator.style.opacity = '0';
  indicator.style.borderColor = 'rgba(74,222,128,0.5)';
  indicator.style.background = 'rgba(74,222,128,0.2)';
  // 恢复边框
  touchpad.style.borderColor = '#2a2a2a';
  touchpad.style.background = '#1a1a1a';

  if (!touchState.moved) {
    const elapsed = Date.now() - touchState.startTime;
    if (elapsed < 300) {
      if (e.touches.length === 0 && touchState.touchCount === 2) {
        // 双指点击 = 右键
        send({ action: 'mouse_click', button: 'right' });
        toast('右键');
      } else if (elapsed < 300) {
        // 单指短按 = 左键
        send({ action: 'mouse_click', button: 'left' });
        toast('左键');
      }
    }
  }

  touchState.active = false;
  touchState.longPress = false;
}, { passive: false });

// 底部按钮
document.getElementById('btn-left').addEventListener('click', () => {
  send({ action: 'mouse_click', button: 'left' });
  toast('左键');
});
document.getElementById('btn-right').addEventListener('click', () => {
  send({ action: 'mouse_click', button: 'right' });
  toast('右键');
});
document.getElementById('btn-dbclick').addEventListener('click', () => {
  send({ action: 'mouse_double_click', button: 'left' });
  toast('双击');
});

// ==================== 键盘 ====================
document.querySelectorAll('.key-btn[data-key]').forEach(btn => {
  btn.addEventListener('click', () => {
    send({ action: 'key_press', key: btn.dataset.key });
    toast(btn.dataset.key);
  });
});
document.querySelectorAll('.key-btn[data-combo]').forEach(btn => {
  btn.addEventListener('click', () => {
    const keys = btn.dataset.combo.split(',');
    send({ action: 'key_combo', keys: keys });
    toast(keys.join('+'));
  });
});
document.getElementById('btn-send').addEventListener('click', () => {
  const input = document.getElementById('text-input');
  const text = input.value;
  if (text) {
    send({ action: 'type_text', text: text });
    toast('已发送: ' + text);
    input.value = '';
  }
});
document.getElementById('text-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    document.getElementById('btn-send').click();
  }
});

// ==================== 媒体 ====================
document.querySelectorAll('[data-media]').forEach(btn => {
  btn.addEventListener('click', () => {
    send({ action: 'media', cmd: btn.dataset.media });
  });
});
document.getElementById('btn-vol-up').addEventListener('click', () => {
  send({ action: 'volume_up' });
});
document.getElementById('btn-vol-down').addEventListener('click', () => {
  send({ action: 'volume_down' });
});
document.getElementById('btn-mute').addEventListener('click', () => {
  send({ action: 'volume_mute' });
});
document.getElementById('volume-slider').addEventListener('input', (e) => {
  const val = parseInt(e.target.value);
  // 不直接设音量，等松开再设
});
document.getElementById('volume-slider').addEventListener('change', (e) => {
  const val = parseInt(e.target.value) / 100;
  // 相对调整音量
  send({ action: 'volume_set', level: val });
});

// ==================== 系统 ====================
document.querySelectorAll('[data-system]').forEach(btn => {
  btn.addEventListener('click', () => {
    const cmd = btn.dataset.system;
    if (cmd === 'sleep') {
      if (confirm('确定要让电脑休眠吗？')) {
        send({ action: 'system', cmd: cmd });
      }
    } else {
      send({ action: 'system', cmd: cmd });
    }
  });
});

// 启动连接
connect();
</script>
</body>
</html>
"""

# ==================== WebSocket 处理 ====================

async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    print(f"  📱 客户端已连接: {request.remote}")

    # 发送屏幕信息
    screen = pyautogui.size()
    await ws.send_json({'type': 'screen', 'width': screen.width, 'height': screen.height})

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    action = data.get('action', '')

                    if action == 'ping':
                        await ws.send_json({'type': 'pong', 'sent': data.get('sent', 0)})
                    else:
                        execute_command(data)

                except json.JSONDecodeError:
                    pass
                except Exception as e:
                    print(f"  ⚠️ WS 命令错误: {e}")

            elif msg.type == web.WSMsgType.ERROR:
                print(f"  ⚠️ WebSocket 错误: {ws.exception()}")
    finally:
        print(f"  📱 客户端已断开: {request.remote}")

    return ws

# ==================== HTTP 命令处理 ====================

def execute_command(data: dict):
    """执行一条命令，返回结果"""
    action = data.get('action', '')
    result = {'ok': True, 'action': action}

    if action == 'mouse_move':
        do_mouse_move(data.get('dx', 0), data.get('dy', 0))

    elif action == 'mouse_click':
        do_mouse_click(data.get('button', 'left'))

    elif action == 'mouse_double_click':
        do_mouse_double_click(data.get('button', 'left'))

    elif action == 'mouse_down':
        do_mouse_down(data.get('button', 'left'))

    elif action == 'mouse_up':
        do_mouse_up(data.get('button', 'left'))

    elif action == 'mouse_scroll':
        do_scroll(data.get('dy', 0))

    elif action == 'key_press':
        do_key_press(data.get('key', ''))

    elif action == 'key_combo':
        do_key_combo(data.get('keys', []))

    elif action == 'type_text':
        do_type_text(data.get('text', ''))

    elif action == 'volume_up':
        do_volume_up()

    elif action == 'volume_down':
        do_volume_down()

    elif action == 'volume_mute':
        do_volume_mute()

    elif action == 'media':
        do_media(data.get('cmd', ''))

    elif action == 'system':
        do_system(data.get('cmd', ''))

    else:
        result['ok'] = False
        result['error'] = f'unknown action: {action}'

    return result


# ==================== HTTP 路由 ====================

FULL_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no, viewport-fit=cover">
<title>PC 远程控制</title>
<style>
:root {
  --bg: #0d0d0d; --card: #1a1a1a; --border: #2a2a2a;
  --text: #eee; --text-dim: #888; --accent: #4ade80;
  --danger: #ef4444; --warn: #f59e0b; --blue: #3b82f6;
  --radius: 14px;
}
* { margin:0; padding:0; box-sizing:border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: var(--bg); color: var(--text);
  height: 100dvh; overflow: hidden;
  display: flex; flex-direction: column;
  touch-action: none;
  -webkit-user-select: none; user-select: none;
  -webkit-tap-highlight-color: transparent;
}

/* 状态栏 */
#status-bar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 14px; background: var(--card);
  border-bottom: 1px solid var(--border); flex-shrink: 0; font-size:12px;
}
#status-bar .dot {
  width:8px; height:8px; border-radius:50%; display:inline-block; margin-right:4px;
}
.dot.green { background: var(--accent); }
.dot.red { background: var(--danger); }
#screen-info { color: var(--text-dim); }

/* 主内容区 */
#main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }

/* ---- 触摸板 ---- */
#touchpad-panel { flex: 1; display: flex; flex-direction: column; }
#touchpad {
  flex: 1; margin: 8px; border-radius: var(--radius);
  background: var(--card); border: 2px solid var(--border);
  position: relative; overflow: hidden; touch-action: none;
}
#touchpad-hint {
  position: absolute; inset: 0; display: flex;
  align-items: center; justify-content: center;
  color: var(--text-dim); font-size: 13px; pointer-events: none;
  transition: opacity 0.4s; flex-direction: column; gap: 4px;
}
#touchpad-indicator {
  position: absolute; width: 36px; height: 36px;
  border-radius: 50%; background: rgba(74,222,128,0.15);
  border: 2px solid rgba(74,222,128,0.4);
  transform: translate(-50%,-50%); pointer-events: none;
  opacity: 0; transition: opacity 0.1s;
}
.touch-buttons {
  display: flex; gap: 6px; padding: 0 8px 6px;
}
.touch-btn {
  flex: 1; padding: 10px; border-radius: 10px;
  border: 1px solid var(--border); background: var(--card);
  color: var(--text); font-size: 13px; text-align: center; cursor: pointer;
}
.touch-btn:active { background: #333; }
.touch-btn.primary { border-color: var(--accent); color: var(--accent); }
.touch-btn.hold-btn { border-color: var(--warn); color: var(--warn); }
.touch-btn.hold-btn.active { background: var(--danger); color: #fff; border-color: var(--danger); animation: glow 0.8s infinite alternate; }
@keyframes glow { from { box-shadow: 0 0 4px var(--danger); } to { box-shadow: 0 0 16px var(--danger); } }

/* 底部导航 */
#nav {
  display: flex; background: var(--card);
  border-top: 1px solid var(--border); flex-shrink: 0;
  padding-bottom: env(safe-area-inset-bottom);
}
.nav-item {
  flex: 1; padding: 8px 6px 6px; text-align: center;
  font-size: 10px; color: var(--text-dim); cursor: pointer;
  border: none; background: none; transition: color 0.2s;
}
.nav-item.active { color: var(--accent); }
.nav-item .icon { font-size: 20px; display: block; margin-bottom: 1px; }

/* 面板 */
.panel { flex: 1; padding: 10px; overflow-y: auto; display: none; }
.panel.active { display: flex; flex-direction: column; }

/* 键盘 */
#keyboard-panel { gap: 8px; }
#text-input {
  width: 100%; padding: 12px; border-radius: var(--radius);
  border: 1px solid var(--border); background: var(--card);
  color: var(--text); font-size: 15px; outline: none;
}
#text-input:focus { border-color: var(--accent); }
.key-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
.key-btn {
  padding: 10px 4px; border-radius: 10px; font-size: 12px;
  border: 1px solid var(--border); background: var(--card);
  color: var(--text); cursor: pointer;
}
.key-btn:active { background: #333; transform: scale(0.95); }
.key-btn.wide { grid-column: span 2; }
.key-btn.send { background: var(--accent); color: #000; font-weight: 700; border: none; }

/* 媒体 */
.media-section { margin-bottom: 14px; }
.media-section h3 { font-size: 12px; color: var(--text-dim); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 1px; }
.volume-row { display: flex; align-items: center; gap: 8px; background: var(--card); padding: 12px; border-radius: var(--radius); }
.volume-row input[type=range] { flex: 1; accent-color: var(--accent); }
.media-buttons { display: flex; gap: 6px; }
.media-btn {
  flex: 1; padding: 14px; border-radius: var(--radius);
  border: 1px solid var(--border); background: var(--card);
  color: var(--text); font-size: 18px; text-align: center; cursor: pointer;
}
.media-btn:active { background: #333; }
.media-btn.main { background: var(--accent); color: #000; border: none; }

/* 系统 */
.sys-grid { display: flex; flex-direction: column; gap: 6px; }
.sys-btn {
  display: flex; align-items: center; gap: 10px;
  padding: 14px; border-radius: var(--radius);
  border: 1px solid var(--border); background: var(--card);
  color: var(--text); font-size: 14px; cursor: pointer;
}
.sys-btn:active { background: #333; }
.sys-btn .sys-icon { font-size: 22px; width: 32px; text-align: center; }
.sys-btn.warn { border-color: var(--warn); color: var(--warn); }

/* 屏幕画面 */
#screen-view {
  width: 100%; border-radius: var(--radius);
  border: 1px solid var(--border); display: block;
  image-rendering: auto; aspect-ratio: 16/9;
  object-fit: contain; background: #000;
}
#screen-panel { align-items: center; gap: 8px; }
#screen-status { font-size: 11px; color: var(--text-dim); text-align: center; }

/* Toast */
#toast {
  position: fixed; bottom: 80px; left: 50%; transform: translateX(-50%);
  background: #333; color: #fff; padding: 8px 18px; border-radius: 20px;
  font-size: 13px; opacity: 0; transition: opacity 0.3s; z-index: 100; pointer-events: none;
}
#toast.show { opacity: 1; }
</style>
</head>
<body>

<div id="status-bar">
  <div>
    <span class="dot green" id="ws-dot"></span>
    <span id="latency">--</span>
  </div>
  <span id="screen-info"></span>
</div>

<div id="main">
  <!-- 触摸板 -->
  <div class="panel active" id="touchpad-panel">
    <div id="touchpad">
      <div id="touchpad-hint">
        <span>🖱️ 滑动=移动光标</span>
        <span style="font-size:11px;">长按不动=拖拽 · 双指=滚轮</span>
      </div>
      <div id="touchpad-indicator"></div>
    </div>
    <div class="touch-buttons">
      <button class="touch-btn hold-btn" id="btn-hold">🔴 按住左键</button>
      <button class="touch-btn primary" id="btn-left">👆 单击</button>
      <button class="touch-btn" id="btn-right">🖱️ 右键</button>
      <button class="touch-btn" id="btn-dbclick">🔁 双击</button>
    </div>
  </div>

  <!-- 屏幕 -->
  <div class="panel" id="screen-panel">
    <span id="screen-status">🔄 等待连接...</span>
    <img id="screen-view" alt="PC屏幕" />
    <button class="touch-btn" id="btn-refresh-screen" style="width:100%;padding:12px;">🔄 刷新屏幕</button>
  </div>

  <!-- 键盘 -->
  <div class="panel" id="keyboard-panel">
    <input type="text" id="text-input" placeholder="输入文字后点发送..." autocomplete="off" autocorrect="off">
    <div class="key-grid">
      <button class="key-btn wide send" id="btn-send">📤 发送</button>
      <button class="key-btn" data-key="enter">Enter</button>
      <button class="key-btn" data-key="space">Space</button>
      <button class="key-btn" data-key="backspace">⌫</button>
      <button class="key-btn" data-key="escape">Esc</button>
      <button class="key-btn" data-key="tab">Tab</button>
      <button class="key-btn" data-key="delete">Del</button>
      <button class="key-btn" data-key="up">↑</button>
      <button class="key-btn" data-key="left">←</button>
      <button class="key-btn" data-key="down">↓</button>
      <button class="key-btn" data-key="right">→</button>
      <button class="key-btn wide" data-combo="ctrl,c">Ctrl+C</button>
      <button class="key-btn wide" data-combo="ctrl,v">Ctrl+V</button>
      <button class="key-btn" data-combo="ctrl,z">Ctrl+Z</button>
      <button class="key-btn" data-combo="alt,f4">Alt+F4</button>
    </div>
  </div>

  <!-- 媒体 -->
  <div class="panel" id="media-panel">
    <div class="media-section">
      <h3>🔊 音量</h3>
      <div class="volume-row">
        <span>🔈</span>
        <input type="range" id="volume-slider" min="0" max="100" value="50">
        <span>🔊</span>
      </div>
      <div class="media-buttons" style="margin-top:6px;">
        <button class="media-btn" id="btn-vol-down">🔉</button>
        <button class="media-btn" id="btn-mute">🔇</button>
        <button class="media-btn" id="btn-vol-up">🔊</button>
      </div>
    </div>
    <div class="media-section">
      <h3>🎵 播放</h3>
      <div class="media-buttons">
        <button class="media-btn" data-media="prev">⏮</button>
        <button class="media-btn main" data-media="play_pause">⏯️</button>
        <button class="media-btn" data-media="next">⏭</button>
      </div>
    </div>
  </div>

  <!-- 系统 -->
  <div class="panel" id="system-panel">
    <div class="sys-grid">
      <button class="sys-btn" data-system="lock"><span class="sys-icon">🔒</span>锁屏</button>
      <button class="sys-btn" data-system="show_desktop"><span class="sys-icon">🖥️</span>显示桌面</button>
      <button class="sys-btn" data-system="task_view"><span class="sys-icon">📋</span>任务视图</button>
      <button class="sys-btn" data-system="start_menu"><span class="sys-icon">🪟</span>开始菜单</button>
      <button class="sys-btn warn" data-system="sleep"><span class="sys-icon">😴</span>休眠</button>
    </div>
  </div>
</div>

<div id="nav">
  <button class="nav-item active" data-panel="touchpad-panel"><span class="icon">🖱️</span>触摸板</button>
  <button class="nav-item" data-panel="screen-panel"><span class="icon">🖥️</span>屏幕</button>
  <button class="nav-item" data-panel="keyboard-panel"><span class="icon">⌨️</span>键盘</button>
  <button class="nav-item" data-panel="media-panel"><span class="icon">🎵</span>媒体</button>
  <button class="nav-item" data-panel="system-panel"><span class="icon">⚙️</span>系统</button>
</div>

<div id="toast"></div>

<script>
// ==================== 状态 ====================
let ws = null;
let wsReady = false;
let screenW = 1920, screenH = 1080;
let screenTimer = null;
let screenRunning = false;

// ==================== WebSocket ====================
function connect() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(proto + '//' + location.host + '/ws');

  ws.onopen = () => {
    wsReady = true;
    document.getElementById('ws-dot').className = 'dot green';
    toast('已连接');
  };

  ws.onclose = () => {
    wsReady = false;
    document.getElementById('ws-dot').className = 'dot red';
    setTimeout(connect, 2000);
  };

  ws.onerror = () => ws.close();

  ws.onmessage = (e) => {
    const data = JSON.parse(e.data);
    if (data.type === 'pong') {
      document.getElementById('latency').textContent = (Date.now() - data.sent) + 'ms';
    } else if (data.type === 'screen') {
      screenW = data.width;
      screenH = data.height;
      document.getElementById('screen-info').textContent = screenW + '×' + screenH;
    } else if (data.type === 'frame') {
      // 接收屏幕帧
      const img = document.getElementById('screen-view');
      img.src = 'data:image/jpeg;base64,' + data.data;
      document.getElementById('screen-status').textContent =
        '🟢 实时 (' + data.fps + 'fps) - ' + new Date().toLocaleTimeString();
    }
  };
}

// ==================== 命令发送 ====================
// 高频操作(鼠标移动) → WebSocket
// 低频操作(点击、按键等) → HTTP POST

let pendingDx = 0, pendingDy = 0;
let flushTimer = null;

function sendMouseMove(dx, dy) {
  pendingDx += dx;
  pendingDy += dy;
  if (!flushTimer) {
    flushTimer = setTimeout(flushMouseMove, 16); // ~60fps
  }
}

function flushMouseMove() {
  flushTimer = null;
  const dx = pendingDx, dy = pendingDy;
  pendingDx = 0; pendingDy = 0;
  if ((Math.abs(dx) > 0.1 || Math.abs(dy) > 0.1) && wsReady) {
    ws.send(JSON.stringify({action:'mouse_move', dx:Math.round(dx), dy:Math.round(dy)}));
  }
}

function send(data) {
  const json = JSON.stringify(data);
  // 优先 WebSocket
  if (wsReady) {
    ws.send(json);
  } else {
    // 回退 HTTP POST
    fetch('/cmd', {method:'POST', headers:{'Content-Type':'application/json'}, body:json}).catch(()=>{});
  }
}

// 心跳
setInterval(() => {
  if (wsReady) ws.send(JSON.stringify({action:'ping', sent:Date.now()}));
}, 3000);

function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg; el.classList.add('show');
  clearTimeout(el._t); el._t = setTimeout(() => el.classList.remove('show'), 1500);
}

// ==================== 面板切换 ====================
document.querySelectorAll('.nav-item').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const pid = btn.dataset.panel;
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    document.getElementById(pid).classList.add('active');

    // 屏幕面板激活时开始刷新
    if (pid === 'screen-panel') startScreenStream();
    else stopScreenStream();
  });
});

// ==================== 屏幕画面 ====================
function startScreenStream() {
  if (screenRunning) return;
  screenRunning = true;
  document.getElementById('screen-status').textContent = '🔄 加载中...';
  refreshScreen();
  screenTimer = setInterval(refreshScreen, 1500);
}

function stopScreenStream() {
  screenRunning = false;
  if (screenTimer) { clearInterval(screenTimer); screenTimer = null; }
}

function refreshScreen() {
  fetch('/screen.jpg?' + Date.now())
    .then(r => r.blob())
    .then(blob => {
      const reader = new FileReader();
      reader.onload = () => {
        document.getElementById('screen-view').src = reader.result;
        document.getElementById('screen-status').textContent =
          '🟢 ' + new Date().toLocaleTimeString() + ' (1.5秒刷新)';
      };
      reader.readAsDataURL(blob);
    })
    .catch(() => {
      document.getElementById('screen-status').textContent = '🔴 获取失败';
    });
}

document.getElementById('btn-refresh-screen').addEventListener('click', refreshScreen);

// ==================== 触摸板 ====================
// 滑动=移动光标 | 长按不动0.5秒→拖拽 | 双指=滚轮
// 按钮：[单击][右键][双击][按住(切换)]
const touchpad = document.getElementById('touchpad');
const indicator = document.getElementById('touchpad-indicator');
const hint = document.getElementById('touchpad-hint');
let holdActive = false;
let dragMode = false;  // 触摸板长按拖拽模式
let dragTimer = null;

let ts = {
  active: false, lastX:0, lastY:0,
  startX:0, startY:0, startTime:0, moved: false
};

touchpad.addEventListener('touchstart', (e) => {
  e.preventDefault();
  const t = e.touches[0];
  ts.active = true;
  ts.lastX = t.clientX;
  ts.lastY = t.clientY;
  ts.startX = t.clientX;
  ts.startY = t.clientY;
  ts.startTime = Date.now();
  ts.moved = false;
  dragMode = false;

  hint.style.opacity = '0';
  touchpad.style.borderColor = '#4ade80';

  // 长按不动 500ms → 进入拖拽模式
  clearTimeout(dragTimer);
  dragTimer = setTimeout(() => {
    if (!ts.moved && ts.active && !holdActive) {
      dragMode = true;
      send({action:'mouse_down', button:'left'});
      touchpad.style.borderColor = '#ef4444';
      indicator.style.borderColor = 'rgba(239,68,68,0.7)';
      indicator.style.background = 'rgba(239,68,68,0.2)';
      // 同步更新按钮状态
      holdActive = true;
      const bh = document.getElementById('btn-hold');
      bh.classList.add('active');
      bh.textContent = '🔴 松开左键';
      toast('拖拽模式 — 滑动拖拽，松手结束');
    }
  }, 500);
}, {passive: false});

touchpad.addEventListener('touchmove', (e) => {
  e.preventDefault();
  if (!ts.active) return;
  const t = e.touches[0];
  const dx = t.clientX - ts.lastX;
  const dy = t.clientY - ts.lastY;
  const totalDist = Math.abs(t.clientX - ts.startX) + Math.abs(t.clientY - ts.startY);

  // 移动超过 5px 取消长按（视为滑动而非长按）
  if (totalDist > 5) {
    ts.moved = true;
    clearTimeout(dragTimer);
  }

  if (Math.abs(dx) > 0.01 || Math.abs(dy) > 0.01) {
    const rect = touchpad.getBoundingClientRect();
    indicator.style.left = (t.clientX - rect.left) + 'px';
    indicator.style.top = (t.clientY - rect.top) + 'px';
    indicator.style.opacity = '1';

    if (e.touches.length >= 2) {
      flushMouseMove();
      send({action:'mouse_scroll', dy: Math.round(-dy * 3)});
    } else {
      sendMouseMove(dx, dy);
    }

    ts.lastX = t.clientX;
    ts.lastY = t.clientY;
  }
}, {passive: false});

touchpad.addEventListener('touchend', (e) => {
  e.preventDefault();
  clearTimeout(dragTimer);
  flushMouseMove();

  indicator.style.opacity = '0';
  indicator.style.borderColor = 'rgba(74,222,128,0.4)';
  indicator.style.background = 'rgba(74,222,128,0.15)';

  // 长按拖拽模式结束 → 松开鼠标
  if (dragMode) {
    send({action:'mouse_up', button:'left'});
    holdActive = false;
    dragMode = false;
    const bh = document.getElementById('btn-hold');
    bh.classList.remove('active');
    bh.textContent = '🔴 按住左键';
    toast('拖拽结束');
  }

  touchpad.style.borderColor = '#2a2a2a';
  ts.active = false;
}, {passive: false});

// ==================== 按钮 ====================
// 按住左键（切换按钮 — 对应需要多指协同的场景）
const btnHold = document.getElementById('btn-hold');
btnHold.addEventListener('click', () => {
  if (!holdActive) {
    send({action:'mouse_down', button:'left'});
    holdActive = true;
    btnHold.classList.add('active');
    btnHold.textContent = '🔴 松开左键';
    touchpad.style.borderColor = '#ef4444';
    toast('左键已按住 — 在触摸板上滑动拖拽');
  } else {
    send({action:'mouse_up', button:'left'});
    holdActive = false;
    dragMode = false;
    btnHold.classList.remove('active');
    btnHold.textContent = '🔴 按住左键';
    touchpad.style.borderColor = '#2a2a2a';
    toast('左键已松开');
  }
});

// 单击左键
document.getElementById('btn-left').addEventListener('click', ()=>{
  send({action:'mouse_click',button:'left'}); toast('左键单击');
});
// 右键
document.getElementById('btn-right').addEventListener('click', ()=>{
  send({action:'mouse_click',button:'right'}); toast('右键');
});
// 双击
document.getElementById('btn-dbclick').addEventListener('click', ()=>{
  send({action:'mouse_double_click',button:'left'}); toast('双击');
});

// ==================== 键盘 ====================
document.querySelectorAll('.key-btn[data-key]').forEach(btn => {
  btn.addEventListener('click', ()=> send({action:'key_press', key:btn.dataset.key}));
});
document.querySelectorAll('.key-btn[data-combo]').forEach(btn => {
  btn.addEventListener('click', ()=> send({action:'key_combo', keys:btn.dataset.combo.split(',')}));
});
document.getElementById('btn-send').addEventListener('click', ()=>{
  const text = document.getElementById('text-input').value;
  if (text) { send({action:'type_text', text}); toast('已发送'); document.getElementById('text-input').value = ''; }
});
document.getElementById('text-input').addEventListener('keydown', (e)=>{
  if (e.key==='Enter') { e.preventDefault(); document.getElementById('btn-send').click(); }
});

// ==================== 媒体 ====================
document.querySelectorAll('[data-media]').forEach(btn => {
  btn.addEventListener('click', ()=> send({action:'media', cmd:btn.dataset.media}));
});
document.getElementById('btn-vol-up').addEventListener('click', ()=> send({action:'volume_up'}));
document.getElementById('btn-vol-down').addEventListener('click', ()=> send({action:'volume_down'}));
document.getElementById('btn-mute').addEventListener('click', ()=> send({action:'volume_mute'}));

// ==================== 系统 ====================
document.querySelectorAll('[data-system]').forEach(btn => {
  btn.addEventListener('click', ()=>{
    const cmd = btn.dataset.system;
    if (cmd==='sleep') { if(confirm('确定休眠？')) send({action:'system',cmd}); }
    else send({action:'system',cmd});
  });
});

// ==================== 启动 ====================
connect();
</script>
</body>
</html>
"""

async def index(request: web.Request) -> web.Response:
    return web.Response(text=FULL_PAGE, content_type='text/html', charset='utf-8')

async def ping(request: web.Request) -> web.Response:
    return web.json_response({'status': 'ok', 'time': time.time()})

async def handle_cmd(request: web.Request) -> web.Response:
    """HTTP POST 命令接口 — 比 WebSocket 更可靠地穿透隧道"""
    try:
        data = await request.json()
        result = execute_command(data)
        return web.json_response(result)
    except json.JSONDecodeError:
        return web.json_response({'ok': False, 'error': 'invalid json'}, status=400)
    except Exception as e:
        return web.json_response({'ok': False, 'error': str(e)}, status=500)

async def handle_screen(request: web.Request) -> web.Response:
    """返回屏幕截图 JPEG，并在图上标注鼠标位置"""
    import io
    from PIL import ImageDraw
    try:
        img = pyautogui.screenshot()
        # 获取鼠标位置
        mx, my = pyautogui.position()
        sw, sh = img.size

        # 缩放到一半尺寸（加快传输）
        img_resized = img.resize((sw // 2, sh // 2))
        rmx = mx // 2
        rmy = my // 2

        # 在截图上画显眼的鼠标光标
        draw = ImageDraw.Draw(img_resized)
        r = 12  # 圆圈半径
        # 外圈（白色粗圈）
        draw.ellipse([rmx - r, rmy - r, rmx + r, rmy + r], outline='white', width=2)
        # 内圈（红色填充）
        draw.ellipse([rmx - r + 2, rmy - r + 2, rmx + r - 2, rmy + r - 2], outline='red', width=2)
        # 十字线
        draw.line([rmx, rmy - r - 4, rmx, rmy + r + 4], fill='red', width=2)
        draw.line([rmx - r - 4, rmy, rmx + r + 4, rmy], fill='red', width=2)
        # 中心点
        draw.ellipse([rmx - 2, rmy - 2, rmx + 2, rmy + 2], fill='cyan')

        buf = io.BytesIO()
        img_resized.save(buf, format='JPEG', quality=40)
        return web.Response(body=buf.getvalue(), content_type='image/jpeg')
    except Exception as e:
        return web.json_response({'ok': False, 'error': str(e)}, status=500)

# ==================== 主入口 ====================

def get_local_ips():
    """获取本机局域网 IP"""
    ips = []
    hostname = socket.gethostname()
    try:
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith('127.'):
                ips.append(ip)
    except:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        if ip not in ips:
            ips.append(ip)
    except:
        pass
    return list(set(ips))


def main():
    app = web.Application()
    app.router.add_get('/', index)
    app.router.add_get('/ping', ping)
    app.router.add_get('/screen.jpg', handle_screen)
    app.router.add_post('/cmd', handle_cmd)
    app.router.add_get('/ws', handle_ws)

    ips = get_local_ips()

    print()
    print("=" * 56)
    print("  🖥️  PC 远程控制服务器")
    print("=" * 56)
    print(f"  🔌 端口: {PORT}")
    print(f"  🖥️  屏幕: {pyautogui.size().width} × {pyautogui.size().height}")
    print()
    print("  🌐 局域网地址：")
    for i, ip in enumerate(sorted(ips), 1):
        print(f"     {i}. http://{ip}:{PORT}")
    print()
    print("  📱 同时启动内网穿透：")
    print(f"     npx --yes localtunnel --port {PORT}")
    print()
    print("  🔴 按 Ctrl+C 停止")
    print("-" * 56)
    print()

    web.run_app(app, host='0.0.0.0', port=PORT)


if __name__ == '__main__':
    main()
