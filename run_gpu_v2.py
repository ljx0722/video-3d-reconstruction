import paramiko, os

HOST = "connect.nmb2.seetacloud.com"
PORT = 10340
USER = "root"
PASSWORD = "p4hbP7UoQzQ0"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
print("Connecting...")
client.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=30)
print("Connected!")

# Upload shell script
sftp = client.open_sftp()
local_script = os.path.join(os.path.dirname(__file__), "gpu_setup.sh")
sftp.put(local_script, "/root/gpu_setup.sh")
sftp.close()
print("Script uploaded!")

# Run it
print("\n=== Running setup ===\n")
chan = client.get_transport().open_session()
chan.settimeout(900)
chan.exec_command("bash /root/gpu_setup.sh")

# Stream output
buf = b""
while True:
    try:
        data = chan.recv(4096)
        if not data:
            break
        buf += data
        text = data.decode(errors="replace")
        print(text, end="", flush=True)
    except Exception:
        break

exit_code = chan.recv_exit_status()
print(f"\n[exit={exit_code}]")

# Wait a few seconds and check worker status
import time
time.sleep(5)
chan2 = client.get_transport().open_session()
chan2.settimeout(10)
chan2.exec_command("ps aux | grep gpu_server | grep -v grep; echo '---'; tail -20 /root/gpu_worker.log 2>/dev/null || echo 'no log'")
status_out = chan2.makefile().read().decode(errors="replace")
print("\n=== Worker status ===")
print(status_out)

client.close()
print("\n=== DONE ===")
