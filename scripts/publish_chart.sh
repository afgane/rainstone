#!/usr/bin/env bash
# Package a Rainstone chart into a checkout of CloudVE/helm-charts and index it.
#
#   scripts/publish_chart.sh CHART_DIR HELM_CHARTS_DIR
#
# Prints "unchanged" when the contents match an existing version. Changed
# contents require a new version, so a published package is never replaced.
# Otherwise prints the new package name. Committing and pushing are left
# to the caller.
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
  echo "Chart $name $version is already published with different contents; bump the chart version." >&2
  exit 1
fi

cp "$work/$package" "$repo_dir/$package"
cd "$repo_dir"
TZ=UTC helm repo index . --merge index.yaml 2>/dev/null
echo "$package"
