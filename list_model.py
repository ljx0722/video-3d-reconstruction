import paramiko

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("connect.nmb2.seetacloud.com", port=10340, username="root", password="p4hbP7UoQzQ0", timeout=15)

# Write a Python script to the server
script = r"""
import urllib.request, json

# List model files
url = "https://hf-mirror.com/api/models/robbyant/lingbot-map"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
try:
    resp = urllib.request.urlopen(req, timeout=30)
    data = json.loads(resp.read())
    for sib in data.get("siblings", []):
        fname = sib.get("rfilename", "")
        size = sib.get("size", 0)
        if size > 1024 * 1024:
            print(f"{fname} - {size//(1024*1024)} MB")
        else:
            print(f"{fname} - {size//1024} KB")
except Exception as e:
    print("ERROR:", e)
    print("Trying direct HF API...")
    url2 = "https://huggingface.co/api/models/robbyant/lingbot-map"
    req2 = urllib.request.Request(url2, headers={"User-Agent": "Mozilla/5.0"})
    resp2 = urllib.request.urlopen(req2, timeout=30)
    data2 = json.loads(resp2.read())
    for sib in data2.get("siblings", []):
        fname = sib.get("rfilename", "")
        size = sib.get("size", 0)
        print(f"{fname} - {size//(1024*1024)} MB")
"""

# Upload the script
sftp = c.open_sftp()
with sftp.file("/root/list_files.py", "w") as f:
    f.write(script)
sftp.close()

# Run it
_, out, err = c.exec_command("/root/miniconda3/bin/python /root/list_files.py", timeout=30)
print(out.read().decode(errors="replace"))
err_out = err.read().decode(errors="replace")
if err_out.strip():
    print("STDERR:", err_out)

c.close()
