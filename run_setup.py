import paramiko

HOST = "connect.nmb2.seetacloud.com"
PORT = 10340
USER = "root"
PASSWORD = "p4hbP7UoQzQ0"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
print("Connecting...")
client.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=30)
print("Connected!")

# Upload the shell script
sftp = client.open_sftp()
sftp.put(
    r"e:\个人\建模类\视频重建作品\video-3d-reconstruction\gpu_setup.sh",
    "/root/gpu_setup.sh",
)
sftp.close()
print("Script uploaded")

# Execute
print("\n=== Running setup ===\n")
stdin, stdout, stderr = client.exec_command("bash /root/gpu_setup.sh", timeout=900)
out = stdout.read().decode(errors="replace")
err = stderr.read().decode(errors="replace")
print(out)
if err and err.strip():
    print("STDERR:", err[-500:])

print("\nExit code:", stdout.channel.recv_exit_status())
print("=== COMPLETE ===")
# Show fresh log after 10s
import time
time.sleep(10)
stdin2, stdout2, stderr2 = client.exec_command("tail -20 /root/gpu_worker.log", timeout=10)
print("Final log:", stdout2.read().decode(errors="replace"))

client.close()
