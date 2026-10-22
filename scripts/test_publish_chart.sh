#!/usr/bin/env bash
# Exercise new versions, replay and overwrite refusal without a remote push.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
cp -R "$root/chart" "$work/chart"
mkdir "$work/repository"
helm repo index "$work/repository"
version=$(yq '.version' "$work/chart/Chart.yaml")
package="rainstone-$version.tgz"
first=$("$root/scripts/publish_chart.sh" "$work/chart" "$work/repository")
[[ "$first" == "$package" ]]
cp "$work/repository/$package" "$work/original.tgz"
cp "$work/repository/index.yaml" "$work/original-index.yaml"
[[ $("$root/scripts/publish_chart.sh" "$work/chart" "$work/repository") == unchanged ]]
cmp "$work/repository/index.yaml" "$work/original-index.yaml"
printf '\n# Changed chart contents\n' >> "$work/chart/values.yaml"
if "$root/scripts/publish_chart.sh" "$work/chart" "$work/repository" > "$work/output" 2> "$work/error"; then
  echo 'Publisher accepted changed contents under an existing version.' >&2
  exit 1
fi
grep -q 'bump the chart version' "$work/error"
cmp "$work/repository/$package" "$work/original.tgz"
cmp "$work/repository/index.yaml" "$work/original-index.yaml"
yq -i '.version = "99.0.0"' "$work/chart/Chart.yaml"
[[ $("$root/scripts/publish_chart.sh" "$work/chart" "$work/repository") == rainstone-99.0.0.tgz ]]
[[ $(yq '.entries.rainstone | length' "$work/repository/index.yaml") == 2 ]]
cmp "$work/repository/$package" "$work/original.tgz"
echo 'Chart publication: new version, replay, overwrite refusal and retained history passed.'
