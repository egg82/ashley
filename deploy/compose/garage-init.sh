#!/bin/sh
# Gives a fresh one-node Garage a layout, the bucket and the app's key. Every step is safe to repeat.
set -eu
API=http://garage:3903/v2
AUTH="Authorization: Bearer ${GARAGE_ADMIN_TOKEN}"
JSON="Content-Type: application/json"

call() { curl -sS -H "$AUTH" -H "$JSON" "$@"; }

# /health stays red until a layout exists, so wait on the admin API instead.
for _ in $(seq 1 60); do
  call -f "$API/GetClusterStatus" >/dev/null 2>&1 && break
  sleep 2
done
call -f "$API/GetClusterStatus" >/dev/null || { echo "garage-init: admin API unreachable (is GARAGE_ADMIN_TOKEN set?)" >&2; exit 1; }

node=$(call "$API/GetClusterStatus" | sed -n 's/.*"id": *"\([0-9a-f]\{64\}\)".*/\1/p' | head -n 1)
[ -n "$node" ] || { echo "garage-init: no node id (is GARAGE_ADMIN_TOKEN set?)" >&2; exit 1; }

if call "$API/GetClusterLayout" | grep -q "\"id\": *\"$node\""; then
  echo "garage-init: layout already has the node"
else
  call -X POST "$API/UpdateClusterLayout" \
    -d "{\"roles\":[{\"id\":\"$node\",\"zone\":\"home\",\"capacity\":1000000000,\"tags\":[]}]}" >/dev/null
  version=$(call "$API/GetClusterLayout" | sed -n 's/.*"version": *\([0-9]*\).*/\1/p' | head -n 1)
  call -X POST "$API/ApplyClusterLayout" -d "{\"version\":$((version + 1))}" >/dev/null
  echo "garage-init: layout applied"
fi

call -X POST "$API/CreateBucket" -d "{\"globalAlias\":\"$FILES_BUCKET\"}" >/dev/null || true
bucket=$(call "$API/GetBucketInfo?globalAlias=$FILES_BUCKET" | sed -n 's/^ *"id": *"\([0-9a-f]*\)".*/\1/p' | head -n 1)
[ -n "$bucket" ] || { echo "garage-init: bucket $FILES_BUCKET missing" >&2; exit 1; }

call -X POST "$API/ImportKey" \
  -d "{\"name\":\"ashley\",\"accessKeyId\":\"$FILES_ACCESS_KEY\",\"secretAccessKey\":\"$FILES_SECRET_KEY\"}" >/dev/null || true
call -X POST "$API/AllowBucketKey" \
  -d "{\"bucketId\":\"$bucket\",\"accessKeyId\":\"$FILES_ACCESS_KEY\",\"permissions\":{\"read\":true,\"write\":true,\"owner\":false}}" >/dev/null
echo "garage-init: bucket $FILES_BUCKET ready"
