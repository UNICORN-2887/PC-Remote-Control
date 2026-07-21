"""
PC 远程控制 - 连通性测试服务器
在电脑上运行此脚本，然后用手机浏览器访问
"""
import http.server
import socket
import json
import os

# ==================== 配置 ====================
PORT = 5000  # 端口号，可自行修改

# ==================== 获取本机局域网 IP ====================
def get_local_ips():
    """获取本机所有局域网 IPv4 地址"""
    ips = []
    hostname = socket.gethostname()
    try:
        # 方法1：通过 hostname 解析
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith('127.'):
                ips.append(ip)
    except:
        pass

    # 方法2：通过连接外部地址获取
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

TEST_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>连接测试</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: #0f0f0f;
            color: #fff;
            display: flex; align-items: center; justify-content: center;
            min-height: 100vh;
            padding: 20px;
        }
        .card {
            background: #1a1a1a;
            border-radius: 20px;
            padding: 32px 28px;
            max-width: 400px;
            width: 100%;
            text-align: center;
            border: 2px solid #333;
        }
        .status { font-size: 64px; margin-bottom: 8px; }
        .title { font-size: 24px; font-weight: 700; margin-bottom: 6px; }
        .subtitle { color: #888; font-size: 14px; margin-bottom: 24px; }
        .info-row {
            display: flex; justify-content: space-between;
            background: #222; border-radius: 10px;
            padding: 12px 16px; margin-bottom: 8px;
            font-size: 14px;
        }
        .info-label { color: #888; }
        .info-value { color: #4ade80; font-weight: 600; word-break: break-all; text-align: right; }
        .pulse {
            display: inline-block; width: 12px; height: 12px;
            background: #4ade80; border-radius: 50%;
            animation: pulse 1.5s infinite;
            margin-right: 6px;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.4; transform: scale(1.3); }
        }
    </style>
</head>
<body>
    <div class="card">
        <div class="status">🎉</div>
        <div class="title">连接成功！</div>
        <div class="subtitle"><span class="pulse"></span>手机已成功连接到电脑</div>
        <div class="info-row">
            <span class="info-label">电脑名称</span>
            <span class="info-value" id="hostname">-</span>
        </div>
        <div class="info-row">
            <span class="info-label">客户端 IP</span>
            <span class="info-value" id="client">-</span>
        </div>
        <div class="info-row">
            <span class="info-label">User-Agent</span>
            <span class="info-value" id="ua" style="font-size:11px;">-</span>
        </div>
    </div>

    <script>
        // 每秒 ping 一次服务器，测试实时延迟
        async function ping() {
            const start = performance.now();
            await fetch('/ping');
            const ms = Math.round(performance.now() - start);
            document.getElementById('hostname').textContent =
                document.getElementById('hostname').textContent + ' | 延迟: ' + ms + 'ms';
        }
        setTimeout(ping, 500);
    </script>
</body>
</html>
"""

class TestHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"  📱 {self.client_address[0]} → {format % args}")

    def do_GET(self):
        if self.path == '/ping':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok'}).encode())
            return

        if self.path == '/' or self.path == '/index.html':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            # 动态填充本机信息
            page = TEST_PAGE
            page = page.replace('id="hostname">-', f'id="hostname">{socket.gethostname()}')
            page = page.replace('id="client">-', f'id="client">{self.client_address[0]}')
            self.wfile.write(page.encode())
            return

        self.send_response(404)
        self.end_headers()

if __name__ == '__main__':
    ips = get_local_ips()

    print()
    print("=" * 56)
    print("  📡 PC 远程控制 - 连通性测试服务器")
    print("=" * 56)
    print()
    print(f"  🖥️  电脑名称: {socket.gethostname()}")
    print(f"  🔌 监听端口: {PORT}")
    print()
    print("  📱 请在手机浏览器中输入以下任一地址：")
    print()
    for i, ip in enumerate(sorted(ips), 1):
        print(f"     {i}. http://{ip}:{PORT}")
    print()
    print("  ⚠️  确保手机和电脑连接的是同一个 WiFi/网络")
    print("  🔴 按 Ctrl+C 停止服务器")
    print("-" * 56)
    print()

    server = http.server.HTTPServer(('0.0.0.0', PORT), TestHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n  服务器已停止。")
        server.server_close()
