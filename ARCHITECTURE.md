# 架构原理

## 整体架构

```
┌──────────────────────────────────────────────────────────────────┐
│                         PC Remote Control                        │
│                                                                  │
│  📱 手机浏览器               🌐 公网                 💻 PC        │
│  ┌────────────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │                │    │              │    │   server.py      │  │
│  │  控制面板 UI   │◀──▶│ localtunnel  │◀──▶│   aiohttp :5000  │  │
│  │  (HTML/CSS/JS) │    │  内网穿透     │    │                  │  │
│  │                │    │              │    │   ┌────────────┐  │  │
│  │  🖱️ 触摸板     │    └──────────────┘    │   │ pyautogui  │  │  │
│  │  ⌨️ 键盘       │                        │   │            │  │  │
│  │  🎵 媒体       │                        │   │ moveRel()  │  │  │
│  │  ⚙️ 系统       │                        │   │ click()    │  │  │
│  │  🖥️ 屏幕       │                        │   │ press()    │  │  │
│  │                │                        │   │ screenshot │  │  │
│  └────────────────┘                        │   └────────────┘  │  │
│                                            └──────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

## 数据流

### 命令通道（手机 → PC）

```
用户操作（触摸/点击）
    │
    ▼
JavaScript 事件监听器
    │
    ├── 鼠标移动 ──▶ WebSocket ──▶ 低延迟，60fps 批量发送
    │
    └── 其他操作 ──▶ HTTP POST ──▶ 高可靠，穿透隧道不丢包
                            │
                            ▼
                    Python execute_command()
                            │
                            ▼
                       pyautogui
                    (鼠标/键盘/系统)
```

**为什么双通道？**

| 通道 | 协议 | 适用场景 | 原因 |
|------|------|----------|------|
| WebSocket | 全双工长连接 | 鼠标移动（高频） | 延迟低，无需重复建立连接 |
| HTTP POST | 请求-响应 | 点击、按键、系统命令（低频） | localtunnel 对 HTTP 转发最稳定 |

### 鼠标移动优化

手机触摸屏 `touchmove` 事件以 ~60Hz 触发。如果每次事件都直接发送：

```
❌ 不加优化：60次/秒 × WebSocket send = 消息风暴，卡顿
```

实际实现：

```
✅ 前端缓冲合并：
   touchmove → 累加 dx, dy 到 buffer
             → 每 16ms flush 一次
             → 合并后的位移一次性发送
   
   60 fps 事件 → 约 60 次/秒 WebSocket 发送
   但每次发送的是累积值，实际效果流畅
```

```javascript
// 前端关键代码
let pendingDx = 0, pendingDy = 0;
let flushTimer = null;

function sendMouseMove(dx, dy) {
  pendingDx += dx;
  pendingDy += dy;
  if (!flushTimer) {
    flushTimer = setTimeout(flushMouseMove, 16);  // 16ms 窗口
  }
}

function flushMouseMove() {
  flushTimer = null;
  const dx = pendingDx, dy = pendingDy;
  pendingDx = 0; pendingDy = 0;
  if (wsReady) {
    ws.send(JSON.stringify({action:'mouse_move', dx:Math.round(dx), dy:Math.round(dy)}));
  }
}
```

### 画面通道（PC → 手机）

```
定时器触发（每 1.5 秒）
    │
    ▼
pyautogui.screenshot()
    │
    ▼
Pillow: 缩放到 50% + JPEG 质量 40%
    │
    ▼
ImageDraw: 在图上绘制鼠标光标指示器
    │  ├── 白色外圈（可见性）
    │  ├── 红色十字线（定位）
    │  └── 青色中心点（精确）
    ▼
HTTP Response (image/jpeg)
    │
    ▼
手机 <img> 标签显示
```

**优化策略**：
- **缩放 50%**：1920×1080 → 960×540，减少 75% 像素
- **JPEG Q40**：单帧 ~50KB（原始 BMP ~2MB）
- **惰性传输**：仅「屏幕」标签激活时才请求
- **缓存破坏**：URL 加时间戳 `?timestamp` 防止浏览器缓存旧图

## 触摸板交互设计

### 手势模型

```
单指滑动        → 移动光标（WebSocket 发送 moveRel）
    │
单指长按 0.5s   → 进入拖拽模式（mouseDown）
    │               │
    │               └→ 滑动 → 拖拽中（moveRel，左键保持按下）
    │               └→ 松手 → 结束拖拽（mouseUp）
    │
双指滑动        → 滚轮滚动（mouse_scroll）
```

### 为什么触摸板不自动触发点击？

早期的设计在触摸板短按自动触发左键单击，但带来两个问题：

1. **误触**：手指放上去准备滑动时可能触发意外点击
2. **拖拽冲突**：无法区分"按住不动想拖拽"和"只是手指累了停顿"

最终设计：触摸板 = 纯光标移动，点击由独立按钮控制。拖拽用长按手势或切换按钮触发。

### 拖拽的两种方式

| 方式 | 操作 | 原理 |
|------|------|------|
| **长按拖拽** | 触摸板长按 0.5s → 滑动 → 松手 | mouseDown → moveRel → mouseUp |
| **按钮拖拽** | 点「按住左键」→ 滑动 → 再点松开 | 切换式 mouseDown/mouseUp |

长按检测：`touchstart` 启动 500ms 计时器，如果期间手指移动超过 5px 则取消（认为是正常滑动）。

## 通信协议

### HTTP POST `/cmd`

所有命令通过 JSON body 发送：

```json
// 鼠标移动
{"action": "mouse_move", "dx": 10, "dy": -5}

// 鼠标点击
{"action": "mouse_click", "button": "left"}    // left | right | middle
{"action": "mouse_double_click", "button": "left"}

// 鼠标按键（拖拽用）
{"action": "mouse_down", "button": "left"}
{"action": "mouse_up", "button": "left"}

// 滚轮
{"action": "mouse_scroll", "dy": -3}           // 正=上滚 负=下滚

// 键盘
{"action": "key_press", "key": "enter"}        // 单个按键
{"action": "key_combo", "keys": ["ctrl", "c"]} // 组合键
{"action": "type_text", "text": "你好世界"}     // 文本输入

// 媒体
{"action": "volume_up"}
{"action": "volume_down"}
{"action": "volume_mute"}
{"action": "media", "cmd": "play_pause"}       // play_pause | next | prev | stop

// 系统
{"action": "system", "cmd": "lock"}            // lock | sleep | show_desktop | task_view | start_menu
```

### WebSocket `/ws`

用于双向实时通信：

**手机 → PC**：发送命令（格式同 HTTP，额外支持 `ping`）

```json
{"action": "ping", "sent": 1721556789123}
{"action": "mouse_move", "dx": 10, "dy": -5}
```

**PC → 手机**：状态推送

```json
{"type": "pong", "sent": 1721556789123}         // 心跳响应（计算延迟）
{"type": "screen", "width": 1920, "height": 1080} // 屏幕尺寸（连接时发送）
```

### HTTP GET `/screen.jpg`

返回当前屏幕截图的 JPEG 图像（含鼠标标注），约 50KB。

## PC 控制层

### pyautogui 操作映射

| 命令 | pyautogui 调用 | 说明 |
|------|---------------|------|
| mouse_move | `moveRel(dx*sensitivity, dy*sensitivity)` | 相对位移，支持灵敏度调节 |
| mouse_click | `click(button=...)` | 单击 |
| mouse_double_click | `doubleClick(button=...)` | 双击 |
| mouse_down/up | `mouseDown()` / `mouseUp()` | 按住/松开，实现拖拽 |
| mouse_scroll | `scroll(amount)` | 滚轮，正=上 |
| key_press | `press(key)` | 单键 |
| key_combo | `hotkey(*keys)` | 组合键 |
| type_text | `write(text)` / 剪贴板粘贴 | ASCII 直接输入，中文走 Ctrl+V |
| volume_* | `press('volumeup'/'volumedown'/'volumemute')` | Windows 媒体键 |
| media | `press('playpause'/'nexttrack'/'prevtrack')` | Windows 媒体键 |
| system: lock | `rundll32.exe user32.dll,LockWorkStation` | 调用 Windows API |
| system: sleep | `rundll32.exe powrprof.dll,SetSuspendState` | 调用 Windows API |
| system: show_desktop | `hotkey('win', 'd')` | Win+D |
| system: task_view | `hotkey('win', 'tab')` | Win+Tab |

### 安全机制

```python
pyautogui.FAILSAFE = True   # 鼠标移到屏幕左上角 (0,0) 时立即中止
pyautogui.PAUSE = 0         # 关闭默认延迟，WebSocket 已有流控
```

## 内网穿透

### 为什么需要内网穿透？

校园网/公司网络通常启用了 **AP 隔离**（客户端隔离），同一 WiFi 下的设备无法互相通信。localtunnel 通过公网服务器中转，绕过此限制。

### 连接建立过程

```
1. PC 启动 server.py (localhost:5000)
2. PC 启动 localtunnel，连接到 localtunnel 服务器
3. localtunnel 分配一个公网子域名: https://xxx.loca.lt
4. localtunnel 服务器建立隧道: xxx.loca.lt → PC:5000
5. 手机访问 https://xxx.loca.lt
6. 首次访问需验证 IP（人机验证，防滥用）
7. 之后正常使用，所有 HTTP/WS 请求透明转发
```

### 延迟分析

```
手机 → localtunnel 服务器 → PC     往返延迟 ~100-300ms（取决于网络）
PC → pyautogui 执行                 < 1ms
PC 截图 → localtunnel → 手机         ~100-500ms（取决于图片大小）
```

## 前端技术细节

### 响应式触摸处理

```javascript
// 防止浏览器默认行为（滚动、缩放）
touchpad.addEventListener('touchstart', e => e.preventDefault(), {passive: false});
touchpad.addEventListener('touchmove',  e => e.preventDefault(), {passive: false});
touchpad.addEventListener('touchend',  e => e.preventDefault(), {passive: false});

// CSS 层面
body { touch-action: none; }          // 禁止浏览器手势
#touchpad { touch-action: none; }     // 触摸板区域专属控制
```

### 状态管理

- `wsReady`：WebSocket 连接状态（影响鼠标移动通道选择）
- `holdActive`：左键是否被按住（影响按钮显示 + 触摸板样式）
- `dragMode`：触摸板长按拖拽模式（松手时自动 mouseUp）
- `pendingDx/pendingDy`：鼠标移动缓冲区

### 屏幕流生命周期

```
切换到「屏幕」标签 → startScreenStream()
    ├── 立即请求一帧 refreshScreen()
    └── setInterval(refreshScreen, 1500)

切换离开「屏幕」标签 → stopScreenStream()
    └── clearInterval()
```

这样切换到其他标签时不会浪费带宽请求截图。
