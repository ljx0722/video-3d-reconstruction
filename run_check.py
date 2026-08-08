import subprocess, json, base64

gh = 'C:/Program Files/GitHub CLI/gh.exe'
repo = 'ljx0722/video-3d-reconstruction'

script = r"""name: Quick Deploy Check

on:
  workflow_dispatch:

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: azure/setup-kubectl@v4
        with:
          version: latest
      - name: Check
        run: |
          mkdir -p ~/.kube
          echo "${{ secrets.SEALOS_KUBECONFIG }}" | base64 -d > ~/.kube/config
          echo === All Deployments ===
          kubectl get deploy -n ns-mzyybqj8
          echo === All Pods ===
          kubectl get pods -n ns-mzyybqj8
          echo === All Services ===
          kubectl get svc -n ns-mzyybqj8
          echo === All Ingresses ===
          kubectl get ingress -n ns-mzyybqj8
          echo === Check for video-3d deploy ===
          kubectl describe deploy -n ns-mzyybqj8 --selector=cloud.sealos.io/app-deploy-manager=video-3d-reconstruction 2>/dev/null || echo no-matching
          echo === All Deployments with sealos labels ===
          kubectl get deploy -n ns-mzyybqj8 -o json 2>/dev/null | python3 -c "import json,sys; [print(d['metadata']['name'], d['metadata'].get('labels',{})) for d in json.load(sys.stdin)['items']]"
"""

content_b64 = base64.b64encode(script.encode()).decode()
result = subprocess.run([gh, 'api',
    'repos/ljx0722/video-3d-reconstruction/contents/.github/workflows/quick-check.yml',
    '-X', 'PUT',
    '-f', 'message=quick check',
    '-f', f'content={content_b64}',
], capture_output=True, text=True)
print(f'Update: {result.stdout[:200]}')

# Run workflow
result2 = subprocess.run([gh, 'workflow', 'run', 'quick-check.yml', '--repo', repo, '--ref', 'master'],
    capture_output=True, text=True)
print(f'Run: {result2.stdout.strip()}')
