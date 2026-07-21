"""
PC 远程控制 - 启动器
自动启动服务器 + 内网穿透，显示公网地址
"""
import subprocess
import sys
import time
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

print("=" * 56)
print("  PC Remote Control - Launcher")
print("=" * 56)
print()

# 1. 启动服务器
print("[1/2] Starting server...")
server_proc = subprocess.Popen(
    [sys.executable, "-u", "server.py"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
)
time.sleep(3)
print("       Server running on http://localhost:5000")
print()

# 2. 启动 localtunnel
print("[2/2] Starting tunnel...")
print("       Waiting for public URL...")
print()

tunnel_proc = subprocess.Popen(
    "npx --yes localtunnel --port 5000",
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    text=True, encoding="utf-8", shell=True
)

# 读取 tunnel 输出，提取 URL
try:
    for line in tunnel_proc.stdout:
        line = line.strip()
        if line:
            print(f"       {line}")
        if "your url is:" in line.lower():
            url = line.split("your url is:")[-1].strip()
            print()
            print("=" * 56)
            print(f"  OPEN THIS ON YOUR PHONE:")
            print(f"  >>> {url} <<<")
            print("=" * 56)
            print()
            print("  Press Ctrl+C to stop.")
            break

    # 继续显示后续输出
    for line in tunnel_proc.stdout:
        pass

except KeyboardInterrupt:
    pass
finally:
    print()
    print("Shutting down...")
    server_proc.terminate()
    tunnel_proc.terminate()
    print("Stopped.")
