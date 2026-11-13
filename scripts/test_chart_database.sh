#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
values=(--set instance.slug=test --set auth.workspaceOwner=test
        --set database.storageClass=postgres-storage)
helm template rainstone "$root/chart" "${values[@]}" > "$work/standalone.yaml"
helm template rainstone "$root/chart" "${values[@]}" \
  --set database.provider=cnpg > "$work/cnpg.yaml"
helm template rainstone "$root/chart" "${values[@]}" \
  --set database.provider=cnpg \
  --set 'database.cnpg.plugins[0].name=cnpg-i-skip-initdb.leonardoce.github.com' \
  > "$work/restore.yaml"
helm template rainstone "$root/chart" "${values[@]}" \
  --set database.provider=cnpg --set database.existingSecret=external \
  > "$work/external.yaml"

for mode in standalone cnpg restore external; do
  yq eval-all -o=json '. as $document ireduce ([]; . + [$document])' \
    "$work/$mode.yaml" > "$work/$mode-array.yaml"
done
check() {
  jq -e "$2" "$work/$1-array.yaml" >/dev/null
}
check standalone '[.[] | select(.kind == "StatefulSet")] | length == 1'
check standalone '[.[] | select(.kind == "Cluster")] | length == 0'
check cnpg '[.[] | select(.kind == "StatefulSet" or .kind == "PersistentVolumeClaim")] | length == 0'
check cnpg '[.[] | select(.kind == "Cluster")][0] | .metadata.name == "rainstone-postgres" and .spec.instances == 1 and .spec.enableSuperuserAccess == false and .spec.bootstrap.initdb.secret.name == "rainstone-postgres-credentials" and .spec.storage.storageClass == "postgres-storage"'
check cnpg '[.[] | select(.kind == "Secret" and .metadata.name == "rainstone-postgres-credentials")][0] | .type == "kubernetes.io/basic-auth" and .stringData.username == "rainstone" and (.stringData.dsn | contains("@rainstone-postgres-rw:5432/rainstone")) and .metadata.labels."cnpg.io/reload" == "true"'
check restore '[.[] | select(.kind == "Cluster")][0].spec.plugins[0].name == "cnpg-i-skip-initdb.leonardoce.github.com"'
check external '[.[] | select(.kind == "Cluster" or .kind == "StatefulSet" or (.kind == "Secret" and .metadata.name == "rainstone-postgres-credentials"))] | length == 0'
if helm template rainstone "$root/chart" "${values[@]}" \
  --set database.provider=unknown > /dev/null 2>&1; then
  echo 'An unknown database provider was accepted.' >&2
  exit 1
fi
if helm template rainstone "$root/chart" "${values[@]}" \
  --set database.provider=cnpg --set database.storageClass= > /dev/null 2>&1; then
  echo 'CNPG accepted unacknowledged ephemeral storage.' >&2
  exit 1
fi
echo 'Database chart: standalone, CNPG, restore, external and invalid settings passed.'
