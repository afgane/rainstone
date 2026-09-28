#!/usr/bin/env bash
# Package a Rainstone chart into a checkout of CloudVE/helm-charts and index it.
#
#   scripts/publish_chart.sh CHART_DIR HELM_CHARTS_DIR
#
# The chart version is not bumped yet, so publishing replaces the package and
# index entry for the same version rather than adding one. `helm repo index
# --merge` keeps an existing entry for a version it already lists, digest
# included, so the old entry is removed before merging. Prints "unchanged" and
# leaves the checkout untouched when the chart's contents are the same as the
# published package; otherwise prints the package name. Committing and pushing
# are left to the caller.
set -euo pipefail

chart_dir=$(cd "$1" && pwd)
repo_dir=$(cd "$2" && pwd)
name=$(yq '.name' "$chart_dir/Chart.yaml")
version=$(yq '.version' "$chart_dir/Chart.yaml")
package="$name-$version.tgz"

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

helm package "$chart_dir" --destination "$work" >/dev/null

# Packages carry build timestamps, so compare what they contain instead.
if [[ -f "$repo_dir/$package" ]]; then
  mkdir "$work/old" "$work/new"
  tar -xzf "$repo_dir/$package" -C "$work/old"
  tar -xzf "$work/$package" -C "$work/new"
  if diff -r "$work/old" "$work/new" >/dev/null; then
    echo unchanged
    exit 0
  fi
fi

cp "$work/$package" "$repo_dir/$package"
cd "$repo_dir"
yq -i "del(.entries.\"$name\"[] | select(.version == \"$version\"))" index.yaml
yq -i "del(.entries.\"$name\" | select(length == 0))" index.yaml
TZ=UTC helm repo index . --merge index.yaml 2>/dev/null
echo "$package"
