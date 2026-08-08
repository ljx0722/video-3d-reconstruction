import os

path = r'e:\个人\建模类\视频重建作品\video-3d-reconstruction\.github\workflows\check-schema.yml'

# Use chr(36) for $ and chr(123) for { and chr(125) for } to avoid bash issues
S = chr(36)  # $
OB = chr(123)  # {
CB = chr(125)  # }

content = f"""name: Check Sealos App Schema

on:
  workflow_dispatch:

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: azure/setup-kubectl@v4
        with:
          version: latest
      - name: Config
        run: |
          mkdir -p ~/.kube
          echo "{S}{OB}{OB} secrets.SEALOS_KUBECONFIG {CB}{CB}" | base64 -d > ~/.kube/config
      - name: Check
        run: |
          echo === App CRD ===
          kubectl get crd apps.app.sealos.io -o yaml 2>/dev/null | head -200
          echo === Instance CRD ===
          kubectl get crd instances.app.sealos.io -o yaml 2>/dev/null | head -200
          echo === Gesture deployment ===
          kubectl get deployment gesture-island -n ns-mzyybqj8 -o yaml 2>/dev/null | head -60
          echo === Our Ingress ===
          kubectl get ingress video2gauss -n ns-mzyybqj8 -o yaml 2>/dev/null
          echo === DNS ===
          nslookup video2gauss.sealoshzh.site 2>/dev/null || echo dns-fail
"""

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Written")
